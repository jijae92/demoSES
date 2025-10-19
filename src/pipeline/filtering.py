"""Post-fetch filtering utilities."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, MutableMapping, Sequence

from util import PaperItem, build_matcher_text


@dataclass(slots=True)
class FilterStats:
    """Summary statistics for filtering stages."""

    total: int
    matched: int
    unique: int


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    for char in "-(),":
        lowered = lowered.replace(char, " ")
    return " ".join(lowered.split())


def _match_keywords(text: str, keywords: Sequence[str], mode: str) -> Sequence[str]:
    if not keywords:
        return ()
    hits = [kw for kw in keywords if kw in text]
    if mode.upper() == "AND":
        return tuple(hits) if len(hits) == len(keywords) else ()
    return tuple(hits) if hits else ()


def filter_items(
    items_by_source: Mapping[str, Sequence[PaperItem]],
    keywords: Sequence[str],
    match_mode: str,
) -> tuple[Dict[str, list[PaperItem]], FilterStats]:
    """Filter items by keywords and deduplicate by paper_id."""
    total = 0
    matched = 0
    seen_ids: set[str] = set()
    filtered: Dict[str, list[PaperItem]] = defaultdict(list)

    normalized_keywords = tuple(keyword.lower() for keyword in keywords)

    for source, items in items_by_source.items():
        for item in items:
            total += 1
            matcher_text = build_matcher_text(
                [
                    item.title,
                    item.summary,
                    item.journal,
                    item.url,
                ]
            )
            normalized_text = _normalize_text(matcher_text)
            hits = _match_keywords(normalized_text, normalized_keywords, match_mode)
            if not hits:
                continue
            matched += 1
            paper_id = item.paper_id.lower()
            if paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)
            item.matched_keywords = hits
            filtered[source].append(item)

    stats = FilterStats(total=total, matched=matched, unique=len(seen_ids))
    return {source: entries for source, entries in filtered.items()}, stats
