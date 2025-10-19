from __future__ import annotations

import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace

from runtime import FIXED_KEYWORDS, RuntimeOptions, derive_runtime_options

DummyBotoCoreError = type('DummyBotoCoreError', (Exception,), {})
DummyClientError = type('DummyClientError', (Exception,), {})
DummyRetryError = type('DummyRetryError', (Exception,), {})


def _identity_decorator(*_args, **_kwargs):
    def wrapper(func):
        return func
    return wrapper


if 'tenacity' not in sys.modules:
    tenacity_module = ModuleType('tenacity')
    tenacity_module.RetryError = DummyRetryError
    tenacity_module.retry = _identity_decorator
    tenacity_module.retry_if_exception_type = _identity_decorator
    tenacity_module.stop_after_attempt = lambda *_args, **_kwargs: None
    tenacity_module.wait_exponential = lambda *_args, **_kwargs: None
    sys.modules['tenacity'] = tenacity_module

if 'feedparser' not in sys.modules:
    sys.modules['feedparser'] = SimpleNamespace(
        parse=lambda *_args, **_kwargs: SimpleNamespace(entries=[], bozo=False),
        FeedParserDict=dict,
    )

if 'boto3' not in sys.modules:
    sys.modules['boto3'] = SimpleNamespace(client=lambda *_args, **_kwargs: None)
if 'botocore' not in sys.modules:
    botocore_module = ModuleType('botocore')
    exceptions_module = ModuleType('botocore.exceptions')
    exceptions_module.BotoCoreError = DummyBotoCoreError
    exceptions_module.ClientError = DummyClientError
    botocore_module.exceptions = exceptions_module
    sys.modules['botocore'] = botocore_module
    sys.modules['botocore.exceptions'] = exceptions_module
else:
    # Ensure exceptions exist when real botocore is present
    exceptions_module = sys.modules.get('botocore.exceptions')
    if exceptions_module is None:
        exceptions_module = ModuleType('botocore.exceptions')
        exceptions_module.BotoCoreError = DummyBotoCoreError
        exceptions_module.ClientError = DummyClientError
        sys.modules['botocore'].exceptions = exceptions_module
        sys.modules['botocore.exceptions'] = exceptions_module

import handler



def _make_config():
    return SimpleNamespace(
        keywords=FIXED_KEYWORDS,
        match_mode="OR",
        window_hours=24,
        sources=("crossref", "pubmed", "rss"),
    )


def test_event_overrides_sources_and_keywords():
    config = _make_config()
    event = {
        "sources": ["rss"],
        "keywords": "review, interferon",
        "window_hours": 2880,
        "dry_run": True,
        "match_mode": "and",
    }

    runtime = derive_runtime_options(config, event)

    assert runtime.sources == ("rss",)
    assert runtime.keywords == FIXED_KEYWORDS
    assert runtime.window_hours == 2880
    assert runtime.dry_run is True
    assert runtime.match_mode == "AND"


def test_recipients_override_parsing():
    config = _make_config()
    event = {
        "recipients_override": ["one@example.com", "two@example.com", "one@example.com"],
    }

    runtime = derive_runtime_options(config, event)

    assert runtime.recipients_override == ("one@example.com", "two@example.com")
    assert runtime.sources == config.sources
    assert runtime.keywords == FIXED_KEYWORDS


def test_force_send_summary_defaults_false():
    config = _make_config()
    runtime = derive_runtime_options(config, {})

    assert runtime.force_send_summary is False


def test_fetch_sources_respects_event_preference(monkeypatch):
    calls = []

    def fake_rss(**kwargs):
        calls.append("rss")
        return []

    def fail_fetch(*_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("unexpected source invocation")

    monkeypatch.setattr(handler, "fetch_rss", fake_rss)
    monkeypatch.setattr(handler, "fetch_pubmed", fail_fetch)
    monkeypatch.setattr(handler, "fetch_crossref", fail_fetch)

    config = SimpleNamespace(
        user_agent="agent",
        api_secrets=SimpleNamespace(pubmed_api_key=None, user_agent_email=None),
    )
    runtime = RuntimeOptions(
        keywords=("sting",),
        sources=("rss",),
        match_mode="OR",
        window_hours=24,
        dry_run=True,
        recipients_override=None,
        force_send_summary=False,
    )

    results, counts = handler._fetch_sources(
        config,
        runtime,
        window_start_dt=datetime.utcnow(),
        window_end_dt=datetime.utcnow(),
    )

    assert calls == ["rss"]
    assert list(results.keys()) == ["rss"]
    assert counts["rss"] == 0
