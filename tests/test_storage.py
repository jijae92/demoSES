"""
Unit tests for storage module.

Tests deduplication, hashing, TTL cleanup, and state management.
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit

from src.crawler.interface import ResultItem
from src.storage import (
    SeenStorage,
    compute_hash,
    normalize_title,
)


# ========== Title Normalization Tests ==========

def test_normalize_title_lowercase():
    """Test that normalization converts to lowercase."""
    assert normalize_title("UPPER CASE") == "upper case"


def test_normalize_title_whitespace():
    """Test that extra whitespace is removed."""
    assert normalize_title("  Multiple   Spaces  ") == "multiple spaces"


def test_normalize_title_punctuation():
    """Test that punctuation is removed."""
    assert normalize_title("Title: With, Punctuation!") == "title with punctuation"


def test_normalize_title_unicode():
    """Test Unicode handling."""
    assert normalize_title("Café résumé") == "café résumé"


def test_normalize_title_complex():
    """Test complex normalization."""
    title = "  PARP  Inhibitors:  A  New   Approach!!  "
    expected = "parp inhibitors a new approach"
    assert normalize_title(title) == expected


# ========== Hash Computation Tests ==========

def test_compute_hash_consistency():
    """Test that hash is consistent for same input."""
    url = "https://example.com/article"
    title = "Test Article"

    hash1 = compute_hash(url, title)
    hash2 = compute_hash(url, title)

    assert hash1 == hash2


def test_compute_hash_length():
    """Test that hash is SHA-256 (64 hex characters)."""
    url = "https://example.com"
    title = "Title"

    hash_value = compute_hash(url, title)

    assert len(hash_value) == 64
    assert all(c in '0123456789abcdef' for c in hash_value)


def test_compute_hash_title_normalization():
    """Test that different title cases produce same hash."""
    url = "https://example.com/article"
    title1 = "Test Article"
    title2 = "TEST ARTICLE"
    title3 = "  test  article  "

    hash1 = compute_hash(url, title1)
    hash2 = compute_hash(url, title2)
    hash3 = compute_hash(url, title3)

    assert hash1 == hash2 == hash3


def test_compute_hash_different_urls():
    """Test that different URLs produce different hashes."""
    title = "Same Title"
    url1 = "https://example.com/article1"
    url2 = "https://example.com/article2"

    hash1 = compute_hash(url1, title)
    hash2 = compute_hash(url2, title)

    assert hash1 != hash2


def test_compute_hash_different_titles():
    """Test that different titles produce different hashes."""
    url = "https://example.com/article"
    title1 = "Title One"
    title2 = "Title Two"

    hash1 = compute_hash(url, title1)
    hash2 = compute_hash(url, title2)

    assert hash1 != hash2


# ========== SeenStorage Tests ==========

@pytest.fixture
def temp_storage():
    """Create a temporary storage file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "test_seen.json"
        storage = SeenStorage(storage_path=storage_path, dedup_window_days=14)
        yield storage


def test_storage_initialization(temp_storage):
    """Test storage initialization."""
    assert temp_storage.dedup_window_days == 14
    assert temp_storage.storage_path.parent.exists()


def test_load_seen_empty(temp_storage):
    """Test loading from non-existent file returns empty dict."""
    seen_items = temp_storage.load_seen()
    assert seen_items == {}


def test_save_and_load_seen(temp_storage):
    """Test saving and loading seen items."""
    test_data = {
        "hash123": {
            "url": "https://example.com",
            "title": "Test",
            "seen_at": datetime.now(timezone.utc).isoformat(),
            "hash": "hash123"
        }
    }

    temp_storage.save_seen(test_data)
    loaded_data = temp_storage.load_seen()

    assert loaded_data == test_data


def test_is_seen_new_item(temp_storage):
    """Test that new item is not seen."""
    item = ResultItem(
        title="New Article",
        url="https://example.com/new",
        snippet="This is new"
    )

    assert temp_storage.is_seen(item) is False


def test_is_seen_existing_item(temp_storage):
    """Test that marked item is seen."""
    item = ResultItem(
        title="Test Article",
        url="https://example.com/test",
        snippet="Test snippet"
    )

    # Mark as seen
    temp_storage.mark_seen([item])

    # Check if seen
    assert temp_storage.is_seen(item) is True


def test_is_seen_expired_item(temp_storage):
    """Test that expired item is not seen."""
    item = ResultItem(
        title="Old Article",
        url="https://example.com/old",
        snippet="Old snippet"
    )

    # Create old record (20 days ago)
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    item_hash = compute_hash(item.url, item.title)

    seen_items = {
        item_hash: {
            "url": item.url,
            "title": item.title,
            "seen_at": old_timestamp,
            "hash": item_hash
        }
    }

    temp_storage.save_seen(seen_items)

    # Should not be seen (beyond 14-day window)
    assert temp_storage.is_seen(item) is False


def test_mark_seen_single_item(temp_storage):
    """Test marking a single item as seen."""
    item = ResultItem(
        title="Article",
        url="https://example.com/article",
        snippet="Snippet"
    )

    temp_storage.mark_seen([item])

    seen_items = temp_storage.load_seen()
    assert len(seen_items) == 1


def test_mark_seen_multiple_items(temp_storage):
    """Test marking multiple items as seen."""
    items = [
        ResultItem("Article 1", "https://example.com/1", "Snippet 1"),
        ResultItem("Article 2", "https://example.com/2", "Snippet 2"),
        ResultItem("Article 3", "https://example.com/3", "Snippet 3"),
    ]

    temp_storage.mark_seen(items)

    seen_items = temp_storage.load_seen()
    assert len(seen_items) == 3


