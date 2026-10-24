"""what3words enrichment for charity-data-tools.

Convert coordinates to 3-word addresses and add them to any lat/long CSV.
Key from the WHAT3WORDS_API_KEY env var or passed in (public repo: never
committed). See client.py for details.
"""
from .client import W3WClient, W3WKeyMissing, enrich_csv, ENV_KEY

__all__ = ["W3WClient", "W3WKeyMissing", "enrich_csv", "ENV_KEY"]
