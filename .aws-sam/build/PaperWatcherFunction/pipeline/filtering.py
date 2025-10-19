"""Post-fetch filtering utilities."""
from __future__ import annotations

import logging
import re
import string
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Mapping, MutableMapping, Sequence, Tuple

from util import PaperItem, highlight_text

LOGGER = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_PUNCTUATION_RE = re.compile(rf"[{re.escape(string.punctuation)}]")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class FilterStats:
    """Summary statistics for filtering stages."""

    post_fetch: int
    post_keyword: int
    post_dedup: int

    def as_dict(self, post_seen: int | None = None) -> Dict[str, int]:
        summary: Dict[str, int] = {
            "post_fetch": self.post_fetch,
            "post_keyword": self.post_keyword,
            "post_dedup": self.post_dedup,
            "total": self.post_fetch,
            "matched": self.post_keyword,
            "unique": self.post_dedup,
        }
        if post_seen is not None:
            summary["post_seen"] = post_seen
        return summary


def _strip_html(value: str) -> str:
    return _TAG_RE.sub(" ", value)


def _normalize_field(value: str | None) -> str:
    if not value:
        return ""
    lowered = _strip_html(value).lower()
    without_punct = _PUNCTUATION_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", without_punct).strip()


def _prepare_keywords(keywords: Sequence[str]) -> Sequence[Tuple[str, str]]:
    prepared: list[Tuple[str, str]] = []
    for raw in keywords:
        if not raw:
            continue
        candidate = raw.strip().lower()
        if not candidate:
            continue
        is_quoted = len(candidate) >= 2 and candidate.startswith('"') and candidate.endswith('"')
        if is_quoted:
            candidate = candidate[1:-1]
        candidate = candidate.strip()
        normalized = _normalize_field(candidate)
        if not normalized:
            continue
        prepared.append((normalized, candidate))
    return tuple(prepared)


def keyword_match(
    title: str | None,
    summary: str | None,
    keywords: Sequence[str],
    match_mode: str,
) -> tuple[bool, tuple[str, ...]]:
    """Evaluate keyword containment against title/summary content."""

    prepared_keywords = _prepare_keywords(keywords)
    if not prepared_keywords:
        return True, ()

    normalized_title = _normalize_field(title)
    normalized_summary = _normalize_field(summary)
    haystacks = tuple(filter(None, (normalized_title, normalized_summary)))
    if not haystacks:
        return False, ()

    mode = match_mode.upper()
    matches: list[str] = []
    matched_tokens: set[str] = set()

    for normalized, original in prepared_keywords:
        found = any(normalized in haystack for haystack in haystacks)
        if found:
            if original not in matched_tokens:
                matched_tokens.add(original)
                matches.append(original)
        elif mode == "AND":
            return False, tuple(matches)

    if mode == "AND":
        return len(matches) == len(prepared_keywords), tuple(matches)
    return bool(matches), tuple(matches)


def filter_items(
    items_by_source: Mapping[str, Sequence[PaperItem]],
    keywords: Sequence[str],
    match_mode: str,
) -> tuple[Dict[str, list[PaperItem]], FilterStats]:
    """Filter items by keywords and deduplicate by paper_id."""

    total_candidates = sum(len(items) for items in items_by_source.values())
    matched_candidates = 0
    seen_ids: set[str] = set()
    filtered: Dict[str, list[PaperItem]] = defaultdict(list)

    for source, items in items_by_source.items():
        for item in items:
            if item.matched_keywords:
                matched = True
                matched_terms = tuple(item.matched_keywords)
            else:
                matched, matched_terms = keyword_match(item.title, item.summary, keywords, match_mode)
            if not matched:
                continue
            matched_candidates += 1
            paper_id = item.paper_id.lower()
            if paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)
            if matched_terms:
                highlight_terms = tuple(dict.fromkeys(matched_terms))
                item.title = highlight_text(item.title, highlight_terms)
                if item.summary:
                    item.summary = highlight_text(item.summary, highlight_terms)
                item.matched_keywords = highlight_terms
            filtered[source].append(item)

    stats = FilterStats(
        post_fetch=total_candidates,
        post_keyword=matched_candidates,
        post_dedup=len(seen_ids),
    )

    LOGGER.info(
        "FILTER pipeline counts: pre_fetch=%d post_fetch=%d post_keyword=%d post_dedup=%d",
        total_candidates,
        total_candidates,
        matched_candidates,
        len(seen_ids),
    )

    return {source: entries for source, entries in filtered.items()}, stats
