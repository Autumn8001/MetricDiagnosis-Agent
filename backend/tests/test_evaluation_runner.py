"""Hermetic tests for the Evaluation runner contract."""

from __future__ import annotations

import datetime
from decimal import Decimal
import inspect
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
    CoreCaseScore,
    EvidenceCitationScore,
    EvaluationCaseScoreBundle,
    EvaluationRunOutcome,
    EvaluationRunRecord,
    EvaluationRunStatus,
    EvaluationValidationError,
    HermeticEvaluationResult,
    ToolOperationalScore,
    UnifiedEvaluationReport,
    run_hermetic_evaluation,
    score_evaluation_run_record,
)
from app.evaluation import runner as runner_module
from app.evaluation import build_evidence_obligations
from app.observations import Observation, ObservationStatus


NOW = datetime.datetime(2026, 2, 2, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 2, 2), datetime.date(2026, 2, 2))
BASELINE = DateRange(datetime.date(2026, 1, 26), datetime.date(2026, 2, 1))


def make_case(
    case_id: str,
    *,
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED,
) -> object:
    # Keep the helper's return annotation loose so tests can pass each case to
    # the public constructor without importing private runner helpers.
    from app.evaluation import GroundTruthCase

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


def evidence(
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


def diagnosed_composition(case_id: str) -> DiagnosisComposition:
    target = evidence(
        f"{case_id}-target",
        "sales",
        ObservationStatus.ANOMALOUS,
        role=EvidenceRole.SUPPORTING,
    )
    driver = evidence(
        f"{case_id}-driver",
        "conversion_rate",
        ObservationStatus.ANOMALOUS,
        role=EvidenceRole.SUPPORTING,
        filters={"marketplace": "US", "asin": "ASIN-A"},
        dimensions={"traffic_source": "Ads"},
    )
    control = evidence(
        f"{case_id}-control",
        "sessions",
        ObservationStatus.NORMAL,
        role=EvidenceRole.NEGATIVE_CONTROL,
        dimensions={"marketplace": "DE"},
    )
    items = (target, driver, control)
    diagnosis = Diagnosis(
        diagnosis_id=f"diag:{case_id}",
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
    status: DiagnosisStatus,
) -> DiagnosisComposition:
    diagnosis = Diagnosis(
        diagnosis_id=f"diag:{case_id}",
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


def outcome(
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


class TestEvaluationRunner(unittest.TestCase):
    def test_completed_run_scores_all_existing_vectors(self) -> None:
        case = make_case("canonical")
        record = EvaluationRunRecord(
            run_id="run-canonical",
            case=case,
            outcome=outcome("canonical", EvaluationRunStatus.COMPLETED, 3, 3),
            composition=diagnosed_composition("canonical"),
        )

        bundle = score_evaluation_run_record(record)

        self.assertEqual(bundle.case_id, "canonical")
        self.assertEqual(bundle.core_score.case_id, "canonical")
        self.assertEqual(bundle.evidence_score.case_id, "canonical")
        self.assertIsNotNone(bundle.unsupported_claim_score)
        self.assertEqual(bundle.operational_score.tool_success_rate, Decimal("1"))
        self.assertEqual(bundle.core_score.exact_match, True)

    def test_failed_runs_without_composition_are_scored_without_fabricated_diagnosis(self) -> None:
        records = (
            EvaluationRunRecord(
                run_id="run-runtime",
                case=make_case("runtime"),
                outcome=outcome(
                    "runtime",
                    EvaluationRunStatus.RUNTIME_FAILURE,
                    1,
                    0,
                    "runtime_error",
                ),
            ),
            EvaluationRunRecord(
                run_id="run-budget",
                case=make_case("budget"),
                outcome=outcome(
                    "budget",
                    EvaluationRunStatus.BUDGET_EXHAUSTED,
                    8,
                    7,
                    "budget_exhausted",
                ),
            ),
            EvaluationRunRecord(
                run_id="run-tool",
                case=make_case("tool"),
                outcome=outcome(
                    "tool",
                    EvaluationRunStatus.TOOL_FAILURE,
                    2,
                    1,
                    "tool_failure",
                ),
            ),
        )
        result = run_hermetic_evaluation(records)

        self.assertEqual(result.report.core_report.case_ids, ("runtime", "budget", "tool"))
        self.assertEqual(result.report.core_report.status_accuracy, Decimal("0"))
        self.assertEqual(result.report.core_report.scope_accuracy_by_dimension["asin"], Decimal("0"))
        self.assertEqual(result.report.operational_report.tool_success_rate, Decimal("8") / Decimal("11"))
        self.assertEqual(result.report.operational_report.budget_exhaustion_rate, Decimal("1") / Decimal("3"))
        self.assertEqual(result.report.unsupported_claim_scores, ())
        for bundle in result.bundles:
            self.assertIsNone(bundle.unsupported_claim_score)
            self.assertIsNone(bundle.evidence_score.citation_precision)
            self.assertEqual(bundle.evidence_score.evidence_coverage, Decimal("0"))
            self.assertFalse(bundle.core_score.exact_match)

    def test_budget_and_tool_failure_compositions_must_match_and_are_scored(self) -> None:
        budget = EvaluationRunRecord(
            run_id="run-budget-composed",
            case=make_case("budget-composed"),
            outcome=outcome(
                "budget-composed",
                EvaluationRunStatus.BUDGET_EXHAUSTED,
                8,
                8,
                "budget_exhausted",
            ),
            composition=terminal_composition(
                "budget-composed", DiagnosisStatus.BUDGET_EXHAUSTED
            ),
        )
        tool = EvaluationRunRecord(
            run_id="run-tool-composed",
            case=make_case("tool-composed"),
            outcome=outcome(
                "tool-composed",
                EvaluationRunStatus.TOOL_FAILURE,
                2,
                1,
                "tool_failure",
            ),
            composition=terminal_composition(
                "tool-composed", DiagnosisStatus.TOOL_FAILURE
            ),
        )

        result = run_hermetic_evaluation((budget, tool))

        self.assertEqual(
            tuple(score.diagnosis_id for score in result.report.unsupported_claim_scores),
            ("diag:budget-composed", "diag:tool-composed"),
        )
        self.assertEqual(
            tuple(bundle.evidence_score.evidence_coverage for bundle in result.bundles),
            (Decimal("0"), Decimal("0")),
        )

    def test_record_state_and_identity_invariants_fail_closed(self) -> None:
        case = make_case("case-a")
        cases = [
            dict(
                run_id="run-1",
                case=case,
                outcome=outcome("case-b", EvaluationRunStatus.COMPLETED, 1, 1),
                composition=diagnosed_composition("case-a"),
            ),
            dict(
                run_id="run-1",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.COMPLETED, 1, 1),
                composition=None,
            ),
            dict(
                run_id="run-1",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.COMPLETED, 1, 1),
                composition=terminal_composition(
                    "case-a", DiagnosisStatus.BUDGET_EXHAUSTED
                ),
            ),
            dict(
                run_id="run-1",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.COMPLETED, 1, 1),
                composition=terminal_composition(
                    "case-a", DiagnosisStatus.TOOL_FAILURE
                ),
            ),
            dict(
                run_id="run-1",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.RUNTIME_FAILURE, 1, 0, "runtime"),
                composition=diagnosed_composition("case-a"),
            ),
            dict(
                run_id="run-1",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.BUDGET_EXHAUSTED, 1, 1, "budget"),
                composition=terminal_composition("case-a", DiagnosisStatus.TOOL_FAILURE),
            ),
            dict(
                run_id="run-1",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.TOOL_FAILURE, 1, 1, "tool"),
                composition=terminal_composition("case-a", DiagnosisStatus.BUDGET_EXHAUSTED),
            ),
            dict(
                run_id="",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
                composition=None,
            ),
            dict(
                run_id="   ",
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
                composition=None,
            ),
            dict(
                run_id=123,  # type: ignore[arg-type]
                case=case,
                outcome=outcome("case-a", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
                composition=None,
            ),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(EvaluationValidationError):
                EvaluationRunRecord(**kwargs)

    def test_record_trims_run_id_whitespace(self) -> None:
        case = make_case("case-trim")
        record = EvaluationRunRecord(
            run_id="  run-padded-id  ",
            case=case,
            outcome=outcome("case-trim", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
        )
        self.assertEqual(record.run_id, "run-padded-id")

    def test_run_rejects_empty_non_sequence_duplicate_and_bad_records(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            run_hermetic_evaluation(())
        with self.assertRaises(EvaluationValidationError):
            run_hermetic_evaluation((1,))  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            run_hermetic_evaluation(
                iter(
                    [
                        EvaluationRunRecord(
                            run_id="run-generator",
                            case=make_case("generator"),
                            outcome=outcome("generator", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
                        )
                    ]
                )
            )  # type: ignore[arg-type]
        record = EvaluationRunRecord(
            run_id="run-duplicate",
            case=make_case("duplicate"),
            outcome=outcome("duplicate", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
        )
        duplicate = (record, record)
        with self.assertRaises(EvaluationValidationError):
            run_hermetic_evaluation(duplicate)

    def test_run_rejects_duplicate_run_id_in_single_pass(self) -> None:
        rec1 = EvaluationRunRecord(
            run_id="run-same",
            case=make_case("case-1"),
            outcome=outcome("case-1", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
        )
        rec2 = EvaluationRunRecord(
            run_id="run-same",
            case=make_case("case-2"),
            outcome=outcome("case-2", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
        )
        with self.assertRaises(EvaluationValidationError):
            run_hermetic_evaluation((rec1, rec2))

    def test_run_preserves_order_is_deterministic_and_snapshots_nested_sequences(self) -> None:
        first_records = [
            EvaluationRunRecord(
                run_id="run-b",
                case=make_case("b"),
                outcome=outcome("b", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
            ),
            EvaluationRunRecord(
                run_id="run-a",
                case=make_case("a"),
                outcome=outcome("a", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
            ),
        ]
        first = run_hermetic_evaluation(first_records)
        second = run_hermetic_evaluation(tuple(first_records))
        first_records.clear()

        self.assertEqual(first, second)
        self.assertEqual(tuple(bundle.case_id for bundle in first.bundles), ("b", "a"))
        self.assertIsInstance(first.bundles, tuple)
        with self.assertRaises(AttributeError):
            first.bundles = ()  # type: ignore[misc]

    def test_result_and_bundle_validate_report_identity_and_deep_snapshot(self) -> None:
        record = EvaluationRunRecord(
            run_id="run-identity",
            case=make_case("identity"),
            outcome=outcome("identity", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
        )
        result = run_hermetic_evaluation((record,))
        source = list(result.bundles)
        copied = HermeticEvaluationResult(bundles=source, report=result.report)
        source.clear()
        self.assertEqual(len(copied.bundles), 1)

        with self.assertRaises(EvaluationValidationError):
            EvaluationCaseScoreBundle(
                case_id="wrong",
                core_score=result.bundles[0].core_score,
                evidence_score=result.bundles[0].evidence_score,
                unsupported_claim_score=None,
                operational_score=result.bundles[0].operational_score,
            )
        with self.assertRaises(EvaluationValidationError):
            HermeticEvaluationResult(
                bundles=(result.bundles[0],),
                report=object(),  # type: ignore[arg-type]
            )

    def test_no_composition_evidence_score_builds_all_case_obligations(self) -> None:
        case = make_case("obligation-check")
        record = EvaluationRunRecord(
            run_id="run-obligation",
            case=case,
            outcome=outcome("obligation-check", EvaluationRunStatus.RUNTIME_FAILURE, 0, 0, "runtime"),
        )
        score = score_evaluation_run_record(record)
        expected = build_evidence_obligations(case)
        self.assertEqual(
            score.evidence_score.obligation_ids,
            tuple(item.obligation_id for item in expected),
        )
        self.assertEqual(score.evidence_score.covered_obligation_ids, ())

    def test_runner_source_has_no_runtime_loader_or_external_io(self) -> None:
        source = inspect.getsource(runner_module)
        for forbidden in (
            "load_ground_truth_cases",
            "psycopg",
            "Runner.run",
            "open(",
            "requests.",
            "http://",
            "https://",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
