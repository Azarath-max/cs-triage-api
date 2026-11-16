"""Database pool and repository factory.

``REPOSITORY=memory`` is the default so ``uvicorn app.main:app`` works with no
Postgres. Docker Compose sets ``REPOSITORY=postgres``. There is no silent
fallback: if you ask for Postgres and it is down, the app fails loudly.
"""

from __future__ import annotations

from app.config import Settings
from app.demo import DEMO_CUSTOMERS
from app.repository import InMemoryRepository, PostgresRepository, Repository


def create_pool(settings: Settings):
    from psycopg_pool import ConnectionPool

    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )


def build_repository(settings: Settings) -> Repository:
    if settings.repository == "postgres":
        return PostgresRepository(create_pool(settings))
    return InMemoryRepository(DEMO_CUSTOMERS)
