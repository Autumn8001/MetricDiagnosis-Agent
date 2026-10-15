"""Read-only retrospective scoring of a Synthetic task; never calls a model.

Expected status/driver are supplied by the evaluator, never inferred from the
prediction. Scope support reuses the existing joint-claim scorer. This does not
measure scope accuracy against negative controls or the timing of stopping.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.analytics.models import DateRange
from app.api.task_schemas import TaskDetailResponse
from app.diagnosis import Diagnosis, DiagnosisChange, DiagnosisComposition, DiagnosisStatus
from app.evidence import Evidence, EvidenceRole
from app.evaluation import score_unsupported_claims
from app.observations import ObservationStatus
from app.persistence.task_read_repository import InvestigationTaskReadRepository
from scripts.serve_live_browser_task_acceptance import SafeArgumentParser, validate_database_url
from scripts.verify_live_task_persistence import _validate_persisted_provenance


METRICS = ("sales", "orders", "sessions", "conversion_rate", "aov")


def restore_composition(detail: TaskDetailResponse) -> DiagnosisComposition:
    """Restore only persisted facts; missing/invalid fields fail domain validation."""
    calls = {item.tool_call_id: item for item in detail.tool_calls}
    observations = {item.observation_id: item for item in detail.observations}
    evidence = []
    for item in detail.evidence:
        observation = observations[item.observation_id]
        evidence.append(Evidence(
            evidence_id=item.evidence_id, observation_id=item.observation_id,
            role=EvidenceRole(item.role), tool_name=calls[item.tool_call_id].tool_name,
            tool_call_id=item.tool_call_id, metric=observation.metric,
            current_period=DateRange(observation.current_period_start, observation.current_period_end),
            baseline_period=DateRange(observation.baseline_period_start, observation.baseline_period_end),
            filters=observation.filters, group_by=tuple(observation.group_by),
            dimensions=observation.dimensions, current_value=observation.current_value,
            baseline_value=observation.baseline_value, relative_change=observation.relative_change,
            unit=observation.unit, sample_size=observation.sample_size,
            observation_status=ObservationStatus(observation.status),
            source_status=observation.source_status,
            query_or_result_reference=observation.query_reference,
            created_at=item.created_at, error_code=observation.error_code,
        ))
    row = detail.diagnoses[0]
    diagnosis = Diagnosis(
        diagnosis_id=row.diagnosis_id, status=DiagnosisStatus(row.status),
        target_metric=row.target_metric,
        change=None if row.change is None else DiagnosisChange(**row.change.model_dump()),
        primary_driver=row.primary_driver, affected_scope=row.affected_scope,
        evidence_ids=tuple(row.evidence_ids), confidence=row.confidence,
        limitations=tuple(row.limitations), created_at=row.created_at,
    )
    return DiagnosisComposition(evidence=tuple(evidence), diagnosis=diagnosis)


def score_detail(detail: TaskDetailResponse, *, source_id: str, data_version: str,
                 expected_metric: str, expected_status: str, expected_driver: str | None) -> dict:
    """Evaluate a stored outcome without hiding failures or fabricating telemetry."""
    if expected_metric not in METRICS or expected_status not in {"diagnosed", "no_material_anomaly"}:
        raise ValueError("invalid_expectation")
    if (expected_status == "diagnosed" and expected_driver not in METRICS) or (
        expected_status == "no_material_anomaly" and expected_driver is not None
    ):
        raise ValueError("invalid_expectation")
    provenance = _validate_persisted_provenance(
        detail.model_dump(mode="json"), source_id=source_id, data_version=data_version,
    )
    result = {
        "expectations": {"metric": expected_metric, "status": expected_status, "driver": expected_driver},
        "sample_count": 1,
        "execution_succeeded": detail.run.status == "succeeded",
        "provenance_passed": provenance["passed"],
        "semantic_evaluated": False, "semantic_passed": False,
        "status_correct": None, "target_metric_correct": None, "driver_correct": None,
        "all_claims_supported": None, "unsupported_claim_rate": None,
        "scope_accuracy": "not_evaluated_no_negative_controls",
        "stop_timing": "not_evaluated", "tokens": None, "cost": None,
        "persisted_tool_calls": detail.run.tool_call_count,
    }
    if not provenance["passed"] or len(detail.diagnoses) != 1:
        return result
    composition = restore_composition(detail)
    claims = score_unsupported_claims(composition)
    diagnosis = composition.diagnosis
    checks = {
        "status_correct": diagnosis.status.value == expected_status,
        "target_metric_correct": diagnosis.target_metric == expected_metric == detail.run.requested_metric,
        "driver_correct": diagnosis.primary_driver == expected_driver,
        "all_claims_supported": bool(claims.claim_ids) and not claims.unsupported_claim_ids,
    }
    result.update(checks)
    result.update(
        semantic_evaluated=True, semantic_passed=all(checks.values()),
        unsupported_claim_rate=None if claims.unsupported_claim_rate is None else str(claims.unsupported_claim_rate),
        supported_claim_count=len(claims.supported_claim_ids), total_claim_count=len(claims.claim_ids),
    )
    return result


def main(argv=None) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--expected-metric", choices=METRICS, required=True)
    parser.add_argument("--expected-status", choices=("diagnosed", "no_material_anomaly"), required=True)
    parser.add_argument("--expected-driver", choices=METRICS)
    args = parser.parse_args(argv)
    try:
        validate_database_url(args.database_url)
        source_id, run_id = str(UUID(args.source_id)), str(UUID(args.run_id))
        import psycopg
        # Direct reader only: no task application, worker, client, env or migration.
        with psycopg.connect(args.database_url, connect_timeout=5) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute("SET LOCAL statement_timeout = '10s'")
            reader = InvestigationTaskReadRepository(connection)
            raw = reader.get_details(run_id, source_id, "sandbox")
            # provider is server-bound API metadata, not a persisted run column.
            # Verify its actual source row before restoring the API contract.
            identity = connection.execute(
                "SELECT provider, environment FROM app_state.data_sources WHERE source_id = %s", (source_id,),
            ).fetchone()
        if raw is None:
            raise ValueError("run_unavailable")
        if identity != ("synthetic", "sandbox"):
            raise ValueError("synthetic_sandbox_required")
        raw["run"]["provider"] = identity[0]
        detail = TaskDetailResponse.model_validate(raw)
        result = score_detail(detail, source_id=source_id, data_version=args.data_version,
                              expected_metric=args.expected_metric, expected_status=args.expected_status,
                              expected_driver=args.expected_driver)
        print(json.dumps({"evaluation_kind": "retrospective_persisted_synthetic",
                          "sample_selection": "known_historical_runs_not_holdout",
                          "new_model_calls": 0, "run_id": run_id, **result}, sort_keys=True))
        return 0 if result["semantic_passed"] else 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "persisted_scoring_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
