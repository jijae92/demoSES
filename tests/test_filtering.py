from __future__ import annotations

from datetime import datetime

from pipeline.filtering import filter_items
from util import PaperItem


def _make_item(paper_id: str, title: str) -> PaperItem:
    return PaperItem(
        source="crossref",
        paper_id=paper_id,
        title=title,
        authors=(),
        published=datetime.utcnow(),
        url="https://example.com",
        journal="Nature",
    )


def test_filter_items_and_mode():
    items = {
        "crossref": [
            _make_item("a1", "Interferon therapy improves cancer outcomes"),
            _make_item("a2", "Interferon study"),
        ]
    }

    filtered, stats = filter_items(items, keywords=("interferon", "therapy"), match_mode="AND")

    assert stats.total == 2
    assert stats.matched == 1
    assert stats.unique == 1
    assert list(filtered["crossref"][0].matched_keywords) == ["interferon", "therapy"]


def test_filter_items_deduplicates_by_id():
    duplicate = _make_item("dup", "Tumor immune therapy advances")
    items = {"rss": [duplicate, duplicate]}

    filtered, stats = filter_items(items, keywords=("tumor",), match_mode="OR")

    assert stats.matched == 2
    assert len(filtered["rss"]) == 1
