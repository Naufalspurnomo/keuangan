ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS quotation_required BOOLEAN;

UPDATE projects
SET quotation_required = FALSE
WHERE quotation_required IS NULL;

ALTER TABLE projects
    ALTER COLUMN quotation_required SET DEFAULT TRUE,
    ALTER COLUMN quotation_required SET NOT NULL;

CREATE TABLE IF NOT EXISTS project_quotation_handoffs (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    version INTEGER NOT NULL CHECK (version > 0),
    canva_url TEXT NOT NULL CHECK (canva_url ~ '^https://'),
    amount BIGINT NOT NULL CHECK (amount > 0 AND amount <= 9000000000000000),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'sent', 'revised', 'accepted', 'rejected')),
    channel TEXT NOT NULL DEFAULT 'whatsapp'
        CHECK (channel IN ('whatsapp', 'phone', 'email', 'meeting', 'other')),
    negotiation_notes TEXT,
    sent_at TIMESTAMPTZ,
    decided_at TIMESTAMPTZ,
    sales_order_id UUID REFERENCES project_documents(id),
    created_by JSONB NOT NULL CHECK (jsonb_typeof(created_by) = 'object'),
    updated_by JSONB NOT NULL CHECK (jsonb_typeof(updated_by) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version > 0),
    CONSTRAINT uq_project_quotation_version UNIQUE (project_id, version),
    CONSTRAINT chk_project_quotation_timestamps CHECK (
        (status = 'draft' AND sent_at IS NULL AND decided_at IS NULL)
        OR (status = 'sent' AND sent_at IS NOT NULL AND decided_at IS NULL)
        OR (status IN ('revised', 'accepted', 'rejected') AND sent_at IS NOT NULL AND decided_at IS NOT NULL)
    ),
    CONSTRAINT chk_project_quotation_sales_order CHECK (
        sales_order_id IS NULL OR status = 'accepted'
    )
);

ALTER TABLE project_quotation_handoffs
    ADD COLUMN IF NOT EXISTS sales_order_id UUID REFERENCES project_documents(id);

