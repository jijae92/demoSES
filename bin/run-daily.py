#!/usr/bin/env python3
"""
Paper Watcher - Daily Runner Script

Production-ready script for scheduled execution.
Crawls sources, deduplicates results, and sends email notifications.

Usage:
    ./bin/run-daily.py
    ./bin/run-daily.py --dry-run
    ./bin/run-daily.py --provider bing --keywords "parp,isg"
    ./bin/run-daily.py --reset-state

Exit codes:
    0: Success
    1: Error occurred
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import load_config, load_config_with_env_fallback
from src.crawler import BingCrawler, HttpCrawler
from src.emailer import Emailer, EmailStats
from src.storage import SeenStorage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Paper Watcher - Daily keyword search and email notification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Normal run with config.yaml
  %(prog)s --dry-run                    # Test without sending email
  %(prog)s --reset-state                # Clear deduplication history
  %(prog)s --provider bing              # Use Bing search
  %(prog)s --keywords "parp,isg,sting"  # Override keywords
  %(prog)s --min-results 5              # Require 5+ results
        """
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config file (default: config.yaml)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run: crawl and deduplicate but don't send email"
    )

    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Reset deduplication state before running"
    )

    parser.add_argument(
        "--provider",
        type=str,
        choices=["bing", "http"],
        help="Override search provider (bing or http)"
    )

    parser.add_argument(
        "--keywords",
        type=str,
        help="Override keywords (comma-separated, e.g., 'parp,isg,interferon')"
    )

    parser.add_argument(
        "--min-results",
        type=int,
        help="Override minimum results threshold"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging (DEBUG level)"
    )

    parser.add_argument(
        "--storage-path",
        type=str,
        default=".data/seen.json",
        help="Path to deduplication storage file (default: .data/seen.json)"
    )

    return parser.parse_args()


def load_configuration(args):
    """
    Load and merge configuration.

    Args:
        args: Parsed command line arguments

    Returns:
        Tuple of (config, keywords, provider, min_results)
    """
    logger.info(f"Loading configuration from {args.config}")

    config_path = Path(args.config)
    if config_path.exists():
        config = load_config(config_path)
        logger.info("✓ Configuration loaded from config.yaml")
    else:
        logger.warning(f"Config file not found: {args.config}, using environment variables")
        config = load_config_with_env_fallback()

    # Apply command-line overrides
    keywords = config.keywords
    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(',')]
        logger.info(f"Keywords overridden via CLI: {keywords}")

    provider = args.provider or config.provider
    logger.info(f"Provider: {provider}")

    min_results = args.min_results if args.min_results is not None else config.min_results
    logger.info(f"Min results threshold: {min_results}")

    return config, keywords, provider, min_results


def perform_crawl(provider, keywords, config):
    """
    Perform web crawling.

    Args:
        provider: Search provider ("bing" or "http")
        keywords: List of keywords to search
        config: Configuration object

    Returns:
        List of ResultItem objects

    Raises:
        RuntimeError: If crawling fails
    """
    logger.info(f"Initializing {provider} crawler...")

    if provider == "bing":
        crawler = BingCrawler()
        logger.info("✓ Bing crawler initialized")
    elif provider == "http":
        if not config.sources:
            raise ValueError("HTTP provider requires 'sources' in config.yaml")
        crawler = HttpCrawler(
            source_urls=config.sources,
            respect_robots_txt=True
        )
        logger.info(f"✓ HTTP crawler initialized ({len(config.sources)} sources)")
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Perform search
    logger.info(f"Searching for keywords: {keywords}")
    results = crawler.search(keywords)

    logger.info(f"Crawling complete: {len(results)} results found")
    return results


