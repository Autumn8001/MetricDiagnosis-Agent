-- MetricSleuth Phase 1: Warehouse Schema
-- Idempotent schema definition for Synthetic Benchmark Dataset

CREATE SCHEMA IF NOT EXISTS warehouse;

CREATE TABLE IF NOT EXISTS warehouse.dim_products (
    asin TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse.fact_daily_performance (
    date DATE NOT NULL,
    asin TEXT NOT NULL REFERENCES warehouse.dim_products(asin),
    marketplace TEXT NOT NULL,
    traffic_source TEXT NOT NULL,
    impressions INTEGER NOT NULL CHECK (impressions >= 0),
    clicks INTEGER NOT NULL CHECK (clicks >= 0 AND clicks <= impressions),
    sessions INTEGER NOT NULL CHECK (sessions >= 0),
    orders INTEGER NOT NULL CHECK (orders >= 0 AND orders <= sessions),
    sales NUMERIC(12, 2) NOT NULL CHECK (sales >= 0),
    ad_spend NUMERIC(12, 2) NOT NULL CHECK (ad_spend >= 0),
    refunds NUMERIC(12, 2) NOT NULL CHECK (refunds >= 0),
    PRIMARY KEY (date, asin, marketplace, traffic_source)
);