def test_mark_seen_duplicate_item(temp_storage):
    """Test that marking the same item twice doesn't create duplicates."""
    item = ResultItem(
        title="Article",
        url="https://example.com/article",
        snippet="Snippet"
    )

    temp_storage.mark_seen([item])
    temp_storage.mark_seen([item])

    seen_items = temp_storage.load_seen()
    assert len(seen_items) == 1


def test_cleanup_old_records(temp_storage):
    """Test cleanup of old records."""
    # Create mix of old and new records
    now = datetime.now(timezone.utc)
    old_timestamp = (now - timedelta(days=20)).isoformat()
    new_timestamp = (now - timedelta(days=5)).isoformat()

    seen_items = {
        "old_hash": {
            "url": "https://example.com/old",
            "title": "Old Article",
            "seen_at": old_timestamp,
            "hash": "old_hash"
        },
        "new_hash": {
            "url": "https://example.com/new",
            "title": "New Article",
            "seen_at": new_timestamp,
            "hash": "new_hash"
        }
    }

    temp_storage.save_seen(seen_items)

    # Clean up
    removed = temp_storage.cleanup_old_records()

    # Should remove 1 old record
    assert removed == 1

    # Only new record should remain
    remaining = temp_storage.load_seen()
    assert len(remaining) == 1
    assert "new_hash" in remaining


def test_cleanup_no_old_records(temp_storage):
    """Test cleanup when there are no old records."""
    # Create only new records
    now = datetime.now(timezone.utc)
    new_timestamp = (now - timedelta(days=5)).isoformat()

    seen_items = {
        "hash1": {
            "url": "https://example.com/1",
            "title": "Article 1",
            "seen_at": new_timestamp,
            "hash": "hash1"
        }
    }

    temp_storage.save_seen(seen_items)

    # Clean up
    removed = temp_storage.cleanup_old_records()

    assert removed == 0
    assert len(temp_storage.load_seen()) == 1


def test_reset_state(temp_storage):
    """Test resetting storage state."""
    # Add some items
    item = ResultItem("Article", "https://example.com", "Snippet")
    temp_storage.mark_seen([item])

    assert len(temp_storage.load_seen()) == 1

    # Reset
    temp_storage.reset_state()

    # Should be empty
    assert len(temp_storage.load_seen()) == 0
    assert not temp_storage.storage_path.exists()


def test_reset_state_empty(temp_storage):
    """Test resetting empty storage doesn't error."""
    # Should not raise error
    temp_storage.reset_state()


def test_get_stats_empty(temp_storage):
    """Test stats for empty storage."""
    stats = temp_storage.get_stats()

    assert stats["total_count"] == 0
    assert stats["oldest_record"] is None
    assert stats["newest_record"] is None


def test_get_stats_with_records(temp_storage):
    """Test stats with records."""
    now = datetime.now(timezone.utc)
    old_timestamp = (now - timedelta(days=10)).isoformat()
    new_timestamp = now.isoformat()

    seen_items = {
        "old": {
            "url": "https://example.com/old",
            "title": "Old",
            "seen_at": old_timestamp,
            "hash": "old"
        },
        "new": {
            "url": "https://example.com/new",
            "title": "New",
            "seen_at": new_timestamp,
            "hash": "new"
        }
    }

    temp_storage.save_seen(seen_items)

    stats = temp_storage.get_stats()

    assert stats["total_count"] == 2
    assert stats["oldest_record"] == old_timestamp
    assert stats["newest_record"] == new_timestamp


def test_storage_json_format(temp_storage):
    """Test that storage file is valid JSON."""
    item = ResultItem("Test", "https://example.com", "Snippet")
    temp_storage.mark_seen([item])

    # Read raw file
    with open(temp_storage.storage_path, 'r') as f:
        data = json.load(f)

    # Should be valid JSON with expected structure
    assert isinstance(data, dict)
    assert len(data) == 1

    for item_hash, record in data.items():
        assert "url" in record
        assert "title" in record
        assert "seen_at" in record
        assert "hash" in record
        assert record["hash"] == item_hash


# ========== Integration Tests ==========

def test_deduplication_workflow(temp_storage):
    """Test full deduplication workflow."""
    # Create items
    item1 = ResultItem("Article 1", "https://example.com/1", "Snippet 1")
    item2 = ResultItem("Article 2", "https://example.com/2", "Snippet 2")
    item1_duplicate = ResultItem("Article 1", "https://example.com/1", "Different snippet")

    # First batch
    temp_storage.mark_seen([item1, item2])

    # Check seen status
    assert temp_storage.is_seen(item1) is True
    assert temp_storage.is_seen(item2) is True
    assert temp_storage.is_seen(item1_duplicate) is True  # Same URL+title

    # Create new item
    item3 = ResultItem("Article 3", "https://example.com/3", "Snippet 3")
    assert temp_storage.is_seen(item3) is False


def test_title_variation_deduplication(temp_storage):
    """Test that title variations are deduplicated."""
    item1 = ResultItem("PARP Inhibitors", "https://example.com/parp", "Snippet")
    item2 = ResultItem("parp inhibitors", "https://example.com/parp", "Snippet")
    item3 = ResultItem("  PARP  Inhibitors  ", "https://example.com/parp", "Snippet")

    temp_storage.mark_seen([item1])

    # All variations should be seen
    assert temp_storage.is_seen(item1) is True
    assert temp_storage.is_seen(item2) is True
    assert temp_storage.is_seen(item3) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
