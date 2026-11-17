BEGIN;

ALTER TABLE project_quotation_handoffs
    ADD COLUMN IF NOT EXISTS template_version TEXT,
    ADD COLUMN IF NOT EXISTS payment_profile_key TEXT;

ALTER TABLE project_documents
    ADD COLUMN IF NOT EXISTS template_key TEXT,
    ADD COLUMN IF NOT EXISTS template_version TEXT,
    ADD COLUMN IF NOT EXISTS payment_profile_key TEXT;

ALTER TABLE project_document_lines
    ADD COLUMN IF NOT EXISTS commercial_meta JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE project_document_lines
    DROP CONSTRAINT IF EXISTS chk_project_document_line_commercial_meta_object;
ALTER TABLE project_document_lines
    ADD CONSTRAINT chk_project_document_line_commercial_meta_object
    CHECK (jsonb_typeof(commercial_meta) = 'object');

UPDATE project_quotation_handoffs q
SET template_version = COALESCE(q.template_version, 'commercial-v3'),
    payment_profile_key = COALESCE(q.payment_profile_key, p.issuer_key)
FROM projects p
WHERE p.id = q.project_id
  AND p.company IN ('HOLLA', 'HOJJA', 'TEXTURIN-Surabaya', 'TEXTURIN-Bali')
  AND (q.template_version IS NULL OR q.payment_profile_key IS NULL);

UPDATE project_documents d
SET template_key = COALESCE(d.template_key, CASE p.company
        WHEN 'HOLLA' THEN 'HOLLAWALL'
        WHEN 'HOJJA' THEN 'HOJJA'
        WHEN 'TEXTURIN-Surabaya' THEN 'TEXTURIN'
        WHEN 'TEXTURIN-Bali' THEN 'TEXTURIN'
    END),
    template_version = COALESCE(d.template_version, 'commercial-v3'),
    payment_profile_key = COALESCE(d.payment_profile_key, p.issuer_key)
FROM projects p
WHERE p.id = d.project_id
  AND p.company IN ('HOLLA', 'HOJJA', 'TEXTURIN-Surabaya', 'TEXTURIN-Bali')
  AND (d.template_key IS NULL OR d.template_version IS NULL OR d.payment_profile_key IS NULL);

COMMIT;
