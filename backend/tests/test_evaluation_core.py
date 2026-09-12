"""Hermetic tests for Ground Truth loading and deterministic core scoring."""

from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.diagnosis import Diagnosis, DiagnosisChange, DiagnosisStatus
from app.evaluation import (
    CoreCaseScore,
    EvaluationConfigError,
    EvaluationValidationError,
    GroundTruthCase,
    load_ground_truth_cases,
    score_core_case,
)


ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = ROOT / "warehouse" / "ground_truth.json"
NOW = datetime.datetime(2026, 1, 31, 12, tzinfo=datetime.timezone.utc)


def diagnosis(
    *,
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED,
    target_metric: str = "sales",
    primary_driver: str | None = "conversion_rate",
    affected_scope: dict[str, str] | None = None,
) -> Diagnosis:
    cited_id = "evidence:evaluation-target:supporting"
    return Diagnosis(
        diagnosis_id="diag:evaluation-test",
        status=status,
        target_metric=target_metric,
        change=DiagnosisChange(
            current_value=Decimal("80"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("-0.20"),
            unit="usd",
            evidence_id=cited_id,
        ),
        primary_driver=primary_driver,
        affected_scope=affected_scope or {},
        evidence_ids=(cited_id,),
        confidence=Decimal("0.80"),
        limitations=("Evaluation-only synthetic diagnosis.",),
        created_at=NOW,
    )


class TestGroundTruthLoader(unittest.TestCase):
    def test_loads_real_three_case_development_set(self) -> None:
        cases = load_ground_truth_cases(GROUND_TRUTH)
        self.assertEqual(len(cases), 3)
        self.assertEqual(
            [case.case_id for case in cases],
            [
                "canonical_sales_cr_us_asin_a_ads",
                "alternate_sales_sessions_us_asin_a_ads",
                "normal_fluctuation_no_material_anomaly",
            ],
        )
        self.assertEqual(cases[0].status, DiagnosisStatus.DIAGNOSED)
        self.assertEqual(cases[2].status, DiagnosisStatus.NO_MATERIAL_ANOMALY)
        self.assertEqual(dict(cases[0].affected_scope), {
            "marketplace": "US",
            "asin": "ASIN-A",
            "traffic_source": "Ads",
        })

    def test_models_are_deeply_immutable_and_isolate_sources(self) -> None:
        scope = {"marketplace": "US", "asin": "ASIN-A", "traffic_source": "Ads"}
        stable = ["sessions", "aov"]
        controls = {
            "marketplaces": ["DE", "UK"],
            "asins": ["ASIN-B", "ASIN-C"],
            "traffic_sources": ["Organic"],
        }
        case = GroundTruthCase(
            case_id="case-immutable",
            scenario="scenario-immutable",
            target_metric="sales",
            status=DiagnosisStatus.DIAGNOSED,
            primary_driver="conversion_rate",
            affected_scope=scope,
            expected_stable_metrics=stable,
            negative_controls=controls,
            causal_boundary="Data-level localization only.",
        )
        scope["marketplace"] = "DE"
        stable.clear()
        controls["marketplaces"].clear()
        self.assertEqual(case.affected_scope["marketplace"], "US")
        self.assertEqual(case.expected_stable_metrics, ("sessions", "aov"))
        self.assertEqual(case.negative_controls["marketplaces"], ("DE", "UK"))
        with self.assertRaises(TypeError):
            case.affected_scope["marketplace"] = "DE"
        with self.assertRaises(TypeError):
            case.negative_controls["marketplaces"] = ("US",)

    def test_rejects_string_pseudo_sequences_and_duplicate_values(self) -> None:
        base = dict(
            case_id="case-invalid-seq",
            scenario="scenario-invalid-seq",
            target_metric="sales",
            status=DiagnosisStatus.DIAGNOSED,
            primary_driver="conversion_rate",
            affected_scope={"marketplace": "US"},
            expected_stable_metrics=["sessions"],
            negative_controls={
                "marketplaces": ["DE"],
                "asins": ["ASIN-B"],
                "traffic_sources": ["Organic"],
            },
            causal_boundary="boundary",
        )
        invalid = [
            {"expected_stable_metrics": "sessions"},
            {"negative_controls": {**base["negative_controls"], "asins": "ASIN-B"}},
            {"expected_stable_metrics": ["sessions", "sessions"]},
            {"negative_controls": {**base["negative_controls"], "asins": ["ASIN-B", "ASIN-B"]}},
        ]
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(EvaluationValidationError):
                GroundTruthCase(**{**base, **override})

    def test_rejects_missing_extra_and_invalid_control_or_scope_keys(self) -> None:
        valid = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))[0]
        cases = [
            {key: value for key, value in valid.items() if key != "scenario"},
            {**valid, "unexpected": True},
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
                    json.dump([raw], handle)
                    path = Path(handle.name)
                try:
                    with self.assertRaises(EvaluationConfigError):
                        load_ground_truth_cases(path)
                finally:
                    path.unlink()

        for field, value in (
            ("affected_scope", {"country": "US"}),
            ("negative_controls", {
                "marketplaces": ["DE"],
                "asins": ["ASIN-B"],
                "unexpected": ["Organic"],
            }),
        ):
            with self.subTest(field=field):
                with self.assertRaises(EvaluationValidationError):
                    GroundTruthCase(**{**valid, "status": DiagnosisStatus.DIAGNOSED, field: value})

    def test_rejects_status_invariants_and_duplicate_ids_or_scenarios(self) -> None:
        raw_cases = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
        raw_cases[1]["case_id"] = raw_cases[0]["case_id"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(raw_cases, handle)
            duplicate_id_path = Path(handle.name)
        try:
            with self.assertRaises(EvaluationConfigError):
                load_ground_truth_cases(duplicate_id_path)
        finally:
            duplicate_id_path.unlink()

        raw_cases = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
        raw_cases[1]["scenario"] = raw_cases[0]["scenario"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(raw_cases, handle)
            duplicate_scenario_path = Path(handle.name)
        try:
            with self.assertRaises(EvaluationConfigError):
                load_ground_truth_cases(duplicate_scenario_path)
        finally:
            duplicate_scenario_path.unlink()

        valid = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))[0]
        invalid_status = {**valid, "status": "budget_exhausted"}
        no_anomaly_with_driver = {
            **json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))[2],
            "primary_driver": "sessions",
        }
        diagnosed_without_scope = {
            **valid,
            "affected_scope": {},
        }
        for raw in (invalid_status, no_anomaly_with_driver, diagnosed_without_scope):
            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
                json.dump([raw], handle)
                path = Path(handle.name)
            try:
                with self.assertRaises(EvaluationConfigError):
                    load_ground_truth_cases(path)
            finally:
                path.unlink()

    def test_loader_rejects_json_shape_io_and_non_json_values(self) -> None:
        invalid_payloads = [
            {"not": "a list"},
            [1],
            [],
        ]
        # Empty top-level lists are structurally valid and should remain usable
        # for a caller that intentionally evaluates an empty set.
        for payload in invalid_payloads[:2]:
            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
                json.dump(payload, handle)
                path = Path(handle.name)
            try:
                with self.assertRaises(EvaluationConfigError):
                    load_ground_truth_cases(path)
            finally:
                path.unlink()
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
            handle.write("[NaN]")
            nan_path = Path(handle.name)
        try:
            with self.assertRaises(EvaluationConfigError):
                load_ground_truth_cases(nan_path)
        finally:
            nan_path.unlink()

        with self.assertRaises(EvaluationConfigError):
            load_ground_truth_cases(ROOT / "warehouse" / "does-not-exist.json")
        with self.assertRaises(EvaluationConfigError):
            load_ground_truth_cases("")


