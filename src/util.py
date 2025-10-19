"""Shared utility helpers for the paper watcher Lambda."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PaperItem:
    """Normalized representation of a paper entry from any source."""

    source: str
    paper_id: str
    title: str
    authors: Sequence[str]
    published: Optional[datetime]
    url: str
    journal: Optional[str] = None
    summary: Optional[str] = None
    matched_keywords: Sequence[str] | None = None

    def published_iso(self) -> str:
        """Return the publication time as an ISO string in UTC."""
        if not self.published:
            return ""
        return self.published.astimezone(timezone.utc).isoformat()


def utcnow() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)


def window_start(hours: int) -> datetime:
    """Return the inclusive start timestamp for the search window."""
    return utcnow() - timedelta(hours=hours)


def parse_keywords(raw: str) -> List[str]:
    """Split comma-separated keywords into normalized lower-case tokens."""
    if not raw:
        return []
    keywords = [part.strip().lower() for part in raw.split(",")]
    return [kw for kw in keywords if kw]


def keywords_in_text(text: str, keywords: Sequence[str], mode: str) -> bool:
    """Evaluate keyword containment according to the configured match mode."""
    if not keywords:
        return True
    haystack = text.lower()
    if mode.upper() == "AND":
        return all(keyword in haystack for keyword in keywords)
    return any(keyword in haystack for keyword in keywords)


def highlight_text(text: str, keywords: Sequence[str]) -> str:
    """Wrap matched keywords with square brackets for emphasis."""
    if not text or not keywords:
        return text

    pattern = re.compile(
        "(" + "|".join(re.escape(kw) for kw in sorted(set(keywords), key=len, reverse=True)) + ")",
        re.IGNORECASE,
    )

    def replacer(match: re.Match[str]) -> str:
        return f"[{match.group(0)}]"

    return pattern.sub(replacer, text)


def summarize_authors(authors: Sequence[str], max_names: int = 5) -> str:
    """Create a compact author summary respecting the maximum number of names."""
    cleaned = [author for author in authors if author]
    if not cleaned:
        return "Unknown"
    if len(cleaned) <= max_names:
        return ", ".join(cleaned)
    remainder = len(cleaned) - max_names
    return f"{', '.join(cleaned[:max_names])}, 외 {remainder}명"


def build_matcher_text(parts: Iterable[str | None]) -> str:
    """Join multiple text fragments into a single string for keyword matching."""
    return " ".join(part for part in parts if part)


def sanitize_header(value: str) -> str:
    """Validate email header values to mitigate header injection."""
    if "\r" in value or "\n" in value:
        raise ValueError("Header values must not contain CR/LF characters")
    return value