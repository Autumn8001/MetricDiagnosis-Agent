-- MetricSleuth Phase 1: Canonical Case Manual SQL Verification
-- Full implementation of Phase 0 Manual Investigation Contract:
-- 1. Baseline (7 days) & Current (1 day) presence and completeness checks
-- 2. Explicit NULL checks for all aggregations and metrics
-- 3. Global metric assertions:
--    - Sales material decline (<= -10%)
--    - Orders material decline (<= -10%)
--    - Sessions stable (abs(rel_change) < 5%)
--    - Conversion Rate material decline (<= -10%)
--    - AOV stable (abs(rel_change) < 5%)
-- 4. Marketplace assertions:
--    - US Baseline Sessions >= 30
--    - US own CR material decline (<= -10%)
--    - US is the primary positive shortfall contributor (share >= 50% and max shortfall)
--    - Negative controls: Non-US marketplaces (UK, DE) CR stable / no material decline
-- 5. ASIN assertions (in US):
--    - ASIN-A Baseline Sessions >= 30
--    - ASIN-A own CR material decline (<= -10%)
--    - ASIN-A is the primary positive shortfall contributor in US (share >= 50% and max shortfall)
--    - Negative controls: Non-target ASINs (ASIN-B, ASIN-C) in US CR stable / no material decline
-- 6. Traffic Source assertions (in US + ASIN-A):
--    - Ads Baseline Sessions >= 30
--    - Ads own CR material decline (<= -10%)
--    - Ads is the primary positive shortfall contributor in US+ASIN-A (share >= 50% and max shortfall)
--    - Negative controls: Organic traffic in US+ASIN-A CR stable / no material decline

DO $$
DECLARE
    -- Record count checks
    v_baseline_days_count INT;
    v_current_rows_count INT;

    -- Global metrics
    v_base_sales NUMERIC;
    v_curr_sales NUMERIC;
    v_sales_rel_change NUMERIC;

    v_base_orders NUMERIC;
    v_curr_orders NUMERIC;
    v_orders_rel_change NUMERIC;

    v_base_sessions NUMERIC;
    v_curr_sessions NUMERIC;
    v_sessions_rel_change NUMERIC;

    v_base_cr NUMERIC;
    v_curr_cr NUMERIC;
    v_cr_rel_change NUMERIC;

    v_base_aov NUMERIC;
    v_curr_aov NUMERIC;
    v_aov_rel_change NUMERIC;

    -- Marketplace metrics
    v_us_shortfall NUMERIC;
    v_us_share NUMERIC;
    v_us_base_sessions NUMERIC;
    v_us_cr_rel_change NUMERIC;
    v_uk_cr_rel_change NUMERIC;
    v_de_cr_rel_change NUMERIC;
    v_uk_shortfall NUMERIC;
    v_de_shortfall NUMERIC;
    v_total_mkt_shortfall NUMERIC;

    -- ASIN metrics (in US)
    v_asin_a_shortfall NUMERIC;
    v_asin_a_share NUMERIC;
    v_asin_a_base_sessions NUMERIC;
    v_asin_a_cr_rel_change NUMERIC;
    v_asin_b_cr_rel_change NUMERIC;
    v_asin_c_cr_rel_change NUMERIC;
    v_asin_b_shortfall NUMERIC;
    v_asin_c_shortfall NUMERIC;
    v_total_asin_shortfall NUMERIC;

    -- Traffic Source metrics (in US + ASIN-A)
    v_ads_shortfall NUMERIC;
    v_ads_share NUMERIC;
    v_ads_base_sessions NUMERIC;
    v_ads_cr_rel_change NUMERIC;
    v_org_cr_rel_change NUMERIC;
    v_org_shortfall NUMERIC;
    v_total_src_shortfall NUMERIC;