class TestCoreScorer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_ground_truth_cases(GROUND_TRUTH)

    def test_canonical_case_exact_match_has_one_accuracy(self) -> None:
        case = self.cases[0]
        result = score_core_case(
            case,
            diagnosis(
                affected_scope={
                    "marketplace": "US",
                    "asin": "ASIN-A",
                    "traffic_source": "Ads",
                }
            ),
        )
        self.assertTrue(result.exact_match)
        self.assertEqual(result.scope_accuracy, Decimal("1"))
        self.assertEqual(dict(result.scope_correct), {
            "marketplace": True,
            "asin": True,
            "traffic_source": True,
        })
        self.assertTrue(result.no_anomaly_correct)

    def test_driver_and_single_scope_mismatch_are_scored_separately(self) -> None:
        case = self.cases[0]
        wrong = score_core_case(
            case,
            diagnosis(
                primary_driver="sessions",
                affected_scope={
                    "marketplace": "US",
                    "asin": "ASIN-B",
                    "traffic_source": "Ads",
                },
            ),
        )
        self.assertFalse(wrong.driver_correct)
        self.assertEqual(wrong.scope_accuracy, Decimal("2") / Decimal("3"))
        self.assertEqual(dict(wrong.scope_correct), {
            "marketplace": True,
            "asin": False,
            "traffic_source": True,
        })
        self.assertFalse(wrong.exact_match)

    def test_missing_and_extra_scope_keys_are_not_hidden(self) -> None:
        case = self.cases[0]
        missing = score_core_case(
            case,
            diagnosis(affected_scope={"marketplace": "US", "asin": "ASIN-A"}),
        )
        self.assertEqual(missing.scope_accuracy, Decimal("2") / Decimal("3"))
        self.assertFalse(missing.scope_correct["traffic_source"])

        extra = score_core_case(
            case,
            diagnosis(affected_scope={
                "marketplace": "US",
                "asin": "ASIN-A",
                "traffic_source": "Ads",
                "unknown": "value",
            }),
        )
        self.assertEqual(extra.scope_accuracy, Decimal("1"))
        self.assertFalse(extra.exact_match)

    def test_no_anomaly_status_is_scored_as_binary_classification(self) -> None:
        case = self.cases[2]
        correct = score_core_case(
            case,
            diagnosis(
                status=DiagnosisStatus.NO_MATERIAL_ANOMALY,
                primary_driver=None,
                affected_scope={},
            ),
        )
        self.assertTrue(correct.status_correct)
        self.assertTrue(correct.no_anomaly_correct)
        self.assertTrue(correct.exact_match)

        wrong = score_core_case(
            case,
            diagnosis(affected_scope={"marketplace": "US"}),
        )
        self.assertFalse(wrong.status_correct)
        self.assertFalse(wrong.no_anomaly_correct)
        self.assertFalse(wrong.exact_match)

    def test_score_rejects_wrong_types_and_does_not_mutate_inputs(self) -> None:
        case = self.cases[0]
        predicted_scope = {
            "marketplace": "US",
            "asin": "ASIN-A",
            "traffic_source": "Ads",
        }
        predicted = diagnosis(affected_scope=predicted_scope)
        score_core_case(case, predicted)
        predicted_scope["marketplace"] = "DE"
        self.assertEqual(predicted.affected_scope["marketplace"], "US")
        for invalid_case, invalid_diagnosis in ((object(), predicted), (case, object())):
            with self.subTest(invalid_case=invalid_case, invalid_diagnosis=invalid_diagnosis):
                with self.assertRaises(EvaluationValidationError):
                    score_core_case(invalid_case, invalid_diagnosis)

    def test_core_score_mapping_and_accuracy_are_immutable(self) -> None:
        score = score_core_case(
            self.cases[0],
            diagnosis(affected_scope={
                "marketplace": "US",
                "asin": "ASIN-A",
                "traffic_source": "Ads",
            }),
        )
        with self.assertRaises(TypeError):
            score.scope_correct["marketplace"] = False
        with self.assertRaises(EvaluationValidationError):
            CoreCaseScore(
                case_id="x",
                status_correct=True,
                target_metric_correct=True,
                driver_correct=True,
                scope_correct={
                    "marketplace": True,
                    "asin": True,
                    "traffic_source": True,
                },
                scope_accuracy=Decimal("0.5"),
                exact_match=False,
            )


if __name__ == "__main__":
    unittest.main()
