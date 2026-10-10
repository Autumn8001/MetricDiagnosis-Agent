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
        if "pg_try_advisory_lock" in normalized:
            self._one = (self.connection.lock_acquired,)
        elif normalized.startswith("select investigation_run_id"):
            self._many = []
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
    ) -> None:
        self.lock_acquired = lock_acquired
        self.autocommit = autocommit
        self.queued_row = queued_row
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

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


class InvestigationWorkerTests(unittest.TestCase):
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
