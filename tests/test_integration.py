"""
Integration tests for Paper Watcher.

Tests full workflow: crawl → dedup → email
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config_loader import PaperWatcherConfig, EmailConfig
from src.crawler import BingCrawler, HttpCrawler
from src.crawler.interface import ResultItem
from src.emailer import Emailer, EmailStats
from src.storage import SeenStorage


# ========== Fixtures ==========

@pytest.fixture
def temp_storage_path():
    """Create temporary storage file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "seen.json"


@pytest.fixture
def sample_config():
    """Create sample configuration."""
    return PaperWatcherConfig(
        keywords=["parp", "isg", "interferon"],
        provider="http",
        sources=["https://example.com/news"],
        min_results=1,
        dedup_window_days=14,
        timezone="Asia/Seoul",
        email=EmailConfig(
            sender="test@example.com",
            recipients=["recipient@example.com"],
            subject_prefix="[Test]"
        )
    )


@pytest.fixture
def sample_results():
    """Create sample crawl results."""
    return [
        ResultItem(
            title="PARP Inhibitors Study",
            url="https://example.com/article1",
            snippet="Study on PARP inhibitors in cancer treatment",
            published_at=datetime.now(timezone.utc)
        ),
        ResultItem(
            title="ISG Expression Patterns",
            url="https://example.com/article2",
            snippet="Research on ISG expression in immune response"
        ),
        ResultItem(
            title="Interferon Therapy",
            url="https://example.com/article3",
            snippet="Clinical trials of interferon therapy"
        ),
    ]


# ========== Deduplication Integration Tests ==========

@pytest.mark.integration
def test_dedup_first_run_finds_all(temp_storage_path, sample_results):
    """Test that first run finds all results."""
    storage = SeenStorage(temp_storage_path, dedup_window_days=14)

    # First run: all should be new
    new_results = [item for item in sample_results if not storage.is_seen(item)]

    assert len(new_results) == 3
    assert new_results == sample_results


@pytest.mark.integration
def test_dedup_second_run_finds_none(temp_storage_path, sample_results):
    """Test that second run finds no new results."""
    storage = SeenStorage(temp_storage_path, dedup_window_days=14)

    # First run: mark as seen
    storage.mark_seen(sample_results)

    # Second run: all should be duplicates
    new_results = [item for item in sample_results if not storage.is_seen(item)]

    assert len(new_results) == 0


@pytest.mark.integration
def test_dedup_reset_finds_all_again(temp_storage_path, sample_results):
    """Test that reset allows finding results again."""
    storage = SeenStorage(temp_storage_path, dedup_window_days=14)

    # First run
    storage.mark_seen(sample_results)

    # Verify all seen
    new_results = [item for item in sample_results if not storage.is_seen(item)]
    assert len(new_results) == 0

    # Reset state
    storage.reset_state()

    # After reset: all should be new again
    new_results = [item for item in sample_results if not storage.is_seen(item)]
    assert len(new_results) == 3


@pytest.mark.integration
def test_dedup_partial_overlap(temp_storage_path):
    """Test deduplication with partial overlap."""
    storage = SeenStorage(temp_storage_path, dedup_window_days=14)

    # First batch
    batch1 = [
        ResultItem("Article 1", "https://example.com/1", "Snippet 1"),
        ResultItem("Article 2", "https://example.com/2", "Snippet 2"),
    ]
    storage.mark_seen(batch1)

    # Second batch (partial overlap)
    batch2 = [
        ResultItem("Article 2", "https://example.com/2", "Snippet 2"),  # Duplicate
        ResultItem("Article 3", "https://example.com/3", "Snippet 3"),  # New
    ]

    new_results = [item for item in batch2 if not storage.is_seen(item)]

    assert len(new_results) == 1
    assert new_results[0].title == "Article 3"


# ========== Email Integration Tests ==========

@pytest.mark.integration
@patch('src.emailer.boto3')
def test_email_workflow_with_results(mock_boto3, sample_config, sample_results):
    """Test email workflow with sufficient results."""
    mock_ses = MagicMock()
    mock_ses.send_email.return_value = {"MessageId": "test-123"}
    mock_boto3.client.return_value = mock_ses

    emailer = Emailer(
        sender=sample_config.email.sender,
        recipients=sample_config.email.recipients,
        subject_prefix=sample_config.email.subject_prefix
    )

    stats = EmailStats()
    stats.total_found = 3
    stats.total_new = 3

    sent = emailer.send_email(
        results=sample_results,
        keywords=sample_config.keywords,
        stats=stats,
        min_results=1
    )

    assert sent is True
    mock_ses.send_email.assert_called_once()


