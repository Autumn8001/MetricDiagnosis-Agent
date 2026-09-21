"""Explicit Evidence-aware builder for structured Diagnosis objects."""

import datetime
from decimal import Decimal
from typing import Mapping, Sequence

from app.diagnosis.models import (
    Diagnosis,
    DiagnosisChange,
    DiagnosisStatus,
    DiagnosisValidationError,
)
from app.evidence.models import Evidence, EvidenceRole
from app.observations.models import ObservationStatus


def _evidence_snapshot(evidence: Sequence[Evidence]) -> tuple[Evidence, ...]:
    try:
        snapshot = tuple(evidence)
    except TypeError as exc:
        raise DiagnosisValidationError("'evidence' must be a sequence of Evidence.") from exc
    if any(not isinstance(item, Evidence) for item in snapshot):
        raise DiagnosisValidationError("Every evidence item must be an Evidence instance.")
    ids = [item.evidence_id for item in snapshot]
    if len(ids) != len(set(ids)):
        raise DiagnosisValidationError("Evidence input contains duplicate evidence_id values.")
    return snapshot


def _find_evidence(evidence: tuple[Evidence, ...], evidence_id: str | None) -> Evidence | None:
    if evidence_id is None:
        return None
    matches = [item for item in evidence if item.evidence_id == evidence_id]
    if len(matches) != 1:
        raise DiagnosisValidationError(
            f"target_evidence_id must identify exactly one supplied Evidence: '{evidence_id}'."
        )
    return matches[0]


def _supports_scope(item: Evidence, scope: Mapping[str, str]) -> bool:
    for key, value in scope.items():
        filter_value = item.filters.get(key)
        dimension_value = item.dimensions.get(key)
        if (
            filter_value is not None
            and dimension_value is not None
            and filter_value != dimension_value
        ):
            return False
        actual_value = dimension_value if dimension_value is not None else filter_value
        if actual_value != value:
            return False
    return True


def build_diagnosis(
    *,
    diagnosis_id: str,
    status: DiagnosisStatus,
    target_metric: str,
    evidence: Sequence[Evidence],
    target_evidence_id: str | None = None,
    driver_evidence_id: str | None = None,
    primary_driver: str | None = None,
    affected_scope: Mapping[str, str] | None = None,
    confidence: Decimal | None = None,
    limitations: Sequence[str],
    created_at: datetime.datetime,
) -> Diagnosis:
    """Build a Diagnosis whose values and claims are supported by supplied Evidence."""
    items = _evidence_snapshot(evidence)
    target = _find_evidence(items, target_evidence_id)
    change = None
    if target is not None:
        change = DiagnosisChange(
            current_value=target.current_value,
            baseline_value=target.baseline_value,
            relative_change=target.relative_change,
            unit=target.unit,
            evidence_id=target.evidence_id,
        )
    scope = dict(affected_scope or {})

    if status == DiagnosisStatus.DIAGNOSED:
        if target is None:
            raise DiagnosisValidationError("Diagnosed status requires target Evidence.")
        if not (
            target.metric == target_metric
            and target.role == EvidenceRole.SUPPORTING
            and target.observation_status == ObservationStatus.ANOMALOUS
        ):
            raise DiagnosisValidationError(
                "Target change must come from anomalous supporting Evidence for target_metric."
            )
        driver_at_scope_support = [
            item for item in items
            if item.metric == primary_driver
            and item.role == EvidenceRole.SUPPORTING
            and item.observation_status == ObservationStatus.ANOMALOUS
            and _supports_scope(item, scope)
        ]
        if not scope or not driver_at_scope_support:
            raise DiagnosisValidationError(
                "primary_driver and affected_scope must be jointly supported by one "
                "anomalous supporting Evidence item."
            )
        if driver_evidence_id is not None:
            selected_driver = _find_evidence(items, driver_evidence_id)
            if selected_driver not in driver_at_scope_support:
                raise DiagnosisValidationError(
                    "driver_evidence_id must identify the anomalous supporting Evidence "
                    "that jointly supports primary_driver and affected_scope."
                )
        if not any(item.role == EvidenceRole.NEGATIVE_CONTROL for item in items):
            raise DiagnosisValidationError("Diagnosed status requires negative-control Evidence.")
    elif status == DiagnosisStatus.NO_MATERIAL_ANOMALY:
        if target is None:
            raise DiagnosisValidationError("No-material-anomaly status requires target Evidence.")
        if not (
            target.metric == target_metric
            and target.role == EvidenceRole.SUPPORTING
            and target.observation_status == ObservationStatus.NORMAL
        ):
            raise DiagnosisValidationError(
                "No-material-anomaly target must be normal supporting Evidence for target_metric."
            )
        if any(
            item.role != EvidenceRole.LIMITATION
            and item.observation_status == ObservationStatus.ANOMALOUS
            for item in items
        ):
            raise DiagnosisValidationError(
                "No-material-anomaly diagnosis cannot cite anomalous non-limitation Evidence."
            )
    elif status == DiagnosisStatus.INSUFFICIENT_EVIDENCE:
        if items and not any(item.role == EvidenceRole.LIMITATION for item in items):
            raise DiagnosisValidationError(
                "Insufficient-evidence diagnosis may only be justified with limitation Evidence."
            )
    elif status == DiagnosisStatus.TOOL_FAILURE:
        if items:
            if any(item.role != EvidenceRole.LIMITATION for item in items) or not any(
                item.role == EvidenceRole.LIMITATION
                and item.observation_status == ObservationStatus.FAILED
                for item in items
            ):
                raise DiagnosisValidationError(
                    "Tool-failure Evidence must be FAILED limitation Evidence."
                )

    return Diagnosis(
        diagnosis_id=diagnosis_id,
        status=status,
        target_metric=target_metric,
        change=change,
        primary_driver=primary_driver,
        affected_scope=scope,
        evidence_ids=tuple(item.evidence_id for item in items),
        confidence=confidence,
        limitations=tuple(limitations),
        created_at=created_at,
    )
