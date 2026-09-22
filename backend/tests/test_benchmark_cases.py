import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.diagnosis.models import DiagnosisStatus
from app.evaluation import (
    EvidenceObligationKind,
    GroundTruthCase,
    build_evidence_obligations,
    load_ground_truth_cases,
)
from warehouse.anomaly_injector import (
    SCENARIO_TARGET_SEGMENTS,
    SUPPORTED_SCENARIOS,
    apply_scenario,
    generate_current_normal_records,
)

BENCHMARK_CASES_PATH = ROOT / "warehouse" / "benchmark_cases.json"


class TestBenchmarkCases(unittest.TestCase):
    """Verifies the integrity, uniqueness, and obligation derivation for the 10 benchmark cases."""

    def test_load_all_ten_benchmark_cases(self) -> None:
        """Ensures that load_ground_truth_cases successfully loads all 10 benchmark cases."""
        cases = load_ground_truth_cases(BENCHMARK_CASES_PATH)
        self.assertEqual(len(cases), 10)
        for case in cases:
            self.assertIsInstance(case, GroundTruthCase)

    def test_unique_case_ids_and_scenarios(self) -> None:
        """Ensures that case_id and scenario are globally unique across all 10 cases."""
        cases = load_ground_truth_cases(BENCHMARK_CASES_PATH)
        case_ids = [c.case_id for c in cases]
        scenarios = [c.scenario for c in cases]

        self.assertEqual(len(case_ids), 10)
        self.assertEqual(len(set(case_ids)), 10)
        self.assertEqual(len(scenarios), 10)
        self.assertEqual(len(set(scenarios)), 10)

    def test_scenario_and_driver_coverage(self) -> None:
        """Verifies driver distribution: 3 CR, 3 sessions, 2 AOV, 2 no_material_anomaly."""
        cases = load_ground_truth_cases(BENCHMARK_CASES_PATH)
        cases_by_scenario = {c.scenario: c for c in cases}

        # Verify all 10 scenarios are present
        self.assertEqual(set(cases_by_scenario.keys()), set(SUPPORTED_SCENARIOS))

        # Check driver counts
        cr_cases = [c for c in cases if c.primary_driver == "conversion_rate"]
        sessions_cases = [c for c in cases if c.primary_driver == "sessions"]
        aov_cases = [c for c in cases if c.primary_driver == "aov"]
        no_anomaly_cases = [c for c in cases if c.status == DiagnosisStatus.NO_MATERIAL_ANOMALY]

        self.assertEqual(len(cr_cases), 3)
        self.assertEqual(len(sessions_cases), 3)
        self.assertEqual(len(aov_cases), 2)
        self.assertEqual(len(no_anomaly_cases), 2)

        # Check expected statuses
        for case in cr_cases + sessions_cases + aov_cases:
            self.assertEqual(case.status, DiagnosisStatus.DIAGNOSED)
            self.assertTrue(len(case.affected_scope) > 0)

        for case in no_anomaly_cases:
            self.assertIsNone(case.primary_driver)
            self.assertEqual(len(case.affected_scope), 0)

    def test_build_evidence_obligations_for_all_cases(self) -> None:
        """Verifies deterministic obligation expansion for all 10 cases."""
        cases = load_ground_truth_cases(BENCHMARK_CASES_PATH)

        for case in cases:
            obligations = build_evidence_obligations(case)
            self.assertTrue(len(obligations) > 0, f"Case {case.case_id} produced no obligations.")

            # Check uniqueness of obligation IDs
            obligation_ids = [o.obligation_id for o in obligations]
            self.assertEqual(len(obligation_ids), len(set(obligation_ids)))

            # Check kinds and prefixes
            for o in obligations:
                self.assertTrue(o.obligation_id.startswith("obligation:"))
                if o.kind in {
                    EvidenceObligationKind.TARGET_SUPPORTING,
                    EvidenceObligationKind.DRIVER_SUPPORTING,
                    EvidenceObligationKind.STABLE_METRIC,
                }:
                    self.assertIsNotNone(o.metric)
                    self.assertIsNone(o.dimension)
                elif o.kind == EvidenceObligationKind.NEGATIVE_CONTROL:
                    self.assertIsNone(o.metric)
                    self.assertIsNotNone(o.dimension)
                    self.assertIsNotNone(o.dimension_value)

            if case.status == DiagnosisStatus.DIAGNOSED:
                kinds = [o.kind for o in obligations]
                self.assertIn(EvidenceObligationKind.TARGET_SUPPORTING, kinds)
                self.assertIn(EvidenceObligationKind.DRIVER_SUPPORTING, kinds)
            else:
                kinds = [o.kind for o in obligations]
                self.assertNotIn(EvidenceObligationKind.TARGET_SUPPORTING, kinds)
                self.assertNotIn(EvidenceObligationKind.DRIVER_SUPPORTING, kinds)
                self.assertIn(EvidenceObligationKind.STABLE_METRIC, kinds)
                self.assertIn(EvidenceObligationKind.NEGATIVE_CONTROL, kinds)

    def test_negative_controls_contract_compliance(self) -> None:
        """Verifies that all 10 cases have well-formed negative_controls mappings."""
        cases = load_ground_truth_cases(BENCHMARK_CASES_PATH)
        for case in cases:
            self.assertIn("marketplaces", case.negative_controls)
            self.assertIn("asins", case.negative_controls)
            self.assertIn("traffic_sources", case.negative_controls)
            self.assertTrue(len(case.negative_controls["marketplaces"]) > 0)
            self.assertTrue(len(case.negative_controls["asins"]) > 0)
            self.assertTrue(len(case.negative_controls["traffic_sources"]) > 0)