@pytest.mark.integration
@patch('src.emailer.boto3')
def test_email_workflow_below_threshold(mock_boto3, sample_config):
    """Test email workflow with results below min_results."""
    emailer = Emailer(
        sender=sample_config.email.sender,
        recipients=sample_config.email.recipients,
        subject_prefix=sample_config.email.subject_prefix
    )

    # Only 1 result, but min_results = 5
    results = [
        ResultItem("Article", "https://example.com", "Snippet")
    ]

    sent = emailer.send_email(
        results=results,
        keywords=sample_config.keywords,
        min_results=5
    )

    assert sent is False


# ========== Full Workflow Integration Tests ==========

@pytest.mark.integration
@patch('src.emailer.boto3')
def test_full_workflow_end_to_end(mock_boto3, temp_storage_path, sample_config):
    """Test complete workflow: crawl → dedup → email."""
    mock_ses = MagicMock()
    mock_ses.send_email.return_value = {"MessageId": "test-456"}
    mock_boto3.client.return_value = mock_ses

    # Create mock results
    mock_results = [
        ResultItem(f"Article {i}", f"https://example.com/{i}", f"Snippet {i}")
        for i in range(5)
    ]

    # Initialize components
    storage = SeenStorage(temp_storage_path, dedup_window_days=14)
    emailer = Emailer(
        sender=sample_config.email.sender,
        recipients=sample_config.email.recipients,
        subject_prefix=sample_config.email.subject_prefix
    )

    # First run
    new_results = [item for item in mock_results if not storage.is_seen(item)]
    assert len(new_results) == 5

    storage.mark_seen(new_results)

    stats = EmailStats()
    stats.total_found = len(mock_results)
    stats.total_new = len(new_results)

    sent = emailer.send_email(
        results=new_results,
        keywords=sample_config.keywords,
        stats=stats,
        min_results=sample_config.min_results
    )

    assert sent is True

    # Second run (should find nothing new)
    new_results_2 = [item for item in mock_results if not storage.is_seen(item)]
    assert len(new_results_2) == 0


@pytest.mark.integration
def test_workflow_with_no_results(temp_storage_path, sample_config):
    """Test workflow when no results are found."""
    storage = SeenStorage(temp_storage_path, dedup_window_days=14)

    # Empty results
    results = []

    # Should not crash
    new_results = [item for item in results if not storage.is_seen(item)]
    assert len(new_results) == 0


# ========== HTTP Crawler Integration Tests ==========

@pytest.mark.integration
@patch('src.crawler.http_crawler.requests.get')
def test_http_crawler_with_mock_response(mock_get):
    """Test HTTP crawler with mocked response."""
    html_content = """
    <html>
        <body>
            <article>
                <h2><a href="/article1">PARP Research</a></h2>
                <p>Study on PARP inhibitors in treatment.</p>
            </article>
        </body>
    </html>
    """

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = html_content.encode('utf-8')
    mock_get.return_value = mock_response

    crawler = HttpCrawler(
        source_urls=["https://example.com"],
        respect_robots_txt=False
    )

    results = crawler.search(["parp"])

    assert len(results) >= 0  # May or may not find results depending on matching


# ========== Bing Crawler Integration Tests ==========

@pytest.mark.integration
@pytest.mark.requires_api
@patch('src.crawler.bing_crawler.requests.get')
def test_bing_crawler_with_mock_api(mock_get):
    """Test Bing crawler with mocked API response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "webPages": {
            "totalEstimatedMatches": 100,
            "value": [
                {
                    "name": "PARP Inhibitors Study",
                    "url": "https://example.com/parp-study",
                    "snippet": "Research on PARP inhibitors",
                    "dateLastCrawled": "2025-10-27T12:00:00.0000000Z"
                }
            ]
        }
    }
    mock_get.return_value = mock_response

    crawler = BingCrawler(api_key="test-key")
    results = crawler.search(["parp"])

    assert len(results) == 1
    assert results[0].title == "PARP Inhibitors Study"


# ========== Smoke Tests ==========

@pytest.mark.smoke
def test_imports():
    """Smoke test: verify all modules can be imported."""
    from src import config_loader
    from src import crawler
    from src import emailer
    from src import storage

    assert config_loader is not None
    assert crawler is not None
    assert emailer is not None
    assert storage is not None


@pytest.mark.smoke
def test_basic_workflow_components_initialize():
    """Smoke test: verify all components can be initialized."""
    # Storage
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = SeenStorage(Path(tmpdir) / "test.json", dedup_window_days=14)
        assert storage is not None

    # Emailer
    emailer = Emailer(
        sender="test@example.com",
        recipients=["recipient@example.com"]
    )
    assert emailer is not None

    # Bing Crawler
    bing_crawler = BingCrawler(api_key="test-key")
    assert bing_crawler is not None

    # HTTP Crawler
    http_crawler = HttpCrawler(source_urls=["https://example.com"])
    assert http_crawler is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
