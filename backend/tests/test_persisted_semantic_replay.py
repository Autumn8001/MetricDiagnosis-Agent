"""Offline replay conversion/support checks; no database or model access."""
from decimal import Decimal
from contextlib import redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import patch

from app.api.task_schemas import TaskDetailResponse
from app.diagnosis import DiagnosisStatus
from app.evidence import EvidenceRole
from app.observations import ObservationStatus
from scripts.score_persisted_task import main, restore_composition, score_detail
from tests.test_unsupported_claims import make_evidence, make_diagnosis, NOW


def detail_fixture(*, split_scope=False, normal=False):
    status = ObservationStatus.NORMAL if normal else ObservationStatus.ANOMALOUS
    target = make_evidence("target", "sales", status, role=EvidenceRole.SUPPORTING)
    driver = make_evidence("driver", "conversion_rate", status, role=EvidenceRole.SUPPORTING,
                           dimensions={} if split_scope else {"marketplace": "US"})
    items = [target, driver]
    if split_scope:
        items.append(make_evidence("unrelated", "aov", status, role=EvidenceRole.SUPPORTING,
                                   dimensions={"marketplace": "US"}))
    diagnosis = make_diagnosis(items, scope={"marketplace": "US"} if not normal else {},
        status=DiagnosisStatus.NO_MATERIAL_ANOMALY if normal else DiagnosisStatus.DIAGNOSED)
    calls, observations, evidence = [], [], []
    for item in items:
        calls.append(dict(tool_call_id=item.tool_call_id, tool_name=item.tool_name, status="completed",
            arguments={}, data_version="v1", query_reference=None, result_reference=item.query_or_result_reference, requested_at=NOW))
        observations.append(dict(observation_id=item.observation_id, tool_call_id=item.tool_call_id,
            metric=item.metric, status=item.observation_status.value, source_status=item.source_status,
            current_period_start=item.current_period.start_date, current_period_end=item.current_period.end_date,
            baseline_period_start=item.baseline_period.start_date, baseline_period_end=item.baseline_period.end_date,
            filters=dict(item.filters), group_by=list(item.group_by), dimensions=dict(item.dimensions),
            current_value=item.current_value, baseline_value=item.baseline_value, relative_change=item.relative_change,
            unit=item.unit, sample_size=item.sample_size, query_reference=item.query_or_result_reference,
            data_version="v1", error_code=None, created_at=NOW))
        evidence.append(dict(evidence_id=item.evidence_id, observation_id=item.observation_id,
            tool_call_id=item.tool_call_id, role=item.role.value, data_version="v1",
            query_reference=item.query_or_result_reference, created_at=NOW))
    change = diagnosis.change
    row = dict(diagnosis_id=diagnosis.diagnosis_id, status=diagnosis.status.value, target_metric=diagnosis.target_metric,
        primary_driver=diagnosis.primary_driver, affected_scope=dict(diagnosis.affected_scope),
        change=dict(current_value=change.current_value, baseline_value=change.baseline_value,
            relative_change=change.relative_change, unit=change.unit, evidence_id=change.evidence_id),
        evidence_ids=list(diagnosis.evidence_ids), confidence=diagnosis.confidence,
        limitations=list(diagnosis.limitations), data_version="v1", query_reference="task-ref", created_at=NOW)
    return TaskDetailResponse.model_validate(dict(
        run=dict(investigation_run_id="run-1", source_id="source-1", environment="sandbox", provider="synthetic",
            status="succeeded", requested_metric="sales", requested_at=NOW, started_at=NOW, finished_at=NOW,
            data_version="v1", query_reference="task-ref", failure_code=None,
            tool_call_count=len(calls), observation_count=len(observations), evidence_count=len(evidence), diagnosis_count=1),
        tool_calls=calls, observations=observations, evidence=evidence, diagnoses=[row]))


class PersistedSemanticReplayTests(unittest.TestCase):
    def score(self, detail, **updates):
        kwargs = dict(source_id="source-1", data_version="v1", expected_metric="sales",
                      expected_status="diagnosed", expected_driver="conversion_rate")
        return score_detail(detail, **(kwargs | updates))

    def test_rehydrates_exact_decimals_and_evidence_without_running_agent(self):
        detail = detail_fixture()
        composition = restore_composition(detail)
        self.assertEqual(composition.diagnosis.change.relative_change, Decimal("-0.20"))
        result = self.score(detail)
        self.assertTrue(result["semantic_passed"])
        self.assertEqual(result["unsupported_claim_rate"], "0")
        self.assertIsNone(result["tokens"])
        self.assertEqual(result["stop_timing"], "not_evaluated")

    def test_expected_driver_is_independent_of_prediction(self):
        result = self.score(detail_fixture(), expected_driver="aov")
        self.assertFalse(result["driver_correct"])
        self.assertFalse(result["semantic_passed"])
        detail = detail_fixture()
        detail.run.requested_metric = "orders"
        self.assertFalse(self.score(detail)["target_metric_correct"])

    def test_joint_driver_scope_support_cannot_be_borrowed_from_another_metric(self):
        result = self.score(detail_fixture(split_scope=True))
        self.assertTrue(result["provenance_passed"])
        self.assertFalse(result["all_claims_supported"])
        self.assertFalse(result["semantic_passed"])

    def test_failed_execution_is_kept_without_fabricated_diagnosis(self):
        detail = detail_fixture()
        detail.run.status = "failed"
        detail.run.diagnosis_count = 0
        detail.diagnoses = []
        result = self.score(detail)
        self.assertEqual(result["sample_count"], 1)
        self.assertFalse(result["semantic_evaluated"])
        self.assertFalse(result["semantic_passed"])
        self.assertIsNone(result["driver_correct"])

    def test_broken_references_and_wrong_identity_are_not_semantically_scored(self):
        for field, value in (("source_id", "other"), ("data_version", "v2")):
            self.assertFalse(self.score(detail_fixture(), **{field: value})["semantic_evaluated"])
        detail = detail_fixture()
        detail.evidence[0].observation_id = "absent"
        self.assertFalse(self.score(detail)["semantic_evaluated"])

    def test_normal_status_can_be_scored_without_inventing_driver(self):
        result = self.score(detail_fixture(normal=True), expected_status="no_material_anomaly", expected_driver=None)
        self.assertTrue(result["semantic_passed"])
        self.assertEqual(result["scope_accuracy"], "not_evaluated_no_negative_controls")

    def test_cli_rejects_other_database_before_connecting_and_redacts_values(self):
        output = io.StringIO()
        with patch("psycopg.connect") as connect, redirect_stdout(output):
            result = main(["--database-url", "postgresql://private:do-not-print@example.invalid/production",
                "--source-id", "invalid", "--run-id", "invalid", "--data-version", "v1",
                "--expected-metric", "sales", "--expected-status", "diagnosed", "--expected-driver", "conversion_rate"])
        self.assertEqual(result, 2)
        connect.assert_not_called()
        self.assertNotIn("do-not-print", output.getvalue())

    def test_cli_argument_errors_do_not_echo_credentials(self):
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit):
            main(["--private-option", "do-not-print"])
        self.assertEqual(output.getvalue(), "invalid_arguments\n")
