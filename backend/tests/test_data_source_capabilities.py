"""Unit tests for Data Source Capability Contract.

Verifies:
1. Basic valid contract;
2. Olist capability fixture (supported orders/aov/customer_state vs unavailable sessions/conversion_rate);
3. Different metrics having different dimensions;
4. Cross-grain combination protection (country-level pass vs product-level reject, grain enforcement);
5. Fail-closed validations (empty/blank fields, duplicates, invalid enums/types, unknown metrics/dimensions);
6. Deep immutability (frozen dataclasses, defensive copies, MappingProxyType).
"""

from dataclasses import FrozenInstanceError
import unittest

from app.data_sources import (
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


class TestDataSourceCapabilities(unittest.TestCase):
    """Test suite for Data Source Capability Contract domain models and behaviors."""

    def test_basic_valid_contract(self):
        """1. Basic valid contract: verify provider, environment, grain, and dimensions."""
        descriptor = DataSourceDescriptor(
            source_id="dw_synthetic_bench",
            display_name="Synthetic Benchmark Warehouse",
            provider=SourceProvider.SYNTHETIC,
            environment=SourceEnvironment.BENCHMARK,
        )
        self.assertEqual(descriptor.source_id, "dw_synthetic_bench")
        self.assertEqual(descriptor.display_name, "Synthetic Benchmark Warehouse")
        self.assertEqual(descriptor.provider, SourceProvider.SYNTHETIC)
        self.assertEqual(descriptor.environment, SourceEnvironment.BENCHMARK)

        sales_cap = MetricCapability(
            metric_id="sales",
            supported=True,
            grain=("date", "marketplace", "asin", "traffic_source"),
            dimensions=("marketplace", "asin", "traffic_source"),
        )
        orders_cap = MetricCapability(
            metric_id="orders",
            supported=True,
            grain=("date", "marketplace", "asin", "traffic_source"),
            dimensions=("marketplace", "asin", "traffic_source"),
        )

        caps = DataSourceCapabilities(descriptor, [sales_cap, orders_cap])

        self.assertEqual(caps.descriptor, descriptor)
        self.assertTrue(caps.has_metric("sales"))
        self.assertTrue(caps.has_metric("orders"))
        self.assertFalse(caps.has_metric("nonexistent"))

        got_sales = caps.get_metric_capability("sales")
        self.assertEqual(got_sales.metric_id, "sales")
        self.assertTrue(got_sales.supported)
        self.assertEqual(got_sales.grain, ("date", "marketplace", "asin", "traffic_source"))
        self.assertEqual(got_sales.dimensions, ("marketplace", "asin", "traffic_source"))
        self.assertIsNone(got_sales.unavailable_reason)

        self.assertTrue(caps.is_metric_supported("sales"))
        self.assertTrue(caps.is_dimension_supported("sales", "marketplace"))
        self.assertTrue(caps.is_dimension_supported("sales", "asin"))
        self.assertFalse(caps.is_dimension_supported("sales", "customer_state"))

    def test_olist_capability_fixture(self):
        """2. Olist capability fixture:

        Supports: merchandise_gmv, orders, olist_aov on customer_state.
        Explicitly unsupported: sessions, conversion_rate, marketplace, traffic_source, asin.
        Verifies unavailable metrics fail closed and are not faked by proxy fields.
        """
        descriptor = DataSourceDescriptor(
            source_id="olist_public_dataset",
            display_name="Olist Brazilian E-Commerce",
            provider=SourceProvider.OLIST,
            environment=SourceEnvironment.VALIDATION,
        )

        metrics = [
            MetricCapability(
                metric_id="merchandise_gmv",
                supported=True,
                grain=("date", "customer_state"),
                dimensions=("customer_state",),
            ),
            MetricCapability(
                metric_id="orders",
                supported=True,
                grain=("date", "customer_state"),
                dimensions=("customer_state",),
            ),
            MetricCapability(
                metric_id="olist_aov",
                supported=True,
                grain=("date", "customer_state"),
                dimensions=("customer_state",),
            ),
            MetricCapability(
                metric_id="sessions",
                supported=False,
                unavailable_reason="Olist dataset does not record session or web traffic event stream",
            ),
            MetricCapability(
                metric_id="conversion_rate",
                supported=False,
                unavailable_reason="Conversion rate requires session denominator which is unavailable in Olist",
            ),
        ]

        caps = DataSourceCapabilities(descriptor, metrics)

        # Supported metrics
        self.assertTrue(caps.is_metric_supported("merchandise_gmv"))
        self.assertTrue(caps.is_metric_supported("orders"))
        self.assertTrue(caps.is_metric_supported("olist_aov"))
        self.assertTrue(caps.is_dimension_supported("merchandise_gmv", "customer_state"))

        # Missing metrics explicitly marked as unavailable
        self.assertFalse(caps.is_metric_supported("sessions"))
        self.assertFalse(caps.is_metric_supported("conversion_rate"))

        sessions_cap = caps.get_metric_capability("sessions")
        self.assertFalse(sessions_cap.supported)
        self.assertEqual(sessions_cap.dimensions, ())
        self.assertEqual(sessions_cap.grain, ())
        self.assertIn("session or web traffic event stream", sessions_cap.unavailable_reason)

        conv_cap = caps.get_metric_capability("conversion_rate")
        self.assertFalse(conv_cap.supported)
        self.assertEqual(conv_cap.dimensions, ())
        self.assertEqual(conv_cap.grain, ())
        self.assertIn("session denominator", conv_cap.unavailable_reason)

        # Querying unsupported metrics must fail closed
        with self.assertRaises(MetricNotSupportedError) as ctx:
            caps.validate_query("sessions", group_by=["customer_state"])
        self.assertIn("sessions", str(ctx.exception))
        self.assertIn("Olist dataset does not record session", str(ctx.exception))

        with self.assertRaises(MetricNotSupportedError) as ctx:
            caps.validate_query("conversion_rate")
        self.assertIn("conversion_rate", str(ctx.exception))

        # Unsupported dimensions on supported metrics must be rejected
        for unsupported_dim in ("marketplace", "traffic_source", "asin"):
            self.assertFalse(caps.is_dimension_supported("merchandise_gmv", unsupported_dim))
            with self.assertRaises(UnsupportedDimensionError):
                caps.validate_query("merchandise_gmv", group_by=[unsupported_dim])
            with self.assertRaises(UnsupportedDimensionError):
                caps.validate_query("orders", filters={unsupported_dim: "val"})

        # Combination involving unsupported metric must be rejected
        self.assertFalse(caps.can_combine_metrics("orders", "sessions", ["customer_state"]))
        with self.assertRaises(MetricNotSupportedError):
            caps.validate_metric_combination("orders", "sessions", ["customer_state"])

    def test_different_metrics_different_dimensions(self):
        """3. Different metrics have different dimensions:

        sales supports product and country;
        sessions only supports country and traffic_source.
        """
        descriptor = DataSourceDescriptor(
            source_id="shopify_store_live",
            display_name="Shopify Live Store",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.LIVE,
        )

        caps = DataSourceCapabilities(
            descriptor,
            [
                MetricCapability(
                    metric_id="sales",
                    supported=True,
                    grain=("date", "country", "product"),
                    dimensions=("product", "country"),
                ),
                MetricCapability(
                    metric_id="sessions",
                    supported=True,
                    grain=("date", "country", "traffic_source"),
                    dimensions=("country", "traffic_source"),
                ),
            ],
        )

        # Sales supports product
        self.assertTrue(caps.is_dimension_supported("sales", "product"))
        self.assertTrue(caps.is_dimension_supported("sales", "country"))
        self.assertFalse(caps.is_dimension_supported("sales", "traffic_source"))

        group_by, _ = caps.validate_query("sales", group_by=["product", "country"])
        self.assertEqual(group_by, ("product", "country"))

        # Sessions does NOT support product
        self.assertFalse(caps.is_dimension_supported("sessions", "product"))
        self.assertTrue(caps.is_dimension_supported("sessions", "country"))
        self.assertTrue(caps.is_dimension_supported("sessions", "traffic_source"))

        with self.assertRaises(UnsupportedDimensionError) as ctx:
            caps.validate_query("sessions", group_by=["product"])
        self.assertIn("product", str(ctx.exception))
        self.assertIn("sessions", str(ctx.exception))

        # System must not infer that sessions supports product just because sales supports it
        self.assertNotIn("product", caps.get_metric_capability("sessions").dimensions)

    def test_cross_grain_combination_protection(self):
        """4. Cross-grain combination protection:

        - sales and sessions do not share product -> product-level combination rejected;
        - sales and sessions share country and grain -> country-level combination allowed;
        - cannot just compare dimension names while ignoring grain.
        """
        descriptor = DataSourceDescriptor(
            source_id="multi_grain_source",
            display_name="Multi Grain Source",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.LIVE,
        )

        caps = DataSourceCapabilities(
            descriptor,
            [
                MetricCapability(
                    metric_id="sales",
                    supported=True,
                    grain=("date", "country", "product"),
                    dimensions=("country", "product"),
                ),
                MetricCapability(
                    metric_id="sessions",
                    supported=True,
                    grain=("date", "country", "traffic_source"),
                    dimensions=("country", "traffic_source"),
                ),
            ],
        )

        # Product-level combination: rejected because sessions does not support product
        self.assertFalse(caps.can_combine_metrics("sales", "sessions", ["product"]))
        with self.assertRaises(UnsupportedDimensionError):
            caps.validate_metric_combination("sales", "sessions", ["product"])

        # Country-level combination: allowed because both have country in grain and dimensions
        self.assertTrue(caps.can_combine_metrics("sales", "sessions", ["country"]))
        combined = caps.validate_metric_combination("sales", "sessions", ["country"])
        self.assertEqual(combined, ("country",))

        # Critical: Cannot just compare dimension names while ignoring grain!
        # Construct a scenario where a metric's dimensions include 'product',
        # but its atomic grain only provides 'date' and 'country' (no product grain).
        deceptive_sessions = MetricCapability(
            metric_id="deceptive_sessions",
            supported=True,
            grain=("date", "country"),  # Does NOT contain product in grain!
            dimensions=("country", "product"),  # Declares product in dimensions
        )
        caps_with_deceptive = DataSourceCapabilities(
            descriptor,
            [
                MetricCapability(
                    metric_id="sales",
                    supported=True,
                    grain=("date", "country", "product"),
                    dimensions=("country", "product"),
                ),
                deceptive_sessions,
            ],
        )

        # Even though both metrics declare 'product' in dimensions,
        # combination MUST be rejected because deceptive_sessions lacks 'product' in grain.
        self.assertFalse(
            caps_with_deceptive.can_combine_metrics("sales", "deceptive_sessions", ["product"])
        )
        with self.assertRaises(IncompatibleGrainError) as ctx:
            caps_with_deceptive.validate_metric_combination(
                "sales", "deceptive_sessions", ["product"]
            )
        self.assertIn("not present in grain for metric 'deceptive_sessions'", str(ctx.exception))

    def test_fail_closed_validation(self):
        """5. Fail-closed validation across domain boundaries."""
        # Empty or blank source_id
        with self.assertRaises(CapabilityContractError):
            DataSourceDescriptor(
                source_id="",
                display_name="Name",
                provider=SourceProvider.POSTGRESQL,
                environment=SourceEnvironment.LIVE,
            )
        with self.assertRaises(CapabilityContractError):
            DataSourceDescriptor(
                source_id="   ",
                display_name="Name",
                provider=SourceProvider.POSTGRESQL,
                environment=SourceEnvironment.LIVE,
            )

        # Empty or blank display_name
        with self.assertRaises(CapabilityContractError):
            DataSourceDescriptor(
                source_id="src_1",
                display_name="",
                provider=SourceProvider.POSTGRESQL,
                environment=SourceEnvironment.LIVE,
            )
        with self.assertRaises(CapabilityContractError):
            DataSourceDescriptor(
                source_id="src_1",
                display_name="   ",
                provider=SourceProvider.POSTGRESQL,
                environment=SourceEnvironment.LIVE,
            )

        # Invalid provider or environment (strict enum check)
        with self.assertRaises(CapabilityContractError):
            DataSourceDescriptor(
                source_id="src_1",
                display_name="Name",
                provider="postgresql",  # string instead of enum member
                environment=SourceEnvironment.LIVE,
            )
        with self.assertRaises(CapabilityContractError):
            DataSourceDescriptor(
                source_id="src_1",
                display_name="Name",
                provider=SourceProvider.POSTGRESQL,
                environment="live",  # string instead of enum member
            )

        # Empty or blank metric_id
        with self.assertRaises(CapabilityContractError):
            MetricCapability(metric_id="", supported=True, grain=("date",), dimensions=("country",))
        with self.assertRaises(CapabilityContractError):
            MetricCapability(metric_id="   ", supported=True, grain=("date",), dimensions=("country",))

        # Python boundary: supported must be strict bool, not int (0 or 1)
        with self.assertRaises(CapabilityContractError):
            MetricCapability(metric_id="m", supported=1, grain=("date",), dimensions=("country",))
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=0,
                unavailable_reason="test",
            )

        # Duplicate or blank dimensions in MetricCapability
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=True,
                grain=("date",),
                dimensions=("country", "country"),
            )
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=True,
                grain=("date",),
                dimensions=("country", "  "),
            )

        # Duplicate or blank elements in grain
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=True,
                grain=("date", "date"),
                dimensions=("country",),
            )
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=True,
                grain=("date", ""),
                dimensions=("country",),
            )

        # Supported metric must have non-empty grain
        with self.assertRaises(CapabilityContractError):
            MetricCapability(metric_id="m", supported=True, grain=(), dimensions=("country",))

        # Supported metric must not specify unavailable_reason
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=True,
                grain=("date",),
                dimensions=("country",),
                unavailable_reason="some reason",
            )

        # Unsupported metric missing reason
        with self.assertRaises(CapabilityContractError):
            MetricCapability(metric_id="m", supported=False, unavailable_reason=None)
        with self.assertRaises(CapabilityContractError):
            MetricCapability(metric_id="m", supported=False, unavailable_reason="   ")

        # Unsupported metric still declaring dimensions or grain
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=False,
                unavailable_reason="Missing data",
                dimensions=("country",),
            )
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=False,
                unavailable_reason="Missing data",
                grain=("date",),
            )

        descriptor = DataSourceDescriptor(
            source_id="src_1",
            display_name="Source 1",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.LIVE,
        )

        # Duplicate metric in sequence
        with self.assertRaises(CapabilityContractError):
            DataSourceCapabilities(
                descriptor,
                [
                    MetricCapability(metric_id="sales", supported=True, grain=("date",), dimensions=()),
                    MetricCapability(metric_id="sales", supported=True, grain=("date",), dimensions=()),
                ],
            )

        # Key mismatch in mapping
        with self.assertRaises(CapabilityContractError):
            DataSourceCapabilities(
                descriptor,
                {
                    "wrong_key": MetricCapability(
                        metric_id="sales", supported=True, grain=("date",), dimensions=()
                    )
                },
            )

        caps = DataSourceCapabilities(
            descriptor,
            [
                MetricCapability(
                    metric_id="sales",
                    supported=True,
                    grain=("date", "country"),
                    dimensions=("country",),
                )
            ],
        )

        # Unknown metric lookup
        with self.assertRaises(UnknownMetricError):
            caps.get_metric_capability("unknown_metric")
        with self.assertRaises(UnknownMetricError):
            caps.is_metric_supported("unknown_metric")
        with self.assertRaises(UnknownMetricError):
            caps.is_dimension_supported("unknown_metric", "country")
        with self.assertRaises(UnknownMetricError):
            caps.validate_query("unknown_metric")
        with self.assertRaises(UnknownMetricError):
            caps.validate_metric_combination("unknown_metric", "sales", ["country"])

        # Unknown group_by dimension
        with self.assertRaises(UnsupportedDimensionError):
            caps.validate_query("sales", group_by=["unknown_dim"])

        # Unknown filter dimension
        with self.assertRaises(UnsupportedDimensionError):
            caps.validate_query("sales", filters={"unknown_dim": "val"})

        # Group by with duplicates or blanks
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", group_by=["country", "country"])
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", group_by=["country", ""])

        # Supported metric with invalid non-string unavailable_reason must raise CapabilityContractError, not AttributeError
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=True,
                grain=("date",),
                dimensions=("country",),
                unavailable_reason=123,
            )
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=True,
                grain=("date",),
                dimensions=("country",),
                unavailable_reason=["invalid"],
            )
        with self.assertRaises(CapabilityContractError):
            MetricCapability(
                metric_id="m",
                supported=False,
                unavailable_reason=123,
            )

        # Filters as str or bytes must be explicitly rejected
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", filters="")
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", filters="country")
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", filters=b"country")

        # Group by as str or bytes must be explicitly rejected
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", group_by="")
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", group_by="country")
        with self.assertRaises(CapabilityContractError):
            caps.validate_query("sales", group_by=b"country")

        # on_dimensions as str or bytes must be explicitly rejected
        with self.assertRaises(CapabilityContractError):
            caps.validate_metric_combination("sales", "sales", on_dimensions="")
        with self.assertRaises(CapabilityContractError):
            caps.validate_metric_combination("sales", "sales", on_dimensions="country")

        # Metrics as str or bytes must be explicitly rejected
        with self.assertRaises(CapabilityContractError):
            DataSourceCapabilities(descriptor, metrics="")
        with self.assertRaises(CapabilityContractError):
            DataSourceCapabilities(descriptor, metrics="sales")

        # Combination on empty dimensions
        with self.assertRaises(CapabilityContractError):
            caps.validate_metric_combination("sales", "sales", [])

    def test_deep_immutability(self):
        """6. Deep immutability:

        Verifies that modifying source collections after construction does not alter the contract,
        internal and external containers are truly immutable, and attributes cannot be rebound.
        """
        initial_grain = ["date", "country", "product"]
        initial_dims = ["country", "product"]

        metric_cap = MetricCapability(
            metric_id="sales",
            supported=True,
            grain=initial_grain,
            dimensions=initial_dims,
        )

        # Mutate the source list
        initial_grain.append("tampered_grain")
        initial_dims.append("tampered_dim")

        # Metric capability must remain unaffected
        self.assertEqual(metric_cap.grain, ("date", "country", "product"))
        self.assertEqual(metric_cap.dimensions, ("country", "product"))

        # Frozen dataclass fields cannot be modified
        with self.assertRaises(FrozenInstanceError):
            metric_cap.metric_id = "new_sales"
        with self.assertRaises(FrozenInstanceError):
            metric_cap.grain = ("new_grain",)

        descriptor = DataSourceDescriptor(
            source_id="src_immutable",
            display_name="Immutable Source",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.LIVE,
        )

        with self.assertRaises(FrozenInstanceError):
            descriptor.source_id = "tampered_id"

        metrics_dict = {"sales": metric_cap}
        caps = DataSourceCapabilities(descriptor, metrics_dict)

        # DataSourceCapabilities attributes cannot be rebound on object level
        with self.assertRaises(FrozenInstanceError):
            caps.descriptor = DataSourceDescriptor(
                source_id="tampered_desc",
                display_name="Tampered",
                provider=SourceProvider.SHOPIFY,
                environment=SourceEnvironment.SANDBOX,
            )
        with self.assertRaises(FrozenInstanceError):
            caps._metrics = {}
        with self.assertRaises(FrozenInstanceError):
            caps.new_arbitrary_attr = "injected"

        # Mutating original dictionary does not affect capabilities
        metrics_dict["injected_metric"] = MetricCapability(
            metric_id="injected_metric",
            supported=True,
            grain=("date",),
            dimensions=(),
        )
        self.assertFalse(caps.has_metric("injected_metric"))

        # Internal _metrics mapping is MappingProxyType and cannot be modified
        with self.assertRaises(TypeError):
            caps._metrics["sales"] = MetricCapability(
                metric_id="sales",
                supported=False,
                unavailable_reason="tampered",
            )
        with self.assertRaises(TypeError):
            del caps._metrics["sales"]

        # Returned metrics mapping is also MappingProxyType and cannot be modified
        returned_metrics = caps.metrics
        with self.assertRaises(TypeError):
            returned_metrics["sales"] = MetricCapability(
                metric_id="sales",
                supported=False,
                unavailable_reason="test",
            )


if __name__ == "__main__":
    unittest.main()
