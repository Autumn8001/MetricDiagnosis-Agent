"""Deterministic anomaly injector for MetricSleuth Phase 1 Synthetic Benchmark Dataset."""

import argparse
import datetime
import os
import random
import sys

try:
    import psycopg
except ImportError:
    print("Error: psycopg is required. Install with `pip install 'psycopg[binary]>=3.2,<4'`", file=sys.stderr)
    sys.exit(1)

CURRENT_DATE = datetime.date(2026, 1, 31)
EXPECTED_SEGMENT_COUNT = 18

# Normal baseline segment parameters matching seed.py
SEGMENT_CONFIGS = {
    # US Marketplace
    ("US", "ASIN-A", "Ads"): (10000, 600, 500, 0.08, 80.0, 300.0, 50.0),
    ("US", "ASIN-A", "Organic"): (5000, 300, 250, 0.08, 80.0, 0.0, 25.0),
    ("US", "ASIN-B", "Ads"): (5000, 300, 250, 0.08, 80.0, 150.0, 25.0),
    ("US", "ASIN-B", "Organic"): (3000, 180, 150, 0.08, 80.0, 0.0, 15.0),
    ("US", "ASIN-C", "Ads"): (4000, 240, 200, 0.08, 80.0, 120.0, 20.0),
    ("US", "ASIN-C", "Organic"): (3000, 180, 150, 0.08, 80.0, 0.0, 15.0),
    # UK Marketplace
    ("UK", "ASIN-A", "Ads"): (4000, 240, 200, 0.08, 80.0, 120.0, 20.0),
    ("UK", "ASIN-A", "Organic"): (2000, 120, 100, 0.08, 80.0, 0.0, 10.0),
    ("UK", "ASIN-B", "Ads"): (2000, 120, 100, 0.08, 80.0, 60.0, 10.0),
    ("UK", "ASIN-B", "Organic"): (2000, 120, 100, 0.08, 80.0, 0.0, 10.0),
    ("UK", "ASIN-C", "Ads"): (2000, 120, 100, 0.08, 80.0, 60.0, 10.0),
    ("UK", "ASIN-C", "Organic"): (2000, 120, 100, 0.08, 80.0, 0.0, 10.0),
    # DE Marketplace
    ("DE", "ASIN-A", "Ads"): (3000, 180, 150, 0.08, 80.0, 90.0, 15.0),
    ("DE", "ASIN-A", "Organic"): (2000, 120, 100, 0.08, 80.0, 0.0, 10.0),
    ("DE", "ASIN-B", "Ads"): (2000, 120, 100, 0.08, 80.0, 60.0, 10.0),
    ("DE", "ASIN-B", "Organic"): (2000, 120, 100, 0.08, 80.0, 0.0, 10.0),
    ("DE", "ASIN-C", "Ads"): (2000, 120, 100, 0.08, 80.0, 60.0, 10.0),
    ("DE", "ASIN-C", "Organic"): (2000, 120, 100, 0.08, 80.0, 0.0, 10.0),
}


def get_database_url(cli_arg=None):
    if cli_arg:
        return cli_arg
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    print("Error: DATABASE_URL not specified. Set DATABASE_URL env var or pass --database-url.", file=sys.stderr)
    sys.exit(1)


