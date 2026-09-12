"""Domain models and status contracts for MetricSleuth Observations."""

from dataclasses import dataclass
import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Sequence

from app.analytics.models import DateRange


class ObservationError(Exception):
    """Base exception for observation domain and mapping errors."""


class ObservationValidationError(ObservationError):
    """Raised when an Observation fails domain validation constraints."""


class ObservationStatus(StrEnum):
    """Standard evaluation status for an observation.

    Note: 'anomalous' indicates that the metric meets the material decline threshold
    under the data baseline. It does NOT represent root cause or business causality.
    """

    NORMAL = "normal"
    ANOMALOUS = "anomalous"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    FAILED = "failed"


def _validate_non_empty_str(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ObservationValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True)
class Observation:
    """Immutable domain model representing a traceable observation from a tool result.

    Attributes:
        observation_id: Deterministic unique ID for this observation within a tool call.
        tool_name: Name of the analytics tool that produced this observation.
        tool_call_id: Unique identifier of the tool call invocation.
        metric: Metric ID observed (e.g. 'sales', 'conversion_rate').
        current_period: Current evaluation date range.
        baseline_period: Baseline comparison date range.
        filters: Immutable mapping of dimension filters applied to the query.
        group_by: Immutable tuple of grouping dimensions.
        dimensions: Immutable mapping of segment dimension values for this specific row.
        current_value: Aggregated current metric value (or None if unavailable/failed).
        baseline_value: Aggregated baseline metric value (or None if unavailable/failed).
        relative_change: Relative change ratio (or None if unavailable/insufficient/failed).
        unit: Metric unit ('usd', 'count', 'ratio', etc.).
        sample_size: Baseline sample size / daily average sessions (or None).
        source_status: Raw evaluation status from the source tool ('ok', 'insufficient_data', etc.).
        status: Standardized observation status contract.
        query_or_result_reference: Traceable reference string (e.g. query hash, URI, summary).
        created_at: Timezone-aware UTC timestamp of observation creation.
        error_code: Error code if tool failed (None for successful observations).
        error_message: Error message if tool failed (None for successful observations).
    """

    observation_id: str
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
    source_status: str
    status: ObservationStatus
    query_or_result_reference: str
    created_at: datetime.datetime
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        # Validate non-empty string fields
        clean_obs_id = _validate_non_empty_str(self.observation_id, "observation_id")
        clean_tool_name = _validate_non_empty_str(self.tool_name, "tool_name")
        clean_tool_call_id = _validate_non_empty_str(self.tool_call_id, "tool_call_id")
        clean_metric = _validate_non_empty_str(self.metric, "metric")
        clean_unit = _validate_non_empty_str(self.unit, "unit")
        clean_source_status = _validate_non_empty_str(self.source_status, "source_status")
        clean_ref = _validate_non_empty_str(self.query_or_result_reference, "query_or_result_reference")

        object.__setattr__(self, "observation_id", clean_obs_id)
        object.__setattr__(self, "tool_name", clean_tool_name)
        object.__setattr__(self, "tool_call_id", clean_tool_call_id)
        object.__setattr__(self, "metric", clean_metric)
        object.__setattr__(self, "unit", clean_unit)
        object.__setattr__(self, "source_status", clean_source_status)
        object.__setattr__(self, "query_or_result_reference", clean_ref)

        # Validate DateRange
        if not isinstance(self.current_period, DateRange):
            raise ObservationValidationError("Field 'current_period' must be a DateRange instance.")
        if not isinstance(self.baseline_period, DateRange):
            raise ObservationValidationError("Field 'baseline_period' must be a DateRange instance.")

        # Validate status enum
        if not isinstance(self.status, ObservationStatus):
            raise ObservationValidationError(f"Field 'status' must be an ObservationStatus enum, got {type(self.status).__name__}.")

        # Validate timezone-aware created_at and normalize to UTC
        if not isinstance(self.created_at, datetime.datetime):
            raise ObservationValidationError("Field 'created_at' must be a datetime instance.")
        if self.created_at.tzinfo is None or self.created_at.tzinfo.utcoffset(self.created_at) is None:
            raise ObservationValidationError("Field 'created_at' must be a timezone-aware datetime.")
        utc_created_at = self.created_at.astimezone(datetime.timezone.utc)
        object.__setattr__(self, "created_at", utc_created_at)

        # Validate and freeze filters
        if self.filters is None:
            frozen_filters = MappingProxyType({})
        elif isinstance(self.filters, Mapping):
            for k, v in self.filters.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise ObservationValidationError("All keys and values in 'filters' must be strings.")
            frozen_filters = MappingProxyType(dict(self.filters))
        else:
            raise ObservationValidationError("Field 'filters' must be a Mapping[str, str].")
        object.__setattr__(self, "filters", frozen_filters)

        # Validate and freeze dimensions
        if self.dimensions is None:
            frozen_dimensions = MappingProxyType({})
        elif isinstance(self.dimensions, Mapping):
            for k, v in self.dimensions.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise ObservationValidationError("All keys and values in 'dimensions' must be strings.")
            frozen_dimensions = MappingProxyType(dict(self.dimensions))
        else:
            raise ObservationValidationError("Field 'dimensions' must be a Mapping[str, str].")
        object.__setattr__(self, "dimensions", frozen_dimensions)

        # Validate and freeze group_by
        if self.group_by is None:
            frozen_group_by = ()
        elif isinstance(self.group_by, (tuple, list)):
            for g in self.group_by:
                if not isinstance(g, str) or not g.strip():
                    raise ObservationValidationError("All items in 'group_by' must be non-empty strings.")
            frozen_group_by = tuple(self.group_by)
        else:
            raise ObservationValidationError("Field 'group_by' must be a tuple or list of strings.")
        object.__setattr__(self, "group_by", frozen_group_by)

        # Validate error and numerical fields according to status
        if self.status == ObservationStatus.FAILED:
            if self.current_value is not None:
                raise ObservationValidationError("Failed observation must have 'current_value' set to None.")
            if self.baseline_value is not None:
                raise ObservationValidationError("Failed observation must have 'baseline_value' set to None.")
            if self.relative_change is not None:
                raise ObservationValidationError("Failed observation must have 'relative_change' set to None.")
            if self.sample_size is not None:
                raise ObservationValidationError("Failed observation must have 'sample_size' set to None.")
            if self.error_code is None or not str(self.error_code).strip():
                raise ObservationValidationError("Failed observation must have a non-empty 'error_code'.")
            if self.error_message is None or not str(self.error_message).strip():
                raise ObservationValidationError("Failed observation must have a non-empty 'error_message'.")
            object.__setattr__(self, "error_code", str(self.error_code).strip())
            object.__setattr__(self, "error_message", str(self.error_message).strip())
        else:
            if self.error_code is not None or self.error_message is not None:
                raise ObservationValidationError(
                    f"Non-failed observation ({self.status}) must not have 'error_code' or 'error_message'."
                )
