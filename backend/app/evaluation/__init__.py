"""Ground Truth loading and deterministic core scoring contracts."""

from app.evaluation.aggregate import CoreEvaluationReport, aggregate_core_scores
from app.evaluation.loader import load_ground_truth_cases
from app.evaluation.models import (
    CoreCaseScore,
    EvaluationConfigError,
    EvaluationError,
    EvaluationValidationError,
    GroundTruthCase,
)
from app.evaluation.manifest import EvaluationManifest
from app.evaluation.scorer import score_core_case
from app.evaluation.evidence_obligations import (
    EvidenceObligation,
    EvidenceObligationKind,
    build_evidence_obligations,
    derive_evidence_obligation_id,
)
from app.evaluation.evidence_scorer import (
    EvidenceCitationScore,
    score_evidence_citations,
)
from app.evaluation.unsupported_claims import (
    DiagnosisClaim,
    DiagnosisClaimKind,
    UnsupportedClaimScore,
    build_diagnosis_claims,
    derive_diagnosis_claim_id,
    score_unsupported_claims,
)
from app.evaluation.operational import (
    EvaluationRunOutcome,
    EvaluationRunStatus,
    ToolOperationalScore,
    completed_run_outcome,
    failed_run_outcome,
    score_tool_operations,
)
from app.evaluation.operational_aggregate import (
    ToolOperationalAggregateReport,
    aggregate_tool_operations,
)
from app.evaluation.unified import UnifiedEvaluationReport, build_unified_evaluation_report
from app.evaluation.runner import (
    EvaluationCaseScoreBundle,
    EvaluationRunRecord,
    HermeticEvaluationResult,
    ManifestEvaluationRunSet,
    run_hermetic_evaluation,
    score_evaluation_run_record,
)
from app.evaluation.repeated_aggregate import (
    CaseRepeatedSummary,
    RepeatedRunEvaluationReport,
    aggregate_manifest_evaluation_run_set,
)

__all__ = [
    "CoreCaseScore",
    "CoreEvaluationReport",
    "EvaluationConfigError",
    "EvaluationError",
    "EvaluationValidationError",
    "GroundTruthCase",
    "EvaluationManifest",
    "load_ground_truth_cases",
    "aggregate_core_scores",
    "score_core_case",
    "EvidenceObligation",
    "EvidenceObligationKind",
    "build_evidence_obligations",
    "derive_evidence_obligation_id",
    "EvidenceCitationScore",
    "score_evidence_citations",
    "DiagnosisClaim",
    "DiagnosisClaimKind",
    "UnsupportedClaimScore",
    "build_diagnosis_claims",
    "derive_diagnosis_claim_id",
    "score_unsupported_claims",
    "EvaluationRunOutcome",
    "EvaluationRunStatus",
    "ToolOperationalScore",
    "completed_run_outcome",
    "failed_run_outcome",
    "score_tool_operations",
    "ToolOperationalAggregateReport",
    "aggregate_tool_operations",
    "UnifiedEvaluationReport",
    "build_unified_evaluation_report",
    "EvaluationRunRecord",
    "EvaluationCaseScoreBundle",
    "HermeticEvaluationResult",
    "ManifestEvaluationRunSet",
    "score_evaluation_run_record",
    "run_hermetic_evaluation",
    "CaseRepeatedSummary",
    "RepeatedRunEvaluationReport",
    "aggregate_manifest_evaluation_run_set",
]
