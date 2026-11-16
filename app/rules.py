"""Deterministic routing rules.

Every decision that affects a customer is made here, in plain code, from typed
inputs. The LLM contributes a classification; it does not get to decide who is
escalated or whether an email goes out. That split is the whole point of the
design: model output can be wrong, but it cannot be *in control*.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import (
    Classification,
    CustomerSignals,
    HealthAssessment,
    HealthStatus,
    RequestType,
    ResponseMode,
    RoutingDecision,
    RoutingOutcome,
    Sentiment,
)

_SEVERITY = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.WATCH: 1,
    HealthStatus.AT_RISK: 2,
    HealthStatus.HIGH_RISK: 3,
}

# Health levels at which an automatic reply is allowed, subject to confidence.
_LOW_RISK = frozenset({HealthStatus.HEALTHY, HealthStatus.WATCH})

# Request types that route to a specialist queue even when health is fine.
_ADOPTION_TYPES = frozenset({RequestType.STRATEGIC_ADOPTION_BLOCKER, RequestType.ADOPTION_QUESTION})


@dataclass(frozen=True)
class Thresholds:
    min_confidence: float = 0.70
    auto_send_confidence: float = 0.80


DEFAULT_THRESHOLDS = Thresholds()


def assess_health(
    classification: Classification,
    signals: CustomerSignals,
) -> HealthAssessment:
    """Raise the customer's risk level from message + account signals.

    Rules can only raise risk. Lowering a health status is a human decision, so
    an existing higher status always wins over a computed lower one.
    """
    computed = HealthStatus.HEALTHY
    reasons: list[str] = []

    def raise_to(status: HealthStatus, reason: str) -> None:
        nonlocal computed
        if _SEVERITY[status] > _SEVERITY[computed]:
            computed = status
        reasons.append(reason)

    sentiment = classification.sentiment
    negative = sentiment in (Sentiment.NEGATIVE, Sentiment.VERY_NEGATIVE)

    if sentiment == Sentiment.VERY_NEGATIVE and signals.health_declining:
        raise_to(
            HealthStatus.HIGH_RISK,
            "very negative sentiment while account health is declining",
        )

    if signals.cancellation_language:
        if signals.days_to_renewal is not None and signals.days_to_renewal <= 90:
            raise_to(
                HealthStatus.HIGH_RISK,
                f"cancellation language within {signals.days_to_renewal} days of renewal",
            )
        else:
            raise_to(HealthStatus.AT_RISK, "cancellation language detected")

    if negative and signals.adoption_blocker:
        raise_to(HealthStatus.AT_RISK, "negative sentiment plus an adoption blocker")

    if negative and signals.unresolved_interactions >= 3:
        raise_to(
            HealthStatus.AT_RISK,
            f"{signals.unresolved_interactions} unresolved interactions with negative sentiment",
        )

    if signals.adoption_score < 40:
        if signals.days_to_renewal is not None and signals.days_to_renewal <= 90:
            raise_to(
                HealthStatus.AT_RISK,
                f"adoption score {signals.adoption_score} with renewal in "
                f"{signals.days_to_renewal} days",
            )
        else:
            raise_to(HealthStatus.WATCH, f"adoption score {signals.adoption_score} is below 40")

    if signals.adoption_blocker:
        raise_to(HealthStatus.WATCH, "open adoption blocker on the account")

    if _SEVERITY[signals.current_health] > _SEVERITY[computed]:
        reasons.append(
            f"keeping stored status {signals.current_health.value}; "
            "lowering health requires a human"
        )
        return HealthAssessment(status=signals.current_health, reasons=reasons)

    return HealthAssessment(status=computed, reasons=reasons)


def decide_routing(
    classification: Classification,
    signals: CustomerSignals,
    health: HealthStatus,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> RoutingDecision:
    """Pick the queue and the response mode.

    Priority: escalate > csm_review > billing > human_review > commercial >
    adoption > standard. First match wins, which is why the order is explicit.
    """
    reasons: list[str] = []

    if health == HealthStatus.HIGH_RISK:
        outcome = RoutingOutcome.ESCALATE
        reasons.append("high-risk account")
    elif health == HealthStatus.AT_RISK:
        outcome = RoutingOutcome.CSM_REVIEW
        reasons.append("at-risk account")
    elif classification.request_type == RequestType.BILLING:
        outcome = RoutingOutcome.BILLING
        reasons.append("billing request uses a fixed template, no AI decision")
    elif classification.confidence < thresholds.min_confidence:
        outcome = RoutingOutcome.HUMAN_REVIEW
        reasons.append(
            f"confidence {classification.confidence:.2f} below {thresholds.min_confidence:.2f}"
        )
    elif classification.request_type == RequestType.COMMERCIAL_OPPORTUNITY:
        outcome = RoutingOutcome.COMMERCIAL
        reasons.append("commercial opportunity")
    elif classification.request_type in _ADOPTION_TYPES:
        outcome = RoutingOutcome.ADOPTION
        reasons.append(f"adoption-related request ({classification.request_type.value})")
    else:
        outcome = RoutingOutcome.STANDARD
        reasons.append("standard queue")

    response_mode = _response_mode(classification, health, outcome, thresholds)
    reasons.append(f"response mode: {response_mode.value}")

    return RoutingDecision(
        outcome=outcome,
        response_mode=response_mode,
        health=health,
        reasons=reasons,
    )


def _response_mode(
    classification: Classification,
    health: HealthStatus,
    outcome: RoutingOutcome,
    thresholds: Thresholds,
) -> ResponseMode:
    if outcome == RoutingOutcome.BILLING:
        return ResponseMode.TEMPLATE
    if outcome == RoutingOutcome.HUMAN_REVIEW:
        return ResponseMode.NONE
    if outcome in (RoutingOutcome.ESCALATE, RoutingOutcome.CSM_REVIEW):
        return ResponseMode.APPROVAL
    if health in _LOW_RISK and classification.confidence >= thresholds.auto_send_confidence:
        return ResponseMode.AUTO
    return ResponseMode.APPROVAL
