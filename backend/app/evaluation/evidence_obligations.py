"""Machine-executable Evidence obligations derived from a Ground Truth case.

This module is intentionally limited to the evaluation boundary.  It translates
the semantic expectations in a :class:`GroundTruthCase` into ordered,
immutable obligations that a later evaluator can compare with cited Evidence.
It does not load Ground Truth, inspect Evidence or Diagnosis objects, score a
run, or invoke the agent runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.diagnosis.models import DiagnosisStatus

from .models import (
    EVALUATION_CONTROL_KEYS,
    EvaluationValidationError,
    GroundTruthCase,
)


class EvidenceObligationKind(StrEnum):
    """The semantic Evidence role required by an evaluation case."""

    TARGET_SUPPORTING = "target_supporting"
    DRIVER_SUPPORTING = "driver_supporting"
    STABLE_METRIC = "stable_metric"
    NEGATIVE_CONTROL = "negative_control"


_METRIC_OBLIGATION_KINDS = frozenset(
    {
        EvidenceObligationKind.TARGET_SUPPORTING,
        EvidenceObligationKind.DRIVER_SUPPORTING,
        EvidenceObligationKind.STABLE_METRIC,
    }
)
_NEGATIVE_CONTROL_DIMENSIONS = {
    "marketplaces": "marketplace",
    "asins": "asin",
    "traffic_sources": "traffic_source",
}


def _clean_component(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    cleaned = value.strip()
    if ":" in cleaned:
        raise EvaluationValidationError(
            f"Field '{field_name}' must not contain ':'."
        )
    return cleaned


def _clean_obligation_id(value: object) -> str:
    """Validate an already-derived ID without rejecting its separators."""
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            "Field 'obligation_id' must be a non-empty string."
        )
    return value.strip()


def _validate_components(
    *,
    kind: EvidenceObligationKind,
    metric: object,
    dimension: object,
    dimension_value: object,
) -> tuple[str | None, str | None, str | None]:
    """Validate and normalize the components used by the deterministic ID."""
    if kind in _METRIC_OBLIGATION_KINDS:
        clean_metric = _clean_component(metric, "metric")
        if dimension is not None or dimension_value is not None:
            raise EvaluationValidationError(
                f"{kind.value} obligations cannot contain a dimension or dimension_value."
            )
        return clean_metric, None, None

    if kind == EvidenceObligationKind.NEGATIVE_CONTROL:
        if metric is not None:
            raise EvaluationValidationError(
                "negative_control obligations must not contain a metric."
            )
        clean_dimension = _clean_component(dimension, "dimension")
        clean_value = _clean_component(dimension_value, "dimension_value")
        return None, clean_dimension, clean_value

    raise EvaluationValidationError(
        f"Unsupported EvidenceObligationKind: {kind!r}."
    )


def derive_evidence_obligation_id(
    kind: EvidenceObligationKind,
    metric: str | None = None,
    dimension: str | None = None,
    dimension_value: str | None = None,
) -> str:
    """Derive the sole deterministic identity for an Evidence obligation.

    Components are deliberately rejected when they contain ``:`` so the
    colon-separated representation remains unambiguous and cannot be forged
    through alternate component boundaries.
    """
    if not isinstance(kind, EvidenceObligationKind):
        raise EvaluationValidationError("Field 'kind' must be an EvidenceObligationKind.")

    clean_metric, clean_dimension, clean_value = _validate_components(
        kind=kind,
        metric=metric,
        dimension=dimension,
        dimension_value=dimension_value,
    )
    if kind in _METRIC_OBLIGATION_KINDS:
        # _validate_components guarantees that clean_metric is present here.
        return f"obligation:{kind.value}:{clean_metric}"
    return f"obligation:{kind.value}:{clean_dimension}:{clean_value}"


@dataclass(frozen=True)
class EvidenceObligation:
    """One immutable, machine-checkable expectation for cited Evidence."""

    obligation_id: str
    kind: EvidenceObligationKind
    metric: str | None = None
    dimension: str | None = None
    dimension_value: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceObligationKind):
            raise EvaluationValidationError(
                "Field 'kind' must be an EvidenceObligationKind."
            )

        clean_id = _clean_obligation_id(self.obligation_id)
        clean_metric, clean_dimension, clean_value = _validate_components(
            kind=self.kind,
            metric=self.metric,
            dimension=self.dimension,
            dimension_value=self.dimension_value,
        )

        expected_id = derive_evidence_obligation_id(
            self.kind,
            metric=clean_metric,
            dimension=clean_dimension,
            dimension_value=clean_value,
        )
        if clean_id != expected_id:
            raise EvaluationValidationError(
                "obligation_id must equal the deterministic ID derived from kind "
                "and obligation components."
            )

        object.__setattr__(self, "obligation_id", clean_id)
        object.__setattr__(self, "metric", clean_metric)
        object.__setattr__(self, "dimension", clean_dimension)
        object.__setattr__(self, "dimension_value", clean_value)


def build_evidence_obligations(
    case: GroundTruthCase,
) -> tuple[EvidenceObligation, ...]:
    """Translate one Ground Truth case into ordered Evidence obligations.

    The order is stable and intentional: target/driver obligations (for a
    diagnosed case), then stable metrics in their declared order, then negative
    controls in the fixed marketplace/ASIN/traffic-source order and each
    control's original member order.
    """
    if not isinstance(case, GroundTruthCase):
        raise EvaluationValidationError(
            f"Expected GroundTruthCase instance, got {type(case).__name__}."
        )

    obligations: list[EvidenceObligation] = []
    if case.status == DiagnosisStatus.DIAGNOSED:
        # GroundTruthCase validates these fields for diagnosed cases.
        obligations.append(
            EvidenceObligation(
                obligation_id=derive_evidence_obligation_id(
                    EvidenceObligationKind.TARGET_SUPPORTING,
                    metric=case.target_metric,
                ),
                kind=EvidenceObligationKind.TARGET_SUPPORTING,
                metric=case.target_metric,
            )
        )
        obligations.append(
            EvidenceObligation(
                obligation_id=derive_evidence_obligation_id(
                    EvidenceObligationKind.DRIVER_SUPPORTING,
                    metric=case.primary_driver,
                ),
                kind=EvidenceObligationKind.DRIVER_SUPPORTING,
                metric=case.primary_driver,
            )
        )

    for metric in case.expected_stable_metrics:
        obligations.append(
            EvidenceObligation(
                obligation_id=derive_evidence_obligation_id(
                    EvidenceObligationKind.STABLE_METRIC,
                    metric=metric,
                ),
                kind=EvidenceObligationKind.STABLE_METRIC,
                metric=metric,
            )
        )

    for control_key in EVALUATION_CONTROL_KEYS:
        dimension = _NEGATIVE_CONTROL_DIMENSIONS[control_key]
        for dimension_value in case.negative_controls[control_key]:
            obligations.append(
                EvidenceObligation(
                    obligation_id=derive_evidence_obligation_id(
                        EvidenceObligationKind.NEGATIVE_CONTROL,
                        dimension=dimension,
                        dimension_value=dimension_value,
                    ),
                    kind=EvidenceObligationKind.NEGATIVE_CONTROL,
                    dimension=dimension,
                    dimension_value=dimension_value,
                )
            )

    result = tuple(obligations)
    obligation_ids = [item.obligation_id for item in result]
    if len(obligation_ids) != len(set(obligation_ids)):
        raise EvaluationValidationError(
            "Evidence obligation IDs must be globally unique within a case."
        )
    return result


__all__ = [
    "EvidenceObligation",
    "EvidenceObligationKind",
    "build_evidence_obligations",
    "derive_evidence_obligation_id",
]
