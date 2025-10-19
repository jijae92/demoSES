"""PubMed source integration."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Sequence, Tuple
from xml.etree import ElementTree

import requests
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline.filtering import keyword_match
from util import PaperItem

LOGGER = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DEFAULT_TIMEOUT = 10
MAX_BATCH = 200
JOURNAL_QUERY = '"Nature"[Journal] OR "Cell"[Journal] OR "Science"[Journal]'


def _build_keyword_query(keywords: Sequence[str], match_mode: str) -> str | None:
    if not keywords:
        return None
    terms: List[str] = []
    for keyword in keywords:
        if not keyword:
            continue
        candidate = keyword.strip()
        if not candidate:
            continue
        if candidate.startswith('"') and candidate.endswith('"') and len(candidate) > 1:
            candidate = candidate[1:-1]
        candidate = candidate.strip().lower()
        if not candidate:
            continue
        candidate = candidate.replace('"', '')
        quoted = f'"{candidate}"'
        terms.append(f"{quoted}[Title/Abstract]")
    if not terms:
        return None
    connector = " AND " if match_mode.upper() == "AND" else " OR "
    return connector.join(terms)


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _perform_request(url: str, params: Dict[str, str], headers: Dict[str, str]) -> requests.Response:
    response = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response


def fetch_pubmed(
    keywords: Sequence[str],
    match_mode: str,
    window_start_dt: datetime,
    window_end_dt: datetime,
    user_agent: str,
    api_key: str | None,
) -> List[PaperItem]:
    """Fetch papers from PubMed respecting the configured filters."""
    headers = {"User-Agent": user_agent}
    params_base = {
        "db": "pubmed",
        "retmax": str(MAX_BATCH),
        "retmode": "json",
    }
    if api_key:
        params_base["api_key"] = api_key
    keyword_query = _build_keyword_query(keywords, match_mode)
    window_start_date = window_start_dt.strftime("%Y/%m/%d")
    window_end_date = window_end_dt.strftime("%Y/%m/%d")

    items: List[PaperItem] = []
    term_components = [JOURNAL_QUERY]
    if keyword_query:
        term_components.append(f"({keyword_query})")
    term = " AND ".join(term_components)

    params = {
        **params_base,
        "term": term,
        "datetype": "pubdate",
        "mindate": window_start_date,
        "maxdate": window_end_date,
    }
    LOGGER.info(
        "PUBMED request: term=%s mindate=%s maxdate=%s retmax=%s",
        term,
        window_start_date,
        window_end_date,
        params["retmax"],
    )
    try:
        response = _perform_request(ESEARCH_URL, params, headers)
    except RetryError:
        LOGGER.exception("PubMed esearch failed")
        return items
    delay = 0.11 if api_key else 0.34
    time.sleep(delay)
    data = response.json()
    id_list = data.get("esearchresult", {}).get("idlist", [])
    LOGGER.info(
        "PUBMED response: status=%s returned=%d",
        response.status_code,
        len(id_list),
    )
    if not id_list:
        LOGGER.info(
            "PUBMED zero results: term=%s mindate=%s maxdate=%s",
            term,
            window_start_date,
            window_end_date,
        )
        return items

    matched_total = 0
    for batch_start in range(0, len(id_list), MAX_BATCH):
        batch_ids = id_list[batch_start : batch_start + MAX_BATCH]
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(batch_ids),
            "retmode": "xml",
        }
        if api_key:
            fetch_params["api_key"] = api_key
        try:
            fetch_response = _perform_request(EFETCH_URL, fetch_params, headers)
        except RetryError:
            LOGGER.exception("PubMed efetch failed")
            continue
        time.sleep(delay)
        batch_items, batch_matches = _parse_pubmed_response(
            fetch_response,
            keywords,
            match_mode,
            window_start_dt,
        )
        matched_total += batch_matches
        items.extend(batch_items)
    LOGGER.info(
        "PUBMED processed: ids=%d matched=%d window=%s~%s",
        len(id_list),
        matched_total,
        window_start_date,
        window_end_date,
    )
    return items


def _parse_pubmed_response(
    response: requests.Response,
    keywords: Sequence[str],
    match_mode: str,
    window_start_dt: datetime,
) -> Tuple[List[PaperItem], int]:
    items: List[PaperItem] = []
    matches = 0
    root = ElementTree.fromstring(response.content)
    for article in root.findall("PubmedArticle"):
        medline = article.find("MedlineCitation")
        if medline is None:
            continue
        article_data = medline.find("Article")
        if article_data is None:
            continue
        pmid = medline.findtext("PMID")
        title = article_data.findtext("ArticleTitle")
        if not pmid or not title:
            continue
        abstract = _collect_abstract(article_data)
        matched, matched_terms = keyword_match(title, abstract, keywords, match_mode)
        if not matched:
            continue
        published = _parse_date(article_data)
        if published and published < window_start_dt:
            continue
        matches += 1
        authors = _collect_authors(article_data)
        doi = _extract_doi(article)
        paper_id = (doi or pmid).lower()
        url = f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        items.append(
            PaperItem(
                source="pubmed",
                paper_id=paper_id,
                title=title,
                authors=authors,
                published=published,
                url=url,
                journal=None,
                summary=abstract,
                matched_keywords=matched_terms,
            )
        )
    return items, matches


def _collect_authors(article: ElementTree.Element) -> List[str]:
    authors: List[str] = []
    author_list = article.find("AuthorList")
    if author_list is None:
        return authors
    for author in author_list.findall("Author"):
        last_name = author.findtext("LastName")
        fore_name = author.findtext("ForeName")
        collective = author.findtext("CollectiveName")
        if collective:
            authors.append(collective)
            continue
        parts = [part for part in [fore_name, last_name] if part]
        if parts:
            authors.append(" ".join(parts))
    return authors


def _collect_abstract(article: ElementTree.Element) -> str:
    texts: List[str] = []
    for abstract_text in article.findall("Abstract/AbstractText"):
        if abstract_text.text:
            texts.append(abstract_text.text)
    return "\n".join(texts)


def _parse_date(article: ElementTree.Element) -> datetime | None:
    article_date = article.find("ArticleDate")
    if article_date is not None:
        return _build_date(article_date)
    journal_issue = article.find("Journal/JournalIssue/PubDate")
    if journal_issue is not None:
        return _build_date(journal_issue)
    return None


def _build_date(parent: ElementTree.Element) -> datetime | None:
    year_text = parent.findtext("Year")
    if not year_text:
        return None
    month_text = parent.findtext("Month")
    day_text = parent.findtext("Day")
    try:
        year = int(year_text)
        month = _parse_month(month_text) if month_text else 1
        day = int(day_text) if day_text and day_text.isdigit() else 1
    except ValueError:
        return None
    return datetime(year, month, day, tzinfo=timezone.utc)


def _parse_month(value: str) -> int:
    if value.isdigit():
        return int(value)
    try:
        return datetime.strptime(value[:3], "%b").month
    except ValueError:
        return 1


def _extract_doi(article: ElementTree.Element) -> str | None:
    article_id_list = article.find("PubmedData/ArticleIdList")
    if article_id_list is None:
        return None
    for article_id in article_id_list.findall("ArticleId"):
        if article_id.get("IdType") == "doi" and article_id.text:
            return article_id.text.strip()
    return None
