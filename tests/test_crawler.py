"""
Unit tests for crawler module.

Tests the interface, Bing crawler, HTTP crawler, and utilities.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit

from src.crawler.interface import ICrawler, ResultItem
from src.crawler.bing_crawler import BingCrawler
from src.crawler.http_crawler import HttpCrawler
from src.crawler.utils import (
    deduplicate_results,
    filter_empty_results,
    RobotsTxtChecker,
    RateLimiter,
)


# ========== ResultItem Tests ==========

def test_result_item_valid():
    """Test creating a valid ResultItem."""
    item = ResultItem(
        title="Test Article",
        url="https://example.com/article",
        snippet="This is a test snippet",
        published_at=datetime.now(),
    )
    assert item.title == "Test Article"
    assert item.url == "https://example.com/article"
    assert item.snippet == "This is a test snippet"


def test_result_item_without_published_at():
    """Test creating ResultItem without published_at."""
    item = ResultItem(
        title="Test Article",
        url="https://example.com/article",
        snippet="This is a test snippet",
    )
    assert item.published_at is None


def test_result_item_empty_title_raises():
    """Test that empty title raises ValueError."""
    with pytest.raises(ValueError, match="title cannot be empty"):
        ResultItem(
            title="",
            url="https://example.com",
            snippet="snippet",
        )


def test_result_item_empty_url_raises():
    """Test that empty URL raises ValueError."""
    with pytest.raises(ValueError, match="url cannot be empty"):
        ResultItem(
            title="Title",
            url="",
            snippet="snippet",
        )


def test_result_item_empty_snippet_raises():
    """Test that empty snippet raises ValueError."""
    with pytest.raises(ValueError, match="snippet cannot be empty"):
        ResultItem(
            title="Title",
            url="https://example.com",
            snippet="",
        )


# ========== Utils Tests ==========

def test_deduplicate_results():
    """Test URL deduplication."""
    items = [
        ResultItem("A", "https://example.com/1", "snippet 1"),
        ResultItem("B", "https://example.com/2", "snippet 2"),
        ResultItem("C", "https://example.com/1", "snippet 3"),  # Duplicate URL
    ]

    deduplicated = deduplicate_results(items)

    assert len(deduplicated) == 2
    assert deduplicated[0].title == "A"
    assert deduplicated[1].title == "B"


def test_deduplicate_results_case_insensitive():
    """Test that deduplication is case-insensitive."""
    items = [
        ResultItem("A", "https://Example.com/page", "snippet 1"),
        ResultItem("B", "https://example.com/Page", "snippet 2"),
    ]

    deduplicated = deduplicate_results(items)

    # Should keep only first occurrence
    assert len(deduplicated) == 1


def test_filter_empty_results():
    """Test filtering of empty results."""
    valid = ResultItem("Valid", "https://example.com", "Valid snippet")
    empty_title = ResultItem("Placeholder", "https://example.com/2", "snippet")
    empty_title.title = "  "
    empty_url = ResultItem("Title", "https://example.com/3", "snippet")
    empty_url.url = "   "
    empty_snippet = ResultItem("Another", "https://example.com/4", "snippet")
    empty_snippet.snippet = "  "

    items = [valid, empty_title, empty_url, empty_snippet]

    filtered = filter_empty_results(items)

    assert filtered == [valid]


def test_robots_txt_checker_initialization():
    """Test RobotsTxtChecker initialization."""
    checker = RobotsTxtChecker(user_agent="TestBot/1.0")
    assert checker.user_agent == "TestBot/1.0"
    assert len(checker._cache) == 0


@patch('urllib.robotparser.RobotFileParser.read')
@patch('urllib.robotparser.RobotFileParser.can_fetch')
def test_robots_txt_checker_allowed(mock_can_fetch, mock_read):
    """Test RobotsTxtChecker allows crawling."""
    mock_can_fetch.return_value = True

    checker = RobotsTxtChecker()
    allowed = checker.is_allowed("https://example.com/page")

    assert allowed is True


@patch('urllib.robotparser.RobotFileParser.read')
@patch('urllib.robotparser.RobotFileParser.can_fetch')
def test_robots_txt_checker_disallowed(mock_can_fetch, mock_read):
    """Test RobotsTxtChecker disallows crawling."""
    mock_can_fetch.return_value = False

    checker = RobotsTxtChecker()
    allowed = checker.is_allowed("https://example.com/admin")

    assert allowed is False


def test_rate_limiter_initialization():
    """Test RateLimiter initialization."""
    limiter = RateLimiter(min_delay=1.0, max_delay=30.0)
    assert limiter.min_delay == 1.0
    assert limiter.max_delay == 30.0


def test_rate_limiter_error_recording():
    """Test RateLimiter records errors for exponential backoff."""
    limiter = RateLimiter()

    limiter.record_error("example.com")
    assert limiter._error_count["example.com"] == 1

    limiter.record_error("example.com")
    assert limiter._error_count["example.com"] == 2


def test_rate_limiter_success_resets_errors():
    """Test RateLimiter resets error count on success."""
    limiter = RateLimiter()

    limiter.record_error("example.com")
    limiter.record_error("example.com")
    assert limiter._error_count["example.com"] == 2

    limiter.record_success("example.com")
    assert "example.com" not in limiter._error_count


# ========== BingCrawler Tests ==========

def test_bing_crawler_initialization_no_api_key():
    """Test BingCrawler raises error without API key."""
    with pytest.raises(ValueError, match="Bing API key is required"):
        BingCrawler()


def test_bing_crawler_initialization_with_api_key():
    """Test BingCrawler initializes with API key."""
    crawler = BingCrawler(api_key="test_key_123")
    assert crawler.api_key == "test_key_123"


def test_bing_crawler_search_empty_keywords():
    """Test BingCrawler raises error with empty keywords."""
    crawler = BingCrawler(api_key="test_key")

    with pytest.raises(ValueError, match="Keywords list cannot be empty"):
        crawler.search([])


@patch('src.crawler.bing_crawler.requests.get')
def test_bing_crawler_search_success(mock_get):
    """Test BingCrawler successful search."""
    # Mock API response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "webPages": {
            "totalEstimatedMatches": 100,
            "value": [
                {
                    "name": "Test Article 1",
                    "url": "https://example.com/article1",
                    "snippet": "This article mentions parp and interferon",
                    "dateLastCrawled": "2025-10-27T12:00:00.0000000Z",
                },
                {
                    "name": "Test Article 2",
                    "url": "https://example.com/article2",
                    "snippet": "Another article about isg",
                },
            ]
        }
    }
    mock_get.return_value = mock_response

    crawler = BingCrawler(api_key="test_key")
    results = crawler.search(["parp", "isg"])

    assert len(results) == 2
    assert results[0].title == "Test Article 1"
    assert results[0].url == "https://example.com/article1"
    assert results[1].title == "Test Article 2"


@patch('src.crawler.bing_crawler.requests.get')
def test_bing_crawler_rate_limit(mock_get):
    """Test BingCrawler handles rate limiting."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_get.return_value = mock_response

    crawler = BingCrawler(api_key="test_key")

    with pytest.raises(RuntimeError, match="Bing search failed"):
        crawler.search(["test"])


