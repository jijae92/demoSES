from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Sequence

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "keywords.yml"
_REGISTRY_LOCK = threading.Lock()
_REGISTRY_CACHE: "KeywordRegistry | None" = None
_REGISTRY_MTIME: float | None = None


def _normalize_phrase(value: str) -> str:
    normalized = " ".join(value.strip().lower().split())
    if not normalized:
        raise ValueError("Empty phrase encountered while normalizing keywords.yml")
    return normalized


def _phrase_in_text(phrase: str, text: str) -> bool:
    if phrase == text:
        return True
    pattern = re.compile(rf"\b{re.escape(phrase)}\b")
    return bool(pattern.search(text))


@dataclass(frozen=True)
class KeywordEntry:
    canonical_id: str
    terms: tuple[str, ...]
    synonyms: tuple[str, ...]
    typos: tuple[str, ...]
    negative_terms: tuple[str, ...]
    filters: Mapping[str, Any]
    boosts: Mapping[str, Any]
    rerank: Mapping[str, Any]

    @property
    def all_terms(self) -> Sequence[str]:
        return (*self.terms, *self.synonyms, *self.typos)


class KeywordRegistry:
    def __init__(self, entries: Sequence[KeywordEntry]) -> None:
        self._entries: Dict[str, KeywordEntry] = {}
        self._lookups: Dict[str, Dict[str, tuple[str, str]]] = {
            "exact": {},
            "synonym": {},
            "typo": {},
        }

        for entry in entries:
            if entry.canonical_id in self._entries:
                raise ValueError(f"Duplicated keyword id '{entry.canonical_id}'")
            self._entries[entry.canonical_id] = entry
            self._register_terms(entry, "exact", entry.terms)
            self._register_terms(entry, "synonym", entry.synonyms)
            self._register_terms(entry, "typo", entry.typos)

    def _register_terms(
        self,
        entry: KeywordEntry,
        mode: str,
        phrases: Iterable[str],
    ) -> None:
        lookup = self._lookups[mode]
        for phrase in phrases:
            normalized = _normalize_phrase(phrase)
            if normalized in lookup:
                existing_id, existing_phrase = lookup[normalized]
                raise ValueError(
                    f"Phrase '{phrase}' for '{entry.canonical_id}' "
                    f"already registered by '{existing_id}' as '{existing_phrase}'",
                )
            lookup[normalized] = (entry.canonical_id, phrase)

    def match(self, query: str) -> tuple[KeywordEntry, str, str] | None:
        normalized_query = _normalize_phrase(query)
        for mode in ("exact", "synonym", "typo"):
            hit = self._lookups[mode].get(normalized_query)
            if hit:
                canonical_id, phrase = hit
                return self._entries[canonical_id], phrase, mode

        for mode in ("exact", "synonym", "typo"):
            for normalized_phrase, (canonical_id, phrase) in self._lookups[mode].items():
                if _phrase_in_text(normalized_phrase, normalized_query):
                    return self._entries[canonical_id], phrase, mode
        return None

    def get(self, canonical_id: str) -> KeywordEntry:
        return self._entries[canonical_id]


def _read_keywords_file(path: Path) -> Sequence[Mapping[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Keyword registry file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or []
    if not isinstance(payload, Sequence):
        raise ValueError("keywords.yml must contain a sequence of keyword entries")
    return payload


def _coerce_sequence(mapping: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = mapping.get(key, []) or []
    if isinstance(raw, str):
        values = [raw]
    else:
        values = list(raw)
    result = []
    for item in values:
        text = str(item).strip()
        if text:
            result.append(text)
    return tuple(result)


def _coerce_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = mapping.get(key, {}) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Expected '{key}' to be a mapping in keywords.yml")
    return MappingProxyType(dict(raw))


def _build_entry(payload: Mapping[str, Any]) -> KeywordEntry:
    if not isinstance(payload, Mapping):
        raise ValueError("Each keyword entry must be a mapping")
    try:
        canonical_id = str(payload["id"]).strip()
    except KeyError as exc:
        raise ValueError("Keyword entry missing required 'id'") from exc
    if not canonical_id:
        raise ValueError("Keyword entry 'id' may not be blank")

    terms = _coerce_sequence(payload, "terms")
    if not terms:
        raise ValueError(f"Keyword '{canonical_id}' requires at least one term")

    synonyms = _coerce_sequence(payload, "synonyms")
    typos = _coerce_sequence(payload, "typos")
    negative_terms = _coerce_sequence(payload, "negative_terms")
    filters = _coerce_mapping(payload, "filters")
    boosts = _coerce_mapping(payload, "boosts")
    rerank = _coerce_mapping(payload, "rerank")

    return KeywordEntry(
        canonical_id=canonical_id,
        terms=terms,
        synonyms=synonyms,
        typos=typos,
        negative_terms=negative_terms,
        filters=filters,
        boosts=boosts,
        rerank=rerank,
    )


def load_keywords(*, force_reload: bool = False, path: Path | None = None) -> KeywordRegistry:
    path = path or _CONFIG_PATH
    global _REGISTRY_CACHE, _REGISTRY_MTIME
    with _REGISTRY_LOCK:
        mtime = path.stat().st_mtime
        if (
            not force_reload
            and _REGISTRY_CACHE is not None
            and _REGISTRY_MTIME == mtime
        ):
            return _REGISTRY_CACHE

        payload = _read_keywords_file(path)
        entries = [_build_entry(item) for item in payload]
        _REGISTRY_CACHE = KeywordRegistry(entries)
        _REGISTRY_MTIME = mtime
        return _REGISTRY_CACHE


def resolve(query: str, *, registry: KeywordRegistry | None = None) -> dict[str, str] | None:
    if not query or not query.strip():
        return None
    registry = registry or load_keywords()
    match = registry.match(query)
    if not match:
        return None
    entry, phrase, mode = match
    return {
        "canonical_id": entry.canonical_id,
        "matched_term": phrase,
        "mode": mode,
    }


def validate_only(query: str, *, lenient: bool = False) -> dict[str, str] | None:
    match = resolve(query)
    if match is None:
        if lenient:
            return None
        raise ValueError(f"Unapproved keyword detected: {query!r}")
    return match
