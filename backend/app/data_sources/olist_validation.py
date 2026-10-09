"""Capability contract for the isolated Olist validation source.

The Olist public dataset is retained as a local validation asset.  This module
turns the already-loaded Olist semantic registry into an explicit source
capability contract without connecting to PostgreSQL, reading raw files, or
claiming that Olist is a continuously synchronized product source.
"""

from __future__ import annotations

from app.data_sources.capabilities import (
    CapabilityContractError,
    DataSourceCapabilities,
    DataSourceDescriptor,
    MetricCapability,
    SourceEnvironment,
    SourceProvider,
)
from app.data_sources.semantic_adapter import build_capabilities_from_registry
from app.metrics.registry import MetricRegistry


class OlistValidationCapabilityError(CapabilityContractError):
    """Raised when a registry or descriptor is not the isolated Olist contract."""


OLIST_VALIDATION_DESCRIPTOR = DataSourceDescriptor(
    source_id="olist_validation",
    display_name="Olist Validation Dataset",
    provider=SourceProvider.OLIST,
    environment=SourceEnvironment.VALIDATION,
)

OLIST_VALIDATION_METRIC_IDS = (
    "merchandise_gmv",
    "orders",
    "olist_aov",
)

_UNSUPPORTED_METRICS = (
    MetricCapability(
        metric_id="sessions",
        supported=False,
        unavailable_reason=(
            "Olist public dataset contains no session, impression, or web-traffic event stream."
        ),
    ),
    MetricCapability(
        metric_id="conversion_rate",
        supported=False,
        unavailable_reason=(
            "Olist public dataset contains no session denominator required to calculate conversion rate."
        ),
    ),
)


def build_olist_validation_capabilities(
    registry: MetricRegistry,
    descriptor: DataSourceDescriptor = OLIST_VALIDATION_DESCRIPTOR,
) -> DataSourceCapabilities:
    """Build the explicit capability contract for the Olist validation asset.

    The three supported capabilities are copied from ``registry`` through the
    shared semantic adapter, so their dimensions and atomic grain cannot drift
    from ``configs/olist_validation_metrics.yaml``.  The two unavailable funnel
    metrics are added as explicit, dimensionless fail-closed declarations.

    ``descriptor`` is injectable only to make the source identity boundary
    testable.  It must identify an Olist validation source; this constructor
    must not be used to relabel another provider or environment as Olist.
    This function is pure with respect to external systems: the caller owns
    registry loading and no database or network operation is performed.
    """
    if not isinstance(registry, MetricRegistry):
        raise OlistValidationCapabilityError(
            f"registry must be a MetricRegistry, got {type(registry).__name__}"
        )
    if not isinstance(descriptor, DataSourceDescriptor):
        raise OlistValidationCapabilityError(
            "descriptor must be a DataSourceDescriptor, "
            f"got {type(descriptor).__name__}"
        )
    if descriptor.provider is not SourceProvider.OLIST:
        raise OlistValidationCapabilityError(
            "Olist validation capabilities require provider=SourceProvider.OLIST"
        )
    if descriptor.environment is not SourceEnvironment.VALIDATION:
        raise OlistValidationCapabilityError(
            "Olist validation capabilities require environment=SourceEnvironment.VALIDATION"
        )

    registry_metric_ids = tuple(definition.metric_id for definition in registry.list_metrics())
    if registry_metric_ids != OLIST_VALIDATION_METRIC_IDS:
        raise OlistValidationCapabilityError(
            "Olist validation registry must declare exactly "
            f"{OLIST_VALIDATION_METRIC_IDS}; got {registry_metric_ids}"
        )
    if registry.time_dimension != "date" or registry.dimensions != ("customer_state",):
        raise OlistValidationCapabilityError(
            "Olist validation registry must expose time dimension 'date' and "
            "the order-safe dimension 'customer_state'"
        )

    # The adapter is the source of truth for supported grain/dimension values.
    supported = build_capabilities_from_registry(registry, descriptor)
    return DataSourceCapabilities(
        descriptor=descriptor,
        metrics=[*supported.metrics.values(), *_UNSUPPORTED_METRICS],
    )


__all__ = [
    "OLIST_VALIDATION_DESCRIPTOR",
    "OLIST_VALIDATION_METRIC_IDS",
    "OlistValidationCapabilityError",
    "build_olist_validation_capabilities",
]
