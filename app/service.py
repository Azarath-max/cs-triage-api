"""Orchestration: validate input -> classify -> validate output -> rules -> persist.

Kept separate from the HTTP layer so it can be tested as a plain function.
"""

from __future__ import annotations

from app.classifier import Classifier
from app.repository import Repository
from app.rules import DEFAULT_THRESHOLDS, Thresholds, assess_health, decide_routing
from app.schemas import (
    HealthStatus,
    InboundMessage,
    ResponseMode,
    RoutingDecision,
    RoutingOutcome,
    TriageResult,
)
from app.validation import ClassificationError, fallback_classification


def triage(
    message: InboundMessage,
    *,
    classifier: Classifier,
    repository: Repository,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> TriageResult:
    if repository.is_duplicate(message.message_id):
        repository.log_event(message.message_id, "duplicate_ignored", {})
        return TriageResult(
            message_id=message.message_id,
            accepted=False,
            notes=["duplicate message_id ignored"],
        )

    notes: list[str] = []

    try:
        classification = classifier.classify(message)
    except ClassificationError as exc:
        classification = fallback_classification(str(exc))
        notes.append(f"classification failed: {exc}")

    signals = repository.get_customer_signals(message.customer_email)

    if signals is None:
        routing = RoutingDecision(
            outcome=RoutingOutcome.HUMAN_REVIEW,
            response_mode=ResponseMode.NONE,
            health=HealthStatus.HEALTHY,
            reasons=[
                "sender does not match a known customer",
                "no automatic reply is sent to an unknown sender",
            ],
        )
        repository.save_interaction(message, classification, routing, customer_id=None)
        repository.log_event(
            message.message_id,
            "unknown_sender",
            {"email": message.customer_email, "confidence": classification.confidence},
        )
        return TriageResult(
            message_id=message.message_id,
            accepted=True,
            classification=classification,
            routing=routing,
            requires_human=True,
            notes=[*notes, "unknown sender saved for human review"],
        )

    health = assess_health(classification, signals)
    routing = decide_routing(classification, signals, health.status, thresholds)

    repository.save_interaction(message, classification, routing, signals.customer_id)
    repository.log_event(
        message.message_id,
        "triaged",
        {
            "outcome": routing.outcome.value,
            "response_mode": routing.response_mode.value,
            "health": health.status.value,
            "confidence": classification.confidence,
            "reasons": [*health.reasons, *routing.reasons],
        },
    )

    requires_human = routing.response_mode in (ResponseMode.APPROVAL, ResponseMode.NONE)

    return TriageResult(
        message_id=message.message_id,
        accepted=True,
        classification=classification,
        routing=routing,
        health_reasons=health.reasons,
        requires_human=requires_human,
        notes=notes,
    )
