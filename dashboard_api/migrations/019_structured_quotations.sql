-- Structured, revision-safe quotations and atomic Deal-to-DP scheduling.
ALTER TABLE project_quotation_handoffs
    ALTER COLUMN canva_url DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS template_key TEXT,
    ADD COLUMN IF NOT EXISTS recipient_name TEXT,
    ADD COLUMN IF NOT EXISTS recipient_company TEXT,
    ADD COLUMN IF NOT EXISTS recipient_address TEXT,
    ADD COLUMN IF NOT EXISTS recipient_contact TEXT,
    ADD COLUMN IF NOT EXISTS project_name TEXT,
    ADD COLUMN IF NOT EXISTS subject TEXT,
    ADD COLUMN IF NOT EXISTS valid_until DATE,
    ADD COLUMN IF NOT EXISTS project_image_url TEXT,
    ADD COLUMN IF NOT EXISTS lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS discount_mode TEXT NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS discount_value NUMERIC(18,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tax_percent NUMERIC(7,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payment_terms TEXT,
    ADD COLUMN IF NOT EXISTS content_notes TEXT,
    ADD COLUMN IF NOT EXISTS accepted_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS revision_of_id UUID,
    ADD COLUMN IF NOT EXISTS dp_invoice_id UUID,
    ADD COLUMN IF NOT EXISTS installment_schedule JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_handoffs_revision_of_id_fkey'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT project_quotation_handoffs_revision_of_id_fkey
            FOREIGN KEY (revision_of_id) REFERENCES project_quotation_handoffs(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_handoffs_dp_invoice_id_fkey'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT project_quotation_handoffs_dp_invoice_id_fkey
            FOREIGN KEY (dp_invoice_id) REFERENCES project_documents(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_project_quotation_structured_json'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT chk_project_quotation_structured_json CHECK (
                jsonb_typeof(lines) = 'array'
                AND jsonb_typeof(installment_schedule) = 'array'
                AND (accepted_snapshot IS NULL OR jsonb_typeof(accepted_snapshot) = 'object')
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_project_quotation_discount'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT chk_project_quotation_discount CHECK (
                discount_mode IN ('none', 'fixed', 'percent')
                AND discount_value >= 0
                AND (discount_mode <> 'none' OR discount_value = 0)
                AND (discount_mode <> 'percent' OR discount_value <= 100)
                AND tax_percent >= 0 AND tax_percent <= 100
            );
    END IF;
    ALTER TABLE project_quotation_handoffs
        DROP CONSTRAINT IF EXISTS chk_project_quotation_deal_artifacts;
    ALTER TABLE project_quotation_handoffs
        ADD CONSTRAINT chk_project_quotation_deal_artifacts CHECK (
            (
                status = 'accepted'
                AND (
                    accepted_snapshot IS NOT NULL
                    OR (
                        canva_url IS NOT NULL
                        AND lines = '[]'::jsonb
                        AND dp_invoice_id IS NULL
                        AND installment_schedule = '[]'::jsonb
                    )
                )
            )
            OR (
                status <> 'accepted'
                AND accepted_snapshot IS NULL
                AND dp_invoice_id IS NULL
                AND installment_schedule = '[]'::jsonb
            )
        ) NOT VALID;
    IF EXISTS (
        SELECT 1
        FROM project_quotation_handoffs
        WHERE status = 'accepted'
          AND accepted_snapshot IS NULL
          AND NOT (canva_url IS NOT NULL AND lines = '[]'::jsonb)
    ) THEN
        RAISE EXCEPTION 'accepted quotation lacks immutable Deal snapshot';
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_quotation_dp_invoice
    ON project_quotation_handoffs(dp_invoice_id)
    WHERE dp_invoice_id IS NOT NULL;

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
    IF OLD.status IN ('rejected', 'revised') THEN
        RAISE EXCEPTION 'decided quotation is immutable';
    END IF;
    IF OLD.status = 'accepted' AND NOT (
        NEW.status = OLD.status
        AND OLD.sales_order_id IS NULL
        AND NEW.sales_order_id IS NOT NULL
        AND NEW.dp_invoice_id IS NOT DISTINCT FROM OLD.dp_invoice_id
        AND NEW.accepted_snapshot IS NOT DISTINCT FROM OLD.accepted_snapshot
        AND NEW.installment_schedule IS NOT DISTINCT FROM OLD.installment_schedule
    ) THEN
        RAISE EXCEPTION 'accepted quotation is immutable';
    END IF;
    IF OLD.status = 'sent' AND (
        NEW.canva_url IS DISTINCT FROM OLD.canva_url
        OR NEW.amount IS DISTINCT FROM OLD.amount
        OR NEW.template_key IS DISTINCT FROM OLD.template_key
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
