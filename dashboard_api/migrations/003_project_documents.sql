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

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_issuer_profiles_number_code
    ON project_issuer_profiles ((UPPER(TRIM(number_code))));

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (LENGTH(TRIM(name)) BETWEEN 1 AND 200),
    client_name TEXT NOT NULL CHECK (LENGTH(TRIM(client_name)) BETWEEN 1 AND 200),
    client_company TEXT,
    client_address TEXT,
    client_contact TEXT,
    issuer_key TEXT NOT NULL REFERENCES project_issuer_profiles(issuer_key),
    wallet TEXT NOT NULL CHECK (LENGTH(TRIM(wallet)) BETWEEN 1 AND 120),
    company TEXT NOT NULL CHECK (LENGTH(TRIM(company)) BETWEEN 1 AND 120),
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

-- Fail closed rather than preserving projects that can never issue receipts.
ALTER TABLE projects ALTER COLUMN wallet SET NOT NULL;
ALTER TABLE projects ALTER COLUMN company SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'projects_wallet_nonempty_check'
          AND conrelid = 'projects'::regclass
    ) THEN
        ALTER TABLE projects ADD CONSTRAINT projects_wallet_nonempty_check
            CHECK (LENGTH(TRIM(wallet)) BETWEEN 1 AND 120);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'projects_company_nonempty_check'
          AND conrelid = 'projects'::regclass
    ) THEN
        ALTER TABLE projects ADD CONSTRAINT projects_company_nonempty_check
            CHECK (LENGTH(TRIM(company)) BETWEEN 1 AND 120);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_projects_status_updated ON projects(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_issuer ON projects(issuer_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_legacy_identity ON projects(wallet, company, name);

CREATE TABLE IF NOT EXISTS project_scopes (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    position INTEGER NOT NULL CHECK (position > 0),
    description TEXT NOT NULL CHECK (LENGTH(TRIM(description)) > 0),
    quantity NUMERIC(18,4),
    unit TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, position)
);

-- Upgrade an earlier local application of this not-yet-deployed migration safely.
ALTER TABLE project_scopes DROP CONSTRAINT IF EXISTS project_scopes_project_id_fkey;
ALTER TABLE project_scopes ADD CONSTRAINT project_scopes_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id);

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
    prepared_by TEXT,
    client_signatory TEXT,
    project_image_url TEXT,
    immutable_snapshot JSONB,
    snapshot_sha256 TEXT CHECK (snapshot_sha256 IS NULL OR snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    renderer_version TEXT,
    revision_of_id UUID REFERENCES project_documents(id) DEFERRABLE INITIALLY DEFERRED,
    superseded_by_id UUID REFERENCES project_documents(id) DEFERRABLE INITIALLY DEFERRED,
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
        (status = 'draft' AND official_number IS NULL AND immutable_snapshot IS NULL
            AND snapshot_sha256 IS NULL AND renderer_version IS NULL AND issued_at IS NULL) OR
        (status <> 'draft' AND official_number IS NOT NULL AND immutable_snapshot IS NOT NULL
            AND snapshot_sha256 IS NOT NULL AND renderer_version IS NOT NULL AND issued_at IS NOT NULL)
    ),
    CHECK (status <> 'void' OR (void_reason IS NOT NULL AND LENGTH(TRIM(void_reason)) > 0 AND voided_at IS NOT NULL)),
    CHECK (status <> 'superseded' OR (superseded_by_id IS NOT NULL AND superseded_at IS NOT NULL))
);

-- Idempotently upgrade databases that applied an earlier pre-release 003.
ALTER TABLE project_documents ADD COLUMN IF NOT EXISTS prepared_by TEXT;
ALTER TABLE project_documents ADD COLUMN IF NOT EXISTS client_signatory TEXT;
ALTER TABLE project_documents ADD COLUMN IF NOT EXISTS project_image_url TEXT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_documents_project_image_url_check'
          AND conrelid = 'project_documents'::regclass
    ) THEN
        ALTER TABLE project_documents
            ADD CONSTRAINT project_documents_project_image_url_check CHECK (
                project_image_url IS NULL OR (
                    LENGTH(project_image_url) <= 196608 AND
                    project_image_url ~ '^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$'
                )
            );
    END IF;
END;
$$;

