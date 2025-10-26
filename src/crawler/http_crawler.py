"""
HTTP direct crawler implementation.

Fetches configured source URLs directly and performs keyword matching
on extracted text content.
"""

import logging
import re
from typing import Sequence
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .interface import ICrawler, ResultItem
from .utils import (
    RateLimiter,
    RobotsTxtChecker,
    deduplicate_results,
    filter_empty_results,
)

logger = logging.getLogger(__name__)


class HttpCrawler(ICrawler):
    """
    HTTP direct crawler for specified source URLs.

    Fetches pages directly, extracts text, and performs keyword matching.
    Respects robots.txt and implements rate limiting.
    """

    DEFAULT_USER_AGENT = "PaperWatcher/1.0 (HTTP Crawler; +https://github.com/jijae92/demoSES)"

    def __init__(
        self,
        source_urls: Sequence[str],
        user_agent: str | None = None,
        timeout: int = 30,
        max_snippet_length: int = 300,
        respect_robots_txt: bool = True,
    ):
        """
        Initialize HTTP crawler.

        Args:
            source_urls: List of URLs to crawl
            user_agent: Custom user agent string
            timeout: Request timeout in seconds
            max_snippet_length: Maximum length for extracted snippets
            respect_robots_txt: Whether to check robots.txt before crawling

        Raises:
            ValueError: If source_urls is empty
        """
        if not source_urls or len(source_urls) == 0:
            raise ValueError("source_urls cannot be empty")

        self.source_urls = list(source_urls)
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.timeout = timeout
        self.max_snippet_length = max_snippet_length

        self.rate_limiter = RateLimiter(min_delay=2.0, max_delay=60.0)
        self.robots_checker = RobotsTxtChecker(self.user_agent) if respect_robots_txt else None

        logger.info(f"HttpCrawler initialized with {len(self.source_urls)} sources")

    def search(self, keywords: Sequence[str]) -> list[ResultItem]:
        """
        Crawl source URLs and extract content matching keywords.

        Args:
            keywords: List of keywords to search for

        Returns:
            List of ResultItem objects containing matches

        Raises:
            ValueError: If keywords list is empty
        """
        if not keywords or len(keywords) == 0:
            raise ValueError("Keywords list cannot be empty")

        logger.info(f"Crawling {len(self.source_urls)} sources for keywords: {keywords}")

        all_results = []
        success_count = 0
        skipped_count = 0
        failed_count = 0

        for url in self.source_urls:
            try:
                # Check robots.txt
                if self.robots_checker and not self.robots_checker.is_allowed(url):
                    logger.info(f"Skipped (robots.txt): {url}")
                    skipped_count += 1
                    continue

                # Rate limiting
                host = urlparse(url).netloc
                self.rate_limiter.wait(host)

                # Fetch and parse
                results = self._crawl_url(url, keywords)
                all_results.extend(results)

                self.rate_limiter.record_success(host)
                success_count += 1
                logger.info(f"Crawled {url}: {len(results)} matches")

            except Exception as e:
                logger.warning(f"Failed to crawl {url}: {e}")
                host = urlparse(url).netloc
                self.rate_limiter.record_error(host)
                failed_count += 1

        # Apply filters
        all_results = filter_empty_results(all_results)
        all_results = deduplicate_results(all_results)

        logger.info(
            f"Crawl complete: {success_count} success, {skipped_count} skipped, "
            f"{failed_count} failed, {len(all_results)} unique results"
        )

        return all_results

    @retry(
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _crawl_url(self, url: str, keywords: Sequence[str]) -> list[ResultItem]:
        """
        Crawl a single URL and extract matching content (with retry).

        Args:
            url: URL to crawl
            keywords: Keywords to match

        Returns:
            List of ResultItem objects
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        logger.debug(f"Fetching {url}")
        response = requests.get(url, headers=headers, timeout=self.timeout)

        # Check for rate limiting or errors
        if response.status_code == 429:
            logger.warning(f"Rate limited (429): {url}")
            raise requests.RequestException("Rate limit exceeded")

        if response.status_code >= 500:
            logger.warning(f"Server error ({response.status_code}): {url}")
            raise requests.RequestException(f"Server error: {response.status_code}")

        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.content, "html.parser")

        # Extract articles/items
        results = self._extract_articles(soup, url, keywords)

        return results

    def _extract_articles(
        self,
        soup: BeautifulSoup,
        base_url: str,
        keywords: Sequence[str]
    ) -> list[ResultItem]:
        """
        Extract article elements and match against keywords.

        Args:
            soup: BeautifulSoup parsed HTML
            base_url: Base URL for resolving relative links
            keywords: Keywords to match

        Returns:
            List of ResultItem objects
        """
        results = []

        # Try common article selectors
        article_selectors = [
            "article",
            ".article",
            ".paper",
            ".result-item",
            "div[class*='article']",
            "div[class*='paper']",
            "li[class*='article']",
            "li[class*='paper']",
        ]

        articles = []
        for selector in article_selectors:
            found = soup.select(selector)
            if found:
                articles.extend(found)
                logger.debug(f"Found {len(found)} elements with selector: {selector}")

        # Fallback: if no articles found, try to extract from whole page
        if not articles:
            logger.debug("No article elements found, analyzing full page")
            articles = [soup]

        # Process each article
        for article in articles:
            try:
                result = self._extract_article_item(article, base_url, keywords)
                if result:
                    results.append(result)
            except Exception as e:
                logger.debug(f"Failed to extract article: {e}")

        return results

    def _extract_article_item(
        self,
        element: BeautifulSoup,
        base_url: str,
        keywords: Sequence[str]
    ) -> ResultItem | None:
        """
        Extract a single article item if it matches keywords.

        Args:
            element: BeautifulSoup element (article or container)
            base_url: Base URL for resolving relative links
            keywords: Keywords to match

        Returns:
            ResultItem if keywords match, None otherwise
        """
        # Extract text content
        text_content = element.get_text(separator=" ", strip=True)

        # Check if keywords match
        if not self._matches_keywords(text_content, keywords):
            return None

        # Extract title
        title = self._extract_title(element)
        if not title:
            return None

        # Extract URL
        url = self._extract_url(element, base_url)
        if not url:
            url = base_url  # Fallback to base URL

        # Extract snippet
        snippet = self._extract_snippet(element, keywords)

        try:
            return ResultItem(
                title=title,
                url=url,
                snippet=snippet,
                published_at=None,  # HTTP crawler doesn't extract dates (can be extended)
            )
        except ValueError:
            return None

    def _matches_keywords(self, text: str, keywords: Sequence[str]) -> bool:
        """Check if text contains any of the keywords (case-insensitive)."""
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    def _extract_title(self, element: BeautifulSoup) -> str:
        """Extract title from article element."""
        # Try common title selectors
        title_selectors = ["h1", "h2", "h3", ".title", "a"]

        for selector in title_selectors:
            title_elem = element.select_one(selector)
            if title_elem:
                title = title_elem.get_text(strip=True)
                if title and len(title) > 5:  # Minimum title length
                    return title

        return ""

    def _extract_url(self, element: BeautifulSoup, base_url: str) -> str:
        """Extract URL from article element."""
        # Look for links
        link = element.find("a", href=True)
        if link:
            href = link["href"]
            # Resolve relative URLs
            return urljoin(base_url, href)

        return base_url

    def _extract_snippet(self, element: BeautifulSoup, keywords: Sequence[str]) -> str:
        """
        Extract snippet highlighting keyword context.

        Args:
            element: BeautifulSoup element
            keywords: Keywords to highlight

        Returns:
            Snippet text (truncated to max_snippet_length)
        """
        # Try to find paragraph containing keywords
        paragraphs = element.find_all(["p", "div", "span"])

        best_snippet = ""
        max_keyword_count = 0

        for p in paragraphs:
            text = p.get_text(strip=True)
            if not text:
                continue

            # Count keyword matches
            keyword_count = sum(1 for kw in keywords if kw.lower() in text.lower())

            if keyword_count > max_keyword_count:
                max_keyword_count = keyword_count
                best_snippet = text

        # Fallback to full text
        if not best_snippet:
            best_snippet = element.get_text(separator=" ", strip=True)

        # Truncate
        if len(best_snippet) > self.max_snippet_length:
            best_snippet = best_snippet[:self.max_snippet_length] + "..."

        return best_snippet or "No description available"
