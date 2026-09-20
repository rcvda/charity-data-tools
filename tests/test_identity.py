"""Unit tests — all HTTP mocked; no live network, no real key."""
import csv
import pytest

from charity_data_tools.ftc.extract import extract_identifiers
from charity_data_tools.ch.client import CHClient, CHKeyMissing, orgid_from_company_number
from charity_data_tools.identity import cascade


def test_extract_identifiers_full():
    rec = {
        "orgIDs": ["GB-COH-08837451", "GB-CHC-1156300"],
        "charityNumber": "1156300",
        "companyNumber": "08837451",
        "organisationTypePrimary": "Registered Charity",
        "organisationType": ["Registered Charity", "Registered Company"],
        "linked_records": [{"orgid": "GB-SC-SC012345"}],
    }
    out = extract_identifiers(rec)
    assert out["org_ids"] == ["GB-COH-08837451", "GB-CHC-1156300", "GB-SC-SC012345"]
    assert out["charity_number"] == "1156300"
    assert out["company_number"] == "08837451"
    assert out["org_type_primary"] == "Registered Charity"
    assert "Registered Company" in out["org_types"]


def test_extract_identifiers_empty():
    out = extract_identifiers({})
    assert out["org_ids"] == [] and out["company_number"] == ""


def test_orgid_from_company_number():
    assert orgid_from_company_number("08668189") == "GB-COH-08668189"
    assert orgid_from_company_number("") is None


