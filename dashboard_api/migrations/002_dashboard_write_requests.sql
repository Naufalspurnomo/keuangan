-- Additive durable coordination store for validated dashboard write requests.
-- This migration does not modify or write the authoritative financial ledger.

CREATE TABLE IF NOT EXISTS dashboard_write_requests (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key_hash TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    canonical_request JSONB NOT NULL,
    actor JSONB NOT NULL,
    message_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'claimed'
        CHECK (status IN ('claimed', 'completed', 'failed')),
    completion_response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Repair an earlier additive draft that may have omitted this nullable runtime column.
ALTER TABLE dashboard_write_requests
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_dashboard_write_requests_status_created
    ON dashboard_write_requests (status, created_at);
