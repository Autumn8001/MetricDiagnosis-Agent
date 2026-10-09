"""Hermetic tests for per-run operational outcomes and tool scoring."""

from __future__ import annotations

import datetime
from decimal import Decimal
import unittest

from app.agent_runtime import (
    EvidenceDrivenRunSummary,
    InvestigationRunSummary,
    InvestigationToolTraceEntry,
)
from app.analytics.models import DateRange
from app.diagnosis import Diagnosis, DiagnosisChange, DiagnosisComposition, DiagnosisStatus
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.evaluation import (
    EvaluationRunOutcome,
    EvaluationRunStatus,
    EvaluationValidationError,
    ToolOperationalScore,
    completed_run_outcome,
    failed_run_outcome,
    score_tool_operations,
)
from app.observations import Observation, ObservationStatus


NOW = datetime.datetime(2026, 8, 30, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 8, 30), datetime.date(2026, 8, 30))
BASELINE = DateRange(datetime.date(2026, 8, 23), datetime.date(2026, 8, 29))


def make_investigation(
    *,
    tool_calls_count: int = 2,
    max_tool_calls: int = 5,
    turns_count: int = 3,
    max_turns: int = 10,
) -> InvestigationRunSummary:
    tool_trace = tuple(
        InvestigationToolTraceEntry(
            tool_call_id=f"call-{index}",
            tool_name="query_metric",
            arguments={"metric": f"metric-{index}"},
            observation_ids=(f"observation-{index}",),
        )
        for index in range(tool_calls_count)
    )
    return InvestigationRunSummary(
        final_output="audited run",
        tool_calls_count=tool_calls_count,
        max_tool_calls=max_tool_calls,
        tools_used=tuple("query_metric" for _ in range(tool_calls_count)),
        tool_call_ids=tuple(f"call-{index}" for index in range(tool_calls_count)),
        observation_ids=tuple(f"observation-{index}" for index in range(tool_calls_count)),
        observation_count=tool_calls_count,
        tool_trace=tool_trace,
        trace_sequence=tuple(),
        turns_count=turns_count,
        max_turns=max_turns,
    )


def make_observation(index: int) -> Observation:
    return Observation(
        observation_id=f"observation-{index}",
        tool_name="query_metric",
        tool_call_id=f"call-{index}",
        metric="sales",
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters={},
        group_by=(),
        dimensions={},
        current_value=Decimal("80"),
        baseline_value=Decimal("100"),
        relative_change=Decimal("-0.20"),
        unit="usd",
        sample_size=Decimal("500"),
        source_status="ok",
        status=ObservationStatus.ANOMALOUS,
        query_or_result_reference=f"ref:observation-{index}",
        created_at=NOW,
    )


