from __future__ import annotations

from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from src.config import ApiSecrets, AppConfig, SesSecrets
from src.mailer import send_email
from src.runtime import RuntimeOptions
from src.util import PaperItem

pytestmark = pytest.mark.unit


@mock_aws
def test_send_email_via_ses_dispatches_message():
    client = boto3.client("ses", region_name="us-east-1")
    client.verify_email_identity(EmailAddress="alerts@example.com")

    config = AppConfig(
        keywords=("parp", "isg"),
        match_mode="OR",
        window_hours=24,
        sources=("crossref",),
        app_name="paper-watcher",
        ddb_table="paper-watcher-seen",
        ses_secret_name="ses/secret",
        api_secret_name="api/secret",
        use_smtp=False,
        api_secrets=ApiSecrets(pubmed_api_key=None, user_agent_email="alerts@example.com"),
        ses_secrets=SesSecrets(
            sender="alerts@example.com",
            recipients=("researcher@example.com",),
            region="us-east-1",
            reply_to=(),
            subject_prefix="[PaperWatcher]",
        ),
    )

    runtime = RuntimeOptions(
        keywords=("parp", "isg"),
        sources=("crossref",),
        match_mode="OR",
        window_hours=24,
        dry_run=False,
        recipients_override=None,
        force_send_summary=False,
    )

    window_start = datetime(2025, 10, 25, tzinfo=timezone.utc)
    window_end = datetime(2025, 10, 26, tzinfo=timezone.utc)

    items_by_source = {
        "crossref": [
            PaperItem(
                source="crossref",
                paper_id="10.1000/gamma",
                title="Interferon and PARP co-regulation",
                authors=("Alice Kim",),
                published=None,
                url="https://doi.org/10.1000/gamma",
                matched_keywords=("interferon",),
            )
        ]
    }

    summary = {
        "sources": ["crossref"],
        "window_hours": 24,
        "match_mode": "OR",
        "keywords": ["parp", "isg"],
        "fetch_counts": {"crossref": 1},
        "filtered_counts": {"crossref": 1},
        "new_counts": {"crossref": 1},
        "filter_stats": {
            "post_fetch": 1,
            "post_keyword": 1,
            "post_dedup": 1,
            "post_seen": 1,
        },
    }

    send_email(items_by_source, config, runtime, window_start, window_end, summary)

    from moto.ses.models import ses_backends

    backend = next(iter(ses_backends.values()))["us-east-1"]
    assert backend.sent_message_count == 1
    sent = backend.sent_messages[0]
    assert sent.source == "alerts@example.com"
    assert sent.destinations["ToAddresses"] == ["researcher@example.com"]
