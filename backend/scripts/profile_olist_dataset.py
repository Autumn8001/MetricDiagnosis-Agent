"""Read-only profiler for the Phase 9 Olist real-world validation dataset.

The script intentionally does not import MetricSleuth's synthetic Warehouse,
Metric Registry, Evaluation Ground Truth, or Agent Runtime.  It establishes
what the public data can support before any schema mapping is proposed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "orders": (
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
    ),
    "order_items": ("order_id", "product_id", "seller_id", "price", "freight_value"),
    "customers": ("customer_id", "customer_state"),
    "products": ("product_id", "product_category_name"),
    "sellers": ("seller_id", "seller_state"),
    "payments": ("order_id", "payment_type", "payment_value"),
}

FILE_NAMES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
}


class DatasetProfileError(ValueError):
    """Raised when the local source is not the expected Olist dataset shape."""


def _read_rows(path: Path, required_columns: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise DatasetProfileError(f"Missing required Olist file: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise DatasetProfileError(f"Olist file has no header: {path.name}")
        missing = sorted(set(required_columns) - set(reader.fieldnames))
        if missing:
            raise DatasetProfileError(
                f"Olist file {path.name} is missing required columns: {', '.join(missing)}"
            )
        return list(reader)


def profile_olist_dataset(input_dir: Path) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable source profile.

    ``sales_metric`` deliberately names the available value ``merchandise_gmv``:
    Olist's order-item ``price`` is not a verified equivalent to the existing
    Amazon ``sales`` field, and freight is therefore not silently mixed in.
    """
    datasets = {
        name: _read_rows(input_dir / FILE_NAMES[name], columns)
        for name, columns in REQUIRED_FILES.items()
    }
    orders = datasets["orders"]
    items = datasets["order_items"]
    customers = datasets["customers"]
    products = datasets["products"]
    sellers = datasets["sellers"]
    payments = datasets["payments"]

    order_ids = {row["order_id"] for row in orders}
    customer_ids = {row["customer_id"] for row in customers}
    product_ids = {row["product_id"] for row in products}
    seller_ids = {row["seller_id"] for row in sellers}
    item_order_ids = {row["order_id"] for row in items}
    payment_order_ids = {row["order_id"] for row in payments}

    statuses = Counter(row["order_status"] for row in orders)
    purchase_dates = [
        datetime.fromisoformat(row["order_purchase_timestamp"]).date()
        for row in orders
        if row["order_purchase_timestamp"]
    ]
    if not purchase_dates:
        raise DatasetProfileError("Olist orders contain no purchase timestamps.")

    delivered_orders = [row for row in orders if row["order_status"] == "delivered"]
    delivered_ids = {row["order_id"] for row in delivered_orders}
    delivered_item_rows = [row for row in items if row["order_id"] in delivered_ids]
    try:
        delivered_merchandise_gmv = sum(float(row["price"]) for row in delivered_item_rows)
    except ValueError as exc:
        raise DatasetProfileError("Olist order item price contains a non-numeric value.") from exc

    return {
        "schema": "metricsleuth.phase9_olist_profile.v1",
        "source": {
            "dataset": "Olist Brazilian E-Commerce Public Dataset",
            "input_directory": str(input_dir),
            "raw_files": [FILE_NAMES[name] for name in REQUIRED_FILES],
        },
        "row_counts": {name: len(rows) for name, rows in datasets.items()},
        "time_coverage": {
            "purchase_date_start": min(purchase_dates).isoformat(),
            "purchase_date_end": max(purchase_dates).isoformat(),
            "missing_purchase_timestamp_count": len(orders) - len(purchase_dates),
        },
        "order_quality": {
            "status_counts": dict(sorted(statuses.items())),
            "delivered_order_count": len(delivered_orders),
            "orders_without_customer": sum(row["customer_id"] not in customer_ids for row in orders),
            "order_items_without_order": sum(row["order_id"] not in order_ids for row in items),
            "order_items_without_product": sum(row["product_id"] not in product_ids for row in items),
            "order_items_without_seller": sum(row["seller_id"] not in seller_ids for row in items),
            "orders_without_items": len(order_ids - item_order_ids),
            "payments_without_order": sum(row["order_id"] not in order_ids for row in payments),
            "orders_without_payments": len(order_ids - payment_order_ids),
        },
        "supported_mapping": {
            "metric_candidates": {
                "merchandise_gmv": {
                    "formula": "SUM(order_items.price) for delivered orders",
                    "semantic_note": "Closest Olist candidate for Sales; excludes freight and is not asserted to equal Amazon sales.",
                },
                "orders": {
                    "formula": "COUNT(DISTINCT orders.order_id) for delivered orders",
                    "semantic_note": "Order count is available with an explicit delivered-status filter.",
                },
                "aov": {
                    "formula": "SUM(order_items.price) / COUNT(DISTINCT orders.order_id) for delivered orders",
                    "semantic_note": "Derived only after aggregate numerator and denominator are computed.",
                },
            },
            "dimension_candidates": ["customer_state", "seller_state", "product_category_name", "payment_type"],
            "unsupported_current_metrics": ["sessions", "conversion_rate"],
            "unsupported_current_dimensions": ["marketplace", "traffic_source", "asin"],
            "payment_type_caveat": "An order can have multiple payment rows; do not use payment_type for additive sales without an explicit allocation rule.",
        },
        "delivered_merchandise_gmv": round(delivered_merchandise_gmv, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile a local Olist download without modifying data.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory containing Olist CSV files.")
    parser.add_argument("--output-json", type=Path, help="Optional path for the deterministic JSON profile.")
    args = parser.parse_args(argv)
    try:
        profile = profile_olist_dataset(args.input_dir)
    except DatasetProfileError as exc:
        print(f"Olist profile failed: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
