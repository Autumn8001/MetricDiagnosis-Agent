"""Verify real generated fixture expectations, not invented model outcomes."""
import unittest

from app.api.task_schemas import InvestigationTaskCreate
from app.evaluation import load_ground_truth_cases
from app.sandbox.dataset_writer import build_sandbox_rows
from scripts.prepare_sandbox_evaluation import ROOT, audit_fixture, prepare


class SandboxEvaluationPreparationTests(unittest.TestCase):
    def test_deterministic_inputs_validate_as_product_requests_without_answers(self):
        plan = prepare()
        self.assertEqual(plan, prepare())
        self.assertEqual(plan["execution"], "not_executed")
        self.assertEqual(plan["authorized_model_calls"], 0)
        self.assertIsNone(plan["model_id"])
        self.assertEqual(len({c["data_version"] for c in plan["cases"]}), 3)
        for case in plan["cases"]:
            request = InvestigationTaskCreate.model_validate({"source_id": "assigned-at-publication", **case["task_input"]})
            self.assertEqual(request.filters, {})
            self.assertEqual(set(case["task_input"]), {"target_metric", "target_date", "filters", "group_by"})
            self.assertEqual(case["row_count"], 558)
            self.assertTrue(all(c["passed"] for c in case["fixture_checks"]))

    def test_normal_data_cannot_pass_anomaly_expectation(self):
        case = next(c for c in load_ground_truth_cases(ROOT / "warehouse/benchmark_cases.json") if c.scenario == "canonical")
        with self.assertRaisesRegex(ValueError, "fixture_expectations_disagree"):
            audit_fixture(build_sandbox_rows("no_anomaly"), case)

    def test_polluted_negative_control_is_rejected(self):
        case = next(c for c in load_ground_truth_cases(ROOT / "warehouse/benchmark_cases.json") if c.scenario == "canonical")
        rows = build_sandbox_rows("canonical")
        modified = []
        for row in rows:
            if row[0].isoformat() == "2026-01-31" and row[2] == "DE":
                row = (*row[:7], 0, 0, *row[9:])
            modified.append(row)
        with self.assertRaisesRegex(ValueError, "fixture_expectations_disagree"):
            audit_fixture(modified, case)
