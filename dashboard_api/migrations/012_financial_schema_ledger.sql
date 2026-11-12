-- Version/checksum ledger. This migration is intentionally last: a run is not
-- compatible until every canonical object exists and each checksum is recorded.

CREATE TABLE IF NOT EXISTS financial_schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    filename TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by TEXT NOT NULL DEFAULT current_user
);
