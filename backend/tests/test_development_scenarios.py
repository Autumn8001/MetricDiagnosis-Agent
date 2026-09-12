"""Hermetic tests for the development-only Phase 6 scenario harness."""

import datetime
from decimal import Decimal
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from verify_phase6_development_scenarios import (
    DevelopmentScenarioRecord,
    choose_primary_segment,
    infer_global_outcome,
    score_record,
)
from app.analytics.models import DateRange, MetricQueryResult, MetricQueryRow, RelatedMetricQueryResult


PERIOD = DateRange(datetime.date(2026, 1, 31), datetime.date(2026, 1, 31))
BASELINE = DateRange(datetime.date(2026, 1, 24), datetime.date(2026, 1, 30))


def query(metric, change, current=Decimal("100"), baseline=Decimal("100"), dimensions=None):
    return MetricQueryResult(
        metric_id=metric,
        unit="count",
        current_period=PERIOD,
        baseline_period=BASELINE,
        group_by=tuple((dimensions or {}).keys()),
        rows=(MetricQueryRow(dimensions or {}, current, baseline, change, "ok", Decimal("100")),),
    )


class TestDevelopmentScenarios(unittest.TestCase):
    def test_global_signature_classifies_conversion_sessions_and_normal(self) -> None:
        cases = [
            (Decimal("-0.13"), Decimal("0"), Decimal("-0.13"), ("diagnosed", "conversion_rate")),
            (Decimal("-0.13"), Decimal("-0.13"), Decimal("0"), ("diagnosed", "sessions")),
            (Decimal("0.01"), Decimal("0.01"), Decimal("0.01"), ("no_material_anomaly", None)),
        ]
        for sales_change, session_change, cr_change, expected in cases:
            with self.subTest(expected=expected):
                related = RelatedMetricQueryResult("sales", (
                    query("orders", sales_change),
                    query("sessions", session_change),
                    query("conversion_rate", cr_change),
                    query("aov", Decimal("0")),
                ))
                status, driver, _, _ = infer_global_outcome(query("sales", sales_change), related)
                self.assertEqual((status, driver), expected)

    def test_choose_primary_segment_uses_driver_specific_shortfall(self) -> None:
        def grouped(metric, rows):
            return MetricQueryResult(metric, "count", PERIOD, BASELINE, ("marketplace",), tuple(rows))
        sessions = grouped("sessions", [
            MetricQueryRow({"marketplace": "US"}, Decimal("25"), Decimal("100"), Decimal("-0.75"), "ok", Decimal("100")),
            MetricQueryRow({"marketplace": "UK"}, Decimal("99"), Decimal("100"), Decimal("-0.01"), "ok", Decimal("100")),
        ])
        orders = grouped("orders", [
            MetricQueryRow({"marketplace": "US"}, Decimal("2"), Decimal("8"), Decimal("-0.75"), "ok", Decimal("100")),
            MetricQueryRow({"marketplace": "UK"}, Decimal("8"), Decimal("8"), Decimal("0"), "ok", Decimal("100")),
        ])
        cr = grouped("conversion_rate", [
            MetricQueryRow({"marketplace": "US"}, Decimal("0.08"), Decimal("0.08"), Decimal("0"), "ok", Decimal("100")),
            MetricQueryRow({"marketplace": "UK"}, Decimal("0.08"), Decimal("0.08"), Decimal("0"), "ok", Decimal("100")),
        ])
        result = RelatedMetricQueryResult("sales", (orders, sessions, cr))
        primary, controls = choose_primary_segment(result, driver="sessions", dimension="marketplace")
        self.assertEqual(primary, "US")
        self.assertEqual(controls, ("UK",))

    def test_score_requires_exact_scope_stable_metrics_and_controls(self) -> None:
        record = DevelopmentScenarioRecord(
            scenario="canonical",
            target_metric="sales",
            status="diagnosed",
            primary_driver="conversion_rate",
            affected_scope={"marketplace": "US"},
            stable_metrics=("sessions", "aov"),
            negative_controls={"marketplaces": ("DE", "UK")},
            observed_relative_changes={},
        )
        expected = {
            "scenario": "canonical", "target_metric": "sales", "status": "diagnosed",
            "primary_driver": "conversion_rate", "affected_scope": {"marketplace": "US"},
            "expected_stable_metrics": ["aov", "sessions"],
            "negative_controls": {"marketplaces": ["UK", "DE"]},
        }
        score_record(record, expected)
        expected["negative_controls"] = {"marketplaces": ["UK"]}
        with self.assertRaises(AssertionError):
            score_record(record, expected)

    def test_production_runtime_has_no_ground_truth_reference(self) -> None:
        app_root = Path(__file__).resolve().parent.parent / "app" / "agent_runtime"
        forbidden = "ground" + "_truth"
        offenders = [path for path in app_root.rglob("*.py") if forbidden in path.read_text(encoding="utf-8").lower()]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
