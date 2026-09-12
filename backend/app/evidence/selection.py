"""Resolve runtime Evidence selections against application-owned Observations.

The runtime-facing objects in this module contain only references and explicit
role intent.  They deliberately do not carry any observation facts.  Resolution
looks up the referenced, immutable Observation and delegates promotion to the
existing Evidence promoter, keeping the promoter as the single authority for
status/role compatibility and Evidence construction.
"""

from dataclasses import dataclass
from typing import Sequence

from app.evidence.models import Evidence, EvidenceRole, EvidenceValidationError
from app.evidence.promoter import promote_observation_to_evidence
from app.observations.models import Observation


def _clean_observation_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(
            "Field 'observation_id' must be a non-empty string."
        )
    return value.strip()


def _snapshot_iterable(value: object, field_name: str) -> tuple[object, ...]:
    """Create an immutable input snapshot and normalize iterable failures."""
    if isinstance(value, (str, bytes, bytearray)):
        raise EvidenceValidationError(
            f"Field '{field_name}' must be an iterable, not a string-like value."
        )
    try:
        return tuple(value)  # type: ignore[arg-type]
    except EvidenceValidationError:
        raise
    except Exception as exc:
        raise EvidenceValidationError(
            f"Field '{field_name}' must be a valid iterable."
        ) from exc


@dataclass(frozen=True)
class EvidenceSelection:
    """A fact-free request to promote one Observation for an explicit role."""

    observation_id: str
    role: EvidenceRole

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _clean_observation_id(self.observation_id),
        )
        if not isinstance(self.role, EvidenceRole):
            raise EvidenceValidationError(
                "Field 'role' must be an EvidenceRole enum."
            )


@dataclass(frozen=True)
class EvidenceSelectionDraft:
    """Ordered, immutable and fact-free Evidence promotion selections."""

    selections: tuple[EvidenceSelection, ...]

    def __post_init__(self) -> None:
        items = _snapshot_iterable(self.selections, "selections")
        if any(not isinstance(item, EvidenceSelection) for item in items):
            raise EvidenceValidationError(
                "Every selection must be an EvidenceSelection instance."
            )

        typed_items = tuple(item for item in items if isinstance(item, EvidenceSelection))
        pairs = [(item.observation_id, item.role) for item in typed_items]
        if len(pairs) != len(set(pairs)):
            raise EvidenceValidationError(
                "EvidenceSelectionDraft must not contain duplicate (observation_id, role) pairs."
            )
        object.__setattr__(self, "selections", typed_items)


def _snapshot_observation_catalog(
    observation_catalog: Sequence[Observation],
) -> tuple[Observation, ...]:
    items = _snapshot_iterable(observation_catalog, "observation_catalog")
    if any(not isinstance(item, Observation) for item in items):
        raise EvidenceValidationError(
            "Every observation_catalog item must be an Observation instance."
        )

    typed_items = tuple(item for item in items if isinstance(item, Observation))
    observation_ids = [item.observation_id for item in typed_items]
    if len(observation_ids) != len(set(observation_ids)):
        raise EvidenceValidationError(
            "Observation catalog contains duplicate observation_id values."
        )
    return typed_items


def resolve_evidence_selections(
    *,
    draft: EvidenceSelectionDraft,
    observation_catalog: Sequence[Observation],
) -> tuple[Evidence, ...]:
    """Resolve explicit selections into Evidence backed by real Observations.

    Resolution is fail-closed: the complete Observation catalog is validated,
    every selected ID must exist exactly once, and no unselected Observation is
    promoted.  Role compatibility and all Evidence field copying are delegated
    to ``promote_observation_to_evidence``.
    """
    if not isinstance(draft, EvidenceSelectionDraft):
        raise EvidenceValidationError(
            f"Expected EvidenceSelectionDraft instance, got {type(draft).__name__}."
        )

    catalog = _snapshot_observation_catalog(observation_catalog)
    by_id = {item.observation_id: item for item in catalog}

    resolved: list[Evidence] = []
    for selection in draft.selections:
        observation = by_id.get(selection.observation_id)
        if observation is None:
            raise EvidenceValidationError(
                f"Draft references unknown observation_id: '{selection.observation_id}'."
            )

        # Preserve EvidenceValidationError from the promoter.  It is the domain
        # authority for illegal ObservationStatus/EvidenceRole combinations.
        resolved.append(
            promote_observation_to_evidence(observation, role=selection.role)
        )

    evidence_ids = [item.evidence_id for item in resolved]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise EvidenceValidationError(
            "Resolved Evidence contains duplicate evidence_id values."
        )
    return tuple(resolved)


__all__ = [
    "EvidenceSelection",
    "EvidenceSelectionDraft",
    "resolve_evidence_selections",
]
