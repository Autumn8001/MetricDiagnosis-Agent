"""Tests for the read-only Phase 9 Olist source profiler."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "profile_olist_dataset.py"
SPEC = importlib.util.spec_from_file_location("profile_olist_dataset", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
olist_profiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = olist_profiler
SPEC.loader.exec_module(olist_profiler)


class TestOlistSourceProfile(unittest.TestCase):
    def _write(self, root: Path, name: str, contents: str) -> None:
        (root / name).write_text(contents, encoding="utf-8")

    def test_profile_reports_supported_and_unsupported_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "olist_orders_dataset.csv", "order_id,customer_id,order_status,order_purchase_timestamp\no1,c1,delivered,2017-01-01 10:00:00\n")
            self._write(root, "olist_order_items_dataset.csv", "order_id,product_id,seller_id,price,freight_value\no1,p1,s1,12.50,2.00\n")
            self._write(root, "olist_customers_dataset.csv", "customer_id,customer_state\nc1,SP\n")
            self._write(root, "olist_products_dataset.csv", "product_id,product_category_name\np1,toys\n")
            self._write(root, "olist_sellers_dataset.csv", "seller_id,seller_state\ns1,RJ\n")
            self._write(root, "olist_order_payments_dataset.csv", "order_id,payment_type,payment_value\no1,credit_card,12.50\n")

            profile = olist_profiler.profile_olist_dataset(root)

        self.assertEqual(profile["delivered_merchandise_gmv"], 12.5)
        self.assertEqual(profile["order_quality"]["order_items_without_order"], 0)
        self.assertEqual(profile["supported_mapping"]["unsupported_current_metrics"], ["sessions", "conversion_rate"])
        self.assertEqual(profile["supported_mapping"]["unsupported_current_dimensions"], ["marketplace", "traffic_source", "asin"])

    def test_profile_fails_closed_when_required_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(olist_profiler.DatasetProfileError):
                olist_profiler.profile_olist_dataset(Path(directory))


if __name__ == "__main__":
    unittest.main()
