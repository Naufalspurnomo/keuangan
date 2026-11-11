-- Balanced inter-wallet debt aggregate. Cash movement is represented by linked
-- canonical transaction/posting pairs; debt rows never count as revenue/expense.

CREATE TABLE IF NOT EXISTS interwallet_debts (
    id UUID PRIMARY KEY,
    lender_wallet_id UUID NOT NULL REFERENCES wallets(id) ON DELETE RESTRICT,
    borrower_wallet_id UUID NOT NULL REFERENCES wallets(id) ON DELETE RESTRICT,
    lender_business_unit_id UUID NOT NULL REFERENCES business_units(id) ON DELETE RESTRICT,
    borrower_business_unit_id UUID NOT NULL REFERENCES business_units(id) ON DELETE RESTRICT,
    project_id UUID REFERENCES projects(id) ON DELETE RESTRICT,
    principal BIGINT NOT NULL CHECK (principal > 0),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    occurred_at TIMESTAMPTZ NOT NULL,
    due_at TIMESTAMPTZ,
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paid', 'reversed', 'archived')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (lender_wallet_id <> borrower_wallet_id),
    CHECK (due_at IS NULL OR due_at >= occurred_at),
    FOREIGN KEY (lender_wallet_id, lender_business_unit_id)
        REFERENCES wallet_business_units(wallet_id, business_unit_id) ON DELETE RESTRICT,
    FOREIGN KEY (borrower_wallet_id, borrower_business_unit_id)
        REFERENCES wallet_business_units(wallet_id, business_unit_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS interwallet_debt_events (
    id UUID PRIMARY KEY,
    debt_id UUID NOT NULL REFERENCES interwallet_debts(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'disbursement', 'repayment', 'correction', 'reversal', 'archive'
    )),
    amount BIGINT NOT NULL CHECK (amount > 0),
    transaction_id UUID NOT NULL UNIQUE REFERENCES financial_transactions(id) ON DELETE RESTRICT,
    corrects_event_id UUID REFERENCES interwallet_debt_events(id) ON DELETE RESTRICT,
    reverses_event_id UUID REFERENCES interwallet_debt_events(id) ON DELETE RESTRICT,
    idempotency_key_hash TEXT NOT NULL UNIQUE CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((event_type = 'correction') = (corrects_event_id IS NOT NULL)),
    CHECK ((event_type = 'reversal') = (reverses_event_id IS NOT NULL)),
    CHECK (corrects_event_id IS NULL OR corrects_event_id <> id),
    CHECK (reverses_event_id IS NULL OR reverses_event_id <> id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_interwallet_debt_single_correction
    ON interwallet_debt_events(corrects_event_id) WHERE corrects_event_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_interwallet_debt_single_reversal
    ON interwallet_debt_events(reverses_event_id) WHERE reverses_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_interwallet_debt_events_replay
    ON interwallet_debt_events(debt_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS idx_interwallet_debts_status_due
    ON interwallet_debts(status, due_at) WHERE status = 'open';

CREATE OR REPLACE FUNCTION validate_interwallet_debt_event_reference() RETURNS TRIGGER AS $$
DECLARE
    referenced_debt_id UUID;
BEGIN
    IF NEW.corrects_event_id IS NOT NULL THEN
        SELECT debt_id INTO referenced_debt_id
          FROM interwallet_debt_events WHERE id = NEW.corrects_event_id;
        IF referenced_debt_id IS DISTINCT FROM NEW.debt_id THEN
            RAISE EXCEPTION 'interwallet debt correction must reference the same debt';
        END IF;
    END IF;
    IF NEW.reverses_event_id IS NOT NULL THEN
        SELECT debt_id INTO referenced_debt_id
          FROM interwallet_debt_events WHERE id = NEW.reverses_event_id;
        IF referenced_debt_id IS DISTINCT FROM NEW.debt_id THEN
            RAISE EXCEPTION 'interwallet debt reversal must reference the same debt';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_interwallet_debt_event_reference ON interwallet_debt_events;
CREATE TRIGGER trg_interwallet_debt_event_reference
BEFORE INSERT ON interwallet_debt_events
FOR EACH ROW EXECUTE FUNCTION validate_interwallet_debt_event_reference();

CREATE OR REPLACE FUNCTION reject_interwallet_debt_event_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'interwallet debt events cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_interwallet_debt_events_immutable ON interwallet_debt_events;
CREATE TRIGGER trg_interwallet_debt_events_immutable
BEFORE UPDATE OR DELETE ON interwallet_debt_events
FOR EACH ROW EXECUTE FUNCTION reject_interwallet_debt_event_mutation();

CREATE OR REPLACE FUNCTION reject_interwallet_debt_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'interwallet debts cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_interwallet_debts_immutable ON interwallet_debts;
CREATE TRIGGER trg_interwallet_debts_immutable
BEFORE UPDATE OR DELETE ON interwallet_debts
FOR EACH ROW EXECUTE FUNCTION reject_interwallet_debt_mutation();
