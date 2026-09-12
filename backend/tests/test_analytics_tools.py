"""Unit tests for AnalyticsTools and query_metric."""

import datetime
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from app.analytics.models import (
    MetricQueryError,
    MetricQueryRow,
    RelatedMetricQueryResult,
)
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricRegistry


class FakeCursor:
    """Minimal fake database cursor for hermetic unit tests."""

    def __init__(self, fetch_result: list | None = None) -> None:
        self.fetch_result = fetch_result if fetch_result is not None else []
        self.executed_query = None
        self.executed_params = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def execute(self, query, params=None) -> None:
        self.executed_query = query
        self.executed_params = params

    def fetchall(self) -> list:
        return self.fetch_result


class FakeConnection:
    """Minimal fake database connection returning a configured FakeCursor."""

    def __init__(self, fetch_result: list | None = None) -> None:
        self.cursor_obj = FakeCursor(fetch_result)

    def cursor(self) -> FakeCursor:
        return self.cursor_obj


class TestAnalyticsTools(unittest.TestCase):
    """Unit tests verifying AnalyticsTools behavior, validations, and Decimal calculations."""

    def setUp(self) -> None:
        yaml_path = (
            Path(__file__).resolve().parent.parent.parent
            / "configs"
            / "metrics.yaml"
        )
        self.registry = MetricRegistry.from_yaml(yaml_path)
        self.test_date = datetime.date(2026, 1, 31)

    def test_get_metric_definition(self) -> None:
        """Verify get_metric_definition returns valid MetricDefinition from registry."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        defn = tools.get_metric_definition("sales")
        self.assertEqual(defn.metric_id, "sales")
        self.assertEqual(defn.unit, "usd")
        self.assertEqual(defn.metric_type, "additive")

    def test_query_metric_unknown_metric_raises(self) -> None:
        """Verify querying an unknown metric raises MetricQueryError."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_metric(
                metric="unknown_metric",
                start_date=self.test_date,
                end_date=self.test_date,
                compare_to="previous_7_days",
            )
        self.assertIn("Unknown metric", str(ctx.exception))

    def test_query_metric_multi_day_date_range_raises(self) -> None:
        """Verify non-single-day start/end date raises MetricQueryError."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_metric(
                metric="sales",
                start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2026, 1, 2),
                compare_to="previous_7_days",
            )
        self.assertIn("Only single-day current period", str(ctx.exception))

    def test_query_metric_unsupported_compare_to_raises(self) -> None:
        """Verify unsupported compare_to values raise MetricQueryError."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_metric(
                metric="sales",
                start_date=self.test_date,
                end_date=self.test_date,
                compare_to="previous_year",
            )
        self.assertIn("Unsupported compare_to", str(ctx.exception))

    def test_query_metric_unknown_filter_dimension_raises(self) -> None:
        """Verify filtering on an unsupported dimension raises MetricQueryError."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_metric(
                metric="sales",
                start_date=self.test_date,
                end_date=self.test_date,
                compare_to="previous_7_days",
                filters={"non_existent_dim": "US"},
            )
        self.assertIn("Invalid filter dimension", str(ctx.exception))

    def test_query_metric_unknown_group_by_dimension_raises(self) -> None:
        """Verify grouping by an unsupported dimension raises MetricQueryError."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_metric(
                metric="sales",
                start_date=self.test_date,
                end_date=self.test_date,
                compare_to="previous_7_days",
                group_by=["unknown_group"],
            )
        self.assertIn("Invalid group_by dimension", str(ctx.exception))

    def test_query_metric_duplicate_group_by_raises(self) -> None:
        """Verify duplicate dimensions in group_by raise MetricQueryError."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_metric(
                metric="sales",
                start_date=self.test_date,
                end_date=self.test_date,
                compare_to="previous_7_days",
                group_by=["marketplace", "marketplace"],
            )
        self.assertIn("Duplicate dimensions", str(ctx.exception))

    def test_query_metric_additive_calculation(self) -> None:
        """Verify additive metric calculations: current sum, 7-day average baseline, and relative change."""
        fake_data = [
            (Decimal("7000.00"), None, Decimal("350.00"), 7, Decimal("900.00"), None)
        ]
        conn = FakeConnection(fake_data)
        tools = AnalyticsTools(self.registry, conn)

        result = tools.query_metric(
            metric="sales",
            start_date=self.test_date,
            end_date=self.test_date,
            compare_to="previous_7_days",
        )

        self.assertEqual(result.metric_id, "sales")
        self.assertEqual(result.unit, "usd")
        self.assertEqual(len(result.rows), 1)

        row = result.rows[0]
        self.assertEqual(row.current_value, Decimal("900.00"))
        self.assertEqual(row.baseline_value, Decimal("1000.00"))
        self.assertEqual(row.relative_change, Decimal("-0.1"))
        self.assertEqual(row.status, "ok")
        self.assertEqual(row.sample_size, Decimal("350.00"))

    def test_query_metric_ratio_calculation(self) -> None:
        """Verify ratio metric calculates aggregated numerator / aggregated denominator."""
        fake_data = [
            (Decimal("70"), Decimal("700"), Decimal("100.00"), 7, Decimal("8"), Decimal("100"))
        ]
        conn = FakeConnection(fake_data)
        tools = AnalyticsTools(self.registry, conn)

        result = tools.query_metric(
            metric="conversion_rate",
            start_date=self.test_date,
            end_date=self.test_date,
            compare_to="previous_7_days",
        )

        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(row.current_value, Decimal("0.08"))
        self.assertEqual(row.baseline_value, Decimal("0.10"))
        self.assertEqual(row.relative_change, Decimal("-0.2"))
        self.assertEqual(row.status, "ok")

    def test_query_metric_zero_denominator_unavailable(self) -> None:
        """Verify that zero denominator in ratio metric marks status as unavailable and relative_change as None."""
        fake_data = [
            (Decimal("70"), Decimal("700"), Decimal("100.00"), 7, Decimal("0"), Decimal("0"))
        ]
        conn = FakeConnection(fake_data)
        tools = AnalyticsTools(self.registry, conn)

        result = tools.query_metric(
            metric="conversion_rate",
            start_date=self.test_date,
            end_date=self.test_date,
            compare_to="previous_7_days",
        )

        row = result.rows[0]
        self.assertIsNone(row.current_value)
        self.assertEqual(row.status, "unavailable")
        self.assertIsNone(row.relative_change)

    def test_query_metric_insufficient_sample_size(self) -> None:
        """Verify baseline daily average sessions < 30 marks status as insufficient_data."""
        fake_data = [
            (Decimal("70"), Decimal("140"), Decimal("20.00"), 7, Decimal("8"), Decimal("25"))
        ]
        conn = FakeConnection(fake_data)
        tools = AnalyticsTools(self.registry, conn)

        result = tools.query_metric(
            metric="conversion_rate",
            start_date=self.test_date,
            end_date=self.test_date,
            compare_to="previous_7_days",
        )

        row = result.rows[0]
        self.assertEqual(row.status, "insufficient_data")
        self.assertIsNone(row.relative_change)

    def test_query_metric_group_by_dimension_mapping(self) -> None:
        """Verify group_by queries map dimension keys correctly to row values."""
        fake_data = [
            ("DE", Decimal("700"), None, Decimal("100.00"), 7, Decimal("100"), None),
            ("UK", Decimal("1400"), None, Decimal("200.00"), 7, Decimal("200"), None),
            ("US", Decimal("3500"), None, Decimal("500.00"), 7, Decimal("400"), None),
        ]
        conn = FakeConnection(fake_data)
        tools = AnalyticsTools(self.registry, conn)

        result = tools.query_metric(
            metric="sales",
            start_date=self.test_date,
            end_date=self.test_date,
            compare_to="previous_7_days",
            group_by=["marketplace"],
        )

        self.assertEqual(result.group_by, ("marketplace",))
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(result.rows[0].dimensions, {"marketplace": "DE"})
        self.assertEqual(result.rows[1].dimensions, {"marketplace": "UK"})
        self.assertEqual(result.rows[2].dimensions, {"marketplace": "US"})
        self.assertEqual(result.rows[2].current_value, Decimal("400"))
        self.assertEqual(result.rows[2].baseline_value, Decimal("500"))
        self.assertEqual(result.rows[2].relative_change, Decimal("-0.2"))

    def test_query_metric_filter_parameter_binding(self) -> None:
        """Verify filter values and dates are passed as parameterized arguments without string interpolation."""
        fake_data = [
            (Decimal("3500.00"), None, Decimal("500.00"), 7, Decimal("400.00"), None)
        ]
        conn = FakeConnection(fake_data)
        tools = AnalyticsTools(self.registry, conn)

        tools.query_metric(
            metric="sales",
            start_date=self.test_date,
            end_date=self.test_date,
            compare_to="previous_7_days",
            filters={"marketplace": "US"},
        )

        cursor = conn.cursor_obj
        self.assertIn("US", cursor.executed_params)
        self.assertIn(datetime.date(2026, 1, 24), cursor.executed_params)
        self.assertIn(datetime.date(2026, 1, 30), cursor.executed_params)
        self.assertIn(datetime.date(2026, 1, 31), cursor.executed_params)

    def test_metric_query_row_source_dict_mutation_isolation(self) -> None:
        """Verify mutating the source dictionary passed to MetricQueryRow does not alter row.dimensions."""
        source = {"marketplace": "US"}
        row = MetricQueryRow(
            dimensions=source,
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0"),
            status="ok",
            sample_size=Decimal("50"),
        )
        source["marketplace"] = "DE"
        self.assertEqual(row.dimensions["marketplace"], "US")
        self.assertEqual(row.dimensions, {"marketplace": "US"})

    def test_metric_query_row_dimensions_direct_mutation_raises_type_error(self) -> None:
        """Verify attempting to directly mutate row.dimensions raises TypeError and preserves values."""
        row = MetricQueryRow(
            dimensions={"marketplace": "US"},
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0"),
            status="ok",
            sample_size=Decimal("50"),
        )
        with self.assertRaises(TypeError):
            row.dimensions["marketplace"] = "DE"  # type: ignore[index]
        self.assertEqual(row.dimensions["marketplace"], "US")
        self.assertEqual(row.dimensions, {"marketplace": "US"})

    def test_query_related_metrics_success_and_order(self) -> None:
        """Verify query_related_metrics queries and returns all related metrics in declared order."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        mock_query_metric = MagicMock()
        tools.query_metric = mock_query_metric

        # sales related_metrics declared order: orders, sessions, conversion_rate, aov
        def side_effect(metric, **kwargs):
            return MagicMock(metric_id=metric)

        mock_query_metric.side_effect = side_effect

        rel_result = tools.query_related_metrics(
            metric="sales",
            start_date=self.test_date,
            end_date=self.test_date,
            compare_to="previous_7_days",
            filters={"marketplace": "US"},
            group_by=["asin"],
        )

        self.assertIsInstance(rel_result, RelatedMetricQueryResult)
        self.assertEqual(rel_result.source_metric_id, "sales")
        self.assertIsInstance(rel_result.results, tuple)
        self.assertEqual(len(rel_result.results), 4)

        result_ids = [r.metric_id for r in rel_result.results]
        self.assertEqual(result_ids, ["orders", "sessions", "conversion_rate", "aov"])

        # Verify arguments forwarded to each query_metric call
        self.assertEqual(mock_query_metric.call_count, 4)
        for call_args in mock_query_metric.call_args_list:
            self.assertEqual(call_args.kwargs["start_date"], self.test_date)
            self.assertEqual(call_args.kwargs["end_date"], self.test_date)
            self.assertEqual(call_args.kwargs["compare_to"], "previous_7_days")
            self.assertEqual(call_args.kwargs["filters"], {"marketplace": "US"})
            self.assertEqual(call_args.kwargs["group_by"], ["asin"])

    def test_query_related_metrics_unknown_metric_raises(self) -> None:
        """Verify query_related_metrics fails fast when source metric is unknown."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_related_metrics(
                metric="invalid_source",
                start_date=self.test_date,
                end_date=self.test_date,
                compare_to="previous_7_days",
            )
        self.assertIn("Unknown metric", str(ctx.exception))

    def test_query_related_metrics_child_error_propagates(self) -> None:
        """Verify errors in child query_metric calls propagate directly without being swallowed."""
        tools = AnalyticsTools(self.registry, FakeConnection())
        with self.assertRaises(MetricQueryError) as ctx:
            tools.query_related_metrics(
                metric="sales",
                start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2026, 1, 2),  # Multi-day error
                compare_to="previous_7_days",
            )
        self.assertIn("Only single-day current period", str(ctx.exception))

    def test_related_metric_query_result_source_list_mutation_isolation(self) -> None:
        """Verify constructing RelatedMetricQueryResult with a list creates an independent tuple snapshot."""
        fake_result = MagicMock()
        source_list = [fake_result]
        related = RelatedMetricQueryResult(
            source_metric_id="sales",
            results=source_list,  # type: ignore[arg-type]
        )
        source_list.clear()

        self.assertIsInstance(related.results, tuple)
        self.assertEqual(len(related.results), 1)
        self.assertIs(related.results[0], fake_result)


if __name__ == "__main__":
    unittest.main()
