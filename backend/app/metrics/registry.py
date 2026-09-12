"""Metric Semantic Layer Registry and Definitions for MetricSleuth."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import yaml


class MetricConfigError(ValueError):
    """Raised when metrics configuration YAML is invalid, incomplete, or violates schema rules."""


class MetricNotFoundError(KeyError):
    """Raised when a requested metric ID does not exist in the registry."""


VALID_METRIC_TYPES = {"additive", "ratio"}


def _validate_string_list(
    raw_list: Any,
    field_name: str,
    metric_id: str,
    allow_empty: bool,
    valid_universe: set[str] | None,
    allow_self: bool,
) -> tuple[str, ...]:
    """Validates that raw_list is a list of non-empty strings adhering to constraints."""
    if not isinstance(raw_list, list):
        raise MetricConfigError(f"Metric '{metric_id}' '{field_name}' must be a list")
    if not allow_empty and not raw_list:
        raise MetricConfigError(f"Metric '{metric_id}' requires a non-empty list for '{field_name}'")

    seen = set()
    cleaned = []
    for item in raw_list:
        if not isinstance(item, str) or not item.strip():
            raise MetricConfigError(
                f"Metric '{metric_id}' '{field_name}' contains non-string or empty element: {item!r}"
            )
        val = item.strip()
        if not allow_self and val == metric_id:
            raise MetricConfigError(
                f"Metric '{metric_id}' cannot reference itself in '{field_name}'"
            )
        if valid_universe is not None and val not in valid_universe:
            raise MetricConfigError(
                f"Metric '{metric_id}' references unknown item in '{field_name}': '{val}'"
            )
        if val in seen:
            raise MetricConfigError(
                f"Metric '{metric_id}' contains duplicate element in '{field_name}': '{val}'"
            )
        seen.add(val)
        cleaned.append(val)

    return tuple(cleaned)


@dataclass(frozen=True)
class MetricDefinition:
    """Immutable metadata definition of a metric in the semantic layer."""

    metric_id: str
    display_name: str
    description: str
    metric_type: str
    unit: str
    formula: str
    source_fields: tuple[str, ...]
    dimensions: tuple[str, ...]
    dependencies: tuple[str, ...]
    related_metrics: tuple[str, ...]


class MetricRegistry:
    """Read-only in-memory registry holding all loaded metric definitions."""

    def __init__(
        self,
        table: str,
        time_dimension: str,
        dimensions: tuple[str, ...],
        metrics: Mapping[str, MetricDefinition],
    ) -> None:
        self._table = table
        self._time_dimension = time_dimension
        self._dimensions = tuple(dimensions)
        self._metrics = dict(metrics)

    @property
    def table(self) -> str:
        return self._table

    @property
    def time_dimension(self) -> str:
        return self._time_dimension

    @property
    def dimensions(self) -> tuple[str, ...]:
        return self._dimensions

    def get(self, metric_id: str) -> MetricDefinition:
        """Retrieves a metric definition by ID. Raises MetricNotFoundError if missing."""
        if metric_id not in self._metrics:
            raise MetricNotFoundError(f"Metric '{metric_id}' not found in registry")
        return self._metrics[metric_id]

    def has_metric(self, metric_id: str) -> bool:
        """Checks whether a metric ID exists in the registry."""
        return metric_id in self._metrics

    def list_metrics(self) -> list[MetricDefinition]:
        """Returns all metric definitions in stable declared order."""
        return list(self._metrics.values())

    def get_related_metrics(self, metric_id: str) -> list[MetricDefinition]:
        """Returns MetricDefinitions for all related metrics of the given metric."""
        metric = self.get(metric_id)
        return [self.get(rel_id) for rel_id in metric.related_metrics]

    def get_dependencies(self, metric_id: str) -> list[MetricDefinition]:
        """Returns MetricDefinitions for all direct dependencies of the given metric."""
        metric = self.get(metric_id)
        return [self.get(dep_id) for dep_id in metric.dependencies]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MetricRegistry":
        """Loads and strictly validates a MetricRegistry from a YAML configuration file."""
        file_path = Path(path)
        if not file_path.exists():
            raise MetricConfigError(f"Metrics configuration file not found: {file_path}")

        try:
            content = file_path.read_text(encoding="utf-8")
            raw_data = yaml.safe_load(content)
        except Exception as e:
            raise MetricConfigError(f"Failed to parse YAML from {file_path}: {e}") from e

        return cls._validate_and_build(raw_data)

    @classmethod
    def _validate_and_build(cls, raw: Any) -> "MetricRegistry":
        if not isinstance(raw, dict):
            raise MetricConfigError("Root configuration must be a mapping (dictionary)")

        if raw.get("version") != 1:
            raise MetricConfigError(f"Expected version: 1, got: {raw.get('version')}")

        source = raw.get("source")
        if not isinstance(source, dict):
            raise MetricConfigError("Missing or invalid 'source' section in configuration")

        table = source.get("table")
        if not isinstance(table, str) or not table.strip():
            raise MetricConfigError("'source.table' must be a non-empty string")

        time_dimension = source.get("time_dimension")
        if not isinstance(time_dimension, str) or not time_dimension.strip():
            raise MetricConfigError("'source.time_dimension' must be a non-empty string")

        allowed_dimensions_raw = source.get("dimensions")
        if not isinstance(allowed_dimensions_raw, list) or not allowed_dimensions_raw:
            raise MetricConfigError("'source.dimensions' must be a non-empty list of string dimensions")

        allowed_dims_seen = set()
        allowed_dimensions = []
        for dim in allowed_dimensions_raw:
            if not isinstance(dim, str) or not dim.strip():
                raise MetricConfigError("Each dimension in 'source.dimensions' must be a non-empty string")
            dim_val = dim.strip()
            if dim_val in allowed_dims_seen:
                raise MetricConfigError(f"Duplicate dimension found in 'source.dimensions': '{dim_val}'")
            allowed_dims_seen.add(dim_val)
            allowed_dimensions.append(dim_val)

        metrics_raw = raw.get("metrics")
        if not isinstance(metrics_raw, dict) or not metrics_raw:
            raise MetricConfigError("'metrics' section must be a non-empty mapping")

        metric_ids: list[str] = []
        for raw_metric_id in metrics_raw:
            if not isinstance(raw_metric_id, str) or not raw_metric_id.strip():
                raise MetricConfigError(
                    "Each key in 'metrics' must be a non-empty string metric ID"
                )
            if raw_metric_id != raw_metric_id.strip():
                raise MetricConfigError(
                    f"Metric ID must not contain leading or trailing whitespace: {raw_metric_id!r}"
                )
            metric_ids.append(raw_metric_id)
        declared_metric_ids = set(metric_ids)

        definitions: dict[str, MetricDefinition] = {}

        for m_id in metric_ids:
            m_conf = metrics_raw[m_id]
            if not isinstance(m_conf, dict):
                raise MetricConfigError(f"Metric '{m_id}' configuration must be a mapping")

            display_name = m_conf.get("display_name")
            if not isinstance(display_name, str) or not display_name.strip():
                raise MetricConfigError(f"Metric '{m_id}' requires a non-empty 'display_name'")

            description = m_conf.get("description")
            if not isinstance(description, str) or not description.strip():
                raise MetricConfigError(f"Metric '{m_id}' requires a non-empty 'description'")

            metric_type = m_conf.get("metric_type")
            if metric_type not in VALID_METRIC_TYPES:
                raise MetricConfigError(
                    f"Metric '{m_id}' invalid metric_type '{metric_type}'. Must be one of {VALID_METRIC_TYPES}"
                )

            unit = m_conf.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                raise MetricConfigError(f"Metric '{m_id}' requires a non-empty 'unit'")

            formula = m_conf.get("formula")
            if not isinstance(formula, str) or not formula.strip():
                raise MetricConfigError(f"Metric '{m_id}' requires a non-empty 'formula'")

            source_fields = _validate_string_list(
                m_conf.get("source_fields"),
                "source_fields",
                m_id,
                allow_empty=False,
                valid_universe=None,
                allow_self=True,
            )

            dims = _validate_string_list(
                m_conf.get("dimensions"),
                "dimensions",
                m_id,
                allow_empty=False,
                valid_universe=allowed_dims_seen,
                allow_self=True,
            )

            deps = _validate_string_list(
                m_conf.get("dependencies"),
                "dependencies",
                m_id,
                allow_empty=True,
                valid_universe=declared_metric_ids,
                allow_self=False,
            )

            related = _validate_string_list(
                m_conf.get("related_metrics"),
                "related_metrics",
                m_id,
                allow_empty=True,
                valid_universe=declared_metric_ids,
                allow_self=False,
            )

            definitions[m_id] = MetricDefinition(
                metric_id=m_id,
                display_name=display_name.strip(),
                description=description.strip(),
                metric_type=metric_type,
                unit=unit.strip(),
                formula=formula.strip(),
                source_fields=source_fields,
                dimensions=dims,
                dependencies=deps,
                related_metrics=related,
            )

        return cls(
            table=table.strip(),
            time_dimension=time_dimension.strip(),
            dimensions=tuple(allowed_dimensions),
            metrics=definitions,
        )
