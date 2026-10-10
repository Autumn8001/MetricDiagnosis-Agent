-- Distinguish queued inline investigations from investigations owned by the
-- minimal database-backed worker. Existing rows remain inline.
BEGIN;

ALTER TABLE app_state.investigation_runs
    ADD COLUMN IF NOT EXISTS execution_mode text NOT NULL DEFAULT 'inline'
    CHECK (execution_mode IN ('inline', 'worker'));

COMMIT;
