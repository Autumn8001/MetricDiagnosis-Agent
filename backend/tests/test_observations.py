"""Hermetic unit tests for Observation domain models and mapper functions."""

import datetime
from decimal import Decimal
import unittest

from app.analytics.models import DateRange, MetricQueryRow, MetricQueryResult, RelatedMetricQueryResult
from app.observations.mapper import (
    classify_metric_row_status,
    failed_observation,
    observations_from_metric_query,
    observations_from_related_metric_query,
    observations_from_tool_result,
)
from app.observations.models import (
    Observation,
    ObservationError,
    ObservationStatus,
    ObservationValidationError,
)


class TestObservations(unittest.TestCase):
    """Test suite for Observation models and transformation mappers."""

    def setUp(self) -> None:
        self.utc_now = datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.current_period = DateRange(datetime.date(2026, 1, 15), datetime.date(2026, 1, 15))
        self.baseline_period = DateRange(datetime.date(2026, 1, 8), datetime.date(2026, 1, 14))

    def test_single_row_normal_conversion(self) -> None:
        """Verify normal/stable fluctuation is classified as ObservationStatus.NORMAL."""
        row = MetricQueryRow(
            dimensions={"marketplace": "US"},
            current_value=Decimal("970.00"),
            baseline_value=Decimal("1000.00"),
            relative_change=Decimal("-0.0300"),
            status="ok",
            sample_size=Decimal("500"),
        )
        result = MetricQueryResult(
            metric_id="sales",
            unit="usd",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=("marketplace",),
            rows=(row,),
        )

        obs_tuple = observations_from_metric_query(
            result,
            tool_name="query_metric",
            tool_call_id="call_001",
            filters={"category": "Electronics"},
            query_or_result_reference="ref_sales_us",
            created_at=self.utc_now,
        )

        self.assertEqual(len(obs_tuple), 1)
        obs = obs_tuple[0]
        self.assertEqual(obs.observation_id, "call_001_sales_0")
        self.assertEqual(obs.tool_name, "query_metric")
        self.assertEqual(obs.tool_call_id, "call_001")
        self.assertEqual(obs.metric, "sales")
        self.assertEqual(obs.unit, "usd")
        self.assertEqual(obs.current_period, self.current_period)
        self.assertEqual(obs.baseline_period, self.baseline_period)
        self.assertEqual(obs.filters, {"category": "Electronics"})
        self.assertEqual(obs.group_by, ("marketplace",))
        self.assertEqual(obs.dimensions, {"marketplace": "US"})
        self.assertEqual(obs.current_value, Decimal("970.00"))
        self.assertEqual(obs.baseline_value, Decimal("1000.00"))
        self.assertEqual(obs.relative_change, Decimal("-0.0300"))
        self.assertEqual(obs.sample_size, Decimal("500"))
        self.assertEqual(obs.source_status, "ok")
        self.assertEqual(obs.status, ObservationStatus.NORMAL)
        self.assertEqual(obs.query_or_result_reference, "ref_sales_us")
        self.assertEqual(obs.created_at, self.utc_now)
        self.assertIsNone(obs.error_code)
        self.assertIsNone(obs.error_message)

    def test_material_decline_anomalous(self) -> None:
        """Verify material decline (<= -0.10) is classified as ObservationStatus.ANOMALOUS."""
        row = MetricQueryRow(
            dimensions={},
            current_value=Decimal("800.00"),
            baseline_value=Decimal("1000.00"),
            relative_change=Decimal("-0.2000"),
            status="ok",
            sample_size=Decimal("500"),
        )
        result = MetricQueryResult(
            metric_id="sales",
            unit="usd",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(row,),
        )

        obs_tuple = observations_from_metric_query(
            result,
            tool_name="query_metric",
            tool_call_id="call_002",
            filters=None,
            query_or_result_reference="ref_sales_global",
            created_at=self.utc_now,
        )

        self.assertEqual(len(obs_tuple), 1)
        self.assertEqual(obs_tuple[0].status, ObservationStatus.ANOMALOUS)

    def test_threshold_boundaries(self) -> None:
        """Verify exact mathematical boundaries for status classification."""
        cases = [
            (Decimal("-0.1000"), ObservationStatus.ANOMALOUS),
            (Decimal("-0.1500"), ObservationStatus.ANOMALOUS),
            (Decimal("-0.0999"), ObservationStatus.INCONCLUSIVE),
            (Decimal("-0.0500"), ObservationStatus.INCONCLUSIVE),
            (Decimal("-0.0499"), ObservationStatus.NORMAL),
            (Decimal("0.0000"), ObservationStatus.NORMAL),
            (Decimal("0.0499"), ObservationStatus.NORMAL),
            (Decimal("0.0500"), ObservationStatus.INCONCLUSIVE),
            (Decimal("0.1000"), ObservationStatus.INCONCLUSIVE),
            (Decimal("0.2500"), ObservationStatus.INCONCLUSIVE),
        ]

        for rel_change, expected_status in cases:
            with self.subTest(rel_change=rel_change, expected_status=expected_status):
                row = MetricQueryRow(
                    dimensions={},
                    current_value=Decimal("100"),
                    baseline_value=Decimal("100"),
                    relative_change=rel_change,
                    status="ok",
                    sample_size=Decimal("100"),
                )
                self.assertEqual(classify_metric_row_status(row), expected_status)

    def test_insufficient_data_and_unavailable(self) -> None:
        """Verify insufficient_data, unavailable, and None relative_change map to INSUFFICIENT_EVIDENCE."""
        row_insuff = MetricQueryRow(
            dimensions={"marketplace": "DE"},
            current_value=Decimal("10"),
            baseline_value=Decimal("15"),
            relative_change=None,
            status="insufficient_data",
            sample_size=Decimal("5"),
        )
        self.assertEqual(classify_metric_row_status(row_insuff), ObservationStatus.INSUFFICIENT_EVIDENCE)

        row_unavail = MetricQueryRow(
            dimensions={"marketplace": "UK"},
            current_value=None,
            baseline_value=None,
            relative_change=None,
            status="unavailable",
            sample_size=None,
        )
        self.assertEqual(classify_metric_row_status(row_unavail), ObservationStatus.INSUFFICIENT_EVIDENCE)

        row_ok_none_rel = MetricQueryRow(
            dimensions={},
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=None,
            status="ok",
            sample_size=Decimal("50"),
        )
        self.assertEqual(classify_metric_row_status(row_ok_none_rel), ObservationStatus.INSUFFICIENT_EVIDENCE)

    def test_group_by_multiple_rows_order_and_id_uniqueness(self) -> None:
        """Verify multi-row query preserves row order and generates distinct deterministic IDs."""
        rows = (
            MetricQueryRow(
                dimensions={"marketplace": "US"},
                current_value=Decimal("500"),
                baseline_value=Decimal("1000"),
                relative_change=Decimal("-0.5000"),
                status="ok",
                sample_size=Decimal("400"),
            ),
            MetricQueryRow(
                dimensions={"marketplace": "UK"},
                current_value=Decimal("300"),
                baseline_value=Decimal("305"),
                relative_change=Decimal("-0.0164"),
                status="ok",
                sample_size=Decimal("200"),
            ),
            MetricQueryRow(
                dimensions={"marketplace": "DE"},
                current_value=Decimal("200"),
                baseline_value=Decimal("198"),
                relative_change=Decimal("0.0101"),
                status="ok",
                sample_size=Decimal("150"),
            ),
        )
        result = MetricQueryResult(
            metric_id="conversion_rate",
            unit="ratio",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=("marketplace",),
            rows=rows,
        )

        obs_tuple = observations_from_metric_query(
            result,
            tool_name="query_metric",
            tool_call_id="call_cr_001",
            filters=None,
            query_or_result_reference="ref_cr_group",
            created_at=self.utc_now,
        )

        self.assertEqual(len(obs_tuple), 3)
        self.assertEqual([o.dimensions["marketplace"] for o in obs_tuple], ["US", "UK", "DE"])
        self.assertEqual([o.status for o in obs_tuple], [
            ObservationStatus.ANOMALOUS,
            ObservationStatus.NORMAL,
            ObservationStatus.NORMAL,
        ])
        self.assertEqual([o.observation_id for o in obs_tuple], [
            "call_cr_001_conversion_rate_0",
            "call_cr_001_conversion_rate_1",
            "call_cr_001_conversion_rate_2",
        ])

    def test_related_metrics_flatten_order_and_sub_metric_id(self) -> None:
        """Verify RelatedMetricQueryResult is flattened in order and uses individual metric IDs."""
        sub_orders = MetricQueryResult(
            metric_id="orders",
            unit="count",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(MetricQueryRow({}, Decimal("80"), Decimal("100"), Decimal("-0.2000"), "ok", Decimal("500")),),
        )
        sub_sessions = MetricQueryResult(
            metric_id="sessions",
            unit="count",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(MetricQueryRow({}, Decimal("500"), Decimal("505"), Decimal("-0.0099"), "ok", Decimal("500")),),
        )
        sub_cr = MetricQueryResult(
            metric_id="conversion_rate",
            unit="ratio",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(MetricQueryRow({}, Decimal("0.1600"), Decimal("0.2000"), Decimal("-0.2000"), "ok", Decimal("500")),),
        )
        sub_aov = MetricQueryResult(
            metric_id="aov",
            unit="usd",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(MetricQueryRow({}, Decimal("50.00"), Decimal("50.10"), Decimal("-0.0020"), "ok", Decimal("500")),),
        )

        related_result = RelatedMetricQueryResult(
            source_metric_id="sales",
            results=(sub_orders, sub_sessions, sub_cr, sub_aov),
        )

        obs_tuple = observations_from_related_metric_query(
            related_result,
            tool_name="query_related_metrics",
            tool_call_id="call_rel_001",
            filters={"marketplace": "US"},
            query_or_result_reference="ref_related_sales",
            created_at=self.utc_now,
        )

        self.assertEqual(len(obs_tuple), 4)
        self.assertEqual([o.metric for o in obs_tuple], ["orders", "sessions", "conversion_rate", "aov"])
        self.assertEqual([o.status for o in obs_tuple], [
            ObservationStatus.ANOMALOUS,
            ObservationStatus.NORMAL,
            ObservationStatus.ANOMALOUS,
            ObservationStatus.NORMAL,
        ])
        self.assertEqual([o.observation_id for o in obs_tuple], [
            "call_rel_001_rel0_orders_0",
            "call_rel_001_rel1_sessions_0",
            "call_rel_001_rel2_conversion_rate_0",
            "call_rel_001_rel3_aov_0",
        ])
        for obs in obs_tuple:
            self.assertEqual(obs.filters, {"marketplace": "US"})
            self.assertEqual(obs.tool_name, "query_related_metrics")

    def test_filters_and_dimensions_source_dict_mutation_isolation(self) -> None:
        """Verify external source dictionary mutations do not affect Observation."""
        src_filters = {"marketplace": "US"}
        src_dimensions = {"asin": "ASIN-A"}

        obs = Observation(
            observation_id="obs_iso_001",
            tool_name="query_metric",
            tool_call_id="call_iso",
            metric="sales",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters=src_filters,
            group_by=("asin",),
            dimensions=src_dimensions,
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0"),
            unit="usd",
            sample_size=Decimal("50"),
            source_status="ok",
            status=ObservationStatus.NORMAL,
            query_or_result_reference="ref_iso",
            created_at=self.utc_now,
        )

        # Mutate source dicts
        src_filters["marketplace"] = "MUTATED"
        src_dimensions["asin"] = "MUTATED"

        self.assertEqual(obs.filters["marketplace"], "US")
        self.assertEqual(obs.dimensions["asin"], "ASIN-A")

    def test_observation_mapping_mutation_raises_type_error(self) -> None:
        """Verify direct mutation of Observation.filters or Observation.dimensions raises TypeError."""
        obs = Observation(
            observation_id="obs_mut_001",
            tool_name="query_metric",
            tool_call_id="call_mut",
            metric="sales",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={"marketplace": "US"},
            group_by=(),
            dimensions={"asin": "ASIN-A"},
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0"),
            unit="usd",
            sample_size=Decimal("50"),
            source_status="ok",
            status=ObservationStatus.NORMAL,
            query_or_result_reference="ref_mut",
            created_at=self.utc_now,
        )

        with self.assertRaises(TypeError):
            obs.filters["marketplace"] = "DE"  # type: ignore

        with self.assertRaises(TypeError):
            obs.dimensions["asin"] = "ASIN-B"  # type: ignore

    def test_group_by_source_list_mutation_isolation(self) -> None:
        """Verify passing a mutable list to group_by creates an isolated immutable tuple snapshot."""
        src_group_by = ["marketplace", "asin"]
        obs = Observation(
            observation_id="obs_grp_001",
            tool_name="query_metric",
            tool_call_id="call_grp",
            metric="sales",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={},
            group_by=src_group_by,  # type: ignore
            dimensions={},
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0"),
            unit="usd",
            sample_size=Decimal("50"),
            source_status="ok",
            status=ObservationStatus.NORMAL,
            query_or_result_reference="ref_grp",
            created_at=self.utc_now,
        )

        src_group_by.append("traffic_source")
        self.assertEqual(obs.group_by, ("marketplace", "asin"))

    def test_naive_datetime_rejected(self) -> None:
        """Verify naive datetime (no tzinfo) is rejected with ObservationValidationError."""
        naive_dt = datetime.datetime(2026, 1, 15, 12, 0, 0)
        with self.assertRaises(ObservationValidationError):
            Observation(
                observation_id="obs_naive",
                tool_name="query_metric",
                tool_call_id="call_naive",
                metric="sales",
                current_period=self.current_period,
                baseline_period=self.baseline_period,
                filters={},
                group_by=(),
                dimensions={},
                current_value=Decimal("100"),
                baseline_value=Decimal("100"),
                relative_change=Decimal("0"),
                unit="usd",
                sample_size=Decimal("50"),
                source_status="ok",
                status=ObservationStatus.NORMAL,
                query_or_result_reference="ref_naive",
                created_at=naive_dt,
            )

    def test_timezone_normalized_to_utc(self) -> None:
        """Verify non-UTC timezone-aware datetime is normalized to UTC."""
        tz_cst = datetime.timezone(datetime.timedelta(hours=8))
        dt_cst = datetime.datetime(2026, 1, 15, 20, 0, 0, tzinfo=tz_cst)

        obs = Observation(
            observation_id="obs_tz_norm",
            tool_name="query_metric",
            tool_call_id="call_tz",
            metric="sales",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={},
            group_by=(),
            dimensions={},
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0"),
            unit="usd",
            sample_size=Decimal("50"),
            source_status="ok",
            status=ObservationStatus.NORMAL,
            query_or_result_reference="ref_tz",
            created_at=dt_cst,
        )

        self.assertEqual(obs.created_at.tzinfo, datetime.timezone.utc)
        self.assertEqual(obs.created_at.hour, 12)

    def test_empty_or_whitespace_identifiers_rejected(self) -> None:
        """Verify empty or whitespace-only identifier strings raise ObservationValidationError."""
        invalid_fields = [
            ("observation_id", ""),
            ("observation_id", "   "),
            ("tool_name", ""),
            ("tool_call_id", ""),
            ("metric", "  "),
            ("unit", ""),
            ("source_status", ""),
            ("query_or_result_reference", " "),
        ]

        for field_name, bad_value in invalid_fields:
            with self.subTest(field=field_name, value=bad_value):
                kwargs = {
                    "observation_id": "obs_valid",
                    "tool_name": "query_metric",
                    "tool_call_id": "call_valid",
                    "metric": "sales",
                    "current_period": self.current_period,
                    "baseline_period": self.baseline_period,
                    "filters": {},
                    "group_by": (),
                    "dimensions": {},
                    "current_value": Decimal("100"),
                    "baseline_value": Decimal("100"),
                    "relative_change": Decimal("0"),
                    "unit": "usd",
                    "sample_size": Decimal("50"),
                    "source_status": "ok",
                    "status": ObservationStatus.NORMAL,
                    "query_or_result_reference": "ref_valid",
                    "created_at": self.utc_now,
                }
                kwargs[field_name] = bad_value
                with self.assertRaises(ObservationValidationError):
                    Observation(**kwargs)

    def test_unknown_row_status_rejected(self) -> None:
        """Verify unknown MetricQueryRow.status fails fast."""
        row_unknown = MetricQueryRow(
            dimensions={},
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0"),
            status="random_bad_status",
            sample_size=Decimal("50"),
        )
        with self.assertRaises(ObservationValidationError):
            classify_metric_row_status(row_unknown)

    def test_failed_observation_contract(self) -> None:
        """Verify failed_observation produces status=FAILED with error fields and None values."""
        obs = failed_observation(
            tool_name="query_metric",
            tool_call_id="call_fail_001",
            metric="sales",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={"marketplace": "US"},
            group_by=("asin",),
            query_or_result_reference="ref_fail",
            created_at=self.utc_now,
            error_code="DATABASE_TIMEOUT",
            error_message="Query exceeded statement_timeout 1000ms",
        )

        self.assertEqual(obs.observation_id, "call_fail_001_sales_failed")
        self.assertEqual(obs.status, ObservationStatus.FAILED)
        self.assertEqual(obs.source_status, "failed")
        self.assertIsNone(obs.current_value)
        self.assertIsNone(obs.baseline_value)
        self.assertIsNone(obs.relative_change)
        self.assertIsNone(obs.sample_size)
        self.assertEqual(obs.error_code, "DATABASE_TIMEOUT")
        self.assertEqual(obs.error_message, "Query exceeded statement_timeout 1000ms")

    def test_failed_observation_empty_error_rejected(self) -> None:
        """Verify failed_observation with empty error_code or error_message raises ObservationValidationError."""
        with self.assertRaises(ObservationValidationError):
            failed_observation(
                tool_name="query_metric",
                tool_call_id="call_fail_002",
                metric="sales",
                current_period=self.current_period,
                baseline_period=self.baseline_period,
                query_or_result_reference="ref_fail",
                created_at=self.utc_now,
                error_code="",
                error_message="Some error",
            )

        with self.assertRaises(ObservationValidationError):
            failed_observation(
                tool_name="query_metric",
                tool_call_id="call_fail_003",
                metric="sales",
                current_period=self.current_period,
                baseline_period=self.baseline_period,
                query_or_result_reference="ref_fail",
                created_at=self.utc_now,
                error_code="ERR",
                error_message="   ",
            )

    def test_successful_observation_with_error_rejected(self) -> None:
        """Verify non-failed Observation cannot carry error_code or error_message."""
        with self.assertRaises(ObservationValidationError):
            Observation(
                observation_id="obs_err_bad",
                tool_name="query_metric",
                tool_call_id="call_err",
                metric="sales",
                current_period=self.current_period,
                baseline_period=self.baseline_period,
                filters={},
                group_by=(),
                dimensions={},
                current_value=Decimal("100"),
                baseline_value=Decimal("100"),
                relative_change=Decimal("0"),
                unit="usd",
                sample_size=Decimal("50"),
                source_status="ok",
                status=ObservationStatus.NORMAL,
                query_or_result_reference="ref_err",
                created_at=self.utc_now,
                error_code="SHOULD_BE_NONE",
            )

    def test_empty_metric_query_result_returns_empty_tuple(self) -> None:
        """Verify empty MetricQueryResult returns an empty tuple."""
        result = MetricQueryResult(
            metric_id="sales",
            unit="usd",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(),
        )
        obs_tuple = observations_from_metric_query(
            result,
            tool_name="query_metric",
            tool_call_id="call_empty",
            query_or_result_reference="ref_empty",
            created_at=self.utc_now,
        )
        self.assertEqual(obs_tuple, ())

    def test_observations_from_tool_result_dispatcher(self) -> None:
        """Verify observations_from_tool_result correctly dispatches and rejects unsupported types."""
        single_result = MetricQueryResult(
            metric_id="sales",
            unit="usd",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(MetricQueryRow({}, Decimal("100"), Decimal("100"), Decimal("0"), "ok", Decimal("50")),),
        )
        obs_single = observations_from_tool_result(
            single_result,
            tool_name="query_metric",
            tool_call_id="call_disp_1",
            query_or_result_reference="ref_disp_1",
            created_at=self.utc_now,
        )
        self.assertEqual(len(obs_single), 1)

        related_result = RelatedMetricQueryResult(
            source_metric_id="sales",
            results=(single_result,),
        )
        obs_rel = observations_from_tool_result(
            related_result,
            tool_name="query_related_metrics",
            tool_call_id="call_disp_2",
            query_or_result_reference="ref_disp_2",
            created_at=self.utc_now,
        )
        self.assertEqual(len(obs_rel), 1)

        with self.assertRaises(ObservationValidationError):
            observations_from_tool_result(
                "invalid_result_type",  # type: ignore
                tool_name="query_metric",
                tool_call_id="call_disp_3",
                query_or_result_reference="ref_disp_3",
                created_at=self.utc_now,
            )

    def test_failed_observation_direct_construction_with_values_rejected(self) -> None:
        """Verify directly constructing status=FAILED Observation with any non-None numerical value raises ObservationValidationError."""
        base_kwargs = {
            "observation_id": "obs_failed_test",
            "tool_name": "query_metric",
            "tool_call_id": "call_failed_test",
            "metric": "sales",
            "current_period": self.current_period,
            "baseline_period": self.baseline_period,
            "filters": {},
            "group_by": (),
            "dimensions": {},
            "current_value": None,
            "baseline_value": None,
            "relative_change": None,
            "unit": "usd",
            "sample_size": None,
            "source_status": "failed",
            "status": ObservationStatus.FAILED,
            "query_or_result_reference": "ref_failed",
            "created_at": self.utc_now,
            "error_code": "TEST_ERR",
            "error_message": "Test error message",
        }

        fields_with_invalid_values = [
            ("current_value", Decimal("999.00")),
            ("baseline_value", Decimal("1000.00")),
            ("relative_change", Decimal("-0.0010")),
            ("sample_size", Decimal("100")),
        ]

        for field_name, bad_value in fields_with_invalid_values:
            with self.subTest(field=field_name, value=bad_value):
                kwargs = dict(base_kwargs)
                kwargs[field_name] = bad_value
                with self.assertRaises(ObservationValidationError):
                    Observation(**kwargs)

    def test_related_duplicate_metric_ids_remain_unique_and_deterministic(self) -> None:
        """Verify RelatedMetricQueryResult with duplicate metric IDs produces unique and deterministic Observation IDs."""
        sub_orders_1 = MetricQueryResult(
            metric_id="orders",
            unit="count",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(MetricQueryRow({}, Decimal("80"), Decimal("100"), Decimal("-0.2000"), "ok", Decimal("500")),),
        )
        sub_orders_2 = MetricQueryResult(
            metric_id="orders",
            unit="count",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            group_by=(),
            rows=(MetricQueryRow({}, Decimal("90"), Decimal("100"), Decimal("-0.1000"), "ok", Decimal("500")),),
        )

        related_result = RelatedMetricQueryResult(
            source_metric_id="sales",
            results=(sub_orders_1, sub_orders_2),
        )

        obs_tuple_1 = observations_from_related_metric_query(
            related_result,
            tool_name="query_related_metrics",
            tool_call_id="call_dup_001",
            filters=None,
            query_or_result_reference="ref_dup_sales",
            created_at=self.utc_now,
        )

        self.assertEqual(len(obs_tuple_1), 2)
        ids_1 = [o.observation_id for o in obs_tuple_1]
        self.assertEqual(ids_1, ["call_dup_001_rel0_orders_0", "call_dup_001_rel1_orders_0"])
        self.assertEqual(len(set(ids_1)), len(ids_1), "Observation IDs must be unique across all related results")

        # Test deterministic output
        obs_tuple_2 = observations_from_related_metric_query(
            related_result,
            tool_name="query_related_metrics",
            tool_call_id="call_dup_001",
            filters=None,
            query_or_result_reference="ref_dup_sales",
            created_at=self.utc_now,
        )
        ids_2 = [o.observation_id for o in obs_tuple_2]
        self.assertEqual(ids_1, ids_2)


if __name__ == "__main__":
    unittest.main()
