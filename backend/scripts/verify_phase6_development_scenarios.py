"""Development-only three-scenario harness for Phase 6.

This script deliberately lives outside ``backend/app``. It runs one scenario-
independent probe matrix, builds an actual investigation record, and only then
loads ground truth for scoring. It is a benchmark oracle, not an Agent workflow.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

import psycopg

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analytics.models import MetricQueryResult, RelatedMetricQueryResult
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricRegistry


CURRENT_DATE = datetime.date(2026, 1, 31)
SCENARIOS = ("canonical", "traffic", "no_anomaly")
MATERIAL_DECLINE = Decimal("-0.10")
STABLE_CHANGE = Decimal("0.05")
MIN_CONTRIBUTION = Decimal("0.50")


@dataclass(frozen=True)
class DevelopmentScenarioRecord:
    scenario: str
    target_metric: str
    status: str
    primary_driver: str | None
    affected_scope: Mapping[str, str]
    stable_metrics: tuple[str, ...]
    negative_controls: Mapping[str, tuple[str, ...]]
    observed_relative_changes: Mapping[str, str | None]

    def to_json(self) -> dict:
        payload = asdict(self)
        payload["affected_scope"] = dict(self.affected_scope)
        payload["negative_controls"] = {
            key: list(values) for key, values in self.negative_controls.items()
        }
        payload["stable_metrics"] = list(self.stable_metrics)
        return payload


def _one_row_by_metric(result: RelatedMetricQueryResult) -> dict:
    rows = {}
    for metric_result in result.results:
        if len(metric_result.rows) != 1:
            raise AssertionError(
                f"Expected exactly one global row for {metric_result.metric_id}, "
                f"got {len(metric_result.rows)}."
            )
        rows[metric_result.metric_id] = metric_result.rows[0]
    required = {"orders", "sessions", "conversion_rate", "aov"}
    if set(rows) != required:
        raise AssertionError(f"Related metric set mismatch: expected {required}, got {set(rows)}.")
    return rows


def infer_global_outcome(
    sales: MetricQueryResult,
    related: RelatedMetricQueryResult,
) -> tuple[str, str | None, tuple[str, ...], dict[str, str | None]]:
    """Infer the data-level scenario signature without accessing benchmark labels."""
    if len(sales.rows) != 1:
        raise AssertionError(f"Expected one global Sales row, got {len(sales.rows)}.")
    sales_row = sales.rows[0]
    related_rows = _one_row_by_metric(related)
    all_rows = {"sales": sales_row, **related_rows}
    changes = {
        metric: None if row.relative_change is None else str(row.relative_change)
        for metric, row in all_rows.items()
    }
    if any(row.status != "ok" or row.relative_change is None for row in all_rows.values()):
        raise AssertionError("All development scenario global metrics must be comparable and status=ok.")

    stable = tuple(
        metric for metric in ("sales", "orders", "sessions", "conversion_rate", "aov")
        if abs(all_rows[metric].relative_change) < STABLE_CHANGE
    )
    if len(stable) == 5:
        return "no_material_anomaly", None, stable, changes
    if sales_row.relative_change > MATERIAL_DECLINE:
        raise AssertionError(
            f"Non-normal scenario must have material Sales decline, got {sales_row.relative_change}."
        )
    if (
        related_rows["conversion_rate"].relative_change <= MATERIAL_DECLINE
        and abs(related_rows["sessions"].relative_change) < STABLE_CHANGE
        and abs(related_rows["aov"].relative_change) < STABLE_CHANGE
    ):
        return "diagnosed", "conversion_rate", stable, changes
    if (
        related_rows["sessions"].relative_change <= MATERIAL_DECLINE
        and abs(related_rows["conversion_rate"].relative_change) < STABLE_CHANGE
        and abs(related_rows["aov"].relative_change) < STABLE_CHANGE
    ):
        return "diagnosed", "sessions", stable, changes
    raise AssertionError("Development scenario does not match a supported data-level driver signature.")


def _metric_rows(result: RelatedMetricQueryResult, metric: str, dimension: str) -> dict:
    metric_result = next((item for item in result.results if item.metric_id == metric), None)
    if metric_result is None:
        raise AssertionError(f"Missing metric '{metric}' in related result.")
    values = {}
    for row in metric_result.rows:
        value = row.dimensions.get(dimension)
        if not isinstance(value, str) or not value:
            raise AssertionError(f"Missing dimension '{dimension}' in {metric} row.")
        if value in values:
            raise AssertionError(f"Duplicate dimension member '{value}' for '{dimension}'.")
        values[value] = row
    if not values:
        raise AssertionError(f"No members returned for dimension '{dimension}'.")
    return values


def choose_primary_segment(
    result: RelatedMetricQueryResult,
    *,
    driver: str,
    dimension: str,
) -> tuple[str, tuple[str, ...]]:
    """Choose the largest positive driver-specific shortfall and its controls."""
    sessions = _metric_rows(result, "sessions", dimension)
    orders = _metric_rows(result, "orders", dimension)
    conversion = _metric_rows(result, "conversion_rate", dimension)
    if set(sessions) != set(orders) or set(sessions) != set(conversion):
        raise AssertionError(f"Dimension member sets disagree for '{dimension}'.")

    shortfalls: dict[str, Decimal] = {}
    for value in sessions:
        session_row = sessions[value]
        if driver == "sessions":
            if session_row.current_value is None or session_row.baseline_value is None:
                raise AssertionError(f"Missing sessions values for '{value}'.")
            shortfall = session_row.baseline_value - session_row.current_value
        elif driver == "conversion_rate":
            order_row = orders[value]
            cr_row = conversion[value]
            if (
                session_row.current_value is None
                or order_row.current_value is None
                or cr_row.baseline_value is None
            ):
                raise AssertionError(f"Missing conversion shortfall values for '{value}'.")
            shortfall = session_row.current_value * cr_row.baseline_value - order_row.current_value
        else:
            raise ValueError(f"Unsupported development driver: '{driver}'.")
        shortfalls[value] = max(shortfall, Decimal("0"))

    total = sum(shortfalls.values(), Decimal("0"))
    if total <= 0:
        raise AssertionError(f"No positive {driver} shortfall found for '{dimension}'.")
    primary = max(shortfalls, key=shortfalls.__getitem__)
    contribution = shortfalls[primary] / total
    if contribution < MIN_CONTRIBUTION:
        raise AssertionError(
            f"Primary {dimension} contribution must be >= 50%, got {contribution}."
        )
    controls = tuple(sorted(set(shortfalls) - {primary}))
    return primary, controls


def build_actual_record(tools: AnalyticsTools, scenario: str) -> DevelopmentScenarioRecord:
    """Run the same fixed benchmark probes for every scenario, without labels."""
    common = dict(
        start_date=CURRENT_DATE,
        end_date=CURRENT_DATE,
        compare_to="previous_7_days",
    )
    sales = tools.query_metric(metric="sales", **common)
    global_related = tools.query_related_metrics(metric="sales", **common)
    marketplace = tools.query_related_metrics(metric="sales", group_by=["marketplace"], **common)
    asin = tools.query_related_metrics(
        metric="sales", filters={"marketplace": "US"}, group_by=["asin"], **common
    )
    traffic = tools.query_related_metrics(
        metric="sales",
        filters={"marketplace": "US", "asin": "ASIN-A"},
        group_by=["traffic_source"],
        **common,
    )

    status, driver, stable, changes = infer_global_outcome(sales, global_related)
    if status == "no_material_anomaly":
        affected_scope: dict[str, str] = {}
        controls = {
            "marketplaces": tuple(sorted(_metric_rows(marketplace, "sessions", "marketplace"))),
            "asins": tuple(sorted(_metric_rows(asin, "sessions", "asin"))),
            "traffic_sources": tuple(sorted(_metric_rows(traffic, "sessions", "traffic_source"))),
        }
    else:
        assert driver is not None
        primary_marketplace, market_controls = choose_primary_segment(
            marketplace, driver=driver, dimension="marketplace"
        )
        primary_asin, asin_controls = choose_primary_segment(asin, driver=driver, dimension="asin")
        primary_traffic, traffic_controls = choose_primary_segment(
            traffic, driver=driver, dimension="traffic_source"
        )
        affected_scope = {
            "marketplace": primary_marketplace,
            "asin": primary_asin,
            "traffic_source": primary_traffic,
        }
        controls = {
            "marketplaces": market_controls,
            "asins": asin_controls,
            "traffic_sources": traffic_controls,
        }

    return DevelopmentScenarioRecord(
        scenario=scenario,
        target_metric="sales",
        status=status,
        primary_driver=driver,
        affected_scope=affected_scope,
        stable_metrics=stable,
        negative_controls=controls,
        observed_relative_changes=changes,
    )


def score_record(record: DevelopmentScenarioRecord, expected: Mapping) -> None:
    """Compare an already-created record with test-only ground truth."""
    comparisons = {
        "scenario": record.scenario,
        "target_metric": record.target_metric,
        "status": record.status,
        "primary_driver": record.primary_driver,
        "affected_scope": dict(record.affected_scope),
    }
    for field, actual in comparisons.items():
        if actual != expected[field]:
            raise AssertionError(
                f"Scenario '{record.scenario}' mismatch for {field}: "
                f"expected {expected[field]!r}, got {actual!r}."
            )
    if set(record.stable_metrics) != set(expected["expected_stable_metrics"]):
        raise AssertionError(
            f"Scenario '{record.scenario}' stable metric mismatch: "
            f"expected {expected['expected_stable_metrics']}, got {record.stable_metrics}."
        )
    for dimension, expected_values in expected["negative_controls"].items():
        actual_values = record.negative_controls.get(dimension)
        if set(actual_values or ()) != set(expected_values):
            raise AssertionError(
                f"Scenario '{record.scenario}' negative controls mismatch for {dimension}: "
                f"expected {expected_values}, got {actual_values}."
            )


def _inject_scenario(scenario: str, database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "warehouse" / "anomaly_injector.py"), "--scenario", scenario],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Scenario injector failed for '{scenario}' with exit {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )


def run_harness(database_url: str, restore_scenario: str = "canonical") -> list[dict]:
    config = REPOSITORY_ROOT / "configs" / "metrics.yaml"
    labels_path = REPOSITORY_ROOT / "warehouse" / "ground_truth.json"
    registry = MetricRegistry.from_yaml(config)
    actual_records: list[DevelopmentScenarioRecord] = []
    try:
        for scenario in SCENARIOS:
            _inject_scenario(scenario, database_url)
            with psycopg.connect(database_url) as connection:
                tools = AnalyticsTools(registry=registry, connection=connection)
                actual_records.append(build_actual_record(tools, scenario))

        # Ground truth is deliberately loaded only after all actual records exist.
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        labels_by_scenario = {item["scenario"]: item for item in labels}
        if set(labels_by_scenario) != set(SCENARIOS):
            raise AssertionError("Ground truth scenario set does not exactly match the development set.")
        for record in actual_records:
            score_record(record, labels_by_scenario[record.scenario])
        return [record.to_json() for record in actual_records]
    finally:
        _inject_scenario(restore_scenario, database_url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify all Phase 6 development data scenarios.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--restore-scenario", choices=SCENARIOS, default="canonical")
    args = parser.parse_args()
    if not args.database_url:
        print("Development Scenario Harness: BLOCKED (DATABASE_URL missing)")
        return 2
    try:
        report = run_harness(args.database_url, restore_scenario=args.restore_scenario)
    except Exception as exc:
        print(f"Development Scenario Harness: FAIL — {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "scenarios": report}, indent=2, ensure_ascii=False))
    print("Development Scenario Harness: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
