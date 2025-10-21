from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .keyword_registry import KeywordRegistry, load_keywords, resolve

STRICT = "STRICT"
LENIENT = "LENIENT"
_ALLOWED_POLICIES = {STRICT, LENIENT}


@dataclass(frozen=True)
class ParsedQuery:
    canonical_id: str
    matched_term: str
    mode: str
    filters: Mapping[str, Any]
    boosts: Mapping[str, Any]
    rerank: Mapping[str, Any]
    negative_terms: tuple[str, ...]
    must_not: tuple[str, ...]
    ignored: tuple[str, ...]
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "matched_term": self.matched_term,
            "mode": self.mode,
            "filters": dict(self.filters),
            "boosts": dict(self.boosts),
            "rerank": dict(self.rerank),
            "negative_terms": list(self.negative_terms),
            "must_not": list(self.must_not),
            "ignored": list(self.ignored),
            "raw": self.raw,
        }


def _normalize_policy(policy: str | None) -> str:
    if not policy:
        return STRICT
    value = policy.strip().upper()
    if value not in _ALLOWED_POLICIES:
        raise ValueError(f"Unsupported parser policy '{policy}'")
    return value


def _extract_remainder_tokens(source: str, matched_term: str) -> tuple[str, ...]:
    lowered_source = source.lower()
    lowered_match = matched_term.lower()
    pattern = re.compile(rf"\b{re.escape(lowered_match)}\b")
    remainder = pattern.sub(" ", lowered_source, count=1)
    candidates = re.findall(r"[a-z0-9@._-]+", remainder)
    ordered = []
    seen = set()
    for token in candidates:
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)
    return tuple(ordered)


def parse(
    query: str,
    *,
    policy: Literal["STRICT", "LENIENT"] | str = STRICT,
    registry: KeywordRegistry | None = None,
) -> ParsedQuery | None:
    if not query or not query.strip():
        raise ValueError("Query must be a non-empty string")

    policy_value = _normalize_policy(policy)
    registry = registry or load_keywords()
    match = resolve(query, registry=registry)

    if match is None:
        if policy_value == LENIENT:
            return None
        raise ValueError(f"Query does not contain an approved keyword: {query!r}")

    entry = registry.get(match["canonical_id"])
    remainder_tokens = _extract_remainder_tokens(query, match["matched_term"])
    if policy_value == STRICT:
        must_not = remainder_tokens
        ignored: tuple[str, ...] = ()
    else:
        must_not = ()
        ignored = remainder_tokens

    return ParsedQuery(
        canonical_id=entry.canonical_id,
        matched_term=match["matched_term"],
        mode=match["mode"],
        filters=dict(entry.filters),
        boosts=dict(entry.boosts),
        rerank=dict(entry.rerank),
        negative_terms=entry.negative_terms,
        must_not=must_not,
        ignored=ignored,
        raw=query,
    )
