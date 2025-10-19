"""AWS Lambda handler for the paper watcher."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Sequence

from botocore.exceptions import BotoCoreError, ClientError

from config import AppConfig, get_config
from dal import SeenRepository
from mailer import EmailDeliveryError, send_email
from pipeline.filtering import FilterStats, filter_items
from runtime import RuntimeOptions, derive_runtime_options
from sources.crossref import fetch_crossref
from sources.pubmed import fetch_pubmed
from sources.rss import fetch_rss
from util import PaperItem, utcnow

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda entry point expected by AWS."""
    LOGGER.info("Received event: %s", json.dumps(event))
    try:
        base_config = get_config()
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Configuration error: %s", exc)
        raise

    runtime = derive_runtime_options(base_config, event)
    config = replace(
        base_config,
        keywords=runtime.keywords,
        match_mode=runtime.match_mode,
        window_hours=runtime.window_hours,
        sources=tuple(runtime.sources),
    )

    LOGGER.info(
        "APPLIED params: sources=%s keywords=%d mode=%s window=%sh dry_run=%s force_send=%s recipients_override=%s",
        list(runtime.sources),
        len(runtime.keywords),
        runtime.match_mode,
        runtime.window_hours,
        runtime.dry_run,
        runtime.force_send_summary,
        bool(runtime.recipients_override),
    )

    window_end_dt = utcnow()
    window_start_dt = window_end_dt - timedelta(hours=runtime.window_hours)

    fetched_items, fetch_counts = _fetch_sources(config, runtime, window_start_dt, window_end_dt)
    total_fetched = sum(fetch_counts.values())
    if total_fetched == 0:
        LOGGER.info("No data fetched from any source")
        if runtime.force_send_summary and not runtime.dry_run:
            summary = _build_summary(
                runtime,
                fetch_counts,
                {},
                {},
                FilterStats(post_fetch=0, post_keyword=0, post_dedup=0),
                post_seen=0,
            )
            _send_summary_email({}, config, runtime, window_start_dt, window_end_dt, summary)
            return {"status": "no_data", "summary_email": True}
        return {"status": "no_data"}

    filtered_items, filter_stats = filter_items(fetched_items, runtime.keywords, runtime.match_mode)
    filtered_counts = {source: len(items) for source, items in filtered_items.items()}
    LOGGER.info(
        "POST-FILTER stats: post_fetch=%d post_keyword=%d post_dedup=%d",
        filter_stats.post_fetch,
        filter_stats.post_keyword,
        filter_stats.post_dedup,
    )
    if not any(filtered_counts.values()):
        if runtime.force_send_summary and not runtime.dry_run:
            summary = _build_summary(
                runtime,
                fetch_counts,
                filtered_counts,
                {},
                filter_stats,
                post_seen=0,
            )
            _send_summary_email({}, config, runtime, window_start_dt, window_end_dt, summary)
            return {"status": "no_matches", "summary_email": True}
        LOGGER.info("No items matched keyword filters")
        return {"status": "no_matches"}

    repository = SeenRepository(config.ddb_table)
    new_items = _filter_seen_items(repository, filtered_items)
    new_counts = {source: len(items) for source, items in new_items.items()}
    new_total = sum(new_counts.values())
    LOGGER.info("POST-FILTER seen check: new=%d", new_total)
    LOGGER.info(
        "SUMMARY counts: pre_fetch=%d post_fetch=%d post_keyword=%d post_dedup=%d post_seen=%d",
        total_fetched,
        filter_stats.post_fetch,
        filter_stats.post_keyword,
        filter_stats.post_dedup,
        new_total,
    )

    summary = _build_summary(
        runtime,
        fetch_counts,
        filtered_counts,
        new_counts,
        filter_stats,
        post_seen=new_total,
    )

    if new_total == 0:
        if runtime.force_send_summary and not runtime.dry_run:
            _send_summary_email(new_items, config, runtime, window_start_dt, window_end_dt, summary)
            return {"status": "no_new_items", "summary_email": True}
        LOGGER.info("No new items detected")
        return {"status": "no_new_items"}

    if runtime.dry_run:
        LOGGER.info("Dry run enabled; skipping DynamoDB update and email send")
        return {"status": "dry_run", "new_items": new_total}

    flat_items = [item for items in new_items.values() for item in items]
    try:
        repository.mark_seen(flat_items)
    except (ClientError, BotoCoreError):
        LOGGER.exception("Failed to update DynamoDB")
        raise

    try:
        send_email(new_items, config, runtime, window_start_dt, window_end_dt, summary)
    except EmailDeliveryError as exc:
        LOGGER.error("Email delivery failed: %s", exc)
        raise

    LOGGER.info("Successfully processed %d new items", len(flat_items))
    return {"status": "ok", "new_items": len(flat_items)}


