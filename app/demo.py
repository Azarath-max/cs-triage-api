"""Demo customers for ``REPOSITORY=memory``.

Mirrors ``sql/seed.sql`` so the zero-setup local run can exercise every routing
path. Tests build their own repository and never use this data.
"""

from __future__ import annotations

from app.schemas import CustomerSignals, HealthStatus

DEMO_CUSTOMERS: dict[str, CustomerSignals] = {
    # Healthy and far from renewal: high-confidence messages may auto-send.
    "ada@example.com": CustomerSignals(
        customer_id="demo-ada",
        adoption_score=82,
        current_health=HealthStatus.HEALTHY,
        days_to_renewal=240,
    ),
    # Low adoption and near renewal: the rules raise this to at_risk.
    "grace@example.com": CustomerSignals(
        customer_id="demo-grace",
        adoption_score=34,
        current_health=HealthStatus.WATCH,
        health_declining=True,
        days_to_renewal=60,
    ),
    # Already at risk in storage: rules may raise it but must not lower it.
    "alan@example.com": CustomerSignals(
        customer_id="demo-alan",
        adoption_score=61,
        current_health=HealthStatus.AT_RISK,
        health_declining=True,
        days_to_renewal=45,
    ),
}