class TestAnomalyInjector(unittest.TestCase):
    """Verifies deterministic record mutations for all 10 scenarios in anomaly_injector.py."""

    def test_supported_scenarios_count(self) -> None:
        self.assertEqual(len(SUPPORTED_SCENARIOS), 10)
        self.assertEqual(len(SCENARIO_TARGET_SEGMENTS), 10)

    def test_invalid_scenario_raises_value_error(self) -> None:
        records = generate_current_normal_records()
        with self.assertRaises(ValueError):
            apply_scenario(records, "unknown_nonexistent_scenario")

    def test_no_anomaly_leaves_records_unchanged(self) -> None:
        records = generate_current_normal_records()
        mutated = apply_scenario(records, "no_anomaly")
        normal = generate_current_normal_records()
        self.assertEqual(mutated, normal)

    def test_canonical_conversion_drop(self) -> None:
        records = generate_current_normal_records()
        mutated = apply_scenario(records, "canonical")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-A", "Ads")][0]
        self.assertEqual(target["orders"], 10)
        self.assertEqual(target["sales"], 800.0)

    def test_traffic_drop(self) -> None:
        records = generate_current_normal_records()
        normal_target = [r for r in records if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-A", "Ads")][0]
        expected_sessions = int(round(normal_target["sessions"] * 0.20))

        mutated = apply_scenario(records, "traffic")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-A", "Ads")][0]
        self.assertEqual(target["sessions"], expected_sessions)
        self.assertEqual(target["orders"], int(round(expected_sessions * 0.08)))
        self.assertEqual(target["sales"], round(target["orders"] * 80.0, 2))

    def test_aov_us_asin_b_organic(self) -> None:
        records = generate_current_normal_records()
        normal_target = [r for r in records if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-B", "Organic")][0]
        normal_orders = normal_target["orders"]

        mutated = apply_scenario(records, "aov_us_asin_b_organic")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-B", "Organic")][0]
        self.assertEqual(target["orders"], normal_orders)
        self.assertEqual(target["sales"], round(normal_orders * 8.0, 2))

    def test_traffic_uk_asin_b_ads(self) -> None:
        records = generate_current_normal_records()
        normal_target = [r for r in records if (r["marketplace"], r["asin"], r["traffic_source"]) == ("UK", "ASIN-B", "Ads")][0]
        expected_sessions = int(round(normal_target["sessions"] * 0.10))

        mutated = apply_scenario(records, "traffic_uk_asin_b_ads")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("UK", "ASIN-B", "Ads")][0]
        self.assertEqual(target["sessions"], expected_sessions)
        self.assertEqual(target["orders"], int(round(expected_sessions * 0.08)))
        self.assertEqual(target["sales"], round(target["orders"] * 80.0, 2))

    def test_conversion_de_asin_c_ads(self) -> None:
        records = generate_current_normal_records()
        normal_target = [r for r in records if (r["marketplace"], r["asin"], r["traffic_source"]) == ("DE", "ASIN-C", "Ads")][0]
        expected_orders = int(round(normal_target["orders"] * 0.10))

        mutated = apply_scenario(records, "conversion_de_asin_c_ads")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("DE", "ASIN-C", "Ads")][0]
        self.assertEqual(target["orders"], expected_orders)
        self.assertEqual(target["sales"], round(expected_orders * 80.0, 2))

    def test_traffic_us_asin_c_organic(self) -> None:
        records = generate_current_normal_records()
        normal_target = [r for r in records if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-C", "Organic")][0]
        expected_sessions = int(round(normal_target["sessions"] * 0.10))

        mutated = apply_scenario(records, "traffic_us_asin_c_organic")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-C", "Organic")][0]
        self.assertEqual(target["sessions"], expected_sessions)
        self.assertEqual(target["orders"], int(round(expected_sessions * 0.08)))
        self.assertEqual(target["sales"], round(target["orders"] * 80.0, 2))

    def test_aov_uk_asin_a_ads(self) -> None:
        records = generate_current_normal_records()
        normal_target = [r for r in records if (r["marketplace"], r["asin"], r["traffic_source"]) == ("UK", "ASIN-A", "Ads")][0]
        normal_orders = normal_target["orders"]

        mutated = apply_scenario(records, "aov_uk_asin_a_ads")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("UK", "ASIN-A", "Ads")][0]
        self.assertEqual(target["orders"], normal_orders)
        self.assertEqual(target["sales"], round(normal_orders * 8.0, 2))

    def test_conversion_us_asin_b_ads(self) -> None:
        records = generate_current_normal_records()
        normal_target = [r for r in records if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-B", "Ads")][0]
        expected_orders = int(round(normal_target["orders"] * 0.10))

        mutated = apply_scenario(records, "conversion_us_asin_b_ads")
        target = [r for r in mutated if (r["marketplace"], r["asin"], r["traffic_source"]) == ("US", "ASIN-B", "Ads")][0]
        self.assertEqual(target["orders"], expected_orders)
        self.assertEqual(target["sales"], round(expected_orders * 80.0, 2))

    def test_distractor_minor_fluctuation_materiality(self) -> None:
        records = generate_current_normal_records()
        total_normal_sales = sum(r["sales"] for r in records)

        mutated = apply_scenario(records, "distractor_minor_fluctuation")
        total_mutated_sales = sum(r["sales"] for r in mutated)

        sales_impact = abs(total_mutated_sales - total_normal_sales) / total_normal_sales
        self.assertLess(sales_impact, 0.025, "Distractor impact must be less than 2.5% of total sales.")
