from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_classifier, get_repository
from app.repository import InMemoryRepository
from app.schemas import CustomerSignals, HealthStatus, InboundMessage
from app.validation import ClassificationError


def make_message(**overrides) -> dict:
    payload = {
        "message_id": "msg-001",
        "customer_email": "ada@example.com",
        "subject": "Question about the export",
        "body": "How do I export my data to CSV?",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def healthy_customer() -> CustomerSignals:
    return CustomerSignals(
        customer_id="cust-1",
        adoption_score=82,
        current_health=HealthStatus.HEALTHY,
    )


@pytest.fixture
def repo(healthy_customer: CustomerSignals) -> InMemoryRepository:
    return InMemoryRepository({"ada@example.com": healthy_customer})


@pytest.fixture
def client(repo: InMemoryRepository):
    app.dependency_overrides[get_repository] = lambda: repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class FailingClassifier:
    """Simulates a model that returns something unparseable."""

    def classify(self, message: InboundMessage):
        raise ClassificationError("model response was not valid JSON")


@pytest.fixture
def failing_client(repo: InMemoryRepository):
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_classifier] = lambda: FailingClassifier()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
