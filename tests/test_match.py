"""Unit tests for the core-token name matcher (no network). Synthetic names only."""
from charity_data_tools.ftc.match import (
    core_tokens, contains, token_overlap, contains_any, best_overlap,
    shares_distinctive, shares_distinctive_any, LEGAL_TOKENS, GENERIC_TOKENS,
)


def test_core_tokens_strips_legal_and_filler():
    assert core_tokens("Acme Group") == {"acme"}
    assert core_tokens("Acme Housing Group Limited") == {"acme", "housing"}
    assert core_tokens("The Beacon Trust UK Ltd") == {"beacon", "trust"}
    # identity-bearing words are NOT stripped as legal/filler
    assert "housing" not in LEGAL_TOKENS
    assert "beacon" in core_tokens("Beacon Housing Association")


def test_stopwords_stripped():
    # "and" / "of" must not count as shared tokens
    assert core_tokens("Ashvale and Dale") == {"ashvale", "dale"}
    assert "and" not in core_tokens("Friends of Ashvale Cemetery")
    assert "of" not in core_tokens("Friends of Ashvale Cemetery")


def test_shares_distinctive():
    # only category/generic words in common → not distinctive
    assert not shares_distinctive("Friends of Ashvale Cemetery",
                                  "Friends of Beacon Cemetery")
    assert not shares_distinctive("Harbour Wellbeing Centre", "Meridian Wellbeing Centre")
    # only compass/generic overlap → not distinctive
    assert not shares_distinctive("North Community Trust", "North Community Foundation")
    # a real identity token in common → distinctive
    assert shares_distinctive("Acme Group", "Acme Housing Group Limited")
    assert shares_distinctive("Larkspur Routes", "Larkspur Routes Project")
    # caller-supplied extra generics (e.g. local place-names) can be excluded
    assert not shares_distinctive("Ashvale Bowls", "Ashvale Cricket", generic={"ashvale"})


def test_shares_distinctive_any_over_aliases():
    assert shares_distinctive_any("Harbour Supported Living",
                                  ["Harbour Housing Association", "Harbour Supported Living"])
    assert not shares_distinctive_any("Meridian Wellbeing Centre",
                                      ["Harbour Wellbeing Centre"])


def test_contains_trading_name_in_registered_name():
    assert contains("Acme Group", "Acme Housing Group Limited")
    assert contains("Coast Migration Partnership", "Coast Strategic Migration Partnership")
    # not contained: a distinct token is missing from the candidate
    assert not contains("Beacon Mines", "The Mines Advisory Group")
    # empty query never matches
    assert not contains("Ltd", "Anything Ltd")


def test_token_overlap():
    assert token_overlap("Coast Community Housing", "Coast Country Housing") == 0.5
    assert token_overlap("Beacon Mines", "The Mines Advisory Group") < 0.4
    assert token_overlap("", "Anything") == 0.0


def test_contains_any_and_best_overlap_over_aliases():
    aliases = ["Harbour Housing Association", "Harbour Supported Living"]
    assert contains_any("Harbour Supported Living", aliases)
    assert not contains_any("Totally Different Org", aliases)
    assert best_overlap("Harbour Supported Living", aliases) == 1.0
    assert best_overlap("Nothing Alike", ["Coast Country Housing"]) < 0.3


def test_module_holds_no_specific_placenames():
    # GENERIC_TOKENS is general-purpose: it must not bake in a specific locality.
    for placename in ("Ashvale", "Dale", "Coastshire", "Coast",
                      "Brookton", "Porthaven", "Westbrook"):
        assert placename not in GENERIC_TOKENS
