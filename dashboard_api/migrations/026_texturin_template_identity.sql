BEGIN;

-- Correct legacy rows migrated by the original 024 release candidate before
-- branch review distinguished the Surabaya and Bali visual contracts.
UPDATE project_documents d
SET template_key = CASE p.company
        WHEN 'TEXTURIN-Surabaya' THEN 'TEXTURIN-SURABAYA'
        WHEN 'TEXTURIN-Bali' THEN 'TEXTURIN-BALI'
    END
FROM projects p
WHERE p.id = d.project_id
  AND d.template_key = 'TEXTURIN'
  AND p.company IN ('TEXTURIN-Surabaya', 'TEXTURIN-Bali');

COMMIT;
