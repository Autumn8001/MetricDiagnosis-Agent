"""Hermetic, deterministic orchestration for Evaluation score production.

The runner accepts already-materialized Ground Truth cases and already-observed
run outcomes.  It deliberately does not load Ground Truth, invoke an agent,
call an SDK, access a database, or read files.  Those concerns belong to the
caller; this module only validates identities and composes the existing pure
per-case scorers and aggregate report builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Sequence

from app.diagnosis.models import DiagnosisStatus

from .aggregate import aggregate_core_scores
from .evidence_obligations import build_evidence_obligations
from .evidence_scorer import EvidenceCitationScore, score_evidence_citations
from .manifest import EvaluationManifest
from .models import (
    CoreCaseScore,
    EvaluationValidationError,
    GroundTruthCase,
)
from .operational import (
    EvaluationRunOutcome,
    EvaluationRunStatus,
    ToolOperationalScore,
    score_tool_operations,
)
from .operational_aggregate import aggregate_tool_operations
from .scorer import score_core_case
from .unified import UnifiedEvaluationReport, build_unified_evaluation_report
from .unsupported_claims import UnsupportedClaimScore, score_unsupported_claims
from app.diagnosis import DiagnosisComposition


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def _snapshot_records(value: object) -> tuple["EvaluationRunRecord", ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise EvaluationValidationError(
            "records must be a non-empty sequence of EvaluationRunRecord."
        )
    records = tuple(value)
    if not records:
        raise EvaluationValidationError("records must not be empty.")
    if any(not isinstance(record, EvaluationRunRecord) for record in records):
        raise EvaluationValidationError(
            "records must contain only EvaluationRunRecord instances."
        )
    run_ids = tuple(record.run_id for record in records)
    if len(run_ids) != len(set(run_ids)):
        raise EvaluationValidationError(
            "records must not contain duplicate run_id values."
        )
    case_ids = tuple(record.case.case_id for record in records)
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationValidationError(
            "records must not contain duplicate case_id values."
        )
    return records


@dataclass(frozen=True)
class EvaluationRunRecord:
    """One immutable Case plus its distinct run identity, observed outcome, and optional diagnosis.

    ``run_id`` is the distinct identity of a single execution of a case.
    ``case`` is the evaluation-side expected result, while ``outcome`` is an
    explicit observation of the run.  They are intentionally separate so a
    runtime failure can remain in operational and core denominators without
    fabricating a Diagnosis.
    """

    run_id: str
    case: GroundTruthCase
    outcome: EvaluationRunOutcome
    composition: DiagnosisComposition | None = None

    def __post_init__(self) -> None:
        run_id = _clean_string(self.run_id, "run_id")
        object.__setattr__(self, "run_id", run_id)
        if not isinstance(self.case, GroundTruthCase):
            raise EvaluationValidationError(
                "Field 'case' must be a GroundTruthCase instance."
            )
        if not isinstance(self.outcome, EvaluationRunOutcome):
            raise EvaluationValidationError(
                "Field 'outcome' must be an EvaluationRunOutcome instance."
            )
        if self.case.case_id != self.outcome.case_id:
            raise EvaluationValidationError(
                "case.case_id must equal outcome.case_id."
            )
        if self.composition is not None and not isinstance(
            self.composition, DiagnosisComposition
        ):
            raise EvaluationValidationError(
                "Field 'composition' must be DiagnosisComposition or None."
            )

        status = self.outcome.status
        diagnosis_status = (
            None
            if self.composition is None
            else self.composition.diagnosis.status
        )
        if status == EvaluationRunStatus.COMPLETED:
            if self.composition is None:
                raise EvaluationValidationError(
                    "Completed runs must include a DiagnosisComposition."
                )
            if diagnosis_status in {
                DiagnosisStatus.BUDGET_EXHAUSTED,
                DiagnosisStatus.TOOL_FAILURE,
            }:
                raise EvaluationValidationError(
                    "Completed outcomes cannot carry terminal failure diagnosis."
                )
        elif status == EvaluationRunStatus.RUNTIME_FAILURE:
            if self.composition is not None:
                raise EvaluationValidationError(
                    "Runtime-failure runs must not include a DiagnosisComposition."
                )
        elif status == EvaluationRunStatus.BUDGET_EXHAUSTED:
            if (
                diagnosis_status is not None
                and diagnosis_status != DiagnosisStatus.BUDGET_EXHAUSTED
            ):
                raise EvaluationValidationError(
                    "Budget-exhausted outcomes require a budget_exhausted Diagnosis."
                )
        elif status == EvaluationRunStatus.TOOL_FAILURE:
            if (
                diagnosis_status is not None
                and diagnosis_status != DiagnosisStatus.TOOL_FAILURE
            ):
                raise EvaluationValidationError(
                    "Tool-failure outcomes require a tool_failure Diagnosis."
                )
        else:
            # EvaluationRunOutcome currently validates this enum.  Keep the
            # branch explicit so a future status cannot bypass this contract.
            raise EvaluationValidationError(
                f"Unsupported EvaluationRunStatus: {status!r}."
            )


@dataclass(frozen=True)
class EvaluationCaseScoreBundle:
    """All per-run score vectors, retaining their separate identity domains."""

    case_id: str
    core_score: CoreCaseScore
    evidence_score: EvidenceCitationScore
    unsupported_claim_score: UnsupportedClaimScore | None
    operational_score: ToolOperationalScore

    def __post_init__(self) -> None:
        case_id = _clean_string(self.case_id, "case_id")
        if not isinstance(self.core_score, CoreCaseScore):
            raise EvaluationValidationError(
                "Field 'core_score' must be a CoreCaseScore instance."
            )
        if not isinstance(self.evidence_score, EvidenceCitationScore):
            raise EvaluationValidationError(
                "Field 'evidence_score' must be an EvidenceCitationScore instance."
            )
        if not isinstance(self.operational_score, ToolOperationalScore):
            raise EvaluationValidationError(
                "Field 'operational_score' must be a ToolOperationalScore instance."
            )
        if self.unsupported_claim_score is not None and not isinstance(
            self.unsupported_claim_score, UnsupportedClaimScore
        ):
            raise EvaluationValidationError(
                "Field 'unsupported_claim_score' must be UnsupportedClaimScore or None."
            )

        child_case_ids = (
            self.core_score.case_id,
            self.evidence_score.case_id,
            self.operational_score.case_id,
        )
        if any(child_case_id != case_id for child_case_id in child_case_ids):
            raise EvaluationValidationError(
                "case_id must match core, evidence, and operational score case IDs."
            )
        object.__setattr__(self, "case_id", case_id)


def _empty_core_score(case: GroundTruthCase) -> CoreCaseScore:
    """Represent an unscorable run without inventing a Diagnosis."""
    return CoreCaseScore(
        case_id=case.case_id,
        status_correct=False,
        target_metric_correct=False,
        driver_correct=False,
        scope_correct={
            "marketplace": False,
            "asin": False,
            "traffic_source": False,
        },
        scope_accuracy=Decimal("0"),
        exact_match=False,
        no_anomaly_correct=False,
    )


def _empty_evidence_score(case: GroundTruthCase) -> EvidenceCitationScore:
    obligations = build_evidence_obligations(case)
    return EvidenceCitationScore(
        case_id=case.case_id,
        cited_evidence_ids=(),
        matched_citation_ids=(),
        unsupported_citation_ids=(),
        obligation_ids=tuple(item.obligation_id for item in obligations),
        covered_obligation_ids=(),
        citation_precision=None,
        evidence_coverage=Decimal("0"),
    )


def score_evaluation_run_record(
    record: EvaluationRunRecord,
) -> EvaluationCaseScoreBundle:
    """Score one explicit run record using the existing pure score functions."""
    if not isinstance(record, EvaluationRunRecord):
        raise EvaluationValidationError(
            "Expected EvaluationRunRecord instance, "
            f"got {type(record).__name__}."
        )

    if record.composition is None:
        core_score = _empty_core_score(record.case)
        evidence_score = _empty_evidence_score(record.case)
        unsupported_score = None
    else:
        core_score = score_core_case(
            record.case,
            record.composition.diagnosis,
        )
        evidence_score = score_evidence_citations(
            record.case,
            record.composition,
        )
        unsupported_score = score_unsupported_claims(record.composition)

    operational_score = score_tool_operations(record.outcome)
    return EvaluationCaseScoreBundle(
        case_id=record.case.case_id,
        core_score=core_score,
        evidence_score=evidence_score,
        unsupported_claim_score=unsupported_score,
        operational_score=operational_score,
    )


@dataclass(frozen=True)
class HermeticEvaluationResult:
    """Immutable per-case bundles plus their unified aggregate report."""

    bundles: tuple[EvaluationCaseScoreBundle, ...]
    report: UnifiedEvaluationReport

    def __post_init__(self) -> None:
        if isinstance(self.bundles, (str, bytes, bytearray)):
            raise EvaluationValidationError(
                "Field 'bundles' must be a non-empty sequence of bundles."
            )
        try:
            bundles = tuple(self.bundles)
        except TypeError as exc:
            raise EvaluationValidationError(
                "Field 'bundles' must be a non-empty sequence of bundles."
            ) from exc
        if not bundles:
            raise EvaluationValidationError("Field 'bundles' must not be empty.")
        if any(not isinstance(bundle, EvaluationCaseScoreBundle) for bundle in bundles):
            raise EvaluationValidationError(
                "bundles must contain only EvaluationCaseScoreBundle instances."
            )
        bundle_case_ids = tuple(bundle.case_id for bundle in bundles)
        if len(bundle_case_ids) != len(set(bundle_case_ids)):
            raise EvaluationValidationError(
                "bundles must not contain duplicate case IDs."
            )
        if not isinstance(self.report, UnifiedEvaluationReport):
            raise EvaluationValidationError(
                "Field 'report' must be a UnifiedEvaluationReport instance."
            )

        if self.report.core_report.case_ids != bundle_case_ids:
            raise EvaluationValidationError(
                "report core case IDs must match bundles in order."
            )
        if self.report.operational_report.run_ids != bundle_case_ids:
            raise EvaluationValidationError(
                "report operational run IDs must match bundles in order."
            )
        if tuple(item.case_id for item in self.report.evidence_scores) != bundle_case_ids:
            raise EvaluationValidationError(
                "report evidence case IDs must match bundles in order."
            )

        expected_claim_scores = tuple(
            bundle.unsupported_claim_score
            for bundle in bundles
            if bundle.unsupported_claim_score is not None
        )
        if self.report.unsupported_claim_scores != expected_claim_scores:
            raise EvaluationValidationError(
                "report unsupported claim scores must match bundle scores in order."
            )
        object.__setattr__(self, "bundles", bundles)


def run_hermetic_evaluation(
    records: Sequence[EvaluationRunRecord],
) -> HermeticEvaluationResult:
    """Score and aggregate explicit records in input order.

    This function is intentionally a pure orchestration boundary.  It does not
    call the SDK, load a Ground Truth file, access a database, read the
    filesystem, or infer failure facts from exception text.
    """
    frozen_records = _snapshot_records(records)
    bundles = tuple(score_evaluation_run_record(record) for record in frozen_records)

    core_report = aggregate_core_scores(
        tuple(bundle.core_score for bundle in bundles)
    )
    evidence_scores = tuple(bundle.evidence_score for bundle in bundles)
    unsupported_scores = tuple(
        bundle.unsupported_claim_score
        for bundle in bundles
        if bundle.unsupported_claim_score is not None
    )
    operational_report = aggregate_tool_operations(
        tuple(bundle.operational_score for bundle in bundles)
    )
    report = build_unified_evaluation_report(
        core_report,
        evidence_scores,
        unsupported_scores,
        operational_report,
    )
    return HermeticEvaluationResult(bundles=bundles, report=report)


@dataclass(frozen=True, init=False)
class ManifestEvaluationRunSet:
    """Immutable collection of EvaluationRunRecords reconciled against an EvaluationManifest.

    Enforces that every record has a unique run_id, all declared cases exist with
    their exact required run counts, and no undeclared cases or extra runs exist.
    """

    manifest: EvaluationManifest
    records: tuple[EvaluationRunRecord, ...]
    actual_run_counts_by_case: Mapping[str, int]

    def __init__(
        self,
        manifest: EvaluationManifest,
        records: Sequence[EvaluationRunRecord],
    ) -> None:
        if not isinstance(manifest, EvaluationManifest):
            raise EvaluationValidationError(
                "Field 'manifest' must be an EvaluationManifest instance."
            )
        if (
            isinstance(records, (str, bytes, bytearray))
            or not isinstance(records, Sequence)
        ):
            raise EvaluationValidationError(
                "Field 'records' must be a non-empty sequence of EvaluationRunRecord."
            )
        frozen_records = tuple(records)
        if not frozen_records:
            raise EvaluationValidationError(
                "Field 'records' must not be empty."
            )
        if any(not isinstance(record, EvaluationRunRecord) for record in frozen_records):
            raise EvaluationValidationError(
                "Field 'records' must contain only EvaluationRunRecord instances."
            )

        run_ids = tuple(record.run_id for record in frozen_records)
        if len(run_ids) != len(set(run_ids)):
            raise EvaluationValidationError(
                "Field 'records' must not contain duplicate run_id values."
            )

        actual_counts_raw: dict[str, int] = {}
        for record in frozen_records:
            case_id = record.case.case_id
            actual_counts_raw[case_id] = actual_counts_raw.get(case_id, 0) + 1

        undeclared_case_ids = set(actual_counts_raw.keys()) - set(manifest.run_counts_by_case.keys())
        if undeclared_case_ids:
            raise EvaluationValidationError(
                f"Records contain case_id(s) not declared in manifest: {sorted(undeclared_case_ids)}."
            )

        actual_counts: dict[str, int] = {}
        for case_id, expected_count in manifest.run_counts_by_case.items():
            actual_count = actual_counts_raw.get(case_id, 0)
            if actual_count != expected_count:
                raise EvaluationValidationError(
                    f"Run count mismatch for case_id '{case_id}': expected {expected_count}, got {actual_count}."
                )
            actual_counts[case_id] = actual_count

        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "records", frozen_records)
        object.__setattr__(self, "actual_run_counts_by_case", MappingProxyType(actual_counts))


__all__ = [
    "EvaluationCaseScoreBundle",
    "EvaluationRunRecord",
    "HermeticEvaluationResult",
    "ManifestEvaluationRunSet",
    "run_hermetic_evaluation",
    "score_evaluation_run_record",
]
