"""
Common utilities for web crawlers.

Includes deduplication, robots.txt checking, rate limiting, and retry logic.
"""

import logging
import time
from typing import Sequence
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .interface import ResultItem

logger = logging.getLogger(__name__)


def deduplicate_results(results: Sequence[ResultItem]) -> list[ResultItem]:
    """
    Remove duplicate results based on URL.

    Args:
        results: List of ResultItem objects

    Returns:
        Deduplicated list with unique URLs only (preserves first occurrence)

    Example:
        >>> items = [ResultItem("A", "http://example.com", "..."),
        ...          ResultItem("B", "http://example.com", "...")]
        >>> deduplicated = deduplicate_results(items)
        >>> len(deduplicated)
        1
    """
    seen_urls = set()
    deduplicated = []
    duplicates_count = 0

    for item in results:
        url_normalized = item.url.lower().strip()
        if url_normalized not in seen_urls:
            seen_urls.add(url_normalized)
            deduplicated.append(item)
        else:
            duplicates_count += 1

    if duplicates_count > 0:
        logger.info(f"Removed {duplicates_count} duplicate URLs")

    return deduplicated


def filter_empty_results(results: Sequence[ResultItem]) -> list[ResultItem]:
    """
    Remove results with empty or whitespace-only fields.

    Args:
        results: List of ResultItem objects

    Returns:
        Filtered list with valid results only
    """
    filtered = []
    empty_count = 0

    for item in results:
        if (item.title.strip() and
            item.url.strip() and
            item.snippet.strip()):
            filtered.append(item)
        else:
            empty_count += 1

    if empty_count > 0:
        logger.warning(f"Filtered out {empty_count} empty results")

    return filtered


class RobotsTxtChecker:
    """
    Checks if a URL is allowed by robots.txt.

    Caches robots.txt files for efficiency.
    """

    def __init__(self, user_agent: str = "PaperWatcher/1.0"):
        """
        Initialize the robots.txt checker.

        Args:
            user_agent: User-Agent string to use for checking permissions
        """
        self.user_agent = user_agent
        self._cache: dict[str, RobotFileParser] = {}
        logger.debug(f"RobotsTxtChecker initialized with UA: {user_agent}")

    def is_allowed(self, url: str) -> bool:
        """
        Check if crawling is allowed for the given URL.

        Args:
            url: URL to check

        Returns:
            True if crawling is allowed, False if disallowed

        Note:
            If robots.txt cannot be fetched or parsed, defaults to True (allowed)
        """
        try:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            robots_url = f"{base_url}/robots.txt"

            # Check cache first
            if base_url not in self._cache:
                logger.debug(f"Fetching robots.txt from {robots_url}")
                rp = RobotFileParser()
                rp.set_url(robots_url)
                try:
                    rp.read()
                    self._cache[base_url] = rp
                except Exception as e:
                    logger.warning(f"Failed to fetch robots.txt from {robots_url}: {e}")
                    # Default to allowed if robots.txt is unavailable
                    return True

            rp = self._cache[base_url]
            allowed = rp.can_fetch(self.user_agent, url)

            if not allowed:
                logger.info(f"robots.txt disallows crawling: {url}")

            return allowed

        except Exception as e:
            logger.error(f"Error checking robots.txt for {url}: {e}")
            # Default to allowed on error
            return True


class RateLimiter:
    """
    Simple rate limiter to prevent overwhelming servers.

    Implements exponential backoff on errors.
    """

    def __init__(self, min_delay: float = 1.0, max_delay: float = 30.0):
        """
        Initialize rate limiter.

        Args:
            min_delay: Minimum delay between requests in seconds
            max_delay: Maximum delay for exponential backoff in seconds
        """
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_request_time: dict[str, float] = {}
        self._error_count: dict[str, int] = {}

    def wait(self, host: str) -> None:
        """
        Wait appropriate amount of time before making a request to host.

        Args:
            host: Hostname to rate limit
        """
        current_time = time.time()

        if host in self._last_request_time:
            elapsed = current_time - self._last_request_time[host]
            delay = self._calculate_delay(host)

            if elapsed < delay:
                sleep_time = delay - elapsed
                logger.debug(f"Rate limiting {host}: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)

        self._last_request_time[host] = time.time()

    def _calculate_delay(self, host: str) -> float:
        """Calculate delay based on error count (exponential backoff)."""
        error_count = self._error_count.get(host, 0)
        delay = self.min_delay * (2 ** error_count)
        return min(delay, self.max_delay)

    def record_error(self, host: str) -> None:
        """Record an error for exponential backoff."""
        self._error_count[host] = self._error_count.get(host, 0) + 1
        logger.warning(f"Error count for {host}: {self._error_count[host]}")

    def record_success(self, host: str) -> None:
        """Record a successful request (resets error count)."""
        if host in self._error_count:
            del self._error_count[host]
