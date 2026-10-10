-- MetricSleuth R2 data-source identity protection.
-- A source ID, provider, and environment form one immutable identity. Mutable
-- display and capability metadata remains updateable by the repository.

BEGIN;

CREATE OR REPLACE FUNCTION app_state.reject_data_source_identity_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.source_id IS DISTINCT FROM NEW.source_id
       OR OLD.provider IS DISTINCT FROM NEW.provider
       OR OLD.environment IS DISTINCT FROM NEW.environment THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'Data source identity fields are immutable.';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger AS trigger_row
        JOIN pg_class AS relation_row
            ON relation_row.oid = trigger_row.tgrelid
        JOIN pg_namespace AS namespace_row
            ON namespace_row.oid = relation_row.relnamespace
        WHERE namespace_row.nspname = 'app_state'
          AND relation_row.relname = 'data_sources'
          AND trigger_row.tgname = 'data_sources_identity_immutable'
          AND NOT trigger_row.tgisinternal
    ) THEN
        CREATE TRIGGER data_sources_identity_immutable
            BEFORE UPDATE ON app_state.data_sources
            FOR EACH ROW
            EXECUTE FUNCTION app_state.reject_data_source_identity_change();
    END IF;
END
$$;

COMMIT;
