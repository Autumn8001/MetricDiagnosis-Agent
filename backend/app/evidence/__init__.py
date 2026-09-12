"""Evidence package for MetricSleuth.

Provides immutable Evidence domain models, role contracts, and promotion functions
transforming selected Observations into traceable Evidence.
"""

from app.evidence.models import (
    Evidence,
    EvidenceError,
    EvidenceRole,
    EvidenceValidationError,
)
from app.evidence.promoter import promote_observation_to_evidence
from app.evidence.selection import (
    EvidenceSelection,
    EvidenceSelectionDraft,
    resolve_evidence_selections,
)

__all__ = [
    "Evidence",
    "EvidenceError",
    "EvidenceRole",
    "EvidenceValidationError",
    "promote_observation_to_evidence",
    "EvidenceSelection",
    "EvidenceSelectionDraft",
    "resolve_evidence_selections",
]