def apply_deduplication(results, storage):
    """
    Apply deduplication using storage.

    Args:
        results: List of ResultItem objects
        storage: SeenStorage instance

    Returns:
        Tuple of (new_results, duplicates_count)
    """
    original_count = len(results)
    new_results = [item for item in results if not storage.is_seen(item)]

    duplicates_count = original_count - len(new_results)

    logger.info(f"Deduplication: {original_count} total, {len(new_results)} new, "
               f"{duplicates_count} duplicates")

    # Mark new results as seen
    if new_results:
        storage.mark_seen(new_results)
        logger.info(f"✓ Marked {len(new_results)} results as seen")

    return new_results, duplicates_count


def send_notification(results, keywords, original_count, duplicates_count, config, min_results):
    """
    Send email notification.

    Args:
        results: List of new ResultItem objects
        keywords: List of keywords searched
        original_count: Original result count before dedup
        duplicates_count: Number of duplicates filtered
        config: Configuration object
        min_results: Minimum results threshold

    Returns:
        True if email was sent, False otherwise
    """
    logger.info("Preparing email notification...")

    # Create emailer
    emailer = Emailer(
        sender=config.email.sender,
        recipients=config.email.recipients,
        subject_prefix=config.email.subject_prefix,
    )

    # Create stats
    stats = EmailStats()
    stats.total_found = original_count
    stats.total_new = len(results)
    stats.total_duplicates = duplicates_count

    # Send email
    sent = emailer.send_email(
        results=results,
        keywords=keywords,
        stats=stats,
        min_results=min_results
    )

    return sent


def main():
    """Main entry point."""
    args = parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    try:
        # Load configuration
        config, keywords, provider, min_results = load_configuration(args)

        # Initialize storage
        storage = SeenStorage(
            storage_path=args.storage_path,
            dedup_window_days=config.dedup_window_days
        )
        logger.info(f"Storage initialized: {args.storage_path} (TTL: {config.dedup_window_days} days)")

        # Handle reset-state
        if args.reset_state:
            logger.warning("Resetting deduplication state...")
            storage.reset_state()
            logger.info("✓ State reset complete")
            return 0

        # Step 1: Perform crawling
        logger.info("=" * 60)
        logger.info("STEP 1: CRAWLING")
        logger.info("=" * 60)

        results = perform_crawl(provider, keywords, config)

        if not results:
            logger.info("No results found. Exiting.")
            return 0

        # Step 2: Apply deduplication
        logger.info("=" * 60)
        logger.info("STEP 2: DEDUPLICATION")
        logger.info("=" * 60)

        original_count = len(results)
        new_results, duplicates_count = apply_deduplication(results, storage)

        if not new_results:
            logger.info("All results were duplicates. No email will be sent.")
            return 0

        # Step 3: Send email (unless dry-run)
        logger.info("=" * 60)
        logger.info("STEP 3: EMAIL NOTIFICATION")
        logger.info("=" * 60)

        if args.dry_run:
            logger.info("DRY RUN MODE: Email notification skipped")
            logger.info(f"Would send email with {len(new_results)} results to:")
            for recipient in config.email.recipients:
                logger.info(f"  - {recipient}")
        else:
            if len(new_results) < min_results:
                logger.info(
                    f"Skipping email: {len(new_results)} results < min_results ({min_results})"
                )
            else:
                sent = send_notification(
                    new_results,
                    keywords,
                    original_count,
                    duplicates_count,
                    config,
                    min_results
                )

                if sent:
                    logger.info("✓ Email notification sent successfully")
                else:
                    logger.warning("✗ Failed to send email notification")

        # Step 4: Summary
        logger.info("=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Provider:          {provider}")
        logger.info(f"Keywords:          {', '.join(keywords)}")
        logger.info(f"Total found:       {original_count}")
        logger.info(f"New results:       {len(new_results)}")
        logger.info(f"Duplicates:        {duplicates_count}")
        logger.info(f"Min threshold:     {min_results}")
        logger.info(f"Email sent:        {'No (dry-run)' if args.dry_run else 'Yes' if len(new_results) >= min_results else 'No (below threshold)'}")
        logger.info("=" * 60)

        return 0

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        return 1

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
