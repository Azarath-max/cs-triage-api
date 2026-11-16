from __future__ import annotations

import pytest

from app.rules import assess_health, decide_routing
from app.schemas import (
    Classification,
    CustomerSignals,
    HealthStatus,
    RequestType,
    ResponseMode,
    RoutingOutcome,
    Sentiment,
)


def make_classification(
    request_type: RequestType = RequestType.GENERAL_QUESTION,
    sentiment: Sentiment = Sentiment.NEUTRAL,
    confidence: float = 0.9,
) -> Classification:
    return Classification(
        request_type=request_type,
        sentiment=sentiment,
        confidence=confidence,
        summary="test message",
    )


def make_signals(**overrides) -> CustomerSignals:
    base = {
        "customer_id": "cust-1",
        "adoption_score": 80,
        "current_health": HealthStatus.HEALTHY,
    }
    base.update(overrides)
    return CustomerSignals(**base)


# --------------------------------------------------------------------------- #
# Health rules
# --------------------------------------------------------------------------- #


def test_healthy_account_with_no_triggers_stays_healthy():
    result = assess_health(make_classification(), make_signals())

    assert result.status is HealthStatus.HEALTHY
    assert result.reasons == []


def test_very_negative_sentiment_plus_declining_health_is_high_risk():
    result = assess_health(
        make_classification(sentiment=Sentiment.VERY_NEGATIVE),
        make_signals(health_declining=True),
    )

    assert result.status is HealthStatus.HIGH_RISK
    assert any("very negative" in reason for reason in result.reasons)


def test_cancellation_language_near_renewal_is_high_risk():
    result = assess_health(
        make_classification(sentiment=Sentiment.NEGATIVE),
        make_signals(cancellation_language=True, days_to_renewal=45),
    )

    assert result.status is HealthStatus.HIGH_RISK


def test_cancellation_language_without_a_renewal_date_is_at_risk():
    result = assess_health(
        make_classification(sentiment=Sentiment.NEGATIVE),
        make_signals(cancellation_language=True, days_to_renewal=None),
    )

    assert result.status is HealthStatus.AT_RISK


def test_negative_sentiment_plus_adoption_blocker_is_at_risk():
    result = assess_health(
        make_classification(sentiment=Sentiment.NEGATIVE),
        make_signals(adoption_blocker=True),
    )

    assert result.status is HealthStatus.AT_RISK


def test_three_unresolved_interactions_with_negative_sentiment_is_at_risk():
    result = assess_health(
        make_classification(sentiment=Sentiment.NEGATIVE),
        make_signals(unresolved_interactions=3),
    )

    assert result.status is HealthStatus.AT_RISK


def test_two_unresolved_interactions_is_not_enough():
    result = assess_health(
        make_classification(sentiment=Sentiment.NEGATIVE),
        make_signals(unresolved_interactions=2),
    )

    assert result.status is HealthStatus.HEALTHY


def test_low_adoption_is_watch():
    result = assess_health(make_classification(), make_signals(adoption_score=35))

    assert result.status is HealthStatus.WATCH


def test_low_adoption_near_renewal_is_at_risk():
    result = assess_health(
        make_classification(),
        make_signals(adoption_score=35, days_to_renewal=60),
    )

    assert result.status is HealthStatus.AT_RISK


def test_stored_health_is_never_lowered_by_rules():
    result = assess_health(
        make_classification(),
        make_signals(current_health=HealthStatus.AT_RISK),
    )

    assert result.status is HealthStatus.AT_RISK
    assert any("lowering health requires a human" in reason for reason in result.reasons)


def test_adoption_blocker_alone_is_watch():
    result = assess_health(
        make_classification(sentiment=Sentiment.NEUTRAL),
        make_signals(adoption_blocker=True),
    )

    assert result.status is HealthStatus.WATCH


# --------------------------------------------------------------------------- #
# Routing rules
# --------------------------------------------------------------------------- #


def test_high_risk_escalates_and_requires_approval():
    decision = decide_routing(
        make_classification(),
        make_signals(),
        HealthStatus.HIGH_RISK,
    )

    assert decision.outcome is RoutingOutcome.ESCALATE
    assert decision.response_mode is ResponseMode.APPROVAL


def test_at_risk_goes_to_csm_review():
    decision = decide_routing(
        make_classification(),
        make_signals(),
        HealthStatus.AT_RISK,
    )

    assert decision.outcome is RoutingOutcome.CSM_REVIEW
    assert decision.response_mode is ResponseMode.APPROVAL


def test_billing_uses_a_template_and_no_ai_decision():
    decision = decide_routing(
        make_classification(request_type=RequestType.BILLING, confidence=0.99),
        make_signals(),
        HealthStatus.HEALTHY,
    )

    assert decision.outcome is RoutingOutcome.BILLING
    assert decision.response_mode is ResponseMode.TEMPLATE


def test_high_risk_beats_billing_in_priority_order():
    decision = decide_routing(
        make_classification(request_type=RequestType.BILLING),
        make_signals(),
        HealthStatus.HIGH_RISK,
    )

    assert decision.outcome is RoutingOutcome.ESCALATE


def test_low_confidence_goes_to_human_review_with_no_draft():
    decision = decide_routing(
        make_classification(confidence=0.4),
        make_signals(),
        HealthStatus.HEALTHY,
    )

    assert decision.outcome is RoutingOutcome.HUMAN_REVIEW
    assert decision.response_mode is ResponseMode.NONE


def test_billing_beats_low_confidence():
    decision = decide_routing(
        make_classification(request_type=RequestType.BILLING, confidence=0.2),
        make_signals(),
        HealthStatus.HEALTHY,
    )

    assert decision.outcome is RoutingOutcome.BILLING


def test_high_confidence_healthy_message_can_be_auto_sent():
    decision = decide_routing(
        make_classification(confidence=0.9),
        make_signals(),
        HealthStatus.HEALTHY,
    )

    assert decision.outcome is RoutingOutcome.STANDARD
    assert decision.response_mode is ResponseMode.AUTO


def test_confidence_between_thresholds_requires_approval():
    decision = decide_routing(
        make_classification(confidence=0.75),
        make_signals(),
        HealthStatus.HEALTHY,
    )

    assert decision.response_mode is ResponseMode.APPROVAL


def test_commercial_opportunity_goes_to_the_commercial_queue():
    decision = decide_routing(
        make_classification(request_type=RequestType.COMMERCIAL_OPPORTUNITY),
        make_signals(),
        HealthStatus.HEALTHY,
    )

    assert decision.outcome is RoutingOutcome.COMMERCIAL


@pytest.mark.parametrize(
    "request_type",
    [RequestType.ADOPTION_QUESTION, RequestType.STRATEGIC_ADOPTION_BLOCKER],
)
def test_adoption_types_route_to_the_adoption_queue(request_type):
    decision = decide_routing(
        make_classification(request_type=request_type),
        make_signals(),
        HealthStatus.HEALTHY,
    )

    assert decision.outcome is RoutingOutcome.ADOPTION
