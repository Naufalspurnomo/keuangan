BEGIN;

DO $$
BEGIN
    IF to_regclass('public.financial_ledger') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE financial_ledger
        ADD COLUMN IF NOT EXISTS project_id UUID;

    CREATE INDEX IF NOT EXISTS idx_financial_ledger_project_id_date
        ON financial_ledger (project_id, transaction_date DESC)
        WHERE project_id IS NOT NULL;

    IF to_regclass('public.projects') IS NOT NULL THEN
        UPDATE financial_ledger AS ledger
        SET project_id = projects.id
        FROM projects
        WHERE ledger.project_id IS NULL
          AND ledger.project = projects.id::text;

        WITH unique_names AS (
            SELECT LOWER(BTRIM(name)) AS normalized_name, MIN(id::text)::uuid AS project_id
            FROM projects
            GROUP BY LOWER(BTRIM(name))
            HAVING COUNT(*) = 1
        )
        UPDATE financial_ledger AS ledger
        SET project_id = unique_names.project_id
        FROM unique_names
        WHERE ledger.project_id IS NULL
          AND LOWER(BTRIM(ledger.project)) = unique_names.normalized_name;

        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'financial_ledger_project_id_fkey'
              AND conrelid = 'financial_ledger'::regclass
              AND pg_get_constraintdef(oid, TRUE) <>
                  'FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT'
        ) THEN
            ALTER TABLE financial_ledger
                DROP CONSTRAINT financial_ledger_project_id_fkey;
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'financial_ledger_project_id_fkey'
              AND conrelid = 'financial_ledger'::regclass
        ) THEN
            ALTER TABLE financial_ledger
                ADD CONSTRAINT financial_ledger_project_id_fkey
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
        END IF;
    END IF;
END $$;

COMMIT;