# ========== HttpCrawler Tests ==========

def test_http_crawler_initialization_no_sources():
    """Test HttpCrawler raises error without sources."""
    with pytest.raises(ValueError, match="source_urls cannot be empty"):
        HttpCrawler(source_urls=[])


def test_http_crawler_initialization_with_sources():
    """Test HttpCrawler initializes with sources."""
    crawler = HttpCrawler(source_urls=["https://example.com"])
    assert len(crawler.source_urls) == 1


def test_http_crawler_search_empty_keywords():
    """Test HttpCrawler raises error with empty keywords."""
    crawler = HttpCrawler(source_urls=["https://example.com"])

    with pytest.raises(ValueError, match="Keywords list cannot be empty"):
        crawler.search([])


@patch('src.crawler.http_crawler.requests.get')
def test_http_crawler_search_success(mock_get):
    """Test HttpCrawler successful crawl."""
    # Mock HTML response
    html_content = """
    <html>
        <body>
            <article>
                <h2><a href="/article1">PARP Inhibitors Study</a></h2>
                <p>This article discusses PARP inhibitors and their effects on interferon response.</p>
            </article>
            <article>
                <h2><a href="/article2">ISG Expression</a></h2>
                <p>Research on ISG expression patterns in immune cells.</p>
            </article>
        </body>
    </html>
    """

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = html_content.encode('utf-8')
    mock_get.return_value = mock_response

    crawler = HttpCrawler(
        source_urls=["https://example.com"],
        respect_robots_txt=False  # Disable for testing
    )
    results = crawler.search(["parp", "isg"])

    assert len(results) >= 1  # At least one match
    # The exact number depends on keyword matching logic


@patch('src.crawler.http_crawler.requests.get')
def test_http_crawler_server_error(mock_get):
    """Test HttpCrawler handles server errors."""
    mock_response = Mock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response

    crawler = HttpCrawler(
        source_urls=["https://example.com"],
        respect_robots_txt=False
    )

    # Should handle error gracefully and return empty results
    results = crawler.search(["test"])
    assert len(results) == 0  # Failed requests return no results


# ========== Integration Tests ==========

def test_crawler_interface_contract():
    """Test that both crawlers implement ICrawler interface."""
    assert issubclass(BingCrawler, ICrawler)
    assert issubclass(HttpCrawler, ICrawler)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
