BEGIN;

-- Profile account data is owner-scoped deployment input. This migration only
-- attaches Texturin projects to city-specific profiles that already exist.
-- Issued/commercially-active history remains immutable and is deliberately
-- excluded; only an inactive, all-draft project can be corrected. Block all
-- concurrent writes to the eligibility inputs until the backfill commits so a
-- draft cannot be issued after the snapshot and then rewritten below.
LOCK TABLE projects, project_documents, project_quotation_handoffs,
           financial_transactions, financial_ledger
    IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE eligible_texturin_profile_backfill ON COMMIT DROP AS
SELECT
    p.id AS project_id,
    CASE p.company
        WHEN 'TEXTURIN-Surabaya' THEN 'texturin-surabaya'
        WHEN 'TEXTURIN-Bali' THEN 'texturin-bali'
    END AS issuer_key
FROM projects p
WHERE p.company IN ('TEXTURIN-Surabaya', 'TEXTURIN-Bali')
  AND p.issuer_key IS DISTINCT FROM CASE p.company
        WHEN 'TEXTURIN-Surabaya' THEN 'texturin-surabaya'
        WHEN 'TEXTURIN-Bali' THEN 'texturin-bali'
      END
  AND EXISTS (
      SELECT 1 FROM project_issuer_profiles i
      WHERE i.issuer_key = CASE p.company
          WHEN 'TEXTURIN-Surabaya' THEN 'texturin-surabaya'
          WHEN 'TEXTURIN-Bali' THEN 'texturin-bali'
      END
  )
  AND NOT EXISTS (
      SELECT 1 FROM project_documents d
      WHERE d.project_id = p.id AND d.status <> 'draft'
  )
  AND NOT EXISTS (
      SELECT 1 FROM project_quotation_handoffs q
      WHERE q.project_id = p.id AND q.status <> 'draft'
  )
  AND NOT EXISTS (
      SELECT 1 FROM financial_transactions t WHERE t.project_id = p.id
  )
  AND NOT EXISTS (
      SELECT 1 FROM financial_ledger l WHERE l.project_id = p.id
  );

ALTER TABLE project_documents DISABLE TRIGGER trg_project_document_immutable;
UPDATE project_documents d
SET issuer_key = eligible.issuer_key,
    payment_profile_key = eligible.issuer_key,
    lock_version = d.lock_version + 1,
    updated_by = '{"type":"system","id":"migration-029"}'::jsonb,
    updated_at = NOW()
FROM eligible_texturin_profile_backfill eligible
WHERE d.project_id = eligible.project_id
  AND d.status = 'draft'
  AND (d.issuer_key, d.payment_profile_key)
      IS DISTINCT FROM (eligible.issuer_key, eligible.issuer_key);
ALTER TABLE project_documents ENABLE TRIGGER trg_project_document_immutable;

ALTER TABLE project_quotation_handoffs DISABLE TRIGGER trg_project_quotation_transition;
UPDATE project_quotation_handoffs q
SET payment_profile_key = eligible.issuer_key,
    lock_version = q.lock_version + 1,
    updated_by = '{"type":"system","id":"migration-029"}'::jsonb,
    updated_at = NOW()
FROM eligible_texturin_profile_backfill eligible
WHERE q.project_id = eligible.project_id
  AND q.status = 'draft'
  AND q.payment_profile_key IS DISTINCT FROM eligible.issuer_key;
ALTER TABLE project_quotation_handoffs ENABLE TRIGGER trg_project_quotation_transition;

UPDATE projects p
SET issuer_key = eligible.issuer_key,
    lock_version = p.lock_version + 1,
    updated_by = '{"type":"system","id":"migration-029"}'::jsonb,
    updated_at = NOW()
FROM eligible_texturin_profile_backfill eligible
WHERE p.id = eligible.project_id
  AND p.issuer_key IS DISTINCT FROM eligible.issuer_key;

COMMIT;
