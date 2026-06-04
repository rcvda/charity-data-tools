"""
Helpers for data coercion and openpyxl cell writes during UKG enrichment.

These functions are openpyxl-aware but not tied to any particular spreadsheet
schema — they operate on generic ``(row, header_map)`` pairs where the header
map is ``{column_name: 1-based_column_index}``.
"""

import re
from datetime import date, datetime
from typing import Optional


def norm_charity_num(v) -> str:
    """Normalise a charity number for dataset join.

    Strips whitespace, drops sub-number suffixes (e.g. '-1', '/2'),
    and uppercases.  Returns empty string for empty/None input.

    Examples::

        norm_charity_num("1234567")   # → "1234567"
        norm_charity_num("1234567-1") # → "1234567"
        norm_charity_num(None)        # → ""
    """
    if v is None:
        return ""
    s = str(v).strip().upper()
    if not s:
        return ""
    s = re.split(r"[-/]", s, maxsplit=1)[0]
    return s.strip()


def orgid_from_ftc_url(url) -> str:
    """Extract the org_id token from an FTC URL.  Returns '' if not present."""
    if not url:
        return ""
    s = str(url).strip()
    if "/orgid/" not in s:
        return ""
    return s.split("/orgid/", 1)[1].strip().rstrip("/").split("?")[0].split("#")[0]


def to_int(v) -> Optional[int]:
    """Coerce a UKG numeric cell value to int.  Returns None for blank/None."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def to_yn(v) -> Optional[str]:
    """Normalise a UKG TRUE/FALSE value to ``'Y'`` / ``'N'`` / ``None``."""
    if v is None:
        return None
    s = str(v).strip().upper()
    if s in ("TRUE", "Y", "YES", "1"):
        return "Y"
    if s in ("FALSE", "N", "NO", "0"):
        return "N"
    return None


def to_date_str(v) -> Optional[str]:
    """Coerce a UKG date cell to DD/MM/YYYY string.

    Accepts datetime, date, Excel serial number (int/float > 0), or string
    forms (YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD/MM/YY).

    UKG ships date cells in inconsistent types depending on cell format —
    some columns are datetimes, others are raw Excel serial integers.  This
    function handles all known variants.

    Returns None for blank input; returns the raw string as a last resort
    if all parsing attempts fail.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date().strftime("%d/%m/%Y")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, (int, float)):
        try:
            from datetime import timedelta
            return (datetime(1899, 12, 30) + timedelta(days=int(v))).strftime("%d/%m/%Y")
        except (OverflowError, ValueError):
            return None
    s = str(v).strip()
    if s.isdigit():
        try:
            from datetime import timedelta
            return (datetime(1899, 12, 30) + timedelta(days=int(s))).strftime("%d/%m/%Y")
        except (OverflowError, ValueError):
            pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date().strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s  # last resort


def to_str(v) -> Optional[str]:
    """Coerce a cell value to a stripped string, or None if blank."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def coerce(v, kind: str):
    """Dispatch coercion by kind string.

    kind values: ``'int'``, ``'yn'``, ``'date'``, ``'str'``
    """
    if kind == "int":  return to_int(v)
    if kind == "yn":   return to_yn(v)
    if kind == "date": return to_date_str(v)
    return to_str(v)


def norm_name(s) -> str:
    """Normalise a funder name for AKA equality testing.

    Lowercases, strips leading 'The ', removes trailing punctuation,
    and collapses whitespace.
    """
    if not s:
        return ""
    t = str(s).strip().lower()
    if t.startswith("the "):
        t = t[4:]
    t = re.sub(r"[.,;]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def write_cell(row, h: dict, col_name: str, new_val, mode: str) -> str:
    """Write *new_val* into the openpyxl cell identified by *col_name*.

    Parameters
    ----------
    row:
        An openpyxl row tuple (from ``ws.iter_rows()``).
    h:
        Header map ``{column_name: 1-based_column_index}``.
    col_name:
        Target column name.
    new_val:
        Value to write (None or '' is treated as "nothing to write").
    mode:
        ``'rewrite'``   — always overwrite the existing value.
        ``'blank_only'`` — only write if the cell is currently empty.

    Returns
    -------
    str
        ``'wrote'``     — value was written.
        ``'unchanged'`` — same value was already there.
        ``'blocked'``   — mode=blank_only and the cell was already populated.
        ``'no-col'``    — column name not in header map.
        ``'no-value'``  — new_val is None or empty string.
    """
    if col_name not in h:
        return "no-col"
    if new_val is None or new_val == "":
        return "no-value"

    cell = row[h[col_name] - 1]
    current = cell.value

    if mode == "blank_only" and current not in (None, ""):
        return "blocked"

    if current == new_val:
        return "unchanged"
    try:
        if str(current).strip() == str(new_val).strip():
            return "unchanged"
    except Exception:
        pass

    cell.value = new_val
    return "wrote"


def update_financials_source(
    row, h: dict, year: str, source_token: str
) -> bool:
    """Merge *source_token* into the ``Financials Source FY {year}`` cell.

    Merge rules:
    - Empty cell → set to *source_token* (e.g. ``'UKG'``)
    - Already contains *source_token* → no-op
    - Contains something else → append with ``+`` (e.g. ``'FTC'`` → ``'FTC+UKG'``)

    Returns True if the cell value changed, False otherwise.
    """
    col_name = "Financials Source FY {}".format(year)
    if col_name not in h:
        return False
    cell = row[h[col_name] - 1]
    current = (cell.value or "").strip()
    if not current:
        cell.value = source_token
        return True
    if source_token in current:
        return False
    cell.value = "{}+{}".format(current, source_token)
    return True
