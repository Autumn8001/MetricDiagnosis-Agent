"""Exercise existing AnalyticsTools against the isolated Olist validation registry."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import psycopg


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analytics.tools import AnalyticsTools  # noqa: E402
from app.data_sources import build_olist_validation_capabilities  # noqa: E402
from app.metrics.registry import MetricRegistry  # noqa: E402


CONFIG_PATH = REPOSITORY_ROOT / "configs" / "olist_validation_metrics.yaml"


class OlistToolCompatibilityError(ValueError):
    """Raised when the existing controlled tool cannot query the real-data adapter."""


def _row_payload(row: object) -> dict[str, object]:
    return {
        "dimensions": dict(getattr(row, "dimensions")),
        "current_value": float(getattr(row, "current_value")) if getattr(row, "current_value") is not None else None,
        "baseline_value": float(getattr(row, "baseline_value")) if getattr(row, "baseline_value") is not None else None,
        "relative_change": float(getattr(row, "relative_change")) if getattr(row, "relative_change") is not None else None,
        "status": getattr(row, "status"),
        "sample_size": float(getattr(row, "sample_size")) if getattr(row, "sample_size") is not None else None,
    }


def verify(database_url: str, target_date: datetime.date) -> dict[str, object]:
    registry = MetricRegistry.from_yaml(CONFIG_PATH)
    if registry.sample_size_field != "orders":
        raise OlistToolCompatibilityError("Olist registry must use real order count as its sample-size field.")
    if registry.dimensions != ("customer_state",):
        raise OlistToolCompatibilityError("Olist registry must expose only order-safe customer_state slicing.")
    capabilities = build_olist_validation_capabilities(registry)

    with psycopg.connect(database_url) as connection:
        tools = AnalyticsTools(
            registry=registry,
            connection=connection,
            capabilities=capabilities,
        )
        gmv = tools.query_metric("merchandise_gmv", target_date, target_date, "previous_7_days")
        aov = tools.query_metric("olist_aov", target_date, target_date, "previous_7_days")
        by_state = tools.query_metric("merchandise_gmv", target_date, target_date, "previous_7_days", group_by=["customer_state"])
        related = tools.query_related_metrics("merchandise_gmv", target_date, target_date, "previous_7_days")

    if len(gmv.rows) != 1 or len(aov.rows) != 1 or not by_state.rows:
        raise OlistToolCompatibilityError("Expected overall GMV/AOV rows and at least one customer-state row.")
    if gmv.rows[0].status != "ok" or aov.rows[0].status != "ok":
        raise OlistToolCompatibilityError("Overall Olist GMV and AOV must have sufficient real order sample size.")
    if tuple(result.metric_id for result in related.results) != ("orders", "olist_aov"):
        raise OlistToolCompatibilityError("Related Olist metrics must follow the temporary semantic declaration.")
    return {
        "schema": "metricsleuth.phase9_olist_tool_compatibility.v1",
        "target_date": target_date.isoformat(),
        "registry": {"table": registry.table, "time_dimension": registry.time_dimension, "sample_size_field": registry.sample_size_field, "dimensions": list(registry.dimensions)},
        "overall": {"merchandise_gmv": _row_payload(gmv.rows[0]), "olist_aov": _row_payload(aov.rows[0])},
        "customer_state_row_count": len(by_state.rows),
        "related_metric_order": [result.metric_id for result in related.results],
        "unavailable_by_contract": ["sessions", "conversion_rate", "marketplace", "traffic_source", "asin"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify existing AnalyticsTools with the Olist validation registry.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--target-date", type=datetime.date.fromisoformat, default=datetime.date(2017, 3, 20))
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    if not args.database_url or not args.database_url.strip():
        print("Olist tool compatibility BLOCKED: DATABASE_URL is required.", file=sys.stderr)
        return 2
    try:
        result = verify(args.database_url, args.target_date)
    except Exception as exc:
        print(f"Olist tool compatibility failed: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
