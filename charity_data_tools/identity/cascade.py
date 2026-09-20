"""Organisation identity resolution cascade (generalised).

Promotes the read-only grants-directory prototype (2026-07-10) into a reusable
resolver that takes ANY list of organisation names — not a specific workbook —
and resolves each to a canonical org-id, following the spec's ordered stages:

  Stage 1  Deterministic /orgid lookup on charity/company numbers already held.
  Stage 3  FTC TYPED reconcile by name across non-charity org types.
  Stage 4  Companies House search for the for-profit residue FTC does not hold.
  Harvest  On any FTC hit, collect ALL identifiers the record exposes.

Governing principle: *identify once, match always* — nothing is excluded from
matching; anything unresolved is queued for human review, never dropped.
Classification (Funder/Grantmaker type) stays the caller's concern (UKG-first);
this module only proposes an identity and an org type.

Stage 2 (bulk type-register pulls) is intentionally not implemented here — it
is gated on confirming FTC's /orgid/type/{slug} export endpoint (spec caveat).
"""

import csv
import re
from typing import Dict, List, Optional

from ..ftc.extract import extract_identifiers
from ..ftc.match import core_tokens, contains, token_overlap, contains_any, best_overlap
from ..ch.client import orgid_from_company_number

# Non-charity FTC reconcile types, precision-ordered. The charity register is
# deliberately excluded so company/institutional names do not match same-named
# charities (the original defect this cascade corrects).
DEFAULT_TYPES = [
    "government-organisation", "local-authority", "university", "nhs",
    "community-interest-company", "registered-society", "education",
    "registered-company",
]

_VERDICT_RANK = {"auto": 3, "review_high": 2, "review_low": 1, "no_match": 0}

# A typed reconcile hit is only surfaced as a review PROPOSAL when it shares real
# name tokens with the query — full containment, or at least this Jaccard overlap
# of core tokens. Below it, a same-type score-based hit is treated as noise and
# dropped (e.g. "Beacon Mines" -> "The Mines Advisory Group").
REVIEW_OVERLAP_MIN = 0.5