def test_ch_key_missing(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    with pytest.raises(CHKeyMissing):
        CHClient()


def test_ch_key_from_env(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "dummy")
    c = CHClient()
    assert "dummy" not in repr(c)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
    def json(self):
        return self._p


class _Sess:
    def __init__(self, payload):
        self._p = payload
        self.last_auth = None
    def get(self, url, params=None, auth=None, timeout=None):
        self.last_auth = auth
        return _Resp(200, self._p)
    def close(self):
        pass


def test_ch_search_parses_and_authenticates():
    sess = _Sess({"items": [{"company_number": "08668189", "title": "ACME LTD",
                             "company_status": "active", "company_type": "ltd",
                             "address_snippet": "1 High St"}]})
    c = CHClient(api_key="k", session=sess)
    out = c.search_companies("ACME")
    assert out[0]["company_number"] == "08668189"
    assert sess.last_auth == ("k", "")


class FakeFTC:
    def __init__(self, by_type, orgs, aliases=None):
        self.by_type = by_type
        self.orgs = orgs
        self.aliases = aliases or {}
    def search_all(self, names, type_filter=None):
        table = self.by_type.get(type_filter, {})
        return {n: table.get(n) for n in names}
    def fetch_org(self, orgid):
        return (self.orgs.get(orgid), None) if orgid in self.orgs else (None, "404")
    def alt_names_for(self, orgid):
        return self.aliases.get(orgid, [])


class FakeCH:
    def __init__(self, table):
        self.table = table
    def search_companies(self, q, items=5):
        return self.table.get(q, [])


def test_stage1_deterministic():
    ftc = FakeFTC({}, {"GB-CHC-279000": {"orgIDs": ["GB-CHC-279000"],
                                         "organisationTypePrimary": "Registered Charity"}})
    res = cascade.resolve_names(["Tree Council"], ftc,
                                held={"Tree Council": {"charity_number": "279000"}})
    assert res[0]["source_stage"] == "stage1" and res[0]["org_id"] == "GB-CHC-279000"


def test_stage3_typed_auto():
    ftc = FakeFTC(
        {"local-authority": {"Ashvale and Dale Borough Council":
            {"verdict": "auto", "orgid": "GB-LAE-RCC", "name": "Ashvale and Dale",
             "ftc_url": "u", "score": 100}}},
        {"GB-LAE-RCC": {"orgIDs": ["GB-LAE-RCC"], "organisationTypePrimary": "Local Authority"}})
    res = cascade.resolve_names(["Ashvale and Dale Borough Council"], ftc)
    assert res[0]["source_stage"] == "stage3" and res[0]["org_id"] == "GB-LAE-RCC"


def test_stage4_companies_house_auto():
    ftc = FakeFTC({}, {"GB-COH-01234567": {"orgIDs": ["GB-COH-01234567"]}})
    ch = FakeCH({"Ryder Architects Ltd": [{"company_number": "01234567",
                 "title": "Ryder Architects Ltd", "company_status": "active"}]})
    res = cascade.resolve_names(["Ryder Architects Ltd"], ftc, ch=ch)
    assert res[0]["source_stage"] == "stage4" and res[0]["org_id"] == "GB-COH-01234567"


def test_no_match_is_review_not_dropped():
    ftc = FakeFTC({}, {})
    res = cascade.resolve_names(["Totally Unknown Body"], ftc)
    assert len(res) == 1 and res[0]["org_id"] == ""


def test_write_review_csv(tmp_path):
    ftc = FakeFTC({}, {})
    res = cascade.resolve_names(["A", "B"], ftc)
    p = tmp_path / "review.csv"
    cascade.write_review_csv(res, str(p))
    rows = list(csv.DictReader(open(p)))
    assert len(rows) == 2 and "confirmed_org_id" in rows[0]


def test_classify_company_suffix_aware():
    active = {"title": "WB CONSTRUCTION LTD", "company_status": "active"}
    assert cascade.classify_company(active, "WB Construction") == "auto"
    assert cascade.classify_company({"title": "HITACHI ENERGY UK LIMITED", "company_status": "active"},
                                    "Hitachi Energy") == "auto"
    assert cascade.classify_company({"title": "WB CONSTRUCTION LTD", "company_status": "dissolved"},
                                    "WB Construction") == "review"
    assert cascade.classify_company({"title": "RYDER IRLAM ARCHITECTS LTD", "company_status": "active"},
                                    "Ryder Architects") == "review"


def test_stage3_review_noise_is_dropped():
    # No shared real tokens (Beacon absent from candidate; overlap 0.33) → dropped.
    ftc = FakeFTC(
        {"community-interest-company": {"Beacon Mines":
            {"verdict": "review_low", "orgid": "GB-CHC-1083008",
             "name": "The Mines Advisory Group", "score": 30}}},
        {})
    res = cascade.resolve_names(["Beacon Mines"], ftc)
    assert res[0]["org_id"] == "" and res[0]["candidates"] == []


def test_stage3_single_token_containment_surfaced_as_review():
    # "Acme Group" (core {Acme}) is contained in the registered name but
    # carries only one distinctive token → surfaced as a review PROPOSAL, not auto.
    ftc = FakeFTC(
        {"registered-society": {"Acme Group":
            {"verdict": "review_high", "orgid": "GB-MPR-7522",
             "name": "Acme Housing Group Limited", "ftc_url": "u", "score": 92}}},
        {"GB-MPR-7522": {"orgIDs": ["GB-MPR-7522"],
                         "organisationTypePrimary": "Registered Society"}})
    res = cascade.resolve_names(["Acme Group"], ftc)
    assert res[0]["confidence"] == "review"
    assert res[0]["org_id"] == "GB-MPR-7522"
    assert res[0]["source_stage"] == "stage3"


def test_stage3_multitoken_containment_auto():
    # "North East Migration Partnership" (>=2 distinctive tokens) fully contained
    # in the registered name → auto-accepted.
    ftc = FakeFTC(
        {"government-organisation": {"North East Migration Partnership":
            {"verdict": "review_high", "orgid": "GB-GOVUK-nemp",
             "name": "North East Strategic Migration Partnership", "ftc_url": "u", "score": 88}}},
        {"GB-GOVUK-nemp": {"orgIDs": ["GB-GOVUK-nemp"],
                           "organisationTypePrimary": "Government Organisation"}})
    res = cascade.resolve_names(["North East Migration Partnership"], ftc)
    assert res[0]["confidence"] == "auto"
    assert res[0]["org_id"] == "GB-GOVUK-nemp"


def test_stage3_partial_overlap_surfaced_as_review():
    # Not contained, but strong token overlap (>=0.5) → review proposal, not dropped.
    ftc = FakeFTC(
        {"registered-society": {"Coast Community Housing":
            {"verdict": "review_high", "orgid": "GB-MPR-9999",
             "name": "Coast & Country Housing", "ftc_url": "u", "score": 80}}},
        {"GB-MPR-9999": {"orgIDs": ["GB-MPR-9999"],
                         "organisationTypePrimary": "Registered Society"}})
    res = cascade.resolve_names(["Coast Community Housing"], ftc)
    assert res[0]["confidence"] == "review" and res[0]["org_id"] == "GB-MPR-9999"


def test_stage3_brand_resolves_via_alias():
    # Query is a BRAND ("Harbour Supported Living"); the reconcile candidate's
    # primary name is the parent ("Harbour Housing Association") which the query
    # is NOT contained in — but the brand IS an FTC alias of the parent, so
    # alias cross-referencing resolves it (>=2 tokens contained in alias → auto).
    ftc = FakeFTC(
        {"registered-society": {"Harbour Supported Living":
            {"verdict": "review_high", "orgid": "GB-MPR-19059R",
             "name": "Harbour Housing Association", "ftc_url": "u", "score": 78}}},
        {"GB-MPR-19059R": {"orgIDs": ["GB-MPR-19059R"],
                           "organisationTypePrimary": "Registered Society"}},
        aliases={"GB-MPR-19059R": ["Harbour Supported Living", "Harbour Group"]})
    res = cascade.resolve_names(["Harbour Supported Living"], ftc)
    assert res[0]["confidence"] == "auto"
    assert res[0]["org_id"] == "GB-MPR-19059R"
    assert res[0]["matched_name"] == "Harbour Housing Association"


def test_stage4_upgrades_stage3_review_to_auto():
    # A single-token containment surfaces at Stage 3 as a review proposal; a
    # Companies House exact match then upgrades it to auto (CH wins).
    ftc = FakeFTC(
        {"registered-society": {"Acme":
            {"verdict": "review_high", "orgid": "GB-MPR-1", "name": "Acme Housing Society",
             "ftc_url": "u", "score": 80}}},
        {"GB-COH-01234567": {"orgIDs": ["GB-COH-01234567"]}})
    ch = FakeCH({"Acme": [{"company_number": "01234567",
                 "title": "Acme Ltd", "company_status": "active"}]})
    res = cascade.resolve_names(["Acme"], ftc, ch=ch)
    assert res[0]["confidence"] == "auto"
    assert res[0]["source_stage"] == "stage4" and res[0]["org_id"] == "GB-COH-01234567"
