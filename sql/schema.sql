-- Schema for the CS triage API.
-- Requires the pgvector extension for the knowledge base and recurring-question
-- detection. Run this once against an empty database:
--   psql "$DATABASE_URL" -f sql/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS customers (
    customer_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name     TEXT        NOT NULL,
    contact_name     TEXT        NOT NULL,
    contact_email    TEXT        NOT NULL UNIQUE,
    plan             TEXT        NOT NULL DEFAULT 'standard',
    adoption_score   SMALLINT    NOT NULL DEFAULT 50
                     CHECK (adoption_score BETWEEN 0 AND 100),
    health_status    TEXT        NOT NULL DEFAULT 'healthy'
                     CHECK (health_status IN ('healthy', 'watch', 'at_risk', 'high_risk')),
    health_declining BOOLEAN     NOT NULL DEFAULT false,
    days_to_renewal  INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customer_interactions (
    interaction_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id       TEXT        NOT NULL UNIQUE,          -- duplicate protection
    customer_id      UUID        REFERENCES customers (customer_id) ON DELETE SET NULL,
    request_type     TEXT        NOT NULL,
    sentiment        TEXT        NOT NULL,
    confidence       DOUBLE PRECISION NOT NULL
                     CHECK (confidence BETWEEN 0 AND 1),
    summary          TEXT        NOT NULL DEFAULT '',
    routing_outcome  TEXT        NOT NULL,
    response_mode    TEXT        NOT NULL,
    health_status    TEXT        NOT NULL,
    resolved         BOOLEAN     NOT NULL DEFAULT false,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_interactions_customer
    ON customer_interactions (customer_id, created_at DESC);

-- Partial index: the "unresolved interactions" rule only ever reads these rows.
CREATE INDEX IF NOT EXISTS idx_interactions_unresolved
    ON customer_interactions (customer_id)
    WHERE resolved = false;

CREATE TABLE IF NOT EXISTS customer_health (
    health_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id    UUID NOT NULL REFERENCES customers (customer_id) ON DELETE CASCADE,
    health_status  TEXT NOT NULL
                   CHECK (health_status IN ('healthy', 'watch', 'at_risk', 'high_risk')),
    reason         TEXT NOT NULL DEFAULT '',
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS followup_tasks (
    task_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID REFERENCES customers (customer_id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    owner        TEXT,
    due_at       TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS escalations (
    escalation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID REFERENCES customers (customer_id) ON DELETE SET NULL,
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'acknowledged', 'closed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    document_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    category     TEXT NOT NULL,
    body         TEXT NOT NULL,
    embedding    vector(768),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit trail. Append-only by convention: insert, never update.
CREATE TABLE IF NOT EXISTS automation_logs (
    log_id     BIGSERIAL PRIMARY KEY,
    message_id TEXT,
    event      TEXT NOT NULL,
    details    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_logs_message ON automation_logs (message_id);
