from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from src.sources.crossref import CROSSREF_URL, fetch_crossref

pytestmark = pytest.mark.unit


def _build_crossref_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "message": {
            "total-results": len(items),
            "items": items,
        }
    }


@responses.activate
def test_fetch_crossref_keyword_matching_filters_by_journal():
    """Crossref fetch should honour journal filter and keyword matching."""

    def _callback(request) -> tuple[int, dict[str, str], str]:
        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        filter_value = query.get("filter", [""])[0]
        journal = next(
            (
                part.split(":", 1)[1]
                for part in filter_value.split(",")
                if part.startswith("container-title:")
            ),
            "",
        )
        if journal == "Nature":
            payload = _build_crossref_payload(
                [
                    {
                        "DOI": "10.1234/example",
                        "title": ["Interferon pathways uncovered"],
                        "abstract": "<jats:p>Interferon signaling synergy.</jats:p>",
                        "author": [{"given": "Alice", "family": "Kim"}],
                        "URL": "https://doi.org/10.1234/example",
                        "issued": {"date-parts": [[2025, 10, 20]]},
                    },
                    {
                        "DOI": "10.5555/ignore",
                        "title": ["Completely unrelated topic"],
                        "abstract": "<jats:p>No relevant keywords.</jats:p>",
                        "author": [{"given": "Bob", "family": "Lee"}],
                        "URL": "https://doi.org/10.5555/ignore",
                        "issued": {"date-parts": [[2025, 10, 20]]},
                    },
                ]
            )
        else:
            payload = _build_crossref_payload([])

        headers = {"Content-Type": "application/json"}
        return 200, headers, json.dumps(payload)

    responses.add_callback(responses.GET, CROSSREF_URL, callback=_callback, content_type="application/json")

    window_start = datetime(2025, 10, 18, tzinfo=timezone.utc)
    window_end = datetime(2025, 10, 27, tzinfo=timezone.utc)

    results = fetch_crossref(
        keywords=("Interferon",),
        match_mode="OR",
        window_start_dt=window_start,
        window_end_dt=window_end,
        user_agent="PaperWatcher/1.0",
        contact_email="alerts@example.com",
    )

    # Three journals requested; ensure each triggered a request
    assert len(responses.calls) == 3
    first_request = responses.calls[0].request
    assert "alerts@example.com" in first_request.headers["User-Agent"]

    assert len(results) == 1
    item = results[0]
    assert item.paper_id == "10.1234/example"
    assert item.source == "crossref"
    assert item.matched_keywords == ("interferon",)
