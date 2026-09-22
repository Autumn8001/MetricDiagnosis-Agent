"""Tests for manual Trigger discovery without Agent workflow decisions."""

from __future__ import annotations

import datetime
import importlib.util
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "run_daily_scan.py"
SPEC = importlib.util.spec_from_file_location("run_daily_scan", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
daily_scan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = daily_scan
SPEC.loader.exec_module(daily_scan)

from app.analytics.models import DateRange, MetricQueryResult, MetricQueryRow
from app.metrics.registry import MetricDefinition


def result(metric: str, change: str) -> MetricQueryResult:
    return MetricQueryResult(
        metric_id=metric,
        unit="count",
        current_period=DateRange(datetime.date(2026, 1, 31), datetime.date(2026, 1, 31)),
        baseline_period=DateRange(datetime.date(2026, 1, 24), datetime.date(2026, 1, 30)),
        group_by=(),
        rows=(MetricQueryRow({}, Decimal("100"), Decimal("120"), Decimal(change), "ok", Decimal("50")),),
    )


class TestManualDailyScan(unittest.TestCase):
    def test_scan_reports_candidates_without_driver_or_scope_decision(self) -> None:
        registry = MagicMock()
        registry.list_metrics.return_value = [
            MetricDefinition("sales", "Sales", "Sales", "additive", "usd", "SUM(sales)", ("sales",), ("marketplace",), (), (), ()),
            MetricDefinition("sessions", "Sessions", "Sessions", "additive", "count", "SUM(sessions)", ("sessions",), ("marketplace",), (), (), ()),
        ]
        tools = MagicMock()
        tools.query_metric.side_effect = [result("sales", "-0.12"), result("sessions", "0.01")]

        payload = daily_scan.run_daily_scan(tools, registry, datetime.date(2026, 1, 31))

        self.assertEqual(payload["mode"], "manual_trigger_discovery")
        self.assertEqual(payload["anomaly_candidate_metrics"], ["sales"])
        self.assertEqual([item["status"] for item in payload["observations"]], ["anomalous", "normal"])
        self.assertNotIn("primary_driver", payload)
        self.assertNotIn("affected_scope", payload)
        self.assertEqual(tools.query_metric.call_count, 2)


if __name__ == "__main__":
    unittest.main()