ALTER TABLE project_quotation_handoffs
    ALTER COLUMN project_id DROP DEFAULT,
    ALTER COLUMN project_id SET NOT NULL,
    ALTER COLUMN version DROP DEFAULT,
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN canva_url DROP DEFAULT,
    ALTER COLUMN canva_url SET NOT NULL,
    ALTER COLUMN amount DROP DEFAULT,
    ALTER COLUMN amount SET NOT NULL,
    ALTER COLUMN status SET DEFAULT 'draft',
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN channel SET DEFAULT 'whatsapp',
    ALTER COLUMN channel SET NOT NULL,
    ALTER COLUMN negotiation_notes DROP DEFAULT,
    ALTER COLUMN sent_at DROP DEFAULT,
    ALTER COLUMN decided_at DROP DEFAULT,
    ALTER COLUMN sales_order_id DROP DEFAULT,
    ALTER COLUMN created_by DROP DEFAULT,
    ALTER COLUMN created_by SET NOT NULL,
    ALTER COLUMN updated_by DROP DEFAULT,
    ALTER COLUMN updated_by SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET NOT NULL,
    ALTER COLUMN lock_version SET DEFAULT 1,
    ALTER COLUMN lock_version SET NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_project_quotation_sales_order'
          AND conrelid = 'project_quotation_handoffs'::regclass
          AND pg_get_constraintdef(oid, TRUE) <>
              'CHECK (sales_order_id IS NULL OR status = ''accepted''::text)'
    ) THEN
        ALTER TABLE project_quotation_handoffs
            DROP CONSTRAINT chk_project_quotation_sales_order;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_project_quotation_sales_order'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT chk_project_quotation_sales_order
            CHECK (sales_order_id IS NULL OR status = 'accepted');
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_project_quotation_timestamps'
          AND conrelid = 'project_quotation_handoffs'::regclass
          AND pg_get_constraintdef(oid, TRUE) <>
              'CHECK (status = ''draft''::text AND sent_at IS NULL AND decided_at IS NULL OR status = ''sent''::text AND sent_at IS NOT NULL AND decided_at IS NULL OR (status = ANY (ARRAY[''revised''::text, ''accepted''::text, ''rejected''::text])) AND sent_at IS NOT NULL AND decided_at IS NOT NULL)'
    ) THEN
        ALTER TABLE project_quotation_handoffs
            DROP CONSTRAINT chk_project_quotation_timestamps;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_project_quotation_timestamps'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT chk_project_quotation_timestamps CHECK (
                (status = 'draft' AND sent_at IS NULL AND decided_at IS NULL)
                OR (status = 'sent' AND sent_at IS NOT NULL AND decided_at IS NULL)
                OR (status IN ('revised', 'accepted', 'rejected') AND sent_at IS NOT NULL AND decided_at IS NOT NULL)
            );
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_handoffs_project_id_fkey'
          AND conrelid = 'project_quotation_handoffs'::regclass
          AND pg_get_constraintdef(oid, TRUE) <>
              'FOREIGN KEY (project_id) REFERENCES projects(id)'
    ) THEN
        ALTER TABLE project_quotation_handoffs
            DROP CONSTRAINT project_quotation_handoffs_project_id_fkey;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_handoffs_project_id_fkey'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT project_quotation_handoffs_project_id_fkey
            FOREIGN KEY (project_id) REFERENCES projects(id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_handoffs_sales_order_id_fkey'
          AND conrelid = 'project_quotation_handoffs'::regclass
          AND pg_get_constraintdef(oid, TRUE) <>
              'FOREIGN KEY (sales_order_id) REFERENCES project_documents(id)'
    ) THEN
        ALTER TABLE project_quotation_handoffs
            DROP CONSTRAINT project_quotation_handoffs_sales_order_id_fkey;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_handoffs_sales_order_id_fkey'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT project_quotation_handoffs_sales_order_id_fkey
            FOREIGN KEY (sales_order_id) REFERENCES project_documents(id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_project_quotation_version'
          AND conrelid = 'project_quotation_handoffs'::regclass
          AND pg_get_constraintdef(oid, TRUE) <> 'UNIQUE (project_id, version)'
    ) THEN
        ALTER TABLE project_quotation_handoffs
            DROP CONSTRAINT uq_project_quotation_version;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_project_quotation_version'
          AND conrelid = 'project_quotation_handoffs'::regclass
    ) THEN
        ALTER TABLE project_quotation_handoffs
            ADD CONSTRAINT uq_project_quotation_version UNIQUE (project_id, version);
    END IF;
END;
$$;

DO $$
BEGIN
    IF to_regclass('public.uq_project_accepted_quotation') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM pg_index i
           JOIN pg_class c ON c.oid = i.indexrelid
           WHERE c.oid = to_regclass('public.uq_project_accepted_quotation')
             AND pg_get_indexdef(i.indexrelid) =
                 'CREATE UNIQUE INDEX uq_project_accepted_quotation ON public.project_quotation_handoffs USING btree (project_id) WHERE (status = ''accepted''::text)'
       ) THEN
        DROP INDEX public.uq_project_accepted_quotation;
    END IF;
    IF to_regclass('public.uq_project_quotation_sales_order') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM pg_index i
           JOIN pg_class c ON c.oid = i.indexrelid
           WHERE c.oid = to_regclass('public.uq_project_quotation_sales_order')
             AND pg_get_indexdef(i.indexrelid) =
                 'CREATE UNIQUE INDEX uq_project_quotation_sales_order ON public.project_quotation_handoffs USING btree (sales_order_id) WHERE (sales_order_id IS NOT NULL)'
       ) THEN
        DROP INDEX public.uq_project_quotation_sales_order;
    END IF;
    IF to_regclass('public.idx_project_quotation_project_version') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM pg_index i
           JOIN pg_class c ON c.oid = i.indexrelid
           WHERE c.oid = to_regclass('public.idx_project_quotation_project_version')
             AND pg_get_indexdef(i.indexrelid) =
                 'CREATE INDEX idx_project_quotation_project_version ON public.project_quotation_handoffs USING btree (project_id, version DESC)'
       ) THEN
        DROP INDEX public.idx_project_quotation_project_version;
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_accepted_quotation
    ON project_quotation_handoffs(project_id)
    WHERE status = 'accepted';

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_quotation_sales_order
    ON project_quotation_handoffs(sales_order_id)
    WHERE sales_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_project_quotation_project_version
    ON project_quotation_handoffs(project_id, version DESC);

