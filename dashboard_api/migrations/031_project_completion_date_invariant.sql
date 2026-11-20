BEGIN;

LOCK TABLE projects IN SHARE ROW EXCLUSIVE MODE;

-- Repair legacy rows once before enforcing the lifecycle invariant. Use the
-- recorded update date in Jakarta so the backfill is deterministic and never
-- invents a date earlier than the Project start date.
WITH repaired AS (
    UPDATE projects
    SET completion_date = GREATEST(
        start_date,
        COALESCE(completion_date,
            updated_at AT TIME ZONE 'Asia/Jakarta',
            created_at AT TIME ZONE 'Asia/Jakarta',
            start_date,
            CURRENT_DATE
        )::date
    ),
        lock_version = lock_version + 1,
        updated_by = '{"type":"system","id":"migration-031"}'::jsonb,
        updated_at = NOW()
    WHERE status = 'completed'
      AND completion_date IS NULL
    RETURNING id, completion_date, lock_version
)
INSERT INTO project_document_events(project_id, document_id, event_type, event_data, actor)
SELECT id, NULL, 'project.completion_date_backfilled',
       jsonb_build_object('completion_date', completion_date, 'lock_version', lock_version),
       '{"type":"system","id":"migration-031"}'::jsonb
FROM repaired;

WITH repaired AS (
    UPDATE projects
    SET completion_date = NULL,
        lock_version = lock_version + 1,
        updated_by = '{"type":"system","id":"migration-031"}'::jsonb,
        updated_at = NOW()
    WHERE status <> 'completed'
      AND completion_date IS NOT NULL
    RETURNING id, lock_version
)
INSERT INTO project_document_events(project_id, document_id, event_type, event_data, actor)
SELECT id, NULL, 'project.completion_date_cleared',
       jsonb_build_object('completion_date', NULL, 'lock_version', lock_version),
       '{"type":"system","id":"migration-031"}'::jsonb
FROM repaired;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_projects_completion_date_lifecycle'
          AND conrelid = 'projects'::regclass
    ) THEN
        ALTER TABLE projects
            ADD CONSTRAINT chk_projects_completion_date_lifecycle CHECK (
                (status = 'completed' AND completion_date IS NOT NULL)
                OR (status <> 'completed' AND completion_date IS NULL)
            );
    END IF;
END;
$$;

COMMIT;
