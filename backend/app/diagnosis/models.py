"""Immutable structured Diagnosis domain models for MetricSleuth."""

from dataclasses import dataclass
import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class DiagnosisError(Exception):
    """Base exception for diagnosis domain operations."""


class DiagnosisValidationError(DiagnosisError):
    """Raised when a structured diagnosis violates domain invariants."""


class DiagnosisStatus(StrEnum):
    DIAGNOSED = "diagnosed"
    NO_MATERIAL_ANOMALY = "no_material_anomaly"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_FAILURE = "tool_failure"


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiagnosisValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _validate_decimal(value: Decimal | None, field_name: str) -> None:
    if value is not None and not isinstance(value, Decimal):
        raise DiagnosisValidationError(
            f"Field '{field_name}' must be Decimal or None, got {type(value).__name__}."
        )


@dataclass(frozen=True)
class DiagnosisChange:
    """Target metric values copied from one explicitly cited Evidence object."""

    current_value: Decimal | None
    baseline_value: Decimal | None
    relative_change: Decimal | None
    unit: str
    evidence_id: str

    def __post_init__(self) -> None:
        _validate_decimal(self.current_value, "current_value")
        _validate_decimal(self.baseline_value, "baseline_value")
        _validate_decimal(self.relative_change, "relative_change")
        object.__setattr__(self, "unit", _clean_string(self.unit, "unit"))
        object.__setattr__(self, "evidence_id", _clean_string(self.evidence_id, "evidence_id"))


@dataclass(frozen=True)
class Diagnosis:
    """Evidence-referencing structured data-level diagnosis.

    ``primary_driver`` means the principal data metric driver. It never proves an
    external business cause, and this model intentionally has no root-cause field.
    """

    diagnosis_id: str
    status: DiagnosisStatus
    target_metric: str
    change: DiagnosisChange | None
    primary_driver: str | None
    affected_scope: Mapping[str, str]
    evidence_ids: tuple[str, ...]
    confidence: Decimal | None
    limitations: tuple[str, ...]
    created_at: datetime.datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnosis_id", _clean_string(self.diagnosis_id, "diagnosis_id"))
        object.__setattr__(self, "target_metric", _clean_string(self.target_metric, "target_metric"))
        if not isinstance(self.status, DiagnosisStatus):
            raise DiagnosisValidationError("Field 'status' must be a DiagnosisStatus.")
        if self.change is not None and not isinstance(self.change, DiagnosisChange):
            raise DiagnosisValidationError("Field 'change' must be DiagnosisChange or None.")

        if self.primary_driver is not None:
            object.__setattr__(
                self, "primary_driver", _clean_string(self.primary_driver, "primary_driver")
            )

        if not isinstance(self.affected_scope, Mapping):
            raise DiagnosisValidationError("Field 'affected_scope' must be a string mapping.")
        scope: dict[str, str] = {}
        for key, value in self.affected_scope.items():
            clean_key = _clean_string(key, "affected_scope key")
            clean_value = _clean_string(value, f"affected_scope[{clean_key}]")
            if clean_key in scope:
                raise DiagnosisValidationError(f"Duplicate affected scope key: '{clean_key}'.")
            scope[clean_key] = clean_value
        object.__setattr__(self, "affected_scope", MappingProxyType(scope))

        if isinstance(self.evidence_ids, (str, bytes)):
            raise DiagnosisValidationError(
                "Field 'evidence_ids' must be an iterable of strings, not a string."
            )
        try:
            evidence_ids = tuple(_clean_string(item, "evidence_ids item") for item in self.evidence_ids)
        except TypeError as exc:
            raise DiagnosisValidationError("Field 'evidence_ids' must be an iterable of strings.") from exc
        if len(evidence_ids) != len(set(evidence_ids)):
            raise DiagnosisValidationError("Field 'evidence_ids' must not contain duplicates.")
        object.__setattr__(self, "evidence_ids", evidence_ids)

        if isinstance(self.limitations, (str, bytes)):
            raise DiagnosisValidationError(
                "Field 'limitations' must be an iterable of strings, not a string."
            )
        try:
            limitations = tuple(_clean_string(item, "limitations item") for item in self.limitations)
        except TypeError as exc:
            raise DiagnosisValidationError("Field 'limitations' must be an iterable of strings.") from exc
        if not limitations:
            raise DiagnosisValidationError("Field 'limitations' must contain at least one item.")
        if len(limitations) != len(set(limitations)):
            raise DiagnosisValidationError("Field 'limitations' must not contain duplicates.")
        object.__setattr__(self, "limitations", limitations)

        _validate_decimal(self.confidence, "confidence")
        if self.confidence is not None:
            try:
                confidence_in_range = (
                    self.confidence.is_finite()
                    and Decimal("0") <= self.confidence <= Decimal("1")
                )
            except (ArithmeticError, ValueError):
                confidence_in_range = False
            if not confidence_in_range:
                raise DiagnosisValidationError("Field 'confidence' must be within [0, 1].")

        if not isinstance(self.created_at, datetime.datetime):
            raise DiagnosisValidationError("Field 'created_at' must be a datetime.")
        if self.created_at.tzinfo is None or self.created_at.tzinfo.utcoffset(self.created_at) is None:
            raise DiagnosisValidationError("Field 'created_at' must be timezone-aware.")
        object.__setattr__(self, "created_at", self.created_at.astimezone(datetime.timezone.utc))

        if self.change is not None and self.change.evidence_id not in evidence_ids:
            raise DiagnosisValidationError("DiagnosisChange.evidence_id must be present in evidence_ids.")

        successful = self.status in {
            DiagnosisStatus.DIAGNOSED,
            DiagnosisStatus.NO_MATERIAL_ANOMALY,
        }
        if successful:
            if self.change is None or any(
                value is None
                for value in (
                    self.change.current_value,
                    self.change.baseline_value,
                    self.change.relative_change,
                )
            ):
                raise DiagnosisValidationError("Successful diagnosis requires a complete target change.")
            if not evidence_ids:
                raise DiagnosisValidationError("Successful diagnosis requires evidence_ids.")
            if self.confidence is None:
                raise DiagnosisValidationError("Successful diagnosis requires confidence.")

        if self.status == DiagnosisStatus.DIAGNOSED:
            if self.primary_driver is None or not scope:
                raise DiagnosisValidationError(
                    "Diagnosed status requires primary_driver and non-empty affected_scope."
                )
        elif self.status == DiagnosisStatus.NO_MATERIAL_ANOMALY:
            if self.primary_driver is not None or scope:
                raise DiagnosisValidationError(
                    "No-material-anomaly status cannot carry primary_driver or affected_scope."
                )
        else:
            if self.primary_driver is not None or scope or self.confidence is not None:
                raise DiagnosisValidationError(
                    "Non-success diagnosis cannot carry primary_driver, affected_scope, or confidence."
                )
            if self.status == DiagnosisStatus.TOOL_FAILURE and self.change is not None:
                raise DiagnosisValidationError("Tool-failure diagnosis must not carry target change.")
