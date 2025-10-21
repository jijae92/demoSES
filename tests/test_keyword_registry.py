import pytest

from backend.search.keyword_registry import (
    load_keywords,
    resolve,
    validate_only,
)
from backend.search.query_parser import LENIENT, STRICT, parse


def test_load_keywords_caches_instance():
    first = load_keywords(force_reload=True)
    second = load_keywords()
    assert first is second


def test_resolve_exact_term():
    match = resolve("password reset", registry=load_keywords())
    assert match == {
        "canonical_id": "password_reset",
        "matched_term": "password reset",
        "mode": "exact",
    }


def test_resolve_synonym_term():
    match = resolve("credential reset")
    assert match == {
        "canonical_id": "password_reset",
        "matched_term": "credential reset",
        "mode": "synonym",
    }


def test_resolve_typo_term():
    match = resolve("passwrod reset")
    assert match == {
        "canonical_id": "password_reset",
        "matched_term": "passwrod reset",
        "mode": "typo",
    }


def test_resolve_unknown_returns_none():
    assert resolve("unauthorized recovery") is None


def test_validate_only_strict_raises_on_unknown():
    with pytest.raises(ValueError):
        validate_only("suspicious activity")


def test_validate_only_lenient_allows_unknown():
    assert validate_only("suspicious activity", lenient=True) is None


def test_registry_fields_preserved():
    registry = load_keywords()
    entry = registry.get("password_reset")
    assert entry.negative_terms == ("promo", "newsletter")
    assert entry.filters["has_attachment"] is False
    assert entry.boosts["subject"] == 4.0
    assert entry.boosts["from_suffix"] == ["@security.", "@no-reply."]
    assert entry.rerank["recency_decay"]["scale"] == "7d"


def test_query_parser_strict_produces_must_not_tokens():
    parsed = parse("urgent password reset please", policy=STRICT)
    assert parsed.canonical_id == "password_reset"
    assert parsed.must_not == ("urgent", "please")
    assert parsed.ignored == ()


def test_query_parser_lenient_ignores_remainder_tokens():
    parsed = parse("urgent password reset please", policy=LENIENT)
    assert parsed.canonical_id == "password_reset"
    assert parsed.must_not == ()
    assert parsed.ignored == ("urgent", "please")


def test_query_parser_lenient_without_keyword_returns_none():
    assert parse("system outage", policy=LENIENT) is None


def test_query_parser_strict_without_keyword_raises():
    with pytest.raises(ValueError):
        parse("system outage", policy=STRICT)
