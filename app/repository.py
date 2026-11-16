"""Persistence boundaries.

The service depends on this protocol, not on Postgres. That is what lets the API
tests run with no database and no Docker, and it is why swapping Postgres for
something else later touches one file.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.schemas import Classification, CustomerSignals, InboundMessage, RoutingDecision


class Repository(Protocol):
    def is_duplicate(self, message_id: str) -> bool: ...

    def get_customer_signals(self, email: str) -> CustomerSignals | None: ...

    def save_interaction(
        self,
        message: InboundMessage,
        classification: Classification,
        routing: RoutingDecision,
        customer_id: str | None,
    ) -> None: ...

    def log_event(self, message_id: str, event: str, details: dict[str, Any]) -> None: ...


class InMemoryRepository:
    """Used by tests and by ``REPOSITORY=memory`` for a zero-setup local run."""

    def __init__(self, customers: dict[str, CustomerSignals] | None = None) -> None:
        self._customers = {email.lower(): s for email, s in (customers or {}).items()}
        self._seen: set[str] = set()
        self.interactions: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def is_duplicate(self, message_id: str) -> bool:
        if message_id in self._seen:
            return True
        self._seen.add(message_id)
        return False

    def get_customer_signals(self, email: str) -> CustomerSignals | None:
        return self._customers.get(email.lower())

    def save_interaction(
        self,
        message: InboundMessage,
        classification: Classification,
        routing: RoutingDecision,
        customer_id: str | None,
    ) -> None:
        self.interactions.append(
            {
                "message_id": message.message_id,
                "customer_id": customer_id,
                "request_type": classification.request_type.value,
                "sentiment": classification.sentiment.value,
                "confidence": classification.confidence,
                "outcome": routing.outcome.value,
                "response_mode": routing.response_mode.value,
                "health": routing.health.value,
            }
        )

    def log_event(self, message_id: str, event: str, details: dict[str, Any]) -> None:
        self.events.append({"message_id": message_id, "event": event, "details": details})


class PostgresRepository:
    """Thin psycopg wrapper. SQL lives in ``sql/schema.sql``."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def is_duplicate(self, message_id: str) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM customer_interactions WHERE message_id = %s",
                (message_id,),
            ).fetchone()
        return row is not None

    def get_customer_signals(self, email: str) -> CustomerSignals | None:
        query = """
            SELECT
                c.customer_id,
                c.adoption_score,
                c.health_status,
                c.health_declining,
                c.days_to_renewal,
                COALESCE(
                    (SELECT count(*) FROM customer_interactions ci
                     WHERE ci.customer_id = c.customer_id
                       AND ci.resolved = false),
                    0
                ) AS unresolved_interactions
            FROM customers c
            WHERE lower(c.contact_email) = lower(%s)
            LIMIT 1
        """
        with self._pool.connection() as conn:
            row = conn.execute(query, (email,)).fetchone()

        if row is None:
            return None

        return CustomerSignals(
            customer_id=str(row[0]),
            adoption_score=int(row[1]),
            current_health=row[2],
            health_declining=bool(row[3]),
            days_to_renewal=row[4],
            unresolved_interactions=int(row[5]),
        )

    def save_interaction(
        self,
        message: InboundMessage,
        classification: Classification,
        routing: RoutingDecision,
        customer_id: str | None,
    ) -> None:
        # The UNIQUE constraint on message_id is the last line of defence against
        # two identical messages arriving at the same moment.
        query = """
            INSERT INTO customer_interactions (
                message_id, customer_id, request_type, sentiment, confidence,
                summary, routing_outcome, response_mode, health_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
        """
        with self._pool.connection() as conn:
            conn.execute(
                query,
                (
                    message.message_id,
                    customer_id,
                    classification.request_type.value,
                    classification.sentiment.value,
                    classification.confidence,
                    classification.summary,
                    routing.outcome.value,
                    routing.response_mode.value,
                    routing.health.value,
                ),
            )

    def log_event(self, message_id: str, event: str, details: dict[str, Any]) -> None:
        query = """
            INSERT INTO automation_logs (message_id, event, details)
            VALUES (%s, %s, %s::jsonb)
        """
        with self._pool.connection() as conn:
            conn.execute(query, (message_id, event, json.dumps(details)))

    def close(self) -> None:
        self._pool.close()
