"""Pure persistence-boundary contracts for MetricSleuth.

This package intentionally contains no database driver or repository code yet.
It defines the application-state values that the future persistence adapter must
store and a read-only locator for the versioned SQL migration.
"""

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
    InvalidRunTransitionError,
    InvalidStateTransitionError,
    PersistenceError,
    PersistenceValidationError,
    RunState,
    RunStatus,
    SourceReference,
)

__all__ = [
    "DEFAULT_MIGRATION_NAME",
    "MIGRATIONS_DIRECTORY",
    "DataSourceReference",
    "InvalidRunTransitionError",
    "InvalidStateTransitionError",
    "PersistenceError",
    "PersistenceValidationError",
    "RunState",
    "RunStatus",
    "SourceEnvironment",
    "SourceReference",
    "available_migrations",
    "load_app_state_migration",
    "load_migration",
]
