"""A deliberately small PostgreSQL-backed investigation worker.

The worker claims at most one queued run per call. It uses a session advisory
lock to keep two worker processes from executing the same recovery/claim loop,
and keeps every database transaction short while the injected runner works.
It does not start threads, poll, retry model calls, or discover credentials.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Protocol

from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary
from app.agent_runtime.investigation_runtime import InvestigationToolTraceEntry
from app.data_sources.capabilities import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.observations.models import Observation
from app.persistence.models import PersistenceValidationError, RunStatus
from app.persistence.repository import ApplicationStateRepository
from app.persistence.task_execution_service import (
    InvestigationTaskRequest,
    TaskExecutionFailure,
)
from app.persistence.transaction_coordinator import (
    ConnectionFactory,
    InvestigationRunHandle,
    InvestigationTransactionCoordinator,
)


_WORKER_LOCK_KEY = 7_419_260_103
_INTERRUPTED_CODE = "worker_interrupted"
_DEFAULT_FAILURE_CODE = "execution_failed"


class WorkerError(PersistenceValidationError):
    """Base exception for worker configuration or execution failures."""


class _WorkerLockLost(WorkerError):
    """A session advisory lock or its connection is no longer healthy."""


class _WorkerProgressWriteError(WorkerError):
    """A progress transaction failed and must not be mistaken for runner error."""


class _Cursor(Protocol):
    def execute(self, operation: str, params: object = ...) -> object: ...
    def fetchone(self) -> object: ...
    def close(self) -> object: ...


class _Connection(Protocol):
    autocommit: bool

    def cursor(self) -> _Cursor: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


ProgressCallback = Callable[
    [InvestigationToolTraceEntry, tuple[Observation, ...]], None
]
WorkerRunner = Callable[
    [InvestigationTaskRequest, ProgressCallback], EvidenceDrivenRunSummary
]


def _row_values(row: object, fields: tuple[str, ...]) -> dict[str, object]:
    if isinstance(row, Mapping):
        try:
            return {field: row[field] for field in fields}
        except KeyError as exc:
            raise WorkerError("Queued run row is missing a required field.") from exc
    if isinstance(row, (tuple, list)) and len(row) == len(fields):
        return dict(zip(fields, row, strict=True))
    raise WorkerError("Queued run row has an invalid shape.")


def _json_object(value: object, field: str) -> Mapping[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise WorkerError(f"Stored {field} is invalid JSON.") from exc
    if not isinstance(value, Mapping):
        raise WorkerError(f"Stored {field} must be a JSON object.")
    return value


class InvestigationWorker:
    """Submit and execute single queued investigations on demand."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        runner: WorkerRunner,
        *,
        coordinator: InvestigationTransactionCoordinator | None = None,
        expected_source: DataSourceDescriptor | None = None,
    ) -> None:
        if not callable(connection_factory):
            raise WorkerError("connection_factory must be callable.")
        if not callable(runner):
            raise WorkerError("runner must be callable.")
        if (
            expected_source is not None
            and type(expected_source) is not DataSourceDescriptor
        ):
            raise WorkerError(
                "expected_source must be a DataSourceDescriptor or None."
            )
        self._factory = connection_factory
        self._runner = runner
        self._expected_source = expected_source
        self._coordinator = coordinator or InvestigationTransactionCoordinator(
            connection_factory
        )

    @staticmethod
    def _open_transaction(factory: ConnectionFactory) -> _Connection:
        connection = factory()
        if bool(getattr(connection, "autocommit", False)):
            try:
                connection.close()
            finally:
                raise WorkerError("Worker connections must have autocommit disabled.")
        return connection  # type: ignore[return-value]

    def submit(self, request: InvestigationTaskRequest) -> str:
        """Persist one queued worker run; a duplicate run ID is never replayed."""

        if not isinstance(request, InvestigationTaskRequest):
            raise WorkerError("request must be an InvestigationTaskRequest.")
        request.__post_init__()
        if self._expected_source is not None and not self._same_source_identity(
            request.descriptor, self._expected_source
        ):
            raise WorkerError("Request source does not match this worker's configured source.")
        connection = self._open_transaction(self._factory)
        try:
            repository = ApplicationStateRepository(connection)
            repository.upsert_data_source(request.descriptor, data_version=request.data_version)
            repository.create_investigation_run(
                run_id=request.run_id,
                source_id=request.descriptor.source_id,
                environment=request.descriptor.environment,
                requested_metric=request.requested_metric,
                data_version=request.data_version,
                query_reference=request.query_reference,
                parameters=request.parameters,
            )
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE app_state.investigation_runs
                    SET execution_mode = 'worker'
                    WHERE investigation_run_id = %s AND status = %s
                    """,
                    (request.run_id, RunStatus.QUEUED.value),
                )
                if getattr(cursor, "rowcount", 1) != 1:
                    raise WorkerError("Queued worker run could not be marked.")
            finally:
                cursor.close()
            connection.commit()
            return request.run_id
        except BaseException:
            try:
                connection.rollback()
            except BaseException:
                pass
            raise
        finally:
            connection.close()

    def run_once(self) -> str | None:
        """Recover stale worker runs, claim at most one run, then execute it."""

        lock_connection = self._open_transaction(self._factory)
        acquired = False
        try:
            cursor = lock_connection.cursor()
            try:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (_WORKER_LOCK_KEY,))
                row = cursor.fetchone()
                acquired = bool(row[0] if isinstance(row, (tuple, list)) else row)
            finally:
                cursor.close()
            lock_connection.commit()
            if not acquired:
                return None

            self._recover_interrupted(lock_connection)
            claimed = self._claim_one(lock_connection)
            if claimed is None:
                return None
            request, handle = claimed

            def progress(
                trace_entry: InvestigationToolTraceEntry,
                observations: tuple[Observation, ...],
            ) -> None:
                self._assert_lock(lock_connection)
                try:
                    self._coordinator.checkpoint(handle, trace_entry, observations)
                except Exception as exc:
                    raise _WorkerProgressWriteError(
                        "Investigation progress could not be persisted."
                    ) from exc

            try:
                summary = self._runner(request, progress)
            except _WorkerProgressWriteError:
                raise
            except Exception as exc:
                self._assert_lock(lock_connection)
                failure_code = (
                    exc.code
                    if isinstance(exc, TaskExecutionFailure)
                    else _DEFAULT_FAILURE_CODE
                )
                # The persisted payload contains only this bounded code. A
                # failure-write error is allowed to reach the caller.
                self._coordinator.fail(handle, failure_code)
                return request.run_id

            if not isinstance(summary, EvidenceDrivenRunSummary):
                self._assert_lock(lock_connection)
                self._coordinator.fail(handle, _DEFAULT_FAILURE_CODE)
                return request.run_id

            self._assert_lock(lock_connection)
            self._coordinator.complete(
                handle,
                summary,
                query_reference=request.query_reference,
                checkpointed=True,
            )
            return request.run_id
        finally:
            if acquired:
                try:
                    cursor = lock_connection.cursor()
                    try:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", (_WORKER_LOCK_KEY,))
                        lock_connection.commit()
                    finally:
                        cursor.close()
                except Exception:
                    try:
                        lock_connection.rollback()
                    except Exception:
                        pass
            lock_connection.close()

    @staticmethod
    def _assert_lock(connection: _Connection) -> None:
        try:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                cursor.close()
            connection.commit()
        except Exception as exc:
            raise _WorkerLockLost("Worker lock session is no longer healthy.") from exc

    def _recover_interrupted(self, connection: _Connection) -> None:
        repository = ApplicationStateRepository(connection)
        cursor = connection.cursor()
        try:
            query = """
                SELECT investigation_run_id
                FROM app_state.investigation_runs
                WHERE status = %s AND execution_mode = 'worker'
            """
            params: tuple[object, ...] = (RunStatus.RUNNING.value,)
            if self._expected_source is not None:
                query += (
                    " AND source_id = %s AND environment = %s"
                    " AND EXISTS (SELECT 1 FROM app_state.data_sources AS s"
                    " WHERE s.source_id = app_state.investigation_runs.source_id AND s.provider = %s)"
                )
                params += (
                    self._expected_source.source_id,
                    self._expected_source.environment.value,
                    self._expected_source.provider.value,
                )
            query += " FOR UPDATE"
            cursor.execute(query, params)
            rows = cursor.fetchall()
        finally:
            cursor.close()
        try:
            for row in rows:
                run_id = row[0] if isinstance(row, (tuple, list)) else row["investigation_run_id"]
                repository.fail_investigation_run(
                    run_id=run_id,
                    failure_code=_INTERRUPTED_CODE,
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def _claim_one(
        self, connection: _Connection
    ) -> tuple[InvestigationTaskRequest, InvestigationRunHandle] | None:
        fields = (
            "investigation_run_id",
            "source_id",
            "environment",
            "requested_metric",
            "data_version",
            "query_reference",
            "parameters",
            "provider",
            "display_name",
        )
        connection.rollback()
        cursor = connection.cursor()
        try:
            query = """
                SELECT r.investigation_run_id, r.source_id, r.environment,
                       r.requested_metric, r.data_version, r.query_reference,
                       r.parameters, s.provider, s.display_name
                FROM app_state.investigation_runs AS r
                JOIN app_state.data_sources AS s ON s.source_id = r.source_id
                WHERE r.status = %s AND r.execution_mode = 'worker'
            """
            params: tuple[object, ...] = (RunStatus.QUEUED.value,)
            if self._expected_source is not None:
                query += " AND r.source_id = %s AND r.environment = %s AND s.provider = %s"
                params += (
                    self._expected_source.source_id,
                    self._expected_source.environment.value,
                    self._expected_source.provider.value,
                )
            query += (
                " ORDER BY r.requested_at, r.investigation_run_id"
                " FOR UPDATE OF r SKIP LOCKED LIMIT 1"
            )
            cursor.execute(query, params)
            raw_row = cursor.fetchone()
            if raw_row is None:
                connection.commit()
                return None
            values = _row_values(raw_row, fields)
            descriptor = DataSourceDescriptor(
                source_id=str(values["source_id"]),
                display_name=str(values["display_name"]),
                provider=SourceProvider(values["provider"]),
                environment=SourceEnvironment(values["environment"]),
            )
            run_id = str(values["investigation_run_id"])
            parameters = _json_object(values["parameters"], "parameters")
            requested_metric = values["requested_metric"]
            if not isinstance(requested_metric, str):
                raise WorkerError("Queued run is missing a requested metric.")
            request = InvestigationTaskRequest(
                run_id=run_id,
                descriptor=descriptor,
                requested_metric=requested_metric,
                data_version=values["data_version"],  # type: ignore[arg-type]
                query_reference=values["query_reference"],  # type: ignore[arg-type]
                parameters=parameters,
            )
            cursor.execute(
                """
                UPDATE app_state.investigation_runs
                SET status = %s, started_at = now()
                WHERE investigation_run_id = %s AND status = %s
                """,
                (RunStatus.RUNNING.value, run_id, RunStatus.QUEUED.value),
            )
            if getattr(cursor, "rowcount", 1) != 1:
                raise WorkerError("Claimed run was concurrently changed.")
            connection.commit()
            handle = InvestigationRunHandle(
                run_id=run_id,
                descriptor=descriptor,
                data_version=request.data_version,
            )
            return request, handle
        except BaseException:
            connection.rollback()
            raise
        finally:
            cursor.close()

    @staticmethod
    def _same_source_identity(
        actual: DataSourceDescriptor, expected: DataSourceDescriptor
    ) -> bool:
        return (
            actual.source_id == expected.source_id
            and actual.provider is expected.provider
            and actual.environment is expected.environment
        )


__all__ = ["InvestigationWorker", "ProgressCallback", "WorkerError", "WorkerRunner"]
