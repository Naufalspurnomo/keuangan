-- Upgrade installations whose append-only event trigger predates the owner-authorized
-- project hard-delete gate. Ordinary UPDATE/DELETE mutations remain rejected.

CREATE OR REPLACE FUNCTION prevent_project_document_event_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.project_id = hollawall_project_hard_delete_target() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'project document events are append-only';
END;
$$ LANGUAGE plpgsql;
