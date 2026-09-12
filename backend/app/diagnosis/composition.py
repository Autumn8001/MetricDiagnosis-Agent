"""Compose Observation-backed Evidence into a structured Diagnosis.

This module is intentionally a small application boundary.  It sequences the
two existing resolvers without reimplementing any Evidence promotion or
Diagnosis validation rules:

    Observation catalog -> Evidence selection resolver -> Evidence portfolio
    -> Diagnosis draft resolver -> Diagnosis

The portfolio is retained in full so callers can audit Evidence that was
available to the diagnosis but not cited by it.
"""

import datetime
from dataclasses import dataclass
from typing import Sequence

from app.diagnosis.draft import DiagnosisDraft, resolve_diagnosis_draft
from app.diagnosis.models import Diagnosis, DiagnosisValidationError
from app.evidence.models import Evidence
from app.evidence.selection import (
    EvidenceSelectionDraft,
    resolve_evidence_selections,
)
from app.observations.models import Observation


def _snapshot_evidence(value: object) -> tuple[Evidence, ...]:
    """Take and validate the immutable Evidence portfolio snapshot."""
    if isinstance(value, (str, bytes, bytearray)):
        raise DiagnosisValidationError(
            "Field 'evidence' must be an iterable of Evidence, not a string-like value."
        )
    try:
        items = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise DiagnosisValidationError(
            "Field 'evidence' must be an iterable of Evidence."
        ) from exc
    if any(not isinstance(item, Evidence) for item in items):
        raise DiagnosisValidationError(
            "Every composition evidence item must be an Evidence instance."
        )
    evidence_ids = [item.evidence_id for item in items]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise DiagnosisValidationError(
            "Composition evidence must not contain duplicate evidence_id values."
        )
    return items


@dataclass(frozen=True)
class DiagnosisComposition:
    """Auditable Evidence portfolio paired with its resolved Diagnosis."""

    evidence: tuple[Evidence, ...]
    diagnosis: Diagnosis

    def __post_init__(self) -> None:
        evidence = _snapshot_evidence(self.evidence)
        if not isinstance(self.diagnosis, Diagnosis):
            raise DiagnosisValidationError(
                "Field 'diagnosis' must be a Diagnosis instance."
            )

        evidence_ids = {item.evidence_id for item in evidence}
        missing_ids = [
            evidence_id
            for evidence_id in self.diagnosis.evidence_ids
            if evidence_id not in evidence_ids
        ]
        if missing_ids:
            raise DiagnosisValidationError(
                "Diagnosis references Evidence absent from the composition portfolio: "
                + ", ".join(missing_ids)
            )
        object.__setattr__(self, "evidence", evidence)


def compose_diagnosis_from_observations(
    *,
    diagnosis_id: str,
    evidence_selection_draft: EvidenceSelectionDraft,
    diagnosis_draft: DiagnosisDraft,
    observation_catalog: Sequence[Observation],
    created_at: datetime.datetime,
) -> DiagnosisComposition:
    """Resolve selected Observations and a Diagnosis intent in sequence.

    The first resolver promotes only the explicitly selected Observations.  The
    resulting complete portfolio is then passed as the Evidence catalog to the
    second resolver, which selects the Diagnosis citations and delegates all
    cross-Evidence rules to the existing Diagnosis builder.  Domain exceptions
    intentionally propagate unchanged.
    """
    evidence_portfolio = resolve_evidence_selections(
        draft=evidence_selection_draft,
        observation_catalog=observation_catalog,
    )
    diagnosis = resolve_diagnosis_draft(
        diagnosis_id=diagnosis_id,
        draft=diagnosis_draft,
        evidence_catalog=evidence_portfolio,
        created_at=created_at,
    )
    return DiagnosisComposition(evidence=evidence_portfolio, diagnosis=diagnosis)


__all__ = ["DiagnosisComposition", "compose_diagnosis_from_observations"]
