-- Phase 9 real-world validation schema.
-- This schema is intentionally isolated from ``warehouse`` synthetic Benchmark
-- tables and is not read by the current Agent Runtime.

CREATE SCHEMA IF NOT EXISTS olist_validation;

CREATE TABLE IF NOT EXISTS olist_validation.olist_orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    purchase_date DATE NOT NULL,
    order_status TEXT NOT NULL,
    customer_state TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS olist_validation.olist_order_items (
    order_id TEXT NOT NULL REFERENCES olist_validation.olist_orders(order_id),
    order_item_id INTEGER NOT NULL CHECK (order_item_id > 0),
    product_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    product_category_name TEXT,
    seller_state TEXT NOT NULL,
    price NUMERIC(14, 2) NOT NULL CHECK (price >= 0),
    freight_value NUMERIC(14, 2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE INDEX IF NOT EXISTS idx_olist_orders_purchase_status
    ON olist_validation.olist_orders (purchase_date, order_status);
CREATE INDEX IF NOT EXISTS idx_olist_items_category
    ON olist_validation.olist_order_items (product_category_name);
CREATE INDEX IF NOT EXISTS idx_olist_items_seller_state
    ON olist_validation.olist_order_items (seller_state);
