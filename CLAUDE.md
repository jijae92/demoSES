# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Paper Watcher is a serverless AWS Lambda application that monitors scientific publications from Nature, Cell, and Science journals. It fetches papers from multiple sources (Crossref, PubMed, RSS feeds), filters by keywords, deduplicates using DynamoDB, and sends consolidated email alerts via Amazon SES.

## Build and Deployment

```bash
# Build the Lambda deployment package
sam build

# Deploy (guided mode, prompts for parameters)
sam deploy --guided

# Deploy with specific parameters
sam deploy --parameter-overrides UseSmtp=false TableName=paper_seen
```

The build process packages `src/` and dependencies from `requirements.txt` into `.aws-sam/build/PaperWatcherFunction/`.

## Testing

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_filtering.py

# Run with verbose output
pytest -v

# Run a single test function
pytest tests/test_filtering.py::test_filter_items_or_mode_title_or_summary
```

Tests use standard pytest without mocks - they test the filtering pipeline, runtime options, and keyword matching logic.

## Manual Testing

Use the provided event JSON files to test the Lambda locally or in AWS Console:

- `event.json` - Standard test event
- `event-wide.json` - Wide window test with overrides

```bash
# Invoke locally with SAM
sam local invoke PaperWatcherFunction -e event.json
```

## Core Architecture

### Data Flow Pipeline

1. **Configuration Loading** (`config.py`): Fetches secrets from AWS Secrets Manager on cold start, parses environment variables
2. **Runtime Override** (`runtime.py`): Merges event payload overrides with base config. **CRITICAL**: Line 128 enforces `FIXED_KEYWORDS` regardless of overrides
3. **Source Fetching** (`handler.py:_fetch_sources`): Parallel fetches from enabled sources within the time window
4. **Filtering Pipeline** (`pipeline/filtering.py`):
   - Keyword matching (OR/AND modes) with HTML stripping, punctuation normalization
   - Deduplication by lowercased `paper_id`
   - Keyword highlighting in titles/summaries using `highlight_text()`
5. **Deduplication** (`dal.py`): DynamoDB check for previously-seen papers
6. **Email Delivery** (`mailer.py`): SES API (default) or SMTP fallback

### Fixed Keyword Registry

**IMPORTANT**: `runtime.py:9` defines `FIXED_KEYWORDS = ("parp", "isg", "interferon", "sting")` which is **always enforced** at line 128, ignoring any event-based keyword overrides. This is the single source of truth for production searches.

To change keywords, modify `FIXED_KEYWORDS` in `runtime.py`.

### Configuration System

Two-tier configuration:
- **Base Config** (`AppConfig`): Environment variables + Secrets Manager (loaded once per container)
- **Runtime Options** (`RuntimeOptions`): Event payload overrides merged with base config (per invocation)

Event overrides support:
- `sources`: Filter which sources to query
- `match_mode`: "AND" or "OR" keyword logic
- `window_hours`: Lookback period
- `dry_run`: Skip DynamoDB/email
- `force_send_summary`: Send email even with zero results
- `recipients_override`: Temporary recipient list for testing

### Source Adapters

Each source adapter (`sources/crossref.py`, `sources/pubmed.py`, `sources/rss.py`) returns `List[PaperItem]`. They handle:
- API authentication (PubMed API key, Crossref polite pool via user-agent email)
- Date range filtering
- Retry logic (using `tenacity` library)
- Normalization to `PaperItem` dataclass

### Email Rendering

The mailer builds HTML emails with:
- Per-source grouping
- Highlighted keywords using `[keyword]` notation
- Summary statistics (fetch counts, filter stats, unique papers)
- Configurable subject prefix from secrets
- Header sanitization to prevent injection attacks (`util.sanitize_header`)

## AWS Resources

Defined in `template.yaml`:
- **Lambda Function**: Python 3.11, 512MB memory, 60s timeout, triggered by EventBridge on schedule
- **DynamoDB Table**: `paper_seen` (HASH key: `paper_id`), PAY_PER_REQUEST billing
- **IAM Policies**: Scoped to DynamoDB table ARN, SES SendEmail, Secrets Manager read
- **EventBridge Schedule**: Defaults to `cron(0 9 * * ? *)` (09:00 UTC daily)

## Secrets Management

Two required secrets in AWS Secrets Manager:

### `paperwatcher/ses` (SES configuration)
```json
{
  "sender": "notifications@example.com",
  "recipients": ["recipient@example.com"],
  "region": "ap-northeast-2",
  "reply_to": ["optional@example.com"],
  "subject_prefix": "[PaperWatch]",
  "smtp_user": "optional_smtp_username",
  "smtp_pass": "optional_smtp_password",
  "host": "email-smtp.region.amazonaws.com",
  "port": 587
}
```

### `paperwatcher/api` (API credentials)
```json
{
  "pubmed_api_key": "optional_ncbi_api_key",
  "user_agent_email": "contact@example.com"
}
```

## Environment Variables

Set via `template.yaml` CloudFormation parameters:
- `KEYWORDS`: Comma-separated list (NOTE: overridden by `FIXED_KEYWORDS` in runtime.py)
- `MATCH_MODE`: "OR" or "AND"
- `WINDOW_HOURS`: Integer, hours to look back
- `SOURCES`: Comma-separated: "crossref,pubmed,rss"
- `DDB_TABLE`: DynamoDB table name
- `USE_SMTP`: "true" or "false" (forces SMTP over SES API)

## Logging and Monitoring

CloudWatch Logs at INFO level include:
- Event payload (`lambda_handler` entry)
- Applied runtime parameters (sources, keywords, mode, window)
- Per-source fetch counts
- Filter pipeline stats (post_fetch, post_keyword, post_dedup, post_seen)
- Email delivery status
- Exceptions with stack traces

Key metrics: Lambda Invocations, Errors, Duration; DynamoDB ConsumedReadCapacity/WriteCapacity.

## Common Patterns

### Adding a New Source

1. Create `src/sources/newsource.py` implementing `fetch_newsource()` returning `List[PaperItem]`
2. Add conditional branch in `handler.py:_fetch_sources` for the new source name
3. Add source to `SOURCES` environment variable
4. Add retry logic and error handling following existing patterns

### Modifying Keyword Logic

Edit `pipeline/filtering.py:keyword_match()`. Current logic:
- Normalizes text: strips HTML, lowercases, removes punctuation
- Supports quoted phrases (exact substring match after normalization)
- OR mode: any keyword matches → include paper
- AND mode: all keywords must match → include paper

### Changing Email Template

Edit `mailer.py` (not reviewed in this init, but referenced in imports). Ensure all headers pass `util.sanitize_header()` to prevent injection.

## Development Notes

- Dataclasses use `slots=True` for memory efficiency in Lambda
- Type hints follow modern Python (using `|` union syntax, `Sequence` over `List` for immutability)
- Error handling logs before re-raising to preserve CloudWatch visibility
- DynamoDB operations use exponential backoff via boto3 defaults
- RSS parsing uses `feedparser` library with `sgmllib3k` for Python 3 compatibility
