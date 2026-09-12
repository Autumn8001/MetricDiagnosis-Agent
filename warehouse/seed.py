"""Deterministic seed generator for MetricSleuth Phase 1 Synthetic Benchmark Dataset."""

import argparse
import datetime
import os
import random
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:
    print("Error: psycopg is required. Install with `pip install 'psycopg[binary]>=3.2,<4'`", file=sys.stderr)
    sys.exit(1)

# Fixed date constants
START_DATE = datetime.date(2026, 1, 1)
END_DATE = datetime.date(2026, 1, 31)
BASELINE_START_DATE = datetime.date(2026, 1, 24)
BASELINE_END_DATE = datetime.date(2026, 1, 30)
CURRENT_DATE = datetime.date(2026, 1, 31)

# Dim products definition
PRODUCTS = [
    ("ASIN-A", "Wireless Noise-Canceling Headphones", "Electronics"),
    ("ASIN-B", "Ergonomic Office Mouse", "Electronics"),
    ("ASIN-C", "USB-C Fast Charging Hub", "Accessories"),
]

# Segment base configurations (deterministic baseline per day)
# (marketplace, asin, traffic_source): (base_impressions, base_clicks, base_sessions, base_cr, unit_price, ad_spend_base, refund_base)
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


def generate_normal_records():
    """Generates deterministic daily performance records from START_DATE to END_DATE."""
    rng = random.Random(20260131)
    records = []

    curr = START_DATE
    while curr <= END_DATE:
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

            records.append((
                curr,
                asin,
                mkt,
                src,
                impressions,
                clicks,
                sessions,
                orders,
                sales,
                ad_spend,
                refunds,
            ))
        curr += datetime.timedelta(days=1)
    return records


def get_database_url(cli_arg=None):
    if cli_arg:
        return cli_arg
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    print("Error: DATABASE_URL not specified. Set DATABASE_URL env var or pass --database-url.", file=sys.stderr)
    sys.exit(1)


def ensure_schema(conn):
    schema_file = Path(__file__).resolve().parent / "schema.sql"
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_file}")
    sql = schema_file.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def main():
    parser = argparse.ArgumentParser(description="MetricSleuth synthetic data seed generator")
    parser.add_argument("--reset", action="store_true", help="Reset existing warehouse benchmark data")
    parser.add_argument("--database-url", "-d", type=str, help="PostgreSQL connection string")
    args = parser.parse_args()

    db_url = get_database_url(args.database_url)

    try:
        conn = psycopg.connect(db_url, autocommit=True)
        ensure_schema(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM warehouse.fact_daily_performance")
            count = cur.fetchone()[0]

            if count > 0 and not args.reset:
                print(
                    f"Database already contains {count} records in warehouse.fact_daily_performance. "
                    "Run with --reset to overwrite.",
                    file=sys.stderr,
                )
                conn.close()
                sys.exit(1)

        with conn.transaction():
            with conn.cursor() as cur:
                if args.reset:
                    cur.execute("DELETE FROM warehouse.fact_daily_performance")
                    cur.execute("DELETE FROM warehouse.dim_products")

                # Insert dim_products
                for asin, name, cat in PRODUCTS:
                    cur.execute(
                        """
                        INSERT INTO warehouse.dim_products (asin, product_name, category)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (asin) DO UPDATE SET product_name = EXCLUDED.product_name, category = EXCLUDED.category
                        """,
                        (asin, name, cat),
                    )

                # Insert normal fact records
                records = generate_normal_records()
                cur.executemany(
                    """
                    INSERT INTO warehouse.fact_daily_performance (
                        date, asin, marketplace, traffic_source, impressions, clicks, sessions, orders, sales, ad_spend, refunds
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date, asin, marketplace, traffic_source) DO UPDATE SET
                        impressions = EXCLUDED.impressions,
                        clicks = EXCLUDED.clicks,
                        sessions = EXCLUDED.sessions,
                        orders = EXCLUDED.orders,
                        sales = EXCLUDED.sales,
                        ad_spend = EXCLUDED.ad_spend,
                        refunds = EXCLUDED.refunds
                    """,
                    records,
                )

        conn.close()
        print(f"Seed completed successfully: {len(records)} records inserted ({START_DATE} to {END_DATE}).")
    except Exception as e:
        print(f"Failed to seed database: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
