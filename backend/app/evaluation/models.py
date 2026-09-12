"""Immutable contracts used by the deterministic Evaluation core.

The evaluation package is deliberately kept separate from the agent runtime.  A
``GroundTruthCase`` is owned by the evaluation runner and is never an input to
runtime tools or prompts.  ``CoreCaseScore`` only describes semantic agreement
between a case and a completed structured Diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from app.diagnosis.models import DiagnosisStatus


class EvaluationError(Exception):
    """Base exception for evaluation-domain operations."""


class EvaluationConfigError(EvaluationError):
    """Raised when a Ground Truth file or case violates its contract."""


class EvaluationValidationError(EvaluationError):
    """Raised when an evaluation-domain model is constructed invalidly."""


EVALUATION_SCOPE_DIMENSIONS = ("marketplace", "asin", "traffic_source")
EVALUATION_CONTROL_KEYS = ("marketplaces", "asins", "traffic_sources")
_ALLOWED_CASE_STATUSES = frozenset(
    {DiagnosisStatus.DIAGNOSED, DiagnosisStatus.NO_MATERIAL_ANOMALY}
)


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _freeze_unique_strings(
    value: object,
    field_name: str,
    *,
    require_non_empty: bool = False,
) -> tuple[str, ...]:
    """Copy a JSON-like string sequence while rejecting string pseudo-sequences."""
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (list, tuple)):
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a list or tuple of strings, not a string/mapping."
        )
    items = tuple(_clean_string(item, f"{field_name} item") for item in value)
    if len(items) != len(set(items)):
        raise EvaluationValidationError(f"Field '{field_name}' must not contain duplicates.")
    if require_non_empty and not items:
        raise EvaluationValidationError(f"Field '{field_name}' must not be empty.")
    return items


def _freeze_scope(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError("Field 'affected_scope' must be a string mapping.")

    scope: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _clean_string(raw_key, "affected_scope key")
        if key not in EVALUATION_SCOPE_DIMENSIONS:
            raise EvaluationValidationError(
                f"Unsupported affected_scope dimension '{key}'. "
                f"Allowed dimensions: {EVALUATION_SCOPE_DIMENSIONS}."
            )
        if key in scope:
            raise EvaluationValidationError(f"Duplicate affected_scope dimension '{key}'.")
        scope[key] = _clean_string(raw_value, f"affected_scope[{key}]")
    return MappingProxyType(scope)


def _freeze_negative_controls(value: object) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError("Field 'negative_controls' must be a mapping.")

    controls: dict[str, tuple[str, ...]] = {}
    for raw_key, raw_values in value.items():
        key = _clean_string(raw_key, "negative_controls key")
        if key not in EVALUATION_CONTROL_KEYS:
            raise EvaluationValidationError(
                f"Unsupported negative_controls key '{key}'. "
                f"Expected exactly: {EVALUATION_CONTROL_KEYS}."
            )
        if key in controls:
            raise EvaluationValidationError(f"Duplicate negative_controls key '{key}'.")
        controls[key] = _freeze_unique_strings(
            raw_values,
            f"negative_controls[{key}]",
            require_non_empty=True,
        )

    if set(controls) != set(EVALUATION_CONTROL_KEYS):
        raise EvaluationValidationError(
            "negative_controls must contain exactly the keys "
            f"{EVALUATION_CONTROL_KEYS}."
        )
    return MappingProxyType(controls)


@dataclass(frozen=True)
class GroundTruthCase:
    """Immutable expected semantic outcome for one evaluation case.

    This model intentionally contains no ``root_cause`` field.  The benchmark
    records data-level diagnosis expectations and its causal boundary, not an
    unsupported claim about an external business cause.
    """

    case_id: str
    scenario: str
    target_metric: str
    status: DiagnosisStatus
    primary_driver: str | None
    affected_scope: Mapping[str, str]
    expected_stable_metrics: tuple[str, ...]
    negative_controls: Mapping[str, tuple[str, ...]]
    causal_boundary: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _clean_string(self.case_id, "case_id"))
        object.__setattr__(self, "scenario", _clean_string(self.scenario, "scenario"))
        object.__setattr__(self, "target_metric", _clean_string(self.target_metric, "target_metric"))

        if not isinstance(self.status, DiagnosisStatus):
            raise EvaluationValidationError("Field 'status' must be a DiagnosisStatus.")
        if self.status not in _ALLOWED_CASE_STATUSES:
            raise EvaluationValidationError(
                "Ground Truth development cases only allow diagnosed or "
                "no_material_anomaly status."
            )

        if self.primary_driver is not None:
            object.__setattr__(
                self,
                "primary_driver",
                _clean_string(self.primary_driver, "primary_driver"),
            )

        scope = _freeze_scope(self.affected_scope)
        object.__setattr__(self, "affected_scope", scope)
        object.__setattr__(
            self,
            "expected_stable_metrics",
            _freeze_unique_strings(self.expected_stable_metrics, "expected_stable_metrics"),
        )
        object.__setattr__(self, "negative_controls", _freeze_negative_controls(self.negative_controls))
        object.__setattr__(
            self,
            "causal_boundary",
            _clean_string(self.causal_boundary, "causal_boundary"),
        )

        if self.status == DiagnosisStatus.DIAGNOSED:
            if self.primary_driver is None or not scope:
                raise EvaluationValidationError(
                    "Diagnosed Ground Truth requires primary_driver and non-empty affected_scope."
                )
        elif self.primary_driver is not None or scope:
            raise EvaluationValidationError(
                "No-material-anomaly Ground Truth must have no primary_driver and empty affected_scope."
            )


def _validate_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationValidationError(f"Field '{field_name}' must be bool.")
    return value


@dataclass(frozen=True)
class CoreCaseScore:
    """Deterministic semantic score for one Case/Diagnosis pair."""

    case_id: str
    status_correct: bool
    target_metric_correct: bool
    driver_correct: bool
    scope_correct: Mapping[str, bool]
    scope_accuracy: Decimal
    exact_match: bool
    no_anomaly_correct: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _clean_string(self.case_id, "case_id"))
        for field_name in (
            "status_correct",
            "target_metric_correct",
            "driver_correct",
            "exact_match",
            "no_anomaly_correct",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_bool(getattr(self, field_name), field_name),
            )

        if not isinstance(self.scope_correct, Mapping):
            raise EvaluationValidationError("Field 'scope_correct' must be a mapping.")
        if set(self.scope_correct) != set(EVALUATION_SCOPE_DIMENSIONS):
            raise EvaluationValidationError(
                "scope_correct must contain exactly the three evaluation dimensions."
            )
        scope_correct = {}
        for dimension in EVALUATION_SCOPE_DIMENSIONS:
            scope_correct[dimension] = _validate_bool(
                self.scope_correct[dimension],
                f"scope_correct[{dimension}]",
            )
        object.__setattr__(self, "scope_correct", MappingProxyType(scope_correct))

        if not isinstance(self.scope_accuracy, Decimal) or not self.scope_accuracy.is_finite():
            raise EvaluationValidationError("Field 'scope_accuracy' must be a finite Decimal.")
        expected_accuracy = Decimal(sum(scope_correct.values())) / Decimal("3")
        if self.scope_accuracy != expected_accuracy:
            raise EvaluationValidationError(
                "scope_accuracy must equal the number of correct fixed dimensions divided by 3."
            )

        # A false exact match is allowed even when the three fixed dimensions are
        # all true: the scorer uses it for an extra unknown actual-scope key.
        if self.exact_match and not (
            self.status_correct
            and self.target_metric_correct
            and self.driver_correct
            and all(scope_correct.values())
        ):
            raise EvaluationValidationError(
                "exact_match cannot be true when a core score component is false."
            )
