from __future__ import annotations

from app.classifier import DeterministicClassifier
from app.main import app, get_classifier, get_repository
from app.repository import InMemoryRepository
from app.schemas import CustomerSignals
from tests.conftest import make_message


class CountingClassifier:
    def __init__(self) -> None:
        self.calls = 0

    def classify(self, message):
        self.calls += 1
        return DeterministicClassifier().classify(message)


def test_health_endpoint_reports_mode(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["repository"] == "memory"


def test_valid_message_is_accepted_and_routed(client):
    response = client.post("/v1/messages", json=make_message())

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["classification"]["request_type"] == "how_to"
    assert body["routing"]["outcome"] == "standard"


def test_invalid_email_is_rejected(client):
    response = client.post("/v1/messages", json=make_message(customer_email="not-an-email"))

    assert response.status_code == 422


def test_message_id_must_be_safe_for_logs_and_queries(client):
    response = client.post("/v1/messages", json=make_message(message_id="../../etc/passwd"))

    assert response.status_code == 422


def test_oversized_body_is_rejected(client):
    response = client.post("/v1/messages", json=make_message(body="x" * 6000))

    assert response.status_code == 422


def test_duplicate_message_is_ignored(client):
    client.post("/v1/messages", json=make_message())

    second = client.post("/v1/messages", json=make_message())

    assert second.status_code == 202
    assert second.json()["accepted"] is False


def test_duplicate_never_reaches_the_model(client):
    counter = CountingClassifier()
    app.dependency_overrides[get_classifier] = lambda: counter

    client.post("/v1/messages", json=make_message())
    client.post("/v1/messages", json=make_message())

    assert counter.calls == 1


def test_unknown_sender_requires_a_human_and_sends_nothing(client):
    response = client.post(
        "/v1/messages",
        json=make_message(customer_email="stranger@example.com"),
    )

    body = response.json()
    assert body["routing"]["outcome"] == "human_review"
    assert body["routing"]["response_mode"] == "none"
    assert body["requires_human"] is True


def test_failed_classification_degrades_to_human_review(failing_client):
    response = failing_client.post("/v1/messages", json=make_message())

    body = response.json()
    assert body["classification"]["confidence"] == 0.0
    assert body["routing"]["response_mode"] == "none"
    assert body["requires_human"] is True


def test_billing_request_uses_a_template(client):
    response = client.post(
        "/v1/messages",
        json=make_message(subject="Invoice", body="I need my invoice for last month"),
    )

    body = response.json()
    assert body["routing"]["outcome"] == "billing"
    assert body["routing"]["response_mode"] == "template"


def test_webhook_secret_is_enforced_only_when_configured(client):
    client.app.state.settings.webhook_secret = "s3cret"
    try:
        denied = client.post("/v1/messages", json=make_message())
        assert denied.status_code == 401

        allowed = client.post(
            "/v1/messages",
            json=make_message(message_id="msg-002"),
            headers={"X-Webhook-Secret": "s3cret"},
        )
        assert allowed.status_code == 202
    finally:
        client.app.state.settings.webhook_secret = ""


def test_audit_log_records_the_decision_and_its_reasons(client, repo: InMemoryRepository):
    client.post("/v1/messages", json=make_message())

    assert repo.events[0]["event"] == "triaged"
    assert repo.events[0]["details"]["outcome"] == "standard"
    assert repo.events[0]["details"]["reasons"]


def test_response_explains_why_an_account_was_flagged(client):
    risky = InMemoryRepository(
        {
            "risky@example.com": CustomerSignals(
                customer_id="cust-9",
                adoption_score=20,
                days_to_renewal=30,
            )
        }
    )
    app.dependency_overrides[get_repository] = lambda: risky

    response = client.post(
        "/v1/messages",
        json=make_message(message_id="msg-risky", customer_email="risky@example.com"),
    )

    body = response.json()
    assert body["routing"]["health"] == "at_risk"
    assert body["routing"]["outcome"] == "csm_review"
    assert any("adoption score" in reason for reason in body["health_reasons"])
