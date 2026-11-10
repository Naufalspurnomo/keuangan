BEGIN;

ALTER TABLE project_documents
    ADD COLUMN IF NOT EXISTS applies_to_invoice_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'project_documents_applies_to_invoice_id_fkey'
          AND conrelid = 'project_documents'::regclass
    ) THEN
        ALTER TABLE project_documents
            ADD CONSTRAINT project_documents_applies_to_invoice_id_fkey
            FOREIGN KEY (applies_to_invoice_id)
            REFERENCES project_documents(id)
            ON DELETE RESTRICT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'project_documents_receipt_invoice_application_check'
          AND conrelid = 'project_documents'::regclass
    ) THEN
        ALTER TABLE project_documents
            ADD CONSTRAINT project_documents_receipt_invoice_application_check
            CHECK (applies_to_invoice_id IS NULL OR document_type = 'receipt');
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_project_documents_applies_to_invoice
    ON project_documents(applies_to_invoice_id)
    WHERE applies_to_invoice_id IS NOT NULL;

COMMIT;
