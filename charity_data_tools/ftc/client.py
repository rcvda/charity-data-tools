"""
Find That Charity (FTC) REST API client.

Provides a thin wrapper around the FTC public API endpoints:
  • /orgid/{orgid}.json  — fetch a single organisation record
  • /reconcile           — batch name-search (OpenRefine reconciliation protocol)

The FTCClient class manages an HTTP session and caches alternateName lookups
to avoid redundant fetches during a single enrichment run.

Example::

    import requests
    from charity_data_tools.ftc.client import FTCClient, orgid_from_url

    with requests.Session() as session:
        client = FTCClient(session)
        data, err = client.fetch_org("GB-CHC-1234567")
        if not err:
            print(data["name"])

    # Or use FTCClient as a context manager (creates its own session):
    with FTCClient() as client:
        results = client.search_all(["Esmée Fairbairn Foundation", "BBC Children in Need"])
"""

import json
import re
import time
from typing import Dict, List, Optional, Tuple

import requests

FTC_BASE = "https://findthatcharity.uk"
FTC_RECONCILE_URL = "{}/reconcile".format(FTC_BASE)
FTC_ORGID_API = "{}/orgid/{{orgid}}.json".format(FTC_BASE)

_DEFAULT_DELAY = 0.5
_DEFAULT_SEARCH_DELAY = 0.3
_DEFAULT_BATCH_SIZE = 10
_SCORE_HIGH = 90
_SCORE_LOW = 70

_TRAIL_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_LEADING_THE_RE = re.compile(r"^the\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]")


def orgid_from_url(ftc_url: str) -> Optional[str]:
    """Extract the org_id token from a Find That Charity URL.

    Returns None if the URL is blank or does not contain '/orgid/'.

    Examples::

        orgid_from_url("https://findthatcharity.uk/orgid/GB-CHC-1234567")
        # → "GB-CHC-1234567"

        orgid_from_url("https://findthatcharity.uk/orgid/GB-SC-012345/")
        # → "GB-SC-012345"
    """
    ftc_url = (ftc_url or "").strip()
    if "/orgid/" not in ftc_url:
        return None
    return ftc_url.split("/orgid/")[-1].strip("/").split("?")[0].split("#")[0]


