"""Immutable composition of the independently scored Evaluation vectors."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from .aggregate import CoreEvaluationReport
from .evidence_scorer import EvidenceCitationScore
from .models import EvaluationValidationError
from .operational_aggregate import ToolOperationalAggregateReport
from .unsupported_claims import UnsupportedClaimScore


def _rate(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite() or not Decimal("0") <= value <= Decimal("1"):
        raise EvaluationValidationError(f"Field '{field}' must be a finite Decimal in [0, 1].")
    return value


def _ids(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        raise EvaluationValidationError(f"Field '{field}' must be an iterable of strings.")
    try:
        result = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise EvaluationValidationError(f"Field '{field}' must be an iterable of strings.") from exc
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise EvaluationValidationError(f"Field '{field}' must contain non-empty strings.")
    result = tuple(item.strip() for item in result)
    if len(result) != len(set(result)):
        raise EvaluationValidationError(f"Field '{field}' must not contain duplicates.")
    return result


@dataclass(frozen=True)
class UnifiedEvaluationReport:
    """Combined report preserving Case and diagnosis identities separately.

    Evidence precision averages only defined per-case precisions; coverage uses
    all cases. Unsupported Claim Rate is claim-micro (total unsupported / total
    claims), while operational metrics are retained from their own aggregate.
    """

    core_report: CoreEvaluationReport
    evidence_scores: tuple[EvidenceCitationScore, ...]
    unsupported_claim_scores: tuple[UnsupportedClaimScore, ...]
    operational_report: ToolOperationalAggregateReport
    evidence_citation_precision: Decimal | None
    evidence_coverage: Decimal | None
    unsupported_claim_rate: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.core_report, CoreEvaluationReport):
            raise EvaluationValidationError("core_report must be CoreEvaluationReport.")
        if not isinstance(self.operational_report, ToolOperationalAggregateReport):
            raise EvaluationValidationError("operational_report must be ToolOperationalAggregateReport.")
        evidence = tuple(self.evidence_scores)
        claims = tuple(self.unsupported_claim_scores)
        if any(not isinstance(item, EvidenceCitationScore) for item in evidence):
            raise EvaluationValidationError("evidence_scores must contain only EvidenceCitationScore.")
        if any(not isinstance(item, UnsupportedClaimScore) for item in claims):
            raise EvaluationValidationError("unsupported_claim_scores must contain only UnsupportedClaimScore.")
        case_ids = self.core_report.case_ids
        if tuple(item.case_id for item in evidence) != case_ids:
            raise EvaluationValidationError("evidence_scores must match core_report.case_ids in order.")
        diagnosis_ids = tuple(item.diagnosis_id for item in claims)
        if len(diagnosis_ids) != len(set(diagnosis_ids)):
            raise EvaluationValidationError("unsupported_claim_scores must not repeat diagnosis_id.")
        if self.operational_report.run_ids != case_ids:
            raise EvaluationValidationError("operational_report.run_ids must match core_report.case_ids.")
        precision = _rate(self.evidence_citation_precision, "evidence_citation_precision")
        coverage = _rate(self.evidence_coverage, "evidence_coverage")
        claim_rate = _rate(self.unsupported_claim_rate, "unsupported_claim_rate")
        defined_precision = [item.citation_precision for item in evidence if item.citation_precision is not None]
        expected_precision = None if not defined_precision else sum(defined_precision, Decimal("0")) / Decimal(len(defined_precision))
        expected_coverage = None if not evidence else sum((item.evidence_coverage for item in evidence), Decimal("0")) / Decimal(len(evidence))
        total_claims = sum(len(item.claim_ids) for item in claims)
        total_unsupported = sum(len(item.unsupported_claim_ids) for item in claims)
        expected_claim_rate = None if total_claims == 0 else Decimal(total_unsupported) / Decimal(total_claims)
        if precision != expected_precision or coverage != expected_coverage or claim_rate != expected_claim_rate:
            raise EvaluationValidationError("Unified derived rates are inconsistent with child scores.")
        object.__setattr__(self, "evidence_scores", evidence)
        object.__setattr__(self, "unsupported_claim_scores", claims)


def build_unified_evaluation_report(
    core_report: CoreEvaluationReport,
    evidence_scores: Sequence[EvidenceCitationScore],
    unsupported_claim_scores: Sequence[UnsupportedClaimScore],
    operational_report: ToolOperationalAggregateReport,
) -> UnifiedEvaluationReport:
    """Compose validated score vectors without merging their identity domains."""
    if not isinstance(core_report, CoreEvaluationReport):
        raise EvaluationValidationError("core_report must be CoreEvaluationReport.")
    if not isinstance(evidence_scores, Sequence) or isinstance(evidence_scores, (str, bytes, bytearray)):
        raise EvaluationValidationError("evidence_scores must be a sequence.")
    if not isinstance(unsupported_claim_scores, Sequence) or isinstance(unsupported_claim_scores, (str, bytes, bytearray)):
        raise EvaluationValidationError("unsupported_claim_scores must be a sequence.")
    evidence_by_case = {item.case_id: item for item in evidence_scores if isinstance(item, EvidenceCitationScore)}
    if len(evidence_by_case) != len(evidence_scores):
        raise EvaluationValidationError("evidence_scores must contain valid unique case IDs.")
    ordered_evidence = tuple(evidence_by_case.get(case_id) for case_id in core_report.case_ids)
    if any(item is None for item in ordered_evidence):
        raise EvaluationValidationError("evidence_scores case IDs must exactly match core_report.case_ids.")
    evidence = tuple(ordered_evidence)  # type: ignore[arg-type]
    claims = tuple(unsupported_claim_scores)
    if any(not isinstance(item, UnsupportedClaimScore) for item in claims):
        raise EvaluationValidationError("unsupported_claim_scores must contain only UnsupportedClaimScore.")
    precision_values = [item.citation_precision for item in evidence if item.citation_precision is not None]
    return UnifiedEvaluationReport(
        core_report=core_report,
        evidence_scores=evidence,
        unsupported_claim_scores=claims,
        operational_report=operational_report,
        evidence_citation_precision=None if not precision_values else sum(precision_values, Decimal("0")) / Decimal(len(precision_values)),
        evidence_coverage=None if not evidence else sum((item.evidence_coverage for item in evidence), Decimal("0")) / Decimal(len(evidence)),
        unsupported_claim_rate=(lambda total, bad: None if total == 0 else Decimal(bad) / Decimal(total))(
            sum(len(item.claim_ids) for item in claims), sum(len(item.unsupported_claim_ids) for item in claims)
        ),
    )


__all__ = ["UnifiedEvaluationReport", "build_unified_evaluation_report"]
