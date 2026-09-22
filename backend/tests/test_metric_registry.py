"""Unit tests for Metric Semantic Layer Registry and Definitions."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import unittest
import yaml

from app.metrics import (
    MetricConfigError,
    MetricDefinition,
    MetricNotFoundError,
    MetricRegistry,
)


class TestMetricRegistry(unittest.TestCase):
    """Test suite for MetricRegistry loading, querying, immutability, and validation."""

    def setUp(self):
        # Resolve path to actual project config
        self.project_root = Path(__file__).resolve().parent.parent.parent
        self.config_path = self.project_root / "configs" / "metrics.yaml"
        self.valid_raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))

    def _assert_config_error(self, config_dict: dict):
        """Helper to dump config to temporary file and assert MetricConfigError on load."""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            yaml.dump(config_dict, tf)
            temp_name = tf.name

        try:
            with self.assertRaises(MetricConfigError):
                MetricRegistry.from_yaml(Path(temp_name))
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _load_config(self, config_dict: dict) -> MetricRegistry:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            yaml.safe_dump(config_dict, tf, sort_keys=False)
            temp_name = tf.name
        try:
            return MetricRegistry.from_yaml(Path(temp_name))
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _domain_neutral_config(self) -> dict:
        return {
            "version": 1,
            "source": {
                "table": "semantic.fact_events",
                "time_dimension": "event_date",
                "dimensions": ["segment"],
            },
            "metrics": {
                "metric_beta": {
                    "display_name": "Metric Beta",
                    "description": "A ratio with a domain-specific custom unit.",
                    "metric_type": "ratio",
                    "unit": " events_per_account ",
                    "formula": "SUM(events) / NULLIF(SUM(accounts), 0)",
                    "source_fields": ["events", "accounts"],
                    "dimensions": ["segment"],
                    "dependencies": ["metric_alpha"],
                    "driver_metrics": ["metric_alpha"],
                    "related_metrics": ["metric_alpha"],
                },
                "metric_alpha": {
                    "display_name": "Metric Alpha",
                    "description": "A valid leaf metric.",
                    "metric_type": "additive",
                    "unit": "widgets",
                    "formula": "SUM(widgets)",
                    "source_fields": ["widgets"],
                    "dimensions": ["segment"],
                    "dependencies": [],
                    "driver_metrics": [],
                    "related_metrics": [],
                },
            },
        }

    def test_load_real_metrics_yaml(self):
        """Verify that the repository's configs/metrics.yaml loads cleanly."""
        registry = MetricRegistry.from_yaml(self.config_path)

        self.assertEqual(registry.table, "warehouse.fact_daily_performance")
        self.assertEqual(registry.time_dimension, "date")
        self.assertEqual(registry.dimensions, ("marketplace", "asin", "traffic_source"))

        metrics = registry.list_metrics()
        metric_ids = [m.metric_id for m in metrics]
        self.assertEqual(metric_ids, ["sales", "orders", "sessions", "conversion_rate", "aov"])

    def test_sales_definition(self):
        """Verify Sales metric definition, gross sales semantics, unit and dimensions."""
        registry = MetricRegistry.from_yaml(self.config_path)
        sales = registry.get("sales")

        self.assertIsInstance(sales, MetricDefinition)
        self.assertEqual(sales.metric_id, "sales")
        self.assertEqual(sales.display_name, "Sales")
        self.assertEqual(sales.metric_type, "additive")
        self.assertEqual(sales.unit, "usd")
        self.assertEqual(sales.formula, "SUM(sales)")
        self.assertEqual(sales.source_fields, ("sales",))
        self.assertEqual(sales.dimensions, ("marketplace", "asin", "traffic_source"))
        self.assertEqual(sales.dependencies, ())
        self.assertEqual(sales.driver_metrics, ("orders", "aov"))
        self.assertEqual(
            sales.related_metrics,
            ("orders", "sessions", "conversion_rate", "aov"),
        )
        self.assertIn("gross sales", sales.description.lower())

        # Related metrics lookup returns MetricDefinition objects in exact order
        related_objs = registry.get_related_metrics("sales")
        self.assertEqual(
            [m.metric_id for m in related_objs],
            ["orders", "sessions", "conversion_rate", "aov"],
        )
        driver_objs = registry.get_driver_metrics("sales")
        self.assertEqual([m.metric_id for m in driver_objs], ["orders", "aov"])

    def test_domain_neutral_metrics_preserve_declaration_order_and_custom_units(self):
        registry = self._load_config(self._domain_neutral_config())

        self.assertEqual(
            [metric.metric_id for metric in registry.list_metrics()],
            ["metric_beta", "metric_alpha"],
        )
        beta = registry.get("metric_beta")
        alpha = registry.get("metric_alpha")
        self.assertEqual(beta.unit, "events_per_account")
        self.assertEqual(beta.dependencies, ("metric_alpha",))
        self.assertEqual(beta.driver_metrics, ("metric_alpha",))
        self.assertEqual(
            [metric.metric_id for metric in registry.get_dependencies("metric_beta")],
            ["metric_alpha"],
        )
        self.assertEqual(alpha.unit, "widgets")
        self.assertEqual(alpha.related_metrics, ())
        self.assertEqual(alpha.driver_metrics, ())
        self.assertEqual(registry.get_related_metrics("metric_alpha"), [])
        self.assertEqual(registry.get_driver_metrics("metric_alpha"), [])

    def test_metric_ids_are_non_empty_strings_without_surrounding_whitespace(self):
        base = self._domain_neutral_config()
        alpha = base["metrics"]["metric_alpha"]
        for bad_metric_id in ("", "   ", " metric_alpha", "metric_alpha ", 42):
            bad = deepcopy(base)
            bad["metrics"] = {bad_metric_id: alpha}
            with self.subTest(metric_id=bad_metric_id):
                self._assert_config_error(bad)

    def test_custom_unit_must_be_a_non_empty_string(self):
        for bad_unit in (None, "", "   ", 42):
            bad = self._domain_neutral_config()
            bad["metrics"]["metric_alpha"]["unit"] = bad_unit
            with self.subTest(unit=bad_unit):
                self._assert_config_error(bad)

    def test_domain_neutral_references_remain_fail_closed(self):
        for field, value in (
            ("dependencies", ["not_declared"]),
            ("driver_metrics", ["not_declared"]),
            ("related_metrics", ["not_declared"]),
            ("dependencies", ["metric_beta"]),
            ("driver_metrics", ["metric_beta"]),
            ("related_metrics", ["metric_beta"]),
        ):
            bad = self._domain_neutral_config()
            bad["metrics"]["metric_beta"][field] = value
            with self.subTest(field=field, value=value):
                self._assert_config_error(bad)

    def test_conversion_rate_definition(self):
        """Verify Conversion Rate formula, ratio unit, and dependency resolution."""
        registry = MetricRegistry.from_yaml(self.config_path)
        cr = registry.get("conversion_rate")

        self.assertEqual(cr.metric_type, "ratio")
        self.assertEqual(cr.unit, "ratio")
        self.assertEqual(cr.formula, "SUM(orders) / NULLIF(SUM(sessions), 0)")
        self.assertEqual(cr.dependencies, ("orders", "sessions"))
        self.assertEqual(cr.driver_metrics, ())
        self.assertIn("unavailable", cr.description.lower())

        dep_objs = registry.get_dependencies("conversion_rate")
        self.assertEqual([d.metric_id for d in dep_objs], ["orders", "sessions"])

    def test_aov_definition(self):
        """Verify AOV formula, unit and dependencies."""
        registry = MetricRegistry.from_yaml(self.config_path)
        aov = registry.get("aov")

        self.assertEqual(aov.metric_type, "ratio")
        self.assertEqual(aov.unit, "usd")
        self.assertEqual(aov.formula, "SUM(sales) / NULLIF(SUM(orders), 0)")
        self.assertEqual(aov.dependencies, ("sales", "orders"))
        self.assertEqual(aov.driver_metrics, ())

        dep_objs = registry.get_dependencies("aov")
        self.assertEqual([d.metric_id for d in dep_objs], ["sales", "orders"])

    def test_unknown_metric_raises_not_found(self):
        """Verify that requesting an unknown metric ID raises MetricNotFoundError."""
        registry = MetricRegistry.from_yaml(self.config_path)

        with self.assertRaises(MetricNotFoundError):
            registry.get("refunds")

        with self.assertRaises(MetricNotFoundError):
            registry.get_related_metrics("unknown_metric")

        with self.assertRaises(MetricNotFoundError):
            registry.get_dependencies("unknown_metric")

        with self.assertRaises(MetricNotFoundError):
            registry.get_driver_metrics("unknown_metric")

        self.assertFalse(registry.has_metric("refunds"))
        self.assertTrue(registry.has_metric("sales"))

    def test_immutability(self):
        """Verify that MetricDefinition and returned collections cannot be mutated."""
        registry = MetricRegistry.from_yaml(self.config_path)
        sales = registry.get("sales")

        with self.assertRaises(FrozenInstanceError):
            sales.unit = "eur"  # type: ignore

        with self.assertRaises(FrozenInstanceError):
            sales.formula = "SUM(orders)"  # type: ignore

        # Dimension/field tuples are immutable
        self.assertIsInstance(sales.source_fields, tuple)
        self.assertIsInstance(sales.dimensions, tuple)
        self.assertIsInstance(sales.dependencies, tuple)
        self.assertIsInstance(sales.driver_metrics, tuple)
        self.assertIsInstance(sales.related_metrics, tuple)

    def test_validation_rejects_missing_fields(self):
        """Verify that YAML missing required fields is rejected with MetricConfigError."""
        bad_configs = [
            # Missing source
            {"version": 1, "metrics": {}},
            # Missing version
            {"source": {"table": "t", "time_dimension": "d", "dimensions": ["m"]}, "metrics": {}},
            # Invalid metric type
            {
                "version": 1,
                "source": {"table": "t", "time_dimension": "d", "dimensions": ["marketplace"]},
                "metrics": {
                    "sales": {
                        "display_name": "Sales",
                        "description": "desc",
                        "metric_type": "invalid_type",
                        "unit": "usd",
                        "formula": "SUM(sales)",
                        "source_fields": ["sales"],
                        "dimensions": ["marketplace"],
                        "dependencies": [],
                        "driver_metrics": [],
                        "related_metrics": ["orders", "sessions", "conversion_rate", "aov"],
                    },
                    "orders": {},
                    "sessions": {},
                    "conversion_rate": {},
                    "aov": {},
                },
            },
        ]

        for conf in bad_configs:
            self._assert_config_error(conf)

    def test_validation_rejects_unknown_dependency(self):
        """Verify that YAML referencing unknown dependencies is rejected with MetricConfigError."""
        bad_dep = deepcopy(self.valid_raw)
        bad_dep["metrics"]["conversion_rate"]["dependencies"] = ["orders", "non_existent_metric"]
        self._assert_config_error(bad_dep)

    def test_validation_rejects_unknown_related_metric(self):
        """Verify that YAML referencing unknown related metrics is rejected with MetricConfigError."""
        bad_related = deepcopy(self.valid_raw)
        bad_related["metrics"]["sales"]["related_metrics"] = ["orders", "non_existent_metric"]
        self._assert_config_error(bad_related)

    def test_validation_rejects_missing_driver_metrics(self):
        """Verify that every metric must declare driver_metrics explicitly."""
        bad_config = deepcopy(self.valid_raw)
        del bad_config["metrics"]["sales"]["driver_metrics"]
        self._assert_config_error(bad_config)

    def test_validation_rejects_unknown_driver_metric(self):
        """Verify that driver_metrics cannot reference an undeclared metric."""
        bad_driver = deepcopy(self.valid_raw)
        bad_driver["metrics"]["sales"]["driver_metrics"] = ["non_existent_metric"]
        self._assert_config_error(bad_driver)

    def test_validation_rejects_self_dependency(self):
        """Verify that a metric cannot list itself as a dependency."""
        bad_self_dep = deepcopy(self.valid_raw)
        bad_self_dep["metrics"]["sales"]["dependencies"] = ["sales"]
        self._assert_config_error(bad_self_dep)

    def test_validation_rejects_self_related_metric(self):
        """Verify that a metric cannot list itself in related_metrics."""
        bad_self_rel = deepcopy(self.valid_raw)
        bad_self_rel["metrics"]["sales"]["related_metrics"] = ["sales", "orders"]
        self._assert_config_error(bad_self_rel)

    def test_validation_rejects_self_driver_metric(self):
        """Verify that a metric cannot list itself in driver_metrics."""
        bad_self_driver = deepcopy(self.valid_raw)
        bad_self_driver["metrics"]["sales"]["driver_metrics"] = ["sales"]
        self._assert_config_error(bad_self_driver)

    def test_validation_rejects_duplicate_driver_metrics(self):
        """Verify that duplicate driver metric IDs are rejected."""
        bad_duplicate_driver = deepcopy(self.valid_raw)
        bad_duplicate_driver["metrics"]["sales"]["driver_metrics"] = ["orders", "orders"]
        self._assert_config_error(bad_duplicate_driver)

    def test_validation_rejects_invalid_element_types(self):
        """Verify that non-string or whitespace-only elements in dependencies/related_metrics raise MetricConfigError."""
        invalid_cases = [
            ("dependencies", [[]]),
            ("dependencies", [{}]),
            ("dependencies", [123]),
            ("dependencies", [""]),
            ("dependencies", ["   "]),
            ("driver_metrics", [[]]),
            ("driver_metrics", [{}]),
            ("driver_metrics", [123]),
            ("driver_metrics", [""]),
            ("driver_metrics", ["   "]),
            ("related_metrics", [[]]),
            ("related_metrics", [{}]),
            ("related_metrics", [None]),
            ("related_metrics", [""]),
            ("related_metrics", ["\t\n "]),
            ("source_fields", [[]]),
            ("dimensions", [456]),
        ]

        for field, bad_val in invalid_cases:
            bad_conf = deepcopy(self.valid_raw)
            bad_conf["metrics"]["sales"][field] = bad_val
            with self.subTest(field=field, bad_val=bad_val):
                self._assert_config_error(bad_conf)


if __name__ == "__main__":
    unittest.main()
