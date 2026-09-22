"""Hermetic tests for the end-to-end benchmark evaluation pipeline and reporting."""

from __future__ import annotations

import datetime
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

from app.evaluation import (
    EvaluationManifest,
    EvaluationRunRecord,
    EvaluationValidationError,
    ManifestEvaluationRunSet,
    RepeatedRunEvaluationReport,
    load_ground_truth_cases,
)
from scripts.run_benchmark_evaluation import (
    DEFAULT_BENCHMARK_CASES,
    DEFAULT_PROMPT,
    execute_evaluation_pipeline,
    export_report_json,
    format_dashboard,
    main,
    make_hermetic_run_record,
    report_to_dict,
    write_checkpoint_json,
)


NOW = datetime.datetime(2026, 1, 31, 12, tzinfo=datetime.timezone.utc)


class TestEvaluationPipeline(unittest.TestCase):
    """Hermetic unit tests verifying the 10-Case evaluation runner, reconciliation, and reporting."""

    def setUp(self) -> None:
        self.cases = load_ground_truth_cases(DEFAULT_BENCHMARK_CASES)
        self.assertEqual(len(self.cases), 10)

    def test_hermetic_single_run_pipeline(self) -> None:
        """Verify pipeline execution with 1 run per case across all 10 benchmark cases."""
        manifest = EvaluationManifest(
            manifest_id="manifest-test-single-run",
            model_id="gpt-4o-mini",
            prompt=DEFAULT_PROMPT,
            metric_config_version="v1.0.0",
            dataset_version="v1.0.0",
            run_counts_by_case={c.case_id: 1 for c in self.cases},
            created_at=NOW,
        )

        report = execute_evaluation_pipeline(
            manifest=manifest,
            cases=self.cases,
            hermetic=True,
        )

        self.assertIsInstance(report, RepeatedRunEvaluationReport)
        self.assertEqual(report.manifest_id, "manifest-test-single-run")
        self.assertEqual(report.total_cases, 10)
        self.assertEqual(report.total_runs, 10)
        self.assertEqual(report.overall_run_completion_rate, Decimal("1"))
        self.assertEqual(report.macro_driver_accuracy, Decimal("1"))
        self.assertEqual(report.macro_scope_accuracy, Decimal("1"))
        self.assertEqual(report.macro_exact_match_rate, Decimal("1"))
        self.assertEqual(len(report.case_summaries), 10)

        for summary in report.case_summaries:
            self.assertEqual(summary.total_runs, 1)
            self.assertEqual(summary.completed_runs, 1)
            self.assertEqual(summary.run_completion_rate, Decimal("1"))
            self.assertEqual(summary.mean_driver_accuracy, Decimal("1"))
            self.assertEqual(summary.mean_scope_accuracy, Decimal("1"))
            self.assertEqual(summary.mean_exact_match_rate, Decimal("1"))
            self.assertEqual(summary.mean_evidence_coverage, Decimal("1"))
            self.assertEqual(summary.mean_evidence_precision, Decimal("1"))

    def test_hermetic_repeated_runs_reconciliation_and_aggregation(self) -> None:
        """Verify 20 total runs (2 runs per case) with exact reconciliation and aggregation."""
        runs_per_case = 2
        manifest = EvaluationManifest(
            manifest_id="manifest-test-repeated-runs",
            model_id="gpt-4o-mini",
            prompt=DEFAULT_PROMPT,
            metric_config_version="v1.0.0",
            dataset_version="v1.0.0",
            run_counts_by_case={c.case_id: runs_per_case for c in self.cases},
            created_at=NOW,
        )

        report = execute_evaluation_pipeline(
            manifest=manifest,
            cases=self.cases,
            hermetic=True,
        )

        self.assertEqual(report.total_cases, 10)
        self.assertEqual(report.total_runs, 20)
        self.assertEqual(report.overall_run_completion_rate, Decimal("1"))
        self.assertEqual(report.macro_driver_accuracy, Decimal("1"))
        self.assertEqual(report.macro_scope_accuracy, Decimal("1"))
        self.assertEqual(report.macro_exact_match_rate, Decimal("1"))

        for summary in report.case_summaries:
            self.assertEqual(summary.total_runs, runs_per_case)
            self.assertEqual(summary.completed_runs, runs_per_case)

    def test_format_dashboard_contains_summary_and_all_case_ids(self) -> None:
        """Ensure format_dashboard renders macro KPIs and per-case rows cleanly."""
        manifest = EvaluationManifest(
            manifest_id="manifest-dashboard-test",
            model_id="gpt-4o-mini",
            prompt=DEFAULT_PROMPT,
            metric_config_version="v1.0.0",
            dataset_version="v1.0.0",
            run_counts_by_case={c.case_id: 1 for c in self.cases},
            created_at=NOW,
        )
        report = execute_evaluation_pipeline(manifest, self.cases, hermetic=True)
        dashboard = format_dashboard(report)

        self.assertIn("MetricSleuth Benchmark Repeated Evaluation Dashboard", dashboard)
        self.assertIn("manifest-dashboard-test", dashboard)
        self.assertIn("Total Benchmark Cases:       10", dashboard)
        self.assertIn("Total Evaluation Runs:       10", dashboard)
        self.assertIn("Macro Driver Accuracy:       100.00%", dashboard)
        self.assertIn("Macro Scope Accuracy:        100.00%", dashboard)
        self.assertIn("Macro Exact Match Rate:      100.00%", dashboard)

        for case in self.cases:
            self.assertIn(case.case_id, dashboard)

    def test_export_report_json_roundtrip(self) -> None:
        """Verify report serialization and file export."""
        manifest = EvaluationManifest(
            manifest_id="manifest-json-test",
            model_id="gpt-4o-mini",
            prompt=DEFAULT_PROMPT,
            metric_config_version="v1.0.0",
            dataset_version="v1.0.0",
            run_counts_by_case={c.case_id: 1 for c in self.cases},
            created_at=NOW,
        )
        report = execute_evaluation_pipeline(manifest, self.cases, hermetic=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "sub" / "report.json"
            export_report_json(report, out_file)
            self.assertTrue(out_file.is_file())

            with out_file.open("r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["manifest_id"], "manifest-json-test")
            self.assertEqual(data["total_cases"], 10)
            self.assertEqual(data["total_runs"], 10)
            self.assertEqual(data["macro_driver_accuracy"], 1.0)
            self.assertEqual(len(data["case_summaries"]), 10)

    def test_hermetic_pipeline_writes_redacted_atomic_checkpoint_per_run(self) -> None:
        manifest = EvaluationManifest(
            manifest_id="manifest-checkpoint-test",
            model_id="test-model",
            prompt=DEFAULT_PROMPT,
            metric_config_version="v1.0.0",
            dataset_version="v1.0.0",
            run_counts_by_case={c.case_id: 1 for c in self.cases},
            created_at=NOW,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = Path(tmpdir) / "checkpoint.json"
            execute_evaluation_pipeline(
                manifest,
                self.cases,
                hermetic=True,
                checkpoint_path=checkpoint,
            )
            data = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(data["schema"], "metricsleuth.live_evaluation_checkpoint.v1")
        self.assertEqual(data["manifest_id"], "manifest-checkpoint-test")
        self.assertEqual(data["expected_run_count"], 10)
        self.assertEqual(data["completed_run_count"], 10)
        self.assertEqual(len(data["records"]), 10)
        self.assertNotIn("current_value", json.dumps(data))
        self.assertNotIn("DATABASE_URL", json.dumps(data))

    def test_checkpoint_rewrites_latest_partial_record_set(self) -> None:
        manifest = EvaluationManifest(
            manifest_id="manifest-partial-checkpoint-test",
            model_id="test-model",
            prompt=DEFAULT_PROMPT,
            metric_config_version="v1.0.0",
            dataset_version="v1.0.0",
            run_counts_by_case={self.cases[0].case_id: 1},
            created_at=NOW,
        )
        record = make_hermetic_run_record(self.cases[0], "checkpoint-run", now=NOW)
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint = Path(tmpdir) / "checkpoint.json"
            write_checkpoint_json(checkpoint, manifest, [record])
            data = json.loads(checkpoint.read_text(encoding="utf-8"))

        self.assertEqual(data["completed_run_count"], 1)
        self.assertEqual(data["records"][0]["run_id"], "checkpoint-run")
        self.assertEqual(data["records"][0]["diagnosis"]["primary_driver"], "conversion_rate")

    def test_cli_main_hermetic_flag_returns_zero(self) -> None:
        """Test CLI main() invocation in hermetic mode with --runs-per-case."""
        exit_code = main(["--hermetic", "--runs-per-case", "2"])
        self.assertEqual(exit_code, 0)

    def test_cli_model_resolution_prefers_explicit_then_environment(self) -> None:
        """Live-run manifests must record the same model selected by runtime configuration."""
        report = execute_evaluation_pipeline(
            EvaluationManifest(
                manifest_id="model-resolution-report",
                model_id="test-model",
                prompt=DEFAULT_PROMPT,
                metric_config_version="v1.0.0",
                dataset_version="v1.0.0",
                run_counts_by_case={c.case_id: 1 for c in self.cases},
                created_at=NOW,
            ),
            self.cases,
            hermetic=True,
        )
        with patch.dict("os.environ", {"METRICSLEUTH_AGENT_MODEL": "env-model"}, clear=True):
            with patch("scripts.run_benchmark_evaluation.execute_evaluation_pipeline", return_value=report) as run_mock:
                self.assertEqual(main(["--hermetic"]), 0)
                self.assertEqual(run_mock.call_args.kwargs["manifest"].model_id, "env-model")

                self.assertEqual(main(["--hermetic", "--model-id", "explicit-model"]), 0)
                self.assertEqual(run_mock.call_args.kwargs["manifest"].model_id, "explicit-model")

    def test_cli_main_missing_credentials_exits_with_code_two(self) -> None:
        """Test CLI main() invocation in live mode without credentials returns exit code 2."""
        with patch.dict("os.environ", {}, clear=True):
            exit_code = main([])
            self.assertEqual(exit_code, 2)

    def test_cli_main_invalid_arguments_returns_one(self) -> None:
        """Test CLI main() rejects invalid runs-per-case or missing cases file."""
        self.assertEqual(main(["--hermetic", "--runs-per-case", "0"]), 1)
        self.assertEqual(main(["--hermetic", "--cases-path", "nonexistent_file.json"]), 1)

    def test_manifest_reconciliation_fails_on_tampered_records(self) -> None:
        """Prove that omitting or adding an extra record fails closed at ManifestEvaluationRunSet."""
        manifest = EvaluationManifest(
            manifest_id="manifest-reconciliation-test",
            model_id="gpt-4o-mini",
            prompt=DEFAULT_PROMPT,
            metric_config_version="v1.0.0",
            dataset_version="v1.0.0",
            run_counts_by_case={c.case_id: 1 for c in self.cases},
            created_at=NOW,
        )

        records = [make_hermetic_run_record(c, f"run-{c.case_id}-1", now=NOW) for c in self.cases]

        # 1. Omit the last record (9 instead of 10)
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records[:-1])

        # 2. Duplicate a record with different run_id (2 runs for one case instead of 1)
        extra = make_hermetic_run_record(self.cases[0], "run-extra-1", now=NOW)
        with self.assertRaises(EvaluationValidationError):
            ManifestEvaluationRunSet(manifest, records + [extra])