ALTER TABLE project_documents DROP CONSTRAINT IF EXISTS project_documents_revision_of_id_fkey;
ALTER TABLE project_documents ADD CONSTRAINT project_documents_revision_of_id_fkey
    FOREIGN KEY (revision_of_id) REFERENCES project_documents(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE project_documents DROP CONSTRAINT IF EXISTS project_documents_superseded_by_id_fkey;
ALTER TABLE project_documents ADD CONSTRAINT project_documents_superseded_by_id_fkey
    FOREIGN KEY (superseded_by_id) REFERENCES project_documents(id) DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX IF NOT EXISTS idx_project_documents_project ON project_documents(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_project_documents_status ON project_documents(status, document_type);
CREATE INDEX IF NOT EXISTS idx_project_documents_revision ON project_documents(revision_of_id) WHERE revision_of_id IS NOT NULL;
DROP INDEX IF EXISTS uq_project_live_final_invoice;
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_active_final_invoice
    ON project_documents(project_id)
    WHERE document_type = 'invoice' AND invoice_kind = 'FINAL'
      AND (status = 'issued' OR (status = 'draft' AND revision_of_id IS NULL));
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_active_sales_order
    ON project_documents(project_id)
    WHERE document_type = 'sales_order' AND status = 'issued';
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_pending_document_revision
    ON project_documents(revision_of_id)
    WHERE revision_of_id IS NOT NULL AND status = 'draft';

CREATE TABLE IF NOT EXISTS project_document_lines (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES project_documents(id),
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

ALTER TABLE project_document_lines DROP CONSTRAINT IF EXISTS project_document_lines_document_id_fkey;
ALTER TABLE project_document_lines ADD CONSTRAINT project_document_lines_document_id_fkey
    FOREIGN KEY (document_id) REFERENCES project_documents(id);

CREATE TABLE IF NOT EXISTS project_document_allocations (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES project_documents(id),
    ledger_source_key TEXT NOT NULL,
    amount BIGINT NOT NULL CHECK (amount > 0),
    ledger_amount BIGINT NOT NULL CHECK (ledger_amount > 0),
    ledger_snapshot JSONB NOT NULL CHECK (jsonb_typeof(ledger_snapshot) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, ledger_source_key)
);

ALTER TABLE project_document_allocations DROP CONSTRAINT IF EXISTS project_document_allocations_document_id_fkey;
ALTER TABLE project_document_allocations ADD CONSTRAINT project_document_allocations_document_id_fkey
    FOREIGN KEY (document_id) REFERENCES project_documents(id);

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

CREATE TABLE IF NOT EXISTS project_issuer_profile_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    issuer_key TEXT NOT NULL REFERENCES project_issuer_profiles(issuer_key),
    event_type TEXT NOT NULL CHECK (event_type IN ('issuer.created', 'issuer.updated')),
    profile_version INTEGER NOT NULL CHECK (profile_version > 0),
    event_data JSONB NOT NULL CHECK (jsonb_typeof(event_data) = 'object'),
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_issuer_profile_events_replay
    ON project_issuer_profile_events(issuer_key, id);

CREATE TABLE IF NOT EXISTS project_document_artifacts (
    document_id UUID PRIMARY KEY REFERENCES project_documents(id),
    mime_type TEXT NOT NULL DEFAULT 'application/pdf' CHECK (mime_type = 'application/pdf'),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 10485760),
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    renderer_version TEXT NOT NULL CHECK (LENGTH(TRIM(renderer_version)) > 0),
    pdf_bytes BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (octet_length(pdf_bytes) = byte_size),
    CONSTRAINT project_document_artifacts_pdf_signature_check
        CHECK (substring(pdf_bytes from 1 for 5) = convert_to('%PDF-', 'UTF8'))
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_document_artifacts_pdf_signature_check'
          AND conrelid = 'project_document_artifacts'::regclass
    ) THEN
        ALTER TABLE project_document_artifacts
            ADD CONSTRAINT project_document_artifacts_pdf_signature_check
            CHECK (substring(pdf_bytes from 1 for 5) = convert_to('%PDF-', 'UTF8'));
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS project_document_commands (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    idempotency_key_hash TEXT NOT NULL UNIQUE CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    command_type TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE OR REPLACE FUNCTION prevent_project_issuer_number_code_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.number_code IS DISTINCT FROM OLD.number_code THEN
        RAISE EXCEPTION 'issuer number_code is immutable after profile creation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_issuer_number_code_immutable ON project_issuer_profiles;
CREATE TRIGGER trg_project_issuer_number_code_immutable
BEFORE UPDATE OF number_code ON project_issuer_profiles
FOR EACH ROW EXECUTE FUNCTION prevent_project_issuer_number_code_mutation();

CREATE OR REPLACE FUNCTION prevent_project_delete() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'projects cannot be hard deleted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_projects_no_delete ON projects;
CREATE TRIGGER trg_projects_no_delete
BEFORE DELETE ON projects
FOR EACH ROW EXECUTE FUNCTION prevent_project_delete();

CREATE OR REPLACE FUNCTION prevent_project_document_delete() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'project documents cannot be hard deleted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_documents_no_delete ON project_documents;
CREATE TRIGGER trg_project_documents_no_delete
BEFORE DELETE ON project_documents
FOR EACH ROW EXECUTE FUNCTION prevent_project_document_delete();

CREATE OR REPLACE FUNCTION prevent_project_document_mutation() RETURNS TRIGGER AS $$
DECLARE
    old_stable JSONB;
    new_stable JSONB;
BEGIN
    IF OLD.status = 'draft' AND NEW.status = 'draft' THEN
        old_stable := to_jsonb(OLD) - ARRAY[
            'issue_date', 'due_date', 'valid_until', 'document_discount_amount',
            'document_discount_percent', 'tax_percent', 'notes', 'payment_terms',
            'prepared_by', 'client_signatory', 'project_image_url',
            'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        new_stable := to_jsonb(NEW) - ARRAY[
            'issue_date', 'due_date', 'valid_until', 'document_discount_amount',
            'document_discount_percent', 'tax_percent', 'notes', 'payment_terms',
            'prepared_by', 'client_signatory', 'project_image_url',
            'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        IF new_stable IS DISTINCT FROM old_stable THEN
            RAISE EXCEPTION 'invalid draft project document mutation';
        END IF;
    ELSIF OLD.status = 'draft' AND NEW.status = 'issued' THEN
        old_stable := to_jsonb(OLD) - ARRAY[
            'status', 'official_number', 'immutable_snapshot', 'snapshot_sha256',
            'renderer_version', 'issued_at', 'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        new_stable := to_jsonb(NEW) - ARRAY[
            'status', 'official_number', 'immutable_snapshot', 'snapshot_sha256',
            'renderer_version', 'issued_at', 'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        IF new_stable IS DISTINCT FROM old_stable THEN
            RAISE EXCEPTION 'invalid draft to issued mutation';
        END IF;
    ELSIF OLD.status = 'issued' AND NEW.status = 'void' THEN
        old_stable := to_jsonb(OLD) - ARRAY[
            'status', 'void_reason', 'voided_at', 'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        new_stable := to_jsonb(NEW) - ARRAY[
            'status', 'void_reason', 'voided_at', 'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        IF new_stable IS DISTINCT FROM old_stable THEN
            RAISE EXCEPTION 'invalid issued to void mutation';
        END IF;
    ELSIF OLD.status = 'issued' AND NEW.status = 'superseded' THEN
        old_stable := to_jsonb(OLD) - ARRAY[
            'status', 'superseded_by_id', 'superseded_at', 'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        new_stable := to_jsonb(NEW) - ARRAY[
            'status', 'superseded_by_id', 'superseded_at', 'lock_version', 'updated_by', 'updated_at'
        ]::TEXT[];
        IF new_stable IS DISTINCT FROM old_stable THEN
            RAISE EXCEPTION 'invalid issued to superseded mutation';
        END IF;
    ELSIF OLD.status IN ('void', 'superseded') THEN
        RAISE EXCEPTION 'terminal project document is immutable';
    ELSE
        RAISE EXCEPTION 'invalid project document transition % to %', OLD.status, NEW.status;
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
    IF TG_OP = 'UPDATE' AND NEW.document_id IS DISTINCT FROM OLD.document_id THEN
        RAISE EXCEPTION 'project document children cannot change owner';
    END IF;
    owner_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.document_id ELSE NEW.document_id END;
    SELECT status INTO owner_status FROM project_documents WHERE id = owner_id FOR UPDATE;
    IF owner_status IS NULL THEN
        RAISE EXCEPTION 'project document owner is missing';
    END IF;
    IF owner_status <> 'draft' THEN
        RAISE EXCEPTION 'issued project document children are immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
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

DROP TRIGGER IF EXISTS trg_project_issuer_profile_events_append_only ON project_issuer_profile_events;
CREATE TRIGGER trg_project_issuer_profile_events_append_only
BEFORE UPDATE OR DELETE ON project_issuer_profile_events
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
