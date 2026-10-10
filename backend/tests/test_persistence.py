"""Hermetic tests for R2 persistence contracts and migration shape."""

from __future__ import annotations

import re
import unittest

from app.data_sources.capabilities import SourceEnvironment
from app.persistence import (
    DEFAULT_MIGRATION_NAME,
    DataSourceReference,
    InvalidRunTransitionError,
    PersistenceValidationError,
    RunState,
    RunStatus,
    available_migrations,
    load_app_state_migration,
    load_migration,
)


class RunStateTests(unittest.TestCase):
    def test_new_run_starts_queued_and_is_immutable(self) -> None:
        state = RunState.initial()

        self.assertEqual(state.status, RunStatus.QUEUED)
        self.assertFalse(state.is_terminal)
        with self.assertRaises((AttributeError, TypeError)):
            state.status = RunStatus.RUNNING  # type: ignore[misc]

    def test_legal_transitions_return_new_snapshots(self) -> None:
        queued = RunState.queued()
        running = queued.transition_to(RunStatus.RUNNING)
        succeeded = running.transition(RunStatus.SUCCEEDED)
        failed_before_start = queued.transition_to(RunStatus.FAILED)

        self.assertEqual(queued.status, RunStatus.QUEUED)
        self.assertEqual(running.status, RunStatus.RUNNING)
        self.assertEqual(succeeded.status, RunStatus.SUCCEEDED)
        self.assertEqual(failed_before_start.status, RunStatus.FAILED)
        self.assertTrue(succeeded.is_terminal)
        self.assertTrue(failed_before_start.is_terminal)

    def test_cancel_is_legal_from_queued_or_running(self) -> None:
        self.assertEqual(
            RunState.queued().advance_to(RunStatus.CANCELLED).status,
            RunStatus.CANCELLED,
        )
        self.assertEqual(
            RunState.queued()
            .transition_to(RunStatus.RUNNING)
            .transition_to(RunStatus.CANCELLED)
            .status,
            RunStatus.CANCELLED,
        )

    def test_illegal_and_terminal_transitions_fail_closed(self) -> None:
        illegal = (
            (RunStatus.QUEUED, RunStatus.SUCCEEDED),
            (RunStatus.RUNNING, RunStatus.QUEUED),
            (RunStatus.SUCCEEDED, RunStatus.RUNNING),
            (RunStatus.FAILED, RunStatus.CANCELLED),
            (RunStatus.CANCELLED, RunStatus.RUNNING),
        )
        for source, target in illegal:
            with self.subTest(source=source, target=target):
                with self.assertRaises(InvalidRunTransitionError):
                    RunState(source).transition_to(target)

        with self.assertRaises(InvalidRunTransitionError):
            RunState.queued().transition_to("running")  # type: ignore[arg-type]

    def test_invalid_status_creation_fails_closed(self) -> None:
        with self.assertRaises(PersistenceValidationError):
            RunState("queued")  # type: ignore[arg-type]

    def test_source_reference_requires_known_environment(self) -> None:
        expected = {
            SourceEnvironment.LIVE,
            SourceEnvironment.SANDBOX,
            SourceEnvironment.BENCHMARK,
            SourceEnvironment.VALIDATION,
        }
        self.assertEqual(set(SourceEnvironment), expected)
        source = DataSourceReference("shopify-dev", SourceEnvironment.SANDBOX)
        self.assertEqual(source.source_id, "shopify-dev")
        self.assertEqual(source.environment, SourceEnvironment.SANDBOX)

        with self.assertRaises(PersistenceValidationError):
            DataSourceReference("", SourceEnvironment.LIVE)
        with self.assertRaises(PersistenceValidationError):
            DataSourceReference("source", "live")  # type: ignore[arg-type]


