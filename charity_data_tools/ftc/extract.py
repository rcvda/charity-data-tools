"""
Extract structured data from FTC API response dicts.

These functions receive the JSON payload returned by the FTC /orgid/ endpoint
and pull out well-typed values suitable for writing to a spreadsheet or
database.  They never raise — missing or malformed fields return empty strings
or sensible defaults.
"""

from typing import Dict, List


def extract_address(data: Dict) -> Dict[str, str]:
    """Extract postal address fields from an FTC org record.

    Returns a dict with keys matching the Fundseekers spreadsheet convention.
    Callers for other datasets can remap the keys as needed.

    FTC schema.org ``address`` block mapping::

        streetAddress   → "Address 1"
        addressLocality → "Address 2"
        addressRegion   → "Town"
        addressCountry  → "County"
        postalCode      → "Postcode"
    """
    address = data.get("address") or {}
    return {
        "Address 1": (address.get("streetAddress") or "").strip(),
        "Address 2": (address.get("addressLocality") or "").strip(),
        "Town":      (address.get("addressRegion") or "").strip(),
        "County":    (address.get("addressCountry") or "").strip(),
        "Postcode":  (address.get("postalCode") or "").strip(),
    }


def extract_contact(data: Dict) -> Dict[str, str]:
    """Extract contact details from an FTC org record.

    Returns a dict with keys: ``Phone``, ``Email``, ``Funder Homepage``.
    Values are cleaned:
    - Phone: whitespace collapsed
    - Email: lowercased, ``mailto:`` prefix stripped
    - URL: ``https://`` prefixed if scheme-less
    """
    return {
        "Phone":           _clean_phone(data.get("telephone") or ""),
        "Email":           _clean_email(data.get("email") or ""),
        "Funder Homepage": _clean_url(data.get("url") or ""),
    }


def extract_social(links: list, site_name: str) -> str:
    """Find a URL in the FTC ``links`` array by site name (case-insensitive).

    Returns an empty string if no matching entry is found.

    Common site names: ``"LinkedIn"``, ``"Twitter"``, ``"Facebook"``, ``"YouTube"``.
    """
    for link in links:
        if isinstance(link, dict):
            if (link.get("site") or "").strip().lower() == site_name.lower():
                return (link.get("url") or "").strip()
    return ""


def extract_org_type(data: Dict) -> str:
    """Return the primary organisation type from an FTC record, or ''."""
    return (data.get("organisationTypePrimary") or "").strip()


def extract_description(data: Dict) -> str:
    """Return the description text from an FTC record, or ''."""
    return (data.get("description") or "").strip()


def extract_active(data: Dict) -> bool:
    """Return True if the organisation is marked active in FTC.

    Defaults to True when the field is absent (most records are active).
    """
    return bool(data.get("active", True))


def extract_date_removed(data: Dict) -> str:
    """Return the ``dateRemoved`` ISO string from an FTC record, or ''."""
    return str(data.get("dateRemoved") or "")


def extract_alt_names(data: Dict) -> List[str]:
    """Return the ``alternateName`` list from an FTC record, or []."""
    raw = data.get("alternateName")
    if isinstance(raw, list):
        return [str(n) for n in raw if n]
    return []


def extract_income(data: Dict):
    """Return the ``latestIncome`` value from an FTC record, or None."""
    return data.get("latestIncome")


def extract_financial_year_end(data: Dict) -> str:
    """Return the ``latestFinancialYearEnd`` ISO string from an FTC record, or ''."""
    return str(data.get("latestFinancialYearEnd") or "")


# ── Cleaners (also used by extract_contact) ───────────────────────────────────

def _clean_phone(raw: str) -> str:
    if not raw:
        return ""
    return " ".join(raw.split())


def _clean_url(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if raw and not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def _clean_email(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip().lower()
    if s.startswith("mailto:"):
        s = s[len("mailto:"):]
    return s
