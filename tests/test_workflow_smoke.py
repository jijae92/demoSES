from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.config import ApiSecrets, AppConfig, SesSecrets
from src.handler import lambda_handler
from src.runtime import RuntimeOptions
from src.util import PaperItem


class DummyRepository:
    def __init__(self, _table_name: str) -> None:
        self.seen: set[str] = set()

    def is_seen(self, paper_id: str) -> bool:
        return paper_id in self.seen

    def mark_seen(self, items: list[PaperItem]) -> None:
        for item in items:
            self.seen.add(item.paper_id)


@pytest.mark.smoke
def test_lambda_handler_smoke_flow(monkeypatch):
    now = datetime(2025, 10, 26, 3, 0, tzinfo=timezone.utc)

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

    runtime_options = RuntimeOptions(
        keywords=("parp", "isg"),
        sources=("crossref",),
        match_mode="OR",
        window_hours=24,
        dry_run=False,
        recipients_override=None,
        force_send_summary=False,
    )

    items = [
        PaperItem(
            source="crossref",
            paper_id="10.2000/smoke",
            title="STING and PARP synergy",
            authors=("Alice Kim",),
            published=None,
            url="https://doi.org/10.2000/smoke",
            matched_keywords=("parp",),
        )
    ]

    sent_payload = SimpleNamespace(called=False, items=None)

    monkeypatch.setattr("src.handler.get_config", lambda: config)
    monkeypatch.setattr("src.handler.derive_runtime_options", lambda _config, _event: runtime_options)
    monkeypatch.setattr("src.handler.fetch_crossref", lambda **_: items)
    monkeypatch.setattr("src.handler.fetch_pubmed", lambda **_: [])
    monkeypatch.setattr("src.handler.fetch_rss", lambda **_: [])
    monkeypatch.setattr("src.handler.SeenRepository", DummyRepository)
    monkeypatch.setattr("src.handler.utcnow", lambda: now)

    def _fake_send_email(items_by_source, *_args, **_kwargs):
        sent_payload.called = True
        sent_payload.items = items_by_source

    monkeypatch.setattr("src.handler.send_email", _fake_send_email)

    result = lambda_handler(event={}, context=None)

    assert result["status"] == "ok"
    assert result["new_items"] == 1
    assert sent_payload.called is True
    assert list(sent_payload.items["crossref"])[0].paper_id == "10.2000/smoke"
