-- Restore the owner-authorized hard-delete exception after migration 025.
--
-- Migration 022 is already recorded in deployed databases. Keep its historical
-- SQL/checksum unchanged; this idempotent compatibility repair is applied by
-- the project-document schema gate after 025 recreates the trigger function.

CREATE OR REPLACE FUNCTION reject_project_quotation_artifact_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1
        FROM project_quotation_handoffs
        WHERE id = OLD.quotation_id
          AND project_id = hollawall_project_hard_delete_target()
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'quotation artifacts are immutable';
END;
$$;
