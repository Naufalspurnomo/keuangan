-- Canonical PostgreSQL financial authority. Additive and dormant until
-- CANONICAL_FINANCE_WRITES_ENABLED is explicitly enabled after reconciliation.

CREATE TABLE IF NOT EXISTS business_units (
    id UUID PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9_]{2,32}$'),
    legal_name TEXT NOT NULL CHECK (length(trim(legal_name)) BETWEEN 1 AND 200),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wallets (
    id UUID PRIMARY KEY,
    code TEXT NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9_]{2,32}$'),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 120),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A wallet can be shared by multiple business units (for example HOLLA/HOJJA).
CREATE TABLE IF NOT EXISTS wallet_business_units (
    wallet_id UUID NOT NULL REFERENCES wallets(id) ON DELETE RESTRICT,
    business_unit_id UUID NOT NULL REFERENCES business_units(id) ON DELETE RESTRICT,
    PRIMARY KEY (wallet_id, business_unit_id)
);

CREATE TABLE IF NOT EXISTS wallet_opening_balances (
    id UUID PRIMARY KEY,
    wallet_id UUID NOT NULL REFERENCES wallets(id) ON DELETE RESTRICT,
    business_unit_id UUID NOT NULL REFERENCES business_units(id) ON DELETE RESTRICT,
    amount BIGINT NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    effective_at TIMESTAMPTZ NOT NULL,
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    provenance JSONB NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
    source_snapshot_sha256 TEXT NOT NULL CHECK (source_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (wallet_id, business_unit_id, effective_at),
    FOREIGN KEY (wallet_id, business_unit_id)
        REFERENCES wallet_business_units(wallet_id, business_unit_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS balance_adjustments (
    id UUID PRIMARY KEY,
    wallet_id UUID NOT NULL REFERENCES wallets(id) ON DELETE RESTRICT,
    business_unit_id UUID NOT NULL REFERENCES business_units(id) ON DELETE RESTRICT,
    delta_amount BIGINT NOT NULL CHECK (delta_amount <> 0),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    effective_at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    provenance JSONB NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
    source_snapshot_sha256 TEXT CHECK (source_snapshot_sha256 IS NULL OR source_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (wallet_id, business_unit_id)
        REFERENCES wallet_business_units(wallet_id, business_unit_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS financial_transactions (
    id UUID PRIMARY KEY,
    idempotency_key_hash TEXT NOT NULL UNIQUE CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    scope TEXT NOT NULL CHECK (scope IN ('project', 'office', 'group', 'internal')),
    project_id UUID REFERENCES projects(id) ON DELETE RESTRICT,
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('inflow', 'outflow', 'transfer', 'adjustment')),
    flow_class TEXT NOT NULL CHECK (flow_class IN ('external', 'internal', 'adjustment')),
    amount BIGINT NOT NULL CHECK (amount > 0),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    category TEXT,
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    occurred_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('dashboard', 'whatsapp', 'telegram', 'migration', 'system')),
    source_reference TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    revision_of_id UUID REFERENCES financial_transactions(id) ON DELETE RESTRICT,
    reversal_of_id UUID REFERENCES financial_transactions(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    status TEXT NOT NULL DEFAULT 'posted' CHECK (status IN ('posted', 'correction', 'reversal')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((scope = 'project') = (project_id IS NOT NULL)),
    CHECK ((status = 'correction') = (revision_of_id IS NOT NULL)),
    CHECK ((status = 'reversal') = (reversal_of_id IS NOT NULL)),
    CHECK (revision_of_id IS NULL OR revision_of_id <> id),
    CHECK (reversal_of_id IS NULL OR reversal_of_id <> id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_transaction_revision_version
    ON financial_transactions(revision_of_id, version) WHERE revision_of_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_transaction_single_reversal
    ON financial_transactions(reversal_of_id) WHERE reversal_of_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_financial_transactions_occurred
    ON financial_transactions(occurred_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_financial_transactions_project
    ON financial_transactions(project_id, occurred_at DESC) WHERE project_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS financial_postings (
    id UUID PRIMARY KEY,
    transaction_id UUID NOT NULL REFERENCES financial_transactions(id) ON DELETE RESTRICT,
    wallet_id UUID REFERENCES wallets(id) ON DELETE RESTRICT,
    business_unit_id UUID REFERENCES business_units(id) ON DELETE RESTRICT,
    account_class TEXT NOT NULL CHECK (account_class IN (
        'cash', 'revenue', 'expense', 'receivable', 'payable', 'internal_debt'
    )),
    signed_amount BIGINT NOT NULL CHECK (signed_amount <> 0),
    currency CHAR(3) NOT NULL DEFAULT 'IDR' CHECK (currency = 'IDR'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((account_class = 'cash') = (wallet_id IS NOT NULL)),
    CHECK (wallet_id IS NULL OR business_unit_id IS NOT NULL),
    FOREIGN KEY (wallet_id, business_unit_id)
        REFERENCES wallet_business_units(wallet_id, business_unit_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_financial_postings_wallet
    ON financial_postings(wallet_id, transaction_id) WHERE wallet_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_financial_postings_transaction
    ON financial_postings(transaction_id);

CREATE TABLE IF NOT EXISTS project_status_events (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    from_status TEXT,
    to_status TEXT NOT NULL CHECK (to_status IN ('planned', 'active', 'completed', 'cancelled', 'archived')),
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    visible BOOLEAN NOT NULL DEFAULT TRUE,
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    occurred_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((to_status = 'completed') = (completed_at IS NOT NULL)),
    CHECK ((to_status = 'cancelled') = (cancelled_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_project_status_events_replay
    ON project_status_events(project_id, occurred_at, id);

CREATE OR REPLACE FUNCTION reject_financial_immutable_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'canonical financial records cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'wallet_opening_balances', 'balance_adjustments', 'financial_transactions',
        'financial_postings', 'project_status_events'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_immutable ON %I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER trg_%I_immutable BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION reject_financial_immutable_mutation()',
            table_name, table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION validate_financial_transaction_chain() RETURNS TRIGGER AS $$
DECLARE
    cursor_id UUID;
    next_id UUID;
BEGIN
    IF NEW.revision_of_id IS NULL AND NEW.reversal_of_id IS NULL THEN
        RETURN NEW;
    END IF;
    cursor_id := COALESCE(NEW.revision_of_id, NEW.reversal_of_id);
    LOOP
        IF cursor_id = NEW.id THEN
            RAISE EXCEPTION 'financial transaction revision/reversal cycle';
        END IF;
        SELECT COALESCE(revision_of_id, reversal_of_id)
          INTO next_id FROM financial_transactions WHERE id = cursor_id;
        EXIT WHEN next_id IS NULL;
        cursor_id := next_id;
    END LOOP;
    IF NEW.reversal_of_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM financial_transactions WHERE reversal_of_id = NEW.reversal_of_id
    ) THEN
        RAISE EXCEPTION 'financial transaction already reversed';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_financial_transaction_chain ON financial_transactions;
CREATE TRIGGER trg_financial_transaction_chain
BEFORE INSERT ON financial_transactions
FOR EACH ROW EXECUTE FUNCTION validate_financial_transaction_chain();

CREATE OR REPLACE FUNCTION validate_balanced_transaction_postings(p_transaction_id UUID) RETURNS VOID AS $$
DECLARE
    total NUMERIC;
    row_count BIGINT;
BEGIN
    SELECT COALESCE(sum(signed_amount), 0), count(*) INTO total, row_count
      FROM financial_postings WHERE transaction_id = p_transaction_id;
    IF row_count < 2 OR total <> 0 THEN
        RAISE EXCEPTION 'financial transaction postings must be balanced';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION validate_new_financial_transaction_postings() RETURNS TRIGGER AS $$
BEGIN
    PERFORM validate_balanced_transaction_postings(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION validate_changed_financial_postings() RETURNS TRIGGER AS $$
BEGIN
    PERFORM validate_balanced_transaction_postings(NEW.transaction_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_financial_transaction_balanced ON financial_transactions;
CREATE CONSTRAINT TRIGGER trg_financial_transaction_balanced
AFTER INSERT ON financial_transactions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_new_financial_transaction_postings();

DROP TRIGGER IF EXISTS trg_financial_postings_balanced ON financial_postings;
CREATE CONSTRAINT TRIGGER trg_financial_postings_balanced
AFTER INSERT ON financial_postings
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_changed_financial_postings();
