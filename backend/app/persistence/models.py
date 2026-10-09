"""Immutable state contracts for the application persistence boundary.

R2-001 deliberately stops at domain values.  No model in this module opens a
database, performs a write, or converts a state transition into a SQL command.
The existing data-source capability contract remains the authority for source
environment values, so a persisted reference cannot invent a second vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.data_sources.capabilities import SourceEnvironment


class PersistenceError(Exception):
    """Base exception for persistence-boundary domain errors."""


class PersistenceValidationError(PersistenceError, ValueError):
    """Raised when a persistence value violates its domain contract."""


class PersistenceRepositoryError(PersistenceError):
    """Raised when a repository operation cannot satisfy its persistence contract."""


class InvalidRunTransitionError(PersistenceError, ValueError):
    """Raised when a run status transition is not part of the lifecycle."""


# Keep the more general name available to callers without creating two
# incompatible exception hierarchies for the same contract.
InvalidStateTransitionError = InvalidRunTransitionError


class RunStatus(StrEnum):
    """Persisted lifecycle states for sync and investigation runs."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Whether this state cannot transition to another state."""

        return self in TERMINAL_RUN_STATUSES


TERMINAL_RUN_STATUSES: Final[frozenset[RunStatus]] = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


class DataSourceState(StrEnum):
    """Lifecycle states stored for an application data-source record."""

    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


# ``DataSourceStatus`` is a readable alias for callers that use status
# terminology at the API boundary.  There is still only one enum vocabulary.
DataSourceStatus = DataSourceState


ALLOWED_RUN_TRANSITIONS: Final[dict[RunStatus, frozenset[RunStatus]]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def _clean_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersistenceValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


@dataclass(frozen=True)
class SourceReference:
    """The non-sensitive identity of a source used by a persisted run."""

    source_id: str
    environment: SourceEnvironment

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _clean_identifier(self.source_id, "source_id"))
        if not isinstance(self.environment, SourceEnvironment):
            raise PersistenceValidationError(
                "Field 'environment' must be a SourceEnvironment enum member."
            )


# The longer name is useful at API boundaries while the shorter name reads
# naturally in run-oriented code.  Both refer to the same immutable contract.
DataSourceReference = SourceReference


@dataclass(frozen=True)
class RunState:
    """Immutable run status snapshot with an explicit fail-closed transition."""

    status: RunStatus = RunStatus.QUEUED

    def __post_init__(self) -> None:
        if not isinstance(self.status, RunStatus):
            raise PersistenceValidationError(
                "Field 'status' must be a RunStatus enum member."
            )

    @classmethod
    def initial(cls) -> "RunState":
        """Create the only state used for a newly enqueued run."""

        return cls(status=RunStatus.QUEUED)

    @classmethod
    def queued(cls) -> "RunState":
        """Alias for ``initial`` that reads naturally at call sites."""

        return cls.initial()

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    def can_transition_to(self, target: RunStatus) -> bool:
        """Return whether ``target`` is a legal next state.

        Invalid target types return ``False`` here so callers can use this as a
        predicate.  The mutating-looking operation ``transition_to`` remains
        strict and raises a domain exception for invalid input.
        """

        if not isinstance(target, RunStatus):
            return False
        return target in ALLOWED_RUN_TRANSITIONS[self.status]

    def transition_to(self, target: RunStatus) -> "RunState":
        """Return a new state or reject an illegal transition."""

        if not isinstance(target, RunStatus):
            raise InvalidRunTransitionError(
                "Run transition target must be a RunStatus enum member."
            )
        if not self.can_transition_to(target):
            allowed = sorted(item.value for item in ALLOWED_RUN_TRANSITIONS[self.status])
            allowed_text = ", ".join(allowed) if allowed else "none"
            raise InvalidRunTransitionError(
                f"Cannot transition run from '{self.status.value}' to "
                f"'{target.value}'; allowed targets: {allowed_text}."
            )
        return RunState(status=target)

    # Short aliases keep the value object convenient without introducing a
    # second transition implementation.
    def transition(self, target: RunStatus) -> "RunState":
        return self.transition_to(target)

    def advance_to(self, target: RunStatus) -> "RunState":
        return self.transition_to(target)


__all__ = [
    "ALLOWED_RUN_TRANSITIONS",
    "DataSourceReference",
    "DataSourceState",
    "DataSourceStatus",
    "InvalidRunTransitionError",
    "InvalidStateTransitionError",
    "PersistenceError",
    "PersistenceRepositoryError",
    "PersistenceValidationError",
    "RunState",
    "RunStatus",
    "SourceEnvironment",
    "SourceReference",
    "TERMINAL_RUN_STATUSES",
]
