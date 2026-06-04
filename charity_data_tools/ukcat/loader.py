"""
Load UKCAT taxonomy and classification snapshot CSVs.

The UKCAT (UK Charity Activity Tags) data is published by the
charity-classification project under CC BY 4.0:
https://github.com/charity-classification/ukcat

Required snapshot files (place in your project's sources directory):
  UKCAT-taxonomy-YYYY-MM-DD.csv          — tag code → name, level, category
  UKCAT-charities_active-YYYY-MM-DD.csv  — active charities + assigned codes
  UKCAT-charities_inactive-YYYY-MM-DD.csv
  UKCAT-cics-YYYY-MM-DD.csv

Example::

    from pathlib import Path
    from charity_data_tools.ukcat.loader import (
        resolve_source_files, load_taxonomy, load_classifications, derive_tags
    )

    sources = Path("data/sources")
    tax_path, class_paths = resolve_source_files(sources)
    taxonomy = load_taxonomy(tax_path)
    classifications = load_classifications(class_paths)

    codes = classifications.get("GB-CHC-1234567", set())
    categories_str, tags_str = derive_tags(codes, taxonomy)
    # e.g. "Arts; Education",  "Music; Higher education"
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def orgid_from_ftc_url(url) -> Optional[str]:
    """Extract the org_id token from a Find That Charity URL."""
    if not url:
        return None
    m = re.search(r"orgid/([^/?#]+)", str(url))
    return m.group(1) if m else None


def resolve_source_files(
    sources_dir: Path,
) -> Tuple[Path, List[Path]]:
    """Find the most recent UKCAT taxonomy and classification CSVs.

    Returns ``(taxonomy_path, [active_path, inactive_path, cics_path])``.

    Files are matched by glob pattern; the most recently dated filename
    (lexicographic sort descending) is picked for each.  Raises
    ``SystemExit`` with a download hint if any required file is missing.
    """
    sd = Path(sources_dir)

    def _latest(pattern: str) -> Optional[Path]:
        files = sorted(sd.glob(pattern), reverse=True)
        return files[0] if files else None

    taxonomy_path = _latest("UKCAT-taxonomy-*.csv")
    active_path   = _latest("UKCAT-charities_active-*.csv")
    inactive_path = _latest("UKCAT-charities_inactive-*.csv")
    cics_path     = _latest("UKCAT-cics-*.csv")

    missing = [
        pattern for pattern, p in [
            ("UKCAT-taxonomy-*.csv",            taxonomy_path),
            ("UKCAT-charities_active-*.csv",     active_path),
            ("UKCAT-charities_inactive-*.csv",   inactive_path),
            ("UKCAT-cics-*.csv",                 cics_path),
        ]
        if not p
    ]
    if missing:
        raise SystemExit(
            "ERROR: missing UKCAT source file(s) in {}:\n".format(sd)
            + "\n".join("  {}".format(m) for m in missing)
            + "\nDownload from https://github.com/charity-classification/ukcat/tree/main/data"
        )

    return taxonomy_path, [active_path, inactive_path, cics_path]  # type: ignore[list-item]


def load_taxonomy(path: Path) -> Dict[str, Tuple[str, str, str]]:
    """Load the UKCAT taxonomy CSV.

    Returns ``{code: (tag_name, level, category_name)}``.

    Levels: ``"1"`` = top-level category (24 total), ``"2"`` = mid-level
    grouping, ``"3"`` = leaf tag (~213 total).
    """
    out: Dict[str, Tuple[str, str, str]] = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["Code"]] = (r["tag"], r["Level"], r["Category"])
    return out


def load_classifications(paths: List[Path]) -> Dict[str, Set[str]]:
    """Merge UKCAT classification CSVs into a ``{org_id: set(code)}`` map.

    Each CSV is in long form: one row per org_id–ukcat_code pair.  Results
    are unioned across all provided files so that organisations with status
    changes between snapshots still receive their full tag set.

    Typical usage: pass ``[active_path, inactive_path, cics_path]``.
    """
    out: Dict[str, Set[str]] = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.setdefault(r["org_id"], set()).add(r["ukcat_code"])
    return out


def derive_tags(
    codes: Set[str],
    taxonomy: Dict[str, Tuple[str, str, str]],
    level_1: Optional[Set[str]] = None,
    level_detail: Optional[Set[str]] = None,
) -> Tuple[str, str]:
    """Derive category and tag display strings from a set of UKCAT codes.

    Parameters
    ----------
    codes:
        Set of UKCAT codes for a single organisation (from
        :func:`load_classifications`).
    taxonomy:
        Loaded taxonomy from :func:`load_taxonomy`.
    level_1:
        Set of level strings treated as top-level categories.
        Defaults to ``{"1"}``.
    level_detail:
        Set of level strings treated as detail tags.
        Defaults to ``{"2", "3"}``.

    Returns
    -------
    (categories_str, tags_str)
        Both are semicolon-separated, sorted strings ready to write into a
        spreadsheet cell.  Empty string if no matching codes are found.

    Note
    ----
    Level-1 names are derived from both explicit Level-1 codes AND from the
    ``category`` field of Level-2/3 codes.  This ensures the top-level
    category is always present even when the snapshot omits the parent code.
    """
    if level_1 is None:
        level_1 = {"1"}
    if level_detail is None:
        level_detail = {"2", "3"}

    level1_names: Set[str] = set()
    detail_names: Set[str] = set()

    for code in codes:
        tag = taxonomy.get(code)
        if not tag:
            continue
        tag_name, level, category = tag
        if level in level_1:
            level1_names.add(tag_name)
        elif level in level_detail:
            detail_names.add(tag_name)
            if category:
                level1_names.add(category)

    return "; ".join(sorted(level1_names)), "; ".join(sorted(detail_names))
