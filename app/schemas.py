"""Domain types.

Enums are the contract between the LLM and the routing rules. Anything the model
returns that is not in one of these enums is rejected in ``app.validation`` — the
routing layer never sees free-form model output.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class RequestType(StrEnum):
    TECHNICAL_SUPPORT = "technical_support"
    ADOPTION_QUESTION = "adoption_question"
    HOW_TO = "how_to"
    BILLING = "billing"
    FEATURE_REQUEST = "feature_request"
    ACCOUNT_ACCESS = "account_access"
    STRATEGIC_ADOPTION_BLOCKER = "strategic_adoption_blocker"
    COMMERCIAL_OPPORTUNITY = "commercial_opportunity"
    GENERAL_QUESTION = "general_question"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    WATCH = "watch"
    AT_RISK = "at_risk"
    HIGH_RISK = "high_risk"


class RoutingOutcome(StrEnum):
    ESCALATE = "escalate"
    CSM_REVIEW = "csm_review"
    BILLING = "billing"
    HUMAN_REVIEW = "human_review"
    COMMERCIAL = "commercial"
    ADOPTION = "adoption"
    STANDARD = "standard"


class ResponseMode(StrEnum):
    AUTO = "auto"
    APPROVAL = "approval"
    TEMPLATE = "template"
    NONE = "none"


class InboundMessage(BaseModel):
    """A message arriving from the intake webhook."""

    message_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    customer_email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class Classification(BaseModel):
    """The only shape of LLM output the rest of the app accepts."""

    request_type: RequestType
    sentiment: Sentiment
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(max_length=500)
    blockers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    commercial_signals: list[str] = Field(default_factory=list)


class CustomerSignals(BaseModel):
    """Facts read from the database. The LLM never supplies these."""

    customer_id: str
    adoption_score: int = Field(ge=0, le=100)
    current_health: HealthStatus = HealthStatus.HEALTHY
    health_declining: bool = False
    unresolved_interactions: int = Field(default=0, ge=0)
    days_to_renewal: int | None = None
    cancellation_language: bool = False
    adoption_blocker: bool = False


class HealthAssessment(BaseModel):
    status: HealthStatus
    reasons: list[str] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    outcome: RoutingOutcome
    response_mode: ResponseMode
    health: HealthStatus
    reasons: list[str] = Field(default_factory=list)


class TriageResult(BaseModel):
    message_id: str
    accepted: bool
    classification: Classification | None = None
    routing: RoutingDecision | None = None
    health_reasons: list[str] = Field(default_factory=list)
    requires_human: bool = False
    notes: list[str] = Field(default_factory=list)
