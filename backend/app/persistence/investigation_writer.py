"""Application-layer orchestration for persisting an audited diagnosis run.

This module is deliberately narrower than the DB repository.  It accepts an
already verified :class:`EvidenceDrivenRunSummary`, binds every row to one
immutable :class:`DataSourceDescriptor`, and sequences the existing repository
methods.  It neither opens a connection nor owns a transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
import math
import re
from typing import Protocol

from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary
from app.agent_runtime.investigation_runtime import InvestigationToolTraceEntry
from app.data_sources.capabilities import DataSourceDescriptor
from app.diagnosis.models import Diagnosis
from app.evidence.models import Evidence
from app.observations.models import Observation
from app.persistence.models import (
    PersistenceValidationError,
    RunStatus,
)


class InvestigationPersistenceValidationError(PersistenceValidationError):
    """Raised when a run summary cannot be safely persisted."""


# Readable aliases for callers that use writer-oriented terminology.  There is
# still one exception hierarchy and one validation boundary.
InvestigationWriterValidationError = InvestigationPersistenceValidationError


class ApplicationStateRepositoryProtocol(Protocol):
    """Minimum repository surface required by the orchestration boundary."""

    def upsert_data_source(
        self,
        source: DataSourceDescriptor,
        *,
        data_version: str | None = None,
    ) -> object:
        ...

    def create_investigation_run(
        self,
        *,
        run_id: str,
        source_id: str,
        environment: object,
        requested_metric: str,
        data_version: str | None = None,
        query_reference: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> object:
        ...

    def transition_investigation_run(
        self,
        *,
        run_id: str,
        target_status: RunStatus,
    ) -> object:
        ...

    def fail_investigation_run(
        self,
        *,
        run_id: str,
        failure_code: str,
    ) -> RunStatus:
        ...

    def record_tool_call(
        self,
        tool_call_id: str,
        investigation_run_id: str,
        source_id: str,
        environment: object,
        tool_name: str,
        *,
        status: RunStatus,
        arguments: Mapping[str, object],
        data_version: str | None = None,
        idempotent: bool = False,
    ) -> object:
        ...

    def record_observation(
        self,
        observation: Observation,
        investigation_run_id: str,
        source_id: str,
        environment: object,
        *,
        data_version: str | None = None,
        idempotent: bool = False,
    ) -> object:
        ...

    def lock_running_run(
        self, run_id: str, source_id: str, environment: object,
        data_version: str | None = None,
    ) -> None:
        ...

    def get_run_fact_ids(self, run_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        ...

    def record_evidence(
        self,
        evidence: Evidence,
        investigation_run_id: str,
        source_id: str,
        environment: object,
        *,
        data_version: str | None = None,
    ) -> object:
        ...

    def record_diagnosis(
        self,
        diagnosis: Diagnosis,
        investigation_run_id: str,
        source_id: str,
        environment: object,
        *,
        data_version: str | None = None,
        query_reference: str | None = None,
    ) -> object:
        ...


_SENSITIVE_KEY_PARTS = frozenset(
    {
        "password",
        "token",
        "secret",
        "apikey",
        "authorization",
        "connectionurl",
        "databaseurl",
    }
)
_FAILURE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _clean_required(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvestigationPersistenceValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def _clean_optional(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _clean_required(value, field_name)


def _clean_failure_code(value: object) -> str:
    """Keep the writer's failure boundary safe for every repository protocol impl."""

    if not isinstance(value, str) or not _FAILURE_CODE_RE.fullmatch(value):
        raise InvestigationPersistenceValidationError(
            "failure_code must be 1-64 lowercase ASCII letters, digits, '_' or '-'."
        )
    return value


def _sensitive_key(key: str) -> bool:
    compact = "".join(character for character in key.lower() if character.isalnum())
    return compact in _SENSITIVE_KEY_PARTS or any(
        compact.startswith(part) or compact.endswith(part)
        for part in _SENSITIVE_KEY_PARTS
    )


