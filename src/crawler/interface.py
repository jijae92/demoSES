"""
Abstract interface for web crawlers.

Defines the contract that all crawler implementations must follow.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


@dataclass(slots=True)
class ResultItem:
    """
    Represents a single search result item.

    Attributes:
        title: Article or page title
        url: Full URL to the resource
        snippet: Brief summary or excerpt
        published_at: Publication date (optional)
    """
    title: str
    url: str
    snippet: str
    published_at: datetime | None = None

    def __post_init__(self):
        """Validate that required fields are not empty."""
        if not self.title or not self.title.strip():
            raise ValueError("title cannot be empty")
        if not self.url or not self.url.strip():
            raise ValueError("url cannot be empty")
        if not self.snippet or not self.snippet.strip():
            raise ValueError("snippet cannot be empty")


class ICrawler(ABC):
    """
    Abstract base class for search crawlers.

    All crawler implementations must inherit from this class and implement
    the search() method.
    """

    @abstractmethod
    def search(self, keywords: Sequence[str]) -> list[ResultItem]:
        """
        Search for content matching the given keywords.

        Args:
            keywords: List of keywords to search for

        Returns:
            List of ResultItem objects matching the search criteria

        Raises:
            ValueError: If keywords list is empty or invalid
            RuntimeError: If the search operation fails

        Example:
            >>> crawler = SomeCrawler()
            >>> results = crawler.search(["parp", "isg", "interferon"])
            >>> for item in results:
            ...     print(item.title, item.url)
        """
        pass
