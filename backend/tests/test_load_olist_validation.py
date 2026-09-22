"""Pure-source tests for the isolated Olist staging loader."""

from __future__ import annotations

import datetime
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "load_olist_validation.py"
SPEC = importlib.util.spec_from_file_location("load_olist_validation", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
olist_loader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = olist_loader
SPEC.loader.exec_module(olist_loader)


class TestOlistValidationRows(unittest.TestCase):
    def test_build_rows_preserves_real_source_fields_without_amazon_proxies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = {
                "olist_orders_dataset.csv": "order_id,customer_id,order_status,order_purchase_timestamp\no1,c1,delivered,2017-01-01 10:00:00\n",
                "olist_order_items_dataset.csv": "order_id,order_item_id,product_id,seller_id,price,freight_value\no1,1,p1,s1,12.50,2.00\n",
                "olist_customers_dataset.csv": "customer_id,customer_state\nc1,SP\n",
                "olist_products_dataset.csv": "product_id,product_category_name\np1,toys\n",
                "olist_sellers_dataset.csv": "seller_id,seller_state\ns1,RJ\n",
            }
            for name, contents in fixtures.items():
                (root / name).write_text(contents, encoding="utf-8")

            orders, items = olist_loader.build_validation_rows(root)

        self.assertEqual(orders, [("o1", "c1", datetime.date(2017, 1, 1), "delivered", "SP")])
        self.assertEqual(items, [("o1", 1, "p1", "s1", "toys", "RJ", 12.5, 2.0)])


if __name__ == "__main__":
    unittest.main()
