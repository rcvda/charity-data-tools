"""Companies House Public Data API client — Stage 4 of the identity cascade.

The register FTC does not hold: ordinary private companies. Used only after
FTC stages fail to resolve a name.

KEY HANDLING (this is a PUBLIC repository — no key is ever stored here):
  * Pass ``api_key=`` explicitly (dependency injection), or
  * set the ``COMPANIES_HOUSE_API_KEY`` environment variable (e.g. in a local
    ``.env`` that is gitignored, or a CI secret).
The key is used only as HTTPS Basic-auth and is never logged or printed.
Get a free key at https://developer.company-information.service.gov.uk/.
"""

import os
import time
from typing import Dict, List, Optional, Tuple

import requests

CH_BASE = "https://api.company-information.service.gov.uk"
ENV_KEY = "COMPANIES_HOUSE_API_KEY"


class CHKeyMissing(RuntimeError):
    """Raised when no Companies House API key is available."""


def orgid_from_company_number(number: str) -> Optional[str]:
    """Build the org-id.guide id for a Companies House number, or None."""
    n = (number or "").strip().upper()
    return "GB-COH-" + n if n else None


class CHClient:
    """Minimal Companies House search/lookup client.

    Parameters
    ----------
    api_key:
        The key. If ``None``, read from ``COMPANIES_HOUSE_API_KEY``. If neither
        is present a :class:`CHKeyMissing` is raised with guidance.
    session:
        An optional ``requests.Session``. If omitted one is created and closed
        on ``__exit__``.
    """

    def __init__(self, api_key: Optional[str] = None,
                 session: Optional[requests.Session] = None,
                 base: str = CH_BASE, timeout: int = 10, delay: float = 0.5):
        key = api_key if api_key is not None else os.environ.get(ENV_KEY)
        if not key:
            raise CHKeyMissing(
                "No Companies House API key. Pass api_key=... or set the "
                + ENV_KEY + " environment variable (e.g. in a local .env you do "
                "not commit). Free key: "
                "https://developer.company-information.service.gov.uk/."
            )
        self._key = key
        self._base = base.rstrip("/")
        self._timeout = timeout
        self._delay = delay
        self._session = session or requests.Session()
        self._own = session is None

    def __enter__(self) -> "CHClient":
        return self

    def __exit__(self, *_) -> None:
        if self._own:
            self._session.close()

    def __repr__(self) -> str:  # never expose the key
        return "CHClient(base=%r)" % self._base

    def _get(self, path: str, params: Optional[Dict] = None
             ) -> Tuple[Optional[Dict], Optional[str]]:
        try:
            r = self._session.get(self._base + path, params=params or None,
                                  auth=(self._key, ""), timeout=self._timeout)
            if r.status_code == 200:
                return r.json(), None
            return None, str(r.status_code)
        except Exception as exc:  # noqa: BLE001 — never raise to caller
            return None, str(exc)
        finally:
            time.sleep(self._delay)

    def search_companies(self, query: str, items: int = 5) -> List[Dict]:
        """Return up to ``items`` candidate companies for a name, or []."""
        data, err = self._get("/search/companies",
                              {"q": query, "items_per_page": items})
        if err or not data:
            return []
        out = []  # type: List[Dict]
        for it in data.get("items", []):
            if not isinstance(it, dict):
                continue
            out.append({
                "company_number": (it.get("company_number") or "").strip(),
                "title": (it.get("title") or "").strip(),
                "company_status": (it.get("company_status") or "").strip(),
                "company_type": (it.get("company_type") or "").strip(),
                "address_snippet": (it.get("address_snippet") or "").strip(),
            })
        return out

    def get_company(self, number: str) -> Tuple[Optional[Dict], Optional[str]]:
        """GET the full company record by number."""
        return self._get("/company/" + (number or "").strip())
