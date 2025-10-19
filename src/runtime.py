"""Runtime option derivation for lambda invocations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from util import parse_keywords

if TYPE_CHECKING:  # pragma: no cover
    from config import AppConfig


@dataclass(slots=True)
class RuntimeOptions:
    """Effective runtime parameters after merging event overrides."""

    keywords: Sequence[str]
    sources: Sequence[str]
    match_mode: str
    window_hours: int
    dry_run: bool
    recipients_override: Sequence[str] | None
    force_send_summary: bool


def _normalize_sources(raw: Any, fallback: Sequence[str]) -> Sequence[str]:
    if isinstance(raw, str):
        candidates = [part.strip().lower() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, Sequence):
        candidates = []
        for item in raw:
            value = str(item).strip().lower()
            if value:
                candidates.append(value)
    else:
        return tuple(fallback)
    unique = []
    seen = set()
    for src in candidates:
        if src not in seen:
            seen.add(src)
            unique.append(src)
    return tuple(unique) if unique else tuple(fallback)


def _normalize_keywords(raw: Any, fallback: Sequence[str]) -> Sequence[str]:
    if isinstance(raw, str):
        parsed = parse_keywords(raw)
    elif isinstance(raw, Sequence):
        parsed = []
        for item in raw:
            value = str(item).strip().lower()
            if value:
                parsed.append(value)
    else:
        parsed = list(fallback)
    if not parsed:
        parsed = list(fallback)
    unique = []
    seen = set()
    for keyword in parsed:
        if keyword not in seen:
            seen.add(keyword)
            unique.append(keyword)
    return tuple(unique)


def _normalize_match_mode(raw: Any, fallback: str) -> str:
    value = str(raw).strip().upper() if isinstance(raw, str) else None
    if value in {"AND", "OR"}:
        return value
    return fallback.upper()


def _normalize_window_hours(raw: Any, fallback: int) -> int:
    if raw is None:
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _normalize_bool(raw: Any, fallback: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return fallback


def _normalize_recipients(raw: Any) -> Sequence[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        parsed = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, Sequence):
        parsed = []
        for item in raw:
            value = str(item).strip()
            if value:
                parsed.append(value)
    else:
        return None
    unique = []
    seen = set()
    for recipient in parsed:
        lowered = recipient.lower()
        if lowered not in seen:
            seen.add(lowered)
            unique.append(recipient)
    return tuple(unique) if unique else None


def derive_runtime_options(config: "AppConfig", event: Mapping[str, Any] | None) -> RuntimeOptions:
    payload: Mapping[str, Any] = event if isinstance(event, Mapping) else {}

    sources = _normalize_sources(payload.get("sources"), config.sources)
    keywords = _normalize_keywords(payload.get("keywords"), config.keywords)
    match_mode = _normalize_match_mode(payload.get("match_mode"), config.match_mode)
    window_hours = _normalize_window_hours(payload.get("window_hours"), config.window_hours)
    dry_run = _normalize_bool(payload.get("dry_run"), False)
    force_send_summary = _normalize_bool(payload.get("force_send_summary"), False)
    recipients_override = _normalize_recipients(payload.get("recipients_override"))

    return RuntimeOptions(
        keywords=keywords,
        sources=sources,
        match_mode=match_mode,
        window_hours=window_hours,
        dry_run=dry_run,
        recipients_override=recipients_override,
        force_send_summary=force_send_summary,
    )
