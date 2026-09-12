"""Hermetic tests for ManifestEvaluationRunSet and run identity reconciliation."""

from __future__ import annotations

import datetime
from types import MappingProxyType
import unittest

from app.diagnosis import DiagnosisStatus
from app.evaluation import (
    EvaluationManifest,
    EvaluationRunOutcome,
    EvaluationRunRecord,
    EvaluationRunStatus,
    EvaluationValidationError,
    GroundTruthCase,
    ManifestEvaluationRunSet,
)


NOW = datetime.datetime(2026, 2, 2, 12, tzinfo=datetime.timezone.utc)


def make_case(
    case_id: str,
    *,
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED,
) -> GroundTruthCase:
    diagnosed = status == DiagnosisStatus.DIAGNOSED
    return GroundTruthCase(
        case_id=case_id,
        scenario=case_id,
        target_metric="sales",
        status=status,
        primary_driver="conversion_rate" if diagnosed else None,
        affected_scope=(
            {
                "marketplace": "US",
                "asin": "ASIN-A",
                "traffic_source": "Ads",
            }
            if diagnosed
            else {}
        ),
        expected_stable_metrics=("sessions", "aov"),
        negative_controls={
            "marketplaces": ("DE", "UK"),
            "asins": ("ASIN-B", "ASIN-C"),
            "traffic_sources": ("Organic",),
        },
        causal_boundary="Data contribution only; external cause is unproven.",
    )


def make_outcome(
    case_id: str,
    status: EvaluationRunStatus = EvaluationRunStatus.RUNTIME_FAILURE,
    *,
    failure_code: str | None = "runtime_error",
) -> EvaluationRunOutcome:
    return EvaluationRunOutcome(
        case_id=case_id,
        status=status,
        tool_calls_attempted=0,
        tool_calls_succeeded=0,
        max_tool_calls=8,
        turns_count=1,
        max_turns=4,
        failure_code=failure_code,
    )


def make_record(
    run_id: str,
    case_id: str,
    status: EvaluationRunStatus = EvaluationRunStatus.RUNTIME_FAILURE,
) -> EvaluationRunRecord:
    return EvaluationRunRecord(
        run_id=run_id,
        case=make_case(case_id),
        outcome=make_outcome(case_id, status=status),
    )


def make_manifest(
    run_counts_by_case: dict[str, int],
    *,
    manifest_id: str = "manifest-test-001",
) -> EvaluationManifest:
    return EvaluationManifest(
        manifest_id=manifest_id,
        model_id="gpt-4o-mini",
        prompt="Analyze sales drop",
        metric_config_version="v1.0.0",
        dataset_version="v2.1.0",
        run_counts_by_case=run_counts_by_case,
        created_at=NOW,
    )


