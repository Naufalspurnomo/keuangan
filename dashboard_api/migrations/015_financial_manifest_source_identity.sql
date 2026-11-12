-- Preserve real legacy provenance where multiple transactions can share a
-- visible Sheet locator. source_key remains the idempotency identity.

ALTER TABLE financial_migration_manifest
    ADD COLUMN IF NOT EXISTS source_block TEXT;

UPDATE financial_migration_manifest
SET source_block = COALESCE(NULLIF(reference_map ->> 'source_block', ''), 'legacy')
WHERE source_block IS NULL;

ALTER TABLE financial_migration_manifest
    ALTER COLUMN source_block SET NOT NULL;

ALTER TABLE financial_migration_manifest
    ADD CONSTRAINT financial_manifest_source_block_nonempty
    CHECK (length(trim(source_block)) > 0);

DO $$
DECLARE
    old_constraint TEXT;
BEGIN
    SELECT constraint_record.conname
    INTO old_constraint
    FROM pg_constraint AS constraint_record
    WHERE constraint_record.conrelid = 'financial_migration_manifest'::regclass
      AND constraint_record.contype = 'u'
      AND (
          SELECT array_agg(attribute_record.attname::TEXT ORDER BY key_record.ordinality)
          FROM unnest(constraint_record.conkey)
               WITH ORDINALITY AS key_record(attnum, ordinality)
          JOIN pg_attribute AS attribute_record
            ON attribute_record.attrelid = constraint_record.conrelid
           AND attribute_record.attnum = key_record.attnum
      ) = ARRAY[
          'source_spreadsheet_id',
          'source_snapshot_sha256',
          'source_tab',
          'source_row'
      ]::TEXT[]
    LIMIT 1;

    IF old_constraint IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE financial_migration_manifest DROP CONSTRAINT %I',
            old_constraint
        );
    END IF;
END
$$;

ALTER TABLE financial_migration_manifest
    ADD CONSTRAINT financial_manifest_source_identity_unique
    UNIQUE (
        source_spreadsheet_id,
        source_snapshot_sha256,
        source_tab,
        source_block,
        source_row,
        legacy_source_key
    );
