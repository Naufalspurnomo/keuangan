-- Immutable sent-quotation numbering and PDF artifacts.

ALTER TABLE project_quotation_handoffs
    ADD COLUMN IF NOT EXISTS official_number TEXT,
    ADD COLUMN IF NOT EXISTS issued_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_quotation_official_number
    ON project_quotation_handoffs(official_number)
    WHERE official_number IS NOT NULL;

CREATE TABLE IF NOT EXISTS project_quotation_number_counters (
    template_key TEXT NOT NULL,
    calendar_year INTEGER NOT NULL,
    last_value BIGINT NOT NULL CHECK (last_value > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (template_key, calendar_year)
);

CREATE TABLE IF NOT EXISTS project_quotation_artifacts (
    quotation_id UUID PRIMARY KEY REFERENCES project_quotation_handoffs(id),
    mime_type TEXT NOT NULL DEFAULT 'application/pdf' CHECK (mime_type = 'application/pdf'),
    byte_size BIGINT NOT NULL CHECK (byte_size > 0),
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    pdf_bytes BYTEA NOT NULL,
    immutable_snapshot JSONB NOT NULL CHECK (jsonb_typeof(immutable_snapshot) = 'object'),
    snapshot_sha256 TEXT NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    template_key TEXT NOT NULL,
    template_version TEXT NOT NULL,
    renderer_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (octet_length(pdf_bytes) = byte_size)
);

CREATE OR REPLACE FUNCTION reject_project_quotation_artifact_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'quotation artifacts are immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_project_quotation_artifacts_immutable ON project_quotation_artifacts;
CREATE TRIGGER trg_project_quotation_artifacts_immutable
BEFORE UPDATE OR DELETE ON project_quotation_artifacts
FOR EACH ROW EXECUTE FUNCTION reject_project_quotation_artifact_mutation();

CREATE OR REPLACE FUNCTION guard_project_quotation_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id OR NEW.version <> OLD.version
       OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at
       OR NEW.revision_of_id IS DISTINCT FROM OLD.revision_of_id THEN
        RAISE EXCEPTION 'quotation identity is immutable; create a revision';
    END IF;
    IF OLD.status = 'draft' AND NEW.status NOT IN ('draft', 'sent', 'revised') THEN
        RAISE EXCEPTION 'draft quotation transition is not allowed';
    ELSIF OLD.status = 'sent' AND NEW.status NOT IN ('sent', 'revised', 'rejected', 'accepted') THEN
        RAISE EXCEPTION 'sent quotation transition is not allowed';
    ELSIF OLD.status IN ('rejected', 'revised') THEN
        RAISE EXCEPTION 'decided quotation is immutable';
    ELSIF OLD.status = 'accepted' THEN
        RAISE EXCEPTION 'accepted quotation is immutable';
    END IF;
    IF OLD.status = 'sent' AND (
        NEW.sent_at IS DISTINCT FROM OLD.sent_at
        OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
        OR NEW.official_number IS DISTINCT FROM OLD.official_number
        OR NEW.canva_url IS DISTINCT FROM OLD.canva_url
        OR NEW.amount IS DISTINCT FROM OLD.amount
        OR NEW.template_key IS DISTINCT FROM OLD.template_key
        OR NEW.template_version IS DISTINCT FROM OLD.template_version
        OR NEW.payment_profile_key IS DISTINCT FROM OLD.payment_profile_key
        OR NEW.subject IS DISTINCT FROM OLD.subject
        OR NEW.recipient_name IS DISTINCT FROM OLD.recipient_name
        OR NEW.recipient_company IS DISTINCT FROM OLD.recipient_company
        OR NEW.recipient_address IS DISTINCT FROM OLD.recipient_address
        OR NEW.recipient_contact IS DISTINCT FROM OLD.recipient_contact
        OR NEW.project_name IS DISTINCT FROM OLD.project_name
        OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
        OR NEW.project_image_url IS DISTINCT FROM OLD.project_image_url
        OR NEW.lines IS DISTINCT FROM OLD.lines
        OR NEW.discount_mode IS DISTINCT FROM OLD.discount_mode
        OR NEW.discount_value IS DISTINCT FROM OLD.discount_value
        OR NEW.tax_percent IS DISTINCT FROM OLD.tax_percent
        OR NEW.payment_terms IS DISTINCT FROM OLD.payment_terms
        OR NEW.content_notes IS DISTINCT FROM OLD.content_notes
    ) THEN
        RAISE EXCEPTION 'sent quotation commercial terms are immutable; create a revision';
    END IF;
    IF OLD.status = 'sent' AND NEW.status = 'accepted' AND (
        OLD.lines = '[]'::jsonb OR OLD.project_image_url IS NULL
        OR NEW.accepted_snapshot IS NULL OR NEW.sales_order_id IS NULL
        OR NEW.dp_invoice_id IS NULL OR NEW.installment_schedule = '[]'::jsonb
    ) THEN
        RAISE EXCEPTION 'Deal requires structured immutable artifacts';
    END IF;
    IF NEW.lock_version <> OLD.lock_version + 1 THEN
        RAISE EXCEPTION 'quotation lock_version must increment by one';
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_project_quotation_transition ON project_quotation_handoffs;
CREATE TRIGGER trg_project_quotation_transition
BEFORE UPDATE ON project_quotation_handoffs
FOR EACH ROW EXECUTE FUNCTION guard_project_quotation_transition();
