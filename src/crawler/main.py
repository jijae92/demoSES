#!/usr/bin/env python3
"""
Crawler CLI tool for testing and manual execution.

Usage:
    python -m src.crawler.main --dry-run
    python -m src.crawler.main --provider bing
    python -m src.crawler.main --provider http --config config.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config_loader import load_config, load_config_with_env_fallback
from src.crawler import BingCrawler, HttpCrawler, ResultItem
from src.storage import SeenStorage
from src.emailer import Emailer, EmailStats

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Paper Watcher Crawler - Test keyword searches"
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config.yaml file (default: config.yaml)"
    )

    parser.add_argument(
        "--provider",
        type=str,
        choices=["bing", "http"],
        help="Override provider from config (bing or http)"
    )

    parser.add_argument(
        "--keywords",
        type=str,
        nargs="+",
        help="Override keywords from config (space-separated)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode - just show configuration"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output (DEBUG level)"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Limit number of results to display (default: 10)"
    )

    # Storage management options
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Reset deduplication state (delete all seen records)"
    )

    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up old records beyond dedup window"
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show storage statistics"
    )

    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable deduplication (show all results)"
    )

    parser.add_argument(
        "--storage-path",
        type=str,
        default=".data/seen.json",
        help="Path to storage file (default: .data/seen.json)"
    )

    # Email delivery options
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Send email notification with results"
    )

    parser.add_argument(
        "--force-email",
        action="store_true",
        help="Send email even if results < min_results"
    )

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Load configuration
        logger.info(f"Loading configuration from {args.config}")

        config_path = Path(args.config)
        if config_path.exists():
            config = load_config(config_path)
            logger.info("✓ Loaded config.yaml")
        else:
            logger.warning(f"Config file not found: {args.config}, using environment variables")
            config = load_config_with_env_fallback()

        # Override with CLI arguments
        provider = args.provider or config.provider
        keywords = args.keywords or config.keywords

        logger.info(f"Provider: {provider}")
        logger.info(f"Keywords: {keywords}")

        # Initialize storage
        storage = SeenStorage(
            storage_path=args.storage_path,
            dedup_window_days=config.dedup_window_days
        )

        # Handle storage management commands
        if args.reset_state:
            print("\n" + "="*60)
            print("RESET STATE")
            print("="*60)
            storage.reset_state()
            print("✓ Storage state has been reset")
            print("All previously seen items will be treated as new")
            print("="*60)
            return 0

        if args.cleanup:
            print("\n" + "="*60)
            print("CLEANUP OLD RECORDS")
            print("="*60)
            removed = storage.cleanup_old_records()
            print(f"✓ Removed {removed} old records")
            print(f"(older than {config.dedup_window_days} days)")
            print("="*60)
            return 0

        if args.stats:
            print("\n" + "="*60)
            print("STORAGE STATISTICS")
            print("="*60)
            stats = storage.get_stats()
            print(f"Total records:  {stats['total_count']}")
            if stats['oldest_record']:
                print(f"Oldest record:  {stats['oldest_record']}")
            if stats['newest_record']:
                print(f"Newest record:  {stats['newest_record']}")
            print(f"Dedup window:   {config.dedup_window_days} days")
            print(f"Storage path:   {args.storage_path}")
            print("="*60)
            return 0

        # Dry run mode
        if args.dry_run:
            print("\n" + "="*60)
            print("DRY RUN MODE - Configuration Only")
            print("="*60)
            print(f"Provider:       {provider}")
            print(f"Keywords:       {', '.join(keywords)}")
            print(f"Min Results:    {config.min_results}")
            print(f"Dedup Window:   {config.dedup_window_days} days")
            print(f"Timezone:       {config.timezone}")
            print(f"Email From:     {config.email.sender}")
            print(f"Email To:       {', '.join(config.email.recipients)}")

            if provider == "http" and config.sources:
                print(f"Sources ({len(config.sources)}):")
                for source in config.sources:
                    print(f"  - {source}")

            print("="*60)
            print("\nTo perform actual search, remove --dry-run flag")
            return 0

        # Create crawler
        logger.info("Initializing crawler...")

        if provider == "bing":
            crawler = BingCrawler()
            logger.info("✓ Bing crawler initialized")
        elif provider == "http":
            if not config.sources:
                logger.error("HTTP provider requires 'sources' in config.yaml")
                return 1
            crawler = HttpCrawler(
                source_urls=config.sources,
                respect_robots_txt=True
            )
            logger.info(f"✓ HTTP crawler initialized ({len(config.sources)} sources)")
        else:
            logger.error(f"Unknown provider: {provider}")
            return 1

        # Perform search
        logger.info(f"Searching for keywords: {keywords}")
        results = crawler.search(keywords)

        # Apply deduplication
        if not args.no_dedup:
            original_count = len(results)
            new_results = [item for item in results if not storage.is_seen(item)]

            logger.info(f"Deduplication: {original_count} total, {len(new_results)} new, "
                       f"{original_count - len(new_results)} already seen")

            # Mark new results as seen
            if new_results:
                storage.mark_seen(new_results)

            results = new_results
        else:
            logger.info("Deduplication disabled (--no-dedup)")

        # Display results
        print("\n" + "="*60)
        print(f"SEARCH RESULTS: {len(results)} new items found")
        print("="*60)

        if len(results) == 0:
            print("No results found.")
        else:
            display_count = min(len(results), args.limit)

            for i, item in enumerate(results[:display_count], 1):
                print(f"\n[{i}] {item.title}")
                print(f"    URL: {item.url}")
                print(f"    Snippet: {item.snippet[:200]}...")
                if item.published_at:
                    print(f"    Published: {item.published_at}")

            if len(results) > display_count:
                print(f"\n... and {len(results) - display_count} more results")
                print(f"(Use --limit {len(results)} to see all)")

        print("\n" + "="*60)
        print(f"Total: {len(results)} results")
        print("="*60)

        # Send email if requested
        if args.send_email:
            logger.info("Preparing to send email notification...")

            # Create emailer
            emailer = Emailer(
                sender=config.email.sender,
                recipients=config.email.recipients,
                subject_prefix=config.email.subject_prefix,
            )

            # Create stats
            stats = EmailStats()
            stats.total_found = original_count if not args.no_dedup else len(results)
            stats.total_new = len(results)
            stats.total_duplicates = (original_count - len(results)) if not args.no_dedup else 0

            # Send email
            min_results = 0 if args.force_email else config.min_results

            email_sent = emailer.send_email(
                results=results,
                keywords=keywords,
                stats=stats,
                min_results=min_results
            )

            if email_sent:
                print("\n✓ Email notification sent successfully")
            elif len(results) < config.min_results:
                print(f"\nℹ Email skipped: {len(results)} results < min_results ({config.min_results})")
            else:
                print("\n✗ Failed to send email notification")

        return 0

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        return 130

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
