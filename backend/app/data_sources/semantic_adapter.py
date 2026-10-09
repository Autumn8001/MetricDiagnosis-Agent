"""Adapt the current semantic-layer registry to a data-source capability contract.

This adapter is deliberately pure: it reads immutable metadata already loaded by
``MetricRegistry`` and creates ``DataSourceCapabilities``. It does not inspect a
database, call a connector, or infer metrics that are absent from the registry.
The descriptor supplied by the caller remains the source identity; this function
does not certify that a physical external source has been connected or synced.
"""

from app.data_sources.capabilities import (
    CapabilityContractError,
    DataSourceCapabilities,
    DataSourceDescriptor,
    MetricCapability,
)
from app.metrics.registry import MetricRegistry


class SemanticAdapterError(CapabilityContractError):
    """Raised when a semantic registry cannot produce a capability contract."""


def build_capabilities_from_registry(
    registry: MetricRegistry,
    descriptor: DataSourceDescriptor,
) -> DataSourceCapabilities:
    """Build capabilities for exactly the metrics declared by ``registry``.

    Every registry definition becomes a supported ``MetricCapability`` with the
    same metric ID, dimensions, and atomic grain. A direct ``MetricDefinition``
    constructed by an older caller may have an empty grain; in that narrow
    compatibility case the same explicit legacy fallback used by
    ``MetricRegistry.from_yaml`` (time dimension plus metric dimensions) is
    applied. No additional metric or dimension is inferred.

    Args:
        registry: A loaded semantic-layer registry.
        descriptor: Identity and environment for the source instance receiving
            this semantic contract.

    Raises:
        SemanticAdapterError: If either input has the wrong type or a metric
            definition cannot be represented as a capability.
        CapabilityContractError: If the resulting capability collection fails
            the capability domain contract.
    """
    if not isinstance(registry, MetricRegistry):
        raise SemanticAdapterError(
            f"registry must be a MetricRegistry, got {type(registry).__name__}"
        )
    if not isinstance(descriptor, DataSourceDescriptor):
        raise SemanticAdapterError(
            "descriptor must be a DataSourceDescriptor, "
            f"got {type(descriptor).__name__}"
        )

    capabilities: list[MetricCapability] = []
    for definition in registry.list_metrics():
        grain = definition.grain
        if not grain:
            grain = (registry.time_dimension,) + tuple(definition.dimensions)
        if not grain:
            raise SemanticAdapterError(
                f"Metric '{definition.metric_id}' has no representable atomic grain"
            )

        try:
            capabilities.append(
                MetricCapability(
                    metric_id=definition.metric_id,
                    supported=True,
                    grain=grain,
                    dimensions=definition.dimensions,
                )
            )
        except CapabilityContractError as exc:
            raise SemanticAdapterError(
                f"Metric '{definition.metric_id}' cannot be adapted to capability contract: {exc}"
            ) from exc

    return DataSourceCapabilities(descriptor=descriptor, metrics=capabilities)


__all__ = ["SemanticAdapterError", "build_capabilities_from_registry"]
