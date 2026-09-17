"""
Location / geography extractors for FTC org records, plus a location-scoped
candidate fetch.

FTC stores a ``location`` array on each ``/orgid/{id}.json`` record. Each entry
is tagged by ``type``:

    HQ   — the registered office (its ``geoCode`` is the org's home local
           authority; for CCEW/CCNI/OSCR charities the entry ``id`` is the
           registered postcode)
    AOO  — an area of operation / benefit the org itself declares

The public FTC REST API (``/api/v1/organisations``) does **not** filter by
location, so a location-scoped candidate list is obtained from the website's
CSV export instead (``/?location=<geocode>&filetype=csv``). That export returns
the *union* of orgs whose HQ is in the area OR which name it as an area of
benefit; use :func:`is_based_in` on each enriched record to keep only the ones
actually headquartered in the area.
"""

import csv
import io
from typing import Dict, List, Optional

import requests

FTC_BASE = "https://findthatcharity.uk"


def extract_locations(data: Dict) -> List[Dict[str, str]]:
    """Return the raw ``location`` array from an FTC record (or [])."""
    locs = data.get("location")
    return locs if isinstance(locs, list) else []


def extract_hq(data: Dict) -> Dict[str, str]:
    """Return the first HQ location entry from an FTC record, or {}.

    Falls back to {} when the record carries no HQ-typed location.
    """
    for loc in extract_locations(data):
        if isinstance(loc, dict) and (loc.get("type") or "").upper() == "HQ":
            return loc
    return {}


def extract_hq_geocode(data: Dict) -> str:
    """Return the ONS geo-code of the org's HQ (registered office), or ''.

    This is the authoritative 'based in' signal: it is the local-authority
    (or equivalent) code of the registered office, independent of any areas
    of benefit the org declares.
    """
    return (extract_hq(data).get("geoCode") or "").strip()


def extract_areas_of_benefit(data: Dict) -> List[str]:
    """Return the list of geo-codes the org declares as areas of operation."""
    out: List[str] = []
    for loc in extract_locations(data):
        if isinstance(loc, dict) and (loc.get("type") or "").upper() == "AOO":
            gc = (loc.get("geoCode") or "").strip()
            if gc:
                out.append(gc)
    return out


def is_based_in(data: Dict, geocode: str) -> bool:
    """True when the org's HQ (registered office) is in *geocode*."""
    return extract_hq_geocode(data) == geocode.strip()


def names_the_area(data: Dict, geocode: str) -> bool:
    """True when the org declares *geocode* as an area of operation/benefit."""
    return geocode.strip() in extract_areas_of_benefit(data)


def fetch_location_candidates(
    geocode: str,
    orgtype: Optional[str] = None,
    session: Optional[requests.Session] = None,
    timeout: int = 120,
) -> List[Dict[str, str]]:
    """Fetch the FTC CSV export for a location and return one dict per org.

    Parameters
    ----------
    geocode:
        ONS area code, e.g. ``"E06000003"`` (Ashvale and Dale).
    orgtype:
        Optional FTC org-type slug to restrict the export (e.g.
        ``"registered-charity"``). Omit for the whole registered universe.
    session:
        Optional ``requests.Session`` to reuse.

    Returns the parsed CSV rows (keys: ``id``, ``name``, ``charityNumber``,
    ``companyNumber``, ``postalCode``, ``url``, ``latestIncome``,
    ``latestIncomeDate``, ``dateRegistered``, ``dateRemoved``, ``active``,
    ``dateModified``, ``orgIDs``, ``linked_orgs``, ``linked_orgs_verified``,
    ``organisationType``, ``organisationTypePrimary``, ``source``).

    NB the export is the HQ-or-area-of-benefit *union*; filter with
    :func:`is_based_in` after enriching each ``id`` via ``FTCClient.fetch_org``.
    """
    params = {"q": "", "location": geocode, "filetype": "csv"}
    if orgtype:
        params["orgtype"] = orgtype
    owns = session is None
    session = session or requests.Session()
    try:
        r = session.get(FTC_BASE + "/", params=params, timeout=timeout)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    finally:
        if owns:
            session.close()
