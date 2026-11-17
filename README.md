# CS Triage API

**Live:** <https://cs-triage-api.onrender.com/docs> · **Health:** <https://cs-triage-api.onrender.com/health>

A customer support triage API built around one rule: **the model classifies, plain code decides.**

An inbound message is validated, classified by an LLM against a schema, re-validated in code, scored against deterministic account-health rules, and routed to a queue with an explicit response mode. Risky or uncertain cases are held for a human before anything is sent.

This is the backend rewrite of an n8n workflow I built earlier. The workflow proved the design; this repository is the same design with the parts that matter moved into code I can test, type-check, and deploy.

**Stack:** Python 3.11+ · FastAPI · Pydantic v2 · PostgreSQL + pgvector · Gemini · pytest · Docker · GitHub Actions

---

## Why this exists

My earlier automation projects lived inside n8n. That was a good way to learn the pipeline shape, but it has a ceiling: the routing logic is configuration, not code, so it cannot be unit-tested, reviewed in a pull request, or reasoned about without opening a visual editor.

This version keeps the pipeline and moves the decisions into a testable core:

| Concern | Where it lives now |
| --- | --- |
| Input validation | `app/schemas.py` (Pydantic) |
| LLM output validation | `app/validation.py` (pure functions) |
| Health and routing rules | `app/rules.py` (pure functions, no I/O) |
| Model call | `app/classifier.py` (behind a `Protocol`) |
| Persistence | `app/repository.py` (behind a `Protocol`) |
| Orchestration | `app/service.py` |
| HTTP | `app/main.py` |

The two `Protocol`s are the reason the whole test suite runs with no database, no Docker, and no API key.

## Architecture

```
POST /v1/messages
  │
  ├─ Pydantic validation ──────────────► 422, nothing persisted
  │     (email, message_id charset, length caps)
  │
  ├─ duplicate check ──────────────────► 202 accepted: false, no model call
  │
  ├─ classifier.classify()
  │     ├─ Gemini (schema-constrained) ─► parse_classification()
  │     └─ on failure ─────────────────► fallback: confidence 0
  │
  ├─ customer lookup ──────────────────► unknown sender: human review, no reply
  │
  ├─ assess_health()   (pure) ─────────► may only raise risk
  │
  ├─ decide_routing()  (pure) ─────────► queue + response mode
  │
  └─ save_interaction() + log_event() ─► audit trail
```

## The decisions worth reviewing

**The model's output is treated as untrusted input.** It is derived from text a customer controls, so it gets the same treatment as a form field. `parse_classification` checks required keys, rejects unknown enum values rather than guessing, clamps confidence to `0..1`, and drops anything it does not recognise. A wrong enum is an error, not a nearest match.

**A failed classification cannot be auto-sent.** `fallback_classification` returns confidence `0.0`, which the routing rules convert to `human_review` with response mode `none`. The failure mode is "a person reads it," never "a guess reached a customer."

**The prompt frames message text as data.** The system prompt says the message is data to analyse, never instructions. That reduces prompt injection, but it is not the actual defence — the actual defence is that model output can only ever become a validated `Classification`, and routing is decided by code that never reads the raw message.

**Health can only go up automatically.** Rules may raise a customer's risk level; lowering it requires a human. If the stored status is already higher than what the rules compute, the stored status wins and the reason is recorded.

**Routing priority is explicit and ordered.** `escalate > csm_review > billing > human_review > commercial > adoption > standard`. First match wins, so the order is written out rather than implied by nesting.

**Billing never involves an AI decision.** It gets a fixed template and a specialist queue, regardless of confidence.

**Two thresholds, not one.** `MIN_CONFIDENCE` (default `0.70`) decides whether the message is triaged at all; `AUTO_SEND_CONFIDENCE` (default `0.80`) decides whether a reply can go without approval. Between the two, the message is triaged but held for review.

**Duplicate protection exists in two places.** The service checks before calling the model, and the `message_id` column is `UNIQUE` so two simultaneous arrivals cannot both be stored.

**The audit log is append-only.** `automation_logs` is inserted into, never updated. Each row carries the outcome, the response mode, the confidence, and the reasons that fired.

## Running it

### Without Docker or a database

The default repository is in-memory and the default classifier is a keyword stub, so this works immediately:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open <http://localhost:8000/docs> for the generated OpenAPI UI.

In memory mode three demo customers are preloaded (mirroring `sql/seed.sql`), so routing works immediately:

| Email | What it demonstrates |
| --- | --- |
| `ada@example.com` | healthy account, auto-send allowed at high confidence |
| `grace@example.com` | adoption 34 with renewal in 60 days, rules raise it to `at_risk` |
| `alan@example.com` | stored `at_risk`, rules must not lower it |

