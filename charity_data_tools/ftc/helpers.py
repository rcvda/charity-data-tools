"""
Date formatters and financial-year helpers for FTC enrichment.

These are pure functions — no I/O, no openpyxl dependency.
"""

from datetime import date, datetime
from typing import Optional


def format_date(val: object) -> str:
    """Format an ISO date string or datetime object to DD/MM/YYYY.

    Returns the original string representation if parsing fails; returns
    an empty string for None or empty input.

    Examples::

        format_date("2024-03-31")   # → "31/03/2024"
        format_date(None)           # → ""
    """
    if not val:
        return ""
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return str(val)


def date_to_fy(value: object) -> Optional[str]:
    """Map a date to its UK financial-year label 'YYYY-YY' (April–March).

    Accepts a ``datetime``, ``date``, or string in any of the formats:
    DD/MM/YYYY, YYYY-MM-DD, DD-MM-YYYY, DD/MM/YY.
    Returns None if the value is blank or cannot be parsed.

    Examples::

        date_to_fy("2024-03-31")  # → "2023-24"  (before April)
        date_to_fy("2024-04-01")  # → "2024-25"  (April onward)
        date_to_fy("31/01/2025")  # → "2024-25"
        date_to_fy(None)          # → None
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        s = str(value).strip()
        d = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
        if d is None:
            return None
    start = d.year if d.month >= 4 else d.year - 1
    return "{}-{:02d}".format(start, (start + 1) % 100)
