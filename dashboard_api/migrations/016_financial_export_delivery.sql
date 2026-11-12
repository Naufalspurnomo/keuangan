-- Durable, crash-recoverable delivery state for the derived Sheets export.
-- Canonical payload identity stays immutable; only delivery workflow fields may change.

CREATE SEQUENCE IF NOT EXISTS financial_export_ordinal_seq AS BIGINT;

ALTER TABLE financial_export_outbox
    ADD COLUMN IF NOT EXISTS export_ordinal BIGINT,
    ADD COLUMN IF NOT EXISTS claim_token UUID,
    ADD COLUMN IF NOT EXISTS remote_locator TEXT;

WITH ordered AS (
    SELECT id, row_number() OVER (ORDER BY created_at, id) AS ordinal
    FROM financial_export_outbox
    WHERE export_ordinal IS NULL
)
UPDATE financial_export_outbox AS outbox
SET export_ordinal = ordered.ordinal
FROM ordered
WHERE outbox.id = ordered.id;

SELECT setval(
    'financial_export_ordinal_seq',
    GREATEST(COALESCE((SELECT max(export_ordinal) FROM financial_export_outbox), 0), 1),
    COALESCE((SELECT max(export_ordinal) FROM financial_export_outbox), 0) > 0
);

ALTER TABLE financial_export_outbox
    ALTER COLUMN export_ordinal SET DEFAULT nextval('financial_export_ordinal_seq'),
    ALTER COLUMN export_ordinal SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_financial_export_outbox_ordinal
    ON financial_export_outbox(export_ordinal);

CREATE INDEX IF NOT EXISTS idx_financial_export_outbox_stale_claim
    ON financial_export_outbox(claimed_at, export_ordinal)
    WHERE status = 'exporting';

-- Rows claimed by a pre-v16 worker cannot be acknowledged safely because they
-- have no fencing token. Return them to the bounded retry path.
UPDATE financial_export_outbox
SET status = 'failed',
    last_error = 'schema v16 reset an unfenced exporting claim',
    available_at = now(),
    claim_token = NULL,
    updated_at = now()
WHERE status = 'exporting' AND claim_token IS NULL;

UPDATE financial_export_outbox
SET remote_locator = remote_revision
WHERE status = 'exported'
  AND remote_locator IS NULL
  AND remote_revision IS NOT NULL;

ALTER TABLE financial_export_outbox
    ADD CONSTRAINT financial_export_outbox_delivery_state_check
    CHECK (
        (status = 'exporting' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL)
        OR (status <> 'exporting' AND claim_token IS NULL)
    ) NOT VALID;
ALTER TABLE financial_export_outbox
    VALIDATE CONSTRAINT financial_export_outbox_delivery_state_check;

CREATE OR REPLACE FUNCTION protect_financial_export_identity() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.aggregate_type IS DISTINCT FROM OLD.aggregate_type
       OR NEW.aggregate_id IS DISTINCT FROM OLD.aggregate_id
       OR NEW.aggregate_version IS DISTINCT FROM OLD.aggregate_version
       OR NEW.export_key IS DISTINCT FROM OLD.export_key
       OR NEW.payload IS DISTINCT FROM OLD.payload
       OR NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256
       OR NEW.destination IS DISTINCT FROM OLD.destination
       OR NEW.export_ordinal IS DISTINCT FROM OLD.export_ordinal
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'canonical financial export identity cannot be mutated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_financial_export_outbox_identity_immutable
    ON financial_export_outbox;
CREATE TRIGGER trg_financial_export_outbox_identity_immutable
BEFORE UPDATE ON financial_export_outbox
FOR EACH ROW EXECUTE FUNCTION protect_financial_export_identity();
