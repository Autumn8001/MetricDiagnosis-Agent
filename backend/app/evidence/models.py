"""Domain models and role contracts for MetricSleuth Evidence."""

from dataclasses import dataclass
import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Sequence

from app.analytics.models import DateRange
from app.observations.models import ObservationStatus


class EvidenceError(Exception):
    """Base exception for evidence domain and promotion errors."""


class EvidenceValidationError(EvidenceError):
    """Raised when an Evidence instance fails domain validation constraints."""


class EvidenceRole(StrEnum):
    """Role classification for an Evidence in the investigation chain.

    Note: EvidenceRole represents the evidential purpose (supporting a data anomaly,
    serving as a negative control, or marking a boundary/limitation).
    It does NOT represent business causality or confidence.
    """

    SUPPORTING = "supporting"
    NEGATIVE_CONTROL = "negative_control"
    LIMITATION = "limitation"


# Allowed EvidenceRole mappings per ObservationStatus (Immutable Policy)
_ALLOWED_ROLE_MAP: Mapping[ObservationStatus, frozenset[EvidenceRole]] = MappingProxyType({
    ObservationStatus.ANOMALOUS: frozenset({EvidenceRole.SUPPORTING}),
    ObservationStatus.NORMAL: frozenset({EvidenceRole.SUPPORTING, EvidenceRole.NEGATIVE_CONTROL}),
    ObservationStatus.INCONCLUSIVE: frozenset({EvidenceRole.LIMITATION}),
    ObservationStatus.INSUFFICIENT_EVIDENCE: frozenset({EvidenceRole.LIMITATION}),
    ObservationStatus.FAILED: frozenset({EvidenceRole.LIMITATION}),
})


def _derive_evidence_id(observation_id: str, role: EvidenceRole) -> str:
    """Internal helper to derive deterministic evidence_id from observation_id and role."""
    return f"evidence:{observation_id}:{role.value}"


