"""Unit tests for the core-token name matcher (no network)."""
from charity_data_tools.ftc.match import (
    core_tokens, contains, token_overlap, contains_any, best_overlap, LEGAL_TOKENS,
)


def test_core_tokens_strips_legal_and_filler():
    assert core_tokens("Acme Group") == {"Acme"}
    assert core_tokens("Acme Housing Group Limited") == {"Acme", "housing"}
    assert core_tokens("The Harbour Trust UK Ltd") == {"Harbour", "trust"}
    # identity-bearing words are NOT stripped
    assert "housing" not in LEGAL_TOKENS
    assert "association" in core_tokens("Harbour Housing Association")


def test_contains_trading_name_in_registered_name():
    assert contains("Acme Group", "Acme Housing Group Limited")
    assert contains("North East Migration Partnership",
                    "North East Strategic Migration Partnership")
    # not contained: a distinct token is missing from the candidate
    assert not contains("Beacon Mines", "The Mines Advisory Group")
    # empty query never matches
    assert not contains("Ltd", "Anything Ltd")


def test_token_overlap():
    assert token_overlap("Coast Community Housing", "Coast & Country Housing") == 0.5
    assert token_overlap("Beacon Mines", "The Mines Advisory Group") < 0.4
    assert token_overlap("", "Anything") == 0.0


def test_contains_any_and_best_overlap_over_aliases():
    # brand name matches via an alias, not the primary registered name
    aliases = ["Harbour Housing Association", "Harbour Supported Living"]
    assert contains_any("Harbour Supported Living", aliases)
    assert not contains_any("Totally Different Org", aliases)
    assert best_overlap("Harbour Supported Living", aliases) == 1.0
    assert best_overlap("Nothing Alike", ["Coast & Country Housing"]) < 0.3
