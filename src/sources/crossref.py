"""Crossref source integration."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Sequence

import requests
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline.filtering import keyword_match
from util import PaperItem

LOGGER = logging.getLogger(__name__)

CROSSREF_URL = "https://api.crossref.org/works"
# Nature, Cell, Science and their family journals (23 total)
JOURNALS = [
    # Nature family (9)
    "Nature",
    "Nature Medicine",
    "Nature Immunology",
    "Nature Biotechnology",
    "Nature Genetics",
    "Nature Cancer",
    "Nature Communications",
    "Nature Cell Biology",
    "Nature Chemical Biology",
    # Cell family (9)
    "Cell",
    "Cell Reports",
    "Immunity",
    "Cancer Cell",
    "Molecular Cell",
    "Cell Genomics",
    "Trends in Cancer",
    "Trends in Genetics",
    "Trends in Immunology",
    # Science family (5)
    "Science",
    "Science Immunology",
    "Science Signaling",
    "Science Advances",
    "Science Translational Medicine",
]
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


def _build_query(keywords: Sequence[str]) -> str | None:
    tokens: List[str] = []
    for keyword in keywords:
        if not keyword:
            continue
        candidate = keyword.strip().lower()
        if not candidate:
            continue
        if candidate.startswith('"') and candidate.endswith('"') and len(candidate) > 1:
            candidate = candidate[1:-1]
        candidate = candidate.strip()
        if candidate:
            tokens.append(candidate)
    if not tokens:
        return None
    return " ".join(tokens)


@retry(
    retry=retry_if_exception_type((requests.RequestException, RateLimitError)),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _perform_request(session: requests.Session, params: Dict[str, str]) -> requests.Response:
    response = session.get(CROSSREF_URL, params=params, timeout=DEFAULT_TIMEOUT)
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        delay = int(retry_after) if retry_after and retry_after.isdigit() else 5
        LOGGER.warning("Crossref rate limited, sleeping %s seconds", delay)
        time.sleep(delay)
        raise RateLimitError("Crossref rate limited")
    response.raise_for_status()
    return response


def _mask_params(params: Dict[str, str]) -> Dict[str, str]:
    masked: Dict[str, str] = {}
    for key, value in params.items():
        if key in {"mailto"}:
            masked[key] = "***"
        else:
            masked[key] = value
    return masked


def fetch_crossref(
    keywords: Sequence[str],
    match_mode: str,
    window_start_dt: datetime,
    window_end_dt: datetime,
    user_agent: str,
    contact_email: str | None,
) -> List[PaperItem]:
    """Fetch papers from Crossref honoring the configured filters."""
    session = requests.Session()
    if contact_email:
        header_agent = f"PaperWatcher/1.0 (mailto:{contact_email})"
    else:
        header_agent = user_agent
    session.headers.update({"Accept": "application/json", "User-Agent": header_agent})

    start_date = window_start_dt.date().isoformat()
    end_date = window_end_dt.date().isoformat()
    keyword_query = _build_query(keywords)
    items: List[PaperItem] = []

    for journal in JOURNALS:
        matched_count = 0
        params = {
            "filter": ",".join(
                [
                    f"container-title:{journal}",
                    f"from-pub-date:{start_date}",
                    f"until-pub-date:{end_date}",
                ]
            ),
            "rows": "200",
            "sort": "published",
            "order": "desc",
            "select": "DOI,title,abstract,container-title,issued,URL,type,subject,author",
        }
        if keyword_query:
            params["query.title"] = keyword_query
            if match_mode.upper() == "AND":
                params["query"] = keyword_query
        if contact_email:
            params["mailto"] = contact_email
        LOGGER.info(
            "CROSSREF request: journal=%s window=%s~%s mode=%s keywords=%s params=%s",
            journal,
            start_date,
            end_date,
            match_mode.upper(),
            list(keywords),
            _mask_params(params),
        )
        try:
            response = _perform_request(session, params)
        except RetryError:
            LOGGER.exception("Failed to fetch Crossref data for %s", journal)
            continue
        payload = response.json()
        message = payload.get("message") if isinstance(payload, dict) else None
        records = message.get("items") if isinstance(message, dict) else None
        if not isinstance(records, list):
            LOGGER.warning("Crossref returned unexpected payload for %s", journal)
            continue
        total_results = message.get("total-results") if isinstance(message, dict) else "?"
        safe_url = response.url
        if safe_url and contact_email:
            safe_url = safe_url.replace(contact_email, "***")
        LOGGER.info(
            "CROSSREF response: status=%s total=%s returned=%d url=%s",
            response.status_code,
            total_results,
            len(records),
            safe_url,
        )
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
            matched, matched_terms = keyword_match(title, abstract, keywords, match_mode)
            if not matched:
                continue
            matched_count += 1
            items.append(
                PaperItem(
                    source="crossref",
                    paper_id=doi.lower(),
                    title=title,
                    authors=authors,
                    published=published,
                    url=url,
                    journal=journal,
                    summary=abstract,
                    matched_keywords=matched_terms,
                )
            )
        LOGGER.info(
            "CROSSREF processed: journal=%s returned=%d matched=%d window=%s~%s",
            journal,
            len(records),
            matched_count,
            start_date,
            end_date,
        )
    return items
