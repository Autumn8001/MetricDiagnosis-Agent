"""Mapper functions transforming MetricQueryResults into Observation domain models."""

import datetime
from decimal import Decimal
from typing import Mapping, Sequence

from app.analytics.models import DateRange, MetricQueryRow, MetricQueryResult, RelatedMetricQueryResult
from app.observations.models import (
    Observation,
    ObservationError,
    ObservationStatus,
    ObservationValidationError,
)


def classify_metric_row_status(row: MetricQueryRow) -> ObservationStatus:
    """Classify a MetricQueryRow into an ObservationStatus according to Phase 0 rules.

    Classification rules:
    - row.status in ('insufficient_data', 'unavailable') -> INSUFFICIENT_EVIDENCE
    - row.status == 'ok':
        - relative_change <= -0.10 -> ANOMALOUS (material decline)
        - abs(relative_change) < 0.05 -> NORMAL (stable fluctuation)
        - other cases (e.g. -0.10 < relative_change <= -0.05, positive growth) -> INCONCLUSIVE
    - Unknown row.status -> Fail Fast with ObservationValidationError.
    """
    if not isinstance(row, MetricQueryRow):
        raise ObservationValidationError(f"Expected MetricQueryRow, got {type(row).__name__}")

    if row.status in ("insufficient_data", "unavailable"):
        return ObservationStatus.INSUFFICIENT_EVIDENCE
    elif row.status == "ok":
        if row.relative_change is None:
            return ObservationStatus.INSUFFICIENT_EVIDENCE
        if row.relative_change <= Decimal("-0.10"):
            return ObservationStatus.ANOMALOUS
        elif abs(row.relative_change) < Decimal("0.05"):
            return ObservationStatus.NORMAL
        else:
            return ObservationStatus.INCONCLUSIVE
    else:
        raise ObservationValidationError(f"Unknown MetricQueryRow.status: '{row.status}'")


def _observations_from_metric_query_internal(
    result: MetricQueryResult,
    *,
    tool_name: str,
    tool_call_id: str,
    id_prefix: str,
    filters: Mapping[str, str] | None = None,
    query_or_result_reference: str,
    created_at: datetime.datetime,
) -> tuple[Observation, ...]:
    """Internal helper to convert a MetricQueryResult into Observations with a custom id_prefix."""
    if not isinstance(result, MetricQueryResult):
        raise ObservationValidationError(f"Expected MetricQueryResult, got {type(result).__name__}")

    if not result.rows:
        return ()

    obs_list: list[Observation] = []
    clean_filters = dict(filters) if filters is not None else {}

    for idx, row in enumerate(result.rows):
        status = classify_metric_row_status(row)
        obs_id = f"{id_prefix}_{result.metric_id}_{idx}"

        obs = Observation(
            observation_id=obs_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            metric=result.metric_id,
            current_period=result.current_period,
            baseline_period=result.baseline_period,
            filters=clean_filters,
            group_by=result.group_by,
            dimensions=row.dimensions,
            current_value=row.current_value,
            baseline_value=row.baseline_value,
            relative_change=row.relative_change,
            unit=result.unit,
            sample_size=row.sample_size,
            source_status=row.status,
            status=status,
            query_or_result_reference=query_or_result_reference,
            created_at=created_at,
            error_code=None,
            error_message=None,
        )
        obs_list.append(obs)

    return tuple(obs_list)


def observations_from_metric_query(
    result: MetricQueryResult,
    *,
    tool_name: str,
    tool_call_id: str,
    filters: Mapping[str, str] | None = None,
    query_or_result_reference: str,
    created_at: datetime.datetime,
) -> tuple[Observation, ...]:
    """Transform a MetricQueryResult into a tuple of immutable Observations.

    Each row in MetricQueryResult is converted to an individual Observation,
    preserving row order, with deterministic unique observation_ids.
    """
    return _observations_from_metric_query_internal(
        result,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        id_prefix=tool_call_id,
        filters=filters,
        query_or_result_reference=query_or_result_reference,
        created_at=created_at,
    )


def observations_from_related_metric_query(
    result: RelatedMetricQueryResult,
    *,
    tool_name: str,
    tool_call_id: str,
    filters: Mapping[str, str] | None = None,
    query_or_result_reference: str,
    created_at: datetime.datetime,
) -> tuple[Observation, ...]:
    """Transform a RelatedMetricQueryResult into a flattened tuple of Observations.

    Preserves the declared order of related metrics and the row order within each metric.
    Each sub-result receives a unique deterministic id_prefix incorporating its sub-result index.
    """
    if not isinstance(result, RelatedMetricQueryResult):
        raise ObservationValidationError(f"Expected RelatedMetricQueryResult, got {type(result).__name__}")

    if not result.results:
        return ()

    all_obs: list[Observation] = []
    for sub_idx, sub_result in enumerate(result.results):
        sub_obs = _observations_from_metric_query_internal(
            sub_result,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            id_prefix=f"{tool_call_id}_rel{sub_idx}",
            filters=filters,
            query_or_result_reference=query_or_result_reference,
            created_at=created_at,
        )
        all_obs.extend(sub_obs)

    return tuple(all_obs)


def observations_from_tool_result(
    result: MetricQueryResult | RelatedMetricQueryResult,
    *,
    tool_name: str,
    tool_call_id: str,
    filters: Mapping[str, str] | None = None,
    query_or_result_reference: str,
    created_at: datetime.datetime,
) -> tuple[Observation, ...]:
    """Unified entry point to convert any Analytics Tool result into an Observation tuple."""
    if isinstance(result, MetricQueryResult):
        return observations_from_metric_query(
            result,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            filters=filters,
            query_or_result_reference=query_or_result_reference,
            created_at=created_at,
        )
    elif isinstance(result, RelatedMetricQueryResult):
        return observations_from_related_metric_query(
            result,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            filters=filters,
            query_or_result_reference=query_or_result_reference,
            created_at=created_at,
        )
    else:
        raise ObservationValidationError(
            f"Unsupported result type for observation conversion: {type(result).__name__}"
        )


def failed_observation(
    *,
    tool_name: str,
    tool_call_id: str,
    metric: str,
    current_period: DateRange,
    baseline_period: DateRange,
    filters: Mapping[str, str] | None = None,
    group_by: Sequence[str] | None = None,
    dimensions: Mapping[str, str] | None = None,
    unit: str = "unknown",
    query_or_result_reference: str,
    created_at: datetime.datetime,
    error_code: str,
    error_message: str,
) -> Observation:
    """Factory function creating a failed Observation with status=FAILED.

    Ensures numerical fields are None and error fields are properly populated.
    """
    clean_obs_id = f"{tool_call_id}_{metric}_failed"
    clean_filters = dict(filters) if filters is not None else {}
    clean_group_by = tuple(group_by) if group_by is not None else ()
    clean_dimensions = dict(dimensions) if dimensions is not None else {}

    return Observation(
        observation_id=clean_obs_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        metric=metric,
        current_period=current_period,
        baseline_period=baseline_period,
        filters=clean_filters,
        group_by=clean_group_by,
        dimensions=clean_dimensions,
        current_value=None,
        baseline_value=None,
        relative_change=None,
        unit=unit,
        sample_size=None,
        source_status="failed",
        status=ObservationStatus.FAILED,
        query_or_result_reference=query_or_result_reference,
        created_at=created_at,
        error_code=error_code,
        error_message=error_message,
    )
