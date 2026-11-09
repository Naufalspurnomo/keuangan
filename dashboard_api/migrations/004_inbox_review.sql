-- Owner-only durable inbox review command and append-only audit schema.
-- Apply before enabling INBOX_REVIEW_WRITES_ENABLED.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('hollawall:inbox-review:migration:v004', 0));

CREATE TABLE IF NOT EXISTS transaction_inbox_review_audit (
    id BIGSERIAL PRIMARY KEY,
    command_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    event_key TEXT NOT NULL,
    message_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('ignore', 'confirm_processed')),
    expected_status TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    resulting_status TEXT NOT NULL CHECK (resulting_status IN ('ignored', 'processed')),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 1000),
    ledger_proof JSONB NOT NULL,
    event_snapshot_hash TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE transaction_inbox_review_audit
    ADD COLUMN IF NOT EXISTS message_id TEXT;
UPDATE transaction_inbox_review_audit AS audit
SET message_id = COALESCE(
    (SELECT inbox.message_id FROM transaction_inbox AS inbox WHERE inbox.event_key = audit.event_key),
    'legacy:' || audit.event_key
)
WHERE audit.message_id IS NULL;
ALTER TABLE transaction_inbox_review_audit
    ALTER COLUMN message_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_transaction_inbox_review_event
    ON transaction_inbox_review_audit (event_key, reviewed_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_transaction_inbox_review_command
    ON transaction_inbox_review_audit (command_key);

CREATE INDEX IF NOT EXISTS idx_transaction_inbox_unresolved_reviews
    ON transaction_inbox (received_at)
    WHERE status LIKE 'needs_review%';

CREATE OR REPLACE FUNCTION reject_inbox_review_audit_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'transaction_inbox_review_audit is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_inbox_review_audit_append_only
    ON transaction_inbox_review_audit;
CREATE TRIGGER trg_inbox_review_audit_append_only
BEFORE UPDATE OR DELETE ON transaction_inbox_review_audit
FOR EACH ROW EXECUTE FUNCTION reject_inbox_review_audit_mutation();

COMMIT;
