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
from app.monitoring import run_manual_daily_scan  # noqa: E402


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
            result = run_manual_daily_scan(AnalyticsTools(registry, connection), registry, args.target_date)
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
