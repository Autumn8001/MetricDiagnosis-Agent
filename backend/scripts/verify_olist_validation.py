"""Verify the isolated Olist real-world metric mapping after a load."""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import psycopg
except ImportError:  # pragma: no cover - environment dependency
    psycopg = None


class OlistValidationError(ValueError):
    """Raised when the isolated Olist schema does not meet its declared contract."""


def verify(database_url: str) -> dict[str, object]:
    if psycopg is None:
        raise OlistValidationError("psycopg is required for database validation.")
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            orders, items = cursor.execute(
                "SELECT (SELECT COUNT(*) FROM olist_validation.olist_orders), "
                "(SELECT COUNT(*) FROM olist_validation.olist_order_items)"
            ).fetchone()
            if orders <= 0 or items <= 0:
                raise OlistValidationError("Olist validation tables must contain orders and order items.")
            delivered_orders, merchandise_gmv, aov = cursor.execute(
                "SELECT COUNT(DISTINCT o.order_id), COALESCE(SUM(i.price), 0), "
                "COALESCE(SUM(i.price) / NULLIF(COUNT(DISTINCT o.order_id), 0), 0) "
                "FROM olist_validation.olist_orders o "
                "JOIN olist_validation.olist_order_items i USING (order_id) "
                "WHERE o.order_status = 'delivered'"
            ).fetchone()
            dimension_counts = cursor.execute(
                "SELECT "
                "COUNT(DISTINCT o.customer_state), "
                "COUNT(DISTINCT i.seller_state), "
                "COUNT(DISTINCT i.product_category_name) "
                "FROM olist_validation.olist_orders o "
                "JOIN olist_validation.olist_order_items i USING (order_id)"
            ).fetchone()
            columns = {
                row[0]
                for row in cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'olist_validation'"
                )
            }
    prohibited = {"sessions", "conversion_rate", "marketplace", "traffic_source", "asin"}
    leaked = sorted(prohibited & columns)
    if leaked:
        raise OlistValidationError(f"Unsupported Amazon/funnel fields leaked into Olist schema: {leaked}")
    if delivered_orders <= 0 or merchandise_gmv <= 0 or aov <= 0:
        raise OlistValidationError("Delivered order, merchandise GMV, and AOV aggregates must be positive.")
    if any(count <= 0 for count in dimension_counts):
        raise OlistValidationError("Customer state, seller state, and product category must all have values.")
    return {
        "schema": "metricsleuth.phase9_olist_mapping_verification.v1",
        "orders": orders,
        "order_items": items,
        "delivered_orders": delivered_orders,
        "delivered_merchandise_gmv": float(merchandise_gmv),
        "delivered_aov": float(aov),
        "dimensions": {
            "customer_state_count": dimension_counts[0],
            "seller_state_count": dimension_counts[1],
            "product_category_count": dimension_counts[2],
        },
        "unsupported_fields_verified_absent": sorted(prohibited),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the isolated Olist real-world mapping.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args(argv)
    if not args.database_url or not args.database_url.strip():
        print("Olist mapping verification BLOCKED: DATABASE_URL is required.", file=sys.stderr)
        return 2
    try:
        print(json.dumps(verify(args.database_url), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except OlistValidationError as exc:
        print(f"Olist mapping verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
