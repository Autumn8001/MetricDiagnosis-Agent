from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.data_sources.capabilities import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.persistence.task_execution_service import (
    InvestigationTaskRequest,
    TaskExecutionFailure,
)
from app.persistence.worker import InvestigationWorker, WorkerError


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self.connection = connection
        self.rowcount = 1
        self._one = None
        self._many = []

    def execute(self, operation: str, params: object = None) -> None:
        normalized = " ".join(operation.split()).lower()
        self.connection.executions.append((normalized, params))
        if "pg_try_advisory_lock" in normalized:
            self._one = (self.connection.lock_acquired,)
        elif normalized.startswith("select investigation_run_id"):
            self._many = self.connection.recovery_rows
        elif "from app_state.investigation_runs as r" in normalized:
            self._one = self.connection.queued_row
        elif "pg_advisory_unlock" in normalized:
            self._one = (True,)
        elif normalized == "select 1":
            self._one = (1,)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many

    def close(self) -> None:
        pass


class _FakeConnection:
    def __init__(
        self,
        *,
        lock_acquired: bool = True,
        autocommit: bool = False,
        queued_row: tuple[object, ...] | None = None,
        recovery_rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.lock_acquired = lock_acquired
        self.autocommit = autocommit
        self.queued_row = queued_row
        self.recovery_rows = recovery_rows or []
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.executions: list[tuple[str, object]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _request() -> InvestigationTaskRequest:
    return InvestigationTaskRequest(
        run_id="worker-run-1",
        descriptor=DataSourceDescriptor(
            source_id="synthetic-test",
            display_name="Synthetic test",
            provider=SourceProvider.SYNTHETIC,
            environment=SourceEnvironment.BENCHMARK,
        ),
        requested_metric="revenue",
    )


def _source(
    *,
    source_id: str = "synthetic-test",
    display_name: str = "Another display name",
    provider: SourceProvider = SourceProvider.SYNTHETIC,
    environment: SourceEnvironment = SourceEnvironment.BENCHMARK,
) -> DataSourceDescriptor:
    return DataSourceDescriptor(
        source_id=source_id,
        display_name=display_name,
        provider=provider,
        environment=environment,
    )


class InvestigationWorkerTests(unittest.TestCase):
    def test_expected_source_must_be_a_descriptor(self) -> None:
        with self.assertRaises(WorkerError):
            InvestigationWorker(
                lambda: _FakeConnection(), Mock(), expected_source="synthetic-test"  # type: ignore[arg-type]
            )

    def test_submit_rejects_other_source_before_opening_connection(self) -> None:
        mismatched_sources = (
            _source(source_id="olist-validation"),
            _source(provider=SourceProvider.OLIST),
            _source(environment=SourceEnvironment.SANDBOX),
        )
        for descriptor in mismatched_sources:
            with self.subTest(descriptor=descriptor):
                factory = Mock(
                    side_effect=AssertionError("connection must not be opened")
                )
                worker = InvestigationWorker(factory, Mock(), expected_source=_source())
                request = InvestigationTaskRequest(
                    run_id="other-source-run",
                    descriptor=descriptor,
                    requested_metric="revenue",
                )

                with self.assertRaises(WorkerError):
                    worker.submit(request)
                factory.assert_not_called()

    def test_submit_matches_identity_but_not_display_name(self) -> None:
        connection = _FakeConnection()
        worker = InvestigationWorker(
            lambda: connection,
            Mock(),
            expected_source=_source(display_name="Configured label"),
        )

        self.assertEqual(worker.submit(_request()), "worker-run-1")
        self.assertTrue(connection.closed)

    def test_bound_claim_filters_source_identity_with_parameters(self) -> None:
        connection = _FakeConnection(
            queued_row=(
                "worker-run-1",
                "synthetic-test",
                "benchmark",
                "revenue",
                None,
                None,
                {},
                "synthetic",
                "Synthetic test",
            )
        )
        worker = InvestigationWorker(lambda: connection, Mock(), expected_source=_source())

        claimed = worker._claim_one(connection)

        self.assertIsNotNone(claimed)
        claim_query, claim_params = next(
            (query, params)
            for query, params in connection.executions
            if "from app_state.investigation_runs as r" in query
        )
        self.assertIn(
            "and r.source_id = %s and r.environment = %s and s.provider = %s",
            claim_query,
        )
        self.assertEqual(
            claim_params,
            ("queued", "synthetic-test", "benchmark", "synthetic"),
        )

    def test_bound_recovery_filters_source_and_environment_with_parameters(self) -> None:
        connection = _FakeConnection()
        worker = InvestigationWorker(
            lambda: connection, Mock(), expected_source=_source()
        )

        worker._recover_interrupted(connection)

        recovery_query, recovery_params = connection.executions[0]
        self.assertIn("and source_id = %s and environment = %s", recovery_query)
        self.assertIn("and s.provider = %s", recovery_query)
        self.assertEqual(recovery_params, ("running", "synthetic-test", "benchmark", "synthetic"))

    def test_unbound_worker_keeps_legacy_claim_and_recovery_scope(self) -> None:
        connection = _FakeConnection()
        worker = InvestigationWorker(lambda: connection, Mock())

        worker._recover_interrupted(connection)
        self.assertEqual(connection.executions[0][1], ("running",))
        self.assertNotIn("source_id = %s", connection.executions[0][0])

        connection.executions.clear()
        worker._claim_one(connection)
        claim_query, claim_params = next(
            (query, params)
            for query, params in connection.executions
            if "from app_state.investigation_runs as r" in query
        )
        self.assertNotIn("r.source_id = %s", claim_query)
        self.assertEqual(claim_params, ("queued",))

    def test_autocommit_connection_is_rejected(self) -> None:
        connection = _FakeConnection(autocommit=True)
        worker = InvestigationWorker(lambda: connection, Mock())

        with self.assertRaises(WorkerError):
            worker.submit(_request())
        self.assertTrue(connection.closed)

    def test_lock_refusal_returns_without_claim_or_runner(self) -> None:
        connection = _FakeConnection(lock_acquired=False)
        runner = Mock()
        worker = InvestigationWorker(lambda: connection, runner)

        self.assertIsNone(worker.run_once())
        runner.assert_not_called()
        self.assertTrue(connection.closed)

    def test_empty_queue_does_not_start_runner(self) -> None:
        connection = _FakeConnection()
        runner = Mock()
        worker = InvestigationWorker(lambda: connection, runner)

        self.assertIsNone(worker.run_once())
        runner.assert_not_called()
        self.assertTrue(connection.closed)

    def test_task_execution_failure_persists_only_safe_code(self) -> None:
        connection = _FakeConnection(
            queued_row=(
                "worker-run-1",
                "synthetic-test",
                "benchmark",
                "revenue",
                None,
                None,
                {},
                "synthetic",
                "Synthetic test",
            )
        )
        coordinator = Mock()
        runner = Mock(side_effect=TaskExecutionFailure("tool_timeout"))
        worker = InvestigationWorker(
            lambda: connection,
            runner,
            coordinator=coordinator,
        )

        self.assertEqual(worker.run_once(), "worker-run-1")
        coordinator.fail.assert_called_once()
        self.assertEqual(coordinator.fail.call_args.args[1], "tool_timeout")
        self.assertNotIn("password", repr(coordinator.fail.call_args).lower())


if __name__ == "__main__":
    unittest.main()
