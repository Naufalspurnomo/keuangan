-- Independent review history; financial transactions and their amounts stay unchanged.
CREATE TABLE IF NOT EXISTS project_expense_classification_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL CHECK (length(source_key) BETWEEN 1 AND 512),
    source_fingerprint TEXT NOT NULL CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
    source_snapshot JSONB NOT NULL CHECK (jsonb_typeof(source_snapshot) = 'object'),
    classification TEXT NOT NULL CHECK (classification IN ('project_cost', 'non_cost')),
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_project_expense_classification_history
    ON project_expense_classification_events (project_id, source_key, id DESC);

CREATE OR REPLACE FUNCTION guard_project_expense_classification_event()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.project_id = hollawall_project_hard_delete_target() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'expense classification history is append-only';
END;
$$;
DROP TRIGGER IF EXISTS trg_project_expense_classification_immutable ON project_expense_classification_events;
CREATE TRIGGER trg_project_expense_classification_immutable
    BEFORE UPDATE OR DELETE ON project_expense_classification_events
    FOR EACH ROW EXECUTE FUNCTION guard_project_expense_classification_event();
