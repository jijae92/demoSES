"""
Crawler module for fetching search results from various providers.

Supports:
- Bing Web Search API (recommended)
- HTTP direct crawling with keyword matching
"""

from .interface import ICrawler, ResultItem
from .bing_crawler import BingCrawler

__all__ = ["ICrawler", "ResultItem", "BingCrawler", "HttpCrawler"]


def __getattr__(name: str):
    """
    Lazily import optional crawler implementations.

    HttpCrawler depends on optional third-party libraries (e.g. BeautifulSoup).
    Delaying its import prevents hard failures when those extras are not
    installed in environments that only need core interfaces (like tests).
    """
    if name == "HttpCrawler":
        from .http_crawler import HttpCrawler  # pragma: no cover

        return HttpCrawler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