class MigrationContractTests(unittest.TestCase):
    def test_versioned_migration_is_discoverable_and_read_only(self) -> None:
        self.assertIn(DEFAULT_MIGRATION_NAME, available_migrations())
        sql = load_app_state_migration()
        self.assertEqual(sql, load_migration(DEFAULT_MIGRATION_NAME))
        self.assertIn("CREATE SCHEMA IF NOT EXISTS app_state", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS", sql)
        self.assertIn("BEGIN;", sql)
        self.assertIn("COMMIT;", sql)

    def test_migration_contains_required_entities_and_traceability(self) -> None:
        sql = load_app_state_migration().lower()
        required_tables = {
            "data_sources",
            "sync_runs",
            "investigation_runs",
            "tool_calls",
            "observations",
            "evidence",
            "diagnoses",
        }
        for table in required_tables:
            with self.subTest(table=table):
                self.assertIn(f"app_state.{table}", sql)

        for field in (
            "source_id",
            "environment",
            "data_version",
            "query_reference",
            "dimensions",
            "filters",
            "arguments",
            "created_at",
        ):
            with self.subTest(field=field):
                self.assertIn(field, sql)

        self.assertIn("references app_state.investigation_runs", sql)
        self.assertIn("references app_state.tool_calls", sql)
        self.assertIn("references app_state.observations", sql)
        self.assertIn("references app_state.evidence", sql)
        self.assertIn("app_state.diagnosis_evidence", sql)

    def test_migration_isolated_and_contains_no_sensitive_column_names(self) -> None:
        sql = load_app_state_migration().lower()
        self.assertNotIn("warehouse.", sql)
        self.assertNotIn("olist_validation", sql)
        for forbidden in ("password", "token", "secret", "connection_url", "database_url"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sql)

    def test_provenance_migration_is_discoverable_and_scoped(self) -> None:
        migration_name = "002_enforce_investigation_provenance.sql"
        self.assertIn(migration_name, available_migrations())
        sql = load_migration(migration_name).lower()

        self.assertIn("begin;", sql)
        self.assertIn("commit;", sql)
        self.assertNotIn("warehouse.", sql)
        self.assertNotIn("olist_validation", sql)
        for forbidden in (
            "password",
            "token",
            "secret",
            "connection_url",
            "database_url",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sql)

        # The migration is deliberately constrained to app_state tables and
        # catalog inspection; it must not create or mutate unrelated objects.
        self.assertNotIn("create table", sql)
        self.assertNotIn("drop ", sql)
        self.assertNotIn("truncate ", sql)
        # ``ON DELETE RESTRICT`` is part of the intended FK definitions; only
        # reject executable DELETE statements here.
        self.assertNotIn("delete from", sql)
        self.assertIn("pg_constraint", sql)
        self.assertEqual(
            set(re.findall(r"\balter\s+table\s+([a-z_][a-z0-9_.]*)", sql)),
            {
                "app_state.investigation_runs",
                "app_state.tool_calls",
                "app_state.observations",
                "app_state.evidence",
                "app_state.diagnoses",
            },
        )

    def test_provenance_migration_adds_supporting_keys_and_triple_foreign_keys(self) -> None:
        sql = " ".join(load_migration("002_enforce_investigation_provenance.sql").lower().split())

        self.assertIn(
            "add constraint investigation_runs_provenance_unique unique "
            "(investigation_run_id, source_id, environment)",
            sql,
        )
        self.assertIn(
            "add constraint tool_calls_provenance_unique unique "
            "(tool_call_id, investigation_run_id, source_id, environment)",
            sql,
        )

        expected_triple_fks = {
            (
                "tool_calls_investigation_provenance_fk",
                "app_state.tool_calls",
            ),
            (
                "observations_investigation_provenance_fk",
                "app_state.observations",
            ),
            (
                "evidence_investigation_provenance_fk",
                "app_state.evidence",
            ),
            (
                "diagnoses_investigation_provenance_fk",
                "app_state.diagnoses",
            ),
        }
        triple = (
            "foreign key (investigation_run_id, source_id, environment) "
            "references app_state.investigation_runs "
            "(investigation_run_id, source_id, environment)"
        )
        self.assertEqual(sql.count(triple), len(expected_triple_fks))
        for constraint_name, table_name in expected_triple_fks:
            with self.subTest(constraint=constraint_name):
                self.assertIn(f"{table_name} add constraint {constraint_name}", sql)

        # Every ADD is guarded by pg_constraint lookup, making the migration
        # safely repeatable for the same schema.
        self.assertGreaterEqual(sql.count("if not exists"), 6)
        self.assertNotIn("drop constraint", sql)

    def test_source_identity_migration_is_discoverable_and_guarded(self) -> None:
        migration_name = "003_immutable_data_source_identity.sql"
        self.assertIn(migration_name, available_migrations())
        sql = " ".join(load_migration(migration_name).lower().split())

        self.assertIn("begin;", sql)
        self.assertIn("commit;", sql)
        self.assertIn(
            "create or replace function app_state.reject_data_source_identity_change()",
            sql,
        )
        self.assertIn("before update on app_state.data_sources", sql)
        self.assertIn("old.source_id is distinct from new.source_id", sql)
        self.assertIn("old.provider is distinct from new.provider", sql)
        self.assertIn("old.environment is distinct from new.environment", sql)
        self.assertIn("pg_trigger", sql)
        self.assertIn("if not exists", sql)
        self.assertNotIn("drop ", sql)

    def test_loader_rejects_path_traversal_and_non_sql_names(self) -> None:
        with self.assertRaises(Exception):
            load_migration("../warehouse/schema.sql")
        with self.assertRaises(Exception):
            load_migration("001_app_state.txt")


if __name__ == "__main__":
    unittest.main()