CREATE TABLE IF NOT EXISTS project_quotation_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quotation_id UUID NOT NULL REFERENCES project_quotation_handoffs(id),
    event_type TEXT NOT NULL,
    actor JSONB NOT NULL CHECK (jsonb_typeof(actor) = 'object'),
    data JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(data) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE project_quotation_events
    ALTER COLUMN quotation_id DROP DEFAULT,
    ALTER COLUMN quotation_id SET NOT NULL,
    ALTER COLUMN event_type DROP DEFAULT,
    ALTER COLUMN event_type SET NOT NULL,
    ALTER COLUMN actor DROP DEFAULT,
    ALTER COLUMN actor SET NOT NULL,
    ALTER COLUMN data SET DEFAULT '{}'::jsonb,
    ALTER COLUMN data SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN created_at SET NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_events_quotation_id_fkey'
          AND conrelid = 'project_quotation_events'::regclass
          AND pg_get_constraintdef(oid, TRUE) <>
              'FOREIGN KEY (quotation_id) REFERENCES project_quotation_handoffs(id)'
    ) THEN
        ALTER TABLE project_quotation_events
            DROP CONSTRAINT project_quotation_events_quotation_id_fkey;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_quotation_events_quotation_id_fkey'
          AND conrelid = 'project_quotation_events'::regclass
    ) THEN
        ALTER TABLE project_quotation_events
            ADD CONSTRAINT project_quotation_events_quotation_id_fkey
            FOREIGN KEY (quotation_id) REFERENCES project_quotation_handoffs(id);
    END IF;
END;
$$;

DO $$
BEGIN
    IF to_regclass('public.idx_project_quotation_events_replay') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_index
           WHERE indexrelid = to_regclass('public.idx_project_quotation_events_replay')
             AND pg_get_indexdef(indexrelid) =
                 'CREATE INDEX idx_project_quotation_events_replay ON public.project_quotation_events USING btree (quotation_id, id)'
       ) THEN
        DROP INDEX public.idx_project_quotation_events_replay;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_project_quotation_events_replay
    ON project_quotation_events(quotation_id, id);

CREATE OR REPLACE FUNCTION guard_project_quotation_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id OR NEW.version <> OLD.version
       OR NEW.canva_url <> OLD.canva_url OR NEW.amount <> OLD.amount
       OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'quotation identity and commercial terms are immutable; create a new version';
    END IF;
    IF OLD.status = 'rejected' THEN
        RAISE EXCEPTION 'decided quotation is immutable';
    END IF;
    IF OLD.status = 'accepted' AND NOT (
        NEW.status = OLD.status
        AND OLD.sales_order_id IS NULL
        AND NEW.sales_order_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'accepted quotation only permits one Sales Order handoff';
    END IF;
    IF NEW.lock_version <> OLD.lock_version + 1 THEN
        RAISE EXCEPTION 'quotation lock_version must increment by one';
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_project_quotation_transition ON project_quotation_handoffs;
CREATE TRIGGER trg_project_quotation_transition
BEFORE UPDATE ON project_quotation_handoffs
FOR EACH ROW EXECUTE FUNCTION guard_project_quotation_transition();

CREATE OR REPLACE FUNCTION reject_project_quotation_event_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'project quotation events are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_project_quotation_events_append_only ON project_quotation_events;
CREATE TRIGGER trg_project_quotation_events_append_only
BEFORE UPDATE OR DELETE ON project_quotation_events
FOR EACH ROW EXECUTE FUNCTION reject_project_quotation_event_mutation();
