"""Deterministic aggregation of repeated evaluation runs across cases."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.evaluation.models import EvaluationValidationError
from app.evaluation.operational import EvaluationRunStatus
from app.evaluation.runner import (
    EvaluationCaseScoreBundle,
    ManifestEvaluationRunSet,
    score_evaluation_run_record,
)


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _validate_rate(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise EvaluationValidationError(f"Field '{field_name}' must be a Decimal.")
    if not value.is_finite() or not (Decimal("0") <= value <= Decimal("1")):
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a finite Decimal in [0, 1]."
        )
    return value


@dataclass(frozen=True)
class CaseRepeatedSummary:
    """Immutable summary of repeated evaluation runs for a single case."""

    case_id: str
    total_runs: int
    completed_runs: int
    run_completion_rate: Decimal
    mean_status_accuracy: Decimal
    mean_target_metric_accuracy: Decimal
    mean_driver_accuracy: Decimal
    mean_scope_accuracy: Decimal
    mean_exact_match_rate: Decimal
    mean_evidence_coverage: Decimal
    mean_evidence_precision: Decimal | None
    mean_tool_success_rate: Decimal | None
    mean_tool_calls: Decimal
    budget_exhaustion_rate: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _clean_string(self.case_id, "case_id"))

        if (
            isinstance(self.total_runs, bool)
            or not isinstance(self.total_runs, int)
            or self.total_runs <= 0
        ):
            raise EvaluationValidationError("Field 'total_runs' must be a positive int.")

        if (
            isinstance(self.completed_runs, bool)
            or not isinstance(self.completed_runs, int)
            or self.completed_runs < 0
            or self.completed_runs > self.total_runs
        ):
            raise EvaluationValidationError(
                "Field 'completed_runs' must be an int between 0 and total_runs."
            )

        for field_name in (
            "run_completion_rate",
            "mean_status_accuracy",
            "mean_target_metric_accuracy",
            "mean_driver_accuracy",
            "mean_scope_accuracy",
            "mean_exact_match_rate",
            "mean_evidence_coverage",
            "budget_exhaustion_rate",
        ):
            _validate_rate(getattr(self, field_name), field_name)

        if self.mean_evidence_precision is not None:
            _validate_rate(self.mean_evidence_precision, "mean_evidence_precision")

        if self.mean_tool_success_rate is not None:
            _validate_rate(self.mean_tool_success_rate, "mean_tool_success_rate")

        if (
            not isinstance(self.mean_tool_calls, Decimal)
            or not self.mean_tool_calls.is_finite()
            or self.mean_tool_calls < Decimal("0")
        ):
            raise EvaluationValidationError(
                "Field 'mean_tool_calls' must be a finite non-negative Decimal."
            )

        expected_completion_rate = Decimal(self.completed_runs) / Decimal(self.total_runs)
        if self.run_completion_rate != expected_completion_rate:
            raise EvaluationValidationError(
                "run_completion_rate must equal completed_runs / total_runs."
            )


@dataclass(frozen=True)
class RepeatedRunEvaluationReport:
    """Global evaluation report aggregating repeated runs across all cases."""

    manifest_id: str
    case_summaries: tuple[CaseRepeatedSummary, ...]
    total_cases: int
    total_runs: int
    macro_driver_accuracy: Decimal
    macro_scope_accuracy: Decimal
    macro_exact_match_rate: Decimal
    overall_run_completion_rate: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "manifest_id", _clean_string(self.manifest_id, "manifest_id")
        )

        if isinstance(self.case_summaries, (str, bytes, bytearray)) or not isinstance(
            self.case_summaries, (tuple, list)
        ):
            raise EvaluationValidationError(
                "Field 'case_summaries' must be a tuple or list of CaseRepeatedSummary."
            )
        summaries = tuple(self.case_summaries)
        if not summaries:
            raise EvaluationValidationError("Field 'case_summaries' must not be empty.")
        if any(not isinstance(item, CaseRepeatedSummary) for item in summaries):
            raise EvaluationValidationError(
                "case_summaries must contain only CaseRepeatedSummary instances."
            )

        case_ids = tuple(item.case_id for item in summaries)
        if len(case_ids) != len(set(case_ids)):
            raise EvaluationValidationError(
                "case_summaries must not contain duplicate case_id values."
            )
        object.__setattr__(self, "case_summaries", summaries)

        if (
            isinstance(self.total_cases, bool)
            or not isinstance(self.total_cases, int)
            or self.total_cases != len(summaries)
        ):
            raise EvaluationValidationError("Field 'total_cases' must equal len(case_summaries).")

        expected_total_runs = sum(item.total_runs for item in summaries)
        if (
            isinstance(self.total_runs, bool)
            or not isinstance(self.total_runs, int)
            or self.total_runs != expected_total_runs
        ):
            raise EvaluationValidationError(
                "Field 'total_runs' must equal sum of total_runs in case_summaries."
            )

        _validate_rate(self.macro_driver_accuracy, "macro_driver_accuracy")
        _validate_rate(self.macro_scope_accuracy, "macro_scope_accuracy")
        _validate_rate(self.macro_exact_match_rate, "macro_exact_match_rate")
        _validate_rate(self.overall_run_completion_rate, "overall_run_completion_rate")

        d_cases = Decimal(len(summaries))
        expected_macro_driver = (
            sum(item.mean_driver_accuracy for item in summaries) / d_cases
        )
        if self.macro_driver_accuracy != expected_macro_driver:
            raise EvaluationValidationError(
                "macro_driver_accuracy must equal average of mean_driver_accuracy across case_summaries."
            )

        expected_macro_scope = (
            sum(item.mean_scope_accuracy for item in summaries) / d_cases
        )
        if self.macro_scope_accuracy != expected_macro_scope:
            raise EvaluationValidationError(
                "macro_scope_accuracy must equal average of mean_scope_accuracy across case_summaries."
            )

        expected_macro_exact = (
            sum(item.mean_exact_match_rate for item in summaries) / d_cases
        )
        if self.macro_exact_match_rate != expected_macro_exact:
            raise EvaluationValidationError(
                "macro_exact_match_rate must equal average of mean_exact_match_rate across case_summaries."
            )

        total_completed = sum(item.completed_runs for item in summaries)
        expected_overall_completion = Decimal(total_completed) / Decimal(expected_total_runs)
        if self.overall_run_completion_rate != expected_overall_completion:
            raise EvaluationValidationError(
                "overall_run_completion_rate must equal total completed_runs / total_runs."
            )


def aggregate_manifest_evaluation_run_set(
    run_set: ManifestEvaluationRunSet,
) -> RepeatedRunEvaluationReport:
    """Aggregate a reconciled ManifestEvaluationRunSet into a RepeatedRunEvaluationReport.

    Evaluates each record using score_evaluation_run_record, groups scores by case
    following the exact case order in manifest.run_counts_by_case, and calculates
    case-level and global macro repeated-run statistics using pure Decimal arithmetic.
    """
    if not isinstance(run_set, ManifestEvaluationRunSet):
        raise EvaluationValidationError(
            f"Expected ManifestEvaluationRunSet instance, got {type(run_set).__name__}."
        )

    manifest = run_set.manifest
    records_by_case: dict[str, list[Any]] = {}
    for record in run_set.records:
        records_by_case.setdefault(record.case.case_id, []).append(record)

    case_summaries: list[CaseRepeatedSummary] = []
    for case_id in manifest.run_counts_by_case:
        records = records_by_case.get(case_id, [])
        bundles: list[EvaluationCaseScoreBundle] = [
            score_evaluation_run_record(rec) for rec in records
        ]
        total_runs = len(bundles)
        d_total = Decimal(total_runs)

        completed_runs = sum(
            1 for b in bundles if b.operational_score.run_status == EvaluationRunStatus.COMPLETED
        )
        run_completion_rate = Decimal(completed_runs) / d_total

        mean_status = (
            sum(Decimal("1") if b.core_score.status_correct else Decimal("0") for b in bundles)
            / d_total
        )
        mean_target = (
            sum(Decimal("1") if b.core_score.target_metric_correct else Decimal("0") for b in bundles)
            / d_total
        )
        mean_driver = (
            sum(Decimal("1") if b.core_score.driver_correct else Decimal("0") for b in bundles)
            / d_total
        )
        mean_scope = sum(b.core_score.scope_accuracy for b in bundles) / d_total
        mean_exact = (
            sum(Decimal("1") if b.core_score.exact_match else Decimal("0") for b in bundles)
            / d_total
        )

        mean_coverage = (
            sum(b.evidence_score.evidence_coverage for b in bundles) / d_total
        )

        precisions = [
            b.evidence_score.citation_precision
            for b in bundles
            if b.evidence_score.citation_precision is not None
        ]
        mean_precision = (
            None if not precisions else sum(precisions, Decimal("0")) / Decimal(len(precisions))
        )

        total_attempted = sum(b.operational_score.tool_calls_attempted for b in bundles)
        total_succeeded = sum(b.operational_score.tool_calls_succeeded for b in bundles)
        mean_tool_success = (
            None if total_attempted == 0 else Decimal(total_succeeded) / Decimal(total_attempted)
        )

        mean_tool_calls = Decimal(total_attempted) / d_total
        budget_exhausted_runs = sum(1 for b in bundles if b.operational_score.budget_exhausted)
        budget_exhaustion_rate = Decimal(budget_exhausted_runs) / d_total

        case_summaries.append(
            CaseRepeatedSummary(
                case_id=case_id,
                total_runs=total_runs,
                completed_runs=completed_runs,
                run_completion_rate=run_completion_rate,
                mean_status_accuracy=mean_status,
                mean_target_metric_accuracy=mean_target,
                mean_driver_accuracy=mean_driver,
                mean_scope_accuracy=mean_scope,
                mean_exact_match_rate=mean_exact,
                mean_evidence_coverage=mean_coverage,
                mean_evidence_precision=mean_precision,
                mean_tool_success_rate=mean_tool_success,
                mean_tool_calls=mean_tool_calls,
                budget_exhaustion_rate=budget_exhaustion_rate,
            )
        )

    total_cases = len(case_summaries)
    total_runs = sum(s.total_runs for s in case_summaries)
    d_cases = Decimal(total_cases)
    d_total_runs = Decimal(total_runs)

    macro_driver = sum(s.mean_driver_accuracy for s in case_summaries) / d_cases
    macro_scope = sum(s.mean_scope_accuracy for s in case_summaries) / d_cases
    macro_exact = sum(s.mean_exact_match_rate for s in case_summaries) / d_cases
    total_completed = sum(s.completed_runs for s in case_summaries)
    overall_completion = Decimal(total_completed) / d_total_runs

    return RepeatedRunEvaluationReport(
        manifest_id=manifest.manifest_id,
        case_summaries=tuple(case_summaries),
        total_cases=total_cases,
        total_runs=total_runs,
        macro_driver_accuracy=macro_driver,
        macro_scope_accuracy=macro_scope,
        macro_exact_match_rate=macro_exact,
        overall_run_completion_rate=overall_completion,
    )


__all__ = [
    "CaseRepeatedSummary",
    "RepeatedRunEvaluationReport",
    "aggregate_manifest_evaluation_run_set",
]
