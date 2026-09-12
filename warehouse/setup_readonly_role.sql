-- =============================================================================
-- MetricSleuth: PostgreSQL Readonly Role Setup Script
--
-- This script idempotently creates/updates the `metricsleuth_readonly` role,
-- enforces minimal privileges on warehouse tables, and sets safe default
-- configuration parameters scoped to the `metricsleuth` database.
--
-- Password must be provided via the `METRICSLEUTH_READONLY_PASSWORD`
-- environment variable.
-- =============================================================================

\set ON_ERROR_STOP on
\getenv readonly_pwd METRICSLEUTH_READONLY_PASSWORD

\if :{?readonly_pwd}
    SELECT length(btrim(:'readonly_pwd')) > 0 AS readonly_pwd_valid \gset
    \if :readonly_pwd_valid
    \else
        \warn 'ERROR: Environment variable METRICSLEUTH_READONLY_PASSWORD must be non-empty.'
        SELECT 1/0;
    \endif
\else
    \warn 'ERROR: Environment variable METRICSLEUTH_READONLY_PASSWORD is required.'
    SELECT 1/0;
\endif

-- 1. Idempotently create role if it does not exist
DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metricsleuth_readonly') THEN
        CREATE ROLE metricsleuth_readonly;
    END IF;
END
$do$;

-- 2. Enforce strict role attributes and set password
ALTER ROLE metricsleuth_readonly WITH
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS
    NOINHERIT
    CONNECTION LIMIT 5
    PASSWORD :'readonly_pwd';

-- 3. Reset existing permissions on warehouse schema
REVOKE ALL ON ALL TABLES IN SCHEMA warehouse FROM metricsleuth_readonly;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA warehouse FROM metricsleuth_readonly;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA warehouse FROM metricsleuth_readonly;
REVOKE ALL ON SCHEMA warehouse FROM metricsleuth_readonly;

-- 4. Grant explicit minimal read permissions (only the 2 warehouse tables)
GRANT USAGE ON SCHEMA warehouse TO metricsleuth_readonly;
GRANT SELECT ON warehouse.dim_products TO metricsleuth_readonly;
GRANT SELECT ON warehouse.fact_daily_performance TO metricsleuth_readonly;

-- 5. Set session default parameters scoped to metricsleuth database
ALTER ROLE metricsleuth_readonly IN DATABASE metricsleuth SET default_transaction_read_only = on;
ALTER ROLE metricsleuth_readonly IN DATABASE metricsleuth SET statement_timeout = '1000ms';
ALTER ROLE metricsleuth_readonly IN DATABASE metricsleuth SET search_path = pg_catalog;
