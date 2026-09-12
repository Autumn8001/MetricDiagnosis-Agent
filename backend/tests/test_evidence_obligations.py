"""Hermetic tests for Ground Truth to Evidence-obligation translation."""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from app.diagnosis import DiagnosisStatus
from app.evaluation import (
    EvidenceObligation,
    EvidenceObligationKind,
    EvaluationValidationError,
    GroundTruthCase,
    build_evidence_obligations,
    derive_evidence_obligation_id,
)
from app.evaluation.loader import load_ground_truth_cases


ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = ROOT / "warehouse" / "ground_truth.json"


class TestEvidenceObligations(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_ground_truth_cases(GROUND_TRUTH)

    def test_real_cases_have_expected_count_order_and_ids(self) -> None:
        canonical, traffic, no_anomaly = (
            build_evidence_obligations(case) for case in self.cases
        )

        self.assertEqual(len(canonical), 9)
        self.assertEqual(
            [(item.kind, item.metric, item.dimension, item.dimension_value) for item in canonical],
            [
                (EvidenceObligationKind.TARGET_SUPPORTING, "sales", None, None),
                (EvidenceObligationKind.DRIVER_SUPPORTING, "conversion_rate", None, None),
                (EvidenceObligationKind.STABLE_METRIC, "aov", None, None),
                (EvidenceObligationKind.STABLE_METRIC, "sessions", None, None),
                (EvidenceObligationKind.NEGATIVE_CONTROL, None, "marketplace", "DE"),
                (EvidenceObligationKind.NEGATIVE_CONTROL, None, "marketplace", "UK"),
                (EvidenceObligationKind.NEGATIVE_CONTROL, None, "asin", "ASIN-B"),
                (EvidenceObligationKind.NEGATIVE_CONTROL, None, "asin", "ASIN-C"),
                (EvidenceObligationKind.NEGATIVE_CONTROL, None, "traffic_source", "Organic"),
            ],
        )
        self.assertEqual(
            [item.obligation_id for item in canonical],
            [
                "obligation:target_supporting:sales",
                "obligation:driver_supporting:conversion_rate",
                "obligation:stable_metric:aov",
                "obligation:stable_metric:sessions",
                "obligation:negative_control:marketplace:DE",
                "obligation:negative_control:marketplace:UK",
                "obligation:negative_control:asin:ASIN-B",
                "obligation:negative_control:asin:ASIN-C",
                "obligation:negative_control:traffic_source:Organic",
            ],
        )

        self.assertEqual(len(traffic), 9)
        self.assertEqual(
            [item.obligation_id for item in traffic[:4]],
            [
                "obligation:target_supporting:sales",
                "obligation:driver_supporting:sessions",
                "obligation:stable_metric:aov",
                "obligation:stable_metric:conversion_rate",
            ],
        )

        self.assertEqual(len(no_anomaly), 13)
        self.assertEqual(
            [item.obligation_id for item in no_anomaly[:5]],
            [
                "obligation:stable_metric:sales",
                "obligation:stable_metric:orders",
                "obligation:stable_metric:sessions",
                "obligation:stable_metric:conversion_rate",
                "obligation:stable_metric:aov",
            ],
        )
        self.assertTrue(all(item.kind != EvidenceObligationKind.TARGET_SUPPORTING for item in no_anomaly))
        self.assertTrue(all(item.kind != EvidenceObligationKind.DRIVER_SUPPORTING for item in no_anomaly))

    def test_obligation_is_deeply_immutable_and_id_is_model_checked(self) -> None:
        obligation = EvidenceObligation(
            obligation_id="obligation:negative_control:marketplace:DE",
            kind=EvidenceObligationKind.NEGATIVE_CONTROL,
            dimension="marketplace",
            dimension_value="DE",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            obligation.dimension_value = "UK"  # type: ignore[misc]
        with self.assertRaises(EvaluationValidationError):
            EvidenceObligation(
                obligation_id="obligation:negative_control:marketplace:UK",
                kind=EvidenceObligationKind.NEGATIVE_CONTROL,
                dimension="marketplace",
                dimension_value="DE",
            )

    def test_model_rejects_illegal_component_combinations_and_colons(self) -> None:
        invalid = [
            dict(
                obligation_id="obligation:target_supporting:sales",
                kind=EvidenceObligationKind.TARGET_SUPPORTING,
                metric=None,
            ),
            dict(
                obligation_id="obligation:target_supporting:sales",
                kind=EvidenceObligationKind.TARGET_SUPPORTING,
                metric="sales",
                dimension="marketplace",
            ),
            dict(
                obligation_id="obligation:negative_control:marketplace:DE",
                kind=EvidenceObligationKind.NEGATIVE_CONTROL,
                metric="sales",
                dimension="marketplace",
                dimension_value="DE",
            ),
            dict(
                obligation_id="obligation:negative_control:marketplace:DE",
                kind=EvidenceObligationKind.NEGATIVE_CONTROL,
                dimension="marketplace",
                dimension_value=None,
            ),
            dict(
                obligation_id="obligation:stable_metric:sales:forged",
                kind=EvidenceObligationKind.STABLE_METRIC,
                metric="sales:forged",
            ),
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(EvaluationValidationError):
                EvidenceObligation(**kwargs)  # type: ignore[arg-type]

    def test_derive_function_is_deterministic_and_rejects_ambiguous_input(self) -> None:
        self.assertEqual(
            derive_evidence_obligation_id(
                EvidenceObligationKind.STABLE_METRIC,
                metric=" sessions ",
            ),
            "obligation:stable_metric:sessions",
        )
        with self.assertRaises(EvaluationValidationError):
            derive_evidence_obligation_id(
                EvidenceObligationKind.NEGATIVE_CONTROL,
                dimension="marketplace",
                dimension_value="DE:forged",
            )
        with self.assertRaises(EvaluationValidationError):
            derive_evidence_obligation_id("stable_metric", metric="sales")  # type: ignore[arg-type]

    def test_builder_rejects_wrong_case_type_and_does_not_read_runtime_or_files(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            build_evidence_obligations(object())  # type: ignore[arg-type]

        source = (ROOT / "backend" / "app" / "evaluation" / "evidence_obligations.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("agent_runtime", source)
        self.assertNotIn("psycopg", source)
        self.assertNotIn("ground_truth.json", source)
        self.assertNotIn("load_ground_truth_cases", source)


if __name__ == "__main__":
    unittest.main()
