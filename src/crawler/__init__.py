"""
Crawler module for fetching search results from various providers.

Supports:
- Bing Web Search API (recommended)
- HTTP direct crawling with keyword matching
"""

from .interface import ICrawler, ResultItem
from .bing_crawler import BingCrawler
from .http_crawler import HttpCrawler

__all__ = ["ICrawler", "ResultItem", "BingCrawler", "HttpCrawler"]
