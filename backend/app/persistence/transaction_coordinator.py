"""Short-lived transaction coordination for audited investigation runs.

The repository and the investigation writer deliberately do not own database
transactions.  This module is the small application boundary that supplies a
fresh DB-API connection for each lifecycle operation, commits only after the
operation succeeds, and always releases that connection before returning.

It does not discover credentials, open a network connection, run migrations,
or retain a connection between calls.  A caller can therefore invoke
``start`` before model execution and ``complete``/``fail`` afterwards without
sharing a transaction across the model call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeVar

from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary
from app.data_sources.capabilities import DataSourceDescriptor
from app.persistence.investigation_writer import EvidenceDrivenRunPersistenceWriter
from app.persistence.models import (
    PersistenceValidationError,
    RunStatus,
)
from app.persistence.repository import ApplicationStateRepository


class DBAPIConnection(Protocol):
    """Minimal connection surface required by the transaction boundary."""

    def commit(self) -> object:
        ...

    def rollback(self) -> object:
        ...


ConnectionFactory = Callable[[], DBAPIConnection]


def _clean_required(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersistenceValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def _clean_optional(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _clean_required(value, field_name)


@dataclass(frozen=True)
class InvestigationRunHandle:
    """Immutable binding for later operations on one started run.

    The descriptor and data version are captured at ``start`` time.  Completion
    and failure consequently cannot accidentally be redirected to another
    source by accepting independent source/environment arguments.
    """

    run_id: str
    descriptor: DataSourceDescriptor
    data_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _clean_required(self.run_id, "run_id"))
        if not isinstance(self.descriptor, DataSourceDescriptor):
            raise PersistenceValidationError(
                "Field 'descriptor' must be a DataSourceDescriptor."
            )
        object.__setattr__(
            self,
            "data_version",
            _clean_optional(self.data_version, "data_version"),
        )

    @property
    def source(self) -> DataSourceDescriptor:
        """Readable alias for callers that refer to the bound source."""

        return self.descriptor


# Short aliases keep this contract convenient at application call sites while
# preserving one immutable handle type and one validation implementation.
RunHandle = InvestigationRunHandle
InvestigationRunContext = InvestigationRunHandle


ResultT = TypeVar("ResultT")


class InvestigationTransactionCoordinator:
    """Coordinate one independent DB transaction per run lifecycle operation."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        if not callable(connection_factory):
            raise PersistenceValidationError(
                "connection_factory must be a callable returning a DB-API connection."
            )
        # Store only the factory.  A live connection is always a local variable
        # inside ``_transaction`` and can never span public method calls.
        self._factory = connection_factory

    @staticmethod
    def _validate_handle(handle: object) -> InvestigationRunHandle:
        if not isinstance(handle, InvestigationRunHandle):
            raise PersistenceValidationError(
                "handle must be an InvestigationRunHandle."
            )
        # Re-run the immutable value contract so deliberately forged objects
        # fail closed before a new connection is requested.
        InvestigationRunHandle.__post_init__(handle)
        return handle

    def _transaction(
        self,
        descriptor: DataSourceDescriptor,
        data_version: str | None,
        operation: Callable[[EvidenceDrivenRunPersistenceWriter], ResultT],
    ) -> ResultT:
        """Run one writer operation in a fresh, short-lived transaction."""

        connection: DBAPIConnection | None = None
        try:
            connection = self._factory()
            repository = ApplicationStateRepository(connection)
            writer = EvidenceDrivenRunPersistenceWriter(
                repository,
                descriptor,
                data_version=data_version,
            )
            result = operation(writer)
            connection.commit()
            return result
        except BaseException:
            if connection is not None:
                try:
                    connection.rollback()
                except BaseException:
                    # Preserve the operation/commit exception as the useful
                    # failure; rollback is best effort by contract.
                    pass
            raise
        finally:
            if connection is not None:
                close = getattr(connection, "close", None)
                if callable(close):
                    try:
                        close()
                    except BaseException:
                        # The operation may already be committed.  Raising a
                        # cleanup-only error would mislead callers into retrying
                        # a durable lifecycle transition, so it must never
                        # replace the operation/commit outcome.
                        pass

    def start(
        self,
        descriptor: DataSourceDescriptor,
        *,
        run_id: str,
        requested_metric: str,
        data_version: str | None = None,
        parameters: Mapping[str, object] | None = None,
        query_reference: str | None = None,
    ) -> InvestigationRunHandle:
        """Persist and commit a queued-to-running run, then return its handle."""

        handle = InvestigationRunHandle(
            run_id=run_id,
            descriptor=descriptor,
            data_version=data_version,
        )
        self._transaction(
            handle.descriptor,
            handle.data_version,
            lambda writer: writer.start(
                run_id=handle.run_id,
                requested_metric=requested_metric,
                parameters=parameters,
                query_reference=query_reference,
            ),
        )
        return handle

    def complete(
        self,
        handle: InvestigationRunHandle,
        summary: EvidenceDrivenRunSummary,
        *,
        query_reference: str | None = None,
    ) -> str:
        """Persist facts and diagnosis in a new transaction and mark success."""

        validated_handle = self._validate_handle(handle)
        return self._transaction(
            validated_handle.descriptor,
            validated_handle.data_version,
            lambda writer: writer.complete(
                summary,
                run_id=validated_handle.run_id,
                query_reference=query_reference,
            ),
        )

    def fail(
        self,
        handle: InvestigationRunHandle,
        failure_code: str,
    ) -> RunStatus:
        """Persist only a bounded failure code in a new transaction."""

        validated_handle = self._validate_handle(handle)
        return self._transaction(
            validated_handle.descriptor,
            validated_handle.data_version,
            lambda writer: writer.fail(
                run_id=validated_handle.run_id,
                failure_code=failure_code,
            ),
        )


# A concise alias for application code that does not need the investigation
# qualifier.  It is the same implementation, not a second runtime.
TransactionCoordinator = InvestigationTransactionCoordinator


__all__ = [
    "ConnectionFactory",
    "DBAPIConnection",
    "InvestigationRunContext",
    "InvestigationRunHandle",
    "InvestigationTransactionCoordinator",
    "RunHandle",
    "TransactionCoordinator",
]
