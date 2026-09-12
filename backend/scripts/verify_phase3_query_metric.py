"""Verification script for Phase 3 query_metric against PostgreSQL Warehouse."""

import datetime
from decimal import Decimal
import os
from pathlib import Path
import sys

import psycopg

# Ensure backend root is in sys.path
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricRegistry


def run_verification() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required.", file=sys.stderr)
        print("Example: export DATABASE_URL='postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'", file=sys.stderr)
        sys.exit(1)

    yaml_path = backend_root.parent / "configs" / "metrics.yaml"
    if not yaml_path.exists():
        print(f"ERROR: Metrics configuration not found at {yaml_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading MetricRegistry from {yaml_path} ...")
    registry = MetricRegistry.from_yaml(yaml_path)

    test_date = datetime.date(2026, 1, 31)

    print(f"Connecting to database via DATABASE_URL ...")
    with psycopg.connect(database_url) as conn:
        tools = AnalyticsTools(registry=registry, connection=conn)

        print("\n--- 1. Verifying Global Metrics for Canonical Case (2026-01-31) ---")
        # Global Sales
        res_sales = tools.query_metric(
            metric="sales",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
        )
        assert len(res_sales.rows) == 1, "Expected exactly 1 global sales row"
        row_sales = res_sales.rows[0]
        print(f"Sales: curr={row_sales.current_value}, base={row_sales.baseline_value}, rel_change={row_sales.relative_change:.4f}, status={row_sales.status}")
        assert row_sales.status == "ok", f"Expected status 'ok', got {row_sales.status}"
        assert row_sales.relative_change is not None and row_sales.relative_change <= Decimal("-0.10"), (
            f"Sales drop assertion failed: {row_sales.relative_change}"
        )

        # Global Orders
        res_orders = tools.query_metric(
            metric="orders",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
        )
        assert len(res_orders.rows) == 1
        row_orders = res_orders.rows[0]
        print(f"Orders: curr={row_orders.current_value}, base={row_orders.baseline_value}, rel_change={row_orders.relative_change:.4f}, status={row_orders.status}")
        assert row_orders.status == "ok"
        assert row_orders.relative_change is not None and row_orders.relative_change <= Decimal("-0.10"), (
            f"Orders drop assertion failed: {row_orders.relative_change}"
        )

        # Global Sessions
        res_sessions = tools.query_metric(
            metric="sessions",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
        )
        assert len(res_sessions.rows) == 1
        row_sessions = res_sessions.rows[0]
        print(f"Sessions: curr={row_sessions.current_value}, base={row_sessions.baseline_value}, rel_change={row_sessions.relative_change:.4f}, status={row_sessions.status}")
        assert row_sessions.status == "ok"
        assert row_sessions.relative_change is not None and abs(row_sessions.relative_change) < Decimal("0.05"), (
            f"Sessions stability assertion failed: {row_sessions.relative_change}"
        )

        # Global Conversion Rate
        res_cr = tools.query_metric(
            metric="conversion_rate",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
        )
        assert len(res_cr.rows) == 1
        row_cr = res_cr.rows[0]
        print(f"Conversion Rate: curr={row_cr.current_value:.4f}, base={row_cr.baseline_value:.4f}, rel_change={row_cr.relative_change:.4f}, status={row_cr.status}")
        assert row_cr.status == "ok"
        assert row_cr.relative_change is not None and row_cr.relative_change <= Decimal("-0.10"), (
            f"Conversion Rate drop assertion failed: {row_cr.relative_change}"
        )

        # Global AOV
        res_aov = tools.query_metric(
            metric="aov",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
        )
        assert len(res_aov.rows) == 1
        row_aov = res_aov.rows[0]
        print(f"AOV: curr={row_aov.current_value:.4f}, base={row_aov.baseline_value:.4f}, rel_change={row_aov.relative_change:.4f}, status={row_aov.status}")
        assert row_aov.status == "ok"
        assert row_aov.relative_change is not None and abs(row_aov.relative_change) < Decimal("0.05"), (
            f"AOV stability assertion failed: {row_aov.relative_change}"
        )

        print("\n--- 2. Verifying group_by=['marketplace'] on Conversion Rate ---")
        res_mkt = tools.query_metric(
            metric="conversion_rate",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
            group_by=["marketplace"],
        )
        mkt_map = {r.dimensions["marketplace"]: r for r in res_mkt.rows}
        print(f"Found marketplaces: {list(mkt_map.keys())}")
        assert set(mkt_map.keys()) == {"DE", "UK", "US"}, f"Expected DE, UK, US, got {set(mkt_map.keys())}"

        # US should drop materially
        us_cr = mkt_map["US"]
        print(f"  US: curr={us_cr.current_value:.4f}, base={us_cr.baseline_value:.4f}, rel_change={us_cr.relative_change:.4f}, status={us_cr.status}")
        assert us_cr.status == "ok"
        assert us_cr.relative_change is not None and us_cr.relative_change <= Decimal("-0.10"), "US CR drop assertion failed"

        # UK and DE should be stable negative controls
        for m in ("UK", "DE"):
            row = mkt_map[m]
            print(f"  {m}: curr={row.current_value:.4f}, base={row.baseline_value:.4f}, rel_change={row.relative_change:.4f}, status={row.status}")
            assert row.status == "ok"
            assert row.relative_change is not None and abs(row.relative_change) < Decimal("0.05"), f"{m} stability failed"

        print("\n--- 3. Verifying filters={'marketplace': 'US'}, group_by=['asin'] on Conversion Rate ---")
        res_asin = tools.query_metric(
            metric="conversion_rate",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
            filters={"marketplace": "US"},
            group_by=["asin"],
        )
        asin_map = {r.dimensions["asin"]: r for r in res_asin.rows}
        print(f"Found ASINs: {list(asin_map.keys())}")
        assert set(asin_map.keys()) == {"ASIN-A", "ASIN-B", "ASIN-C"}

        # ASIN-A should drop materially
        row_a = asin_map["ASIN-A"]
        print(f"  ASIN-A: curr={row_a.current_value:.4f}, base={row_a.baseline_value:.4f}, rel_change={row_a.relative_change:.4f}, status={row_a.status}")
        assert row_a.status == "ok"
        assert row_a.relative_change is not None and row_a.relative_change <= Decimal("-0.10"), "ASIN-A CR drop assertion failed"

        # ASIN-B and ASIN-C should be stable negative controls
        for asin in ("ASIN-B", "ASIN-C"):
            row = asin_map[asin]
            print(f"  {asin}: curr={row.current_value:.4f}, base={row.baseline_value:.4f}, rel_change={row.relative_change:.4f}, status={row.status}")
            assert row.status == "ok"
            assert row.relative_change is not None and abs(row.relative_change) < Decimal("0.05"), f"{asin} stability failed"

    print("\nPhase 3 AnalyticsTools query_metric Verification: ALL PASS!")


if __name__ == "__main__":
    run_verification()
