"""Hermetic unit tests for RepeatedRunEvaluationReport and repeated aggregate functions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import datetime
from decimal import Decimal
import unittest

from app.analytics.models import DateRange
from app.diagnosis import (
    Diagnosis,
    DiagnosisChange,
    DiagnosisComposition,
    DiagnosisStatus,
)
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.evaluation import (
    CaseRepeatedSummary,
    EvaluationManifest,
    EvaluationRunOutcome,
    EvaluationRunRecord,
    EvaluationRunStatus,
    EvaluationValidationError,
    GroundTruthCase,
    ManifestEvaluationRunSet,
    RepeatedRunEvaluationReport,
    aggregate_manifest_evaluation_run_set,
)
from app.observations import Observation, ObservationStatus


NOW = datetime.datetime(2026, 2, 2, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 2, 2), datetime.date(2026, 2, 2))
BASELINE = DateRange(datetime.date(2026, 1, 26), datetime.date(2026, 2, 1))


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


def make_observation(
    observation_id: str,
    metric: str,
    status: ObservationStatus,
    *,
    filters: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
) -> Observation:
    failed = status == ObservationStatus.FAILED
    insufficient = status == ObservationStatus.INSUFFICIENT_EVIDENCE
    return Observation(
        observation_id=observation_id,
        tool_name="query_metric",
        tool_call_id=f"call:{observation_id}",
        metric=metric,
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters=filters or {},
        group_by=tuple((dimensions or {}).keys()),
        dimensions=dimensions or {},
        current_value=None if failed else Decimal("80"),
        baseline_value=None if failed else Decimal("100"),
        relative_change=None if failed or insufficient else (
            Decimal("-0.20")
            if status == ObservationStatus.ANOMALOUS
            else Decimal("0.01")
        ),
        unit="ratio" if metric == "conversion_rate" else "usd",
        sample_size=None if failed else Decimal("500"),
        source_status="failed" if failed else (
            "insufficient_data" if insufficient else "ok"
        ),
        status=status,
        query_or_result_reference=f"ref:{observation_id}",
        created_at=NOW,
        error_code="QUERY_FAILED" if failed else None,
        error_message="query failed" if failed else None,
    )


def make_evidence(
    observation_id: str,
    metric: str,
    status: ObservationStatus,
    *,
    role: EvidenceRole,
    filters: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
):
    return promote_observation_to_evidence(
        make_observation(
            observation_id,
            metric,
            status,
            filters=filters,
            dimensions=dimensions,
        ),
        role=role,
    )


def diagnosed_composition(case_id: str, run_id: str) -> DiagnosisComposition:
    target = make_evidence(
        f"{run_id}-target",
        "sales",
        ObservationStatus.ANOMALOUS,
        role=EvidenceRole.SUPPORTING,
    )
    driver = make_evidence(
        f"{run_id}-driver",
        "conversion_rate",
        ObservationStatus.ANOMALOUS,
        role=EvidenceRole.SUPPORTING,
        filters={"marketplace": "US", "asin": "ASIN-A"},
        dimensions={"traffic_source": "Ads"},
    )
    control = make_evidence(
        f"{run_id}-control",
        "sessions",
        ObservationStatus.NORMAL,
        role=EvidenceRole.NEGATIVE_CONTROL,
        dimensions={"marketplace": "DE"},
    )
    items = (target, driver, control)
    diagnosis = Diagnosis(
        diagnosis_id=f"diag:{run_id}",
        status=DiagnosisStatus.DIAGNOSED,
        target_metric="sales",
        change=DiagnosisChange(
            current_value=target.current_value,
            baseline_value=target.baseline_value,
            relative_change=target.relative_change,
            unit=target.unit,
            evidence_id=target.evidence_id,
        ),
        primary_driver="conversion_rate",
        affected_scope={
            "marketplace": "US",
            "asin": "ASIN-A",
            "traffic_source": "Ads",
        },
        evidence_ids=tuple(item.evidence_id for item in items),
        confidence=Decimal("0.9"),
        limitations=("Synthetic benchmark only.",),
        created_at=NOW,
    )
    return DiagnosisComposition(evidence=items, diagnosis=diagnosis)


def terminal_composition(
    case_id: str,
    run_id: str,
    status: DiagnosisStatus,
) -> DiagnosisComposition:
    diagnosis = Diagnosis(
        diagnosis_id=f"diag:{run_id}",
        status=status,
        target_metric="sales",
        change=None,
        primary_driver=None,
        affected_scope={},
        evidence_ids=(),
        confidence=None,
        limitations=("Run terminated before diagnosis.",),
        created_at=NOW,
    )
    return DiagnosisComposition(evidence=(), diagnosis=diagnosis)


def make_outcome(
    case_id: str,
    status: EvaluationRunStatus,
    attempted: int,
    succeeded: int,
    failure_code: str | None = None,
) -> EvaluationRunOutcome:
    return EvaluationRunOutcome(
        case_id=case_id,
        status=status,
        tool_calls_attempted=attempted,
        tool_calls_succeeded=succeeded,
        max_tool_calls=8,
        turns_count=2,
        max_turns=4,
        failure_code=failure_code,
    )


def make_manifest(
    run_counts_by_case: dict[str, int],
    *,
    manifest_id: str = "manifest-test-repeated",
) -> EvaluationManifest:
    return EvaluationManifest(
        manifest_id=manifest_id,
        model_id="gpt-4o-mini",
        prompt="Investigate metric anomaly.",
        metric_config_version="v1.0.0",
        dataset_version="v2.1.0",
        run_counts_by_case=run_counts_by_case,
        created_at=NOW,
    )


class TestEvaluationRepeatedAggregate(unittest.TestCase):
    def test_single_case_multiple_successful_runs(self) -> None:
        """Verify repeated aggregation for 3 fully successful runs of one case."""
        case = make_case("case-canonical")
        records = []
        for i in range(1, 4):
            run_id = f"run-canonical-{i}"
            records.append(
                EvaluationRunRecord(
                    run_id=run_id,
                    case=case,
                    outcome=make_outcome("case-canonical", EvaluationRunStatus.COMPLETED, attempted=3, succeeded=3),
                    composition=diagnosed_composition("case-canonical", run_id),
                )
            )

        manifest = make_manifest({"case-canonical": 3})
        run_set = ManifestEvaluationRunSet(manifest, records)

        report = aggregate_manifest_evaluation_run_set(run_set)

        self.assertIsInstance(report, RepeatedRunEvaluationReport)
        self.assertEqual(report.manifest_id, "manifest-test-repeated")
        self.assertEqual(report.total_cases, 1)
        self.assertEqual(report.total_runs, 3)
        self.assertEqual(report.overall_run_completion_rate, Decimal("1"))
        self.assertEqual(report.macro_driver_accuracy, Decimal("1"))
        self.assertEqual(report.macro_scope_accuracy, Decimal("1"))
        self.assertEqual(report.macro_exact_match_rate, Decimal("1"))

        self.assertEqual(len(report.case_summaries), 1)
        summary = report.case_summaries[0]
        self.assertEqual(summary.case_id, "case-canonical")
        self.assertEqual(summary.total_runs, 3)
        self.assertEqual(summary.completed_runs, 3)
        self.assertEqual(summary.run_completion_rate, Decimal("1"))
        self.assertEqual(summary.mean_status_accuracy, Decimal("1"))
        self.assertEqual(summary.mean_target_metric_accuracy, Decimal("1"))
        self.assertEqual(summary.mean_driver_accuracy, Decimal("1"))
        self.assertEqual(summary.mean_scope_accuracy, Decimal("1"))
        self.assertEqual(summary.mean_exact_match_rate, Decimal("1"))
        self.assertEqual(summary.mean_tool_calls, Decimal("3"))
        self.assertEqual(summary.mean_tool_success_rate, Decimal("1"))
        self.assertEqual(summary.budget_exhaustion_rate, Decimal("0"))
        self.assertIsNotNone(summary.mean_evidence_precision)
        self.assertGreater(summary.mean_evidence_coverage, Decimal("0"))

    def test_single_case_mixed_runs_partial_failure(self) -> None:
        """Verify CaseRepeatedSummary handles COMPLETED, BUDGET_EXHAUSTED, and RUNTIME_FAILURE runs."""
        case = make_case("case-mixed")
        r1 = EvaluationRunRecord(
            run_id="run-1",
            case=case,
            outcome=make_outcome("case-mixed", EvaluationRunStatus.COMPLETED, attempted=2, succeeded=2),
            composition=diagnosed_composition("case-mixed", "run-1"),
        )
        r2 = EvaluationRunRecord(
            run_id="run-2",
            case=case,
            outcome=make_outcome("case-mixed", EvaluationRunStatus.BUDGET_EXHAUSTED, attempted=8, succeeded=8, failure_code="budget"),
            composition=terminal_composition("case-mixed", "run-2", DiagnosisStatus.BUDGET_EXHAUSTED),
        )
        r3 = EvaluationRunRecord(
            run_id="run-3",
            case=case,
            outcome=make_outcome("case-mixed", EvaluationRunStatus.RUNTIME_FAILURE, attempted=1, succeeded=0, failure_code="timeout"),
            composition=None,
        )

        manifest = make_manifest({"case-mixed": 3})
        run_set = ManifestEvaluationRunSet(manifest, [r1, r2, r3])

        report = aggregate_manifest_evaluation_run_set(run_set)
        summary = report.case_summaries[0]

        self.assertEqual(summary.total_runs, 3)
        self.assertEqual(summary.completed_runs, 1)
        self.assertEqual(summary.run_completion_rate, Decimal("1") / Decimal("3"))
        # 1 out of 3 runs had correct driver/status/target/exact
        self.assertEqual(summary.mean_driver_accuracy, Decimal("1") / Decimal("3"))
        self.assertEqual(summary.mean_status_accuracy, Decimal("1") / Decimal("3"))
        self.assertEqual(summary.mean_exact_match_rate, Decimal("1") / Decimal("3"))
        # Tool calls: r1=2, r2=8, r3=1 -> sum=11, mean=11/3
        self.assertEqual(summary.mean_tool_calls, Decimal("11") / Decimal("3"))
        # Tool success: succeeded=2+8+0=10, attempted=2+8+1=11 -> 10/11
        self.assertEqual(summary.mean_tool_success_rate, Decimal("10") / Decimal("11"))
        # Budget exhausted: 1 out of 3
        self.assertEqual(summary.budget_exhaustion_rate, Decimal("1") / Decimal("3"))

    def test_multi_case_multiple_runs_and_macro_averages(self) -> None:
        """Verify macro statistics across multiple cases with unequal run counts."""
        case_a = make_case("case-a")
        case_b = make_case("case-b")

        # Case A: 2 runs, both 100% correct
        a_runs = [
            EvaluationRunRecord(
                run_id=f"run-a-{i}",
                case=case_a,
                outcome=make_outcome("case-a", EvaluationRunStatus.COMPLETED, attempted=2, succeeded=2),
                composition=diagnosed_composition("case-a", f"run-a-{i}"),
            )
            for i in (1, 2)
        ]
        # Case B: 2 runs, 1 completed (100% correct), 1 budget exhausted (0% correct)
        b_runs = [
            EvaluationRunRecord(
                run_id="run-b-1",
                case=case_b,
                outcome=make_outcome("case-b", EvaluationRunStatus.COMPLETED, attempted=2, succeeded=2),
                composition=diagnosed_composition("case-b", "run-b-1"),
            ),
            EvaluationRunRecord(
                run_id="run-b-2",
                case=case_b,
                outcome=make_outcome("case-b", EvaluationRunStatus.BUDGET_EXHAUSTED, attempted=8, succeeded=8, failure_code="budget"),
                composition=terminal_composition("case-b", "run-b-2", DiagnosisStatus.BUDGET_EXHAUSTED),
            ),
        ]

        manifest = make_manifest({"case-a": 2, "case-b": 2})
        run_set = ManifestEvaluationRunSet(manifest, [*a_runs, *b_runs])

        report = aggregate_manifest_evaluation_run_set(run_set)
        self.assertEqual(report.total_cases, 2)
        self.assertEqual(report.total_runs, 4)

        summary_a = report.case_summaries[0]
        summary_b = report.case_summaries[1]

        self.assertEqual(summary_a.case_id, "case-a")
        self.assertEqual(summary_a.mean_driver_accuracy, Decimal("1"))

        self.assertEqual(summary_b.case_id, "case-b")
        self.assertEqual(summary_b.mean_driver_accuracy, Decimal("0.5"))

        # Macro driver accuracy = (1.0 + 0.5) / 2 = 0.75
        self.assertEqual(report.macro_driver_accuracy, Decimal("0.75"))
        self.assertEqual(report.macro_exact_match_rate, Decimal("0.75"))
        # Overall completion: 3 completed out of 4 runs = 0.75
        self.assertEqual(report.overall_run_completion_rate, Decimal("0.75"))

    def test_zero_denominator_precision_and_tool_success(self) -> None:
        """Verify mean_evidence_precision and mean_tool_success_rate are None when denominators are zero."""
        case = make_case("case-empty")
        # Run with 0 tool calls attempted and no evidence citations
        record = EvaluationRunRecord(
            run_id="run-empty-1",
            case=case,
            outcome=make_outcome("case-empty", EvaluationRunStatus.RUNTIME_FAILURE, attempted=0, succeeded=0, failure_code="init_failed"),
            composition=None,
        )

        manifest = make_manifest({"case-empty": 1})
        run_set = ManifestEvaluationRunSet(manifest, [record])

        report = aggregate_manifest_evaluation_run_set(run_set)
        summary = report.case_summaries[0]

        self.assertIsNone(summary.mean_evidence_precision)
        self.assertIsNone(summary.mean_tool_success_rate)
        self.assertEqual(summary.mean_tool_calls, Decimal("0"))
        self.assertEqual(summary.completed_runs, 0)
        self.assertEqual(summary.run_completion_rate, Decimal("0"))

    def test_manifest_case_order_is_strictly_preserved(self) -> None:
        """Verify case_summaries preserves the exact ordering of manifest.run_counts_by_case."""
        case_1 = make_case("case-zeta")
        case_2 = make_case("case-alpha")
        case_3 = make_case("case-beta")

        r1 = EvaluationRunRecord("rz", case_1, make_outcome("case-zeta", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "err"))
        r2 = EvaluationRunRecord("ra", case_2, make_outcome("case-alpha", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "err"))
        r3 = EvaluationRunRecord("rb", case_3, make_outcome("case-beta", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "err"))

        # Declare arbitrary order: zeta, alpha, beta
        manifest = make_manifest({"case-zeta": 1, "case-alpha": 1, "case-beta": 1})
        # Feed in shuffled order: alpha, beta, zeta
        run_set = ManifestEvaluationRunSet(manifest, [r2, r3, r1])

        report = aggregate_manifest_evaluation_run_set(run_set)
        ordered_ids = tuple(s.case_id for s in report.case_summaries)
        self.assertEqual(ordered_ids, ("case-zeta", "case-alpha", "case-beta"))

    def test_immutability_and_tampering_protection(self) -> None:
        """Verify models are frozen dataclasses and collections are immutable tuples."""
        case = make_case("case-freeze")
        rec = EvaluationRunRecord("r1", case, make_outcome("case-freeze", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "err"))
        manifest = make_manifest({"case-freeze": 1})
        run_set = ManifestEvaluationRunSet(manifest, [rec])
        report = aggregate_manifest_evaluation_run_set(run_set)

        self.assertIsInstance(report.case_summaries, tuple)
        with self.assertRaises(FrozenInstanceError):
            report.total_cases = 999  # type: ignore[misc]

        summary = report.case_summaries[0]
        with self.assertRaises(FrozenInstanceError):
            summary.total_runs = 999  # type: ignore[misc]

    def test_case_repeated_summary_invariants_validation(self) -> None:
        """Verify CaseRepeatedSummary rejects invalid types, values, and inconsistencies."""
        valid_kwargs = dict(
            case_id="case-1",
            total_runs=2,
            completed_runs=2,
            run_completion_rate=Decimal("1"),
            mean_status_accuracy=Decimal("1"),
            mean_target_metric_accuracy=Decimal("1"),
            mean_driver_accuracy=Decimal("1"),
            mean_scope_accuracy=Decimal("1"),
            mean_exact_match_rate=Decimal("1"),
            mean_evidence_coverage=Decimal("1"),
            mean_evidence_precision=Decimal("1"),
            mean_tool_success_rate=Decimal("1"),
            mean_tool_calls=Decimal("2"),
            budget_exhaustion_rate=Decimal("0"),
        )

        # Non-positive total_runs
        with self.assertRaises(EvaluationValidationError):
            CaseRepeatedSummary(**{**valid_kwargs, "total_runs": 0})

        # completed_runs > total_runs
        with self.assertRaises(EvaluationValidationError):
            CaseRepeatedSummary(**{**valid_kwargs, "completed_runs": 3})

        # Inconsistent run_completion_rate
        with self.assertRaises(EvaluationValidationError):
            CaseRepeatedSummary(**{**valid_kwargs, "run_completion_rate": Decimal("0.5")})

        # Non-finite rate
        with self.assertRaises(EvaluationValidationError):
            CaseRepeatedSummary(**{**valid_kwargs, "mean_driver_accuracy": Decimal("NaN")})

        # Negative mean_tool_calls
        with self.assertRaises(EvaluationValidationError):
            CaseRepeatedSummary(**{**valid_kwargs, "mean_tool_calls": Decimal("-1")})

        # Empty case_id
        with self.assertRaises(EvaluationValidationError):
            CaseRepeatedSummary(**{**valid_kwargs, "case_id": "   "})

    def test_repeated_run_report_invariants_validation(self) -> None:
        """Verify RepeatedRunEvaluationReport rejects inconsistent totals, empty summaries, and bad rates."""
        summary = CaseRepeatedSummary(
            case_id="case-1",
            total_runs=2,
            completed_runs=2,
            run_completion_rate=Decimal("1"),
            mean_status_accuracy=Decimal("1"),
            mean_target_metric_accuracy=Decimal("1"),
            mean_driver_accuracy=Decimal("1"),
            mean_scope_accuracy=Decimal("1"),
            mean_exact_match_rate=Decimal("1"),
            mean_evidence_coverage=Decimal("1"),
            mean_evidence_precision=Decimal("1"),
            mean_tool_success_rate=Decimal("1"),
            mean_tool_calls=Decimal("2"),
            budget_exhaustion_rate=Decimal("0"),
        )

        valid_report_kwargs = dict(
            manifest_id="manifest-1",
            case_summaries=(summary,),
            total_cases=1,
            total_runs=2,
            macro_driver_accuracy=Decimal("1"),
            macro_scope_accuracy=Decimal("1"),
            macro_exact_match_rate=Decimal("1"),
            overall_run_completion_rate=Decimal("1"),
        )

        # Empty case_summaries
        with self.assertRaises(EvaluationValidationError):
            RepeatedRunEvaluationReport(**{**valid_report_kwargs, "case_summaries": ()})

        # Mismatched total_cases
        with self.assertRaises(EvaluationValidationError):
            RepeatedRunEvaluationReport(**{**valid_report_kwargs, "total_cases": 2})

        # Mismatched total_runs
        with self.assertRaises(EvaluationValidationError):
            RepeatedRunEvaluationReport(**{**valid_report_kwargs, "total_runs": 5})

        # Inconsistent macro_driver_accuracy
        with self.assertRaises(EvaluationValidationError):
            RepeatedRunEvaluationReport(**{**valid_report_kwargs, "macro_driver_accuracy": Decimal("0.5")})

        # Inconsistent overall_run_completion_rate
        with self.assertRaises(EvaluationValidationError):
            RepeatedRunEvaluationReport(**{**valid_report_kwargs, "overall_run_completion_rate": Decimal("0.8")})

    def test_aggregate_rejects_non_manifest_run_set(self) -> None:
        """Verify aggregate_manifest_evaluation_run_set fails closed on invalid input type."""
        with self.assertRaises(EvaluationValidationError):
            aggregate_manifest_evaluation_run_set("not_a_run_set")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
