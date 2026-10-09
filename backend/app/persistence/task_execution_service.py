"""Single-investigation application service.

This module is deliberately a small orchestration boundary.  It does not
create a thread, schedule background work, open a database connection, read
environment variables, or run a model itself.  A caller supplies an already
constructed short-transaction coordinator and a runner that returns the
runtime's verified :class:`EvidenceDrivenRunSummary`.

The service keeps the potentially long runner call between two independent
coordinator calls:

``start -> runner -> complete``

If the runner fails, only a bounded failure code is persisted before the
original runner exception is re-raised.  A coordinator start failure never
enters the runner, and a completion failure is not converted into a second
``fail`` operation because completion may already have partially persisted
facts before its transaction failed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
import re
from typing import Protocol, TypeAlias

from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary
from app.data_sources.capabilities import DataSourceDescriptor
from app.persistence.models import (
    PersistenceValidationError,
)
from app.persistence.transaction_coordinator import InvestigationRunHandle


_FAILURE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DEFAULT_FAILURE_CODE = "execution_failed"
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "password",
        "token",
        "secret",
        "apikey",
        "authorization",
        "connectionurl",
        "databaseurl",
        "credential",
        "credentials",
        "privatekey",
    }
)


class TaskExecutionValidationError(PersistenceValidationError):
    """Raised when a task request or service dependency is invalid."""


class TaskExecutionFailure(Exception):
    """A runner-controlled, safe failure classification.

    Only the bounded ``code`` crosses the persistence boundary.  The runner
    may still carry its own exception context for the caller, but this class
    intentionally exposes no free-form failure message to persistence.
    """

    def __init__(self, code: str) -> None:
        self.code = _clean_failure_code(code)
        super().__init__(self.code)


def _clean_required(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskExecutionValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def _clean_optional(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _clean_required(value, field_name)


def _clean_failure_code(value: object) -> str:
    if not isinstance(value, str) or not _FAILURE_CODE_RE.fullmatch(value):
        raise TaskExecutionValidationError(
            "failure_code must be 1-64 lowercase ASCII letters, digits, '_' or '-'."
        )
    return value


def _is_sensitive_key(key: str) -> bool:
    """Recognize common credential-bearing spellings, including camelCase."""

    compact = "".join(character for character in key.lower() if character.isalnum())
    return compact in _SENSITIVE_KEY_PARTS or any(
        compact.startswith(part) or compact.endswith(part)
        for part in _SENSITIVE_KEY_PARTS
    )


class _FrozenJsonObject(dict[str, object]):
    """A JSON-compatible dict that rejects all ordinary mutations.

    ``MappingProxyType`` would provide a read-only view but is not accepted by
    Python's standard ``json`` encoder.  A frozen dict subclass keeps the
    request both deeply immutable at normal application call sites and
    directly JSON serializable for downstream adapters.
    """

    __slots__ = ()

    def __init__(self, values: Mapping[str, object]) -> None:
        dict.__init__(self, values)

    @staticmethod
    def _reject(*_args: object, **_kwargs: object) -> None:
        raise TypeError("task request parameters are immutable")

    __setitem__ = _reject
    __delitem__ = _reject
    clear = _reject
    pop = _reject
    popitem = _reject
    setdefault = _reject
    update = _reject

    def __ior__(self, _other: object) -> _FrozenJsonObject:
        self._reject()
        return self


def _freeze_json(value: object, path: str) -> object:
    """Validate and deep-freeze the JSON value accepted in a task request."""

    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise TaskExecutionValidationError(
                    f"Parameter keys at '{path}' must be non-empty strings."
                )
            key = raw_key.strip()
            if _is_sensitive_key(key):
                raise TaskExecutionValidationError(
                    f"Sensitive parameter key '{key}' is not allowed."
                )
            if key in normalized:
                raise TaskExecutionValidationError(
                    f"Duplicate parameter key '{key}' at '{path}'."
                )
            normalized[key] = _freeze_json(raw_value, f"{path}.{key}")
        return _FrozenJsonObject(normalized)

    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        )

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise TaskExecutionValidationError(
                f"Parameter at '{path}' must be finite."
            )
        return value

    raise TaskExecutionValidationError(
        f"Parameter at '{path}' has unsupported type {type(value).__name__}."
    )


@dataclass(frozen=True, slots=True)
class InvestigationTaskRequest:
    """Immutable, source-bound input for one investigation execution."""

    run_id: str
    descriptor: DataSourceDescriptor
    requested_metric: str
    data_version: str | None = None
    parameters: Mapping[str, object] | None = None
    query_reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _clean_required(self.run_id, "run_id"))
        if not isinstance(self.descriptor, DataSourceDescriptor):
            raise TaskExecutionValidationError(
                "Field 'descriptor' must be a DataSourceDescriptor."
            )
        object.__setattr__(
            self,
            "requested_metric",
            _clean_required(self.requested_metric, "requested_metric"),
        )
        object.__setattr__(
            self,
            "data_version",
            _clean_optional(self.data_version, "data_version"),
        )
        object.__setattr__(
            self,
            "query_reference",
            _clean_optional(self.query_reference, "query_reference"),
        )

        if self.parameters is None:
            return
        if not isinstance(self.parameters, Mapping):
            raise TaskExecutionValidationError(
                "Field 'parameters' must be a mapping or None."
            )
        frozen_parameters = _freeze_json(self.parameters, "parameters")
        # _freeze_json returns a dict subclass for a mapping root.
        if not isinstance(frozen_parameters, _FrozenJsonObject):
            raise AssertionError("mapping parameters must normalize to an object")
        try:
            json.dumps(
                frozen_parameters,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise TaskExecutionValidationError(
                "Field 'parameters' must be JSON serializable."
            ) from exc
        object.__setattr__(self, "parameters", frozen_parameters)

    @property
    def source(self) -> DataSourceDescriptor:
        """Readable alias for callers that use ``source`` terminology."""

        return self.descriptor


class InvestigationTransactionCoordinatorProtocol(Protocol):
    """Short-transaction surface required by the task execution service."""

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
        ...

    def complete(
        self,
        handle: InvestigationRunHandle,
        summary: EvidenceDrivenRunSummary,
        *,
        query_reference: str | None = None,
    ) -> object:
        ...

    def fail(self, handle: InvestigationRunHandle, failure_code: str) -> object:
        ...


class InvestigationTaskRunner(Protocol):
    """Callable boundary for an injected Agent/runtime runner."""

    def __call__(self, request: InvestigationTaskRequest) -> EvidenceDrivenRunSummary:
        ...


TaskRunner: TypeAlias = Callable[
    [InvestigationTaskRequest], EvidenceDrivenRunSummary
]
TransactionCoordinatorProtocol = InvestigationTransactionCoordinatorProtocol


class InvestigationTaskExecutionService:
    """Execute one task around three independent coordinator operations."""

    def __init__(
        self,
        coordinator: InvestigationTransactionCoordinatorProtocol,
        runner: InvestigationTaskRunner | TaskRunner,
        *,
        default_failure_code: str = _DEFAULT_FAILURE_CODE,
    ) -> None:
        if coordinator is None or any(
            not callable(getattr(coordinator, name, None))
            for name in ("start", "complete", "fail")
        ):
            raise TaskExecutionValidationError(
                "coordinator must provide callable start, complete and fail methods."
            )
        if not callable(runner):
            raise TaskExecutionValidationError("runner must be callable.")
        self._coordinator = coordinator
        self._runner = runner
        self._default_failure_code = _clean_failure_code(default_failure_code)

    def execute(
        self,
        request: InvestigationTaskRequest,
        *,
        failure_code: str | None = None,
    ) -> EvidenceDrivenRunSummary:
        """Run one investigation with no database transaction around the runner.

        Request and optional caller-supplied failure code validation happen
        before ``start``.  Start errors therefore cannot accidentally trigger
        a runner or a second failure write.
        """

        validated_request = self._validate_request(request)
        selected_failure_code = (
            self._default_failure_code
            if failure_code is None
            else _clean_failure_code(failure_code)
        )

        # Intentionally outside the runner try/except: a start failure means
        # no run handle exists and must not invoke fail or the runner.
        handle = self._coordinator.start(
            validated_request.descriptor,
            run_id=validated_request.run_id,
            requested_metric=validated_request.requested_metric,
            data_version=validated_request.data_version,
            parameters=validated_request.parameters,
            query_reference=validated_request.query_reference,
        )

        try:
            summary = self._runner(validated_request)
            if not isinstance(summary, EvidenceDrivenRunSummary):
                raise TaskExecutionValidationError(
                    "runner must return an EvidenceDrivenRunSummary."
                )
            # Re-run the immutable summary contract before crossing into the
            # writer.  This protects against deliberate object.__setattr__
            # bypasses and keeps completion strict without inventing facts.
            try:
                summary.__post_init__()
            except Exception as exc:
                raise TaskExecutionValidationError(
                    "runner returned an invalid EvidenceDrivenRunSummary."
                ) from exc
        except TaskExecutionFailure as exc:
            self._persist_failure_preserving_runner_error(handle, exc.code)
            raise
        except Exception:
            self._persist_failure_preserving_runner_error(
                handle,
                selected_failure_code,
            )
            raise

        # Deliberately outside the runner exception handler.  If completion
        # fails after partial persistence, converting it into ``fail`` would
        # overwrite facts or misrepresent the durable state.
        self._coordinator.complete(
            handle,
            summary,
            query_reference=validated_request.query_reference,
        )
        return summary

    @staticmethod
    def _validate_request(request: object) -> InvestigationTaskRequest:
        if not isinstance(request, InvestigationTaskRequest):
            raise TaskExecutionValidationError(
                "request must be an InvestigationTaskRequest."
            )
        # Revalidate an object that may have been altered through a deliberate
        # object.__setattr__ bypass before any coordinator call.
        try:
            request.__post_init__()
        except TaskExecutionValidationError:
            raise
        except Exception as exc:
            raise TaskExecutionValidationError(
                "request violates the InvestigationTaskRequest contract."
            ) from exc
        return request

    def _persist_failure_preserving_runner_error(
        self,
        handle: InvestigationRunHandle,
        failure_code: str,
    ) -> None:
        """Try the bounded failure write without replacing the runner error."""

        try:
            self._coordinator.fail(handle, failure_code)
        except Exception:
            # The runner exception is the causal error visible to the caller.
            # In particular, do not expose or persist a failure implementation's
            # free-form message as a replacement failure classification.
            pass


# Concise aliases for application call sites; these are one implementation,
# not a second worker/runtime.
TaskExecutionService = InvestigationTaskExecutionService
TaskRequest = InvestigationTaskRequest


__all__ = [
    "InvestigationTaskExecutionService",
    "InvestigationTaskRequest",
    "InvestigationTaskRunner",
    "InvestigationTransactionCoordinatorProtocol",
    "TaskExecutionFailure",
    "TaskExecutionService",
    "TaskExecutionValidationError",
    "TaskRequest",
    "TaskRunner",
    "TransactionCoordinatorProtocol",
]
