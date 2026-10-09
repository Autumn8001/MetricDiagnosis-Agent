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
from app.data_sources.olist_validation import (
    OLIST_VALIDATION_DESCRIPTOR,
    OLIST_VALIDATION_METRIC_IDS,
    OlistValidationCapabilityError,
    build_olist_validation_capabilities,
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
    "OLIST_VALIDATION_DESCRIPTOR",
    "OLIST_VALIDATION_METRIC_IDS",
    "OlistValidationCapabilityError",
    "build_olist_validation_capabilities",
]
