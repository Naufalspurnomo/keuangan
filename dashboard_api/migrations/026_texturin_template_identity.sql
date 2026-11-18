BEGIN;

-- Correct draft rows migrated by the original 024 release candidate before
-- branch review distinguished the Surabaya and Bali visual contracts. The
-- runtime trigger intentionally forbids template changes, so suspend only that
-- trigger for this bounded data correction. Transaction rollback restores it
-- automatically if the correction cannot complete.
ALTER TABLE project_documents
    DISABLE TRIGGER trg_project_document_immutable;

UPDATE project_documents d
SET template_key = CASE p.company
        WHEN 'TEXTURIN-Surabaya' THEN 'TEXTURIN-SURABAYA'
        WHEN 'TEXTURIN-Bali' THEN 'TEXTURIN-BALI'
    END
FROM projects p
WHERE p.id = d.project_id
  AND d.status = 'draft'
  AND d.template_key = 'TEXTURIN'
  AND p.company IN ('TEXTURIN-Surabaya', 'TEXTURIN-Bali');

ALTER TABLE project_documents
    ENABLE TRIGGER trg_project_document_immutable;

COMMIT;
