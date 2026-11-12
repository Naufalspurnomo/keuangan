-- One-way derived Sheets export and authority reconciliation state.

CREATE TABLE IF NOT EXISTS financial_export_outbox (
    id UUID PRIMARY KEY,
    aggregate_type TEXT NOT NULL CHECK (aggregate_type IN ('transaction', 'debt', 'project_status')),
    aggregate_id UUID NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK (aggregate_version > 0),
    export_key TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    destination TEXT NOT NULL CHECK (length(trim(destination)) > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'exporting', 'exported', 'drifted', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    exported_at TIMESTAMPTZ,
    remote_revision TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (aggregate_type, aggregate_id, aggregate_version)
);
CREATE INDEX IF NOT EXISTS idx_financial_export_outbox_pending
    ON financial_export_outbox(available_at, id) WHERE status IN ('pending', 'failed');

CREATE TABLE IF NOT EXISTS financial_reconciliation_checkpoints (
    id UUID PRIMARY KEY,
    authority TEXT NOT NULL CHECK (authority IN ('legacy_sheets', 'postgres', 'sheets_export')),
    cutoff_at TIMESTAMPTZ NOT NULL,
    source_snapshot_sha256 TEXT NOT NULL CHECK (source_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    row_count BIGINT NOT NULL CHECK (row_count >= 0),
    amount_total BIGINT NOT NULL,
    ending_balance_total BIGINT NOT NULL,
    grouped_hash_sha256 TEXT NOT NULL CHECK (grouped_hash_sha256 ~ '^[0-9a-f]{64}$'),
    unexplained_rows BIGINT NOT NULL DEFAULT 0 CHECK (unexplained_rows >= 0),
    unexplained_amount BIGINT NOT NULL DEFAULT 0,
    ending_balance_drift BIGINT NOT NULL DEFAULT 0,
    dangling_references BIGINT NOT NULL DEFAULT 0 CHECK (dangling_references >= 0),
    details JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_by JSONB NOT NULL CHECK (jsonb_typeof(created_by) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (authority, cutoff_at, source_snapshot_sha256)
);

CREATE TABLE IF NOT EXISTS financial_migration_runs (
    id UUID PRIMARY KEY,
    source_spreadsheet_id TEXT NOT NULL,
    source_snapshot_sha256 TEXT NOT NULL CHECK (source_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL CHECK (status IN ('dry_run', 'running', 'interrupted', 'reconciled', 'cutover_ready', 'failed')),
    checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(checkpoint) = 'object'),
    started_by JSONB NOT NULL CHECK (jsonb_typeof(started_by) = 'object'),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (source_spreadsheet_id, source_snapshot_sha256)
);

CREATE TABLE IF NOT EXISTS financial_migration_manifest (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES financial_migration_runs(id) ON DELETE RESTRICT,
    source_spreadsheet_id TEXT NOT NULL,
    source_snapshot_sha256 TEXT NOT NULL CHECK (source_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    source_tab TEXT NOT NULL,
    source_row INTEGER NOT NULL CHECK (source_row > 0),
    legacy_source_key TEXT NOT NULL,
    source_row_sha256 TEXT NOT NULL CHECK (source_row_sha256 ~ '^[0-9a-f]{64}$'),
    canonical_transaction_id UUID REFERENCES financial_transactions(id) ON DELETE RESTRICT,
    canonical_debt_id UUID REFERENCES interwallet_debts(id) ON DELETE RESTRICT,
    canonical_project_id UUID REFERENCES projects(id) ON DELETE RESTRICT,
    wallet_id UUID REFERENCES wallets(id) ON DELETE RESTRICT,
    business_unit_id UUID REFERENCES business_units(id) ON DELETE RESTRICT,
    mapping_type TEXT NOT NULL CHECK (mapping_type IN (
        'opening_balance', 'adjustment', 'transaction', 'debt_principal', 'debt_repayment',
        'project_status', 'document', 'allocation', 'receipt', 'evidence', 'quotation', 'quarantine'
    )),
    reference_map JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(reference_map) = 'object'),
    disposition TEXT NOT NULL CHECK (disposition IN ('mapped', 'resolved', 'owner_excluded', 'quarantined')),
    disposition_actor JSONB CHECK (disposition_actor IS NULL OR jsonb_typeof(disposition_actor) = 'object'),
    disposition_reason TEXT,
    disposition_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_spreadsheet_id, source_snapshot_sha256, source_tab, source_row),
    UNIQUE (run_id, legacy_source_key),
    CHECK (
        disposition = 'mapped' OR
        (disposition_actor IS NOT NULL AND disposition_reason IS NOT NULL AND disposition_at IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_financial_manifest_run_disposition
    ON financial_migration_manifest(run_id, disposition, source_tab, source_row);

CREATE OR REPLACE FUNCTION reject_financial_history_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'financial authority history cannot be mutated or hard deleted';
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'financial_reconciliation_checkpoints', 'financial_migration_manifest'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_immutable ON %I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER trg_%I_immutable BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION reject_financial_history_mutation()',
            table_name, table_name
        );
    END LOOP;
END;
$$;
