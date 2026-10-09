"""Tests for adapting semantic metric definitions to source capabilities."""

from pathlib import Path
import unittest

from app.data_sources import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
    build_capabilities_from_registry,
)
from app.metrics.registry import MetricRegistry


class TestSemanticAdapter(unittest.TestCase):
    def setUp(self) -> None:
        config_path = (
            Path(__file__).resolve().parent.parent.parent
            / "configs"
            / "metrics.yaml"
        )
        self.registry = MetricRegistry.from_yaml(config_path)
        self.descriptor = DataSourceDescriptor(
            source_id="synthetic_benchmark",
            display_name="Synthetic Benchmark",
            provider=SourceProvider.SYNTHETIC,
            environment=SourceEnvironment.BENCHMARK,
        )

    def test_adapts_every_declared_metric_without_inventing_metrics(self) -> None:
        capabilities = build_capabilities_from_registry(self.registry, self.descriptor)

        self.assertIs(capabilities.descriptor, self.descriptor)
        self.assertEqual(
            tuple(capabilities.metrics),
            ("sales", "orders", "sessions", "conversion_rate", "aov"),
        )
        for definition in self.registry.list_metrics():
            capability = capabilities.get_metric_capability(definition.metric_id)
            self.assertTrue(capability.supported)
            self.assertEqual(capability.dimensions, definition.dimensions)
            self.assertEqual(capability.grain, definition.grain)

        with self.assertRaises(KeyError):
            capabilities.metrics["not_declared"]

    def test_rejects_non_registry_inputs(self) -> None:
        with self.assertRaises(ValueError):
            build_capabilities_from_registry(object(), self.descriptor)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            build_capabilities_from_registry(self.registry, object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
