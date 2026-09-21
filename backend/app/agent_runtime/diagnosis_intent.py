"""Strict, fact-free structured output contract for diagnosis intent."""

from __future__ import annotations

from decimal import Decimal, DecimalException
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
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

    observation_id: StrictNonEmptyString = Field(
        description=(
            "Copy the observation_id character-for-character from the current tool output. "
            "Never invent, derive, shorten, or paraphrase an Observation ID."
        )
    )
    role: EvidenceRole = Field(
        description=(
            "Evidence role for this exact tool Observation: supporting, negative_control, "
            "or limitation."
        )
    )


class RuntimeScopeItem(BaseModel):
    """One affected-scope dimension/value pair for strict JSON arrays."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dimension: StrictNonEmptyString = Field(
        description="Affected-scope dimension copied from the selected tool Observation."
    )
    value: StrictNonEmptyString = Field(
        description="Affected-scope value copied from the selected tool Observation."
    )


class RuntimeDiagnosisIntent(BaseModel):
    """SDK structured output containing intent and references, never metric facts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_selections: tuple[RuntimeEvidenceSelection, ...] = Field(
        description=(
            "Select only Observations returned by the current tool run. For diagnosed status, "
            "at least one anomalous supporting selection must be the single Observation that "
            "has metric == primary_driver and whose filters/dimensions cover all affected_scope "
            "items; do not combine separate Evidence items to manufacture that support."
        )
    )
    status: DiagnosisStatus = Field(
        description="Use diagnosed only when all required Evidence constraints are jointly satisfied."
    )
    target_metric: StrictNonEmptyString = Field(
        description="Metric identifier from the semantic definition and current tool output."
    )
    target_evidence_id: StrictNonEmptyString | None = Field(
        description=(
            "Deterministic Evidence ID for the target Observation: "
            "evidence:{observation_id}:{role}. The observation_id portion must be copied "
            "character-for-character from tool output."
        )
    )
    driver_evidence_id: StrictNonEmptyString | None = Field(
        description=(
            "For diagnosed status, the deterministic Evidence ID of the one selected "
            "anomalous supporting Observation that jointly supports primary_driver and "
            "every affected_scope item. It must be included in evidence_ids; never use "
            "a different Evidence for driver versus scope."
        )
    )
    primary_driver: StrictNonEmptyString | None = Field(
        description=(
            "Metric identifier only, never a dimension or dimension value. For diagnosed status, "
            "one anomalous supporting Observation must satisfy metric == primary_driver and have "
            "filters/dimensions covering all affected_scope items. Do not combine different "
            "Evidence items."
        )
    )
    affected_scope: tuple[RuntimeScopeItem, ...] = Field(
        description=(
            "For diagnosed status, every item must be covered by the same anomalous supporting "
            "Observation whose metric == primary_driver and whose filters/dimensions cover all "
            "affected_scope items; do not splice scope from another Evidence item. Use an "
            "appropriate non-success status if no such Observation exists."
        )
    )
    evidence_ids: tuple[StrictNonEmptyString, ...] = Field(
        description=(
            "Deterministic Evidence IDs only, each derived from an exact selected Observation ID "
            "and role; unknown or invented references are invalid."
        )
    )
    confidence: StrictNonEmptyString | None = Field(
        description="Decimal confidence string in [0, 1], or null for non-success statuses."
    )
    limitations: tuple[StrictNonEmptyString, ...] = Field(
        description="Explicit limitations of the data-level diagnosis."
    )

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
        driver_evidence_id=_normalize_evidence_reference(
            intent.driver_evidence_id,
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
