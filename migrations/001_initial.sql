CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS repair_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id TEXT NOT NULL,
    source_field TEXT NOT NULL,
    target_field TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('rename', 'to_float', 'uppercase')),
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000,
    status TEXT NOT NULL DEFAULT 'approved'
        CHECK (status IN ('proposed', 'approved', 'rejected')),
    hit_count INTEGER NOT NULL DEFAULT 0 CHECK (hit_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    UNIQUE (partner_id, source_field, target_field, operation)
);

CREATE TABLE IF NOT EXISTS integration_incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id TEXT NOT NULL,
    order_id TEXT,
    raw_payload JSONB NOT NULL,
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    incident_type TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('detected', 'repaired', 'processed', 'escalated', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS repair_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES integration_incidents(id),
    repair_plan JSONB NOT NULL,
    before_payload JSONB NOT NULL,
    after_payload JSONB,
    validation_result JSONB,
    business_result JSONB,
    processing_result JSONB,
    outcome TEXT NOT NULL
        CHECK (outcome IN ('sandbox_failed', 'business_failed', 'processed', 'escalated')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_orders (
    idempotency_key TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    result JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS escalations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES integration_incidents(id),
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_repair_rules_lookup
    ON repair_rules (partner_id, source_field, status);

CREATE INDEX IF NOT EXISTS idx_incidents_partner_status
    ON integration_incidents (partner_id, status);
