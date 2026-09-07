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
    def __init__(self, by_type, orgs):
        self.by_type = by_type
        self.orgs = orgs
    def search_all(self, names, type_filter=None):
        table = self.by_type.get(type_filter, {})
        return {n: table.get(n) for n in names}
    def fetch_org(self, orgid):
        return (self.orgs.get(orgid), None) if orgid in self.orgs else (None, "404")


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
    ftc = FakeFTC(
        {"community-interest-company": {"Beacon Mines":
            {"verdict": "review_low", "orgid": "GB-CHC-1083008",
             "name": "The Mines Advisory Group", "score": 30}}},
        {})
    res = cascade.resolve_names(["Beacon Mines"], ftc)
    assert res[0]["org_id"] == "" and res[0]["candidates"] == []
