"""Opt-in acceptance tests against an isolated local PostgreSQL database.

Set only ``METRICSLEUTH_TEST_DATABASE_URL`` to a dedicated local database named
``metricsleuth_r2_acceptance``.  These tests never inspect ``.env`` or the
application/production database settings, and never invoke a model.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from decimal import Decimal
import os
import subprocess
import sys
from pathlib import Path
import unittest
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from app.agent_runtime import (
    EvidenceDrivenRunSummary,
    InvestigationRunSummary,
    InvestigationToolTraceEntry,
)
from app.analytics.models import DateRange
from app.data_sources.capabilities import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.diagnosis import (
    Diagnosis,
    DiagnosisChange,
    DiagnosisComposition,
    DiagnosisStatus,
)
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.observations import Observation, ObservationStatus
from app.persistence import (
    ApplicationStateRepository,
    InvestigationRunHandle,
    InvestigationTaskExecutionService,
    InvestigationTaskRequest,
    InvestigationTransactionCoordinator,
    PersistenceRepositoryError,
    RunState,
    RunStatus,
)
from app.persistence.worker import InvestigationWorker


_DATABASE_ENV = "METRICSLEUTH_TEST_DATABASE_URL"
_EXPECTED_DATABASE = "metricsleuth_r2_acceptance"
_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
_NOW = datetime.datetime(2026, 10, 10, 12, tzinfo=datetime.timezone.utc)
_CURRENT = DateRange(datetime.date(2026, 10, 10), datetime.date(2026, 10, 10))
_BASELINE = DateRange(datetime.date(2026, 10, 3), datetime.date(2026, 10, 9))


class _SafeConnectionError(RuntimeError):
    """Connection failure with no driver message or connection details."""


def _safe_local_acceptance_url(value: str) -> bool:
    """Fail closed unless a URL names the explicitly dedicated local database."""

    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        database = unquote(parsed.path.lstrip("/"))
        return (
            parsed.scheme in {"postgres", "postgresql"}
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and database == _EXPECTED_DATABASE
            and not parsed.fragment
            and not ({"host", "hostaddr", "dbname", "service"} & query.keys())
        )
    except (ValueError, UnicodeError):
        return False


def _new_id(kind: str) -> str:
    return f"{kind}-{uuid4()}"


class PostgresPersistenceAcceptanceTests(unittest.TestCase):
    """Real SQL acceptance; skipped unless a dedicated local DB is configured."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        database_url = os.environ.get(_DATABASE_ENV)
        if not database_url:
            raise unittest.SkipTest(
                f"{_DATABASE_ENV} is not configured; PostgreSQL acceptance was not run."
            )
        if not _safe_local_acceptance_url(database_url):
            raise RuntimeError(
                f"{_DATABASE_ENV} must target localhost/{_EXPECTED_DATABASE}; no connection was attempted."
            )

        try:
            import psycopg
        except ImportError:
            raise RuntimeError(
                "The psycopg driver is required when the acceptance database URL is configured."
            ) from None

        cls._psycopg = psycopg
        cls._database_url = database_url
        try:
            connection = cls._connect()
        except _SafeConnectionError:
            raise RuntimeError(
                "The configured isolated PostgreSQL acceptance database is unavailable; connection details suppressed."
            ) from None
        try:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database()")
                    actual_database = cursor.fetchone()[0]
                if actual_database != _EXPECTED_DATABASE:
                    raise RuntimeError(
                        "The configured connection did not reach the dedicated acceptance database."
                    )

                migration_scripts = tuple(sorted(_MIGRATIONS.glob("*.sql")))
                if not migration_scripts:
                    raise RuntimeError("No application-state migrations were found.")
                # Each migration owns its BEGIN/COMMIT. Run the full set twice
                # to prove fresh install and idempotent re-application.
                for _ in range(2):
                    for migration in migration_scripts:
                        connection.execute(migration.read_text(encoding="utf-8"))
            finally:
                connection.close()
        except unittest.SkipTest:
            raise
        except Exception:
            # A configured but broken migration is a failure, not a skip.
            # Suppress the driver exception because it may include connection
            # or server details.
            raise RuntimeError(
                "PostgreSQL acceptance migrations failed; database diagnostics suppressed."
            ) from None

    @classmethod
    def _connect(cls):
        try:
            return cls._psycopg.connect(cls._database_url, autocommit=True)
        except Exception:
            raise _SafeConnectionError(
                "Could not connect to the isolated PostgreSQL acceptance database."
            ) from None

    @classmethod
    def _transaction_connection(cls):
        """Use real transactions for coordinator commit and rollback checks."""

        connection = cls._connect()
        connection.autocommit = False
        return connection

    def setUp(self) -> None:
        self.source_id = _new_id("source")
        self.descriptor = DataSourceDescriptor(
            source_id=self.source_id,
            display_name="MetricSleuth isolated PostgreSQL acceptance source",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.VALIDATION,
        )
        self.data_version = _new_id("data-version")
        self.run_id = _new_id("run")
        self.query_reference = _new_id("controlled-select")
        self.coordinator = InvestigationTransactionCoordinator(self._transaction_connection)

    def _request(self, run_id: str | None = None) -> InvestigationTaskRequest:
        return InvestigationTaskRequest(
            run_id=run_id or self.run_id,
            descriptor=self.descriptor,
            requested_metric="sales",
            data_version=self.data_version,
            parameters={"validation": True},
            query_reference=self.query_reference,
        )

    def _controlled_summary(self, request, *, diagnosis_id: str | None = None):
        """Run a real parameterized SELECT and build facts from its result."""

        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT %s::numeric AS current_value, %s::numeric AS baseline_value",
                (80, 100),
            ).fetchone()
        finally:
            connection.close()
        current_value = Decimal(row[0])
        baseline_value = Decimal(row[1])
        relative_change = (current_value - baseline_value) / baseline_value

        call_id = _new_id("tool-call")
        observation_id = _new_id("observation")
        observation = Observation(
            observation_id=observation_id,
            tool_name="query_metric",
            tool_call_id=call_id,
            metric=request.requested_metric,
            current_period=_CURRENT,
            baseline_period=_BASELINE,
            filters={},
            group_by=("marketplace",),
            dimensions={"marketplace": "acceptance-fixture"},
            current_value=current_value,
            baseline_value=baseline_value,
            relative_change=relative_change,
            unit="usd",
            sample_size=Decimal("100"),
            source_status="ok",
            status=ObservationStatus.ANOMALOUS,
            query_or_result_reference=request.query_reference,
            created_at=_NOW,
        )
        evidence = promote_observation_to_evidence(
            observation,
            role=EvidenceRole.SUPPORTING,
        )
        diagnosis = Diagnosis(
            diagnosis_id=diagnosis_id or _new_id("diagnosis"),
            status=DiagnosisStatus.DIAGNOSED,
            target_metric=request.requested_metric,
            change=DiagnosisChange(
                current_value=current_value,
                baseline_value=baseline_value,
                relative_change=relative_change,
                unit="usd",
                evidence_id=evidence.evidence_id,
            ),
            primary_driver=request.requested_metric,
            affected_scope={"marketplace": "acceptance-fixture"},
            evidence_ids=(evidence.evidence_id,),
            confidence=Decimal("0.9"),
            limitations=("Controlled persistence acceptance data only.",),
            created_at=_NOW,
        )
        trace = InvestigationToolTraceEntry(
            tool_call_id=call_id,
            tool_name="query_metric",
            arguments={"metric": request.requested_metric, "query_reference": request.query_reference},
            observation_ids=(observation_id,),
        )
        investigation = InvestigationRunSummary(
            final_output="Controlled PostgreSQL persistence acceptance.",
            tool_calls_count=1,
            max_tool_calls=1,
            tools_used=("query_metric",),
            tool_call_ids=(call_id,),
            observation_ids=(observation_id,),
            observation_count=1,
            tool_trace=(trace,),
            trace_sequence=(),
            turns_count=1,
            max_turns=1,
        )
        return EvidenceDrivenRunSummary(
            investigation=investigation,
            composition=DiagnosisComposition(
                evidence=(evidence,),
                diagnosis=diagnosis,
            ),
            observation_catalog=(observation,),
        )

    def _read_run_and_counts(self, run_id: str):
        """Read run and its persisted facts from a fresh connection."""

        connection = self._connect()
        try:
            repository = ApplicationStateRepository(connection)
            run = repository.get_investigation_run(run_id=run_id)
            with connection.cursor() as cursor:
                counts = {}
                for table in (
                    "tool_calls",
                    "observations",
                    "evidence",
                    "diagnoses",
                    "diagnosis_evidence",
                ):
                    cursor.execute(
                        f"SELECT count(*) FROM app_state.{table} WHERE investigation_run_id = %s",
                        (run_id,),
                    )
                    counts[table] = cursor.fetchone()[0]
            return run, counts
        finally:
            connection.close()

    def test_controlled_runner_persists_complete_run_and_survives_reconnect(self) -> None:
        runner = self._controlled_summary
        service = InvestigationTaskExecutionService(self.coordinator, runner)
        summary = service.execute(self._request())

        run, counts = self._read_run_and_counts(self.run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertEqual(run.source_id, self.source_id)
        self.assertEqual(run.environment, SourceEnvironment.VALIDATION)
        self.assertEqual(run.data_version, self.data_version)
        self.assertEqual(run.query_reference, self.query_reference)
        self.assertEqual(
            counts,
            {
                "tool_calls": 1,
                "observations": 1,
                "evidence": 1,
                "diagnoses": 1,
                "diagnosis_evidence": 1,
            },
        )
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT query_reference, current_value, baseline_value "
                    "FROM app_state.observations WHERE investigation_run_id = %s",
                    (self.run_id,),
                )
                observation_row = cursor.fetchone()
                cursor.execute(
                    "SELECT query_reference, data_version FROM app_state.diagnoses "
                    "WHERE investigation_run_id = %s",
                    (self.run_id,),
                )
                diagnosis_row = cursor.fetchone()
            self.assertEqual(observation_row, (self.query_reference, Decimal("80"), Decimal("100")))
            self.assertEqual(diagnosis_row, (self.query_reference, self.data_version))
        finally:
            connection.close()
        self.assertEqual(len(summary.observation_catalog), 1)

    def test_observation_free_text_error_is_not_persisted(self) -> None:
        request = self._request()
        summary = self._controlled_summary(request)
        service = InvestigationTaskExecutionService(
            self.coordinator,
            lambda _request: summary,
        )
        service.execute(request)

        source_observation = summary.observation_catalog[0]
        tool_call_id = _new_id("error-tool-call")
        raw_error = f"private response detail {uuid4()}"
        error_observation = replace(
            source_observation,
            observation_id=_new_id("error-observation"),
            tool_call_id=tool_call_id,
            current_value=None,
            baseline_value=None,
            relative_change=None,
            sample_size=None,
            source_status="failed",
            status=ObservationStatus.FAILED,
            query_or_result_reference=_new_id("error-query-ref"),
            error_code=f"provider failure: {raw_error}",
            error_message=raw_error,
        )

        connection = self._connect()
        try:
            repository = ApplicationStateRepository(connection)
            repository.record_tool_call(
                tool_call_id,
                self.run_id,
                self.source_id,
                self.descriptor.environment,
                "query_metric",
                status=RunStatus.FAILED,
                data_version=self.data_version,
                query_reference=error_observation.query_or_result_reference,
            )
            repository.record_observation(
                error_observation,
                self.run_id,
                self.source_id,
                self.descriptor.environment,
                data_version=self.data_version,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT error_code, error_message FROM app_state.observations "
                    "WHERE observation_id = %s",
                    (error_observation.observation_id,),
                )
                persisted_error = cursor.fetchone()
        finally:
            connection.close()

        self.assertEqual(persisted_error, ("tool_error", None))
        self.assertNotIn(raw_error, repr(persisted_error))

    def test_runner_failure_persists_only_safe_code(self) -> None:
        raw_exception_text = f"sensitive-marker-{uuid4()}"

        def failing_runner(_request):
            raise RuntimeError(raw_exception_text)

        service = InvestigationTaskExecutionService(self.coordinator, failing_runner)
        try:
            service.execute(self._request(), failure_code="controlled_runner_failure")
        except RuntimeError as exc:
            self.assertEqual(str(exc), raw_exception_text)
        else:
            self.fail("The controlled runner exception should propagate to its caller.")

        run, counts = self._read_run_and_counts(self.run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(counts["diagnoses"], 0)
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT failure_details FROM app_state.investigation_runs "
                    "WHERE investigation_run_id = %s",
                    (self.run_id,),
                )
                failure_details = cursor.fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(failure_details, {"code": "controlled_runner_failure"})
        self.assertNotIn(raw_exception_text, repr(failure_details))

    def test_queued_to_failed_is_allowed_by_domain_and_postgresql(self) -> None:
        self.assertTrue(RunState.queued().can_transition_to(RunStatus.FAILED))
        self.assertEqual(
            RunState.queued().transition_to(RunStatus.FAILED).status,
            RunStatus.FAILED,
        )

        connection = self._connect()
        try:
            repository = ApplicationStateRepository(connection)
            repository.upsert_data_source(self.descriptor, data_version=self.data_version)
            repository.create_investigation_run(
                run_id=self.run_id,
                source_id=self.source_id,
                environment=self.descriptor.environment,
                requested_metric="sales",
                data_version=self.data_version,
                query_reference=self.query_reference,
            )
            repository.fail_investigation_run(
                run_id=self.run_id,
                failure_code="queue_validation_failed",
            )
        finally:
            connection.close()
        run, _ = self._read_run_and_counts(self.run_id)
        self.assertEqual(run.status, RunStatus.FAILED)

    def test_source_identity_conflict_is_rejected_by_repository_and_trigger(self) -> None:
        connection = self._connect()
        try:
            repository = ApplicationStateRepository(connection)
            repository.upsert_data_source(self.descriptor, data_version=self.data_version)
        finally:
            connection.close()

        changed_provider = DataSourceDescriptor(
            source_id=self.source_id,
            display_name="same source id, changed provider",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.VALIDATION,
        )
        connection = self._connect()
        try:
            repository = ApplicationStateRepository(connection)
            with self.assertRaises(PersistenceRepositoryError):
                repository.upsert_data_source(changed_provider)
        finally:
            connection.close()

        changed_environment = DataSourceDescriptor(
            source_id=self.source_id,
            display_name="same source id, changed environment",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.SANDBOX,
        )
        connection = self._connect()
        try:
            with self.assertRaises(PersistenceRepositoryError):
                ApplicationStateRepository(connection).upsert_data_source(changed_environment)
        finally:
            connection.close()

        # There is deliberately no run referencing this source. The database
        # trigger itself must still protect provider and environment identity.
        for column, changed_value in (
            ("source_id", _new_id("changed-source")),
            ("provider", "shopify"),
            ("environment", "sandbox"),
        ):
            connection = self._connect()
            try:
                with self.assertRaises(self._psycopg.IntegrityError):
                    connection.execute(
                        f"UPDATE app_state.data_sources SET {column} = %s WHERE source_id = %s",
                        (changed_value, self.source_id),
                    )
            finally:
                connection.close()

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT provider, environment FROM app_state.data_sources WHERE source_id = %s",
                    (self.source_id,),
                )
                self.assertEqual(cursor.fetchone(), ("postgresql", "validation"))
        finally:
            connection.close()

        # The immutable identity still permits ordinary metadata refreshes.
        refreshed_descriptor = DataSourceDescriptor(
            source_id=self.source_id,
            display_name="Refreshed validation source label",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.VALIDATION,
        )
        refreshed_version = _new_id("metadata-version")
        connection = self._connect()
        try:
            ApplicationStateRepository(connection).upsert_data_source(
                refreshed_descriptor,
                data_version=refreshed_version,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT source_id, provider, environment, display_name, data_version "
                    "FROM app_state.data_sources WHERE source_id = %s",
                    (self.source_id,),
                )
                self.assertEqual(
                    cursor.fetchone(),
                    (
                        self.source_id,
                        "postgresql",
                        "validation",
                        "Refreshed validation source label",
                        refreshed_version,
                    ),
                )
        finally:
            connection.close()

    def test_cross_run_source_and_environment_provenance_is_rejected(self) -> None:
        other_descriptor = DataSourceDescriptor(
            source_id=_new_id("source"),
            display_name="Second isolated validation source",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.SANDBOX,
        )
        other_run_id = _new_id("run")
        handle_one = self.coordinator.start(
            self.descriptor,
            run_id=self.run_id,
            requested_metric="sales",
            data_version=self.data_version,
        )
        handle_two = self.coordinator.start(
            other_descriptor,
            run_id=other_run_id,
            requested_metric="sales",
            data_version=_new_id("data-version"),
        )
        self.assertIsInstance(handle_one, InvestigationRunHandle)
        self.assertIsInstance(handle_two, InvestigationRunHandle)

        connection = self._connect()
        try:
            repository = ApplicationStateRepository(connection)
            with self.assertRaises(self._psycopg.IntegrityError):
                repository.record_tool_call(
                    _new_id("tool-call"),
                    self.run_id,
                    other_descriptor.source_id,
                    other_descriptor.environment,
                    "query_metric",
                    status=RunStatus.SUCCEEDED,
                    data_version=self.data_version,
                )
        finally:
            connection.close()

        run_one, counts_one = self._read_run_and_counts(self.run_id)
        run_two, counts_two = self._read_run_and_counts(other_run_id)
        self.assertEqual(run_one.status, RunStatus.RUNNING)
        self.assertEqual(run_two.status, RunStatus.RUNNING)
        self.assertEqual(counts_one["tool_calls"], 0)
        self.assertEqual(counts_two["tool_calls"], 0)

    def test_complete_transaction_rolls_back_facts_after_sql_conflict(self) -> None:
        first_request = self._request()
        first_summary = self._controlled_summary(first_request)
        first_service = InvestigationTaskExecutionService(
            self.coordinator,
            lambda _request: first_summary,
        )
        first_service.execute(first_request)
        reused_diagnosis_id = first_summary.composition.diagnosis.diagnosis_id

        second_run_id = _new_id("run")
        second_request = self._request(second_run_id)
        second_handle = self.coordinator.start(
            self.descriptor,
            run_id=second_run_id,
            requested_metric="sales",
            data_version=self.data_version,
            query_reference=self.query_reference,
        )
        second_summary = self._controlled_summary(
            second_request,
            diagnosis_id=reused_diagnosis_id,
        )

        with self.assertRaises(self._psycopg.IntegrityError):
            self.coordinator.complete(second_handle, second_summary)

        # A new connection proves facts written before the duplicate diagnosis
        # failure were rolled back together and the run stayed running.
        run, counts = self._read_run_and_counts(second_run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run.status, RunStatus.RUNNING)
        self.assertEqual(
            counts,
            {
                "tool_calls": 0,
                "observations": 0,
                "evidence": 0,
                "diagnoses": 0,
                "diagnosis_evidence": 0,
            },
        )

    def test_checkpoint_replay_rejects_conflicting_facts_and_terminal_writes(self) -> None:
        request = self._request()
        summary = self._controlled_summary(request)
        handle = self.coordinator.start(
            self.descriptor, run_id=self.run_id, requested_metric="sales",
            data_version=self.data_version,
        )
        trace = summary.investigation.tool_trace[0]
        observations = summary.observation_catalog
        self.coordinator.checkpoint(handle, trace, observations)
        self.coordinator.checkpoint(handle, trace, observations)
        changed = replace(observations[0], current_value=Decimal("70"))
        with self.assertRaises(PersistenceRepositoryError):
            self.coordinator.checkpoint(handle, trace, (changed,))
        changed_trace = replace(trace, arguments={"metric": "orders"})
        with self.assertRaises(PersistenceRepositoryError):
            self.coordinator.checkpoint(handle, changed_trace, observations)
        # A new tool insert followed by a conflicting Observation ID must
        # roll back the tool insert as part of the same step transaction.
        extra_trace = replace(trace, tool_call_id=_new_id("conflicting-call"))
        reused_observation = replace(observations[0], tool_call_id=extra_trace.tool_call_id)
        with self.assertRaises(PersistenceRepositoryError):
            self.coordinator.checkpoint(handle, extra_trace, (reused_observation,))
        wrong_version = replace(handle, data_version="different-validation-version")
        with self.assertRaises(PersistenceRepositoryError):
            self.coordinator.checkpoint(wrong_version, trace, observations)
        self.coordinator.complete(
            handle, summary, query_reference=self.query_reference, checkpointed=True,
        )
        run, counts = self._read_run_and_counts(self.run_id)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertEqual(counts["tool_calls"], 1)
        self.assertEqual(counts["observations"], 1)
        self.assertEqual(counts["diagnoses"], 1)
        with self.assertRaises(PersistenceRepositoryError):
            self.coordinator.checkpoint(handle, trace, observations)

    def test_final_summary_cannot_omit_checkpointed_steps(self) -> None:
        request = self._request()
        summary = self._controlled_summary(request)
        handle = self.coordinator.start(
            self.descriptor, run_id=self.run_id, requested_metric="sales",
            data_version=self.data_version,
        )
        extra_trace = InvestigationToolTraceEntry(
            tool_call_id=_new_id("definition-call"),
            tool_name="get_metric_definition", arguments={"metric": "sales"},
            observation_ids=(),
        )
        self.coordinator.checkpoint(handle, extra_trace, ())
        with self.assertRaises(ValueError):
            self.coordinator.complete(handle, summary, checkpointed=True)
        run, counts = self._read_run_and_counts(self.run_id)
        self.assertEqual(run.status, RunStatus.RUNNING)
        self.assertEqual(counts["tool_calls"], 1)
        self.assertEqual(counts["diagnoses"], 0)

    def test_autocommit_connection_is_rejected_before_lifecycle_writes(self) -> None:
        coordinator = InvestigationTransactionCoordinator(self._connect)
        with self.assertRaises(ValueError):
            coordinator.start(
                self.descriptor, run_id=self.run_id, requested_metric="sales",
                data_version=self.data_version,
            )
        run, _counts = self._read_run_and_counts(self.run_id)
        self.assertIsNone(run)

    def test_worker_success_and_exclusive_claim_with_short_transactions(self) -> None:
        calls = []

        def runner(request, progress):
            calls.append(request.run_id)
            competitor = InvestigationWorker(
                self._transaction_connection,
                lambda *_args: self.fail("Competing worker must not execute."),
            )
            self.assertIsNone(competitor.run_once())
            connection = self._connect()
            try:
                idle_transactions = connection.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND state = 'idle in transaction'"
                ).fetchone()[0]
                self.assertEqual(idle_transactions, 0)
            finally:
                connection.close()
            summary = self._controlled_summary(request)
            progress(summary.investigation.tool_trace[0], summary.observation_catalog)
            progress(summary.investigation.tool_trace[0], summary.observation_catalog)
            return summary

        worker = InvestigationWorker(self._transaction_connection, runner)
        worker.submit(self._request())
        self.assertEqual(worker.run_once(), self.run_id)
        self.assertIsNone(worker.run_once())
        run, counts = self._read_run_and_counts(self.run_id)
        self.assertEqual(calls, [self.run_id])
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertEqual(counts["tool_calls"], 1)
        self.assertEqual(counts["observations"], 1)
        self.assertEqual(counts["diagnoses"], 1)

    def test_worker_failure_keeps_prior_facts_without_diagnosis(self) -> None:
        def runner(request, progress):
            summary = self._controlled_summary(request)
            progress(summary.investigation.tool_trace[0], summary.observation_catalog)
            raise RuntimeError("controlled private response must not persist")

        worker = InvestigationWorker(self._transaction_connection, runner)
        worker.submit(self._request())
        self.assertEqual(worker.run_once(), self.run_id)
        run, counts = self._read_run_and_counts(self.run_id)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(counts["tool_calls"], 1)
        self.assertEqual(counts["observations"], 1)
        self.assertEqual(counts["evidence"], 0)
        self.assertEqual(counts["diagnoses"], 0)
        connection = self._connect()
        try:
            details = connection.execute(
                "SELECT failure_details FROM app_state.investigation_runs "
                "WHERE investigation_run_id = %s", (self.run_id,),
            ).fetchone()[0]
            self.assertEqual(details, {"code": "execution_failed"})
        finally:
            connection.close()

    def test_worker_skips_locked_queue_row_and_rejects_duplicate_submission(self) -> None:
        called = []

        def runner(request, progress):
            called.append(request.run_id)
            return self._controlled_summary(request)

        worker = InvestigationWorker(self._transaction_connection, runner)
        request = self._request()
        second_request = replace(request, run_id=_new_id("second-queued-run"))
        worker.submit(request)
        with self.assertRaises(self._psycopg.IntegrityError):
            worker.submit(request)
        worker.submit(second_request)
        blocker = self._transaction_connection()
        try:
            blocker.execute(
                "SELECT investigation_run_id FROM app_state.investigation_runs "
                "WHERE investigation_run_id = %s FOR UPDATE", (self.run_id,),
            )
            self.assertEqual(worker.run_once(), second_request.run_id)
        finally:
            blocker.rollback()
            blocker.close()
        self.assertEqual(worker.run_once(), self.run_id)
        self.assertEqual(called, [second_request.run_id, self.run_id])
        self.assertIsNone(worker.run_once())

    def test_worker_process_exit_preserves_steps_and_recovers_without_replay(self) -> None:
        # Abrupt child-process exit: no finally/normal runner failure path.
        worker = InvestigationWorker(
            self._transaction_connection,
            lambda *_args: self.fail("Interrupted work must not be replayed."),
        )
        worker.submit(self._request())
        script = '''
import os
from tests.test_postgres_persistence_integration import PostgresPersistenceAcceptanceTests as T
from app.persistence.worker import InvestigationWorker
T.setUpClass()
fixture = T()
fixture.setUp()
def runner(request, progress):
    summary = fixture._controlled_summary(request)
    progress(summary.investigation.tool_trace[0], summary.observation_catalog)
    os._exit(23)
InvestigationWorker(T._transaction_connection, runner).run_once()
'''
        result = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 23, "Controlled child worker did not reach its exit point.")
        run, counts = self._read_run_and_counts(self.run_id)
        self.assertEqual(run.status, RunStatus.RUNNING)
        self.assertEqual(counts["observations"], 1)
        self.assertIsNone(worker.run_once())
        run, counts = self._read_run_and_counts(self.run_id)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertEqual(counts["tool_calls"], 1)
        self.assertEqual(counts["observations"], 1)
        self.assertEqual(counts["diagnoses"], 0)
        connection = self._connect()
        try:
            details = connection.execute(
                "SELECT failure_details FROM app_state.investigation_runs "
                "WHERE investigation_run_id = %s", (self.run_id,),
            ).fetchone()[0]
            self.assertEqual(details, {"code": "worker_interrupted"})
        finally:
            connection.close()

    def test_worker_recovery_does_not_touch_inline_runs(self) -> None:
        self.coordinator.start(
            self.descriptor, run_id=self.run_id, requested_metric="sales",
            data_version=self.data_version,
        )
        worker = InvestigationWorker(
            self._transaction_connection, lambda *_args: self.fail("No work expected."),
        )
        self.assertIsNone(worker.run_once())
        run, _counts = self._read_run_and_counts(self.run_id)
        self.assertEqual(run.status, RunStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()
