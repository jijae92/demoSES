from __future__ import annotations

import pytest

from src.handler import _filter_seen_items
from src.util import PaperItem

pytestmark = pytest.mark.unit


class InMemoryRepository:
    """Minimal SeenRepository replacement for deduplication tests."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_seen(self, paper_id: str) -> bool:
        return paper_id in self._seen

    def mark_seen(self, items: list[PaperItem]) -> None:
        for item in items:
            self._seen.add(item.paper_id)

    def reset(self) -> None:
        self._seen.clear()


def _build_items() -> dict[str, list[PaperItem]]:
    return {
        "crossref": [
            PaperItem(
                source="crossref",
                paper_id="10.1000/alpha",
                title="PARP inhibition boosts interferon response",
                authors=("Alice Kim",),
                published=None,
                url="https://doi.org/10.1000/alpha",
            ),
            PaperItem(
                source="crossref",
                paper_id="10.1000/beta",
                title="STING agonists synergise with PARP blockade",
                authors=("Bob Lee",),
                published=None,
                url="https://doi.org/10.1000/beta",
            ),
        ]
    }


def test_filter_seen_items_respects_previous_runs():
    repository = InMemoryRepository()
    items_by_source = _build_items()

    first_run = _filter_seen_items(repository, items_by_source)
    assert len(first_run["crossref"]) == 2

    # Persist the seen state then rerun - should produce no new items.
    repository.mark_seen(first_run["crossref"])
    second_run = _filter_seen_items(repository, items_by_source)
    assert second_run == {}

    # Reset the repository and ensure items surface again.
    repository.reset()
    third_run = _filter_seen_items(repository, items_by_source)
    assert len(third_run["crossref"]) == 2
