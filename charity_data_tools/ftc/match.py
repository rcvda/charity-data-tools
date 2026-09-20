"""Name-matching helpers shared across the resolver.

The resolver used to treat a name as a match *only* when it normalised to an
exact string equal to the candidate's registered name. That is too strict for
real registers: an organisation's **trading name** is routinely shorter than,
or word-ordered differently from, its **registered name** —

    "Acme Group"            vs  "Acme Housing Group Limited"
    "Coast Migration …"     vs  "Coast Strategic Migration …"

so a correct, same-type, high-scoring candidate was scored ``review`` and then
discarded. These helpers add **core-token containment** — comparing names after
dropping legal-form, stopword and filler tokens — so a trading name that is
fully contained in the registered name is recognised.

Containment/overlap is a *proposal* signal, not licence to auto-apply on its
own: a match that rests only on generic descriptor words ("Wellbeing Centre",
"Friends of … Cemetery") or on shared place-names is category/geography noise,
not identity. :func:`shares_distinctive` guards against that — a match must
share at least one token that is not in the generic set. Callers scoping to a
region can extend the generic set with local place-names via the ``generic``
argument (kept OUT of this general-purpose module).
"""

import re
from typing import Optional, Set

# Legal-form tokens and English stopwords ignored when comparing two org names.
# Stopwords ("and", "of"…) are pure noise that otherwise inflate overlap
# ("A and B District" vs "A and B Borough Council" share the empty-value "and").
LEGAL_TOKENS: Set[str] = {
    "ltd", "limited", "plc", "llp", "lp", "cic", "cio", "co", "company",
    "uk", "the", "group", "holdings", "inc", "llc",
    # stopwords
    "and", "of", "for", "in", "on", "to", "at", "by", "or", "a", "an",
}

# Low-information tokens a match must NOT rest on *alone*: generic
# category/descriptor words (and compass directions). Two orgs sharing only
# these ("X Wellbeing Centre" vs "Y Wellbeing Centres"; "Friends of X Cemetery"
# vs "Friends of Y Cemetery") are NOT the same org. Identity words (an org's own
# distinctive name, a specific place-name) are deliberately absent so real
# matches survive. This module is general-purpose and holds **no** specific
# place-names — a region-scoped caller passes its local geography via the
# ``generic`` argument of :func:`shares_distinctive`.
GENERIC_TOKENS: Set[str] = {
    "friends", "cemetery", "wellbeing", "centre", "centres", "center",
    "community", "association", "borough", "council", "office", "society",
    "network", "support", "services", "service", "trust", "foundation",
    "charity", "charitable", "organisation", "organization", "project", "projects",
    "north", "south", "east", "west",
}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def core_tokens(s: str) -> Set[str]:
    """Return the distinctive lowercase tokens of *s* (legal/filler/stopwords removed).

    Examples::

        core_tokens("Acme Group")                 # -> {"acme"}
        core_tokens("Acme Housing Group Limited")  # -> {"acme", "housing"}
        core_tokens("Ashvale and District")        # -> {"ashvale", "district"}
    """
    s = (s or "").lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    return {t for t in s.split() if t and t not in LEGAL_TOKENS}


def contains(query: str, candidate: str) -> bool:
    """True when every distinctive token of *query* appears in *candidate*.

    This is the trading-name-inside-registered-name test: "Acme Group"
    (core {acme}) is contained in "Acme Housing Group Limited"
    (core {acme, housing}). Empty query cores never match.
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
    as an alias is recognised even when shorter than the registered name.
    """
    return any(contains(query, c) for c in candidates if c)


def best_overlap(query: str, candidates) -> float:
    """Highest token overlap of *query* against any of the *candidates* names."""
    return max((token_overlap(query, c) for c in candidates if c), default=0.0)


def shares_distinctive(a: str, b: str, generic: Optional[Set[str]] = None) -> bool:
    """True when *a* and *b* share at least one token that is not generic.

    A safeguard against matches resting only on category words (or, for a
    region-scoped caller, place-names): the two names must have a real identity
    token in common. Pass ``generic`` to extend :data:`GENERIC_TOKENS` (e.g.
    with local place-names) without hardcoding geography into this module.
    """
    stop = GENERIC_TOKENS if generic is None else (GENERIC_TOKENS | generic)
    shared = core_tokens(a) & core_tokens(b)
    return any(t not in stop for t in shared)


def shares_distinctive_any(query: str, candidates, generic: Optional[Set[str]] = None) -> bool:
    """True when *query* shares a distinctive token with ANY of *candidates*."""
    return any(shares_distinctive(query, c, generic=generic) for c in candidates if c)
