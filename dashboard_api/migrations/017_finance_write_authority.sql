-- Durable identity mapping and fail-closed quarantine for finance authority cutover.

CREATE TABLE IF NOT EXISTS canonical_project_identity_mappings (
    normalized_label TEXT PRIMARY KEY CHECK (
        normalized_label = lower(trim(normalized_label))
        AND length(normalized_label) BETWEEN 1 AND 200
    ),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    owner_approved BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    approval_evidence JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(approval_evidence) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_project_identity_active_project
    ON canonical_project_identity_mappings(project_id) WHERE active AND owner_approved;

CREATE TABLE IF NOT EXISTS financial_command_quarantine (
    id UUID PRIMARY KEY,
    command_sha256 TEXT NOT NULL UNIQUE CHECK (command_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key_hash TEXT CHECK (
        idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'unknown_wallet', 'unmapped_project', 'unsupported_command',
        'same_wallet_debt', 'missing_idempotency', 'missing_actor',
        'missing_timestamp', 'invalid_command'
    )),
    command JSONB NOT NULL CHECK (jsonb_typeof(command) = 'object'),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'rejected')),
    resolution JSONB CHECK (resolution IS NULL OR jsonb_typeof(resolution) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    CHECK ((status = 'open') = (resolved_at IS NULL)),
    CHECK ((status = 'open') = (resolution IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_financial_command_quarantine_open
    ON financial_command_quarantine(created_at, id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_financial_command_quarantine_idempotency
    ON financial_command_quarantine(idempotency_key_hash)
    WHERE idempotency_key_hash IS NOT NULL;
