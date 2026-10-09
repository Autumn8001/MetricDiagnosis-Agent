"""Hermetic tests for the isolated Olist validation capability contract."""

from __future__ import annotations

import datetime
from pathlib import Path
import unittest

from app.analytics.models import MetricQueryError
from app.analytics.tools import AnalyticsTools
from app.data_sources import (
    DataSourceDescriptor,
    MetricNotSupportedError,
    OLIST_VALIDATION_METRIC_IDS,
    OlistValidationCapabilityError,
    SourceEnvironment,
    SourceProvider,
    build_olist_validation_capabilities,
)
from app.metrics.registry import MetricRegistry


class NoSqlConnection:
    """Connection sentinel proving contract errors happen before SQL."""

    def __init__(self) -> None:
        self.cursor_calls = 0

    def cursor(self):
        self.cursor_calls += 1
        raise AssertionError("Olist capability rejection must happen before SQL")


class TestOlistValidationCapabilities(unittest.TestCase):
    def setUp(self) -> None:
        config_path = (
            Path(__file__).resolve().parents[2]
            / "configs"
            / "olist_validation_metrics.yaml"
        )
        self.registry = MetricRegistry.from_yaml(config_path)

    def test_registry_and_supported_capabilities_keep_order_safe_grain(self) -> None:
        self.assertEqual(
            tuple(definition.metric_id for definition in self.registry.list_metrics()),
            OLIST_VALIDATION_METRIC_IDS,
        )
        self.assertEqual(self.registry.time_dimension, "date")
        self.assertEqual(self.registry.dimensions, ("customer_state",))
        for definition in self.registry.list_metrics():
            self.assertEqual(definition.grain, ("date", "customer_state"))

        capabilities = build_olist_validation_capabilities(self.registry)
        self.assertEqual(capabilities.descriptor.provider, SourceProvider.OLIST)
        self.assertEqual(capabilities.descriptor.environment, SourceEnvironment.VALIDATION)
        for metric_id in OLIST_VALIDATION_METRIC_IDS:
            capability = capabilities.get_metric_capability(metric_id)
            self.assertTrue(capability.supported)
            self.assertEqual(capability.grain, ("date", "customer_state"))
            self.assertEqual(capability.dimensions, ("customer_state",))

    def test_funnel_metrics_are_explicitly_unavailable(self) -> None:
        capabilities = build_olist_validation_capabilities(self.registry)

        sessions = capabilities.get_metric_capability("sessions")
        self.assertFalse(sessions.supported)
        self.assertIn("no session", sessions.unavailable_reason.lower())
        with self.assertRaisesRegex(MetricNotSupportedError, "sessions"):
            capabilities.validate_query("sessions")

        conversion_rate = capabilities.get_metric_capability("conversion_rate")
        self.assertFalse(conversion_rate.supported)
        self.assertIn("denominator", conversion_rate.unavailable_reason.lower())
        with self.assertRaisesRegex(MetricNotSupportedError, "conversion_rate"):
            capabilities.validate_query("conversion_rate")

    def test_analytics_tools_reject_funnel_queries_without_sql(self) -> None:
        connection = NoSqlConnection()
        tools = AnalyticsTools(
            registry=self.registry,
            connection=connection,
            capabilities=build_olist_validation_capabilities(self.registry),
        )
        for metric_id in ("sessions", "conversion_rate"):
            with self.assertRaisesRegex(MetricQueryError, "Data source capability validation failed") as ctx:
                tools.query_metric(
                    metric=metric_id,
                    start_date=datetime.date(2017, 3, 20),
                    end_date=datetime.date(2017, 3, 20),
                    compare_to="previous_7_days",
                )
            self.assertIn(metric_id, str(ctx.exception))
        self.assertEqual(connection.cursor_calls, 0)

    def test_olist_dimensions_fail_closed_before_sql(self) -> None:
        connection = NoSqlConnection()
        tools = AnalyticsTools(
            registry=self.registry,
            connection=connection,
            capabilities=build_olist_validation_capabilities(self.registry),
        )
        for dimension in ("marketplace", "traffic_source", "asin"):
            with self.assertRaises(MetricQueryError):
                tools.query_metric(
                    metric="merchandise_gmv",
                    start_date=datetime.date(2017, 3, 20),
                    end_date=datetime.date(2017, 3, 20),
                    compare_to="previous_7_days",
                    group_by=[dimension],
                )
            with self.assertRaises(MetricQueryError):
                tools.query_metric(
                    metric="orders",
                    start_date=datetime.date(2017, 3, 20),
                    end_date=datetime.date(2017, 3, 20),
                    compare_to="previous_7_days",
                    filters={dimension: "value"},
                )
        self.assertEqual(connection.cursor_calls, 0)

    def test_wrong_provider_or_environment_is_rejected(self) -> None:
        wrong_provider = DataSourceDescriptor(
            source_id="wrong_provider",
            display_name="Wrong Provider",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.VALIDATION,
        )
        with self.assertRaises(OlistValidationCapabilityError):
            build_olist_validation_capabilities(self.registry, wrong_provider)

        wrong_environment = DataSourceDescriptor(
            source_id="wrong_environment",
            display_name="Wrong Environment",
            provider=SourceProvider.OLIST,
            environment=SourceEnvironment.LIVE,
        )
        with self.assertRaises(OlistValidationCapabilityError):
            build_olist_validation_capabilities(self.registry, wrong_environment)


if __name__ == "__main__":
    unittest.main()
