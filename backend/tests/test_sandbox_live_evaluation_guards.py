import io
from contextlib import redirect_stderr
import unittest
from unittest.mock import patch

from scripts import run_sandbox_live_evaluation as evaluation
from app.evaluation import load_ground_truth_cases
from tests.test_persisted_semantic_replay import detail_fixture
from scripts.replay_sandbox_live_evaluation import validate_records


class SandboxLiveEvaluationGuards(unittest.TestCase):
    def test_replay_cannot_duplicate_a_run_or_case_slot(self):
        record = {"event": "run_scored", "case_id": "case", "repetition": 1,
                  "run_id": "11111111-1111-4111-8111-111111111111"}
        events = [{"event": "plan_frozen", "plan": {"cases": [{"case_id": "case"}]}},
                  record, {"event": "batch_finished"}]
        self.assertEqual(len(validate_records(events)[1]), 1)
        with self.assertRaisesRegex(ValueError, "duplicate_run_or_slot"):
            validate_records([*events, record])
        with self.assertRaisesRegex(ValueError, "completed_journal_required"):
            validate_records(events[:-1])

    def canonical(self):
        return next(c for c in load_ground_truth_cases(evaluation.ROOT / "warehouse/benchmark_cases.json")
                    if c.scenario == "canonical")

    def test_matching_driver_does_not_hide_incomplete_scope_and_controls(self):
        score = evaluation.score_run(detail_fixture(), self.canonical())
        self.assertTrue(score["driver_correct"])
        self.assertFalse(score["exact_match"])
        self.assertNotEqual(score["evidence_coverage"], "1")
        self.assertTrue(score["missing_obligations"])

    def test_failed_run_has_no_invented_scope_or_diagnosis_score(self):
        detail = detail_fixture()
        detail.run.status = "failed"
        detail.run.diagnosis_count = 0
        detail.diagnoses = []
        score = evaluation.score_run(detail, self.canonical())
        self.assertFalse(score["execution_succeeded"])
        self.assertFalse(score["exact_match"])
        self.assertIsNone(score["scope_accuracy"])
        self.assertIsNone(score["evidence_coverage"])

    def test_six_run_opt_in_is_required_before_any_connection_or_model_setup(self):
        with (
            patch.object(evaluation, "preflight_database") as database,
            patch.object(evaluation, "load_model_settings") as model,
            redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                evaluation.main(["--database-url", "unused", "--model-env-file", "unused", "--safe-log-file", "unused"])
        database.assert_not_called()
        model.assert_not_called()

    def test_auth_protocol_and_transport_errors_stop_without_retrying(self):
        for error in ("AuthenticationError", "UserError", "RuntimeTraceError", "APITimeoutError"):
            self.assertTrue(evaluation.stop_after_error(error))
        self.assertTrue(evaluation.stop_after_error("OtherError", 403))
        self.assertFalse(evaluation.stop_after_error("RuntimeBudgetExceededError"))
        self.assertFalse(evaluation.stop_after_error(None))
