"""Observations package for MetricSleuth.

Provides immutable Observation models, status contracts, and mapper functions
transforming Analytics Tool results into traceable observations.
"""

from app.observations.mapper import (
    classify_metric_row_status,
    failed_observation,
    observations_from_metric_query,
    observations_from_related_metric_query,
    observations_from_tool_result,
)
from app.observations.models import (
    Observation,
    ObservationError,
    ObservationStatus,
    ObservationValidationError,
)

__all__ = [
    "Observation",
    "ObservationError",
    "ObservationStatus",
    "ObservationValidationError",
    "classify_metric_row_status",
    "failed_observation",
    "observations_from_metric_query",
    "observations_from_related_metric_query",
    "observations_from_tool_result",
]
