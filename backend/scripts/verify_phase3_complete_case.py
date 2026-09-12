"""Verification script for Phase 3 complete Canonical Case investigation.

Performs a full step-by-step human investigation using AnalyticsTools:
  Global Sales Drop
  -> Orders & Conversion Rate Drop (Sessions & AOV stable)
  -> Marketplace Drill-Down (US by conversion_order_shortfall >= 50%)
  -> ASIN Drill-Down (ASIN-A by conversion_order_shortfall >= 50%)
  -> Traffic Source Drill-Down (Ads by conversion_order_shortfall >= 50%)
"""

from dataclasses import dataclass
import datetime
from decimal import Decimal
import os
from pathlib import Path
import sys

import psycopg

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.analytics.models import RelatedMetricQueryResult
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricRegistry


@dataclass(frozen=True)
class SegmentShortfallAnalysis:
    dimension_key: str
    dimension_value: str
    current_orders: Decimal
    current_sessions: Decimal
    baseline_cr: Decimal
    current_cr: Decimal
    cr_relative_change: Decimal | None
    expected_orders: Decimal
    conversion_order_shortfall: Decimal
    positive_shortfall: Decimal
    contribution_share: Decimal
    sample_size: Decimal | None
    status: str


def analyze_segments(
    related_result: RelatedMetricQueryResult,
    group_dim: str,
) -> tuple[list[SegmentShortfallAnalysis], SegmentShortfallAnalysis]:
    """Calculate conversion_order_shortfall and contribution_share for each segment.

    Identifies the unique primary anomaly segment satisfying:
      - status == 'ok'
      - sample_size >= 30
      - cr_relative_change <= -0.10
      - contribution_share >= 0.50 (50%)
    """
    res_map = {r.metric_id: r for r in related_result.results}
    orders_res = res_map["orders"]
    sessions_res = res_map["sessions"]
    cr_res = res_map["conversion_rate"]

    orders_by_dim = {r.dimensions[group_dim]: r for r in orders_res.rows}
    sessions_by_dim = {r.dimensions[group_dim]: r for r in sessions_res.rows}
    cr_by_dim = {r.dimensions[group_dim]: r for r in cr_res.rows}

    dim_values = sorted(cr_by_dim.keys())

    preliminary_rows = []
    total_pos_shortfall = Decimal("0")

    for val in dim_values:
        o_row = orders_by_dim[val]
        s_row = sessions_by_dim[val]
        c_row = cr_by_dim[val]

        curr_orders = o_row.current_value if o_row.current_value is not None else Decimal("0")
        curr_sessions = s_row.current_value if s_row.current_value is not None else Decimal("0")
        base_cr = c_row.baseline_value if c_row.baseline_value is not None else Decimal("0")
        curr_cr = c_row.current_value if c_row.current_value is not None else Decimal("0")

        expected_orders = curr_sessions * base_cr
        shortfall = expected_orders - curr_orders
        pos_shortfall = max(shortfall, Decimal("0"))
        total_pos_shortfall += pos_shortfall

        preliminary_rows.append(
            (val, curr_orders, curr_sessions, base_cr, curr_cr, c_row.relative_change, expected_orders, shortfall, pos_shortfall, c_row.sample_size, c_row.status)
        )

    analyzed_segments: list[SegmentShortfallAnalysis] = []
    for item in preliminary_rows:
        val, curr_o, curr_s, base_c, curr_c, rel_chg, exp_o, s_fall, pos_s, sample_s, st = item
        if total_pos_shortfall > Decimal("0"):
            contrib_share = pos_s / total_pos_shortfall
        else:
            contrib_share = Decimal("0")

        analyzed_segments.append(
            SegmentShortfallAnalysis(
                dimension_key=group_dim,
                dimension_value=val,
                current_orders=curr_o,
                current_sessions=curr_s,
                baseline_cr=base_c,
                current_cr=curr_c,
                cr_relative_change=rel_chg,
                expected_orders=exp_o,
                conversion_order_shortfall=s_fall,
                positive_shortfall=pos_s,
                contribution_share=contrib_share,
                sample_size=sample_s,
                status=st,
            )
        )

    # Filter candidates meeting strict primary driver criteria
    candidates = [
        seg
        for seg in analyzed_segments
        if seg.status == "ok"
        and seg.sample_size is not None
        and seg.sample_size >= Decimal("30")
        and seg.cr_relative_change is not None
        and seg.cr_relative_change <= Decimal("-0.10")
        and seg.contribution_share >= Decimal("0.50")
    ]

    if len(candidates) != 1:
        raise AssertionError(
            f"Expected exactly 1 primary segment with contribution_share >= 50% for '{group_dim}', found {len(candidates)}: {candidates}"
        )

    return analyzed_segments, candidates[0]


