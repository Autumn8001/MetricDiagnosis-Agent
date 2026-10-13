-- Explicit application-state migration. No analytics data or credentials.
BEGIN;
CREATE TABLE IF NOT EXISTS app_state.lab_experiments (
    experiment_id text PRIMARY KEY,
    source_id text NOT NULL UNIQUE,
    environment text NOT NULL DEFAULT 'sandbox' CHECK (environment = 'sandbox'),
    provider text NOT NULL DEFAULT 'synthetic' CHECK (provider = 'synthetic'),
    scenario_id text NOT NULL CHECK (scenario_id IN ('no_anomaly', 'canonical', 'traffic')),
    idempotency_key text NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    target_date date NOT NULL CHECK (target_date = DATE '2026-01-31'),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'publishing', 'published', 'failed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    data_version text,
    failure_code text CHECK (failure_code IN ('publication_failed', 'publication_interrupted', 'publication_recovery_unavailable')),
    requested_metric text,
    investigation_run_id text UNIQUE,
    CONSTRAINT lab_source_environment_fk FOREIGN KEY (source_id, environment)
        REFERENCES app_state.data_sources (source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT lab_run_source_fk FOREIGN KEY (investigation_run_id, source_id, environment)
        REFERENCES app_state.investigation_runs (investigation_run_id, source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT lab_publication_shape CHECK (
        (status = 'published' AND data_version IS NOT NULL AND failure_code IS NULL)
        OR (status IN ('queued', 'publishing') AND data_version IS NULL AND failure_code IS NULL)
        OR (status = 'failed' AND data_version IS NULL AND failure_code IS NOT NULL)),
    CONSTRAINT lab_run_shape CHECK (investigation_run_id IS NULL OR (status = 'published' AND requested_metric IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS lab_experiments_created_idx ON app_state.lab_experiments (created_at DESC, experiment_id DESC);
COMMIT;