class TestManifestEvaluationRunSet(unittest.TestCase):
    def test_single_case_single_run_reconciles_successfully(self) -> None:
        manifest = make_manifest({"case-001": 1})
        record = make_record("run-001", "case-001")

        run_set = ManifestEvaluationRunSet(manifest, [record])

        self.assertIs(run_set.manifest, manifest)
        self.assertEqual(run_set.records, (record,))
        self.assertEqual(dict(run_set.actual_run_counts_by_case), {"case-001": 1})
        self.assertIsInstance(run_set.actual_run_counts_by_case, MappingProxyType)

    def test_multiple_cases_with_multiple_runs_reconciles_successfully(self) -> None:
        manifest = make_manifest({"case-alpha": 2, "case-beta": 3})
        records = [
            make_record("run-a1", "case-alpha"),
            make_record("run-b1", "case-beta"),
            make_record("run-a2", "case-alpha"),
            make_record("run-b2", "case-beta"),
            make_record("run-b3", "case-beta"),
        ]

        run_set = ManifestEvaluationRunSet(manifest, records)

        self.assertEqual(len(run_set.records), 5)
        self.assertEqual(
            dict(run_set.actual_run_counts_by_case),
            {"case-alpha": 2, "case-beta": 3},
        )
        self.assertEqual(
            tuple(run_set.actual_run_counts_by_case.keys()),
            ("case-alpha", "case-beta"),
        )

    def test_actual_run_counts_order_preserves_manifest_declaration_order(self) -> None:
        manifest = make_manifest({"case-z": 1, "case-a": 2, "case-m": 1})
        records = [
            make_record("run-1", "case-a"),
            make_record("run-2", "case-m"),
            make_record("run-3", "case-z"),
            make_record("run-4", "case-a"),
        ]

        run_set = ManifestEvaluationRunSet(manifest, records)

        self.assertEqual(
            tuple(run_set.actual_run_counts_by_case.keys()),
            ("case-z", "case-a", "case-m"),
        )
        self.assertEqual(
            tuple(run_set.actual_run_counts_by_case.values()),
            (1, 2, 1),
        )

    def test_duplicate_run_id_rejected(self) -> None:
        manifest = make_manifest({"case-001": 2})
        records = [
            make_record("run-dup", "case-001"),
            make_record("run-dup", "case-001"),
        ]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records)

    def test_duplicate_run_id_after_whitespace_trimming_rejected(self) -> None:
        manifest = make_manifest({"case-001": 2})
        records = [
            make_record("  run-dup  ", "case-001"),
            make_record("run-dup", "case-001"),
        ]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records)

    def test_record_with_blank_or_invalid_run_id_fails_closed(self) -> None:
        case = make_case("case-001")
        outcome = make_outcome("case-001")
        with self.assertRaises(EvaluationValidationError):
            EvaluationRunRecord(run_id="", case=case, outcome=outcome)
        with self.assertRaises(EvaluationValidationError):
            EvaluationRunRecord(run_id="   ", case=case, outcome=outcome)
        with self.assertRaises(EvaluationValidationError):
            EvaluationRunRecord(run_id=None, case=case, outcome=outcome)  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            EvaluationRunRecord(run_id=12345, case=case, outcome=outcome)  # type: ignore[arg-type]

    def test_fewer_runs_than_declared_rejected(self) -> None:
        manifest = make_manifest({"case-001": 3})
        records = [
            make_record("run-1", "case-001"),
            make_record("run-2", "case-001"),
        ]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records)

    def test_more_runs_than_declared_rejected(self) -> None:
        manifest = make_manifest({"case-001": 2})
        records = [
            make_record("run-1", "case-001"),
            make_record("run-2", "case-001"),
            make_record("run-3", "case-001"),
        ]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records)

    def test_undeclared_case_in_records_rejected(self) -> None:
        manifest = make_manifest({"case-001": 1})
        records = [
            make_record("run-1", "case-001"),
            make_record("run-2", "case-undeclared"),
        ]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records)

    def test_missing_declared_case_in_records_rejected(self) -> None:
        manifest = make_manifest({"case-001": 1, "case-missing": 1})
        records = [
            make_record("run-1", "case-001"),
        ]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records)

    def test_deep_immutability_and_defensive_snapshot(self) -> None:
        manifest = make_manifest({"case-001": 1})
        rec = make_record("run-1", "case-001")
        records_list = [rec]

        run_set = ManifestEvaluationRunSet(manifest, records_list)

        # Mutating the original input list must not affect run_set.records
        records_list.clear()
        self.assertEqual(len(run_set.records), 1)
        self.assertEqual(run_set.records[0], rec)

        # Mutating actual_run_counts_by_case must raise TypeError
        with self.assertRaises(TypeError):
            run_set.actual_run_counts_by_case["case-001"] = 99  # type: ignore[index]

        # Mutating fields on frozen dataclass must raise AttributeError or FrozenInstanceError
        with self.assertRaises((AttributeError, Exception)):
            run_set.records = ()  # type: ignore[misc]

    def test_invalid_manifest_type_rejected(self) -> None:
        record = make_record("run-1", "case-001")
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(None, [record])  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet("manifest-id", [record])  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet({"run_counts_by_case": {}}, [record])  # type: ignore[arg-type]

    def test_invalid_records_type_and_contents_rejected(self) -> None:
        manifest = make_manifest({"case-001": 1})
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, ())
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, "not-a-sequence")  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, 123)  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, [object()])  # type: ignore[list-item]

    def test_cannot_pass_actual_run_counts_by_case_directly(self) -> None:
        manifest = make_manifest({"case-001": 1})
        record = make_record("run-1", "case-001")
        with self.assertRaises(TypeError):
            ManifestEvaluationRunSet(  # type: ignore[call-arg]
                manifest=manifest,
                records=[record],
                actual_run_counts_by_case={"case-001": 1},
            )

    def test_run_set_equality_and_repr(self) -> None:
        manifest = make_manifest({"case-001": 1})
        rec1 = make_record("run-1", "case-001")
        set1 = ManifestEvaluationRunSet(manifest, [rec1])
        set2 = ManifestEvaluationRunSet(manifest, [rec1])

        self.assertEqual(set1, set2)
        self.assertIn("ManifestEvaluationRunSet", repr(set1))
        self.assertIn("run-1", repr(set1))


if __name__ == "__main__":
    unittest.main()
