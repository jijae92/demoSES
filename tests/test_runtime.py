from __future__ import annotations

from runtime import derive_runtime_options
from types import SimpleNamespace


def _make_config():
    return SimpleNamespace(
        keywords=("baseline",),
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
    assert runtime.keywords == ("review", "interferon")
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
    assert runtime.keywords == config.keywords


def test_force_send_summary_defaults_false():
    config = _make_config()
    runtime = derive_runtime_options(config, {})

    assert runtime.force_send_summary is False
