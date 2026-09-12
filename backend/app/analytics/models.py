"""Data models and exceptions for MetricSleuth Analytics Tools."""

from dataclasses import dataclass
import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping


class AnalyticsError(Exception):
    """Base exception for all analytics queries and tools."""


class MetricQueryError(AnalyticsError):
    """Raised when metric query parameters or validation checks fail."""


@dataclass(frozen=True)
class DateRange:
    """Immutable date range representation."""

    start_date: datetime.date
    end_date: datetime.date


@dataclass(frozen=True)
class MetricQueryRow:
    """Immutable single row result of a metric query.

    Attributes:
        dimensions: Immutable dimension key-value mapping for this row.
        current_value: Aggregated metric value for the current period.
        baseline_value: Aggregated metric value for the baseline period (daily average for additive).
        relative_change: Relative change (current - baseline) / baseline, or None if unavailable/insufficient.
        status: Evaluation status ('ok', 'insufficient_data', 'unavailable').
        sample_size: Baseline daily average sessions for this segment, used for >= 30 sample size check.
    """

    dimensions: Mapping[str, str]
    current_value: Decimal | None
    baseline_value: Decimal | None
    relative_change: Decimal | None
    status: str
    sample_size: Decimal | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dimensions",
            MappingProxyType(dict(self.dimensions)),
        )


@dataclass(frozen=True)
class MetricQueryResult:
    """Immutable structured result of an analytics metric query."""

    metric_id: str
    unit: str
    current_period: DateRange
    baseline_period: DateRange
    group_by: tuple[str, ...]
    rows: tuple[MetricQueryRow, ...]


@dataclass(frozen=True)
class RelatedMetricQueryResult:
    """Immutable structured result of querying related metrics for a source metric."""

    source_metric_id: str
    results: tuple[MetricQueryResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "results",
            tuple(self.results),
        )
