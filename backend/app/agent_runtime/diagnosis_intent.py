"""Strict, fact-free structured output contract for diagnosis intent."""

from __future__ import annotations

from decimal import Decimal, DecimalException
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
)

from app.diagnosis import DiagnosisDraft, DiagnosisStatus, DiagnosisValidationError
from app.evidence import (
    EvidenceRole,
    EvidenceSelection,
    EvidenceSelectionDraft,
    EvidenceValidationError,
)


StrictNonEmptyString = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]


class RuntimeEvidenceSelection(BaseModel):
    """One model-selected Observation reference and evidential role."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    observation_id: StrictNonEmptyString
    role: EvidenceRole


class RuntimeScopeItem(BaseModel):
    """One affected-scope dimension/value pair for strict JSON arrays."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dimension: StrictNonEmptyString
    value: StrictNonEmptyString


class RuntimeDiagnosisIntent(BaseModel):
    """SDK structured output containing intent and references, never metric facts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_selections: tuple[RuntimeEvidenceSelection, ...]
    status: DiagnosisStatus
    target_metric: StrictNonEmptyString
    target_evidence_id: StrictNonEmptyString | None
    primary_driver: StrictNonEmptyString | None
    affected_scope: tuple[RuntimeScopeItem, ...]
    evidence_ids: tuple[StrictNonEmptyString, ...]
    confidence: StrictNonEmptyString | None
    limitations: tuple[StrictNonEmptyString, ...]

    @field_validator(
        "evidence_selections",
        "affected_scope",
        "evidence_ids",
        "limitations",
        mode="before",
    )
    @classmethod
    def _require_json_array(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("Structured output collection fields must be JSON arrays.")
        return tuple(value)


def _parse_confidence(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except (DecimalException, TypeError, ValueError) as exc:
        raise DiagnosisValidationError(
            "Runtime confidence must be a valid decimal string or None."
        ) from exc
    if not parsed.is_finite():
        raise DiagnosisValidationError("Runtime confidence must be finite.")
    return parsed


def _normalize_evidence_reference(
    value: str | None,
    selections: tuple[RuntimeEvidenceSelection, ...],
) -> str | None:
    """Normalize an unambiguous Observation-ID alias to its deterministic Evidence ID.

    Some compatible providers copy the selected ``observation_id`` into an
    Evidence-reference field instead of repeating the mechanical
    ``evidence:{observation_id}:{role}`` encoding.  Accept only the exact ID of
    one selected Observation/role pair; unknown or ambiguous references remain
    unchanged and are rejected by the downstream Evidence resolver.
    """
    if value is None:
        return None
    derived = {
        f"evidence:{item.observation_id}:{item.role.value}": item
        for item in selections
    }
    if value in derived:
        return value
    matches = [item for item in selections if item.observation_id == value]
    if len(matches) == 1:
        item = matches[0]
        return f"evidence:{item.observation_id}:{item.role.value}"
    return value


def runtime_intent_to_drafts(
    intent: RuntimeDiagnosisIntent,
) -> tuple[EvidenceSelectionDraft, DiagnosisDraft]:
    """Convert a schema-validated runtime intent into existing domain drafts."""
    if not isinstance(intent, RuntimeDiagnosisIntent):
        raise DiagnosisValidationError(
            f"Expected RuntimeDiagnosisIntent, got {type(intent).__name__}."
        )

    scope: dict[str, str] = {}
    for item in intent.affected_scope:
        if item.dimension in scope:
            raise DiagnosisValidationError(
                f"Runtime affected_scope contains duplicate dimension: '{item.dimension}'."
            )
        scope[item.dimension] = item.value

    try:
        evidence_draft = EvidenceSelectionDraft(
            [
                EvidenceSelection(item.observation_id, item.role)
                for item in intent.evidence_selections
            ]
        )
    except EvidenceValidationError as exc:
        raise DiagnosisValidationError("Invalid runtime Evidence selections.") from exc

    selections = tuple(intent.evidence_selections)
    diagnosis_draft = DiagnosisDraft(
        status=intent.status,
        target_metric=intent.target_metric,
        target_evidence_id=_normalize_evidence_reference(
            intent.target_evidence_id,
            selections,
        ),
        primary_driver=intent.primary_driver,
        affected_scope=scope,
        evidence_ids=tuple(
            _normalize_evidence_reference(item, selections)
            for item in intent.evidence_ids
        ),
        confidence=_parse_confidence(intent.confidence),
        limitations=intent.limitations,
    )
    return evidence_draft, diagnosis_draft


__all__ = [
    "RuntimeDiagnosisIntent",
    "RuntimeEvidenceSelection",
    "RuntimeScopeItem",
    "runtime_intent_to_drafts",
]
