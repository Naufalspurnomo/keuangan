CREATE TABLE IF NOT EXISTS project_transaction_evidence (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    ledger_source_key TEXT NOT NULL CHECK (LENGTH(TRIM(ledger_source_key)) BETWEEN 1 AND 512),
    mime_type TEXT NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 5242880),
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    original_name TEXT NOT NULL CHECK (LENGTH(TRIM(original_name)) BETWEEN 1 AND 255),
    image_bytes BYTEA NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    review_note TEXT,
    reviewed_by JSONB,
    reviewed_at TIMESTAMPTZ,
    created_by JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lock_version INTEGER NOT NULL DEFAULT 0 CHECK (lock_version >= 0),
    CHECK (octet_length(image_bytes) = byte_size),
    CHECK (
        (review_status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL)
        OR
        (review_status IN ('approved', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
    ),
    CONSTRAINT uq_project_transaction_evidence_content UNIQUE (project_id, ledger_source_key, sha256)
);

CREATE INDEX IF NOT EXISTS idx_project_transaction_evidence_source
    ON project_transaction_evidence(project_id, ledger_source_key, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS project_transaction_evidence_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evidence_id UUID NOT NULL REFERENCES project_transaction_evidence(id),
    event_type TEXT NOT NULL CHECK (event_type IN ('evidence.uploaded', 'evidence.reviewed')),
    actor JSONB NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_transaction_evidence_events_replay
    ON project_transaction_evidence_events(evidence_id, id);

CREATE OR REPLACE FUNCTION guard_project_transaction_evidence_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'project transaction evidence cannot be deleted';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.ledger_source_key IS DISTINCT FROM OLD.ledger_source_key
       OR NEW.mime_type IS DISTINCT FROM OLD.mime_type
       OR NEW.byte_size IS DISTINCT FROM OLD.byte_size
       OR NEW.sha256 IS DISTINCT FROM OLD.sha256
       OR NEW.original_name IS DISTINCT FROM OLD.original_name
       OR NEW.image_bytes IS DISTINCT FROM OLD.image_bytes
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'project transaction evidence bytes are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_transaction_evidence_guard ON project_transaction_evidence;
CREATE TRIGGER trg_project_transaction_evidence_guard
BEFORE UPDATE OR DELETE ON project_transaction_evidence
FOR EACH ROW EXECUTE FUNCTION guard_project_transaction_evidence_mutation();

CREATE OR REPLACE FUNCTION prevent_project_transaction_evidence_event_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'project transaction evidence events are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_transaction_evidence_events_append_only ON project_transaction_evidence_events;
CREATE TRIGGER trg_project_transaction_evidence_events_append_only
BEFORE UPDATE OR DELETE ON project_transaction_evidence_events
FOR EACH ROW EXECUTE FUNCTION prevent_project_transaction_evidence_event_mutation();
