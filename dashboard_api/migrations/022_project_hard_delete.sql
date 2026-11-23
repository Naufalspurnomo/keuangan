-- Owner-authorized project hard-delete gate. Immutable ledgers and commercial
-- documents remain protected unless a repository transaction names the exact
-- target project. Every bypass below proves OLD belongs to that project.

CREATE OR REPLACE FUNCTION hollawall_project_hard_delete_target() RETURNS UUID AS $$
DECLARE
    raw_target TEXT;
BEGIN
    raw_target := current_setting('hollawall.project_hard_delete_target', TRUE);
    IF raw_target IS NULL OR raw_target !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$' THEN
        RETURN NULL;
    END IF;
    RETURN raw_target::UUID;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION prevent_project_delete() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.id = hollawall_project_hard_delete_target() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'projects cannot be hard deleted';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION prevent_project_document_delete() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.project_id = hollawall_project_hard_delete_target() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'project documents cannot be hard deleted';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION reject_financial_immutable_mutation() RETURNS TRIGGER AS $$
DECLARE
    target UUID := hollawall_project_hard_delete_target();
    row_data JSONB := to_jsonb(OLD);
BEGIN
    IF TG_OP = 'DELETE' AND target IS NOT NULL THEN
        IF TG_TABLE_NAME = 'financial_transactions' THEN
            IF (row_data->>'project_id')::UUID = target THEN
                RETURN OLD;
            END IF;
        ELSIF TG_TABLE_NAME = 'financial_postings' THEN
            IF EXISTS (
                SELECT 1 FROM financial_transactions
                WHERE id = (row_data->>'transaction_id')::UUID AND project_id = target
            ) THEN
                RETURN OLD;
            END IF;
        ELSIF TG_TABLE_NAME = 'project_status_events' THEN
            IF (row_data->>'project_id')::UUID = target THEN
                RETURN OLD;
            END IF;
        END IF;
    END IF;
    RAISE EXCEPTION 'canonical financial records cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION reject_financial_history_mutation() RETURNS TRIGGER AS $$
DECLARE
    target UUID := hollawall_project_hard_delete_target();
    row_data JSONB := to_jsonb(OLD);
BEGIN
    IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'financial_migration_manifest' AND target IS NOT NULL THEN
        IF NULLIF(row_data->>'canonical_project_id', '')::UUID = target
           OR EXISTS (
                SELECT 1 FROM financial_transactions
                WHERE id = NULLIF(row_data->>'canonical_transaction_id', '')::UUID
                  AND project_id = target
           )
           OR EXISTS (
                SELECT 1 FROM interwallet_debts
                WHERE id = NULLIF(row_data->>'canonical_debt_id', '')::UUID
                  AND project_id = target
           ) THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION 'financial authority history cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION reject_interwallet_debt_event_mutation() RETURNS TRIGGER AS $$
DECLARE
    target UUID := hollawall_project_hard_delete_target();
BEGIN
    IF TG_OP = 'DELETE' AND target IS NOT NULL AND EXISTS (
        SELECT 1
        FROM interwallet_debt_events event
        LEFT JOIN interwallet_debts debt ON debt.id = event.debt_id
        LEFT JOIN financial_transactions tx ON tx.id = event.transaction_id
        WHERE event.id = OLD.id
          AND (debt.project_id = target OR tx.project_id = target)
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'interwallet debt events cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION reject_interwallet_debt_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.project_id = hollawall_project_hard_delete_target() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'interwallet debts cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION prevent_project_document_event_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.project_id = hollawall_project_hard_delete_target() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'project document events are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION prevent_project_document_artifact_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1 FROM project_documents
        WHERE id = OLD.document_id AND project_id = hollawall_project_hard_delete_target()
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'project document artifacts are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION reject_project_quotation_artifact_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1 FROM project_quotation_handoffs
        WHERE id = OLD.quotation_id AND project_id = hollawall_project_hard_delete_target()
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'quotation artifacts are immutable';
END;
$$;

CREATE OR REPLACE FUNCTION prevent_non_draft_document_child_mutation() RETURNS TRIGGER AS $$
DECLARE
    owner_id UUID;
    owner_status TEXT;
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1 FROM project_documents
        WHERE id = OLD.document_id AND project_id = hollawall_project_hard_delete_target()
    ) THEN
        RETURN OLD;
    END IF;
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

CREATE OR REPLACE FUNCTION reject_project_quotation_event_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1 FROM project_quotation_handoffs
        WHERE id = OLD.quotation_id AND project_id = hollawall_project_hard_delete_target()
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'project quotation events are append-only';
END;
$$;

CREATE OR REPLACE FUNCTION guard_project_transaction_evidence_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.project_id = hollawall_project_hard_delete_target() THEN
            RETURN OLD;
        END IF;
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

CREATE OR REPLACE FUNCTION prevent_project_transaction_evidence_event_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1 FROM project_transaction_evidence
        WHERE id = OLD.evidence_id AND project_id = hollawall_project_hard_delete_target()
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'project transaction evidence events are append-only';
END;
$$ LANGUAGE plpgsql;
