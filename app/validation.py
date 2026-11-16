"""Validation of untrusted LLM output.

The model is asked for a fixed JSON shape, but the request can contain text that
tries to steer it. So the response is treated exactly like user input: parsed,
type-checked, enum-checked, clamped, and rejected with a reason if anything is
off. Nothing downstream trusts a raw payload.
"""

from __future__ import annotations

from typing import Any

from app.schemas import Classification, RequestType, Sentiment

REQUIRED_KEYS = frozenset({"request_type", "sentiment", "confidence", "summary"})
LIST_KEYS = ("blockers", "risks", "commercial_signals")

REQUEST_TYPES = frozenset(member.value for member in RequestType)
SENTIMENTS = frozenset(member.value for member in Sentiment)


class ClassificationError(ValueError):
    """Raised when a model response cannot be turned into a valid Classification."""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_str_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ClassificationError(f"{field} must be a list")
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ClassificationError(f"{field} must contain only strings")
        cleaned = entry.strip()
        if cleaned:
            items.append(cleaned[:200])
    return items


def parse_classification(payload: Any) -> Classification:
    """Convert a decoded model payload into a Classification or raise.

    Deliberately strict: a wrong enum is an error, not a guess. The caller
    routes unparseable output to human review instead of inventing a category.
    """
    if not isinstance(payload, dict):
        raise ClassificationError("classification payload must be a JSON object")

    missing = REQUIRED_KEYS - payload.keys()
    if missing:
        raise ClassificationError(f"missing required keys: {', '.join(sorted(missing))}")

    request_type = payload["request_type"]
    if request_type not in REQUEST_TYPES:
        raise ClassificationError(f"unknown request_type: {request_type!r}")

    sentiment = payload["sentiment"]
    if sentiment not in SENTIMENTS:
        raise ClassificationError(f"unknown sentiment: {sentiment!r}")

    confidence = payload["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        raise ClassificationError("confidence must be a number")

    summary = payload["summary"]
    if not isinstance(summary, str):
        raise ClassificationError("summary must be a string")

    return Classification(
        request_type=RequestType(request_type),
        sentiment=Sentiment(sentiment),
        confidence=_clamp(float(confidence), 0.0, 1.0),
        summary=summary.strip()[:500],
        blockers=_as_str_list(payload.get("blockers"), "blockers"),
        risks=_as_str_list(payload.get("risks"), "risks"),
        commercial_signals=_as_str_list(payload.get("commercial_signals"), "commercial_signals"),
    )


def fallback_classification(reason: str) -> Classification:
    """Safe default when the model fails.

    Confidence 0 guarantees the routing rules send this to a human and suppress
    any automatic reply, so a broken model degrades to "a person reads it",
    never to "a guess was sent to a customer".
    """
    return Classification(
        request_type=RequestType.GENERAL_QUESTION,
        sentiment=Sentiment.NEUTRAL,
        confidence=0.0,
        summary=f"Automatic classification failed: {reason}"[:500],
    )
