"""Manual, controlled daily anomaly scan for the Stage 1 Warehouse.

This command is a trigger-discovery surface, not an Agent workflow: it queries
each metric declared by the active semantic layer exactly once at global scope,
records the resulting Observation state, and leaves any later investigation to
the existing Agent Runtime or a human.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analytics.tools import AnalyticsTools  # noqa: E402
from app.metrics.registry import MetricRegistry  # noqa: E402
from app.observations.mapper import observations_from_metric_query  # noqa: E402


class DailyScanError(ValueError):
    """Raised when a controlled manual scan cannot establish a complete snapshot."""


def _observation_payload(observation: object) -> dict[str, Any]:
    return {
        "metric": getattr(observation, "metric"),
        "status": str(getattr(observation, "status")),
        "current_value": float(getattr(observation, "current_value")) if getattr(observation, "current_value") is not None else None,
        "baseline_value": float(getattr(observation, "baseline_value")) if getattr(observation, "baseline_value") is not None else None,
        "relative_change": float(getattr(observation, "relative_change")) if getattr(observation, "relative_change") is not None else None,
        "unit": getattr(observation, "unit"),
        "sample_size": float(getattr(observation, "sample_size")) if getattr(observation, "sample_size") is not None else None,
        "observation_id": getattr(observation, "observation_id"),
    }


def run_daily_scan(
    tools: AnalyticsTools,
    registry: MetricRegistry,
    target_date: datetime.date,
) -> dict[str, Any]:
    """Scan declared metrics once each without choosing investigation actions."""
    created_at = datetime.datetime.now(datetime.timezone.utc)
    observations: list[dict[str, Any]] = []
    for metric_definition in registry.list_metrics():
        metric_id = metric_definition.metric_id
        tool_call_id = f"daily_scan_{target_date.isoformat()}_{metric_id}"
        result = tools.query_metric(metric_id, target_date, target_date, "previous_7_days")
        converted = observations_from_metric_query(
            result,
            tool_name="query_metric",
            tool_call_id=tool_call_id,
            query_or_result_reference=f"daily-scan:{target_date.isoformat()}:{metric_id}",
            created_at=created_at,
        )
        if len(converted) != 1:
            raise DailyScanError(
                f"Global daily scan expected exactly one Observation for {metric_id}, got {len(converted)}."
            )
        observations.append(_observation_payload(converted[0]))
    candidates = [item["metric"] for item in observations if item["status"] == "anomalous"]
    return {
        "schema": "metricsleuth.manual_daily_scan.v1",
        "target_date": target_date.isoformat(),
        "comparison": "previous_7_days",
        "mode": "manual_trigger_discovery",
        "observations": observations,
        "anomaly_candidate_metrics": candidates,
        "next_step": (
            "Human or caller may start the existing Agent investigation for a selected candidate; "
            "this scan does not select a driver, scope, or next query."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a manual MetricSleuth daily anomaly scan.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--target-date", type=datetime.date.fromisoformat, default=datetime.date(2026, 1, 31))
    parser.add_argument("--metrics-config", type=Path, default=REPOSITORY_ROOT / "configs" / "metrics.yaml")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    if not args.database_url or not args.database_url.strip():
        print("Manual daily scan BLOCKED: DATABASE_URL is required.", file=sys.stderr)
        return 2
    try:
        registry = MetricRegistry.from_yaml(args.metrics_config)
        with psycopg.connect(args.database_url) as connection:
            result = run_daily_scan(AnalyticsTools(registry, connection), registry, args.target_date)
    except Exception as exc:
        print(f"Manual daily scan failed: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
