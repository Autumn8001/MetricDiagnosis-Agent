"""Data Source Capability Contract domain models and fail-closed validation rules.

This module defines the minimal, domain-neutral, immutable capability contracts
for data sources, their environments, and individual metric dimensions and grains.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class CapabilityContractError(ValueError):
    """Raised when data source capability contract definition or validation fails."""


class UnknownMetricError(CapabilityContractError):
    """Raised when a requested metric is not declared in the capability contract."""


class MetricNotSupportedError(CapabilityContractError):
    """Raised when an operation is requested on an unsupported metric."""


class UnsupportedDimensionError(CapabilityContractError):
    """Raised when an unsupported dimension is used in group_by, filter, or combination."""


class IncompatibleGrainError(CapabilityContractError):
    """Raised when two metrics cannot be safely combined due to grain incompatibility."""


class SourceProvider(StrEnum):
    """Data source platform/provider identifiers."""

    POSTGRESQL = "postgresql"
    SHOPIFY = "shopify"
    OLIST = "olist"
    SYNTHETIC = "synthetic"


class SourceEnvironment(StrEnum):
    """Operating environment of a data source instance."""

    LIVE = "live"
    SANDBOX = "sandbox"
    BENCHMARK = "benchmark"
    VALIDATION = "validation"


def _validate_identifier(value: Any, name: str) -> str:
    """Validates that value is a non-empty string after stripping whitespace."""
    if not isinstance(value, str):
        raise CapabilityContractError(f"{name} must be a string, got {type(value).__name__}")
    cleaned = value.strip()
    if not cleaned:
        raise CapabilityContractError(f"{name} must not be empty or blank")
    return cleaned


def _validate_string_tuple(
    raw_sequence: Any,
    field_name: str,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    """Validates that raw_sequence is a sequence of non-empty, non-duplicate strings."""
    if isinstance(raw_sequence, (str, bytes)) or not isinstance(raw_sequence, (list, tuple)):
        raise CapabilityContractError(
            f"'{field_name}' must be a sequence of strings, got {type(raw_sequence).__name__}"
        )

    seen = set()
    cleaned = []
    for item in raw_sequence:
        if not isinstance(item, str):
            raise CapabilityContractError(
                f"'{field_name}' contains non-string element: {item!r}"
            )
        val = item.strip()
        if not val:
            raise CapabilityContractError(f"'{field_name}' contains empty or blank element")
        if val in seen:
            raise CapabilityContractError(f"'{field_name}' contains duplicate element: {val!r}")
        seen.add(val)
        cleaned.append(val)

    if not allow_empty and not cleaned:
        raise CapabilityContractError(f"'{field_name}' cannot be empty")

    return tuple(cleaned)


@dataclass(frozen=True)
class DataSourceDescriptor:
    """Immutable identity and environment descriptor for a data source instance."""

    source_id: str
    display_name: str
    provider: SourceProvider
    environment: SourceEnvironment

    def __post_init__(self) -> None:
        clean_source_id = _validate_identifier(self.source_id, "source_id")
        clean_display_name = _validate_identifier(self.display_name, "display_name")

        if not isinstance(self.provider, SourceProvider):
            raise CapabilityContractError(
                f"provider must be a SourceProvider enum member, got {self.provider!r}"
            )
        if not isinstance(self.environment, SourceEnvironment):
            raise CapabilityContractError(
                f"environment must be a SourceEnvironment enum member, got {self.environment!r}"
            )

        object.__setattr__(self, "source_id", clean_source_id)
        object.__setattr__(self, "display_name", clean_display_name)


@dataclass(frozen=True)
class MetricCapability:
    """Immutable capability declaration for an individual metric within a data source."""

    metric_id: str
    supported: bool
    grain: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        clean_metric_id = _validate_identifier(self.metric_id, "metric_id")
        object.__setattr__(self, "metric_id", clean_metric_id)

        # Strictly verify supported is a boolean (not an int like 0 or 1)
        if type(self.supported) is not bool:
            raise CapabilityContractError(
                f"supported must be a boolean, got {type(self.supported).__name__}"
            )

        clean_grain = _validate_string_tuple(self.grain, "grain", allow_empty=True)
        clean_dimensions = _validate_string_tuple(self.dimensions, "dimensions", allow_empty=True)

        if self.unavailable_reason is not None and not isinstance(self.unavailable_reason, str):
            raise CapabilityContractError(
                f"unavailable_reason must be a string, got {type(self.unavailable_reason).__name__}"
            )

        if not self.supported:
            if not self.unavailable_reason or not self.unavailable_reason.strip():
                raise CapabilityContractError(
                    f"Unsupported metric '{clean_metric_id}' must provide a non-empty unavailable_reason"
                )
            if clean_dimensions:
                raise CapabilityContractError(
                    f"Unsupported metric '{clean_metric_id}' cannot declare queryable dimensions"
                )
            if clean_grain:
                raise CapabilityContractError(
                    f"Unsupported metric '{clean_metric_id}' cannot declare grain"
                )
            object.__setattr__(self, "unavailable_reason", self.unavailable_reason.strip())
        else:
            if self.unavailable_reason is not None and self.unavailable_reason.strip():
                raise CapabilityContractError(
                    f"Supported metric '{clean_metric_id}' must not have an unavailable_reason"
                )
            if not clean_grain:
                raise CapabilityContractError(
                    f"Supported metric '{clean_metric_id}' must declare a non-empty grain"
                )
            object.__setattr__(self, "unavailable_reason", None)

        object.__setattr__(self, "grain", clean_grain)
        object.__setattr__(self, "dimensions", clean_dimensions)


@dataclass(frozen=True)
class DataSourceCapabilities:
    """Immutable capability contract representing all metric capabilities for a data source instance."""

    descriptor: DataSourceDescriptor
    _metrics: Mapping[str, MetricCapability]

    def __init__(
        self,
        descriptor: DataSourceDescriptor,
        metrics: Mapping[str, MetricCapability] | Sequence[MetricCapability],
    ) -> None:
        if not isinstance(descriptor, DataSourceDescriptor):
            raise CapabilityContractError(
                f"descriptor must be a DataSourceDescriptor, got {type(descriptor).__name__}"
            )
        if isinstance(metrics, (str, bytes)):
            raise CapabilityContractError(
                f"metrics must be a Mapping or Sequence of MetricCapability, got {type(metrics).__name__}"
            )

        validated_metrics: dict[str, MetricCapability] = {}
        if isinstance(metrics, Mapping):
            for k, cap in metrics.items():
                if not isinstance(cap, MetricCapability):
                    raise CapabilityContractError(
                        f"Expected MetricCapability instance for metric '{k}', got {type(cap).__name__}"
                    )
                if k != cap.metric_id:
                    raise CapabilityContractError(
                        f"Metric key '{k}' does not match metric_id '{cap.metric_id}'"
                    )
                validated_metrics[k] = cap
        elif isinstance(metrics, Sequence):
            for cap in metrics:
                if not isinstance(cap, MetricCapability):
                    raise CapabilityContractError(
                        f"Expected MetricCapability instance in sequence, got {type(cap).__name__}"
                    )
                if cap.metric_id in validated_metrics:
                    raise CapabilityContractError(
                        f"Duplicate metric_id found in capabilities: '{cap.metric_id}'"
                    )
                validated_metrics[cap.metric_id] = cap
        else:
            raise CapabilityContractError(
                f"metrics must be a Mapping or Sequence of MetricCapability, got {type(metrics).__name__}"
            )

        object.__setattr__(self, "descriptor", descriptor)
        object.__setattr__(self, "_metrics", MappingProxyType(validated_metrics))

    @property
    def metrics(self) -> Mapping[str, MetricCapability]:
        """Read-only mapping of declared metric capabilities."""
        return self._metrics

    def has_metric(self, metric_id: str) -> bool:
        """Checks if a metric is declared in this data source contract."""
        if not isinstance(metric_id, str):
            raise CapabilityContractError("metric_id must be a string")
        return metric_id.strip() in self._metrics

    def get_metric_capability(self, metric_id: str) -> MetricCapability:
        """Retrieves capability for a metric ID. Fails closed with UnknownMetricError if undeclared."""
        if not isinstance(metric_id, str):
            raise CapabilityContractError("metric_id must be a string")
        clean_id = metric_id.strip()
        if clean_id not in self._metrics:
            raise UnknownMetricError(
                f"Metric '{clean_id}' is not declared in data source '{self.descriptor.source_id}'"
            )
        return self._metrics[clean_id]

    def is_metric_supported(self, metric_id: str) -> bool:
        """Checks whether a declared metric is supported. Fails closed if undeclared."""
        cap = self.get_metric_capability(metric_id)
        return cap.supported

    def is_dimension_supported(self, metric_id: str, dimension: str) -> bool:
        """Checks whether a given dimension is supported for a specific metric.

        Fails closed with UnknownMetricError if metric is undeclared.
        Returns False if the metric is unsupported or the dimension is not in dimensions.
        """
        if not isinstance(dimension, str) or not dimension.strip():
            raise CapabilityContractError("dimension must be a non-empty string")
        clean_dim = dimension.strip()
        cap = self.get_metric_capability(metric_id)
        if not cap.supported:
            return False
        return clean_dim in cap.dimensions

    def validate_query(
        self,
        metric_id: str,
        group_by: Sequence[str] | None = None,
        filters: Mapping[str, Any] | Sequence[str] | None = None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Validates that a query's metric, group_by dimensions, and filter dimensions are supported.

        Returns:
            A tuple of (normalized_group_by, normalized_filter_dimensions).

        Raises:
            UnknownMetricError: If metric_id is not declared in the contract.
            MetricNotSupportedError: If metric_id is declared but unsupported.
            UnsupportedDimensionError: If any group_by or filter dimension is unsupported.
            CapabilityContractError: If arguments contain duplicate or invalid entries.
        """
        cap = self.get_metric_capability(metric_id)
        if not cap.supported:
            raise MetricNotSupportedError(
                f"Metric '{cap.metric_id}' is not supported on source '{self.descriptor.source_id}': "
                f"{cap.unavailable_reason}"
            )

        norm_group_by: tuple[str, ...] = ()
        if group_by is not None:
            if isinstance(group_by, (str, bytes)):
                raise CapabilityContractError(
                    f"group_by must be a Sequence of dimension names, not {type(group_by).__name__}"
                )
            norm_group_by = _validate_string_tuple(group_by, "group_by", allow_empty=True)
            for dim in norm_group_by:
                if dim not in cap.dimensions:
                    raise UnsupportedDimensionError(
                        f"Dimension '{dim}' in group_by is not supported for metric '{cap.metric_id}'. "
                        f"Supported dimensions: {cap.dimensions}"
                    )

        norm_filters: list[str] = []
        if filters is not None:
            if isinstance(filters, (str, bytes)):
                raise CapabilityContractError(
                    f"filters must be a Mapping or Sequence of dimension names, not {type(filters).__name__}"
                )
            if isinstance(filters, Mapping):
                filter_keys = list(filters.keys())
            elif isinstance(filters, Sequence):
                filter_keys = list(filters)
            else:
                raise CapabilityContractError("filters must be a Mapping or Sequence of dimension names")

            validated_filter_dims = _validate_string_tuple(filter_keys, "filters", allow_empty=True)
            for dim in validated_filter_dims:
                if dim not in cap.dimensions:
                    raise UnsupportedDimensionError(
                        f"Dimension '{dim}' in filters is not supported for metric '{cap.metric_id}'. "
                        f"Supported dimensions: {cap.dimensions}"
                    )
            norm_filters = list(validated_filter_dims)

        return norm_group_by, tuple(norm_filters)

    def validate_metric_combination(
        self,
        metric_a: str,
        metric_b: str,
        on_dimensions: Sequence[str],
    ) -> tuple[str, ...]:
        """Validates whether two metrics can be safely compared or combined on specified dimensions.

        Enforces fail-closed rules:
        1. Both metrics must be declared and supported;
        2. on_dimensions must be non-empty, non-blank, distinct strings;
        3. All on_dimensions must be supported in both metrics' dimensions;
        4. All on_dimensions must be present in both metrics' grains (prevents combining on a dimension
           finer than or unbacked by either metric's atomic grain).

        Returns:
            Normalized on_dimensions tuple on success.

        Raises:
            UnknownMetricError: If either metric is undeclared.
            MetricNotSupportedError: If either metric is unsupported.
            UnsupportedDimensionError: If any dimension is not supported by both metrics.
            IncompatibleGrainError: If any dimension is not backed by both metrics' grains.
            CapabilityContractError: If dimensions are empty, duplicate, or blank.
        """
        if isinstance(on_dimensions, (str, bytes)):
            raise CapabilityContractError(
                f"on_dimensions must be a Sequence of dimension names, not {type(on_dimensions).__name__}"
            )
        cap_a = self.get_metric_capability(metric_a)
        cap_b = self.get_metric_capability(metric_b)

        if not cap_a.supported:
            raise MetricNotSupportedError(
                f"Metric '{metric_a}' is not supported: {cap_a.unavailable_reason}"
            )
        if not cap_b.supported:
            raise MetricNotSupportedError(
                f"Metric '{metric_b}' is not supported: {cap_b.unavailable_reason}"
            )

        norm_dims = _validate_string_tuple(on_dimensions, "on_dimensions", allow_empty=False)

        for dim in norm_dims:
            if dim not in cap_a.dimensions:
                raise UnsupportedDimensionError(
                    f"Dimension '{dim}' is not supported by metric '{metric_a}'. "
                    f"Supported dimensions: {cap_a.dimensions}"
                )
            if dim not in cap_b.dimensions:
                raise UnsupportedDimensionError(
                    f"Dimension '{dim}' is not supported by metric '{metric_b}'. "
                    f"Supported dimensions: {cap_b.dimensions}"
                )

        # Grain protection: do not just compare dimension names while ignoring grain
        for dim in norm_dims:
            if dim not in cap_a.grain:
                raise IncompatibleGrainError(
                    f"Cannot combine '{metric_a}' and '{metric_b}' on dimension '{dim}': "
                    f"dimension is not present in grain for metric '{metric_a}' ({cap_a.grain})"
                )
            if dim not in cap_b.grain:
                raise IncompatibleGrainError(
                    f"Cannot combine '{metric_a}' and '{metric_b}' on dimension '{dim}': "
                    f"dimension is not present in grain for metric '{metric_b}' ({cap_b.grain})"
                )

        return norm_dims

    def can_combine_metrics(
        self,
        metric_a: str,
        metric_b: str,
        on_dimensions: Sequence[str],
    ) -> bool:
        """Determines whether two metrics can be safely combined on the given dimensions.

        Fails closed (returns False) on capability mismatches or unsupported dimensions/grains.
        Raises UnknownMetricError or CapabilityContractError if metrics are undeclared or inputs are invalid.
        """
        try:
            self.validate_metric_combination(metric_a, metric_b, on_dimensions)
            return True
        except (MetricNotSupportedError, UnsupportedDimensionError, IncompatibleGrainError):
            return False
