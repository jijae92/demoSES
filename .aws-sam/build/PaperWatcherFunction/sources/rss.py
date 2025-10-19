"""RSS fallback source integration."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Sequence

import feedparser
import requests
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from util import PaperItem, build_matcher_text, highlight_text, keywords_in_text

LOGGER = logging.getLogger(__name__)

FEEDS = {
    "Nature": "https://www.nature.com/nature.rss",
    "Cell": "https://www.cell.com/cell/current.rss",
    "Science": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
}
DEFAULT_TIMEOUT = 10


def _parse_date(entry: feedparser.FeedParserDict) -> datetime | None:
    published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published_parsed:
        return None
    return datetime(*published_parsed[:6], tzinfo=timezone.utc)


def _extract_authors(entry: feedparser.FeedParserDict) -> List[str]:
    authors: List[str] = []
    raw_authors = entry.get("authors")
    if isinstance(raw_authors, list):
        for author in raw_authors:
            name = author.get("name") if isinstance(author, dict) else None
            if name:
                authors.append(name)
    return authors


def _extract_identifier(entry: feedparser.FeedParserDict) -> str | None:
    for key in ("id", "guid", "dc_identifier"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    links = entry.get("links")
    if isinstance(links, list):
        for link in links:
            href = link.get("href") if isinstance(link, dict) else None
            if href:
                return href
    link = entry.get("link")
    if isinstance(link, str) and link:
        return link
    return None


def _maybe_extract_doi(identifier: str) -> str | None:
    if "doi.org" in identifier:
        return identifier.split("doi.org/")[-1]
    return None


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _download_feed(url: str, headers: Dict[str, str]) -> bytes:
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.content


def fetch_rss(
    keywords: Sequence[str],
    match_mode: str,
    window_start_dt: datetime,
    window_end_dt: datetime,
    user_agent: str,
) -> List[PaperItem]:
    """Fetch feed entries from RSS sources."""
    headers = {"User-Agent": user_agent}
    items: List[PaperItem] = []
    downloaded = 0
    parsed_ok = 0

    LOGGER.info(
        "RSS request: from=%s until=%s feeds=%d",
        window_start_dt.date().isoformat(),
        window_end_dt.date().isoformat(),
        len(FEEDS),
    )

    for journal, url in FEEDS.items():
        try:
            payload = _download_feed(url, headers)
            downloaded += 1
        except RetryError:
            LOGGER.exception("Failed to download RSS feed for %s", journal)
            continue
        feed = feedparser.parse(payload)
        if feed.bozo:
            LOGGER.warning("RSS parsing issue for %s: %s", journal, getattr(feed, "bozo_exception", "unknown"))
        else:
            parsed_ok += 1
        for entry in feed.entries:
            published = _parse_date(entry)
            if published and published < window_start_dt:
                continue
            identifier = _extract_identifier(entry)
            if not identifier:
                continue
            doi = _maybe_extract_doi(identifier)
            url_value = entry.get("link") if isinstance(entry.get("link"), str) else identifier
            title = entry.get("title")
            if not isinstance(title, str):
                continue
            summary = entry.get("summary") if isinstance(entry.get("summary"), str) else None
            text_to_match = build_matcher_text([title, summary or ""])
            text_lower = text_to_match.lower()
            if not keywords_in_text(text_lower, keywords, match_mode):
                continue
            matched = [kw for kw in keywords if kw in text_lower]
            authors = _extract_authors(entry)
            items.append(
                PaperItem(
                    source="rss",
                    paper_id=doi.lower() if doi else identifier,
                    title=highlight_text(title, keywords),
                    authors=authors,
                    published=published,
                    url=url_value,
                    journal=journal,
                    summary=highlight_text(summary, keywords) if summary else None,
                    matched_keywords=matched,
                )
            )
    LOGGER.info(
        "RSS summary: feeds=%d downloaded=%d parsed=%d matched=%d",
        len(FEEDS),
        downloaded,
        parsed_ok,
        len(items),
    )
    return items