def generate_current_normal_records():
    """Generates the clean, uncorrupted normal state for CURRENT_DATE (2026-01-31)."""
    rng = random.Random(20260131)
    for _ in range(30):
        for _ in SEGMENT_CONFIGS:
            _ = rng.uniform(-0.01, 0.01)

    records = []
    for (mkt, asin, src), (base_imp, base_clk, base_sess, cr, price, base_spend, base_ref) in SEGMENT_CONFIGS.items():
        delta = rng.uniform(-0.01, 0.01)
        sessions = int(round(base_sess * (1.0 + delta)))
        clicks = int(round(base_clk * (1.0 + delta)))
        impressions = int(round(base_imp * (1.0 + delta)))
        clicks = min(clicks, impressions)
        orders = int(round(sessions * cr))
        orders = min(orders, sessions)
        sales = round(orders * price, 2)
        ad_spend = round(base_spend * (1.0 + delta), 2) if base_spend > 0 else 0.0
        refunds = round(base_ref * (1.0 + delta), 2)

        records.append({
            "date": CURRENT_DATE,
            "asin": asin,
            "marketplace": mkt,
            "traffic_source": src,
            "impressions": impressions,
            "clicks": clicks,
            "sessions": sessions,
            "orders": orders,
            "sales": sales,
            "ad_spend": ad_spend,
            "refunds": refunds,
        })
    return records


SUPPORTED_SCENARIOS = (
    "canonical",
    "traffic",
    "no_anomaly",
    "aov_us_asin_b_organic",
    "traffic_uk_asin_b_ads",
    "conversion_de_asin_c_ads",
    "traffic_us_asin_c_organic",
    "aov_uk_asin_a_ads",
    "conversion_us_asin_b_ads",
    "distractor_minor_fluctuation",
)

SCENARIO_TARGET_SEGMENTS = {
    "canonical": ("US", "ASIN-A", "Ads"),
    "traffic": ("US", "ASIN-A", "Ads"),
    "no_anomaly": None,
    "aov_us_asin_b_organic": ("US", "ASIN-B", "Organic"),
    "traffic_uk_asin_b_ads": ("UK", "ASIN-B", "Ads"),
    "conversion_de_asin_c_ads": ("DE", "ASIN-C", "Ads"),
    "traffic_us_asin_c_organic": ("US", "ASIN-C", "Organic"),
    "aov_uk_asin_a_ads": ("UK", "ASIN-A", "Ads"),
    "conversion_us_asin_b_ads": ("US", "ASIN-B", "Ads"),
    "distractor_minor_fluctuation": ("DE", "ASIN-C", "Organic"),
}


def apply_scenario(records, scenario):
    """Applies target scenario mutation on CURRENT_DATE records."""
    if scenario not in SUPPORTED_SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")

    if scenario == "no_anomaly":
        return records

    for r in records:
        key = (r["marketplace"], r["asin"], r["traffic_source"])
        if scenario == "canonical":
            if key == ("US", "ASIN-A", "Ads"):
                r["orders"] = 10
                r["sales"] = round(10 * 80.0, 2)
        elif scenario == "traffic":
            if key == ("US", "ASIN-A", "Ads"):
                r["impressions"] = int(round(r["impressions"] * 0.25))
                r["clicks"] = int(round(r["clicks"] * 0.25))
                r["sessions"] = int(round(r["sessions"] * 0.25))
                r["orders"] = int(round(r["sessions"] * 0.08))
                r["sales"] = round(r["orders"] * 80.0, 2)
        elif scenario == "aov_us_asin_b_organic":
            if key == ("US", "ASIN-B", "Organic"):
                # Price/AOV drops 40% (80.0 -> 48.0)
                r["sales"] = round(r["orders"] * 48.0, 2)
        elif scenario == "traffic_uk_asin_b_ads":
            if key == ("UK", "ASIN-B", "Ads"):
                # Traffic drops 60%
                r["impressions"] = int(round(r["impressions"] * 0.40))
                r["clicks"] = int(round(r["clicks"] * 0.40))
                r["sessions"] = int(round(r["sessions"] * 0.40))
                r["orders"] = int(round(r["sessions"] * 0.08))
                r["sales"] = round(r["orders"] * 80.0, 2)
        elif scenario == "conversion_de_asin_c_ads":
            if key == ("DE", "ASIN-C", "Ads"):
                # Orders halved (CR drops 50%)
                r["orders"] = int(round(r["orders"] * 0.50))
                r["sales"] = round(r["orders"] * 80.0, 2)
        elif scenario == "traffic_us_asin_c_organic":
            if key == ("US", "ASIN-C", "Organic"):
                # Traffic drops 50%
                r["impressions"] = int(round(r["impressions"] * 0.50))
                r["clicks"] = int(round(r["clicks"] * 0.50))
                r["sessions"] = int(round(r["sessions"] * 0.50))
                r["orders"] = int(round(r["sessions"] * 0.08))
                r["sales"] = round(r["orders"] * 80.0, 2)
        elif scenario == "aov_uk_asin_a_ads":
            if key == ("UK", "ASIN-A", "Ads"):
                # Price drops 35% (80.0 -> 52.0)
                r["sales"] = round(r["orders"] * 52.0, 2)
        elif scenario == "conversion_us_asin_b_ads":
            if key == ("US", "ASIN-B", "Ads"):
                # Orders halved (CR drops 50%)
                r["orders"] = int(round(r["orders"] * 0.50))
                r["sales"] = round(r["orders"] * 80.0, 2)
        elif scenario == "distractor_minor_fluctuation":
            if key == ("DE", "ASIN-C", "Organic"):
                # Minor fluctuation: -2 orders in small segment (<2.5% global sales impact)
                r["orders"] = max(1, r["orders"] - 2)
                r["sales"] = round(r["orders"] * 80.0, 2)

    return records


