-- Authoritative Hollawall project and commercial-document store.
-- Google Sheets and financial_ledger remain the cash authority/projection.

CREATE TABLE IF NOT EXISTS project_issuer_profiles (
    issuer_key TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL CHECK (LENGTH(TRIM(legal_name)) > 0),
    display_name TEXT NOT NULL CHECK (LENGTH(TRIM(display_name)) > 0),
    number_code TEXT NOT NULL CHECK (number_code ~ '^[A-Z0-9]{2,8}$'),
    address TEXT NOT NULL CHECK (LENGTH(TRIM(address)) > 0),
    phone TEXT,
    email TEXT,
    tax_identity TEXT,
    bank_details JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(bank_details) = 'object'),
    logo_path TEXT,
    profile_version INTEGER NOT NULL DEFAULT 1 CHECK (profile_version > 0),
    created_by JSONB NOT NULL CHECK (jsonb_typeof(created_by) = 'object'),
    updated_by JSONB NOT NULL CHECK (jsonb_typeof(updated_by) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (LENGTH(TRIM(name)) BETWEEN 1 AND 200),
    client_name TEXT NOT NULL CHECK (LENGTH(TRIM(client_name)) BETWEEN 1 AND 200),
    client_company TEXT,
    client_address TEXT,
    client_contact TEXT,
    issuer_key TEXT NOT NULL REFERENCES project_issuer_profiles(issuer_key),
    wallet TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'active', 'completed', 'cancelled')),
    start_date DATE,
    completion_date DATE,
    contract_notes TEXT,
    lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version > 0),
    created_by JSONB NOT NULL CHECK (jsonb_typeof(created_by) = 'object'),
    updated_by JSONB NOT NULL CHECK (jsonb_typeof(updated_by) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (completion_date IS NULL OR start_date IS NULL OR completion_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_projects_status_updated ON projects(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_issuer ON projects(issuer_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_legacy_identity ON projects(wallet, company, name);

CREATE TABLE IF NOT EXISTS project_scopes (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    description TEXT NOT NULL CHECK (LENGTH(TRIM(description)) > 0),
    quantity NUMERIC(18,4),
    unit TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, position)
);

CREATE TABLE IF NOT EXISTS project_documents (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    issuer_key TEXT NOT NULL REFERENCES project_issuer_profiles(issuer_key),
    document_type TEXT NOT NULL
        CHECK (document_type IN ('sales_order', 'invoice', 'receipt')),
    invoice_kind TEXT CHECK (
        (document_type = 'invoice' AND invoice_kind IN ('DP', 'PROGRESS', 'FINAL')) OR
        (document_type <> 'invoice' AND invoice_kind IS NULL)
    ),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'issued', 'void', 'superseded')),
    official_number TEXT UNIQUE,
    issue_date DATE,
    due_date DATE,
    valid_until DATE,
    document_discount_amount BIGINT NOT NULL DEFAULT 0 CHECK (document_discount_amount >= 0),
    document_discount_percent NUMERIC(7,4) NOT NULL DEFAULT 0
        CHECK (document_discount_percent >= 0 AND document_discount_percent <= 100),
    tax_percent NUMERIC(7,4) NOT NULL DEFAULT 0 CHECK (tax_percent >= 0 AND tax_percent <= 100),
    notes TEXT,
    payment_terms TEXT,
    immutable_snapshot JSONB,
    snapshot_sha256 TEXT CHECK (snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    renderer_version TEXT,
    revision_of_id UUID REFERENCES project_documents(id),
    superseded_by_id UUID REFERENCES project_documents(id),
    void_reason TEXT,
    lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version > 0),
    issued_at TIMESTAMPTZ,
    voided_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_by JSONB NOT NULL CHECK (jsonb_typeof(created_by) = 'object'),
    updated_by JSONB NOT NULL CHECK (jsonb_typeof(updated_by) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (document_discount_amount = 0 OR document_discount_percent = 0),
    CHECK (
        (status = 'draft' AND official_number IS NULL AND immutable_snapshot IS NULL AND issued_at IS NULL) OR
        (status <> 'draft' AND official_number IS NOT NULL AND immutable_snapshot IS NOT NULL AND issued_at IS NOT NULL)
    ),
    CHECK (status <> 'void' OR (void_reason IS NOT NULL AND LENGTH(TRIM(void_reason)) > 0)),
    CHECK (status <> 'superseded' OR superseded_by_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_project_documents_project ON project_documents(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_project_documents_status ON project_documents(status, document_type);
CREATE INDEX IF NOT EXISTS idx_project_documents_revision ON project_documents(revision_of_id) WHERE revision_of_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_live_final_invoice
    ON project_documents(project_id)
    WHERE document_type = 'invoice' AND invoice_kind = 'FINAL' AND status IN ('draft', 'issued', 'superseded');

CREATE TABLE IF NOT EXISTS project_document_lines (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES project_documents(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    description TEXT NOT NULL CHECK (LENGTH(TRIM(description)) > 0),
    quantity NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
    unit TEXT NOT NULL CHECK (LENGTH(TRIM(unit)) > 0),
    unit_price BIGINT NOT NULL CHECK (unit_price >= 0),
    line_discount_percent NUMERIC(7,4) NOT NULL DEFAULT 0
        CHECK (line_discount_percent >= 0 AND line_discount_percent <= 100),
    line_gross BIGINT NOT NULL CHECK (line_gross >= 0),
    line_discount BIGINT NOT NULL CHECK (line_discount >= 0),
    line_total BIGINT NOT NULL CHECK (line_total >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, position),
    CHECK (line_total = line_gross - line_discount)
);

CREATE TABLE IF NOT EXISTS project_document_allocations (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES project_documents(id) ON DELETE CASCADE,
    ledger_source_key TEXT NOT NULL,
    amount BIGINT NOT NULL CHECK (amount > 0),
    ledger_amount BIGINT NOT NULL CHECK (ledger_amount > 0),
    ledger_snapshot JSONB NOT NULL CHECK (jsonb_typeof(ledger_snapshot) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, ledger_source_key)
);

CREATE INDEX IF NOT EXISTS idx_project_document_allocations_source
    ON project_document_allocations(ledger_source_key);

CREATE TABLE IF NOT EXISTS project_document_number_counters (
    issuer_key TEXT NOT NULL REFERENCES project_issuer_profiles(issuer_key),
    document_type TEXT NOT NULL CHECK (document_type IN ('sales_order', 'invoice', 'receipt')),
    calendar_year INTEGER NOT NULL CHECK (calendar_year BETWEEN 2000 AND 9999),
    last_value BIGINT NOT NULL CHECK (last_value > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(issuer_key, document_type, calendar_year)
);

CREATE TABLE IF NOT EXISTS project_document_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    document_id UUID REFERENCES project_documents(id),
    event_type TEXT NOT NULL CHECK (LENGTH(TRIM(event_type)) > 0),
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(event_data) = 'object'),
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_document_events_project_replay
    ON project_document_events(project_id, id);
CREATE INDEX IF NOT EXISTS idx_project_document_events_document_replay
    ON project_document_events(document_id, id) WHERE document_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS project_document_artifacts (
    document_id UUID PRIMARY KEY REFERENCES project_documents(id),
    mime_type TEXT NOT NULL DEFAULT 'application/pdf' CHECK (mime_type = 'application/pdf'),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 10485760),
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    renderer_version TEXT NOT NULL CHECK (LENGTH(TRIM(renderer_version)) > 0),
    pdf_bytes BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (octet_length(pdf_bytes) = byte_size)
);

CREATE TABLE IF NOT EXISTS project_document_commands (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idempotency_key_hash TEXT NOT NULL UNIQUE CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    command_type TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE OR REPLACE FUNCTION prevent_project_document_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status <> 'draft' THEN
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.project_id IS DISTINCT FROM OLD.project_id
           OR NEW.issuer_key IS DISTINCT FROM OLD.issuer_key
           OR NEW.document_type IS DISTINCT FROM OLD.document_type
           OR NEW.invoice_kind IS DISTINCT FROM OLD.invoice_kind
           OR NEW.official_number IS DISTINCT FROM OLD.official_number
           OR NEW.issue_date IS DISTINCT FROM OLD.issue_date
           OR NEW.due_date IS DISTINCT FROM OLD.due_date
           OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
           OR NEW.document_discount_amount IS DISTINCT FROM OLD.document_discount_amount
           OR NEW.document_discount_percent IS DISTINCT FROM OLD.document_discount_percent
           OR NEW.tax_percent IS DISTINCT FROM OLD.tax_percent
           OR NEW.notes IS DISTINCT FROM OLD.notes
           OR NEW.payment_terms IS DISTINCT FROM OLD.payment_terms
           OR NEW.immutable_snapshot IS DISTINCT FROM OLD.immutable_snapshot
           OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256
           OR NEW.renderer_version IS DISTINCT FROM OLD.renderer_version
           OR NEW.revision_of_id IS DISTINCT FROM OLD.revision_of_id
           OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
           OR NEW.created_by IS DISTINCT FROM OLD.created_by
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'issued project document content is immutable';
        END IF;
        IF NOT (
            NEW.status = OLD.status OR
            (OLD.status = 'issued' AND NEW.status IN ('void', 'superseded'))
        ) THEN
            RAISE EXCEPTION 'invalid project document transition % to %', OLD.status, NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_document_immutable ON project_documents;
CREATE TRIGGER trg_project_document_immutable
BEFORE UPDATE ON project_documents
FOR EACH ROW EXECUTE FUNCTION prevent_project_document_mutation();

CREATE OR REPLACE FUNCTION prevent_non_draft_document_child_mutation() RETURNS TRIGGER AS $$
DECLARE
    owner_id UUID;
    owner_status TEXT;
BEGIN
    owner_id := COALESCE(NEW.document_id, OLD.document_id);
    SELECT status INTO owner_status FROM project_documents WHERE id = owner_id FOR UPDATE;
    IF owner_status <> 'draft' THEN
        RAISE EXCEPTION 'issued project document children are immutable';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_document_lines_draft_only ON project_document_lines;
CREATE TRIGGER trg_project_document_lines_draft_only
BEFORE INSERT OR UPDATE OR DELETE ON project_document_lines
FOR EACH ROW EXECUTE FUNCTION prevent_non_draft_document_child_mutation();

DROP TRIGGER IF EXISTS trg_project_document_allocations_draft_only ON project_document_allocations;
CREATE TRIGGER trg_project_document_allocations_draft_only
BEFORE INSERT OR UPDATE OR DELETE ON project_document_allocations
FOR EACH ROW EXECUTE FUNCTION prevent_non_draft_document_child_mutation();

CREATE OR REPLACE FUNCTION prevent_project_document_event_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'project document events are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_document_events_append_only ON project_document_events;
CREATE TRIGGER trg_project_document_events_append_only
BEFORE UPDATE OR DELETE ON project_document_events
FOR EACH ROW EXECUTE FUNCTION prevent_project_document_event_mutation();

CREATE OR REPLACE FUNCTION prevent_project_document_artifact_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'project document artifacts are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_document_artifacts_immutable ON project_document_artifacts;
CREATE TRIGGER trg_project_document_artifacts_immutable
BEFORE UPDATE OR DELETE ON project_document_artifacts
FOR EACH ROW EXECUTE FUNCTION prevent_project_document_artifact_mutation();

-- Allocation issue-time revalidation uses row locks against financial_ledger:
-- SELECT ... FROM financial_ledger WHERE source_key = $1 FOR UPDATE;
