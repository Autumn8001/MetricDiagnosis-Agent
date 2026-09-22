"""Load a local Olist download into the isolated Phase 9 validation schema.

This is a data-validation adapter, not a production ingestion service.  It
does not touch ``warehouse`` synthetic data, metric YAML, Ground Truth, or the
Agent Runtime. Database replacement requires an explicit flag.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import os
import sys
from pathlib import Path
from typing import Iterable

try:
    import psycopg
except ImportError:  # pragma: no cover - environment dependency
    psycopg = None


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "warehouse" / "olist_validation_schema.sql"

REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "orders": ("order_id", "customer_id", "order_status", "order_purchase_timestamp"),
    "order_items": ("order_id", "order_item_id", "product_id", "seller_id", "price", "freight_value"),
    "customers": ("customer_id", "customer_state"),
    "products": ("product_id", "product_category_name"),
    "sellers": ("seller_id", "seller_state"),
}
FILE_NAMES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
}


class OlistLoadError(ValueError):
    """Raised when the source cannot safely be loaded into the validation schema."""


def _read_rows(path: Path, required_columns: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise OlistLoadError(f"Missing required Olist file: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise OlistLoadError(f"Olist file has no header: {path.name}")
        missing = sorted(set(required_columns) - set(reader.fieldnames))
        if missing:
            raise OlistLoadError(f"{path.name} is missing columns: {', '.join(missing)}")
        return list(reader)


def build_validation_rows(input_dir: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """Join raw Olist CSVs into order and item rows without writing any data."""
    source = {
        name: _read_rows(input_dir / FILE_NAMES[name], required)
        for name, required in REQUIRED_FILES.items()
    }
    customers = {row["customer_id"]: row["customer_state"] for row in source["customers"]}
    categories = {row["product_id"]: row["product_category_name"] or None for row in source["products"]}
    seller_states = {row["seller_id"]: row["seller_state"] for row in source["sellers"]}

    orders: dict[str, tuple[object, ...]] = {}
    for row in source["orders"]:
        customer_state = customers.get(row["customer_id"])
        if not customer_state:
            raise OlistLoadError(f"Order {row['order_id']} has no customer-state mapping.")
        try:
            purchase_date = datetime.datetime.fromisoformat(row["order_purchase_timestamp"]).date()
        except ValueError as exc:
            raise OlistLoadError(f"Order {row['order_id']} has invalid purchase timestamp.") from exc
        order_id = row["order_id"]
        if order_id in orders:
            raise OlistLoadError(f"Duplicate order ID in Olist orders file: {order_id}")
        orders[order_id] = (order_id, row["customer_id"], purchase_date, row["order_status"], customer_state)

    items: list[tuple[object, ...]] = []
    seen_item_keys: set[tuple[str, int]] = set()
    for row in source["order_items"]:
        order_id = row["order_id"]
        if order_id not in orders:
            raise OlistLoadError(f"Order item references unknown order: {order_id}")
        seller_state = seller_states.get(row["seller_id"])
        if not seller_state:
            raise OlistLoadError(f"Order item references seller without state: {row['seller_id']}")
        try:
            item_id = int(row["order_item_id"])
            price = float(row["price"])
            freight = float(row["freight_value"])
        except ValueError as exc:
            raise OlistLoadError(f"Order item for {order_id} has invalid numeric values.") from exc
        if item_id <= 0 or price < 0 or freight < 0:
            raise OlistLoadError(f"Order item for {order_id} violates non-negative quantity/value rules.")
        item_key = (order_id, item_id)
        if item_key in seen_item_keys:
            raise OlistLoadError(f"Duplicate Olist order-item identity: {item_key}")
        seen_item_keys.add(item_key)
        items.append((order_id, item_id, row["product_id"], row["seller_id"], categories.get(row["product_id"]), seller_state, price, freight))

    return list(orders.values()), items


def _copy_rows(cursor: object, statement: str, rows: Iterable[tuple[object, ...]]) -> None:
    with cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def load_validation_schema(input_dir: Path, database_url: str, replace: bool) -> tuple[int, int]:
    """Create isolated schema then load rows; replacement is explicit and scoped."""
    if psycopg is None:
        raise OlistLoadError("psycopg is required for database loading.")
    orders, items = build_validation_rows(input_dir)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(schema_sql)
                existing = cursor.execute("SELECT COUNT(*) FROM olist_validation.olist_orders").fetchone()[0]
                if existing and not replace:
                    raise OlistLoadError(
                        "olist_validation already contains data; rerun with --replace to truncate only validation tables."
                    )
                if existing:
                    cursor.execute("TRUNCATE olist_validation.olist_order_items, olist_validation.olist_orders")
                _copy_rows(cursor, "COPY olist_validation.olist_orders (order_id, customer_id, purchase_date, order_status, customer_state) FROM STDIN", orders)
                _copy_rows(cursor, "COPY olist_validation.olist_order_items (order_id, order_item_id, product_id, seller_id, product_category_name, seller_state, price, freight_value) FROM STDIN", items)
    return len(orders), len(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Olist into the isolated real-world validation schema.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--replace", action="store_true", help="Explicitly truncate only olist_validation tables before loading.")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate joins without a database write.")
    args = parser.parse_args(argv)
    try:
        orders, items = build_validation_rows(args.input_dir)
        if args.dry_run:
            print(f"Olist validation dry-run PASS: {len(orders)} orders, {len(items)} order items.")
            return 0
        if not args.database_url or not args.database_url.strip():
            raise OlistLoadError("DATABASE_URL is required unless --dry-run is selected.")
        order_count, item_count = load_validation_schema(args.input_dir, args.database_url, args.replace)
        print(f"Olist validation load PASS: {order_count} orders, {item_count} order items.")
        return 0
    except OlistLoadError as exc:
        print(f"Olist validation load failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
