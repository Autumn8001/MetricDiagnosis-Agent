"""Deterministic aggregation of the Evaluation Core score vector."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Sequence

from .models import (
    CoreCaseScore,
    EVALUATION_SCOPE_DIMENSIONS,
    EvaluationValidationError,
)


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _freeze_case_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (list, tuple)):
        raise EvaluationValidationError(
            "Field 'case_ids' must be a list or tuple of strings, not a string/mapping."
        )
    case_ids = tuple(_clean_string(item, "case_ids item") for item in value)
    if not case_ids:
        raise EvaluationValidationError("Field 'case_ids' must not be empty.")
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationValidationError("Field 'case_ids' must not contain duplicates.")
    return case_ids


def _validate_rate(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise EvaluationValidationError(f"Field '{field_name}' must be a finite Decimal.")
    if not Decimal("0") <= value <= Decimal("1"):
        raise EvaluationValidationError(f"Field '{field_name}' must be between 0 and 1.")
    return value


def _freeze_scope_rates(value: object) -> Mapping[str, Decimal]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError(
            "Field 'scope_accuracy_by_dimension' must be a mapping."
        )
    if set(value) != set(EVALUATION_SCOPE_DIMENSIONS):
        raise EvaluationValidationError(
            "scope_accuracy_by_dimension must contain exactly the three evaluation dimensions."
        )
    scope_rates = {
        dimension: _validate_rate(
            value[dimension],
            f"scope_accuracy_by_dimension[{dimension}]",
        )
        for dimension in EVALUATION_SCOPE_DIMENSIONS
    }
    return MappingProxyType(scope_rates)


@dataclass(frozen=True)
class CoreEvaluationReport:
    """Immutable aggregate of one or more deterministic core case scores."""

    case_count: int
    status_accuracy: Decimal
    target_metric_accuracy: Decimal
    driver_accuracy: Decimal
    no_anomaly_accuracy: Decimal
    exact_match_rate: Decimal
    scope_accuracy_by_dimension: Mapping[str, Decimal]
    macro_scope_accuracy: Decimal
    case_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.case_count, bool) or not isinstance(self.case_count, int):
            raise EvaluationValidationError("Field 'case_count' must be a positive int.")
        if self.case_count <= 0:
            raise EvaluationValidationError("Field 'case_count' must be a positive int.")

        case_ids = _freeze_case_ids(self.case_ids)
        if self.case_count != len(case_ids):
            raise EvaluationValidationError(
                "Field 'case_count' must equal the number of case_ids."
            )
        object.__setattr__(self, "case_ids", case_ids)

        for field_name in (
            "status_accuracy",
            "target_metric_accuracy",
            "driver_accuracy",
            "no_anomaly_accuracy",
            "exact_match_rate",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_rate(getattr(self, field_name), field_name),
            )

        scope_rates = _freeze_scope_rates(self.scope_accuracy_by_dimension)
        object.__setattr__(self, "scope_accuracy_by_dimension", scope_rates)

        macro_scope_accuracy = _validate_rate(
            self.macro_scope_accuracy,
            "macro_scope_accuracy",
        )
        expected_macro = sum(scope_rates.values(), Decimal("0")) / Decimal("3")
        if macro_scope_accuracy != expected_macro:
            raise EvaluationValidationError(
                "macro_scope_accuracy must equal the mean of the three scope accuracies."
            )
        object.__setattr__(self, "macro_scope_accuracy", macro_scope_accuracy)


def _ensure_scores(scores: object) -> tuple[CoreCaseScore, ...]:
    if isinstance(scores, (str, bytes, bytearray)) or not isinstance(scores, Sequence):
        raise EvaluationValidationError(
            "'scores' must be a non-empty sequence of CoreCaseScore instances."
        )
    frozen_scores = tuple(scores)
    if not frozen_scores:
        raise EvaluationValidationError("'scores' must not be empty.")
    if any(not isinstance(score, CoreCaseScore) for score in frozen_scores):
        raise EvaluationValidationError(
            "'scores' must contain only CoreCaseScore instances."
        )
    case_ids = [score.case_id for score in frozen_scores]
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationValidationError("'scores' must not contain duplicate case_id values.")
    return frozen_scores


def aggregate_core_scores(scores: Sequence[CoreCaseScore]) -> CoreEvaluationReport:
    """Aggregate core score booleans into deterministic Decimal rates.

    The input order is preserved in ``case_ids``.  Every reported rate uses
    the same case denominator, and scope rates are calculated independently for
    the three fixed evaluation dimensions.
    """
    frozen_scores = _ensure_scores(scores)
    case_count = len(frozen_scores)
    denominator = Decimal(case_count)

    def accuracy(attribute: str) -> Decimal:
        return Decimal(sum(getattr(score, attribute) for score in frozen_scores)) / denominator

    scope_rates = {
        dimension: Decimal(
            sum(score.scope_correct[dimension] for score in frozen_scores)
        )
        / denominator
        for dimension in EVALUATION_SCOPE_DIMENSIONS
    }
    macro_scope_accuracy = sum(scope_rates.values(), Decimal("0")) / Decimal("3")

    return CoreEvaluationReport(
        case_count=case_count,
        status_accuracy=accuracy("status_correct"),
        target_metric_accuracy=accuracy("target_metric_correct"),
        driver_accuracy=accuracy("driver_correct"),
        no_anomaly_accuracy=accuracy("no_anomaly_correct"),
        exact_match_rate=accuracy("exact_match"),
        scope_accuracy_by_dimension=scope_rates,
        macro_scope_accuracy=macro_scope_accuracy,
        case_ids=tuple(score.case_id for score in frozen_scores),
    )


__all__ = ["CoreEvaluationReport", "aggregate_core_scores"]
