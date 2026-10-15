"""Offline preparation only: no model, database connection, or environment file.

The output is evaluator-owned and contains Ground Truth. Never pass the whole
document to an agent; only task_input belongs in a product task request.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation import load_ground_truth_cases
from app.sandbox.dataset_writer import _checksum, build_sandbox_rows

SCENARIOS = ("canonical", "traffic", "no_anomaly")
TARGET = date(2026, 1, 31)
BASELINE_START, BASELINE_END = date(2026, 1, 24), date(2026, 1, 30)
DIMENSIONS = {"asin": 1, "marketplace": 2, "traffic_source": 3}
CONTROL_DIMENSIONS = {"marketplaces": "marketplace", "asins": "asin", "traffic_sources": "traffic_source"}


def relative_change(rows, metric, filters):
    """Independent in-memory fixture audit, not a replacement for SQL tools."""
    selected = [r for r in rows if all(r[DIMENSIONS[k]] == v for k, v in filters.items())]

    def value(period, days):
        totals = {name: sum((Decimal(str(r[index])) for r in period), Decimal(0))
                  for name, index in (("sessions", 6), ("orders", 7), ("sales", 8))}
        if metric == "conversion_rate":
            return totals["orders"] / totals["sessions"]
        if metric == "aov":
            return totals["sales"] / totals["orders"]
        return totals[metric] / days

    current = value([r for r in selected if r[0] == TARGET], 1)
    baseline = value([r for r in selected if BASELINE_START <= r[0] <= BASELINE_END], 7)
    return (current - baseline) / baseline


def audit_fixture(rows, case):
    """Fail preparation if independent numbers contradict the fixed case truth."""
    checks = []

    def check(label, metric, scope, anomalous):
        change = relative_change(rows, metric, scope)
        passed = change <= Decimal("-0.10") if anomalous else abs(change) < Decimal("0.05")
        checks.append({"check": label, "metric": metric, "scope": dict(scope),
                       "relative_change": str(change), "passed": passed})

    check("target", case.target_metric, {}, case.primary_driver is not None)
    if case.primary_driver:
        check("joint_driver_scope", case.primary_driver, case.affected_scope, True)
    for metric in case.expected_stable_metrics:
        check("stable_metric", metric, {}, False)
    for plural, values in case.negative_controls.items():
        for dimension_value in values:
            scope = {CONTROL_DIMENSIONS[plural]: dimension_value}
            for metric in dict.fromkeys((case.target_metric, case.primary_driver or case.target_metric)):
                check("negative_control", metric, scope, False)
    if not all(c["passed"] for c in checks):
        raise ValueError("fixture_expectations_disagree")
    return checks


def prepare():
    cases = {c.scenario: c for c in load_ground_truth_cases(ROOT / "warehouse/benchmark_cases.json")}
    paths = [ROOT / "configs/metrics.yaml", ROOT / "warehouse/benchmark_cases.json",
             ROOT / "warehouse/seed.py", ROOT / "warehouse/anomaly_injector.py",
             ROOT / "backend/app/sandbox/dataset_writer.py",
             ROOT / "backend/app/task_application.py",
             ROOT / "backend/app/persistence/task_execution_service.py",
             Path(__file__).resolve()]
    for directory in ("agent_runtime", "analytics", "metrics", "observations", "evidence", "diagnosis", "evaluation"):
        paths.extend((ROOT / "backend/app" / directory).rglob("*.py"))
    fingerprints = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(set(paths))}
    prepared = []
    for scenario in SCENARIOS:
        case, rows = cases[scenario], build_sandbox_rows(scenario)
        prepared.append({
            "case_id": case.case_id, "scenario": scenario,
            "data_version": "sandbox-" + _checksum(rows), "row_count": len(rows),
            "task_input": {"target_metric": "sales", "target_date": TARGET.isoformat(),
                           "filters": {}, "group_by": []},
            "evaluator_only": {"status": case.status.value, "primary_driver": case.primary_driver,
                               "affected_scope": dict(case.affected_scope)},
            "fixture_checks": audit_fixture(rows, case),
        })
    return {"plan_id": "sandbox-development-v1", "execution": "not_executed",
            "dataset_kind": "synthetic_development_not_holdout", "model_id": None,
            "proposed_repetitions_per_case": 2, "authorized_model_calls": 0,
            "max_tool_calls_per_run": 8, "max_turns_per_run": 10,
            "source_sha256": fingerprints, "cases": prepared}


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, sort_keys=True, indent=2))
