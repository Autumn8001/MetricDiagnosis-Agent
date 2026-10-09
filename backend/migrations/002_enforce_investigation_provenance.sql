-- MetricSleuth R2-004 investigation provenance guard.
-- This migration only adds app_state constraints. It does not execute a
-- migration runner and does not alter warehouse or source data tables.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation_row
            ON relation_row.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace_row
            ON namespace_row.oid = relation_row.relnamespace
        WHERE namespace_row.nspname = 'app_state'
          AND relation_row.relname = 'investigation_runs'
          AND constraint_row.conname = 'investigation_runs_provenance_unique'
    ) THEN
        ALTER TABLE app_state.investigation_runs
            ADD CONSTRAINT investigation_runs_provenance_unique
            UNIQUE (investigation_run_id, source_id, environment);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation_row
            ON relation_row.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace_row
            ON namespace_row.oid = relation_row.relnamespace
        WHERE namespace_row.nspname = 'app_state'
          AND relation_row.relname = 'tool_calls'
          AND constraint_row.conname = 'tool_calls_provenance_unique'
    ) THEN
        ALTER TABLE app_state.tool_calls
            ADD CONSTRAINT tool_calls_provenance_unique
            UNIQUE (tool_call_id, investigation_run_id, source_id, environment);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation_row
            ON relation_row.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace_row
            ON namespace_row.oid = relation_row.relnamespace
        WHERE namespace_row.nspname = 'app_state'
          AND relation_row.relname = 'tool_calls'
          AND constraint_row.conname = 'tool_calls_investigation_provenance_fk'
    ) THEN
        ALTER TABLE app_state.tool_calls
            ADD CONSTRAINT tool_calls_investigation_provenance_fk
            FOREIGN KEY (investigation_run_id, source_id, environment)
            REFERENCES app_state.investigation_runs
                (investigation_run_id, source_id, environment)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation_row
            ON relation_row.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace_row
            ON namespace_row.oid = relation_row.relnamespace
        WHERE namespace_row.nspname = 'app_state'
          AND relation_row.relname = 'observations'
          AND constraint_row.conname = 'observations_investigation_provenance_fk'
    ) THEN
        ALTER TABLE app_state.observations
            ADD CONSTRAINT observations_investigation_provenance_fk
            FOREIGN KEY (investigation_run_id, source_id, environment)
            REFERENCES app_state.investigation_runs
                (investigation_run_id, source_id, environment)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation_row
            ON relation_row.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace_row
            ON namespace_row.oid = relation_row.relnamespace
        WHERE namespace_row.nspname = 'app_state'
          AND relation_row.relname = 'evidence'
          AND constraint_row.conname = 'evidence_investigation_provenance_fk'
    ) THEN
        ALTER TABLE app_state.evidence
            ADD CONSTRAINT evidence_investigation_provenance_fk
            FOREIGN KEY (investigation_run_id, source_id, environment)
            REFERENCES app_state.investigation_runs
                (investigation_run_id, source_id, environment)
            ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation_row
            ON relation_row.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace_row
            ON namespace_row.oid = relation_row.relnamespace
        WHERE namespace_row.nspname = 'app_state'
          AND relation_row.relname = 'diagnoses'
          AND constraint_row.conname = 'diagnoses_investigation_provenance_fk'
    ) THEN
        ALTER TABLE app_state.diagnoses
            ADD CONSTRAINT diagnoses_investigation_provenance_fk
            FOREIGN KEY (investigation_run_id, source_id, environment)
            REFERENCES app_state.investigation_runs
                (investigation_run_id, source_id, environment)
            ON DELETE RESTRICT;
    END IF;
END
$$;

COMMIT;