```bash
curl -s http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "msg-001",
    "customer_email": "grace@example.com",
    "subject": "We are not seeing results",
    "body": "This is frustrating and we are considering cancelling before renewal."
  }'
```

Any other address is treated as an unknown sender: it is stored and routed to human review with no automatic reply.

### With Postgres and pgvector

```bash
docker compose up --build
```

Compose starts `pgvector/pgvector:pg16`, applies `sql/schema.sql` and `sql/seed.sql` on first boot, and runs the API with `REPOSITORY=postgres`. The seed loads the same three demo customers as memory mode. Set `GEMINI_API_KEY` in `.env` to use the real model instead of the stub.

### Tests

```bash
pytest
ruff check .
```

No network, no database, no API key. The suite covers validation edge cases, every health rule, every routing branch, the Gemini request/response handling via `httpx.MockTransport`, and the HTTP layer end to end.

## Deploying it

The image is self-contained and reads the `PORT` environment variable, so it runs on any Docker host. The repository ships a `render.yaml` blueprint for Render's free tier.

### Render

1. In the Render Dashboard, choose **New → Blueprint** and select this repository.
2. Click **Apply**. Render builds the Dockerfile and serves it at `https://<service-name>.onrender.com`.

`render.yaml` sets one variable, `REPOSITORY=memory`. There is no API key and no webhook secret, so the deployment runs the deterministic classifier against the three in-memory demo customers and `/docs` works for anyone who visits. That is deliberate: a demo nobody can call is not a demo.

Free-plan behaviour worth knowing:

- The service spins down after 15 minutes with no traffic and takes about a minute to wake up. The first visitor after a quiet period waits.
- 750 instance hours per month, 0.1 CPU / 512 MB RAM.
- The filesystem is ephemeral, so in-memory state resets on every restart.

To use the real model, add `GEMINI_API_KEY` under the service's Environment tab. If you also set `WEBHOOK_SECRET`, every request needs an `X-Webhook-Secret` header, which breaks "Try it out" in `/docs` — leave it empty for a public demo and set it only when the endpoint is called by another service you control.

### Any other Docker host

```bash
docker build -t cs-triage-api .
docker run -p 8000:8000 cs-triage-api
```

Override the listening port the way a platform would:

```bash
docker run -p 10000:10000 -e PORT=10000 cs-triage-api
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `REPOSITORY` | `memory` | `memory` or `postgres`. No silent fallback. |
| `DATABASE_URL` | local Postgres | Only used when `REPOSITORY=postgres`. |
| `GEMINI_API_KEY` | empty | Empty means deterministic stub mode. |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model name. |
| `WEBHOOK_SECRET` | empty | When set, `/v1/messages` requires `X-Webhook-Secret`. |
| `MIN_CONFIDENCE` | `0.70` | Below this, human review. |
| `AUTO_SEND_CONFIDENCE` | `0.80` | At or above this, auto-send is allowed. |
| `TEST_RECIPIENT` | empty | Redirects outgoing mail during testing. |

## Limitations

Being explicit about what this is not:

- **The keyword stub is not a classifier.** It exists so the API runs without a key. Real use requires `GEMINI_API_KEY`.
- **Thresholds are untuned.** `0.70` and `0.80` are starting values, not values validated on traffic. There are no accuracy metrics yet.
- **No email sending in this repository.** The API decides a response mode; delivery is deliberately out of scope so nothing can be sent accidentally during development.
- **No authentication beyond the shared secret.** Suitable for a demo; not a multi-tenant auth system.
- **The in-memory repository loses data on restart.** That is intentional for local runs.
- **`customer_interactions.resolved` is never set by this API.** Marking an interaction resolved is a human action, so the "unresolved interactions" rule counts rows a human has not closed.

## Next steps

- An evaluation set: fixed messages with expected classifications, run in CI to catch prompt or model regressions.
- Response drafting with a content guard that blocks money and commitment language.
- Slack approval flow with a 24-hour timeout.
- A read-only dashboard over `automation_logs`.
- Threaded replies instead of new emails.

## Repository layout

```
app/
  main.py          FastAPI app, dependencies, auth
  service.py       orchestration
  rules.py         health + routing rules (pure)
  validation.py    LLM output validation (pure)
  classifier.py    Gemini + deterministic stub
  repository.py    Postgres + in-memory
  schemas.py       domain types
  config.py        settings
  db.py            pool + repository factory
sql/schema.sql     tables, constraints, indexes
tests/             pytest suite
```