def _validate_parameter_value(value: object, path: str) -> None:
    """Validate request parameters before the first repository write."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or not key.strip():
                raise InvestigationPersistenceValidationError(
                    f"Parameter keys at '{path}' must be non-empty strings."
                )
            if _sensitive_key(key.strip()):
                raise InvestigationPersistenceValidationError(
                    f"Sensitive parameter key '{key}' is not allowed."
                )
            _validate_parameter_value(nested, f"{path}.{key.strip()}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _validate_parameter_value(nested, f"{path}[{index}]")
        return
    if isinstance(value, Enum):
        _validate_parameter_value(value.value, path)
        return
    if value is None or isinstance(value, (str, int, float, bool, Decimal, date, datetime)):
        if isinstance(value, float) and not math.isfinite(value):
            raise InvestigationPersistenceValidationError(
                f"Parameter at '{path}' must be finite."
            )
        return
    raise InvestigationPersistenceValidationError(
        f"Parameter at '{path}' has unsupported type {type(value).__name__}."
    )


def _validate_parameters(parameters: Mapping[str, object] | None) -> None:
    if parameters is None:
        return
    if not isinstance(parameters, Mapping):
        raise InvestigationPersistenceValidationError(
            "Field 'parameters' must be a mapping or None."
        )
    _validate_parameter_value(parameters, "parameters")
    try:
        json.dumps(parameters, default=str, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvestigationPersistenceValidationError(
            "Field 'parameters' must be JSON serializable."
        ) from exc


def _validate_summary(summary: object) -> EvidenceDrivenRunSummary:
    """Re-check the cross-boundary invariants immediately before any write."""

    if not isinstance(summary, EvidenceDrivenRunSummary):
        raise InvestigationPersistenceValidationError(
            "summary must be an EvidenceDrivenRunSummary."
        )

    # The summary constructor performs this same validation.  Rechecking here
    # makes this boundary fail closed even if a caller deliberately bypassed a
    # frozen dataclass with object.__setattr__.
    try:
        summary.__post_init__()
    except Exception as exc:
        if isinstance(exc, InvestigationPersistenceValidationError):
            raise
        raise InvestigationPersistenceValidationError(
            "EvidenceDrivenRunSummary violates its verified catalog contract."
        ) from exc

    investigation = summary.investigation
    catalog = summary.observation_catalog
    trace_by_call_id = {entry.tool_call_id: entry for entry in investigation.tool_trace}
    if len(trace_by_call_id) != len(investigation.tool_trace):
        raise InvestigationPersistenceValidationError(
            "Investigation trace contains duplicate tool_call_id values."
        )

    catalog_by_id: dict[str, Observation] = {}
    for observation in catalog:
        if observation.observation_id in catalog_by_id:
            raise InvestigationPersistenceValidationError(
                f"Duplicate observation_id '{observation.observation_id}'."
            )
        catalog_by_id[observation.observation_id] = observation
        trace_entry = trace_by_call_id.get(observation.tool_call_id)
        if trace_entry is None or trace_entry.tool_name != observation.tool_name:
            raise InvestigationPersistenceValidationError(
                "Observation does not match a verified trace tool call: "
                f"{observation.observation_id}."
            )
        if observation.observation_id not in trace_entry.observation_ids:
            raise InvestigationPersistenceValidationError(
                "Observation is not listed by its verified trace tool call: "
                f"{observation.observation_id}."
            )

    if tuple(catalog_by_id) != investigation.observation_ids:
        raise InvestigationPersistenceValidationError(
            "Observation catalog order does not match the verified trace."
        )

    evidence_ids: set[str] = set()
    for evidence in summary.composition.evidence:
        if not isinstance(evidence, Evidence):
            raise InvestigationPersistenceValidationError(
                "Composition evidence must contain Evidence values."
            )
        if evidence.evidence_id in evidence_ids:
            raise InvestigationPersistenceValidationError(
                f"Duplicate evidence_id '{evidence.evidence_id}'."
            )
        evidence_ids.add(evidence.evidence_id)
        observation = catalog_by_id.get(evidence.observation_id)
        if observation is None:
            raise InvestigationPersistenceValidationError(
                "Evidence references an observation absent from the verified catalog: "
                f"{evidence.observation_id}."
            )
        if (
            evidence.tool_call_id != observation.tool_call_id
            or evidence.tool_name != observation.tool_name
        ):
            raise InvestigationPersistenceValidationError(
                "Evidence tool identity does not match its catalog Observation: "
                f"{evidence.evidence_id}."
            )

    diagnosis = summary.composition.diagnosis
    if not isinstance(diagnosis, Diagnosis):
        raise InvestigationPersistenceValidationError(
            "Composition diagnosis must be a Diagnosis."
        )
    diagnosis_evidence_ids = tuple(diagnosis.evidence_ids)
    if len(diagnosis_evidence_ids) != len(set(diagnosis_evidence_ids)):
        raise InvestigationPersistenceValidationError(
            "Diagnosis evidence_ids must not contain duplicates."
        )
    missing_evidence_ids = set(diagnosis_evidence_ids) - evidence_ids
    if missing_evidence_ids:
        raise InvestigationPersistenceValidationError(
            "Diagnosis references Evidence absent from the composition: "
            + ", ".join(sorted(missing_evidence_ids))
        )
    return summary


@dataclass(frozen=True)
class EvidenceDrivenRunPersistenceWriter:
    """Persist one verified runtime summary against one source descriptor."""

    repository: ApplicationStateRepositoryProtocol
    descriptor: DataSourceDescriptor
    data_version: str | None = None

    def __post_init__(self) -> None:
        if self.repository is None:
            raise InvestigationPersistenceValidationError(
                "repository must be an established application-state repository."
            )
        if not isinstance(self.descriptor, DataSourceDescriptor):
            raise InvestigationPersistenceValidationError(
                "descriptor must be a DataSourceDescriptor."
            )
        object.__setattr__(self, "data_version", _clean_optional(self.data_version, "data_version"))

    def start(
        self,
        *,
        run_id: str,
        requested_metric: str,
        parameters: Mapping[str, object] | None = None,
        query_reference: str | None = None,
    ) -> str:
        """Create and start a run before any model or fact-producing work.

        This is intentionally a short lifecycle operation.  It validates only
        the run request, then persists ``source -> queued -> running`` using
        the writer's one immutable descriptor.  No transaction is opened or
        retained here; the caller owns that boundary.
        """

        clean_run_id = _clean_required(run_id, "run_id")
        clean_metric = _clean_required(requested_metric, "requested_metric")
        clean_query_reference = _clean_optional(query_reference, "query_reference")
        _validate_parameters(parameters)

        source_id = self.descriptor.source_id
        environment = self.descriptor.environment
        repository = self.repository
        repository.upsert_data_source(
            self.descriptor,
            data_version=self.data_version,
        )
        repository.create_investigation_run(
            run_id=clean_run_id,
            source_id=source_id,
            environment=environment,
            requested_metric=clean_metric,
            data_version=self.data_version,
            query_reference=clean_query_reference,
            parameters=parameters,
        )
        repository.transition_investigation_run(
            run_id=clean_run_id,
            target_status=RunStatus.RUNNING,
        )
        return clean_run_id

    def complete(
        self,
        summary: EvidenceDrivenRunSummary,
        *,
        run_id: str,
        query_reference: str | None = None,
        checkpointed: bool = False,
    ) -> str:
        """Persist facts and diagnosis, then mark an already-running run done.

        The complete summary and every trace/evidence cross-reference are
        checked before the first fact write.  This method never re-creates the
        source or run and never silently turns a repository error into a
        successful run.
        """

        clean_run_id = _clean_required(run_id, "run_id")
        clean_query_reference = _clean_optional(query_reference, "query_reference")
        verified_summary = _validate_summary(summary)
        if type(checkpointed) is not bool:
            raise InvestigationPersistenceValidationError("checkpointed must be a boolean.")

        source_id = self.descriptor.source_id
        environment = self.descriptor.environment
        repository = self.repository

        if checkpointed:
            repository.lock_running_run(
                clean_run_id, source_id, environment, data_version=self.data_version,
            )
            saved_calls, saved_observations = repository.get_run_fact_ids(clean_run_id)
            if (
                not set(saved_calls).issubset(verified_summary.investigation.tool_call_ids)
                or not set(saved_observations).issubset(verified_summary.investigation.observation_ids)
            ):
                raise InvestigationPersistenceValidationError(
                    "Final summary omits previously persisted investigation facts."
                )

        catalog_by_call_id: dict[str, list[Observation]] = {}
        for observation in verified_summary.observation_catalog:
            catalog_by_call_id.setdefault(observation.tool_call_id, []).append(observation)

        # Persist the audited trace in call order.  Each call's observations
        # immediately follow it; no evidence can precede the full catalog.
        for trace_entry in verified_summary.investigation.tool_trace:
            replay_options = {"idempotent": True} if checkpointed else {}
            repository.record_tool_call(
                trace_entry.tool_call_id,
                clean_run_id,
                source_id,
                environment,
                trace_entry.tool_name,
                status=RunStatus.SUCCEEDED,
                arguments=trace_entry.arguments,
                data_version=self.data_version,
                **replay_options,
            )
            for observation in catalog_by_call_id.get(trace_entry.tool_call_id, ()):
                repository.record_observation(
                    observation,
                    clean_run_id,
                    source_id,
                    environment,
                    data_version=self.data_version,
                    **replay_options,
                )

        for evidence in verified_summary.composition.evidence:
            repository.record_evidence(
                evidence,
                clean_run_id,
                source_id,
                environment,
                data_version=self.data_version,
            )

        repository.record_diagnosis(
            verified_summary.composition.diagnosis,
            clean_run_id,
            source_id,
            environment,
            data_version=self.data_version,
            query_reference=clean_query_reference,
        )
        repository.transition_investigation_run(
            run_id=clean_run_id,
            target_status=RunStatus.SUCCEEDED,
        )
        return clean_run_id

    def checkpoint(
        self,
        trace_entry: InvestigationToolTraceEntry,
        observations: Sequence[Observation],
        *,
        run_id: str,
    ) -> None:
        """Save one completed tool step without inventing Evidence or Diagnosis.

        The caller commits this independently of the model call. The repository
        locks the source-bound running run; exact replays are accepted while
        conflicting IDs fail closed. A step is stored all-or-nothing.
        """

        clean_run_id = _clean_required(run_id, "run_id")
        if not isinstance(trace_entry, InvestigationToolTraceEntry):
            raise InvestigationPersistenceValidationError("Invalid checkpoint trace entry.")
        if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
            raise InvestigationPersistenceValidationError("Checkpoint observations must be a sequence.")
        snapshot = tuple(observations)
        try:
            trace_entry.__post_init__()
            for observation in snapshot:
                if not isinstance(observation, Observation):
                    raise InvestigationPersistenceValidationError("Invalid checkpoint Observation.")
                observation.__post_init__()
        except Exception as exc:
            raise InvestigationPersistenceValidationError("Invalid checkpoint facts.") from exc
        if tuple(item.observation_id for item in snapshot) != trace_entry.observation_ids:
            raise InvestigationPersistenceValidationError("Checkpoint Observation IDs do not match trace.")
        if any(
            item.tool_call_id != trace_entry.tool_call_id or item.tool_name != trace_entry.tool_name
            for item in snapshot
        ):
            raise InvestigationPersistenceValidationError("Checkpoint tool identities do not match.")

        repository = self.repository
        source_id = self.descriptor.source_id
        environment = self.descriptor.environment
        repository.lock_running_run(
            clean_run_id, source_id, environment, data_version=self.data_version,
        )
        repository.record_tool_call(
            trace_entry.tool_call_id, clean_run_id, source_id, environment,
            trace_entry.tool_name, status=RunStatus.SUCCEEDED,
            arguments=trace_entry.arguments, data_version=self.data_version,
            idempotent=True,
        )
        for observation in snapshot:
            repository.record_observation(
                observation, clean_run_id, source_id, environment,
                data_version=self.data_version, idempotent=True,
            )

    def fail(self, *, run_id: str, failure_code: str) -> RunStatus:
        """Mark a queued/running run failed using only a controlled code."""

        clean_run_id = _clean_required(run_id, "run_id")
        clean_failure_code = _clean_failure_code(failure_code)
        return self.repository.fail_investigation_run(
            run_id=clean_run_id,
            failure_code=clean_failure_code,
        )

    def write(
        self,
        summary: EvidenceDrivenRunSummary,
        *,
        run_id: str,
        requested_metric: str,
        parameters: Mapping[str, object] | None = None,
        query_reference: str | None = None,
    ) -> str:
        """Backward-compatible one-shot composition of ``start`` + ``complete``."""

        # Unlike ``start`` (which intentionally precedes a model call), a
        # one-shot caller already has every fact. Validate it before creating
        # a run so malformed historical data cannot leave a stranded running
        # record merely because it entered through the compatibility helper.
        _validate_summary(summary)
        clean_run_id = self.start(
            run_id=run_id,
            requested_metric=requested_metric,
            parameters=parameters,
            query_reference=query_reference,
        )
        return self.complete(
            summary,
            run_id=clean_run_id,
            query_reference=query_reference,
        )


def persist_evidence_driven_run(
    repository: ApplicationStateRepositoryProtocol,
    descriptor: DataSourceDescriptor,
    summary: EvidenceDrivenRunSummary,
    *,
    run_id: str,
    requested_metric: str,
    data_version: str | None = None,
    parameters: Mapping[str, object] | None = None,
    query_reference: str | None = None,
) -> str:
    """Convenience function for one-shot persistence of an audited run."""

    return EvidenceDrivenRunPersistenceWriter(
        repository,
        descriptor,
        data_version=data_version,
    ).write(
        summary,
        run_id=run_id,
        requested_metric=requested_metric,
        parameters=parameters,
        query_reference=query_reference,
    )


__all__ = [
    "ApplicationStateRepositoryProtocol",
    "EvidenceDrivenRunPersistenceWriter",
    "InvestigationPersistenceValidationError",
    "InvestigationWriterValidationError",
    "persist_evidence_driven_run",
]