def _validate_non_empty_str(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class Evidence:
    """Immutable domain model representing an explicit evidence promoted from an Observation.

    Attributes:
        evidence_id: Deterministic identifier derived from observation_id and role ('evidence:{obs_id}:{role}').
        observation_id: Originating observation ID.
        role: Evidential role (supporting, negative_control, limitation).
        tool_name: Name of the analytics tool that produced the original observation.
        tool_call_id: Identifier of the tool call invocation.
        metric: Metric ID observed (e.g. 'sales', 'conversion_rate').
        current_period: Current evaluation date range.
        baseline_period: Baseline comparison date range.
        filters: Immutable mapping of dimension filters applied.
        group_by: Immutable tuple of grouping dimensions.
        dimensions: Immutable mapping of segment dimension values for this row.
        current_value: Current metric value (or None for failed/unavailable).
        baseline_value: Baseline metric value (or None for failed/unavailable).
        relative_change: Relative change ratio (or None for failed/insufficient).
        unit: Metric unit ('usd', 'count', 'ratio', etc.).
        sample_size: Baseline sample size / daily average sessions (or None).
        observation_status: Original observation evaluation status.
        source_status: Raw source tool status ('ok', 'insufficient_data', 'failed', etc.).
        query_or_result_reference: Traceable reference string.
        created_at: Timezone-aware UTC timestamp of evidence creation.
        error_code: Error code for failed evidence (None for non-failed).
        error_message: Error message for failed evidence (None for non-failed).
    """

    evidence_id: str
    observation_id: str
    role: EvidenceRole
    tool_name: str
    tool_call_id: str
    metric: str
    current_period: DateRange
    baseline_period: DateRange
    filters: Mapping[str, str]
    group_by: tuple[str, ...]
    dimensions: Mapping[str, str]
    current_value: Decimal | None
    baseline_value: Decimal | None
    relative_change: Decimal | None
    unit: str
    sample_size: Decimal | None
    observation_status: ObservationStatus
    source_status: str
    query_or_result_reference: str
    created_at: datetime.datetime
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        # 1. Validate EvidenceRole
        if not isinstance(self.role, EvidenceRole):
            raise EvidenceValidationError(f"Field 'role' must be an EvidenceRole enum, got {type(self.role).__name__}.")

        # 2. Validate ObservationStatus
        if not isinstance(self.observation_status, ObservationStatus):
            raise EvidenceValidationError(
                f"Field 'observation_status' must be an ObservationStatus enum, got {type(self.observation_status).__name__}."
            )

        # 3. Validate Role & Status compatibility
        allowed_roles = _ALLOWED_ROLE_MAP.get(self.observation_status)
        if allowed_roles is None:
            raise EvidenceValidationError(f"Unknown observation status '{self.observation_status}'.")
        if self.role not in allowed_roles:
            allowed_names = ", ".join(sorted(r.value for r in allowed_roles))
            raise EvidenceValidationError(
                f"Incompatible EvidenceRole '{self.role.value}' for observation_status '{self.observation_status.value}'. "
                f"Allowed roles: [{allowed_names}]."
            )

        # 4. Clean & validate observation_id and evidence_id matching
        clean_obs_id = _validate_non_empty_str(self.observation_id, "observation_id")
        expected_evidence_id = _derive_evidence_id(clean_obs_id, self.role)
        clean_evidence_id = _validate_non_empty_str(self.evidence_id, "evidence_id")
        if clean_evidence_id != expected_evidence_id:
            raise EvidenceValidationError(
                f"Invalid evidence_id '{clean_evidence_id}'. Expected '{expected_evidence_id}' "
                f"derived from observation_id and role."
            )

        # 5. Validate other non-empty string fields
        clean_tool_name = _validate_non_empty_str(self.tool_name, "tool_name")
        clean_tool_call_id = _validate_non_empty_str(self.tool_call_id, "tool_call_id")
        clean_metric = _validate_non_empty_str(self.metric, "metric")
        clean_unit = _validate_non_empty_str(self.unit, "unit")
        clean_source_status = _validate_non_empty_str(self.source_status, "source_status")
        clean_ref = _validate_non_empty_str(self.query_or_result_reference, "query_or_result_reference")

        object.__setattr__(self, "evidence_id", clean_evidence_id)
        object.__setattr__(self, "observation_id", clean_obs_id)
        object.__setattr__(self, "tool_name", clean_tool_name)
        object.__setattr__(self, "tool_call_id", clean_tool_call_id)
        object.__setattr__(self, "metric", clean_metric)
        object.__setattr__(self, "unit", clean_unit)
        object.__setattr__(self, "source_status", clean_source_status)
        object.__setattr__(self, "query_or_result_reference", clean_ref)
        object.__setattr__(self, "source_status", clean_source_status)
        object.__setattr__(self, "query_or_result_reference", clean_ref)

        # Validate DateRange
        if not isinstance(self.current_period, DateRange):
            raise EvidenceValidationError("Field 'current_period' must be a DateRange instance.")
        if not isinstance(self.baseline_period, DateRange):
            raise EvidenceValidationError("Field 'baseline_period' must be a DateRange instance.")

        # Validate timezone-aware created_at and normalize to UTC
        if not isinstance(self.created_at, datetime.datetime):
            raise EvidenceValidationError("Field 'created_at' must be a datetime instance.")
        if self.created_at.tzinfo is None or self.created_at.tzinfo.utcoffset(self.created_at) is None:
            raise EvidenceValidationError("Field 'created_at' must be a timezone-aware datetime.")
        utc_created_at = self.created_at.astimezone(datetime.timezone.utc)
        object.__setattr__(self, "created_at", utc_created_at)

        # Validate and defensively freeze filters
        if self.filters is None:
            frozen_filters = MappingProxyType({})
        elif isinstance(self.filters, Mapping):
            for k, v in self.filters.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise EvidenceValidationError("All keys and values in 'filters' must be strings.")
            frozen_filters = MappingProxyType(dict(self.filters))
        else:
            raise EvidenceValidationError("Field 'filters' must be a Mapping[str, str].")
        object.__setattr__(self, "filters", frozen_filters)

        # Validate and defensively freeze dimensions
        if self.dimensions is None:
            frozen_dimensions = MappingProxyType({})
        elif isinstance(self.dimensions, Mapping):
            for k, v in self.dimensions.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise EvidenceValidationError("All keys and values in 'dimensions' must be strings.")
            frozen_dimensions = MappingProxyType(dict(self.dimensions))
        else:
            raise EvidenceValidationError("Field 'dimensions' must be a Mapping[str, str].")
        object.__setattr__(self, "dimensions", frozen_dimensions)

        # Validate and defensively freeze group_by
        if self.group_by is None:
            frozen_group_by = ()
        elif isinstance(self.group_by, (tuple, list)):
            for g in self.group_by:
                if not isinstance(g, str) or not g.strip():
                    raise EvidenceValidationError("All items in 'group_by' must be non-empty strings.")
            frozen_group_by = tuple(self.group_by)
        else:
            raise EvidenceValidationError("Field 'group_by' must be a tuple or list of strings.")
        object.__setattr__(self, "group_by", frozen_group_by)

        # Validate failure status numerical invariants and error fields
        if self.observation_status == ObservationStatus.FAILED:
            if self.current_value is not None:
                raise EvidenceValidationError("Failed evidence must have 'current_value' set to None.")
            if self.baseline_value is not None:
                raise EvidenceValidationError("Failed evidence must have 'baseline_value' set to None.")
            if self.relative_change is not None:
                raise EvidenceValidationError("Failed evidence must have 'relative_change' set to None.")
            if self.sample_size is not None:
                raise EvidenceValidationError("Failed evidence must have 'sample_size' set to None.")
            if self.error_code is None or not str(self.error_code).strip():
                raise EvidenceValidationError("Failed evidence must have a non-empty 'error_code'.")
            if self.error_message is None or not str(self.error_message).strip():
                raise EvidenceValidationError("Failed evidence must have a non-empty 'error_message'.")
            object.__setattr__(self, "error_code", str(self.error_code).strip())
            object.__setattr__(self, "error_message", str(self.error_message).strip())
        else:
            if self.error_code is not None or self.error_message is not None:
                raise EvidenceValidationError(
                    f"Non-failed evidence ({self.observation_status}) must not have 'error_code' or 'error_message'."
                )