def print_summary(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                SUM(sales) / 7.0 AS baseline_sales,
                SUM(orders) / 7.0 AS baseline_orders,
                SUM(sessions) / 7.0 AS baseline_sessions,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS baseline_cr,
                SUM(sales)::numeric / NULLIF(SUM(orders), 0) AS baseline_aov
            FROM warehouse.fact_daily_performance
            WHERE date >= '2026-01-24' AND date <= '2026-01-30'
            """
        )
        base = cur.fetchone()

        cur.execute(
            """
            SELECT
                SUM(sales) AS current_sales,
                SUM(orders) AS current_orders,
                SUM(sessions) AS current_sessions,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS current_cr,
                SUM(sales)::numeric / NULLIF(SUM(orders), 0) AS current_aov
            FROM warehouse.fact_daily_performance
            WHERE date = '2026-01-31'
            """
        )
        curr = cur.fetchone()

    base_sales, base_orders, base_sessions, base_cr, base_aov = [float(x) for x in base]
    curr_sales, curr_orders, curr_sessions, curr_cr, curr_aov = [float(x) for x in curr]

    def rel_chg(c, b):
        return (c - b) / b if b != 0 else 0.0

    print("\n--- Current Period (2026-01-31) vs Baseline (7-Day Avg) Summary ---")
    print(f"Sales:           Current=${curr_sales:,.2f}  | Baseline=${base_sales:,.2f}  | RelChange={rel_chg(curr_sales, base_sales):+.2%}")
    print(f"Orders:          Current={curr_orders:,.0f}       | Baseline={base_orders:,.1f}       | RelChange={rel_chg(curr_orders, base_orders):+.2%}")
    print(f"Sessions:        Current={curr_sessions:,.0f}     | Baseline={base_sessions:,.1f}     | RelChange={rel_chg(curr_sessions, base_sessions):+.2%}")
    print(f"Conversion Rate: Current={curr_cr:.2%}      | Baseline={base_cr:.2%}      | RelChange={rel_chg(curr_cr, base_cr):+.2%}")
    print(f"AOV:             Current=${curr_aov:.2f}     | Baseline=${base_aov:.2f}     | RelChange={rel_chg(curr_aov, base_aov):+.2%}")
    print("-------------------------------------------------------------------\n")


def main():
    parser = argparse.ArgumentParser(description="MetricSleuth anomaly injector")
    parser.add_argument(
        "--scenario",
        "-s",
        required=True,
        choices=list(SUPPORTED_SCENARIOS),
        help="Scenario to inject",
    )
    parser.add_argument("--database-url", "-d", type=str, help="PostgreSQL connection string")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and validate records in memory without connecting to database",
    )
    args = parser.parse_args()

    if args.dry_run:
        records = generate_current_normal_records()
        mutated = apply_scenario(records, args.scenario)
        curr_sales = sum(r["sales"] for r in mutated)
        curr_orders = sum(r["orders"] for r in mutated)
        curr_sessions = sum(r["sessions"] for r in mutated)
        curr_cr = (curr_orders / curr_sessions) if curr_sessions else 0.0
        curr_aov = (curr_sales / curr_orders) if curr_orders else 0.0
        print(f"Dry-run scenario '{args.scenario}' applied cleanly to CURRENT_DATE ({CURRENT_DATE}): {len(mutated)} records generated.")
        print(f"Current Date Stats: Sales=${curr_sales:,.2f}, Orders={curr_orders}, Sessions={curr_sessions}, CR={curr_cr:.2%}, AOV=${curr_aov:.2f}")
        return

    db_url = get_database_url(args.database_url)

    try:
        conn = psycopg.connect(db_url, autocommit=True)

        # 1. Validate data presence and row count on CURRENT_DATE
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM warehouse.fact_daily_performance WHERE date = %s", (CURRENT_DATE,))
            existing_count = cur.fetchone()[0]

            if existing_count != EXPECTED_SEGMENT_COUNT:
                raise RuntimeError(
                    f"Integrity check failed: Expected exactly {EXPECTED_SEGMENT_COUNT} segment rows for CURRENT_DATE ({CURRENT_DATE}), "
                    f"but found {existing_count}. Ensure database has been seeded with `python warehouse/seed.py --reset`."
                )

            target_key = SCENARIO_TARGET_SEGMENTS.get(args.scenario)
            if target_key is not None:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM warehouse.fact_daily_performance
                    WHERE date = %s AND marketplace = %s AND asin = %s AND traffic_source = %s
                    """,
                    (CURRENT_DATE, target_key[0], target_key[1], target_key[2]),
                )
                target_count = cur.fetchone()[0]
                if target_count != 1:
                    raise RuntimeError(f"Target segment {target_key} not found for CURRENT_DATE ({CURRENT_DATE}).")

        # 2. Generate and apply scenario
        records = generate_current_normal_records()
        records = apply_scenario(records, args.scenario)

        # 3. Update records inside transaction and verify rowcount
        total_updated = 0
        with conn.transaction():
            with conn.cursor() as cur:
                for r in records:
                    cur.execute(
                        """
                        UPDATE warehouse.fact_daily_performance
                        SET impressions = %s,
                            clicks = %s,
                            sessions = %s,
                            orders = %s,
                            sales = %s,
                            ad_spend = %s,
                            refunds = %s
                        WHERE date = %s AND asin = %s AND marketplace = %s AND traffic_source = %s
                        """,
                        (
                            r["impressions"],
                            r["clicks"],
                            r["sessions"],
                            r["orders"],
                            r["sales"],
                            r["ad_spend"],
                            r["refunds"],
                            r["date"],
                            r["asin"],
                            r["marketplace"],
                            r["traffic_source"],
                        ),
                    )
                    if cur.rowcount != 1:
                        raise RuntimeError(
                            f"Failed to update segment ({r['marketplace']}, {r['asin']}, {r['traffic_source']}) on date {r['date']}: rowcount={cur.rowcount}"
                        )
                    total_updated += cur.rowcount

        if total_updated != EXPECTED_SEGMENT_COUNT:
            raise RuntimeError(f"Expected {EXPECTED_SEGMENT_COUNT} rows updated, but updated {total_updated} rows.")

        print(f"Scenario '{args.scenario}' applied cleanly to CURRENT_DATE ({CURRENT_DATE}): {total_updated} segments updated.")
        print_summary(conn)
        conn.close()
    except Exception as e:
        print(f"Failed to inject anomaly scenario: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