def run_complete_investigation() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)

    yaml_path = backend_root.parent / "configs" / "metrics.yaml"
    print(f"Loading MetricRegistry from {yaml_path} ...")
    registry = MetricRegistry.from_yaml(yaml_path)

    test_date = datetime.date(2026, 1, 31)

    print("Connecting to database via DATABASE_URL ...")
    with psycopg.connect(database_url) as conn:
        tools = AnalyticsTools(registry=registry, connection=conn)

        print("\n=======================================================")
        print(" Step 1: Global Metric Anomaly Detection (Sales)       ")
        print("=======================================================")
        sales_result = tools.query_metric(
            metric="sales",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
        )
        assert len(sales_result.rows) == 1
        sales_row = sales_result.rows[0]
        print(f"Global Sales: curr=${sales_row.current_value:.2f}, base=${sales_row.baseline_value:.2f}, rel_change={sales_row.relative_change:.4f}, status={sales_row.status}")
        assert sales_row.status == "ok"
        assert sales_row.relative_change is not None and sales_row.relative_change <= Decimal("-0.10"), (
            f"Expected material drop in sales (<= -10%), got {sales_row.relative_change}"
        )

        print("\n=======================================================")
        print(" Step 2: Query Related Metrics to Decompose Sales      ")
        print("=======================================================")
        related_global = tools.query_related_metrics(
            metric="sales",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
        )
        rel_map = {r.metric_id: r.rows[0] for r in related_global.results}

        # Check declared related metrics order and values
        declared_order = [r.metric_id for r in related_global.results]
        assert declared_order == ["orders", "sessions", "conversion_rate", "aov"]

        orders_row = rel_map["orders"]
        sessions_row = rel_map["sessions"]
        cr_row = rel_map["conversion_rate"]
        aov_row = rel_map["aov"]

        print(f"  - Orders: curr={orders_row.current_value}, base={orders_row.baseline_value:.2f}, rel_change={orders_row.relative_change:.4f}")
        print(f"  - Sessions: curr={sessions_row.current_value}, base={sessions_row.baseline_value:.2f}, rel_change={sessions_row.relative_change:.4f}")
        print(f"  - Conversion Rate: curr={cr_row.current_value:.4f}, base={cr_row.baseline_value:.4f}, rel_change={cr_row.relative_change:.4f}")
        print(f"  - AOV: curr=${aov_row.current_value:.2f}, base=${aov_row.baseline_value:.2f}, rel_change={aov_row.relative_change:.4f}")

        # Assert: Orders dropped, AOV stable, Sessions stable, CR dropped
        assert orders_row.relative_change is not None and orders_row.relative_change <= Decimal("-0.10"), "Orders must drop <= -10%"
        assert aov_row.relative_change is not None and abs(aov_row.relative_change) < Decimal("0.05"), "AOV must be stable (< 5%)"
        assert sessions_row.relative_change is not None and abs(sessions_row.relative_change) < Decimal("0.05"), "Sessions must be stable (< 5%)"
        assert cr_row.relative_change is not None and cr_row.relative_change <= Decimal("-0.10"), "Conversion Rate must drop <= -10%"

        print("\nPrimary Driver Metric: Conversion Rate (Orders drop driven by CR drop, not Sessions or AOV)")

        print("\n=======================================================")
        print(" Step 3: Marketplace Drill-Down (group_by=['marketplace'])")
        print("=======================================================")
        rel_mkt = tools.query_related_metrics(
            metric="sales",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
            group_by=["marketplace"],
        )
        mkt_analyses, primary_mkt = analyze_segments(rel_mkt, "marketplace")

        print("Marketplace Shortfall Analysis:")
        for seg in mkt_analyses:
            print(
                f"  [{seg.dimension_value}] curr_orders={seg.current_orders}, expected={seg.expected_orders:.1f}, "
                f"shortfall={seg.conversion_order_shortfall:.1f}, share={seg.contribution_share:.2%}, "
                f"CR_rel={seg.cr_relative_change:.4f}, sample_size={seg.sample_size:.1f}"
            )

        # Assert exact member set for Marketplace
        mkt_values = {seg.dimension_value for seg in mkt_analyses}
        assert mkt_values == {"US", "UK", "DE"}, f"Expected marketplace set {{'US', 'UK', 'DE'}}, got {mkt_values}"

        assert primary_mkt.dimension_value == "US", f"Expected primary marketplace 'US', got {primary_mkt.dimension_value}"
        assert primary_mkt.contribution_share >= Decimal("0.50"), f"US share must be >= 50%, got {primary_mkt.contribution_share:.2%}"

        # Check negative controls directly by key (UK, DE)
        mkt_by_val = {seg.dimension_value: seg for seg in mkt_analyses}
        for ctrl_val in ("UK", "DE"):
            ctrl_seg = mkt_by_val[ctrl_val]
            assert ctrl_seg.cr_relative_change is not None and abs(ctrl_seg.cr_relative_change) < Decimal("0.05"), (
                f"Marketplace {ctrl_val} CR must be stable (< 5%), got {ctrl_seg.cr_relative_change}"
            )

        print(f"-> Primary Marketplace: {primary_mkt.dimension_value} (Contribution Share: {primary_mkt.contribution_share:.2%})")

        print("\n=======================================================")
        print(" Step 4: ASIN Drill-Down (filters={'marketplace': 'US'}, group_by=['asin'])")
        print("=======================================================")
        rel_asin = tools.query_related_metrics(
            metric="sales",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
            filters={"marketplace": "US"},
            group_by=["asin"],
        )
        asin_analyses, primary_asin = analyze_segments(rel_asin, "asin")

        print("ASIN Shortfall Analysis (in US):")
        for seg in asin_analyses:
            print(
                f"  [{seg.dimension_value}] curr_orders={seg.current_orders}, expected={seg.expected_orders:.1f}, "
                f"shortfall={seg.conversion_order_shortfall:.1f}, share={seg.contribution_share:.2%}, "
                f"CR_rel={seg.cr_relative_change:.4f}, sample_size={seg.sample_size:.1f}"
            )

        # Assert exact member set for ASIN
        asin_values = {seg.dimension_value for seg in asin_analyses}
        assert asin_values == {"ASIN-A", "ASIN-B", "ASIN-C"}, f"Expected ASIN set {{'ASIN-A', 'ASIN-B', 'ASIN-C'}}, got {asin_values}"

        assert primary_asin.dimension_value == "ASIN-A", f"Expected primary ASIN 'ASIN-A', got {primary_asin.dimension_value}"
        assert primary_asin.contribution_share >= Decimal("0.50"), f"ASIN-A share must be >= 50%, got {primary_asin.contribution_share:.2%}"

        # Check negative controls directly by key (ASIN-B, ASIN-C)
        asin_by_val = {seg.dimension_value: seg for seg in asin_analyses}
        for ctrl_val in ("ASIN-B", "ASIN-C"):
            ctrl_seg = asin_by_val[ctrl_val]
            assert ctrl_seg.cr_relative_change is not None and abs(ctrl_seg.cr_relative_change) < Decimal("0.05"), (
                f"ASIN {ctrl_val} CR must be stable (< 5%), got {ctrl_seg.cr_relative_change}"
            )

        print(f"-> Primary ASIN: {primary_asin.dimension_value} (Contribution Share: {primary_asin.contribution_share:.2%})")

        print("\n=======================================================")
        print(" Step 5: Traffic Source Drill-Down (filters={'marketplace': 'US', 'asin': 'ASIN-A'}, group_by=['traffic_source'])")
        print("=======================================================")
        rel_traffic = tools.query_related_metrics(
            metric="sales",
            start_date=test_date,
            end_date=test_date,
            compare_to="previous_7_days",
            filters={"marketplace": "US", "asin": "ASIN-A"},
            group_by=["traffic_source"],
        )
        traffic_analyses, primary_traffic = analyze_segments(rel_traffic, "traffic_source")

        print("Traffic Source Shortfall Analysis (in US / ASIN-A):")
        for seg in traffic_analyses:
            print(
                f"  [{seg.dimension_value}] curr_orders={seg.current_orders}, expected={seg.expected_orders:.1f}, "
                f"shortfall={seg.conversion_order_shortfall:.1f}, share={seg.contribution_share:.2%}, "
                f"CR_rel={seg.cr_relative_change:.4f}, sample_size={seg.sample_size:.1f}"
            )

        # Assert exact member set for Traffic Source
        traffic_values = {seg.dimension_value for seg in traffic_analyses}
        assert traffic_values == {"Ads", "Organic"}, f"Expected traffic source set {{'Ads', 'Organic'}}, got {traffic_values}"

        assert primary_traffic.dimension_value == "Ads", f"Expected primary traffic source 'Ads', got {primary_traffic.dimension_value}"
        assert primary_traffic.contribution_share >= Decimal("0.50"), f"Ads share must be >= 50%, got {primary_traffic.contribution_share:.2%}"

        # Check negative control directly by key (Organic)
        traffic_by_val = {seg.dimension_value: seg for seg in traffic_analyses}
        ctrl_seg = traffic_by_val["Organic"]
        assert ctrl_seg.cr_relative_change is not None and abs(ctrl_seg.cr_relative_change) < Decimal("0.05"), (
            f"Organic CR must be stable (< 5%), got {ctrl_seg.cr_relative_change}"
        )

        print(f"-> Primary Traffic Source: {primary_traffic.dimension_value} (Contribution Share: {primary_traffic.contribution_share:.2%})")

        print("\n=======================================================")
        print(" Canonical Case Human Investigation Summary            ")
        print("=======================================================")
        print("Metric: Sales")
        print("Primary Driver Metric: Conversion Rate")
        print(f"Marketplace: {primary_mkt.dimension_value} (Contribution Share: {primary_mkt.contribution_share:.2%})")
        print(f"ASIN: {primary_asin.dimension_value} (Contribution Share: {primary_asin.contribution_share:.2%})")
        print(f"Traffic Source: {primary_traffic.dimension_value} (Contribution Share: {primary_traffic.contribution_share:.2%})")
        print("Conclusion Type: Data Anomaly Contribution Localization")
        print("\n[NOTE] This investigation concludes data anomaly contribution localization.")
        print("It does NOT prove external business root cause (e.g. ad bidding, listing page changes, competitor pricing).")
        print("=======================================================")
        print("Phase 3 Complete Case Verification: ALL PASS!")


if __name__ == "__main__":
    run_complete_investigation()
