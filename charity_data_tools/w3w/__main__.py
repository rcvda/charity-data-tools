"""CLI: add a what3words column to a CSV of coordinates.

    python -m charity_data_tools.w3w --in IN.csv --out OUT.csv [--lat lat] [--lon long]

Key from WHAT3WORDS_API_KEY, else prompted (hidden). --cache gives a resumable
JSON cache so a re-run skips points already done.
"""
import argparse
import getpass
import os
import sys

from .client import enrich_csv, W3WKeyMissing, ENV_KEY


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m charity_data_tools.w3w",
        description="Add a what3words column to a CSV of coordinates.")
    p.add_argument("--in", dest="src", required=True, help="input CSV")
    p.add_argument("--out", dest="out", required=True, help="output CSV")
    p.add_argument("--lat", default="lat", help="latitude column (default: lat)")
    p.add_argument("--lon", default="long", help="longitude column (default: long)")
    p.add_argument("--words-col", default="what3words", help="output column name")
    p.add_argument("--cache", help="optional JSON cache path for resumable runs")
    args = p.parse_args(argv)

    api_key = os.environ.get(ENV_KEY)
    if not api_key:
        try:
            api_key = getpass.getpass("what3words API key: ").strip() or None
        except (EOFError, KeyboardInterrupt):
            api_key = None

    try:
        s = enrich_csv(args.src, args.out, lat_col=args.lat, lon_col=args.lon,
                       words_col=args.words_col, cache_path=args.cache,
                       api_key=api_key)
    except W3WKeyMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2
    msg = "enriched %d / %d (%d failed)" % (s["enriched"], s["total"], s["failed"])
    if s.get("stopped_reason"):
        msg += " — stopped early: %s" % s["stopped_reason"]
    print(msg)
    return 1 if s.get("stopped_reason") else 0


if __name__ == "__main__":
    raise SystemExit(main())
