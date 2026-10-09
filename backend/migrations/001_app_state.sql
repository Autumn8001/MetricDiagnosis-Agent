-- MetricSleuth R2-001 application-state schema.
-- This migration owns only the app_state schema. It does not alter analytics
-- warehouse objects or contain source authentication material.

BEGIN;

CREATE SCHEMA IF NOT EXISTS app_state;

CREATE TABLE IF NOT EXISTS app_state.data_sources (
    source_id text PRIMARY KEY,
    provider text NOT NULL CHECK (btrim(provider) <> ''),
    environment text NOT NULL CHECK (environment IN ('live', 'sandbox', 'benchmark', 'validation')),
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'paused', 'retired')),
    capabilities jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(capabilities) = 'object'),
    data_version text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT data_sources_identity_unique UNIQUE (source_id, environment)
);

CREATE TABLE IF NOT EXISTS app_state.sync_runs (
    sync_run_id text PRIMARY KEY,
    source_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('live', 'sandbox', 'benchmark', 'validation')),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    data_version text,
    query_reference text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT sync_runs_source_fk
        FOREIGN KEY (source_id) REFERENCES app_state.data_sources (source_id) ON DELETE RESTRICT,
    CONSTRAINT sync_runs_source_environment_fk
        FOREIGN KEY (source_id, environment)
        REFERENCES app_state.data_sources (source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT sync_runs_time_order
        CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS app_state.investigation_runs (
    investigation_run_id text PRIMARY KEY,
    source_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('live', 'sandbox', 'benchmark', 'validation')),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    requested_metric text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    data_version text,
    query_reference text,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(parameters) = 'object'),
    failure_details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(failure_details) = 'object'),
    CONSTRAINT investigation_runs_source_fk
        FOREIGN KEY (source_id) REFERENCES app_state.data_sources (source_id) ON DELETE RESTRICT,
    CONSTRAINT investigation_runs_source_environment_fk
        FOREIGN KEY (source_id, environment)
        REFERENCES app_state.data_sources (source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT investigation_runs_time_order
        CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS app_state.tool_calls (
    tool_call_id text PRIMARY KEY,
    investigation_run_id text NOT NULL,
    source_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('live', 'sandbox', 'benchmark', 'validation')),
    tool_name text NOT NULL CHECK (btrim(tool_name) <> ''),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    arguments jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(arguments) = 'object'),
    dimensions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(dimensions) = 'object'),
    filters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(filters) = 'object'),
    data_version text,
    query_reference text,
    result_reference text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT tool_calls_run_fk
        FOREIGN KEY (investigation_run_id) REFERENCES app_state.investigation_runs (investigation_run_id) ON DELETE RESTRICT,
    CONSTRAINT tool_calls_source_fk
        FOREIGN KEY (source_id) REFERENCES app_state.data_sources (source_id) ON DELETE RESTRICT,
    CONSTRAINT tool_calls_source_environment_fk
        FOREIGN KEY (source_id, environment)
        REFERENCES app_state.data_sources (source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT tool_calls_run_call_unique UNIQUE (tool_call_id, investigation_run_id),
    CONSTRAINT tool_calls_time_order
        CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS app_state.observations (
    observation_id text PRIMARY KEY,
    investigation_run_id text NOT NULL,
    tool_call_id text NOT NULL,
    source_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('live', 'sandbox', 'benchmark', 'validation')),
    metric text NOT NULL CHECK (btrim(metric) <> ''),
    status text NOT NULL CHECK (status IN ('normal', 'anomalous', 'inconclusive', 'insufficient_evidence', 'failed')),
    source_status text NOT NULL CHECK (btrim(source_status) <> ''),
    current_period_start date NOT NULL,
    current_period_end date NOT NULL,
    baseline_period_start date NOT NULL,
    baseline_period_end date NOT NULL,
    filters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(filters) = 'object'),
    group_by jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(group_by) = 'array'),
    dimensions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(dimensions) = 'object'),
    current_value numeric,
    baseline_value numeric,
    relative_change numeric,
    unit text NOT NULL CHECK (btrim(unit) <> ''),
    sample_size numeric,
    data_version text,
    query_reference text NOT NULL CHECK (btrim(query_reference) <> ''),
    error_code text,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT observations_run_fk
        FOREIGN KEY (investigation_run_id) REFERENCES app_state.investigation_runs (investigation_run_id) ON DELETE RESTRICT,
    CONSTRAINT observations_tool_fk
        FOREIGN KEY (tool_call_id, investigation_run_id)
        REFERENCES app_state.tool_calls (tool_call_id, investigation_run_id) ON DELETE RESTRICT,
    CONSTRAINT observations_source_fk
        FOREIGN KEY (source_id) REFERENCES app_state.data_sources (source_id) ON DELETE RESTRICT,
    CONSTRAINT observations_source_environment_fk
        FOREIGN KEY (source_id, environment)
        REFERENCES app_state.data_sources (source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT observations_period_order
        CHECK (current_period_end >= current_period_start AND baseline_period_end >= baseline_period_start),
    CONSTRAINT observations_tool_unique UNIQUE (observation_id, investigation_run_id)
);

