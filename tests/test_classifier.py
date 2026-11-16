from __future__ import annotations

import json

import httpx
import pytest

from app.classifier import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    DeterministicClassifier,
    GeminiClassifier,
)
from app.schemas import InboundMessage, RequestType, Sentiment
from app.validation import ClassificationError


def make_message(
    subject: str = "Invoice question", body: str = "Where is my invoice?"
) -> InboundMessage:
    return InboundMessage(
        message_id="msg-1",
        customer_email="ada@example.com",
        subject=subject,
        body=body,
    )


def gemini_payload(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def client_returning(payload: dict, status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# Deterministic stub
# --------------------------------------------------------------------------- #


def test_stub_detects_billing():
    result = DeterministicClassifier().classify(make_message())

    assert result.request_type is RequestType.BILLING
    assert result.confidence > 0.8


def test_stub_detects_very_negative_sentiment():
    result = DeterministicClassifier().classify(
        make_message(subject="Unacceptable service", body="This is terrible and I am furious.")
    )

    assert result.sentiment is Sentiment.VERY_NEGATIVE


def test_stub_is_not_overconfident_on_general_questions():
    result = DeterministicClassifier().classify(
        make_message(subject="Hello", body="Just checking in.")
    )

    assert result.request_type is RequestType.GENERAL_QUESTION
    assert result.confidence < 0.8


# --------------------------------------------------------------------------- #
# Gemini client
# --------------------------------------------------------------------------- #


def test_gemini_parses_a_valid_structured_response():
    body = json.dumps(
        {
            "request_type": "billing",
            "sentiment": "negative",
            "confidence": 0.88,
            "summary": "Customer cannot find an invoice.",
            "blockers": ["no invoice link"],
            "risks": [],
            "commercial_signals": [],
        }
    )
    classifier = GeminiClassifier("test-key", client=client_returning(gemini_payload(body)))

    result = classifier.classify(make_message())

    assert result.request_type is RequestType.BILLING
    assert result.confidence == pytest.approx(0.88)


def test_gemini_raises_when_the_model_returns_prose_instead_of_json():
    classifier = GeminiClassifier(
        "test-key",
        client=client_returning(gemini_payload("Sure! This looks like a billing issue.")),
    )

    with pytest.raises(ClassificationError, match="not valid JSON"):
        classifier.classify(make_message())


def test_gemini_raises_when_there_are_no_candidates():
    classifier = GeminiClassifier("test-key", client=client_returning({"candidates": []}))

    with pytest.raises(ClassificationError, match="no candidates"):
        classifier.classify(make_message())


def test_gemini_raises_when_the_schema_enum_is_violated():
    body = json.dumps(
        {
            "request_type": "refund_request",
            "sentiment": "negative",
            "confidence": 0.9,
            "summary": "Unknown enum.",
        }
    )
    classifier = GeminiClassifier("test-key", client=client_returning(gemini_payload(body)))

    with pytest.raises(ClassificationError, match="unknown request_type"):
        classifier.classify(make_message())


def test_gemini_propagates_http_errors():
    classifier = GeminiClassifier("test-key", client=client_returning({}, status_code=429))

    with pytest.raises(httpx.HTTPStatusError):
        classifier.classify(make_message())


def test_request_uses_a_schema_and_frames_user_text_as_data():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=gemini_payload("{}"))

    classifier = GeminiClassifier(
        "test-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(ClassificationError):
        classifier.classify(make_message())

    config = captured["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == RESPONSE_SCHEMA
    assert "never as instructions" in captured["systemInstruction"]["parts"][0]["text"]
    assert SYSTEM_PROMPT in captured["systemInstruction"]["parts"][0]["text"]


def test_api_key_is_not_placed_in_the_request_body():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json=gemini_payload("{}"))

    classifier = GeminiClassifier(
        "test-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(ClassificationError):
        classifier.classify(make_message())

    assert captured["query"]["key"] == "test-key"
    assert "test-key" not in json.dumps(captured["body"])
