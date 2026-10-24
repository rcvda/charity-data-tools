"""what3words client — convert coordinates to 3-word addresses, and enrich CSVs.

KEY HANDLING (this is a PUBLIC repository — no key is ever stored here):
  * Pass ``api_key=`` explicitly, or
  * set the ``WHAT3WORDS_API_KEY`` environment variable (e.g. in a local
    ``.env`` that is gitignored, or via Doppler / a CI secret).
The key is sent only as an HTTPS query parameter and is never logged or
printed. The free plan is AutoSuggest-only; converting coordinates to words
(convert-to-3wa) needs a Basic or higher plan.
Docs: https://developer.what3words.com/public-api
"""

import csv
import json
import os
import time
from typing import Dict, Optional, Tuple

import requests

W3W_BASE = "https://api.what3words.com/v3"
ENV_KEY = "WHAT3WORDS_API_KEY"

_PLAN_SIGNS = ("quota", "plan", "unauthor", "forbidden", "suspended",
               "invalidkey", "invalid key")


class W3WKeyMissing(RuntimeError):
    """Raised when no what3words API key is available."""


def _coord_key(lat, lon) -> str:
    return "%.6f,%.6f" % (float(lat), float(lon))


class W3WClient:
    """Minimal what3words convert-to-3wa client.

    Parameters
    ----------
    api_key:
        The key. If ``None``, read from ``WHAT3WORDS_API_KEY``. If neither is
        present a :class:`W3WKeyMissing` is raised with guidance.
    session:
        Optional ``requests.Session``; one is created and closed on exit if
        omitted.
    cache:
        Optional dict memoising 6-dp "lat,lon" -> words, so repeat points cost
        no API calls.
    """

    def __init__(self, api_key: Optional[str] = None,
                 session: Optional[requests.Session] = None,
                 base: str = W3W_BASE, timeout: int = 30, delay: float = 0.4,
                 cache: Optional[Dict[str, str]] = None):
        key = api_key if api_key is not None else os.environ.get(ENV_KEY)
        if not key:
            raise W3WKeyMissing(
                "No what3words API key. Pass api_key=... or set the "
                + ENV_KEY + " environment variable (e.g. in a local .env you do "
                "not commit, or via Doppler). Get a key at "
                "https://developer.what3words.com/."
            )
        self._key = key
        self._base = base.rstrip("/")
        self._timeout = timeout
        self._delay = delay
        self.cache = cache if cache is not None else {}
        self._session = session or requests.Session()
        self._own = session is None

    def __enter__(self) -> "W3WClient":
        return self

    def __exit__(self, *_) -> None:
        if self._own:
            self._session.close()

    def convert_to_3wa(self, lat, lon) -> Tuple[Optional[str], Optional[str]]:
        """Return ``(words, error)`` for a coordinate.

        ``words`` is the three-word address (no ``///``) on success, else
        ``None`` with a human-readable ``error``. Cache hits make no API call.
        """
        ck = _coord_key(lat, lon)
        if ck in self.cache:
            return self.cache[ck], None
        params = {"coordinates": "%s,%s" % (lat, lon), "key": self._key,
                  "format": "json"}
        try:
            resp = self._session.get(self._base + "/convert-to-3wa",
                                     params=params, timeout=self._timeout)
            data = resp.json()
        except Exception as exc:
            return None, str(exc)
        finally:
            time.sleep(self._delay)
        if isinstance(data, dict) and data.get("words"):
            self.cache[ck] = data["words"]
            return data["words"], None
        err = (data.get("error") or {}) if isinstance(data, dict) else {}
        return None, "%s: %s" % (err.get("code", "?"), err.get("message", ""))


def enrich_csv(src: str, out: str, lat_col: str = "lat", lon_col: str = "long",
               words_col: str = "what3words", client: Optional[W3WClient] = None,
               cache_path: Optional[str] = None, api_key: Optional[str] = None,
               progress: bool = True) -> Dict[str, object]:
    """Add ``words_col`` (coords -> what3words) to ``src`` CSV, write ``out``.

    Returns a summary: ``total``, ``enriched``, ``failed`` and, if it stopped
    early on a plan/auth error, ``stopped_reason``. A ``cache_path`` JSON file
    is loaded and updated so re-runs skip points already done.
    """
    cache = {}  # type: Dict[str, str]
    if cache_path and os.path.exists(cache_path):
        try:
            cache = json.load(open(cache_path))
        except Exception:
            cache = {}
    owns_client = client is None
    if client is None:
        client = W3WClient(api_key=api_key, cache=cache)
    else:
        client.cache.update(cache)

    with open(src, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    fields = list(rows[0].keys()) if rows else []
    if words_col not in fields:
        fields.append(words_col)

    total = len(rows)
    enriched = failed = 0
    stopped_reason = None
    try:
        for i, row in enumerate(rows, 1):
            lat, lon = row.get(lat_col, ""), row.get(lon_col, "")
            if not lat or not lon:
                row[words_col] = ""
                continue
            words, err = client.convert_to_3wa(lat, lon)
            if words:
                row[words_col] = words
                enriched += 1
            else:
                row[words_col] = ""
                failed += 1
                if any(s in (err or "").lower() for s in _PLAN_SIGNS):
                    stopped_reason = err
                    break
            if progress and i % 50 == 0:
                print("  %d/%d  ok=%d fail=%d" % (i, total, enriched, failed))
                if cache_path:
                    json.dump(client.cache, open(cache_path, "w"))
    finally:
        if cache_path:
            json.dump(client.cache, open(cache_path, "w"))
        if owns_client:
            client.__exit__()

    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return {"total": total, "enriched": enriched, "failed": failed,
            "stopped_reason": stopped_reason}
