"""Name-matching helpers shared across the resolver.

The resolver used to treat a name as a match *only* when it normalised to an
exact string equal to the candidate's registered name. That is too strict for
real registers: an organisation's **trading name** is routinely shorter than,
or word-ordered differently from, its **registered name** —

    "Acme Group"            vs  "Acme Housing Group Limited"
    "North East Migration …"    vs  "North East Strategic Migration …"

so a correct, same-type, high-scoring candidate was scored ``review`` and then
discarded. These helpers add **core-token containment** — comparing names after
dropping legal-form and filler tokens — so a trading name that is fully
contained in the registered name is recognised.

Containment is a *proposal* signal, not licence to auto-apply on its own: a
short two-token query can be contained in an unrelated longer name. Callers
auto-accept a containment match only with a second corroborating signal (e.g.
the candidate's HQ falls in the target geography); otherwise they surface it as
a ``review`` proposal for human confirmation.
"""

import re
from typing import Set

# Legal-form and filler tokens ignored when comparing two organisation names.
# Kept deliberately tight — only genuinely non-distinctive words — so that
# containment stays meaningful (e.g. "housing", "trust", "association" are NOT
# here; they carry identity).
LEGAL_TOKENS: Set[str] = {
    "ltd", "limited", "plc", "llp", "lp", "cic", "cio", "co", "company",
    "uk", "the", "group", "holdings", "inc", "llc",
}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def core_tokens(s: str) -> Set[str]:
    """Return the distinctive lowercase tokens of *s* (legal/filler removed).

    Examples::

        core_tokens("Acme Group")                 # -> {"Acme"}
        core_tokens("Acme Housing Group Limited")  # -> {"Acme", "housing"}
        core_tokens("The Harbour Trust UK Ltd")      # -> {"Harbour", "trust"}
    """
    s = (s or "").lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    return {t for t in s.split() if t and t not in LEGAL_TOKENS}


def contains(query: str, candidate: str) -> bool:
    """True when every distinctive token of *query* appears in *candidate*.

    This is the trading-name-inside-registered-name test: "Acme Group"
    (core {Acme}) is contained in "Acme Housing Group Limited"
    (core {Acme, housing}). Empty query cores never match.
    """
    q = core_tokens(query)
    return bool(q) and q <= core_tokens(candidate)


def token_overlap(a: str, b: str) -> float:
    """Jaccard overlap of the two names' core-token sets (0.0–1.0).

    A softer signal than :func:`contains` for ranking review candidates when
    neither name is fully contained in the other.
    """
    ta, tb = core_tokens(a), core_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def contains_any(query: str, candidates) -> bool:
    """True when *query* is contained in ANY of the *candidates* names.

    Used to cross-reference a query against an organisation's registered name
    *and* its FTC ``alternateName`` aliases — so a trading/brand name registered
    as an alias ("Harbour Supported Living" as an alias of the Harbour
    parent) is recognised.
    """
    return any(contains(query, c) for c in candidates if c)


def best_overlap(query: str, candidates) -> float:
    """Highest token overlap of *query* against any of the *candidates* names."""
    return max((token_overlap(query, c) for c in candidates if c), default=0.0)
