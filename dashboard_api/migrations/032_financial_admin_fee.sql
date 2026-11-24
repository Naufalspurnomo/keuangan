BEGIN;

-- Biaya Admin is a presentation breakdown. `amount` remains the ledger amount;
-- admin_fee must never be added to income/expense totals.
ALTER TABLE financial_transactions
    ADD COLUMN IF NOT EXISTS admin_fee BIGINT NOT NULL DEFAULT 0;

ALTER TABLE financial_transactions
    DROP CONSTRAINT IF EXISTS financial_transactions_admin_fee_check;

ALTER TABLE financial_transactions
    ADD CONSTRAINT financial_transactions_admin_fee_check
    CHECK (admin_fee >= 0);

COMMIT;