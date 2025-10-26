"""
Local storage module for deduplication tracking.

Stores seen items in .data/seen.json with SHA-256 hashing and TTL-based cleanup.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.crawler.interface import ResultItem

logger = logging.getLogger(__name__)

# Default storage path
DEFAULT_STORAGE_PATH = Path(".data/seen.json")


def normalize_title(title: str) -> str:
    """
    Normalize title for consistent hashing.

    Removes extra whitespace, converts to lowercase, removes punctuation.

    Args:
        title: Raw title string

    Returns:
        Normalized title string
    """
    # Lowercase
    normalized = title.lower()

    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized)

    # Remove common punctuation (keep alphanumeric and spaces)
    normalized = re.sub(r'[^\w\s]', '', normalized)

    # Strip leading/trailing whitespace
    normalized = normalized.strip()

    return normalized


def compute_hash(url: str, title: str) -> str:
    """
    Compute SHA-256 hash of URL and normalized title.

    Args:
        url: Item URL
        title: Item title (will be normalized)

    Returns:
        SHA-256 hash as hexadecimal string
    """
    normalized_title = normalize_title(title)
    composite_key = f"{url}|{normalized_title}"

    hash_obj = hashlib.sha256(composite_key.encode('utf-8'))
    return hash_obj.hexdigest()


class SeenStorage:
    """
    Manages seen items storage with TTL-based cleanup.

    Stores items in JSON format with SHA-256 hashing for deduplication.
    """

    def __init__(self, storage_path: Path | str = DEFAULT_STORAGE_PATH, dedup_window_days: int = 14):
        """
        Initialize storage manager.

        Args:
            storage_path: Path to storage JSON file
            dedup_window_days: Number of days to keep seen records
        """
        self.storage_path = Path(storage_path)
        self.dedup_window_days = dedup_window_days

        # Ensure .data directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(f"SeenStorage initialized: {self.storage_path} (TTL: {dedup_window_days} days)")

    def load_seen(self) -> dict[str, dict[str, Any]]:
        """
        Load seen items from storage file.

        Returns:
            Dictionary mapping hash keys to item metadata

        Example:
            {
                "abc123...": {
                    "url": "https://example.com",
                    "title": "Example Title",
                    "seen_at": "2025-10-27T12:00:00+00:00",
                    "hash": "abc123..."
                }
            }
        """
        if not self.storage_path.exists():
            logger.debug(f"Storage file does not exist: {self.storage_path}")
            return {}

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            logger.info(f"Loaded {len(data)} seen items from storage")
            return data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse storage file: {e}")
            return {}
        except Exception as e:
            logger.error(f"Failed to load storage: {e}")
            return {}

    def save_seen(self, seen_items: dict[str, dict[str, Any]]) -> None:
        """
        Save seen items to storage file.

        Args:
            seen_items: Dictionary of seen items to save
        """
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(seen_items, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved {len(seen_items)} seen items to storage")

        except Exception as e:
            logger.error(f"Failed to save storage: {e}")
            raise

    def is_seen(self, item: ResultItem) -> bool:
        """
        Check if an item has been seen before.

        Args:
            item: ResultItem to check

        Returns:
            True if item was seen within the dedup window, False otherwise
        """
        seen_items = self.load_seen()
        item_hash = compute_hash(item.url, item.title)

        if item_hash not in seen_items:
            return False

        # Check if record is within TTL window
        record = seen_items[item_hash]
        seen_at_str = record.get("seen_at")

        if not seen_at_str:
            logger.warning(f"Missing seen_at timestamp for hash: {item_hash}")
            return False

        try:
            seen_at = datetime.fromisoformat(seen_at_str)
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.dedup_window_days)

            if seen_at < cutoff_time:
                logger.debug(f"Record expired (seen {self.dedup_window_days}+ days ago): {item.url}")
                return False

            logger.debug(f"Item already seen: {item.url}")
            return True

        except Exception as e:
            logger.error(f"Failed to parse seen_at timestamp: {e}")
            return False

    def mark_seen(self, items: list[ResultItem]) -> None:
        """
        Mark multiple items as seen.

        Args:
            items: List of ResultItem objects to mark as seen
        """
        seen_items = self.load_seen()
        current_time = datetime.now(timezone.utc).isoformat()

        new_count = 0
        for item in items:
            item_hash = compute_hash(item.url, item.title)

            if item_hash not in seen_items:
                new_count += 1

            seen_items[item_hash] = {
                "url": item.url,
                "title": item.title,
                "seen_at": current_time,
                "hash": item_hash,
            }

        self.save_seen(seen_items)
        logger.info(f"Marked {new_count} new items as seen (total: {len(seen_items)})")

    def cleanup_old_records(self) -> int:
        """
        Remove records older than the dedup window.

        Returns:
            Number of records removed
        """
        seen_items = self.load_seen()
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.dedup_window_days)

        original_count = len(seen_items)
        cleaned_items = {}

        for item_hash, record in seen_items.items():
            seen_at_str = record.get("seen_at")

            if not seen_at_str:
                logger.warning(f"Skipping record with missing timestamp: {item_hash}")
                continue

            try:
                seen_at = datetime.fromisoformat(seen_at_str)

                if seen_at >= cutoff_time:
                    cleaned_items[item_hash] = record

            except Exception as e:
                logger.error(f"Failed to parse timestamp for {item_hash}: {e}")

        removed_count = original_count - len(cleaned_items)

        if removed_count > 0:
            self.save_seen(cleaned_items)
            logger.info(f"Cleaned up {removed_count} old records (kept {len(cleaned_items)})")
        else:
            logger.debug("No old records to clean up")

        return removed_count

    def reset_state(self) -> None:
        """
        Reset storage state (delete all seen records).

        Use with caution - this will allow all previously seen items to be sent again.
        """
        if self.storage_path.exists():
            self.storage_path.unlink()
            logger.warning(f"Storage reset: deleted {self.storage_path}")
        else:
            logger.info("Storage already empty")

    def get_stats(self) -> dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage stats (count, oldest/newest records)
        """
        seen_items = self.load_seen()

        if not seen_items:
            return {
                "total_count": 0,
                "oldest_record": None,
                "newest_record": None,
            }

        timestamps = []
        for record in seen_items.values():
            seen_at_str = record.get("seen_at")
            if seen_at_str:
                try:
                    timestamps.append(datetime.fromisoformat(seen_at_str))
                except Exception:
                    pass

        return {
            "total_count": len(seen_items),
            "oldest_record": min(timestamps).isoformat() if timestamps else None,
            "newest_record": max(timestamps).isoformat() if timestamps else None,
        }
