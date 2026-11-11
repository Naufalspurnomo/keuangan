-- Persist the complete immutable debt-event replay contract. Every debt event
-- references the canonical internal financial transaction that owns its balanced
-- postings; these columns preserve correction/reversal semantics on readback.

ALTER TABLE interwallet_debt_events
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS reason TEXT,
    ADD COLUMN IF NOT EXISTS corrected_event_type TEXT;

ALTER TABLE interwallet_debt_events
    DROP CONSTRAINT IF EXISTS interwallet_debt_events_corrected_event_type_check;
ALTER TABLE interwallet_debt_events
    ADD CONSTRAINT interwallet_debt_events_corrected_event_type_check CHECK (
        corrected_event_type IS NULL OR corrected_event_type IN ('disbursement', 'repayment')
    );

ALTER TABLE interwallet_debt_events
    DROP CONSTRAINT IF EXISTS interwallet_debt_events_effective_type_check;
ALTER TABLE interwallet_debt_events
    ADD CONSTRAINT interwallet_debt_events_effective_type_check CHECK (
        (event_type IN ('correction', 'reversal')) = (corrected_event_type IS NOT NULL)
    );
