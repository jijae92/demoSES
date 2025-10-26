"""
Bing Web Search API crawler implementation.

Uses the Bing Web Search API v7 to find content matching keywords.
Requires BING_API_KEY environment variable.
"""

import logging
import os
from datetime import datetime
from typing import Sequence

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .interface import ICrawler, ResultItem
from .utils import deduplicate_results, filter_empty_results

logger = logging.getLogger(__name__)


class BingCrawler(ICrawler):
    """
    Bing Web Search API crawler.

    Uses Bing's Web Search API to find articles matching keywords.
    Respects rate limits and implements exponential backoff on failures.
    """

    BING_API_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
    DEFAULT_USER_AGENT = "PaperWatcher/1.0 (Bing Search Client)"

    def __init__(
        self,
        api_key: str | None = None,
        user_agent: str | None = None,
        count: int = 50,
        market: str = "en-US",
        safe_search: str = "Moderate",
        timeout: int = 30,
    ):
        """
        Initialize Bing crawler.

        Args:
            api_key: Bing API key (defaults to BING_API_KEY env var)
            user_agent: Custom user agent string
            count: Number of results to return per request (max 50)
            market: Market code for search (e.g., "en-US", "ko-KR")
            safe_search: SafeSearch level ("Off", "Moderate", "Strict")
            timeout: Request timeout in seconds

        Raises:
            ValueError: If API key is not provided
        """
        self.api_key = api_key or os.getenv("BING_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Bing API key is required. Set BING_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.count = min(count, 50)  # Bing max is 50
        self.market = market
        self.safe_search = safe_search
        self.timeout = timeout

        logger.info(f"BingCrawler initialized (market={market}, count={count})")

    def search(self, keywords: Sequence[str]) -> list[ResultItem]:
        """
        Search Bing for content matching keywords.

        Args:
            keywords: List of keywords to search for (combined with OR)

        Returns:
            List of ResultItem objects

        Raises:
            ValueError: If keywords list is empty
            RuntimeError: If API request fails after retries
        """
        if not keywords or len(keywords) == 0:
            raise ValueError("Keywords list cannot be empty")

        # Build query string: keyword1 OR keyword2 OR keyword3
        query = " OR ".join(f'"{kw}"' for kw in keywords)
        logger.info(f"Searching Bing with query: {query}")

        try:
            results = self._perform_search(query)
            logger.info(f"Bing returned {len(results)} raw results")

            # Apply filters
            results = filter_empty_results(results)
            results = deduplicate_results(results)

            logger.info(f"After filtering: {len(results)} unique results")
            return results

        except Exception as e:
            logger.error(f"Bing search failed: {e}", exc_info=True)
            raise RuntimeError(f"Bing search failed: {e}") from e

    @retry(
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _perform_search(self, query: str) -> list[ResultItem]:
        """
        Perform actual API request to Bing (with retry logic).

        Args:
            query: Search query string

        Returns:
            List of ResultItem objects from API response
        """
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "User-Agent": self.user_agent,
        }

        params = {
            "q": query,
            "count": self.count,
            "mkt": self.market,
            "safeSearch": self.safe_search,
            "responseFilter": "Webpages",  # Only web results
            "textDecorations": False,
            "textFormat": "Raw",
        }

        logger.debug(f"Bing API request: {params}")

        response = requests.get(
            self.BING_API_ENDPOINT,
            headers=headers,
            params=params,
            timeout=self.timeout,
        )

        # Check for rate limiting
        if response.status_code == 429:
            logger.warning("Bing API rate limit hit (429)")
            raise requests.RequestException("Rate limit exceeded")

        # Check for other errors
        response.raise_for_status()

        data = response.json()

        # Parse web pages from response
        web_pages = data.get("webPages", {})
        total_estimated = web_pages.get("totalEstimatedMatches", 0)
        logger.info(f"Bing estimated total matches: {total_estimated}")

        results = []
        for item in web_pages.get("value", []):
            try:
                result_item = ResultItem(
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", ""),
                    published_at=self._parse_date(item.get("dateLastCrawled")),
                )
                results.append(result_item)
            except ValueError as e:
                # Skip invalid items (empty title/url/snippet)
                logger.debug(f"Skipping invalid result: {e}")
                continue

        return results

    def _parse_date(self, date_str: str | None) -> datetime | None:
        """
        Parse Bing date string to datetime.

        Args:
            date_str: ISO 8601 date string from Bing API

        Returns:
            datetime object or None if parsing fails
        """
        if not date_str:
            return None

        try:
            # Bing returns ISO 8601 format: 2025-10-27T12:00:00.0000000Z
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception as e:
            logger.debug(f"Failed to parse date '{date_str}': {e}")
            return None
