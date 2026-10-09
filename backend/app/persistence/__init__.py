"""Persistence-boundary contracts and the small application-state repository."""

from app.data_sources.capabilities import SourceEnvironment
from app.persistence.migrations import (
    DEFAULT_MIGRATION_NAME,
    MIGRATIONS_DIRECTORY,
    available_migrations,
    load_app_state_migration,
    load_migration,
)
from app.persistence.models import (
    DataSourceReference,
    DataSourceState,
    DataSourceStatus,
    InvalidRunTransitionError,
    InvalidStateTransitionError,
    PersistenceError,
    PersistenceRepositoryError,
    PersistenceValidationError,
    RunState,
    RunStatus,
    SourceReference,
)
from app.persistence.repository import ApplicationStateRepository, InvestigationRunSummary
from app.persistence.investigation_writer import (
    ApplicationStateRepositoryProtocol,
    EvidenceDrivenRunPersistenceWriter,
    InvestigationPersistenceValidationError,
    InvestigationWriterValidationError,
    persist_evidence_driven_run,
)
from app.persistence.transaction_coordinator import (
    ConnectionFactory,
    DBAPIConnection,
    InvestigationRunContext,
    InvestigationRunHandle,
    InvestigationTransactionCoordinator,
    RunHandle,
    TransactionCoordinator,
)

__all__ = [
    "DEFAULT_MIGRATION_NAME",
    "MIGRATIONS_DIRECTORY",
    "DataSourceReference",
    "DataSourceState",
    "DataSourceStatus",
    "ApplicationStateRepository",
    "ApplicationStateRepositoryProtocol",
    "EvidenceDrivenRunPersistenceWriter",
    "ConnectionFactory",
    "DBAPIConnection",
    "InvestigationRunContext",
    "InvestigationRunHandle",
    "InvestigationTransactionCoordinator",
    "InvestigationRunSummary",
    "InvestigationPersistenceValidationError",
    "InvestigationWriterValidationError",
    "InvalidRunTransitionError",
    "InvalidStateTransitionError",
    "PersistenceError",
    "PersistenceRepositoryError",
    "PersistenceValidationError",
    "RunState",
    "RunStatus",
    "RunHandle",
    "SourceEnvironment",
    "SourceReference",
    "available_migrations",
    "load_app_state_migration",
    "load_migration",
    "persist_evidence_driven_run",
    "TransactionCoordinator",
]
