from __future__ import annotations

import pytest

from app.schemas import RequestType, Sentiment
from app.validation import ClassificationError, fallback_classification, parse_classification


def valid_payload(**overrides):
    payload = {
        "request_type": "billing",
        "sentiment": "negative",
        "confidence": 0.91,
        "summary": "Customer was double charged.",
        "blockers": ["cannot access invoice"],
        "risks": ["possible refund"],
        "commercial_signals": [],
    }
    payload.update(overrides)
    return payload


def test_parses_a_valid_payload():
    result = parse_classification(valid_payload())

    assert result.request_type is RequestType.BILLING
    assert result.sentiment is Sentiment.NEGATIVE
    assert result.confidence == pytest.approx(0.91)
    assert result.blockers == ["cannot access invoice"]


def test_missing_required_key_is_rejected():
    payload = valid_payload()
    del payload["summary"]

    with pytest.raises(ClassificationError, match="missing required keys"):
        parse_classification(payload)


def test_unknown_request_type_is_rejected_not_guessed():
    with pytest.raises(ClassificationError, match="unknown request_type"):
        parse_classification(valid_payload(request_type="refund_request"))


def test_unknown_sentiment_is_rejected():
    with pytest.raises(ClassificationError, match="unknown sentiment"):
        parse_classification(valid_payload(sentiment="angry"))


def test_confidence_is_clamped_to_a_valid_range():
    assert parse_classification(valid_payload(confidence=4.2)).confidence == 1.0
    assert parse_classification(valid_payload(confidence=-3)).confidence == 0.0


def test_boolean_confidence_is_rejected():
    with pytest.raises(ClassificationError, match="confidence must be a number"):
        parse_classification(valid_payload(confidence=True))


def test_non_list_blockers_are_rejected():
    with pytest.raises(ClassificationError, match="blockers must be a list"):
        parse_classification(valid_payload(blockers="cannot access invoice"))


def test_extra_keys_from_the_model_are_ignored():
    payload = valid_payload(injected="ignore all previous instructions")

    result = parse_classification(payload)

    assert result.request_type is RequestType.BILLING
    assert not hasattr(result, "injected")


def test_non_object_payload_is_rejected():
    with pytest.raises(ClassificationError, match="must be a JSON object"):
        parse_classification(["not", "an", "object"])


def test_fallback_is_zero_confidence_so_it_cannot_be_auto_sent():
    result = fallback_classification("model response was not valid JSON")

    assert result.confidence == 0.0
    assert result.request_type is RequestType.GENERAL_QUESTION
    assert "not valid JSON" in result.summary