BEGIN
    RAISE NOTICE '=======================================================';
    RAISE NOTICE 'MetricSleuth Canonical Case Manual SQL Verification';
    RAISE NOTICE '=======================================================';

    -- 0. Check data presence and completeness
    SELECT COUNT(DISTINCT date) INTO v_baseline_days_count
    FROM warehouse.fact_daily_performance
    WHERE date >= '2026-01-24' AND date <= '2026-01-30';

    IF v_baseline_days_count IS NULL OR v_baseline_days_count != 7 THEN
        RAISE EXCEPTION 'FAIL: Baseline period (2026-01-24 to 2026-01-30) requires exactly 7 days, but found % days', COALESCE(v_baseline_days_count, 0);
    END IF;

    SELECT COUNT(*) INTO v_current_rows_count
    FROM warehouse.fact_daily_performance
    WHERE date = '2026-01-31';

    IF v_current_rows_count IS NULL OR v_current_rows_count != 18 THEN
        RAISE EXCEPTION 'FAIL: Current period (2026-01-31) requires exactly 18 segment rows, but found % rows', COALESCE(v_current_rows_count, 0);
    END IF;

    -- 1. Global Metrics Calculation
    SELECT
        SUM(sales) / 7.0,
        SUM(orders) / 7.0,
        SUM(sessions) / 7.0,
        SUM(orders)::numeric / NULLIF(SUM(sessions), 0),
        SUM(sales)::numeric / NULLIF(SUM(orders), 0)
    INTO
        v_base_sales,
        v_base_orders,
        v_base_sessions,
        v_base_cr,
        v_base_aov
    FROM warehouse.fact_daily_performance
    WHERE date >= '2026-01-24' AND date <= '2026-01-30';

    SELECT
        SUM(sales),
        SUM(orders),
        SUM(sessions),
        SUM(orders)::numeric / NULLIF(SUM(sessions), 0),
        SUM(sales)::numeric / NULLIF(SUM(orders), 0)
    INTO
        v_curr_sales,
        v_curr_orders,
        v_curr_sessions,
        v_curr_cr,
        v_curr_aov
    FROM warehouse.fact_daily_performance
    WHERE date = '2026-01-31';

    -- Explicit NULL guards
    IF v_base_sales IS NULL OR v_curr_sales IS NULL OR v_base_sales = 0 THEN
        RAISE EXCEPTION 'FAIL: Global Sales calculation returned NULL or zero baseline (base=%, curr=%)', v_base_sales, v_curr_sales;
    END IF;
    IF v_base_orders IS NULL OR v_curr_orders IS NULL OR v_base_orders = 0 THEN
        RAISE EXCEPTION 'FAIL: Global Orders calculation returned NULL or zero baseline (base=%, curr=%)', v_base_orders, v_curr_orders;
    END IF;
    IF v_base_sessions IS NULL OR v_curr_sessions IS NULL OR v_base_sessions = 0 THEN
        RAISE EXCEPTION 'FAIL: Global Sessions calculation returned NULL or zero baseline (base=%, curr=%)', v_base_sessions, v_curr_sessions;
    END IF;
    IF v_base_cr IS NULL OR v_curr_cr IS NULL OR v_base_cr = 0 THEN
        RAISE EXCEPTION 'FAIL: Global Conversion Rate calculation returned NULL or zero baseline (base=%, curr=%)', v_base_cr, v_curr_cr;
    END IF;
    IF v_base_aov IS NULL OR v_curr_aov IS NULL OR v_base_aov = 0 THEN
        RAISE EXCEPTION 'FAIL: Global AOV calculation returned NULL or zero baseline (base=%, curr=%)', v_base_aov, v_curr_aov;
    END IF;

    v_sales_rel_change := (v_curr_sales - v_base_sales) / v_base_sales;
    v_orders_rel_change := (v_curr_orders - v_base_orders) / v_base_orders;
    v_sessions_rel_change := (v_curr_sessions - v_base_sessions) / v_base_sessions;
    v_cr_rel_change := (v_curr_cr - v_base_cr) / v_base_cr;
    v_aov_rel_change := (v_curr_aov - v_base_aov) / v_base_aov;

    RAISE NOTICE 'Global Sales:           Base=$% | Curr=$% | RelChg=%', ROUND(v_base_sales, 2), ROUND(v_curr_sales, 2), ROUND(v_sales_rel_change * 100, 2) || '%';
    RAISE NOTICE 'Global Orders:          Base=% | Curr=% | RelChg=%', ROUND(v_base_orders, 1), ROUND(v_curr_orders, 1), ROUND(v_orders_rel_change * 100, 2) || '%';
    RAISE NOTICE 'Global Sessions:        Base=% | Curr=% | RelChg=%', ROUND(v_base_sessions, 1), ROUND(v_curr_sessions, 1), ROUND(v_sessions_rel_change * 100, 2) || '%';
    RAISE NOTICE 'Global Conversion Rate: Base=% | Curr=% | RelChg=%', ROUND(v_base_cr * 100, 2) || '%', ROUND(v_curr_cr * 100, 2) || '%', ROUND(v_cr_rel_change * 100, 2) || '%';
    RAISE NOTICE 'Global AOV:             Base=$% | Curr=$% | RelChg=%', ROUND(v_base_aov, 2), ROUND(v_curr_aov, 2), ROUND(v_aov_rel_change * 100, 2) || '%';

    -- Global Assertions
    IF NOT (v_sales_rel_change <= -0.10) THEN
        RAISE EXCEPTION 'FAIL: Sales relative change (%) did not meet material decline threshold (<= -10%%)', ROUND(v_sales_rel_change * 100, 2);
    END IF;

    IF NOT (v_orders_rel_change <= -0.10) THEN
        RAISE EXCEPTION 'FAIL: Orders relative change (%) did not meet material decline threshold (<= -10%%)', ROUND(v_orders_rel_change * 100, 2);
    END IF;

    IF NOT (ABS(v_sessions_rel_change) < 0.05) THEN
        RAISE EXCEPTION 'FAIL: Sessions relative change (%) exceeded stability threshold (< 5%%)', ROUND(v_sessions_rel_change * 100, 2);
    END IF;

    IF NOT (v_cr_rel_change <= -0.10) THEN
        RAISE EXCEPTION 'FAIL: Conversion Rate relative change (%) did not meet material decline threshold (<= -10%%)', ROUND(v_cr_rel_change * 100, 2);
    END IF;

    IF NOT (ABS(v_aov_rel_change) < 0.05) THEN
        RAISE EXCEPTION 'FAIL: AOV relative change (%) exceeded stability threshold (< 5%%)', ROUND(v_aov_rel_change * 100, 2);
    END IF;

    -- 2. Marketplace Level Analysis
    WITH mkt_stats AS (
        SELECT
            b.marketplace,
            b.base_sessions,
            b.base_cr,
            c.curr_sessions,
            c.curr_orders,
            c.curr_cr,
            (c.curr_cr - b.base_cr) / NULLIF(b.base_cr, 0) AS cr_rel_change,
            (c.curr_sessions * b.base_cr - c.curr_orders) AS shortfall
        FROM (
            SELECT
                marketplace,
                SUM(sessions) / 7.0 AS base_sessions,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS base_cr
            FROM warehouse.fact_daily_performance
            WHERE date >= '2026-01-24' AND date <= '2026-01-30'
            GROUP BY marketplace
        ) b
        JOIN (
            SELECT
                marketplace,
                SUM(sessions) AS curr_sessions,
                SUM(orders) AS curr_orders,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS curr_cr
            FROM warehouse.fact_daily_performance
            WHERE date = '2026-01-31'
            GROUP BY marketplace
        ) c ON b.marketplace = c.marketplace
    )
    SELECT
        COALESCE(SUM(CASE WHEN shortfall > 0 THEN shortfall ELSE 0 END), 0),
        COALESCE(MAX(CASE WHEN marketplace = 'US' THEN shortfall ELSE NULL END), 0),
        COALESCE(MAX(CASE WHEN marketplace = 'US' THEN base_sessions ELSE NULL END), 0),
        MAX(CASE WHEN marketplace = 'US' THEN cr_rel_change ELSE NULL END),
        MAX(CASE WHEN marketplace = 'UK' THEN cr_rel_change ELSE NULL END),
        MAX(CASE WHEN marketplace = 'DE' THEN cr_rel_change ELSE NULL END),
        COALESCE(MAX(CASE WHEN marketplace = 'UK' THEN shortfall ELSE NULL END), 0),
        COALESCE(MAX(CASE WHEN marketplace = 'DE' THEN shortfall ELSE NULL END), 0)
    INTO
        v_total_mkt_shortfall,
        v_us_shortfall,
        v_us_base_sessions,
        v_us_cr_rel_change,
        v_uk_cr_rel_change,
        v_de_cr_rel_change,
        v_uk_shortfall,
        v_de_shortfall
    FROM mkt_stats;

    IF v_total_mkt_shortfall IS NULL OR v_total_mkt_shortfall <= 0 THEN
        RAISE EXCEPTION 'FAIL: Total marketplace positive shortfall is zero or NULL (%)', v_total_mkt_shortfall;
    END IF;
    IF v_us_cr_rel_change IS NULL OR v_uk_cr_rel_change IS NULL OR v_de_cr_rel_change IS NULL THEN
        RAISE EXCEPTION 'FAIL: Marketplace CR relative change contains NULL (US=%, UK=%, DE=%)', v_us_cr_rel_change, v_uk_cr_rel_change, v_de_cr_rel_change;
    END IF;

    v_us_share := v_us_shortfall / v_total_mkt_shortfall;
    RAISE NOTICE 'Marketplace US:         Shortfall=% | TotalShortfall=% | Share=% | BaseSessions=% | CRRelChg=%',
        ROUND(v_us_shortfall, 2), ROUND(v_total_mkt_shortfall, 2), ROUND(v_us_share * 100, 2) || '%', ROUND(v_us_base_sessions, 1), ROUND(v_us_cr_rel_change * 100, 2) || '%';
    RAISE NOTICE 'Marketplace Controls:   UK CRRelChg=% (Shortfall=%) | DE CRRelChg=% (Shortfall=%)',
        ROUND(v_uk_cr_rel_change * 100, 2) || '%', ROUND(v_uk_shortfall, 2), ROUND(v_de_cr_rel_change * 100, 2) || '%', ROUND(v_de_shortfall, 2);

    IF NOT (v_us_base_sessions >= 30) THEN
        RAISE EXCEPTION 'FAIL: Marketplace US baseline daily sessions (%) is below 30 threshold', v_us_base_sessions;
    END IF;

    IF NOT (v_us_cr_rel_change <= -0.10) THEN
        RAISE EXCEPTION 'FAIL: Marketplace US own Conversion Rate relative change (%) did not meet material decline threshold (<= -10%%)', ROUND(v_us_cr_rel_change * 100, 2);
    END IF;

    IF NOT (v_us_shortfall > v_uk_shortfall AND v_us_shortfall > v_de_shortfall) THEN
        RAISE EXCEPTION 'FAIL: Marketplace US is not the maximum shortfall contributor (US=%, UK=%, DE=%)', v_us_shortfall, v_uk_shortfall, v_de_shortfall;
    END IF;

    IF NOT (v_us_share >= 0.50) THEN
        RAISE EXCEPTION 'FAIL: Marketplace US shortfall share (%) is below 50%% threshold', ROUND(v_us_share * 100, 2);
    END IF;

    IF NOT (ABS(v_uk_cr_rel_change) < 0.05 AND ABS(v_de_cr_rel_change) < 0.05) THEN
        RAISE EXCEPTION 'FAIL: Non-US marketplace negative controls violated (UK CR RelChg=%, DE CR RelChg=%)', ROUND(v_uk_cr_rel_change * 100, 2), ROUND(v_de_cr_rel_change * 100, 2);
    END IF;

    -- 3. ASIN Level Analysis (Inside Marketplace = 'US')
    WITH asin_stats AS (
        SELECT
            b.asin,
            b.base_sessions,
            b.base_cr,
            c.curr_sessions,
            c.curr_orders,
            c.curr_cr,
            (c.curr_cr - b.base_cr) / NULLIF(b.base_cr, 0) AS cr_rel_change,
            (c.curr_sessions * b.base_cr - c.curr_orders) AS shortfall
        FROM (
            SELECT
                asin,
                SUM(sessions) / 7.0 AS base_sessions,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS base_cr
            FROM warehouse.fact_daily_performance
            WHERE date >= '2026-01-24' AND date <= '2026-01-30' AND marketplace = 'US'
            GROUP BY asin
        ) b
        JOIN (
            SELECT
                asin,
                SUM(sessions) AS curr_sessions,
                SUM(orders) AS curr_orders,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS curr_cr
            FROM warehouse.fact_daily_performance
            WHERE date = '2026-01-31' AND marketplace = 'US'
            GROUP BY asin
        ) c ON b.asin = c.asin
    )
    SELECT
        COALESCE(SUM(CASE WHEN shortfall > 0 THEN shortfall ELSE 0 END), 0),
        COALESCE(MAX(CASE WHEN asin = 'ASIN-A' THEN shortfall ELSE NULL END), 0),
        COALESCE(MAX(CASE WHEN asin = 'ASIN-A' THEN base_sessions ELSE NULL END), 0),
        MAX(CASE WHEN asin = 'ASIN-A' THEN cr_rel_change ELSE NULL END),
        MAX(CASE WHEN asin = 'ASIN-B' THEN cr_rel_change ELSE NULL END),
        MAX(CASE WHEN asin = 'ASIN-C' THEN cr_rel_change ELSE NULL END),
        COALESCE(MAX(CASE WHEN asin = 'ASIN-B' THEN shortfall ELSE NULL END), 0),
        COALESCE(MAX(CASE WHEN asin = 'ASIN-C' THEN shortfall ELSE NULL END), 0)
    INTO
        v_total_asin_shortfall,
        v_asin_a_shortfall,
        v_asin_a_base_sessions,
        v_asin_a_cr_rel_change,
        v_asin_b_cr_rel_change,
        v_asin_c_cr_rel_change,
        v_asin_b_shortfall,
        v_asin_c_shortfall
    FROM asin_stats;

    IF v_total_asin_shortfall IS NULL OR v_total_asin_shortfall <= 0 THEN
        RAISE EXCEPTION 'FAIL: Total US ASIN positive shortfall is zero or NULL (%)', v_total_asin_shortfall;
    END IF;
    IF v_asin_a_cr_rel_change IS NULL OR v_asin_b_cr_rel_change IS NULL OR v_asin_c_cr_rel_change IS NULL THEN
        RAISE EXCEPTION 'FAIL: US ASIN CR relative change contains NULL (A=%, B=%, C=%)', v_asin_a_cr_rel_change, v_asin_b_cr_rel_change, v_asin_c_cr_rel_change;
    END IF;

    v_asin_a_share := v_asin_a_shortfall / v_total_asin_shortfall;
    RAISE NOTICE 'ASIN ASIN-A (in US):    Shortfall=% | TotalShortfall=% | Share=% | BaseSessions=% | CRRelChg=%',
        ROUND(v_asin_a_shortfall, 2), ROUND(v_total_asin_shortfall, 2), ROUND(v_asin_a_share * 100, 2) || '%', ROUND(v_asin_a_base_sessions, 1), ROUND(v_asin_a_cr_rel_change * 100, 2) || '%';
    RAISE NOTICE 'ASIN Controls (in US):  ASIN-B CRRelChg=% (Shortfall=%) | ASIN-C CRRelChg=% (Shortfall=%)',
        ROUND(v_asin_b_cr_rel_change * 100, 2) || '%', ROUND(v_asin_b_shortfall, 2), ROUND(v_asin_c_cr_rel_change * 100, 2) || '%', ROUND(v_asin_c_shortfall, 2);

    IF NOT (v_asin_a_base_sessions >= 30) THEN
        RAISE EXCEPTION 'FAIL: ASIN-A baseline daily sessions (%) is below 30 threshold', v_asin_a_base_sessions;
    END IF;

    IF NOT (v_asin_a_cr_rel_change <= -0.10) THEN
        RAISE EXCEPTION 'FAIL: ASIN-A own Conversion Rate relative change (%) did not meet material decline threshold (<= -10%%)', ROUND(v_asin_a_cr_rel_change * 100, 2);
    END IF;

    IF NOT (v_asin_a_shortfall > v_asin_b_shortfall AND v_asin_a_shortfall > v_asin_c_shortfall) THEN
        RAISE EXCEPTION 'FAIL: ASIN-A is not the maximum shortfall contributor in US (A=%, B=%, C=%)', v_asin_a_shortfall, v_asin_b_shortfall, v_asin_c_shortfall;
    END IF;

    IF NOT (v_asin_a_share >= 0.50) THEN
        RAISE EXCEPTION 'FAIL: ASIN-A shortfall share (%) is below 50%% threshold', ROUND(v_asin_a_share * 100, 2);
    END IF;

    IF NOT (ABS(v_asin_b_cr_rel_change) < 0.05 AND ABS(v_asin_c_cr_rel_change) < 0.05) THEN
        RAISE EXCEPTION 'FAIL: Non-target ASIN negative controls violated in US (ASIN-B CR RelChg=%, ASIN-C CR RelChg=%)', ROUND(v_asin_b_cr_rel_change * 100, 2), ROUND(v_asin_c_cr_rel_change * 100, 2);
    END IF;

    -- 4. Traffic Source Level Analysis (Inside Marketplace = 'US' AND ASIN = 'ASIN-A')
    WITH src_stats AS (
        SELECT
            b.traffic_source,
            b.base_sessions,
            b.base_cr,
            c.curr_sessions,
            c.curr_orders,
            c.curr_cr,
            (c.curr_cr - b.base_cr) / NULLIF(b.base_cr, 0) AS cr_rel_change,
            (c.curr_sessions * b.base_cr - c.curr_orders) AS shortfall
        FROM (
            SELECT
                traffic_source,
                SUM(sessions) / 7.0 AS base_sessions,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS base_cr
            FROM warehouse.fact_daily_performance
            WHERE date >= '2026-01-24' AND date <= '2026-01-30' AND marketplace = 'US' AND asin = 'ASIN-A'
            GROUP BY traffic_source
        ) b
        JOIN (
            SELECT
                traffic_source,
                SUM(sessions) AS curr_sessions,
                SUM(orders) AS curr_orders,
                SUM(orders)::numeric / NULLIF(SUM(sessions), 0) AS curr_cr
            FROM warehouse.fact_daily_performance
            WHERE date = '2026-01-31' AND marketplace = 'US' AND asin = 'ASIN-A'
            GROUP BY traffic_source
        ) c ON b.traffic_source = c.traffic_source
    )
    SELECT
        COALESCE(SUM(CASE WHEN shortfall > 0 THEN shortfall ELSE 0 END), 0),
        COALESCE(MAX(CASE WHEN traffic_source = 'Ads' THEN shortfall ELSE NULL END), 0),
        COALESCE(MAX(CASE WHEN traffic_source = 'Ads' THEN base_sessions ELSE NULL END), 0),
        MAX(CASE WHEN traffic_source = 'Ads' THEN cr_rel_change ELSE NULL END),
        MAX(CASE WHEN traffic_source = 'Organic' THEN cr_rel_change ELSE NULL END),
        COALESCE(MAX(CASE WHEN traffic_source = 'Organic' THEN shortfall ELSE NULL END), 0)
    INTO
        v_total_src_shortfall,
        v_ads_shortfall,
        v_ads_base_sessions,
        v_ads_cr_rel_change,
        v_org_cr_rel_change,
        v_org_shortfall
    FROM src_stats;

    IF v_total_src_shortfall IS NULL OR v_total_src_shortfall <= 0 THEN
        RAISE EXCEPTION 'FAIL: Total US+ASIN-A traffic source positive shortfall is zero or NULL (%)', v_total_src_shortfall;
    END IF;
    IF v_ads_cr_rel_change IS NULL OR v_org_cr_rel_change IS NULL THEN
        RAISE EXCEPTION 'FAIL: US+ASIN-A traffic source CR relative change contains NULL (Ads=%, Organic=%)', v_ads_cr_rel_change, v_org_cr_rel_change;
    END IF;

    v_ads_share := v_ads_shortfall / v_total_src_shortfall;
    RAISE NOTICE 'Traffic Source Ads:     Shortfall=% | TotalShortfall=% | Share=% | BaseSessions=% | CRRelChg=%',
        ROUND(v_ads_shortfall, 2), ROUND(v_total_src_shortfall, 2), ROUND(v_ads_share * 100, 2) || '%', ROUND(v_ads_base_sessions, 1), ROUND(v_ads_cr_rel_change * 100, 2) || '%';
    RAISE NOTICE 'Traffic Source Controls: Organic CRRelChg=% (Shortfall=%)',
        ROUND(v_org_cr_rel_change * 100, 2) || '%', ROUND(v_org_shortfall, 2);

    IF NOT (v_ads_base_sessions >= 30) THEN
        RAISE EXCEPTION 'FAIL: Ads baseline daily sessions (%) is below 30 threshold', v_ads_base_sessions;
    END IF;

    IF NOT (v_ads_cr_rel_change <= -0.10) THEN
        RAISE EXCEPTION 'FAIL: Ads own Conversion Rate relative change (%) did not meet material decline threshold (<= -10%%)', ROUND(v_ads_cr_rel_change * 100, 2);
    END IF;

    IF NOT (v_ads_shortfall > v_org_shortfall) THEN
        RAISE EXCEPTION 'FAIL: Ads is not the maximum shortfall contributor in US+ASIN-A (Ads=%, Organic=%)', v_ads_shortfall, v_org_shortfall;
    END IF;

    IF NOT (v_ads_share >= 0.50) THEN
        RAISE EXCEPTION 'FAIL: Ads shortfall share (%) is below 50%% threshold', ROUND(v_ads_share * 100, 2);
    END IF;

    IF NOT (ABS(v_org_cr_rel_change) < 0.05) THEN
        RAISE EXCEPTION 'FAIL: Organic traffic negative control violated in US+ASIN-A (Organic CR RelChg=%)', ROUND(v_org_cr_rel_change * 100, 2);
    END IF;

    RAISE NOTICE '=======================================================';
    RAISE NOTICE 'STATUS: PASS - All Canonical Case Assertions Succeeded!';
    RAISE NOTICE '=======================================================';
END $$;