CREATE TABLE IF NOT EXISTS app_state.evidence (
    evidence_id text PRIMARY KEY,
    investigation_run_id text NOT NULL,
    observation_id text NOT NULL,
    source_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('live', 'sandbox', 'benchmark', 'validation')),
    role text NOT NULL CHECK (role IN ('supporting', 'negative_control', 'limitation')),
    observation_status text NOT NULL CHECK (observation_status IN ('normal', 'anomalous', 'inconclusive', 'insufficient_evidence', 'failed')),
    metric text NOT NULL CHECK (btrim(metric) <> ''),
    dimensions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(dimensions) = 'object'),
    filters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(filters) = 'object'),
    query_reference text NOT NULL CHECK (btrim(query_reference) <> ''),
    data_version text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_observation_fk
        FOREIGN KEY (observation_id, investigation_run_id)
        REFERENCES app_state.observations (observation_id, investigation_run_id) ON DELETE RESTRICT,
    CONSTRAINT evidence_source_fk
        FOREIGN KEY (source_id) REFERENCES app_state.data_sources (source_id) ON DELETE RESTRICT,
    CONSTRAINT evidence_source_environment_fk
        FOREIGN KEY (source_id, environment)
        REFERENCES app_state.data_sources (source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT evidence_run_unique UNIQUE (evidence_id, investigation_run_id)
);

CREATE TABLE IF NOT EXISTS app_state.diagnoses (
    diagnosis_id text PRIMARY KEY,
    investigation_run_id text NOT NULL,
    source_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('live', 'sandbox', 'benchmark', 'validation')),
    status text NOT NULL CHECK (status IN ('diagnosed', 'no_material_anomaly', 'insufficient_evidence', 'budget_exhausted', 'tool_failure')),
    target_metric text NOT NULL CHECK (btrim(target_metric) <> ''),
    primary_driver text,
    affected_scope jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(affected_scope) = 'object'),
    change jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(change) = 'object'),
    evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(evidence_ids) = 'array'),
    confidence numeric,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(limitations) = 'array'),
    data_version text,
    query_reference text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT diagnoses_run_fk
        FOREIGN KEY (investigation_run_id) REFERENCES app_state.investigation_runs (investigation_run_id) ON DELETE RESTRICT,
    CONSTRAINT diagnoses_source_fk
        FOREIGN KEY (source_id) REFERENCES app_state.data_sources (source_id) ON DELETE RESTRICT,
    CONSTRAINT diagnoses_source_environment_fk
        FOREIGN KEY (source_id, environment)
        REFERENCES app_state.data_sources (source_id, environment) ON DELETE RESTRICT,
    CONSTRAINT diagnoses_run_unique UNIQUE (diagnosis_id, investigation_run_id)
);

-- A normalized link preserves the many-evidence relationship while the JSONB
-- snapshot on diagnoses remains convenient for immutable API payloads.
CREATE TABLE IF NOT EXISTS app_state.diagnosis_evidence (
    diagnosis_id text NOT NULL,
    investigation_run_id text NOT NULL,
    evidence_id text NOT NULL,
    PRIMARY KEY (diagnosis_id, evidence_id),
    CONSTRAINT diagnosis_evidence_diagnosis_fk
        FOREIGN KEY (diagnosis_id, investigation_run_id)
        REFERENCES app_state.diagnoses (diagnosis_id, investigation_run_id) ON DELETE RESTRICT,
    CONSTRAINT diagnosis_evidence_evidence_fk
        FOREIGN KEY (evidence_id, investigation_run_id)
        REFERENCES app_state.evidence (evidence_id, investigation_run_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS sync_runs_source_requested_idx
    ON app_state.sync_runs (source_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS investigation_runs_source_requested_idx
    ON app_state.investigation_runs (source_id, requested_at DESC);
CREATE INDEX IF NOT EXISTS investigation_runs_status_idx
    ON app_state.investigation_runs (status, requested_at);
CREATE INDEX IF NOT EXISTS tool_calls_run_requested_idx
    ON app_state.tool_calls (investigation_run_id, requested_at);
CREATE INDEX IF NOT EXISTS observations_run_created_idx
    ON app_state.observations (investigation_run_id, created_at);
CREATE INDEX IF NOT EXISTS evidence_run_created_idx
    ON app_state.evidence (investigation_run_id, created_at);
CREATE INDEX IF NOT EXISTS diagnoses_run_created_idx
    ON app_state.diagnoses (investigation_run_id, created_at);

COMMIT;
