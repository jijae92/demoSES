"""Crossref source integration."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Sequence

import requests
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from util import PaperItem, build_matcher_text, highlight_text, keywords_in_text

LOGGER = logging.getLogger(__name__)

CROSSREF_URL = "https://api.crossref.org/works"
JOURNALS = ["Nature", "Cell", "Science"]
DEFAULT_TIMEOUT = 10


class RateLimitError(Exception):
    """Raised when Crossref responds with a rate-limit signal."""


def _extract_date(message: Dict[str, object]) -> datetime | None:
    date_fields = [
        "published-print",
        "published-online",
        "issued",
        "created",
        "deposited",
        "indexed",
    ]
    for field in date_fields:
        value = message.get(field)
        if isinstance(value, dict):
            date_parts = value.get("date-parts")
            if isinstance(date_parts, list) and date_parts:
                parts = date_parts[0]
                if isinstance(parts, list) and parts:
                    year = int(parts[0])
                    month = int(parts[1]) if len(parts) > 1 else 1
                    day = int(parts[2]) if len(parts) > 2 else 1
                    return datetime(year, month, day, tzinfo=timezone.utc)
            date_time = value.get("date-time")
            if isinstance(date_time, str):
                try:
                    return datetime.fromisoformat(date_time.replace("Z", "+00:00"))
                except ValueError:
                    continue
    return None


def _cleanup_abstract(raw: str | None) -> str | None:
    if not raw:
        return None
    return requests.utils.unquote(_strip_tags(raw))


def _strip_tags(raw: str) -> str:
    text = []
    in_tag = False
    for char in raw:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            continue
        if not in_tag:
            text.append(char)
    return "".join(text)


def _collect_authors(message: Dict[str, object]) -> List[str]:
    authors: List[str] = []
    raw_authors = message.get("author")
    if isinstance(raw_authors, list):
        for entry in raw_authors:
            if not isinstance(entry, dict):
                continue
            given = entry.get("given")
            family = entry.get("family")
            parts = [part for part in [given, family] if isinstance(part, str)]
            if parts:
                authors.append(" ".join(parts))
    return authors


def _build_query(keywords: Sequence[str], match_mode: str) -> str | None:
    if not keywords:
        return None
    connector = " AND " if match_mode.upper() == "AND" else " OR "
    return connector.join(f'"{keyword}"' for keyword in keywords)


@retry(
    retry=retry_if_exception_type((requests.RequestException, RateLimitError)),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _perform_request(session: requests.Session, params: Dict[str, str]) -> Dict[str, object]:
    response = session.get(CROSSREF_URL, params=params, timeout=DEFAULT_TIMEOUT)
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        delay = int(retry_after) if retry_after and retry_after.isdigit() else 5
        LOGGER.warning("Crossref rate limited, sleeping %s seconds", delay)
        time.sleep(delay)
        raise RateLimitError("Crossref rate limited")
    response.raise_for_status()
    return response.json()


def fetch_crossref(
    keywords: Sequence[str],
    match_mode: str,
    window_start_dt: datetime,
    user_agent: str,
) -> List[PaperItem]:
    """Fetch papers from Crossref honoring the configured filters."""
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": user_agent})

    window_iso = window_start_dt.date().isoformat()
    keyword_query = _build_query(keywords, match_mode)
    items: List[PaperItem] = []

    for journal in JOURNALS:
        params = {
            "filter": f"container-title:{journal},from-pub-date:{window_iso},from-index-date:{window_iso}",
            "rows": "100",
            "sort": "published",
            "order": "desc",
        }
        if keyword_query:
            params["query"] = keyword_query
        try:
            payload = _perform_request(session, params)
        except RetryError:
            LOGGER.exception("Failed to fetch Crossref data for %s", journal)
            continue
        message = payload.get("message") if isinstance(payload, dict) else None
        records = message.get("items") if isinstance(message, dict) else None
        if not isinstance(records, list):
            LOGGER.warning("Crossref returned unexpected payload for %s", journal)
            continue
        LOGGER.info("Crossref returned %d records for %s", len(records), journal)
        for record in records:
            if not isinstance(record, dict):
                continue
            doi = record.get("DOI")
            if not isinstance(doi, str):
                continue
            title_entries = record.get("title")
            title = title_entries[0] if isinstance(title_entries, list) and title_entries else None
            if not isinstance(title, str):
                continue
            published = _extract_date(record)
            if published and published < window_start_dt:
                continue
            abstract_raw = record.get("abstract") if isinstance(record.get("abstract"), str) else None
            abstract = _cleanup_abstract(abstract_raw)
            authors = _collect_authors(record)
            url = record.get("URL") if isinstance(record.get("URL"), str) else f"https://doi.org/{doi}"
            text_to_match = build_matcher_text([title, abstract or ""])
            text_lower = text_to_match.lower()
            if not keywords_in_text(text_lower, keywords, match_mode):
                continue
            matched = [kw for kw in keywords if kw in text_lower]
            items.append(
                PaperItem(
                    source="crossref",
                    paper_id=doi.lower(),
                    title=highlight_text(title, keywords),
                    authors=authors,
                    published=published,
                    url=url,
                    journal=journal,
                    summary=highlight_text(abstract, keywords) if abstract else None,
                    matched_keywords=matched,
                )
            )
    return items