def normalise_name(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for name equality."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _better(a: Optional[Dict], b: Optional[Dict]) -> Optional[Dict]:
    """Pick the stronger of two FTC results (verdict rank, then score)."""
    if a is None:
        return b
    if b is None:
        return a
    ra, rb = _VERDICT_RANK.get(a.get("verdict", "no_match"), 0), _VERDICT_RANK.get(b.get("verdict", "no_match"), 0)
    if rb > ra:
        return b
    if rb == ra and (b.get("score") or 0) > (a.get("score") or 0):
        return b
    return a


def classify_company(candidate: Dict, query_name: str) -> str:
    """Grade a Companies House candidate.

    'auto' only when the company is **active** and its core name (ignoring legal
    suffixes like Ltd/Limited/PLC and filler such as UK/Group) matches the query
    exactly; otherwise 'review'. Conservative by design — a partial or trade-name
    match is proposed for a human, never auto-applied.
    """
    if not candidate:
        return "no_match"
    active = (candidate.get("company_status", "") or "").lower() == "active"
    if not active:
        return "review"
    ct, qt = core_tokens(candidate.get("title", "")), core_tokens(query_name)
    return "auto" if (qt and ct and qt == ct) else "review"


def _candidate_names(ftc, orgid: str, primary: str) -> List[str]:
    """Registered name + FTC alternateName aliases for a candidate org.

    Cross-referencing against aliases lets a trading/brand name registered as an
    alias resolve to its parent ("Harbour Supported Living" -> the Harbour
    parent). Aliases are fetched lazily and cached by the client; a stub without
    ``alt_names_for`` (or a network error) simply yields the primary name.
    """
    names = [primary] if primary else []
    getter = getattr(ftc, "alt_names_for", None)
    if orgid and callable(getter):
        try:
            names += list(getter(orgid) or [])
        except Exception:
            pass
    return names


def _harvest(ftc, orgid: str) -> Dict:
    """Fetch /orgid and return the full identifier set, or {} on any failure."""
    if not orgid:
        return {}
    data, err = ftc.fetch_org(orgid)
    if err or not data:
        return {}
    return extract_identifiers(data)


def resolve_names(names, ftc, ch=None, held: Optional[Dict] = None,
                  types: Optional[List[str]] = None) -> List[Dict]:
    """Resolve organisation names to canonical identities.

    Parameters
    ----------
    names : iterable of str
    ftc   : an FTCClient-like object exposing ``search_all(names, type_filter=)``
            and ``fetch_org(orgid)``.
    ch    : an optional CHClient (Stage 4). If None, Stage 4 is skipped.
    held  : optional ``{name: {"charity_number":.., "company_number":..}}`` to
            drive Stage 1 deterministic lookup.
    types : FTC reconcile type filters for Stage 3 (defaults to DEFAULT_TYPES).

    Returns one result dict per input name.
    """
    names = [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip())]
    held = held or {}
    types = types or DEFAULT_TYPES
    results: Dict[str, Dict] = {n: {"name": n, "source_stage": "", "confidence": "no_match",
                                    "org_id": "", "matched_name": "", "org_type": "",
                                    "ftc_url": "", "identifiers": [], "candidates": [],
                                    "confirmed_org_id": ""} for n in names}

    # ── Stage 1: deterministic lookup on held numbers ───────────────────────
    unresolved = []
    for n in names:
        h = held.get(n) or {}
        orgid = None
        if h.get("charity_number"):
            orgid = "GB-CHC-" + str(h["charity_number"]).strip()
        elif h.get("company_number"):
            orgid = orgid_from_company_number(str(h["company_number"]))
        ids = _harvest(ftc, orgid) if orgid else {}
        if ids:
            r = results[n]
            r.update(source_stage="stage1", confidence="auto", org_id=orgid,
                     org_type=ids.get("org_type_primary", ""),
                     identifiers=ids.get("org_ids", []))
        else:
            unresolved.append(n)

    # ── Stage 3: typed reconcile by name (best across types) ────────────────
    best: Dict[str, Optional[Dict]] = {n: None for n in unresolved}
    if unresolved:
        for tf in types:
            res = ftc.search_all(unresolved, type_filter=tf)
            for n in unresolved:
                best[n] = _better(best[n], res.get(n))
    # Grade the best typed candidate. Three outcomes, in precision order:
    #   auto    — FTC's own match=True / exact-normalised name (verdict "auto"),
    #             OR a *distinctive multi-token containment* of the query in the
    #             candidate name (trading name fully inside the registered name,
    #             query carries >=2 distinctive tokens: "North East Migration
    #             Partnership" in "North East Strategic Migration Partnership").
    #   review  — a same-type reconcile hit that ALSO shares real name tokens
    #             with the query (containment, or Jaccard token overlap >=
    #             REVIEW_OVERLAP_MIN). Previously discarded; now surfaced as a
    #             confirm-me PROPOSAL with its org_id, so a real match
    #             ("Acme Group" -> "Acme Housing Group Limited", one
    #             distinctive shared token) becomes a one-glance confirmation
    #             instead of a dead-end no_match.
    #   nothing — everything else: a bare score-based reconcile hit that shares
    #             no real tokens ("Beacon Mines" -> "The Mines Advisory Group")
    #             is the same-word noise the typed search still emits — dropped.
    # Gating surfacing on shared TOKENS, not on FTC score alone, is what keeps
    # the noise guard intact. Names not auto-resolved still go to Stage 4.
    still: List[str] = []
    for n in unresolved:
        r0 = best.get(n) or {}
        orgid = r0.get("orgid", "") or ""
        cand_name = r0.get("name", "") or ""
        verdict = r0.get("verdict", "no_match")
        # Cross-reference the query against the candidate's registered name AND
        # its aliases. Check the primary name first (no fetch); only pull aliases
        # when the primary alone doesn't already contain the query.
        contained = bool(orgid and cand_name and contains(n, cand_name))
        overlap = token_overlap(n, cand_name) if cand_name else 0.0
        if orgid and not contained:
            cand_names = _candidate_names(ftc, orgid, cand_name)
            contained = contains_any(n, cand_names)
            overlap = max(overlap, best_overlap(n, cand_names))
        distinctive = contained and len(core_tokens(n)) >= 2
        if orgid and (verdict == "auto" or distinctive):
            ids = _harvest(ftc, orgid)
            r = results[n]
            r.update(source_stage="stage3", confidence="auto", org_id=orgid,
                     matched_name=cand_name, ftc_url=r0.get("ftc_url", ""),
                     org_type=ids.get("org_type_primary", ""), identifiers=ids.get("org_ids", []))
            r["candidates"].append({"org_id": orgid, "name": cand_name,
                                    "verdict": "auto" if verdict == "auto" else "auto-contained"})
        else:
            share = contained or overlap >= REVIEW_OVERLAP_MIN
            if orgid and verdict in ("review_high", "review_low") and share:
                # Surface as a proposal (do not auto-apply); Stage 4 may upgrade.
                r = results[n]
                r.update(source_stage="stage3", confidence="review", org_id=orgid,
                         matched_name=cand_name, ftc_url=r0.get("ftc_url", ""))
                r["candidates"].append({"org_id": orgid, "name": cand_name, "verdict": verdict})
            still.append(n)

    # ── Stage 4: Companies House for the for-profit residue ─────────────────
    if ch is not None:
        for n in still:
            cands = ch.search_companies(n)
            if not cands:
                continue
            top = cands[0]
            conf = classify_company(top, n)
            orgid = orgid_from_company_number(top.get("company_number", ""))
            r = results[n]
            r["candidates"].append({"org_id": orgid, "name": top.get("title", ""),
                                    "status": top.get("company_status", ""), "verdict": conf})
            if conf == "auto" and orgid:
                ids = _harvest(ftc, orgid)   # re-check FTC by number for cross-ids
                r.update(source_stage="stage4", confidence="auto", org_id=orgid,
                         matched_name=top.get("title", ""),
                         org_type=ids.get("org_type_primary", "") or "company",
                         identifiers=ids.get("org_ids", []) or [orgid])
            elif r["confidence"] == "no_match":
                r.update(source_stage="stage4", confidence="review",
                         matched_name=top.get("title", ""))

    return [results[n] for n in names]


REVIEW_COLS = ["name", "source_stage", "confidence", "org_id", "matched_name",
               "org_type", "ftc_url", "identifiers", "candidates", "confirmed_org_id"]


def write_review_csv(results: List[Dict], path: str) -> None:
    """Write the propose-grade-confirm worksheet (resolve_orgs.py shape)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLS)
        w.writeheader()
        for r in results:
            row = {k: r.get(k, "") for k in REVIEW_COLS}
            row["identifiers"] = "; ".join(r.get("identifiers", []))
            row["candidates"] = " || ".join(
                "%s:%s[%s]" % (c.get("org_id", ""), c.get("name", ""), c.get("verdict", ""))
                for c in r.get("candidates", []))
            w.writerow(row)
