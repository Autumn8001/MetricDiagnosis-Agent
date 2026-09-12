"""Deterministic scoring for unsupported Diagnosis claims.

The core evaluation scores a Diagnosis against Ground Truth.  This module
answers a different question: which verifiable facts did the Diagnosis itself
claim, and are those facts backed by Evidence that the Diagnosis actually
cited?  It deliberately does not load or inspect Ground Truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from app.diagnosis import DiagnosisComposition
from app.diagnosis.models import Diagnosis, DiagnosisStatus
from app.evidence import Evidence, EvidenceRole
from app.observations import ObservationStatus

from .models import EvaluationValidationError


class DiagnosisClaimKind(StrEnum):
    """Kinds of verifiable facts a successful Diagnosis may state."""

    TARGET_CHANGE = "target_change"
    PRIMARY_DRIVER = "primary_driver"
    SCOPE_MEMBER = "scope_member"


def _clean_component(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    cleaned = value.strip()
    if ":" in cleaned:
        raise EvaluationValidationError(
            f"Field '{field_name}' must not contain ':'."
        )
    return cleaned


def _clean_claim_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            "Field 'claim_id' must be a non-empty string."
        )
    return value.strip()


def _clean_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def derive_diagnosis_claim_id(
    kind: DiagnosisClaimKind,
    *,
    metric: str | None = None,
    dimension: str | None = None,
    dimension_value: str | None = None,
) -> str:
    """Derive the sole deterministic identity for a Diagnosis claim."""
    if not isinstance(kind, DiagnosisClaimKind):
        raise EvaluationValidationError(
            "Field 'kind' must be a DiagnosisClaimKind."
        )

    if kind in {
        DiagnosisClaimKind.TARGET_CHANGE,
        DiagnosisClaimKind.PRIMARY_DRIVER,
    }:
        clean_metric = _clean_component(metric, "metric")
        if dimension is not None or dimension_value is not None:
            raise EvaluationValidationError(
                f"{kind.value} claims cannot contain a dimension or dimension_value."
            )
        return f"claim:{kind.value}:{clean_metric}"

    if kind == DiagnosisClaimKind.SCOPE_MEMBER:
        if metric is not None:
            raise EvaluationValidationError(
                "scope_member claims must not contain a metric."
            )
        clean_dimension = _clean_component(dimension, "dimension")
        clean_value = _clean_component(dimension_value, "dimension_value")
        return f"claim:{kind.value}:{clean_dimension}:{clean_value}"

    # The enum is currently exhaustive.  Keep the branch explicit so a future
    # extension cannot silently acquire an identity or matching semantics.
    raise EvaluationValidationError(f"Unsupported DiagnosisClaimKind: {kind!r}.")


@dataclass(frozen=True)
class DiagnosisClaim:
    """One immutable, machine-checkable fact asserted by a Diagnosis."""

    claim_id: str
    kind: DiagnosisClaimKind
    metric: str | None = None
    dimension: str | None = None
    dimension_value: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DiagnosisClaimKind):
            raise EvaluationValidationError(
                "Field 'kind' must be a DiagnosisClaimKind."
            )

        clean_metric: str | None = None
        clean_dimension: str | None = None
        clean_value: str | None = None
        if self.kind in {
            DiagnosisClaimKind.TARGET_CHANGE,
            DiagnosisClaimKind.PRIMARY_DRIVER,
        }:
            clean_metric = _clean_component(self.metric, "metric")
            if self.dimension is not None or self.dimension_value is not None:
                raise EvaluationValidationError(
                    f"{self.kind.value} claims cannot contain a dimension or dimension_value."
                )
        elif self.kind == DiagnosisClaimKind.SCOPE_MEMBER:
            if self.metric is not None:
                raise EvaluationValidationError(
                    "scope_member claims must not contain a metric."
                )
            clean_dimension = _clean_component(self.dimension, "dimension")
            clean_value = _clean_component(self.dimension_value, "dimension_value")
        else:
            raise EvaluationValidationError(
                f"Unsupported DiagnosisClaimKind: {self.kind!r}."
            )

        clean_id = _clean_claim_id(self.claim_id)
        expected_id = derive_diagnosis_claim_id(
            self.kind,
            metric=clean_metric,
            dimension=clean_dimension,
            dimension_value=clean_value,
        )
        if clean_id != expected_id:
            raise EvaluationValidationError(
                "claim_id must equal the deterministic ID derived from kind "
                "and claim components."
            )

        object.__setattr__(self, "claim_id", clean_id)
        object.__setattr__(self, "metric", clean_metric)
        object.__setattr__(self, "dimension", clean_dimension)
        object.__setattr__(self, "dimension_value", clean_value)


def build_diagnosis_claims(diagnosis: Diagnosis) -> tuple[DiagnosisClaim, ...]:
    """Expand a Diagnosis into its ordered, auditable factual claims.

    A diagnosed result emits target, primary-driver, and each affected-scope
    member in the Diagnosis mapping's insertion order.  A no-anomaly result
    emits only its target-change claim.  Non-success terminal states make no
    successful factual assertions and therefore emit no claims.
    """
    if not isinstance(diagnosis, Diagnosis):
        raise EvaluationValidationError(
            f"Expected Diagnosis instance, got {type(diagnosis).__name__}."
        )

    if diagnosis.status == DiagnosisStatus.DIAGNOSED:
        # Diagnosis validation guarantees these values are present.  Re-check
        # at this boundary so this evaluator remains fail-closed if the domain
        # model evolves or an unusual object crosses the boundary.
        if diagnosis.primary_driver is None or not diagnosis.affected_scope:
            raise EvaluationValidationError(
                "Diagnosed Diagnosis must contain primary_driver and affected_scope."
            )
        claims: list[DiagnosisClaim] = [
            DiagnosisClaim(
                claim_id=derive_diagnosis_claim_id(
                    DiagnosisClaimKind.TARGET_CHANGE,
                    metric=diagnosis.target_metric,
                ),
                kind=DiagnosisClaimKind.TARGET_CHANGE,
                metric=diagnosis.target_metric,
            ),
            DiagnosisClaim(
                claim_id=derive_diagnosis_claim_id(
                    DiagnosisClaimKind.PRIMARY_DRIVER,
                    metric=diagnosis.primary_driver,
                ),
                kind=DiagnosisClaimKind.PRIMARY_DRIVER,
                metric=diagnosis.primary_driver,
            ),
        ]
        claims.extend(
            DiagnosisClaim(
                claim_id=derive_diagnosis_claim_id(
                    DiagnosisClaimKind.SCOPE_MEMBER,
                    dimension=dimension,
                    dimension_value=value,
                ),
                kind=DiagnosisClaimKind.SCOPE_MEMBER,
                dimension=dimension,
                dimension_value=value,
            )
            for dimension, value in diagnosis.affected_scope.items()
        )
        return tuple(claims)

    if diagnosis.status == DiagnosisStatus.NO_MATERIAL_ANOMALY:
        return (
            DiagnosisClaim(
                claim_id=derive_diagnosis_claim_id(
                    DiagnosisClaimKind.TARGET_CHANGE,
                    metric=diagnosis.target_metric,
                ),
                kind=DiagnosisClaimKind.TARGET_CHANGE,
                metric=diagnosis.target_metric,
            ),
        )

    if diagnosis.status in {
        DiagnosisStatus.INSUFFICIENT_EVIDENCE,
        DiagnosisStatus.BUDGET_EXHAUSTED,
        DiagnosisStatus.TOOL_FAILURE,
    }:
        return ()

    raise EvaluationValidationError(
        f"Unsupported DiagnosisStatus: {diagnosis.status!r}."
    )


def _context_matches(
    evidence: Evidence,
    dimension: str,
    expected_value: str,
) -> bool:
    """Match one scope member while rejecting conflicting representations."""
    filter_value = evidence.filters.get(dimension)
    row_value = evidence.dimensions.get(dimension)
    if filter_value is not None and row_value is not None and filter_value != row_value:
        return False
    actual_value = row_value if row_value is not None else filter_value
    return actual_value == expected_value


def _supports_scope(evidence: Evidence, scope: Mapping[str, str]) -> bool:
    """Require one unambiguous Evidence context to cover the complete scope."""
    return all(
        _context_matches(evidence, dimension, expected_value)
        for dimension, expected_value in scope.items()
    )


def _target_claim_supported(
    diagnosis: Diagnosis,
    claim: DiagnosisClaim,
    evidence_by_id: Mapping[str, Evidence],
    cited_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if diagnosis.change is None or claim.metric is None:
        return ()

    target_id = diagnosis.change.evidence_id
    if target_id not in set(cited_ids):
        return ()
    target = evidence_by_id.get(target_id)
    if target is None:
        return ()

    expected_status = (
        ObservationStatus.ANOMALOUS
        if diagnosis.status == DiagnosisStatus.DIAGNOSED
        else ObservationStatus.NORMAL
    )
    if not (
        target.evidence_id == target_id
        and target.metric == claim.metric
        and target.role == EvidenceRole.SUPPORTING
        and target.observation_status == expected_status
        and target.current_value == diagnosis.change.current_value
        and target.baseline_value == diagnosis.change.baseline_value
        and target.relative_change == diagnosis.change.relative_change
        and target.unit == diagnosis.change.unit
    ):
        return ()
    return (target_id,)


def _claim_supporting_ids(
    diagnosis: Diagnosis,
    claim: DiagnosisClaim,
    evidence_by_id: Mapping[str, Evidence],
    cited_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if claim.kind == DiagnosisClaimKind.TARGET_CHANGE:
        return _target_claim_supported(diagnosis, claim, evidence_by_id, cited_ids)

    if claim.kind == DiagnosisClaimKind.PRIMARY_DRIVER:
        return tuple(
            evidence_id
            for evidence_id in cited_ids
            if (
                (evidence := evidence_by_id[evidence_id]).metric == claim.metric
                and evidence.role == EvidenceRole.SUPPORTING
                and evidence.observation_status == ObservationStatus.ANOMALOUS
            )
        )

    if claim.kind == DiagnosisClaimKind.SCOPE_MEMBER:
        if claim.dimension is None or claim.dimension_value is None:
            return ()
        return tuple(
            evidence_id
            for evidence_id in cited_ids
            if (
                (evidence := evidence_by_id[evidence_id]).metric
                == diagnosis.primary_driver
                and evidence.role == EvidenceRole.SUPPORTING
                and evidence.observation_status == ObservationStatus.ANOMALOUS
                and _context_matches(evidence, claim.dimension, claim.dimension_value)
                and _supports_scope(evidence, diagnosis.affected_scope)
            )
        )

    return ()


def _snapshot_unique_ids(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        raise EvaluationValidationError(
            f"Field '{field_name}' must be an iterable of strings, not a string/mapping."
        )
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise EvaluationValidationError(
            f"Field '{field_name}' must be an iterable of strings."
        ) from exc
    result = tuple(_clean_claim_id(item) for item in values)
    if len(result) != len(set(result)):
        raise EvaluationValidationError(f"Field '{field_name}' must not contain duplicates.")
    return result


def _snapshot_support_map(value: object) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError(
            "Field 'supporting_evidence_ids_by_claim' must be a mapping."
        )
    snapshot: dict[str, tuple[str, ...]] = {}
    for claim_id, evidence_ids in value.items():
        clean_claim = _clean_claim_id(claim_id)
        if clean_claim in snapshot:
            raise EvaluationValidationError(
                "supporting_evidence_ids_by_claim must not contain duplicate claim IDs."
            )
        ids = _snapshot_unique_ids(
            evidence_ids,
            f"supporting_evidence_ids_by_claim[{clean_claim}]",
        )
        if not ids:
            raise EvaluationValidationError(
                "Every supported claim must have at least one supporting Evidence ID."
            )
        snapshot[clean_claim] = ids
    return MappingProxyType(snapshot)


def _validate_rate(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise EvaluationValidationError(f"Field '{field_name}' must be a Decimal.")
    try:
        valid = value.is_finite() and Decimal("0") <= value <= Decimal("1")
    except (ArithmeticError, ValueError):
        valid = False
    if not valid:
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a finite Decimal in [0, 1]."
        )
    return value


@dataclass(frozen=True)
class UnsupportedClaimScore:
    """Auditable unsupported-claim score for one Diagnosis composition."""

    diagnosis_id: str
    claim_ids: tuple[str, ...]
    supported_claim_ids: tuple[str, ...]
    unsupported_claim_ids: tuple[str, ...]
    supporting_evidence_ids_by_claim: Mapping[str, tuple[str, ...]]
    unsupported_claim_rate: Decimal | None

    def __post_init__(self) -> None:
        diagnosis_id = _clean_identifier(self.diagnosis_id, "diagnosis_id")
        claims = _snapshot_unique_ids(self.claim_ids, "claim_ids")
        supported = _snapshot_unique_ids(
            self.supported_claim_ids,
            "supported_claim_ids",
        )
        unsupported = _snapshot_unique_ids(
            self.unsupported_claim_ids,
            "unsupported_claim_ids",
        )
        support_map = _snapshot_support_map(self.supporting_evidence_ids_by_claim)

        claim_set = set(claims)
        supported_set = set(supported)
        unsupported_set = set(unsupported)
        if supported_set & unsupported_set:
            raise EvaluationValidationError(
                "supported_claim_ids and unsupported_claim_ids must be disjoint."
            )
        if supported_set | unsupported_set != claim_set:
            raise EvaluationValidationError(
                "supported_claim_ids and unsupported_claim_ids must exactly partition "
                "claim_ids."
            )
        if set(support_map) != supported_set:
            raise EvaluationValidationError(
                "supporting_evidence_ids_by_claim keys must exactly equal supported_claim_ids."
            )

        rate = self.unsupported_claim_rate
        if rate is not None:
            rate = _validate_rate(rate, "unsupported_claim_rate")
        if (not claims) != (rate is None):
            raise EvaluationValidationError(
                "unsupported_claim_rate must be None exactly when claim_ids is empty."
            )
        if claims:
            expected_rate = Decimal(len(unsupported)) / Decimal(len(claims))
            if rate != expected_rate:
                raise EvaluationValidationError(
                    "unsupported_claim_rate must equal unsupported claims divided by claims."
                )

        object.__setattr__(self, "diagnosis_id", diagnosis_id)
        object.__setattr__(self, "claim_ids", claims)
        object.__setattr__(self, "supported_claim_ids", supported)
        object.__setattr__(self, "unsupported_claim_ids", unsupported)
        object.__setattr__(self, "supporting_evidence_ids_by_claim", support_map)
        object.__setattr__(self, "unsupported_claim_rate", rate)


def score_unsupported_claims(
    composition: DiagnosisComposition,
) -> UnsupportedClaimScore:
    """Score claims against only the Evidence explicitly cited by Diagnosis."""
    if not isinstance(composition, DiagnosisComposition):
        raise EvaluationValidationError(
            f"Expected DiagnosisComposition instance, got {type(composition).__name__}."
        )

    diagnosis = composition.diagnosis
    claims = build_diagnosis_claims(diagnosis)
    cited_ids = tuple(diagnosis.evidence_ids)
    evidence_by_id = {item.evidence_id: item for item in composition.evidence}
    if set(cited_ids) - set(evidence_by_id):
        # DiagnosisComposition currently rejects this during construction.  The
        # explicit check keeps this scoring boundary fail-closed if that model
        # contract changes later.
        raise EvaluationValidationError(
            "Diagnosis cites Evidence absent from the composition portfolio."
        )

    supported: list[str] = []
    unsupported: list[str] = []
    support_map: dict[str, tuple[str, ...]] = {}
    for claim in claims:
        evidence_ids = _claim_supporting_ids(
            diagnosis,
            claim,
            evidence_by_id,
            cited_ids,
        )
        if evidence_ids:
            supported.append(claim.claim_id)
            support_map[claim.claim_id] = evidence_ids
        else:
            unsupported.append(claim.claim_id)

    rate = (
        None
        if not claims
        else Decimal(len(unsupported)) / Decimal(len(claims))
    )
    return UnsupportedClaimScore(
        diagnosis_id=diagnosis.diagnosis_id,
        claim_ids=tuple(claim.claim_id for claim in claims),
        supported_claim_ids=tuple(supported),
        unsupported_claim_ids=tuple(unsupported),
        supporting_evidence_ids_by_claim=support_map,
        unsupported_claim_rate=rate,
    )


__all__ = [
    "DiagnosisClaim",
    "DiagnosisClaimKind",
    "UnsupportedClaimScore",
    "build_diagnosis_claims",
    "derive_diagnosis_claim_id",
    "score_unsupported_claims",
]
