"""Deterministic scoring of Diagnosis Evidence citations against obligations.

This module evaluates only the Evidence explicitly cited by a Diagnosis.  The
complete Evidence portfolio is retained by :class:`DiagnosisComposition` for
auditability, but uncited portfolio items must not improve citation precision
or obligation coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.diagnosis import DiagnosisComposition
from app.evidence import Evidence, EvidenceRole
from app.observations import ObservationStatus

from .evidence_obligations import (
    EvidenceObligation,
    EvidenceObligationKind,
    build_evidence_obligations,
)
from .models import EvaluationValidationError, GroundTruthCase


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _snapshot_unique_ids(value: object, field_name: str) -> tuple[str, ...]:
    """Take a defensive tuple snapshot of a unique string-id collection."""
    if isinstance(value, (str, bytes, bytearray)) or isinstance(value, Mapping):
        raise EvaluationValidationError(
            f"Field '{field_name}' must be an iterable of strings, not a string/mapping."
        )
    try:
        items = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise EvaluationValidationError(
            f"Field '{field_name}' must be an iterable of strings."
        ) from exc
    result = tuple(_clean_string(item, f"{field_name} item") for item in items)
    if len(result) != len(set(result)):
        raise EvaluationValidationError(f"Field '{field_name}' must not contain duplicates.")
    return result


def _validate_ratio(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise EvaluationValidationError(f"Field '{field_name}' must be a Decimal.")
    try:
        valid = value.is_finite() and Decimal("0") <= value <= Decimal("1")
    except (ArithmeticError, ValueError):
        valid = False
    if not valid:
        raise EvaluationValidationError(f"Field '{field_name}' must be a finite Decimal in [0, 1].")
    return value


@dataclass(frozen=True)
class EvidenceCitationScore:
    """Auditable citation precision and Evidence-obligation coverage for one case.

    ``cited_evidence_ids`` follows ``Diagnosis.evidence_ids`` order, while
    ``obligation_ids`` and ``covered_obligation_ids`` follow the deterministic
    order returned by :func:`build_evidence_obligations`.
    """

    case_id: str
    cited_evidence_ids: tuple[str, ...]
    matched_citation_ids: tuple[str, ...]
    unsupported_citation_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    covered_obligation_ids: tuple[str, ...]
    citation_precision: Decimal | None
    evidence_coverage: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _clean_string(self.case_id, "case_id"))

        cited = _snapshot_unique_ids(self.cited_evidence_ids, "cited_evidence_ids")
        matched = _snapshot_unique_ids(self.matched_citation_ids, "matched_citation_ids")
        unsupported = _snapshot_unique_ids(
            self.unsupported_citation_ids,
            "unsupported_citation_ids",
        )
        obligations = _snapshot_unique_ids(self.obligation_ids, "obligation_ids")
        covered = _snapshot_unique_ids(
            self.covered_obligation_ids,
            "covered_obligation_ids",
        )

        if not obligations:
            raise EvaluationValidationError("Field 'obligation_ids' must not be empty.")

        cited_set = set(cited)
        matched_set = set(matched)
        unsupported_set = set(unsupported)
        if matched_set & unsupported_set:
            raise EvaluationValidationError(
                "matched_citation_ids and unsupported_citation_ids must be disjoint."
            )
        if matched_set | unsupported_set != cited_set:
            raise EvaluationValidationError(
                "matched_citation_ids and unsupported_citation_ids must exactly partition "
                "cited_evidence_ids."
            )

        obligation_set = set(obligations)
        if not set(covered).issubset(obligation_set):
            raise EvaluationValidationError(
                "covered_obligation_ids must be a subset of obligation_ids."
            )

        precision = self.citation_precision
        if precision is not None:
            precision = _validate_ratio(precision, "citation_precision")
        coverage = _validate_ratio(self.evidence_coverage, "evidence_coverage")

        if (not cited) != (precision is None):
            raise EvaluationValidationError(
                "citation_precision must be None exactly when cited_evidence_ids is empty."
            )
        if cited:
            expected_precision = Decimal(len(matched)) / Decimal(len(cited))
            if precision != expected_precision:
                raise EvaluationValidationError(
                    "citation_precision must equal matched citations divided by cited citations."
                )

        expected_coverage = Decimal(len(covered)) / Decimal(len(obligations))
        if coverage != expected_coverage:
            raise EvaluationValidationError(
                "evidence_coverage must equal covered obligations divided by obligations."
            )

        object.__setattr__(self, "cited_evidence_ids", cited)
        object.__setattr__(self, "matched_citation_ids", matched)
        object.__setattr__(self, "unsupported_citation_ids", unsupported)
        object.__setattr__(self, "obligation_ids", obligations)
        object.__setattr__(self, "covered_obligation_ids", covered)
        object.__setattr__(self, "citation_precision", precision)
        object.__setattr__(self, "evidence_coverage", coverage)


def _negative_control_matches(
    evidence: Evidence,
    obligation: EvidenceObligation,
) -> bool:
    """Match a control dimension without allowing filter/dimension conflicts."""
    if obligation.dimension is None or obligation.dimension_value is None:
        return False

    dimension = obligation.dimension
    expected_value = obligation.dimension_value
    filter_value = evidence.filters.get(dimension)
    row_value = evidence.dimensions.get(dimension)

    # A duplicate dimension is valid only when both representations agree.  A
    # conflicting pair is deliberately not resolved by precedence.
    if filter_value is not None and row_value is not None and filter_value != row_value:
        return False
    actual_value = row_value if row_value is not None else filter_value
    return actual_value == expected_value


def _evidence_matches_obligation(
    evidence: Evidence,
    obligation: EvidenceObligation,
) -> bool:
    if obligation.kind in {
        EvidenceObligationKind.TARGET_SUPPORTING,
        EvidenceObligationKind.DRIVER_SUPPORTING,
    }:
        return (
            evidence.metric == obligation.metric
            and evidence.role == EvidenceRole.SUPPORTING
            and evidence.observation_status == ObservationStatus.ANOMALOUS
        )

    if obligation.kind == EvidenceObligationKind.STABLE_METRIC:
        return (
            evidence.metric == obligation.metric
            and evidence.observation_status == ObservationStatus.NORMAL
            and evidence.role
            in {EvidenceRole.SUPPORTING, EvidenceRole.NEGATIVE_CONTROL}
        )

    if obligation.kind == EvidenceObligationKind.NEGATIVE_CONTROL:
        return (
            evidence.role == EvidenceRole.NEGATIVE_CONTROL
            and evidence.observation_status == ObservationStatus.NORMAL
            and _negative_control_matches(evidence, obligation)
        )

    # The obligation builder currently exhausts the enum.  Keep this explicit
    # so a future enum extension fails closed instead of becoming a free match.
    return False


def score_evidence_citations(
    case: GroundTruthCase,
    composition: DiagnosisComposition,
) -> EvidenceCitationScore:
    """Score only Diagnosis-cited Evidence against deterministic obligations.

    Citation precision is ``matched cited Evidence / cited Evidence`` and is
    ``None`` when no Evidence is cited.  Evidence coverage is ``covered
    obligations / all obligations``.  A cited Evidence item may cover multiple
    obligations; an uncited portfolio item covers none.
    """
    if not isinstance(case, GroundTruthCase):
        raise EvaluationValidationError(
            f"Expected GroundTruthCase instance, got {type(case).__name__}."
        )
    if not isinstance(composition, DiagnosisComposition):
        raise EvaluationValidationError(
            f"Expected DiagnosisComposition instance, got {type(composition).__name__}."
        )

    obligations = build_evidence_obligations(case)
    portfolio_by_id = {item.evidence_id: item for item in composition.evidence}
    cited_ids = tuple(composition.diagnosis.evidence_ids)
    cited_evidence = tuple(portfolio_by_id[evidence_id] for evidence_id in cited_ids)

    matched_citation_ids: list[str] = []
    unsupported_citation_ids: list[str] = []
    covered_obligation_ids: list[str] = []

    for evidence_id, evidence in zip(cited_ids, cited_evidence):
        evidence_matches = [
            obligation
            for obligation in obligations
            if _evidence_matches_obligation(evidence, obligation)
        ]
        if evidence_matches:
            matched_citation_ids.append(evidence_id)
            for obligation in evidence_matches:
                if obligation.obligation_id not in covered_obligation_ids:
                    covered_obligation_ids.append(obligation.obligation_id)
        else:
            unsupported_citation_ids.append(evidence_id)

    ordered_covered_ids = tuple(
        obligation.obligation_id
        for obligation in obligations
        if obligation.obligation_id in covered_obligation_ids
    )
    precision = (
        None
        if not cited_ids
        else Decimal(len(matched_citation_ids)) / Decimal(len(cited_ids))
    )
    coverage = Decimal(len(ordered_covered_ids)) / Decimal(len(obligations))

    return EvidenceCitationScore(
        case_id=case.case_id,
        cited_evidence_ids=cited_ids,
        matched_citation_ids=tuple(matched_citation_ids),
        unsupported_citation_ids=tuple(unsupported_citation_ids),
        obligation_ids=tuple(item.obligation_id for item in obligations),
        covered_obligation_ids=ordered_covered_ids,
        citation_precision=precision,
        evidence_coverage=coverage,
    )


__all__ = ["EvidenceCitationScore", "score_evidence_citations"]