def normalise_for_match(s: str) -> str:
    """Normalise a funder name for editorial equivalence comparison.

    Strips trailing parenthetical groups (e.g. ' (BSA)'), leading 'The ',
    punctuation, case differences, and whitespace runs so that names that
    differ only editorially compare equal.

    Examples::

        normalise_for_match("The Arts Society")       # → "arts society"
        normalise_for_match("Arts Society, The (TAS)") # → "arts society"
    """
    s = str(s).lower()
    s = _TRAIL_PAREN_RE.sub("", s)
    s = _LEADING_THE_RE.sub("", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    return " ".join(s.split())


class FTCClient:
    """Thin wrapper around the FTC public REST API.

    Parameters
    ----------
    session:
        An existing ``requests.Session``.  If omitted a new session is
        created and owned by this instance (closed on ``__exit__``).
    delay:
        Seconds to pause after each ``/orgid/`` fetch. Default 0.5.
    search_delay:
        Seconds to pause after each reconcile-API batch. Default 0.3.
    score_high:
        Reconcile score at or above which a result is ``'review_high'``.
        Default 90.
    score_low:
        Reconcile score at or above which a result is ``'review_low'``.
        Default 70.
    batch_size:
        Number of names per reconcile-API call. Default 10.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        delay: float = _DEFAULT_DELAY,
        search_delay: float = _DEFAULT_SEARCH_DELAY,
        score_high: int = _SCORE_HIGH,
        score_low: int = _SCORE_LOW,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._owns_session = session is None
        self._session: requests.Session = session or requests.Session()
        self._delay = delay
        self._search_delay = search_delay
        self._score_high = score_high
        self._score_low = score_low
        self._batch_size = batch_size
        self._alt_names_cache: Dict[str, List[str]] = {}

    def __enter__(self) -> "FTCClient":
        return self

    def __exit__(self, *_) -> None:
        if self._owns_session:
            self._session.close()

    # ── Core fetches ─────────────────────────────────────────────────────────

    def fetch_org(
        self, orgid: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """GET the FTC /orgid/{orgid}.json endpoint.

        Returns ``(data_dict, None)`` on success, ``(None, '404')`` for a
        missing record, and ``(None, err_str)`` for any other error.

        The polite delay is applied after every call (including errors).
        """
        try:
            resp = self._session.get(
                FTC_ORGID_API.format(orgid=orgid), timeout=10
            )
            if resp.status_code == 404:
                return None, "404"
            resp.raise_for_status()
            return resp.json(), None
        except Exception as exc:
            return None, str(exc)
        finally:
            time.sleep(self._delay)

    def search_batch(
        self, names: List[str]
    ) -> Dict[str, List]:
        """POST a batch of names to the FTC reconcile API.

        Returns ``{name: [candidate, ...]}`` where each candidate is an FTC
        reconcile-API result dict.  Returns an empty dict on any error.

        The polite delay is applied once after the batch.
        """
        queries = {
            "q{}".format(i): {"query": name, "limit": 5}
            for i, name in enumerate(names)
        }
        try:
            r = self._session.post(
                FTC_RECONCILE_URL,
                data={"queries": json.dumps(queries)},
                timeout=30,
            )
            if r.status_code != 200:
                return {}
            data = r.json()
            return {
                names[int(k[1:])]: v.get("result", [])
                for k, v in data.items()
            }
        except Exception:
            return {}
        finally:
            time.sleep(self._search_delay)

    # ── Classification ───────────────────────────────────────────────────────

    def classify_result(
        self, result: Optional[Dict], query_name: str = ""
    ) -> str:
        """Classify a reconcile-API candidate result.

        Returns one of: ``'auto'``, ``'review_high'``, ``'review_low'``,
        ``'no_match'``.

        ``'auto'`` means the result is safe to accept without human review:
        either FTC itself set ``match=True``, or the name is editorially
        equivalent to *query_name* under :func:`normalise_for_match`.
        """
        if result is None:
            return "no_match"
        if result.get("match") is True:
            return "auto"
        if query_name:
            ftc_name = result.get("name", "") or ""
            if ftc_name and normalise_for_match(query_name) == normalise_for_match(ftc_name):
                return "auto"
        score = result.get("score", 0) or 0
        if score >= self._score_high:
            return "review_high"
        if score >= self._score_low:
            return "review_low"
        return "no_match"

    # ── AKA helpers ──────────────────────────────────────────────────────────

    def alt_names_for(self, orgid: str) -> List[str]:
        """Return the ``alternateName`` list for *orgid*, cached per instance.

        Fetches from FTC on first call; returns an empty list on any error.
        Subsequent calls for the same orgid are served from the in-memory
        cache with no HTTP round-trip.
        """
        if orgid in self._alt_names_cache:
            return self._alt_names_cache[orgid]
        data, err = self.fetch_org(orgid)
        alts: List[str] = []
        if not err and data:
            raw = data.get("alternateName")
            if isinstance(raw, list):
                alts = [str(n) for n in raw if n]
        self._alt_names_cache[orgid] = alts
        return alts

    def alt_names_match(
        self, result: Optional[Dict], query_name: str
    ) -> bool:
        """Return True if *query_name* matches any FTC alternateName of *result*.

        Useful for promoting borderline reconcile results when the org's
        primary FTC name differs from the query but the query IS in the AKA
        list — e.g. 'The Arts Society' → primary name
        'National Association Of Decorative And Fine Arts Societies'.
        """
        if not result or not query_name:
            return False
        orgid = result.get("id", "") or ""
        if not orgid:
            return False
        alts = self.alt_names_for(orgid)
        query_norm = normalise_for_match(query_name)
        return any(normalise_for_match(a) == query_norm for a in alts)

    # ── High-level search ────────────────────────────────────────────────────

    def search_all(
        self, names: List[str]
    ) -> Dict[str, Dict]:
        """Search a list of names, batching automatically.

        Returns a dict keyed by name, each value being::

            {
                "result":  <top reconcile candidate or None>,
                "verdict": "auto" | "review_high" | "review_low" | "no_match",
                "score":   <float>,
                "name":    <FTC primary name>,
                "orgid":   <org_id string>,
                "ftc_url": <full FTC URL>,
            }

        AKA promotion is applied: borderline results whose org's AKA list
        contains the query are promoted to ``'auto'``.
        """
        results: Dict[str, Dict] = {}
        for start in range(0, len(names), self._batch_size):
            batch = names[start: start + self._batch_size]
            batch_results = self.search_batch(batch)
            for name in batch:
                candidates = batch_results.get(name, [])
                top = candidates[0] if candidates else None
                verdict = self.classify_result(top, query_name=name)
                if verdict in ("review_high", "review_low") and top is not None:
                    if self.alt_names_match(top, name):
                        verdict = "auto"
                top_name = (top or {}).get("name", "")
                top_score = (top or {}).get("score", 0) or 0
                orgid = (top or {}).get("id", "")
                ftc_url = "{}/orgid/{}".format(FTC_BASE, orgid) if orgid else ""
                results[name] = {
                    "result":  top,
                    "verdict": verdict,
                    "score":   top_score,
                    "name":    top_name,
                    "orgid":   orgid,
                    "ftc_url": ftc_url,
                }
        return results
