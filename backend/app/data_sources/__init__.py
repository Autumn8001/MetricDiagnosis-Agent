"""Data source capability contract and abstractions for MetricSleuth."""

from app.data_sources.capabilities import (
    CapabilityContractError,
    DataSourceCapabilities,
    DataSourceDescriptor,
    IncompatibleGrainError,
    MetricCapability,
    MetricNotSupportedError,
    SourceEnvironment,
    SourceProvider,
    UnknownMetricError,
    UnsupportedDimensionError,
)
from app.data_sources.semantic_adapter import (
    SemanticAdapterError,
    build_capabilities_from_registry,
)

__all__ = [
    "CapabilityContractError",
    "DataSourceCapabilities",
    "DataSourceDescriptor",
    "IncompatibleGrainError",
    "MetricCapability",
    "MetricNotSupportedError",
    "SourceEnvironment",
    "SourceProvider",
    "UnknownMetricError",
    "UnsupportedDimensionError",
    "SemanticAdapterError",
    "build_capabilities_from_registry",
]
