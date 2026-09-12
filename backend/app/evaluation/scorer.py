"""Pure deterministic semantic scoring for Evaluation cases."""

from __future__ import annotations

from decimal import Decimal

from app.diagnosis.models import Diagnosis, DiagnosisStatus

from .models import (
    CoreCaseScore,
    EvaluationValidationError,
    EVALUATION_SCOPE_DIMENSIONS,
    GroundTruthCase,
)


def score_core_case(case: GroundTruthCase, diagnosis: Diagnosis) -> CoreCaseScore:
    """Score only structured diagnosis semantics; never inspect Evidence values."""
    if not isinstance(case, GroundTruthCase):
        raise EvaluationValidationError("'case' must be a GroundTruthCase instance.")
    if not isinstance(diagnosis, Diagnosis):
        raise EvaluationValidationError("'diagnosis' must be a Diagnosis instance.")

    status_correct = case.status == diagnosis.status
    target_metric_correct = case.target_metric == diagnosis.target_metric
    driver_correct = case.primary_driver == diagnosis.primary_driver
    scope_correct = {
        dimension: case.affected_scope.get(dimension) == diagnosis.affected_scope.get(dimension)
        for dimension in EVALUATION_SCOPE_DIMENSIONS
    }
    scope_accuracy = Decimal(sum(scope_correct.values())) / Decimal("3")
    scope_shape_correct = set(case.affected_scope) == set(diagnosis.affected_scope)
    exact_match = (
        status_correct
        and target_metric_correct
        and driver_correct
        and all(scope_correct.values())
        and scope_shape_correct
    )
    no_anomaly_truth = case.status == DiagnosisStatus.NO_MATERIAL_ANOMALY
    no_anomaly_prediction = diagnosis.status == DiagnosisStatus.NO_MATERIAL_ANOMALY

    return CoreCaseScore(
        case_id=case.case_id,
        status_correct=status_correct,
        target_metric_correct=target_metric_correct,
        driver_correct=driver_correct,
        scope_correct=scope_correct,
        scope_accuracy=scope_accuracy,
        exact_match=exact_match,
        no_anomaly_correct=no_anomaly_truth == no_anomaly_prediction,
    )