def make_composition(status: DiagnosisStatus) -> DiagnosisComposition:
    if status != DiagnosisStatus.DIAGNOSED:
        diagnosis = Diagnosis(
            diagnosis_id=f"diag:{status.value}",
            status=status,
            target_metric="sales",
            change=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=(),
            confidence=None,
            limitations=("Synthetic operational test outcome.",),
            created_at=NOW,
        )
        return DiagnosisComposition(evidence=(), diagnosis=diagnosis)

    observation = Observation(
        observation_id="observation-0",
        tool_name="query_metric",
        tool_call_id="call-0",
        metric="sales",
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters={},
        group_by=(),
        dimensions={},
        current_value=Decimal("80"),
        baseline_value=Decimal("100"),
        relative_change=Decimal("-0.20"),
        unit="usd",
        sample_size=Decimal("500"),
        source_status="ok",
        status=ObservationStatus.ANOMALOUS,
        query_or_result_reference="ref:observation-0",
        created_at=NOW,
    )
    evidence = promote_observation_to_evidence(observation, role=EvidenceRole.SUPPORTING)
    diagnosis = Diagnosis(
        diagnosis_id="diag:diagnosed",
        status=DiagnosisStatus.DIAGNOSED,
        target_metric="sales",
        change=DiagnosisChange(
            current_value=Decimal("80"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("-0.20"),
            unit="usd",
            evidence_id=evidence.evidence_id,
        ),
        primary_driver="conversion_rate",
        affected_scope={"marketplace": "US"},
        evidence_ids=(evidence.evidence_id,),
        confidence=Decimal("0.9"),
        limitations=("Synthetic operational test outcome.",),
        created_at=NOW,
    )
    return DiagnosisComposition(evidence=(evidence,), diagnosis=diagnosis)


class TestEvaluationRunOutcome(unittest.TestCase):
    def test_completed_outcome_copies_audited_counts_and_scores_one(self) -> None:
        summary = EvidenceDrivenRunSummary(
            investigation=make_investigation(),
            composition=make_composition(DiagnosisStatus.DIAGNOSED),
            observation_catalog=(make_observation(0), make_observation(1)),
        )

        outcome = completed_run_outcome("  canonical  ", summary)
        score = score_tool_operations(outcome)

        self.assertEqual(outcome.case_id, "canonical")
        self.assertEqual(outcome.status, EvaluationRunStatus.COMPLETED)
        self.assertEqual(outcome.tool_calls_attempted, 2)
        self.assertEqual(outcome.tool_calls_succeeded, 2)
        self.assertEqual(outcome.max_tool_calls, 5)
        self.assertEqual(outcome.turns_count, 3)
        self.assertEqual(outcome.max_turns, 10)
        self.assertIsNone(outcome.failure_code)
        self.assertEqual(score.tool_success_rate, Decimal("1"))
        self.assertFalse(score.budget_exhausted)

    def test_completed_outcome_maps_budget_exhausted_diagnosis(self) -> None:
        summary = EvidenceDrivenRunSummary(
            investigation=make_investigation(),
            composition=make_composition(DiagnosisStatus.BUDGET_EXHAUSTED),
            observation_catalog=(make_observation(0), make_observation(1)),
        )

        outcome = completed_run_outcome("budget-case", summary)

        self.assertEqual(outcome.status, EvaluationRunStatus.BUDGET_EXHAUSTED)
        self.assertEqual(outcome.failure_code, "budget_exhausted")

    def test_completed_outcome_maps_tool_failure_diagnosis(self) -> None:
        summary = EvidenceDrivenRunSummary(
            investigation=make_investigation(tool_calls_count=1),
            composition=make_composition(DiagnosisStatus.TOOL_FAILURE),
            observation_catalog=(make_observation(0),),
        )

        outcome = completed_run_outcome("tool-case", summary)

        self.assertEqual(outcome.status, EvaluationRunStatus.TOOL_FAILURE)
        self.assertEqual(outcome.failure_code, "tool_failure")

    def test_completed_outcome_maps_other_legal_diagnosis_status_to_completed(self) -> None:
        summary = EvidenceDrivenRunSummary(
            investigation=make_investigation(tool_calls_count=0),
            composition=make_composition(DiagnosisStatus.INSUFFICIENT_EVIDENCE),
        )

        outcome = completed_run_outcome("inconclusive-case", summary)

        self.assertEqual(outcome.status, EvaluationRunStatus.COMPLETED)
        self.assertIsNone(outcome.failure_code)

    def test_completed_outcome_requires_exact_summary_type(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            completed_run_outcome("case", object())  # type: ignore[arg-type]

    def test_failed_factory_keeps_explicit_partial_facts(self) -> None:
        outcome = failed_run_outcome(
            "partial-case",
            EvaluationRunStatus.TOOL_FAILURE,
            3,
            2,
            8,
            2,
            10,
            "db_timeout",
        )
        score = score_tool_operations(outcome)

        self.assertEqual(outcome.tool_calls_attempted, 3)
        self.assertEqual(outcome.tool_calls_succeeded, 2)
        self.assertEqual(outcome.failure_code, "db_timeout")
        self.assertEqual(score.tool_success_rate, Decimal("2") / Decimal("3"))
        self.assertFalse(score.budget_exhausted)

    def test_zero_attempts_have_undefined_success_rate(self) -> None:
        outcome = failed_run_outcome(
            "runtime-case",
            EvaluationRunStatus.RUNTIME_FAILURE,
            0,
            0,
            4,
            None,
            10,
            "runner_crash",
        )

        score = score_tool_operations(outcome)

        self.assertIsNone(score.tool_success_rate)
        self.assertFalse(score.budget_exhausted)

    def test_failure_statuses_remain_distinct(self) -> None:
        statuses = (
            EvaluationRunStatus.TOOL_FAILURE,
            EvaluationRunStatus.BUDGET_EXHAUSTED,
            EvaluationRunStatus.RUNTIME_FAILURE,
        )
        outcomes = tuple(
            failed_run_outcome("case", status, 1, 0, 2, 1, 3, status.value)
            for status in statuses
        )

        self.assertEqual(tuple(item.status for item in outcomes), statuses)
        self.assertEqual(
            tuple(score_tool_operations(item).budget_exhausted for item in outcomes),
            (False, True, False),
        )

    def test_outcome_rejects_invalid_counts_and_bool_values(self) -> None:
        invalid = (
            {"tool_calls_attempted": True},
            {"tool_calls_succeeded": False},
            {"max_tool_calls": True},
            {"max_turns": True},
            {"tool_calls_attempted": -1},
            {"tool_calls_succeeded": -1},
            {"max_tool_calls": 0},
            {"max_turns": 0},
            {"tool_calls_attempted": 3, "max_tool_calls": 2},
            {"tool_calls_succeeded": 3, "tool_calls_attempted": 2},
            {"turns_count": 0},
            {"turns_count": 11},
        )
        for overrides in invalid:
            kwargs = {
                "case_id": "case",
                "status": EvaluationRunStatus.RUNTIME_FAILURE,
                "tool_calls_attempted": 1,
                "tool_calls_succeeded": 1,
                "max_tool_calls": 2,
                "turns_count": 2,
                "max_turns": 10,
                "failure_code": "runtime_error",
            }
            kwargs.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(EvaluationValidationError):
                EvaluationRunOutcome(**kwargs)

    def test_outcome_enforces_failure_code_state_invariant(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            EvaluationRunOutcome(
                "case",
                EvaluationRunStatus.COMPLETED,
                0,
                0,
                2,
                None,
                3,
                "unexpected",
            )
        with self.assertRaises(EvaluationValidationError):
            EvaluationRunOutcome(
                "case",
                EvaluationRunStatus.RUNTIME_FAILURE,
                0,
                0,
                2,
                None,
                3,
                None,
            )
        with self.assertRaises(EvaluationValidationError):
            failed_run_outcome(
                "case",
                EvaluationRunStatus.COMPLETED,
                0,
                0,
                2,
                None,
                3,
                "bad-status",
            )

    def test_failed_factory_rejects_wrong_status_type(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            failed_run_outcome("case", "runtime_failure", 0, 0, 2, None, 3, "error")  # type: ignore[arg-type]

    def test_outcome_normalizes_strings_and_is_frozen(self) -> None:
        outcome = EvaluationRunOutcome(
            "  case  ",
            EvaluationRunStatus.COMPLETED,
            0,
            0,
            2,
            None,
            3,
            None,
        )
        self.assertEqual(outcome.case_id, "case")
        with self.assertRaises(AttributeError):
            outcome.case_id = "other"  # type: ignore[misc]


class TestToolOperationalScore(unittest.TestCase):
    def test_score_model_requires_exact_formula_and_budget_flag(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            ToolOperationalScore(
                "case",
                EvaluationRunStatus.TOOL_FAILURE,
                3,
                2,
                Decimal("1"),
                False,
            )
        with self.assertRaises(EvaluationValidationError):
            ToolOperationalScore(
                "case",
                EvaluationRunStatus.BUDGET_EXHAUSTED,
                1,
                1,
                Decimal("1"),
                False,
            )
        with self.assertRaises(EvaluationValidationError):
            ToolOperationalScore(
                "case",
                EvaluationRunStatus.RUNTIME_FAILURE,
                0,
                0,
                Decimal("0"),
                False,
            )

    def test_score_model_rejects_invalid_rate_and_types(self) -> None:
        invalid = (
            {"run_status": "completed"},
            {"tool_calls_attempted": True},
            {"tool_calls_succeeded": 2},
            {"tool_success_rate": Decimal("NaN")},
            {"tool_success_rate": Decimal("1.1")},
            {"budget_exhausted": 1},
        )
        for overrides in invalid:
            kwargs = {
                "case_id": "case",
                "run_status": EvaluationRunStatus.COMPLETED,
                "tool_calls_attempted": 1,
                "tool_calls_succeeded": 1,
                "tool_success_rate": Decimal("1"),
                "budget_exhausted": False,
            }
            kwargs.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(EvaluationValidationError):
                ToolOperationalScore(**kwargs)

    def test_score_is_deterministic_and_does_not_mutate_outcome(self) -> None:
        outcome = failed_run_outcome(
            "stable-case",
            EvaluationRunStatus.RUNTIME_FAILURE,
            2,
            1,
            5,
            2,
            10,
            "runner_error",
        )

        first = score_tool_operations(outcome)
        second = score_tool_operations(outcome)

        self.assertEqual(first, second)
        self.assertEqual(outcome.tool_calls_attempted, 2)
        self.assertEqual(outcome.failure_code, "runner_error")


if __name__ == "__main__":
    unittest.main()
