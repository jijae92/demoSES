from __future__ import annotations

from datetime import datetime

from pipeline.filtering import filter_items, keyword_match
from util import PaperItem


def _make_item(paper_id: str, title: str, summary: str | None = None) -> PaperItem:
    return PaperItem(
        source="crossref",
        paper_id=paper_id,
        title=title,
        authors=(),
        published=datetime.utcnow(),
        url="https://example.com",
        journal="Nature",
        summary=summary,
    )


def test_filter_items_or_mode_title_or_summary():
    items = {
        "crossref": [
            _make_item("a1", "Interferon therapy improves outcomes"),
            _make_item("a2", "New innate immune axis", "Activation of STING pathway"),
            _make_item("a3", "Completely unrelated study"),
        ]
    }

    filtered, stats = filter_items(items, keywords=("interferon", "sting"), match_mode="OR")

    assert stats.post_fetch == 3
    assert stats.post_keyword == 2
    assert stats.post_dedup == 2
    assert len(filtered["crossref"]) == 2
    titles = {item.paper_id: item.title for item in filtered["crossref"]}
    assert "[Interferon] therapy" in titles["a1"]
    assert "[STING" in filtered["crossref"][1].summary


def test_filter_items_and_mode_requires_all_keywords():
    items = {
        "rss": [
            _make_item("r1", "Interferon priming enhances", "Downstream STING activation"),
            _make_item("r2", "Interferon priming study"),
            _make_item("r3", "Innate immunity", "STING signaling adapters"),
        ]
    }

    filtered, stats = filter_items(items, keywords=("interferon", "sting"), match_mode="AND")

    assert stats.post_fetch == 3
    assert stats.post_keyword == 1
    assert stats.post_dedup == 1
    assert list(filtered.keys()) == ["rss"]
    assert filtered["rss"][0].paper_id == "r1"
    assert "[STING" in filtered["rss"][0].summary


def test_keyword_match_phrase_detection():
    matched, keywords = keyword_match(
        title="Type I interferon response",
        summary="PARP inhibition sensitizes cells",
        keywords=("\"type I interferon\"", "parp"),
        match_mode="AND",
    )
    assert matched is True
    assert list(keywords) == ["type i interferon", "parp"]

    matched_fail, _ = keyword_match(
        title="Interferon-like response",
        summary="PARP activity",
        keywords=("\"type I interferon\"",),
        match_mode="OR",
    )
    assert matched_fail is False


def test_keyword_match_ignores_punctuation_and_case():
    matched, matched_terms = keyword_match(
        title="TYPE-I  interferon-driven signaling",
        summary="STING-dependent pathways",
        keywords=("Interferon", "sting"),
        match_mode="AND",
    )
    assert matched is True
    assert set(matched_terms) == {"interferon", "sting"}

    matched_single, _ = keyword_match(
        title="Adaptive immunity",
        summary="Signal transduction",
        keywords=("sting",),
        match_mode="OR",
    )
    assert matched_single is False
