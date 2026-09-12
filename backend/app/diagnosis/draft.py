"""Resolution of untrusted structured Diagnosis drafts into domain objects.

The future agent runtime may describe its intended diagnosis, but it must not be
allowed to provide metric facts or manufacture Evidence.  This module keeps the
runtime-facing draft intentionally small and resolves every cited Evidence ID
against an application-owned catalog before delegating to ``build_diagnosis``.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Sequence

from app.diagnosis.builder import build_diagnosis
from app.diagnosis.models import Diagnosis, DiagnosisStatus, DiagnosisValidationError
from app.evidence.models import Evidence


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiagnosisValidationError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _validate_decimal(value: Decimal | None, field_name: str) -> None:
    if value is not None and not isinstance(value, Decimal):
        raise DiagnosisValidationError(
            f"Field '{field_name}' must be Decimal or None, got {type(value).__name__}."
        )


def _snapshot_strings(value: object, field_name: str) -> tuple[str, ...]:
    """Copy and validate a string collection without accepting a scalar string."""
    if isinstance(value, (str, bytes, bytearray)):
        raise DiagnosisValidationError(
            f"Field '{field_name}' must be an iterable of strings, not a string."
        )
    try:
        items = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise DiagnosisValidationError(
            f"Field '{field_name}' must be an iterable of strings."
        ) from exc
    try:
        cleaned = tuple(_clean_string(item, f"{field_name} item") for item in items)
    except DiagnosisValidationError:
        raise
    if len(cleaned) != len(set(cleaned)):
        raise DiagnosisValidationError(f"Field '{field_name}' must not contain duplicates.")
    return cleaned


@dataclass(frozen=True)
class DiagnosisDraft:
    """Minimal, fact-free intent submitted for deterministic diagnosis resolution.

    A draft contains claims and Evidence identifiers only.  It deliberately has
    no metric values, unit, change object, or root-cause field; those facts must
    be copied from resolved Evidence by ``build_diagnosis``.
    """

    status: DiagnosisStatus
    target_metric: str
    target_evidence_id: str | None
    primary_driver: str | None
    affected_scope: Mapping[str, str]
    evidence_ids: tuple[str, ...]
    confidence: Decimal | None
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, DiagnosisStatus):
            raise DiagnosisValidationError("Field 'status' must be a DiagnosisStatus.")
        object.__setattr__(self, "target_metric", _clean_string(self.target_metric, "target_metric"))

        if self.target_evidence_id is not None:
            object.__setattr__(
                self,
                "target_evidence_id",
                _clean_string(self.target_evidence_id, "target_evidence_id"),
            )
        if self.primary_driver is not None:
            object.__setattr__(
                self,
                "primary_driver",
                _clean_string(self.primary_driver, "primary_driver"),
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

        object.__setattr__(self, "evidence_ids", _snapshot_strings(self.evidence_ids, "evidence_ids"))
        limitations = _snapshot_strings(self.limitations, "limitations")
        if not limitations:
            raise DiagnosisValidationError("Field 'limitations' must contain at least one item.")
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


def _snapshot_catalog(evidence_catalog: Sequence[Evidence]) -> tuple[Evidence, ...]:
    if isinstance(evidence_catalog, (str, bytes, bytearray)):
        raise DiagnosisValidationError(
            "'evidence_catalog' must be an iterable of Evidence, not a string."
        )
    try:
        catalog = tuple(evidence_catalog)
    except TypeError as exc:
        raise DiagnosisValidationError(
            "'evidence_catalog' must be an iterable of Evidence."
        ) from exc
    if any(not isinstance(item, Evidence) for item in catalog):
        raise DiagnosisValidationError("Every evidence_catalog item must be an Evidence instance.")
    ids = [item.evidence_id for item in catalog]
    if len(ids) != len(set(ids)):
        raise DiagnosisValidationError("Evidence catalog contains duplicate evidence_id values.")
    return catalog


def resolve_diagnosis_draft(
    *,
    diagnosis_id: str,
    draft: DiagnosisDraft,
    evidence_catalog: Sequence[Evidence],
    created_at: datetime.datetime,
) -> Diagnosis:
    """Resolve a runtime draft against real Evidence and build a Diagnosis.

    Resolution is fail-closed: every cited ID must exist exactly once in the
    catalog, and only cited Evidence is passed to the existing domain builder.
    The builder remains the single authority for cross-Evidence status rules.
    """
    if not isinstance(draft, DiagnosisDraft):
        raise DiagnosisValidationError(
            f"Expected DiagnosisDraft instance, got {type(draft).__name__}."
        )

    catalog = _snapshot_catalog(evidence_catalog)
    by_id = {item.evidence_id: item for item in catalog}

    if (
        draft.target_evidence_id is not None
        and draft.target_evidence_id not in draft.evidence_ids
    ):
        raise DiagnosisValidationError(
            "target_evidence_id must be included in draft.evidence_ids."
        )

    selected: list[Evidence] = []
    for evidence_id in draft.evidence_ids:
        item = by_id.get(evidence_id)
        if item is None:
            raise DiagnosisValidationError(
                f"Draft references unknown evidence_id: '{evidence_id}'."
            )
        selected.append(item)

    return build_diagnosis(
        diagnosis_id=diagnosis_id,
        status=draft.status,
        target_metric=draft.target_metric,
        evidence=selected,
        target_evidence_id=draft.target_evidence_id,
        primary_driver=draft.primary_driver,
        affected_scope=draft.affected_scope,
        confidence=draft.confidence,
        limitations=draft.limitations,
        created_at=created_at,
    )


__all__ = ["DiagnosisDraft", "resolve_diagnosis_draft"]
