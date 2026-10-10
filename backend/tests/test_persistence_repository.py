"""Hermetic contract tests for the R2-002 application-state repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import unittest

from app.analytics.models import DateRange
from app.data_sources.capabilities import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.diagnosis.models import Diagnosis, DiagnosisChange, DiagnosisStatus
from app.evidence.models import Evidence, EvidenceRole
from app.observations.models import Observation, ObservationStatus
from app.persistence import (
    ApplicationStateRepository,
    DataSourceState,
    InvalidRunTransitionError,
    PersistenceRepositoryError,
    PersistenceValidationError,
    RunStatus,
)


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.rowcount = connection.next_rowcount
        self._row = connection.next_row
        self.closed = False

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.connection.calls.append((sql, params))
        if "SELECT investigation_run_id" in sql:
            self._row = self.connection.next_row
        if self.connection.execute_error is not None:
            raise self.connection.execute_error

    def fetchone(self) -> object:
        return self._row

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.next_rowcount = 1
        self.next_row: object | None = None
        self.execute_error: Exception | None = None
        self.commit_calls = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_calls += 1


def _repository() -> tuple[ApplicationStateRepository, FakeConnection]:
    connection = FakeConnection()
    return ApplicationStateRepository(connection), connection


def _observation() -> Observation:
    return Observation(
        observation_id="obs-1",
        tool_name="query_metric",
        tool_call_id="call-1",
        metric="sales",
        current_period=DateRange(date(2026, 10, 1), date(2026, 10, 7)),
        baseline_period=DateRange(date(2026, 9, 24), date(2026, 9, 30)),
        filters={"marketplace": "US"},
        group_by=("marketplace",),
        dimensions={"marketplace": "US"},
        current_value=Decimal("80"),
        baseline_value=Decimal("100"),
        relative_change=Decimal("-0.2"),
        unit="usd",
        sample_size=Decimal("100"),
        source_status="ok",
        status=ObservationStatus.ANOMALOUS,
        query_or_result_reference="query:abc",
        created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )


def _evidence() -> Evidence:
    return Evidence(
        evidence_id="evidence:obs-1:supporting",
        observation_id="obs-1",
        role=EvidenceRole.SUPPORTING,
        tool_name="query_metric",
        tool_call_id="call-1",
        metric="sales",
        current_period=DateRange(date(2026, 10, 1), date(2026, 10, 7)),
        baseline_period=DateRange(date(2026, 9, 24), date(2026, 9, 30)),
        filters={"marketplace": "US"},
        group_by=("marketplace",),
        dimensions={"marketplace": "US"},
        current_value=Decimal("80"),
        baseline_value=Decimal("100"),
        relative_change=Decimal("-0.2"),
        unit="usd",
        sample_size=Decimal("100"),
        observation_status=ObservationStatus.ANOMALOUS,
        source_status="ok",
        query_or_result_reference="query:abc",
        created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        diagnosis_id="diagnosis-1",
        status=DiagnosisStatus.DIAGNOSED,
        target_metric="sales",
        change=DiagnosisChange(
            current_value=Decimal("80"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("-0.2"),
            unit="usd",
            evidence_id="evidence:obs-1:supporting",
        ),
        primary_driver="sales",
        affected_scope={"marketplace": "US"},
        evidence_ids=("evidence:obs-1:supporting",),
        confidence=Decimal("0.9"),
        limitations=("Data-level evidence only.",),
        created_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )


class ApplicationStateRepositoryTests(unittest.TestCase):
    def test_requires_established_connection_and_never_commits(self) -> None:
        with self.assertRaises(PersistenceValidationError):
            ApplicationStateRepository(None)

        repository, connection = _repository()
        repository.create_investigation_run(
            "run-1",
            "source-1",
            SourceEnvironment.SANDBOX,
            requested_metric="sales",
        )
        self.assertEqual(connection.commit_calls, 0)
        self.assertFalse(hasattr(repository, "database_url"))

    def test_upsert_uses_parameters_and_preserves_source_environment(self) -> None:
        repository, connection = _repository()
        descriptor = DataSourceDescriptor(
            source_id="shopify-dev",
            display_name="Shopify Dev Store",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.SANDBOX,
        )

        returned = repository.upsert_data_source(
            descriptor,
            capabilities={"sales": {"supported": True, "grain": ["date"]}},
            data_version="snapshot-1",
            state=DataSourceState.ACTIVE,
        )

        self.assertEqual(returned, descriptor)
        sql, params = connection.calls[-1]
        self.assertIn("ON CONFLICT (source_id)", sql)
        self.assertIn(
            "WHERE app_state.data_sources.provider = EXCLUDED.provider", sql
        )
        self.assertIn(
            "AND app_state.data_sources.environment = EXCLUDED.environment", sql
        )
        update_clause = sql.split("DO UPDATE SET", 1)[1].split("WHERE", 1)[0]
        self.assertNotIn("provider =", update_clause)
        self.assertNotIn("environment =", update_clause)
        self.assertIn("%s", sql)
        self.assertIn("sandbox", params)
        self.assertIn("snapshot-1", params)
        self.assertEqual(params[6], "snapshot-1")
        self.assertEqual(params[7], True)
        self.assertNotIn("shopify-dev", sql)

    def test_upsert_distinguishes_omitted_and_explicit_empty_capabilities(self) -> None:
        descriptor = DataSourceDescriptor(
            source_id="shopify-dev",
            display_name="Shopify Dev Store",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.SANDBOX,
        )

        for supplied, expected_flag in ((None, False), ({}, True)):
            with self.subTest(capabilities=supplied):
                repository, connection = _repository()
                repository.upsert_data_source(descriptor, capabilities=supplied)

                sql, params = connection.calls[-1]
                self.assertIn(
                    "capabilities = CASE WHEN %s THEN EXCLUDED.capabilities", sql
                )
                self.assertIn(
                    "ELSE app_state.data_sources.capabilities END", sql
                )
                self.assertEqual(json.loads(params[5]), {})
                self.assertIsNone(params[6])
                self.assertIs(params[7], expected_flag)
                self.assertLess(
                    sql.index("CAST(%s AS jsonb), %s)"),
                    sql.index("capabilities = CASE WHEN %s"),
                )

    def test_upsert_identity_conflict_guard_remains_parameterized(self) -> None:
        repository, connection = _repository()
        connection.next_rowcount = 0
        descriptor = DataSourceDescriptor(
            source_id="shopify-dev",
            display_name="Shopify Dev Store",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.SANDBOX,
        )

        with self.assertRaisesRegex(
            PersistenceRepositoryError,
            "Data source identity conflicts with the existing record",
        ):
            repository.upsert_data_source(descriptor)

        sql, params = connection.calls[-1]
        self.assertIn(
            "WHERE app_state.data_sources.provider = EXCLUDED.provider", sql
        )
        self.assertIn(
            "AND app_state.data_sources.environment = EXCLUDED.environment", sql
        )
        self.assertIsNone(params[6])
        self.assertIs(params[7], False)
        self.assertEqual(connection.commit_calls, 0)

    def test_upsert_rejects_source_identity_conflict(self) -> None:
        repository, connection = _repository()
        connection.next_rowcount = 0
        descriptor = DataSourceDescriptor(
            source_id="shopify-dev",
            display_name="Shopify Dev Store",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.SANDBOX,
        )

        with self.assertRaisesRegex(
            PersistenceRepositoryError,
            "Data source identity conflicts with the existing record",
        ):
            repository.upsert_data_source(descriptor)

        self.assertEqual(len(connection.calls), 1)

    def test_sensitive_keys_are_rejected_recursively_before_sql(self) -> None:
        repository, connection = _repository()
        with self.assertRaises(PersistenceValidationError):
            repository.create_investigation_run(
                "run-sensitive",
                "source-1",
                SourceEnvironment.LIVE,
                parameters={"nested": {"api_key": "redacted"}},
            )
        with self.assertRaises(PersistenceValidationError):
            repository.record_tool_call(
                "call-sensitive",
                "run-1",
                "source-1",
                SourceEnvironment.LIVE,
                "query_metric",
                arguments={"headers": {"Authorization": "redacted"}},
            )
        self.assertEqual(connection.calls, [])

    def test_create_run_is_queued_and_transition_is_conditioned_on_state(self) -> None:
        repository, connection = _repository()
        summary = repository.create_investigation_run(
            run_id="run-1",
            source_id="source-1",
            environment=SourceEnvironment.VALIDATION,
            requested_metric="sales",
            query_reference="query:run-1",
        )
        self.assertEqual(summary.status, RunStatus.QUEUED)
        self.assertEqual(summary.environment, SourceEnvironment.VALIDATION)

        self.assertEqual(
            repository.transition_investigation_run("run-1", RunStatus.RUNNING),
            RunStatus.RUNNING,
        )
        sql, params = connection.calls[-1]
        self.assertIn("AND status IN", sql)
        self.assertIn(RunStatus.QUEUED.value, params)
        self.assertNotIn("run-1", sql)

        with self.assertRaises(InvalidRunTransitionError):
            repository.transition_investigation_run("run-1", RunStatus.QUEUED)

        connection.next_rowcount = 0
        with self.assertRaises(PersistenceRepositoryError):
            repository.transition_investigation_run("run-1", RunStatus.SUCCEEDED)

    def test_queued_run_can_transition_to_failed(self) -> None:
        repository, connection = _repository()

        self.assertEqual(
            repository.transition_investigation_run("run-queued", RunStatus.FAILED),
            RunStatus.FAILED,
        )
        sql, params = connection.calls[-1]
        self.assertIn("status IN", sql)
        self.assertEqual(
            params[-3:],
            ("run-queued", RunStatus.QUEUED.value, RunStatus.RUNNING.value),
        )

    def test_failure_update_is_parameterized_and_stores_only_controlled_code(self) -> None:
        repository, connection = _repository()

        result = repository.fail_investigation_run(
            run_id="run-failure",
            failure_code="tool_timeout",
        )

        self.assertEqual(result, RunStatus.FAILED)
        sql, params = connection.calls[-1]
        self.assertIn("UPDATE app_state.investigation_runs", sql)
        self.assertIn("status IN", sql)
        self.assertIn("finished_at = now()", sql)
        self.assertNotIn("run-failure", sql)
        self.assertNotIn("tool_timeout", sql)
        self.assertEqual(params[0], RunStatus.FAILED.value)
        self.assertEqual(json.loads(params[1]), {"code": "tool_timeout"})
        self.assertEqual(params[2:], ("run-failure", "queued", "running"))
        self.assertEqual(connection.commit_calls, 0)

    def test_failure_update_fails_closed_on_zero_rows(self) -> None:
        repository, connection = _repository()
        connection.next_rowcount = 0

        with self.assertRaises(PersistenceRepositoryError):
            repository.fail_investigation_run(
                run_id="run-terminal",
                failure_code="runtime_error",
            )

        self.assertEqual(connection.commit_calls, 0)

    def test_invalid_failure_code_is_rejected_before_sql(self) -> None:
        repository, connection = _repository()

        for invalid_code in (
            "",
            "RuntimeError",
            "runtime error",
            "runtime.error",
            "runtime/error",
            "a" * 65,
            "异常",
        ):
            with self.subTest(invalid_code=invalid_code):
                with self.assertRaises(PersistenceValidationError):
                    repository.fail_investigation_run(
                        run_id="run-invalid",
                        failure_code=invalid_code,
                    )

        self.assertEqual(connection.calls, [])

    def test_tool_call_carries_source_environment_and_rejects_non_enum_status(self) -> None:
        repository, connection = _repository()
        repository.record_tool_call(
            "call-1",
            "run-1",
            "source-1",
            SourceEnvironment.BENCHMARK,
            "query_metric",
            status=RunStatus.SUCCEEDED,
            arguments={"metric": "sales"},
            dimensions={"marketplace": "US"},
            filters={"marketplace": "US"},
            data_version="benchmark-1",
            query_reference="query:call-1",
        )
        sql, params = connection.calls[-1]
        self.assertIn("source_id", sql)
        self.assertIn("benchmark", params)
        self.assertIn("query:call-1", params)
        with self.assertRaises(PersistenceValidationError):
            repository.record_tool_call(
                "call-invalid",
                "run-1",
                "source-1",
                "benchmark",  # type: ignore[arg-type]
                "query_metric",
            )

    def test_observation_evidence_diagnosis_and_links_share_run_in_order(self) -> None:
        repository, connection = _repository()
        observation = _observation()
        evidence = _evidence()
        diagnosis = _diagnosis()

        repository.record_tool_call(
            "call-1",
            "run-1",
            "source-1",
            SourceEnvironment.VALIDATION,
            "query_metric",
            query_reference="query:call-1",
        )
        repository.record_observation(
            observation,
            "run-1",
            "source-1",
            SourceEnvironment.VALIDATION,
            data_version="validation-1",
        )
        repository.record_evidence(
            evidence,
            "run-1",
            "source-1",
            SourceEnvironment.VALIDATION,
            data_version="validation-1",
        )
        repository.record_diagnosis(
            diagnosis,
            "run-1",
            "source-1",
            SourceEnvironment.VALIDATION,
            data_version="validation-1",
            query_reference="query:diagnosis-1",
        )

        self.assertEqual(len(connection.calls), 5)
        sql_names = [
            "tool_calls",
            "observations",
            "evidence",
            "diagnoses",
            "diagnosis_evidence",
        ]
        for (sql, params), table in zip(connection.calls, sql_names):
            self.assertIn(table, sql)
            self.assertIn("run-1", params)
            if table != "diagnosis_evidence":
                self.assertIn("source-1", params)
                self.assertIn("validation", params)
        self.assertEqual(connection.calls[-1][1][-3:], ("diagnosis-1", "run-1", "evidence:obs-1:supporting"))

    def test_observation_persistence_discards_error_text_and_sanitizes_code(self) -> None:
        repository, connection = _repository()
        failed = replace(
            _observation(),
            status=ObservationStatus.FAILED,
            source_status="failed",
            current_value=None,
            baseline_value=None,
            relative_change=None,
            sample_size=None,
            error_code="DatabaseError: password=hunter2",
            error_message="postgres://user:secret@example.invalid/db",
        )

        repository.record_observation(
            failed,
            "run-1",
            "source-1",
            SourceEnvironment.VALIDATION,
        )

        params = connection.calls[-1][1]
        self.assertEqual(params[-3], "tool_error")
        self.assertIsNone(params[-2])
        self.assertNotIn("hunter2", params)
        self.assertNotIn("secret@example", params)

    def test_evidence_default_payload_discards_error_text_and_sanitizes_code(self) -> None:
        repository, connection = _repository()
        failed = replace(
            _evidence(),
            evidence_id="evidence:obs-1:limitation",
            role=EvidenceRole.LIMITATION,
            observation_status=ObservationStatus.FAILED,
            source_status="failed",
            current_value=None,
            baseline_value=None,
            relative_change=None,
            sample_size=None,
            error_code="DatabaseError: password=hunter2",
            error_message="postgres://user:secret@example.invalid/db",
        )

        repository.record_evidence(
            failed,
            "run-1",
            "source-1",
            SourceEnvironment.VALIDATION,
        )

        payload = json.loads(connection.calls[-1][1][-1])
        self.assertEqual(payload["error_code"], "tool_error")
        self.assertIsNone(payload["error_message"])
        self.assertNotIn("hunter2", connection.calls[-1][1][-1])
        self.assertNotIn("secret@example", connection.calls[-1][1][-1])

    def test_evidence_payload_rejects_nested_error_message_before_sql(self) -> None:
        repository, connection = _repository()

        for unsafe_payload in (
            {"error_message": "password=hunter2"},
            {"nested": [{"ERROR_MESSAGE": "postgres://user:secret@host/db"}]},
            {"nested": {"errorMessage": "untrusted service response"}},
        ):
            with self.subTest(payload=unsafe_payload):
                with self.assertRaisesRegex(
                    PersistenceValidationError,
                    "must not include 'error_message'",
                ):
                    repository.record_evidence(
                        _evidence(),
                        "run-1",
                        "source-1",
                        SourceEnvironment.VALIDATION,
                        payload=unsafe_payload,
                    )

        self.assertEqual(connection.calls, [])

    def test_evidence_payload_sanitizes_nested_error_codes(self) -> None:
        repository, connection = _repository()

        repository.record_evidence(
            _evidence(),
            "run-1",
            "source-1",
            SourceEnvironment.VALIDATION,
            payload={"details": [{"error_code": "database password=hunter2"}]},
        )

        payload_json = connection.calls[-1][1][-1]
        payload = json.loads(payload_json)
        self.assertEqual(payload["details"][0]["error_code"], "tool_error")
        self.assertNotIn("hunter2", payload_json)

    def test_payload_must_be_json_serializable(self) -> None:
        repository, connection = _repository()
        with self.assertRaises(PersistenceValidationError):
            repository.record_evidence(
                _evidence(),
                "run-1",
                "source-1",
                SourceEnvironment.VALIDATION,
                payload={"not_json": object()},
            )
        self.assertEqual(connection.calls, [])

    def test_database_errors_propagate_without_repository_wrapping_or_commit(self) -> None:
        repository, connection = _repository()
        connection.execute_error = RuntimeError("database unavailable")
        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            repository.create_investigation_run(
                "run-db-error",
                "source-1",
                SourceEnvironment.LIVE,
            )
        self.assertEqual(connection.commit_calls, 0)

    def test_reads_minimal_summary_with_parameterized_run_id(self) -> None:
        repository, connection = _repository()
        requested_at = datetime(2026, 10, 9, tzinfo=timezone.utc)
        connection.next_row = (
            "run-1",
            "source-1",
            "sandbox",
            "succeeded",
            "sales",
            "version-1",
            "query:run-1",
            requested_at,
            requested_at,
            requested_at,
        )
        summary = repository.get_investigation_run("run-1")
        assert summary is not None
        self.assertEqual(summary.run_id, "run-1")
        self.assertEqual(summary.status, RunStatus.SUCCEEDED)
        self.assertEqual(summary.environment, SourceEnvironment.SANDBOX)
        self.assertEqual(summary.query_reference, "query:run-1")
        self.assertEqual(connection.calls[-1][1], ("run-1",))
        connection.next_row = None
        self.assertIsNone(repository.get_investigation_run("missing"))


if __name__ == "__main__":
    unittest.main()
