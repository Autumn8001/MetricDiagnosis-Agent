"""Explicit promotion functions transforming Observations into immutable Evidence."""

from app.evidence.models import (
    Evidence,
    EvidenceError,
    EvidenceRole,
    EvidenceValidationError,
    _derive_evidence_id,
)
from app.observations.models import Observation


def promote_observation_to_evidence(
    observation: Observation,
    *,
    role: EvidenceRole,
) -> Evidence:
    """Explicitly promote a selected Observation to an immutable Evidence.

    Requirements:
    - role must be explicitly provided by the caller as an EvidenceRole enum.
    - All business numbers, periods, dimensions, and trace fields are faithfully copied from observation.
    - Deterministic evidence_id is derived from observation_id and role ('evidence:{obs_id}:{role}').
    - Repromoting the same Observation with the same role yields identical deterministic Evidence.
    """
    if not isinstance(observation, Observation):
        raise EvidenceValidationError(f"Expected Observation instance, got {type(observation).__name__}.")

    if not isinstance(role, EvidenceRole):
        raise EvidenceValidationError(f"Expected EvidenceRole enum, got {type(role).__name__}.")

    evidence_id = _derive_evidence_id(observation.observation_id, role)

    return Evidence(
        evidence_id=evidence_id,
        observation_id=observation.observation_id,
        role=role,
        tool_name=observation.tool_name,
        tool_call_id=observation.tool_call_id,
        metric=observation.metric,
        current_period=observation.current_period,
        baseline_period=observation.baseline_period,
        filters=observation.filters,
        group_by=observation.group_by,
        dimensions=observation.dimensions,
        current_value=observation.current_value,
        baseline_value=observation.baseline_value,
        relative_change=observation.relative_change,
        unit=observation.unit,
        sample_size=observation.sample_size,
        observation_status=observation.status,
        source_status=observation.source_status,
        query_or_result_reference=observation.query_or_result_reference,
        created_at=observation.created_at,
        error_code=observation.error_code,
        error_message=observation.error_message,
    )