def _fetch_sources(
    config: AppConfig,
    runtime: RuntimeOptions,
    window_start_dt: datetime,
    window_end_dt: datetime,
) -> tuple[Dict[str, List[PaperItem]], Dict[str, int]]:
    results: Dict[str, List[PaperItem]] = {}
    counts: Dict[str, int] = {}
    for source in runtime.sources:
        try:
            if source == "pubmed":
                items = fetch_pubmed(
                    keywords=runtime.keywords,
                    match_mode=runtime.match_mode,
                    window_start_dt=window_start_dt,
                    window_end_dt=window_end_dt,
                    user_agent=config.user_agent,
                    api_key=config.api_secrets.pubmed_api_key,
                )
            elif source == "rss":
                items = fetch_rss(
                    keywords=runtime.keywords,
                    match_mode=runtime.match_mode,
                    window_start_dt=window_start_dt,
                    window_end_dt=window_end_dt,
                    user_agent=config.user_agent,
                )
            elif source == "crossref":
                items = fetch_crossref(
                    keywords=runtime.keywords,
                    match_mode=runtime.match_mode,
                    window_start_dt=window_start_dt,
                    window_end_dt=window_end_dt,
                    user_agent=config.user_agent,
                    contact_email=config.api_secrets.user_agent_email,
                )
            else:
                LOGGER.warning("Unsupported source requested: %s", source)
                continue
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to fetch items from %s", source)
            continue
        counts[source] = len(items)
        results[source] = items
    return results, counts


def _filter_seen_items(
    repository: SeenRepository,
    items_by_source: Mapping[str, Sequence[PaperItem]],
) -> Dict[str, List[PaperItem]]:
    new_items: Dict[str, List[PaperItem]] = {}
    for source, items in items_by_source.items():
        unseen: List[PaperItem] = []
        for item in items:
            if repository.is_seen(item.paper_id):
                continue
            unseen.append(item)
        if unseen:
            new_items[source] = unseen
    return new_items


def _build_summary(
    runtime: RuntimeOptions,
    fetch_counts: Mapping[str, int],
    filtered_counts: Mapping[str, int],
    new_counts: Mapping[str, int],
    filter_stats: FilterStats,
    post_seen: int,
) -> Dict[str, Any]:
    return {
        "sources": list(runtime.sources),
        "window_hours": runtime.window_hours,
        "match_mode": runtime.match_mode,
        "keywords": list(runtime.keywords),
        "fetch_counts": dict(fetch_counts),
        "filtered_counts": dict(filtered_counts),
        "new_counts": dict(new_counts),
        "filter_stats": filter_stats.as_dict(post_seen=post_seen),
    }


def _send_summary_email(
    items_by_source: Mapping[str, Sequence[PaperItem]],
    config: AppConfig,
    runtime: RuntimeOptions,
    window_start_dt: datetime,
    window_end_dt: datetime,
    summary: Mapping[str, Any],
) -> None:
    try:
        send_email(items_by_source, config, runtime, window_start_dt, window_end_dt, summary)
    except EmailDeliveryError as exc:
        LOGGER.error("Email delivery failed during summary send: %s", exc)
        raise
