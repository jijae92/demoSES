"""AWS Lambda handler for the paper watcher."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Mapping, Sequence

from botocore.exceptions import BotoCoreError, ClientError

from config import AppConfig, get_config
from dal import SeenRepository
from mailer import EmailDeliveryError, send_email
from sources.crossref import fetch_crossref
from sources.pubmed import fetch_pubmed
from sources.rss import fetch_rss
from util import PaperItem, window_start

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

SOURCE_FETCHERS = {
    "crossref": fetch_crossref,
    "pubmed": fetch_pubmed,
    "rss": fetch_rss,
}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda entry point expected by AWS."""
    LOGGER.info("Received event: %s", json.dumps(event))
    try:
        config = get_config()
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Configuration error: %s", exc)
        raise

    window_start_dt = window_start(config.window_hours)
    LOGGER.info("Processing window starting at %s", window_start_dt.isoformat())

    fetched_items = _fetch_sources(config, window_start_dt)
    if not fetched_items:
        LOGGER.info("No data fetched from any source")
        return {"status": "no_data"}

    repository = SeenRepository(config.ddb_table)
    new_items = _filter_new_items(repository, fetched_items)
    if not new_items:
        LOGGER.info("No new items detected")
        return {"status": "no_new_items"}

    sorted_items = _sort_items(new_items)
    flat_items = [item for items in sorted_items.values() for item in items]
    try:
        repository.mark_seen(flat_items)
    except (ClientError, BotoCoreError):
        LOGGER.exception("Failed to update DynamoDB")
        raise

    try:
        send_email(sorted_items, config)
    except EmailDeliveryError as exc:
        LOGGER.error("Email delivery failed: %s", exc)
        raise

    LOGGER.info("Successfully processed %d new items", len(flat_items))
    return {"status": "ok", "new_items": len(flat_items)}


def _fetch_sources(config: AppConfig, window_start_dt: datetime) -> Mapping[str, List[PaperItem]]:
    results: Dict[str, List[PaperItem]] = {}
    for source in config.sources:
        fetcher = SOURCE_FETCHERS.get(source)
        if not fetcher:
            LOGGER.warning("Unsupported source requested: %s", source)
            continue
        try:
            if source == "pubmed":
                items = fetcher(
                    config.keywords,
                    config.match_mode,
                    window_start_dt,
                    config.user_agent,
                    config.api_secrets.pubmed_api_key,
                )
            else:
                items = fetcher(
                    config.keywords,
                    config.match_mode,
                    window_start_dt,
                    config.user_agent,
                )
            LOGGER.info("Fetched %d items from %s", len(items), source)
            results[source] = items
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to fetch items from %s", source)
    return results


def _filter_new_items(repository: SeenRepository, items_by_source: Mapping[str, Sequence[PaperItem]]) -> Dict[str, List[PaperItem]]:
    new_items: Dict[str, List[PaperItem]] = defaultdict(list)
    for source, items in items_by_source.items():
        for item in items:
            if repository.is_seen(item.paper_id):
                continue
            new_items[source].append(item)
    return new_items


def _sort_items(items_by_source: Mapping[str, Sequence[PaperItem]]) -> Dict[str, List[PaperItem]]:
    sorted_items: Dict[str, List[PaperItem]] = {}
    for source, items in items_by_source.items():
        sorted_items[source] = sorted(
            items,
            key=lambda item: item.published or datetime.min.replace(tzinfo=item.published.tzinfo if item.published else None),
            reverse=True,
        )
    return sorted_items