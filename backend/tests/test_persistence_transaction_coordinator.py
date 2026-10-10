from __future__ import annotations

import inspect
import os
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

from app.data_sources.capabilities import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.persistence import (
    InvestigationRunHandle,
    InvestigationTransactionCoordinator,
    PersistenceValidationError,
)
from app.persistence import transaction_coordinator as coordinator_module
from app.persistence.models import RunStatus


DESCRIPTOR = DataSourceDescriptor(
    source_id="synthetic-main",
    display_name="Synthetic benchmark",
    provider=SourceProvider.SYNTHETIC,
    environment=SourceEnvironment.BENCHMARK,
)
class FakeConnection:
    def __init__(
        self,
        *,
        commit_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.commit_error = commit_error
        self.close_error = close_error
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def commit(self) -> None:
        self.commit_count += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class NoCloseConnection:
    """A minimal fake for the optional DB-API cleanup method contract."""

    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class RecordingCursor:
    def __init__(self, executions: list[tuple[str, tuple[object, ...]]]) -> None:
        self.executions = executions
        self.rowcount = 1
        self.close_count = 0

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executions.append((sql, params))

    def close(self) -> None:
        self.close_count += 1


class RecordingConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.cursors: list[RecordingCursor] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> RecordingCursor:
        cursor = RecordingCursor(self.executions)
        self.cursors.append(cursor)
        return cursor

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


class FakeRepository:
    instances: list["FakeRepository"] = []

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.__class__.instances.append(self)


class FakeWriter:
    instances: list["FakeWriter"] = []
    events: list[tuple[str, dict[str, object]]] = []
    operation_error: BaseException | None = None

    def __init__(self, repository: FakeRepository, descriptor, *, data_version=None) -> None:
        self.repository = repository
        self.descriptor = descriptor
        self.data_version = data_version
        self.__class__.instances.append(self)

    def start(self, *, run_id, requested_metric, parameters=None, query_reference=None):
        self.__class__.events.append(
            (
                "start",
                {
                    "run_id": run_id,
                    "requested_metric": requested_metric,
                    "parameters": parameters,
                    "query_reference": query_reference,
                    "descriptor": self.descriptor,
                    "data_version": self.data_version,
                },
            )
        )
        if self.operation_error is not None:
            raise self.operation_error
        return run_id

    def complete(self, summary, *, run_id, query_reference=None, checkpointed=False):
        self.__class__.events.append(
            (
                "complete",
                {
                    "summary": summary,
                    "run_id": run_id,
                    "query_reference": query_reference,
                    "descriptor": self.descriptor,
                    "data_version": self.data_version,
                },
            )
        )
        if self.operation_error is not None:
            raise self.operation_error
        return run_id

    def fail(self, *, run_id, failure_code):
        self.__class__.events.append(
            (
                "fail",
                {
                    "run_id": run_id,
                    "failure_code": failure_code,
                    "descriptor": self.descriptor,
                    "data_version": self.data_version,
                },
            )
        )
        if self.operation_error is not None:
            raise self.operation_error
        return RunStatus.FAILED


class TestInvestigationTransactionCoordinator(unittest.TestCase):
    def setUp(self) -> None:
        FakeRepository.instances.clear()
        FakeWriter.instances.clear()
        FakeWriter.events.clear()
        FakeWriter.operation_error = None

    def patched_coordinator(self):
        return patch.multiple(
            coordinator_module,
            ApplicationStateRepository=FakeRepository,
            EvidenceDrivenRunPersistenceWriter=FakeWriter,
        )

    def test_each_public_operation_uses_a_fresh_connection_and_commits_once(self) -> None:
        connections = [FakeConnection(), FakeConnection(), FakeConnection()]
        factory = Mock(side_effect=connections)
        coordinator = InvestigationTransactionCoordinator(factory)

        with self.patched_coordinator():
            handle = coordinator.start(
                DESCRIPTOR,
                run_id="run:short-lived",
                requested_metric="sales",
                data_version="v1",
            )
            self.assertEqual(
                coordinator.complete(handle, {"diagnosis": "placeholder"}),
                "run:short-lived",
            )
            self.assertEqual(
                coordinator.fail(handle, "tool_timeout"),
                RunStatus.FAILED,
            )

        self.assertEqual(factory.call_count, 3)
        self.assertEqual(
            [id(item.repository.connection) for item in FakeWriter.instances],
            [id(item) for item in connections],
        )
        for connection in connections:
            self.assertEqual(connection.commit_count, 1)
            self.assertEqual(connection.rollback_count, 0)
            self.assertEqual(connection.close_count, 1)

        self.assertIs(handle.descriptor, DESCRIPTOR)
        self.assertEqual(handle.data_version, "v1")
        self.assertEqual(
            [name for name, _ in FakeWriter.events],
            ["start", "complete", "fail"],
        )

    def test_start_uses_the_real_repository_and_writer_boundary(self) -> None:
        connection = RecordingConnection()
        factory = Mock(return_value=connection)
        coordinator = InvestigationTransactionCoordinator(factory)

        # Do not patch the repository or writer here: this remains hermetic,
        # while proving the coordinator composes the committed persistence
        # adapters rather than implementing a second SQL path.
        handle = coordinator.start(
            DESCRIPTOR,
            run_id="run:real-adapters",
            requested_metric="sales",
            data_version="benchmark-v1",
        )

        self.assertEqual(handle.run_id, "run:real-adapters")
        self.assertEqual(len(connection.executions), 3)
        self.assertTrue(all(isinstance(params, tuple) for _, params in connection.executions))
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(connection.close_count, 1)

    def test_complete_and_fail_are_bound_to_handle_without_source_arguments(self) -> None:
        connection = FakeConnection()
        factory = Mock(return_value=connection)
        coordinator = InvestigationTransactionCoordinator(factory)
        handle = InvestigationRunHandle(
            run_id="run:bound",
            descriptor=DESCRIPTOR,
            data_version="snapshot-7",
        )

        with self.patched_coordinator():
            coordinator.complete(handle, object(), query_reference="query:7")
            coordinator.fail(handle, "model_error")

        self.assertEqual(len(FakeWriter.instances), 2)
        for writer in FakeWriter.instances:
            self.assertIs(writer.descriptor, DESCRIPTOR)
            self.assertEqual(writer.data_version, "snapshot-7")
        self.assertEqual(FakeWriter.events[0][1]["run_id"], "run:bound")
        self.assertEqual(FakeWriter.events[1][1]["run_id"], "run:bound")
        self.assertEqual(FakeWriter.events[1][1], {
            "run_id": "run:bound",
            "failure_code": "model_error",
            "descriptor": DESCRIPTOR,
            "data_version": "snapshot-7",
        })

        complete_parameters = inspect.signature(coordinator.complete).parameters
        fail_parameters = inspect.signature(coordinator.fail).parameters
        for parameters in (complete_parameters, fail_parameters):
            self.assertNotIn("source_id", parameters)
            self.assertNotIn("environment", parameters)

    def test_operation_error_rolls_back_closes_and_never_commits(self) -> None:
        connection = FakeConnection()
        factory = Mock(return_value=connection)
        coordinator = InvestigationTransactionCoordinator(factory)
        FakeWriter.operation_error = RuntimeError("writer failed")

        with self.patched_coordinator(), self.assertRaisesRegex(
            RuntimeError, "writer failed"
        ):
            coordinator.start(
                DESCRIPTOR,
                run_id="run:error",
                requested_metric="sales",
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.close_count, 1)

    def test_commit_error_rolls_back_closes_and_preserves_commit_exception(self) -> None:
        connection = FakeConnection(commit_error=RuntimeError("commit failed"))
        factory = Mock(return_value=connection)
        coordinator = InvestigationTransactionCoordinator(factory)

        with self.patched_coordinator(), self.assertRaisesRegex(
            RuntimeError, "commit failed"
        ):
            coordinator.start(
                DESCRIPTOR,
                run_id="run:commit-error",
                requested_metric="sales",
            )

        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.close_count, 1)

    def test_close_error_after_commit_does_not_turn_success_into_retryable_failure(self) -> None:
        connection = FakeConnection(close_error=RuntimeError("close failed"))
        coordinator = InvestigationTransactionCoordinator(Mock(return_value=connection))

        with self.patched_coordinator():
            handle = coordinator.start(
                DESCRIPTOR,
                run_id="run:close-error",
                requested_metric="sales",
            )

        self.assertEqual(handle.run_id, "run:close-error")
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(connection.close_count, 1)

    def test_missing_optional_close_does_not_change_success_result(self) -> None:
        connection = NoCloseConnection()
        factory = Mock(return_value=connection)
        coordinator = InvestigationTransactionCoordinator(factory)

        with self.patched_coordinator():
            handle = coordinator.start(
                DESCRIPTOR,
                run_id="run:no-close",
                requested_metric="sales",
            )

        self.assertEqual(handle.run_id, "run:no-close")
        self.assertEqual(connection.commit_count, 1)

    def test_invalid_handle_fails_closed_before_factory_call(self) -> None:
        factory = Mock()
        coordinator = InvestigationTransactionCoordinator(factory)

        with self.assertRaises(PersistenceValidationError):
            coordinator.complete(object(), object())
        with self.assertRaises(PersistenceValidationError):
            coordinator.fail(object(), "tool_timeout")

        factory.assert_not_called()

    def test_handle_is_immutable_and_validates_descriptor_and_identifiers(self) -> None:
        with self.assertRaises(PersistenceValidationError):
            InvestigationRunHandle(run_id="", descriptor=DESCRIPTOR)
        with self.assertRaises(PersistenceValidationError):
            InvestigationRunHandle(run_id="run:bad", descriptor=object())
        with self.assertRaises(PersistenceValidationError):
            InvestigationRunHandle(
                run_id="run:bad-version",
                descriptor=DESCRIPTOR,
                data_version=" ",
            )

        handle = InvestigationRunHandle("run:immutable", DESCRIPTOR, "v1")
        with self.assertRaises(FrozenInstanceError):
            handle.run_id = "run:changed"  # type: ignore[misc]

    def test_factory_is_the_only_connection_source(self) -> None:
        connection = FakeConnection()
        factory = Mock(return_value=connection)
        coordinator = InvestigationTransactionCoordinator(factory)

        with patch.dict(os.environ, {"DATABASE_URL": "sentinel"}), self.patched_coordinator():
            handle = coordinator.start(
                DESCRIPTOR,
                run_id="run:factory-only",
                requested_metric="sales",
            )

        self.assertEqual(handle.run_id, "run:factory-only")
        factory.assert_called_once_with()
        self.assertFalse(any("DATABASE_URL" in name for name in dir(coordinator)))

    def test_non_callable_factory_is_rejected(self) -> None:
        with self.assertRaises(PersistenceValidationError):
            InvestigationTransactionCoordinator(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
