-- Durable one-way authority latch. Application rollback must never revive Sheets-primary writes.

CREATE TABLE IF NOT EXISTS finance_authority_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    authority TEXT NOT NULL CHECK (authority IN ('google_sheets', 'postgresql')),
    activated_at TIMESTAMPTZ,
    activated_by TEXT,
    historical_import BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT historical_import),
    activation_evidence_sha256 TEXT CHECK (
        activation_evidence_sha256 IS NULL
        OR activation_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (authority = 'google_sheets' AND activated_at IS NULL
            AND activated_by IS NULL AND activation_evidence_sha256 IS NULL
            AND historical_import = FALSE)
        OR
        (authority = 'postgresql' AND activated_at IS NOT NULL
            AND length(trim(activated_by)) BETWEEN 1 AND 200
            AND activation_evidence_sha256 IS NOT NULL)
    )
);

ALTER TABLE finance_authority_state
    ADD COLUMN IF NOT EXISTS historical_import BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT historical_import);

INSERT INTO finance_authority_state (singleton, authority)
VALUES (TRUE, 'google_sheets')
ON CONFLICT (singleton) DO NOTHING;

CREATE OR REPLACE FUNCTION protect_finance_authority_latch()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'finance authority latch cannot be deleted';
    END IF;
    IF OLD.authority = 'postgresql' AND NEW.authority <> 'postgresql' THEN
        RAISE EXCEPTION 'finance authority cannot return to google_sheets';
    END IF;
    IF OLD.authority = 'postgresql' AND (
        NEW.activated_at IS DISTINCT FROM OLD.activated_at
        OR NEW.activated_by IS DISTINCT FROM OLD.activated_by
        OR NEW.historical_import IS DISTINCT FROM OLD.historical_import
        OR NEW.activation_evidence_sha256 IS DISTINCT FROM OLD.activation_evidence_sha256
    ) THEN
        RAISE EXCEPTION 'finance authority activation evidence is immutable';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_protect_finance_authority_latch ON finance_authority_state;
CREATE TRIGGER trg_protect_finance_authority_latch
BEFORE UPDATE OR DELETE ON finance_authority_state
FOR EACH ROW EXECUTE FUNCTION protect_finance_authority_latch();
