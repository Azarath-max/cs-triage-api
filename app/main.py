from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status

from app.classifier import Classifier, build_classifier
from app.config import Settings, get_settings
from app.db import build_repository
from app.repository import Repository
from app.rules import Thresholds
from app.schemas import InboundMessage, TriageResult
from app.service import triage


def _close(resource: Any) -> None:
    closer = getattr(resource, "close", None)
    if callable(closer):
        closer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.classifier = build_classifier(settings)
    app.state.repository = build_repository(settings)
    try:
        yield
    finally:
        _close(app.state.classifier)
        _close(app.state.repository)


app = FastAPI(
    title="CS Triage API",
    summary="Validate, classify, re-validate, then route customer messages with plain rules.",
    version="0.1.0",
    lifespan=lifespan,
)


def get_classifier(request: Request) -> Classifier:
    return request.app.state.classifier


def get_repository(request: Request) -> Repository:
    return request.app.state.repository


def get_thresholds(request: Request) -> Thresholds:
    settings: Settings = request.app.state.settings
    return Thresholds(settings.min_confidence, settings.auto_send_confidence)


def verify_webhook_secret(request: Request) -> None:
    """Optional shared-secret check on intake.

    Off when ``WEBHOOK_SECRET`` is empty, which keeps local development simple.
    On when it is set, which is what a public deployment needs.
    """
    settings: Settings = request.app.state.settings
    if not settings.webhook_secret:
        return

    provided = request.headers.get("x-webhook-secret", "")
    if not secrets.compare_digest(provided, settings.webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook secret",
        )


@app.get("/health", tags=["ops"])
def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "llm": "gemini" if settings.llm_enabled else "deterministic-stub",
        "repository": settings.repository,
    }


@app.post(
    "/v1/messages",
    response_model=TriageResult,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["triage"],
    dependencies=[Depends(verify_webhook_secret)],
)
def ingest_message(
    message: InboundMessage,
    classifier: Classifier = Depends(get_classifier),
    repository: Repository = Depends(get_repository),
    thresholds: Thresholds = Depends(get_thresholds),
) -> TriageResult:
    # Deliberately a sync def: the classifier and repository do blocking I/O, so
    # FastAPI runs this in its threadpool instead of stalling the event loop.
    return triage(
        message,
        classifier=classifier,
        repository=repository,
        thresholds=thresholds,
    )
