-- Additive read indexes for the private Hollawall dashboard.
-- No table or source-ledger mutation is performed.

CREATE INDEX IF NOT EXISTS idx_financial_ledger_dashboard_scope
    ON financial_ledger (wallet, company, project, transaction_date DESC, id DESC)
    WHERE is_valid;

CREATE INDEX IF NOT EXISTS idx_financial_ledger_dashboard_type_date
    ON financial_ledger (transaction_type, transaction_date DESC, id DESC)
    WHERE is_valid;

CREATE INDEX IF NOT EXISTS idx_financial_ledger_dashboard_updated
    ON financial_ledger (updated_at DESC);
