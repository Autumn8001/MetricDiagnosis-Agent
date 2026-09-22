"""End-to-end Benchmark Evaluation Runner and Dashboard Generator.

Supports both hermetic offline simulation and live Agent evaluation modes.
Loads Ground Truth benchmark cases, builds an EvaluationManifest, executes
runs per case, reconciles all runs in a ManifestEvaluationRunSet, and computes
repeated-run aggregate metrics using aggregate_manifest_evaluation_run_set().
"""

from __future__ import annotations

import argparse
import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Sequence

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.analytics.models import DateRange
from app.diagnosis import (
    Diagnosis,
    DiagnosisChange,
    DiagnosisComposition,
    DiagnosisStatus,
)
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.evaluation import (
    EvaluationManifest,
    EvaluationRunOutcome,
    EvaluationRunRecord,
    EvaluationRunStatus,
    GroundTruthCase,
    ManifestEvaluationRunSet,
    RepeatedRunEvaluationReport,
    aggregate_manifest_evaluation_run_set,
    completed_run_outcome,
    load_ground_truth_cases,
)
from app.observations import Observation, ObservationStatus


DEFAULT_BENCHMARK_CASES = REPOSITORY_ROOT / "warehouse" / "benchmark_cases.json"
DEFAULT_MODEL_ID = "gpt-4o-mini"
DEFAULT_PROMPT = (
    "Please investigate the sales anomaly for 2026-01-31 compared to the "
    "previous_7_days baseline. Available dimensions are marketplace, asin, "
    "and traffic_source. Use the controlled analytics tools to identify the "
    "primary data driver and affected segment if any, cite the resulting "
    "observations, and conclude with the structured diagnosis intent."
)
BENCHMARK_PERIOD = DateRange(datetime.date(2026, 1, 31), datetime.date(2026, 1, 31))
BENCHMARK_BASELINE = DateRange(datetime.date(2026, 1, 24), datetime.date(2026, 1, 30))


def _inject_scenario(scenario: str, database_url: str) -> None:
    """Inject scenario into PostgreSQL warehouse via anomaly_injector.py."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "warehouse" / "anomaly_injector.py"),
            "--scenario",
            scenario,
            "--database-url",
            database_url,
        ],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Scenario injector failed for '{scenario}' (exit {completed.returncode}): "
            f"{completed.stderr.strip()}"
        )


def make_hermetic_run_record(
    case: GroundTruthCase,
    run_id: str,
    *,
    now: datetime.datetime | None = None,
) -> EvaluationRunRecord:
    """Construct a deterministic hermetic EvaluationRunRecord for a benchmark case."""
    timestamp = now or datetime.datetime.now(datetime.timezone.utc)
    evidences = []

    # 1. Target metric observation and evidence
    target_is_anomalous = case.status == DiagnosisStatus.DIAGNOSED
    target_obs = Observation(
        observation_id=f"{run_id}-target",
        tool_name="query_metric",
        tool_call_id=f"call:{run_id}-target",
        metric=case.target_metric,
        current_period=BENCHMARK_PERIOD,
        baseline_period=BENCHMARK_BASELINE,
        filters={},
        group_by=(),
        dimensions={},
        current_value=Decimal("15840.00") if target_is_anomalous else Decimal("18240.00"),
        baseline_value=Decimal("18240.00"),
        relative_change=Decimal("-0.1316") if target_is_anomalous else Decimal("0.0000"),
        unit="usd",
        sample_size=Decimal("2850"),
        source_status="ok",
        status=ObservationStatus.ANOMALOUS if target_is_anomalous else ObservationStatus.NORMAL,
        query_or_result_reference=f"ref:{run_id}-target",
        created_at=timestamp,
    )
    target_ev = promote_observation_to_evidence(target_obs, role=EvidenceRole.SUPPORTING)
    evidences.append(target_ev)

    # 2. Primary driver observation and evidence (for diagnosed cases)
    if case.status == DiagnosisStatus.DIAGNOSED and case.primary_driver is not None:
        driver_metric = case.primary_driver
        is_ratio = driver_metric == "conversion_rate"
        driver_obs = Observation(
            observation_id=f"{run_id}-driver",
            tool_name="query_metric",
            tool_call_id=f"call:{run_id}-driver",
            metric=driver_metric,
            current_period=BENCHMARK_PERIOD,
            baseline_period=BENCHMARK_BASELINE,
            filters=dict(case.affected_scope),
            group_by=(),
            dimensions=dict(case.affected_scope),
            current_value=Decimal("0.0200") if is_ratio else Decimal("100"),
            baseline_value=Decimal("0.0800") if is_ratio else Decimal("200"),
            relative_change=Decimal("-0.7500") if is_ratio else Decimal("-0.5000"),
            unit="ratio" if is_ratio else "count",
            sample_size=Decimal("500"),
            source_status="ok",
            status=ObservationStatus.ANOMALOUS,
            query_or_result_reference=f"ref:{run_id}-driver",
            created_at=timestamp,
        )
        driver_ev = promote_observation_to_evidence(driver_obs, role=EvidenceRole.SUPPORTING)
        evidences.append(driver_ev)

    # 3. Expected stable metrics observations and evidences
    for stable_m in case.expected_stable_metrics:
        stable_obs = Observation(
            observation_id=f"{run_id}-stable-{stable_m}",
            tool_name="query_metric",
            tool_call_id=f"call:{run_id}-stable-{stable_m}",
            metric=stable_m,
            current_period=BENCHMARK_PERIOD,
            baseline_period=BENCHMARK_BASELINE,
            filters={},
            group_by=(),
            dimensions={},
            current_value=Decimal("100"),
            baseline_value=Decimal("100"),
            relative_change=Decimal("0.00"),
            unit="usd" if stable_m in {"sales", "aov"} else ("ratio" if stable_m == "conversion_rate" else "count"),
            sample_size=Decimal("500"),
            source_status="ok",
            status=ObservationStatus.NORMAL,
            query_or_result_reference=f"ref:{run_id}-stable-{stable_m}",
            created_at=timestamp,
        )
        stable_ev = promote_observation_to_evidence(stable_obs, role=EvidenceRole.SUPPORTING)
        evidences.append(stable_ev)

    # 4. Negative controls observations and evidences
    control_mapping = [
        ("marketplaces", "marketplace"),
        ("asins", "asin"),
        ("traffic_sources", "traffic_source"),
    ]
    for ctrl_key, dim_name in control_mapping:
        for val in case.negative_controls.get(ctrl_key, ()):
            ctrl_obs = Observation(
                observation_id=f"{run_id}-ctrl-{dim_name}-{val}",
                tool_name="query_metric",
                tool_call_id=f"call:{run_id}-ctrl-{dim_name}-{val}",
                metric="sessions",
                current_period=BENCHMARK_PERIOD,
                baseline_period=BENCHMARK_BASELINE,
                filters={dim_name: val},
                group_by=(dim_name,),
                dimensions={dim_name: val},
                current_value=Decimal("100"),
                baseline_value=Decimal("100"),
                relative_change=Decimal("0.00"),
                unit="count",
                sample_size=Decimal("500"),
                source_status="ok",
                status=ObservationStatus.NORMAL,
                query_or_result_reference=f"ref:{run_id}-ctrl-{dim_name}-{val}",
                created_at=timestamp,
            )
            ctrl_ev = promote_observation_to_evidence(ctrl_obs, role=EvidenceRole.NEGATIVE_CONTROL)
            evidences.append(ctrl_ev)

    diagnosis = Diagnosis(
        diagnosis_id=f"diag:{run_id}",
        status=case.status,
        target_metric=case.target_metric,
        change=DiagnosisChange(
            current_value=target_ev.current_value,
            baseline_value=target_ev.baseline_value,
            relative_change=target_ev.relative_change,
            unit=target_ev.unit,
            evidence_id=target_ev.evidence_id,
        ),
        primary_driver=case.primary_driver,
        affected_scope=dict(case.affected_scope),
        evidence_ids=tuple(item.evidence_id for item in evidences),
        confidence=Decimal("0.90"),
        limitations=("Hermetic benchmark evaluation simulation.",),
        created_at=timestamp,
    )

    composition = DiagnosisComposition(evidence=tuple(evidences), diagnosis=diagnosis)
    outcome = EvaluationRunOutcome(
        case_id=case.case_id,
        status=EvaluationRunStatus.COMPLETED,
        tool_calls_attempted=len(evidences),
        tool_calls_succeeded=len(evidences),
        max_tool_calls=25,
        turns_count=3,
        max_turns=10,
        failure_code=None,
    )

    return EvaluationRunRecord(
        run_id=run_id,
        case=case,
        outcome=outcome,
        composition=composition,
    )


def _checkpoint_record_to_dict(record: EvaluationRunRecord) -> dict[str, Any]:
    """Serialize only run identity, operational outcome, and diagnosis references.

    A checkpoint is intentionally not a copy of Tool Output, database values,
    credentials, or provider responses.  It exists solely to make a partially
    completed live evaluation auditable after an interrupted process.
    """
    composition = record.composition
    diagnosis = None
    if composition is not None:
        resolved = composition.diagnosis
        diagnosis = {
            "status": resolved.status.value,
            "target_metric": resolved.target_metric,
            "primary_driver": resolved.primary_driver,
            "affected_scope": dict(resolved.affected_scope),
            "evidence_ids": list(resolved.evidence_ids),
        }
    outcome = record.outcome
    return {
        "run_id": record.run_id,
        "case_id": record.case.case_id,
        "scenario": record.case.scenario,
        "outcome": {
            "status": outcome.status.value,
            "tool_calls_attempted": outcome.tool_calls_attempted,
            "tool_calls_succeeded": outcome.tool_calls_succeeded,
            "max_tool_calls": outcome.max_tool_calls,
            "turns_count": outcome.turns_count,
            "max_turns": outcome.max_turns,
            "failure_code": outcome.failure_code,
        },
        "diagnosis": diagnosis,
    }


def _safe_runtime_failure_code(exc: Exception) -> str:
    """Return a bounded failure code without serializing provider or database details.

    ``run_evidence_driven_diagnosis`` deliberately adds one compact, reference-only
    note when its domain composition rejects a runtime intent.  Preserve that note
    for a later evaluation audit; arbitrary exception messages remain excluded.
    """
    code = f"RUNTIME_ERROR: {type(exc).__name__}"
    notes = getattr(exc, "__notes__", ())
    if not isinstance(notes, list):
        return code
    for note in notes:
        if isinstance(note, str) and note.startswith("Runtime intent references: "):
            return f"{code} | {note}"
    return code


def write_checkpoint_json(
    path: str | Path,
    manifest: EvaluationManifest,
    records: Sequence[EvaluationRunRecord],
) -> None:
    """Atomically persist an intentionally partial, redacted evaluation checkpoint."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "metricsleuth.live_evaluation_checkpoint.v1",
        "manifest_id": manifest.manifest_id,
        "model_id": manifest.model_id,
        "expected_run_count": manifest.total_run_count,
        "completed_run_count": len(records),
        "records": [_checkpoint_record_to_dict(record) for record in records],
    }
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def execute_evaluation_pipeline(
    manifest: EvaluationManifest,
    cases: Sequence[GroundTruthCase],
    *,
    hermetic: bool = True,
    database_url: str | None = None,
    checkpoint_path: str | Path | None = None,
) -> RepeatedRunEvaluationReport:
    """Execute the full evaluation pipeline and aggregate into a RepeatedRunEvaluationReport."""
    records: list[EvaluationRunRecord] = []

    def append_record(record: EvaluationRunRecord) -> None:
        records.append(record)
        if checkpoint_path is not None:
            write_checkpoint_json(checkpoint_path, manifest, records)

    if hermetic:
        for case in cases:
            runs_count = manifest.run_counts_by_case[case.case_id]
            for run_idx in range(1, runs_count + 1):
                run_id = f"{case.case_id}-hermetic-run-{run_idx}"
                append_record(make_hermetic_run_record(case, run_id))
    else:
        # Live mode: import dependencies lazily
        import psycopg
        from app.agent_runtime.diagnosis_runtime import (
            DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
            DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
            run_evidence_driven_diagnosis,
        )
        from app.analytics.tools import AnalyticsTools
        from app.metrics.registry import MetricRegistry

        if not database_url:
            raise ValueError("database_url is required for live evaluation mode.")

        metrics_config_path = REPOSITORY_ROOT / "configs" / "metrics.yaml"
        registry = MetricRegistry.from_yaml(metrics_config_path)

        try:
            for case in cases:
                runs_count = manifest.run_counts_by_case[case.case_id]
                for run_idx in range(1, runs_count + 1):
                    run_id = f"{case.case_id}-live-run-{run_idx}"
                    print(f"  [Live] Injecting scenario: {case.scenario} (Run {run_idx}/{runs_count}) ...")
                    _inject_scenario(case.scenario, database_url)

                    try:
                        with psycopg.connect(database_url) as conn:
                            tools = AnalyticsTools(registry=registry, connection=conn)
                            diagnosis_id = f"diag_{case.scenario}_{run_idx}_{int(time.time())}"
                            summary = run_evidence_driven_diagnosis(
                                prompt=manifest.prompt,
                                diagnosis_id=diagnosis_id,
                                analytics_tools=tools,
                                model=manifest.model_id,
                                max_tool_calls=DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
                                max_turns=DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
                            )
                            outcome = completed_run_outcome(case.case_id, summary)
                            append_record(
                                EvaluationRunRecord(
                                    run_id=run_id,
                                    case=case,
                                    outcome=outcome,
                                    composition=summary.composition if outcome.status == EvaluationRunStatus.COMPLETED else None,
                                )
                            )
                    except Exception as exc:
                        outcome = EvaluationRunOutcome(
                            case_id=case.case_id,
                            status=EvaluationRunStatus.RUNTIME_FAILURE,
                            tool_calls_attempted=0,
                            tool_calls_succeeded=0,
                            max_tool_calls=DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
                            turns_count=None,
                            max_turns=DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
                            failure_code=_safe_runtime_failure_code(exc),
                        )
                        append_record(
                            EvaluationRunRecord(
                                run_id=run_id,
                                case=case,
                                outcome=outcome,
                                composition=None,
                            )
                        )
        finally:
            print("  [Live] Restoring warehouse to canonical scenario ...")
            try:
                _inject_scenario("canonical", database_url)
            except Exception as exc:
                print(f"  [Warning] Failed to restore canonical scenario: {exc}", file=sys.stderr)

    run_set = ManifestEvaluationRunSet(manifest, records)
    return aggregate_manifest_evaluation_run_set(run_set)


def report_to_dict(report: RepeatedRunEvaluationReport) -> dict[str, Any]:
    """Convert RepeatedRunEvaluationReport to a JSON-serializable dictionary."""
    return {
        "manifest_id": report.manifest_id,
        "total_cases": report.total_cases,
        "total_runs": report.total_runs,
        "macro_driver_accuracy": float(report.macro_driver_accuracy),
        "macro_scope_accuracy": float(report.macro_scope_accuracy),
        "macro_exact_match_rate": float(report.macro_exact_match_rate),
        "overall_run_completion_rate": float(report.overall_run_completion_rate),
        "case_summaries": [
            {
                "case_id": s.case_id,
                "total_runs": s.total_runs,
                "completed_runs": s.completed_runs,
                "run_completion_rate": float(s.run_completion_rate),
                "mean_status_accuracy": float(s.mean_status_accuracy),
                "mean_target_metric_accuracy": float(s.mean_target_metric_accuracy),
                "mean_driver_accuracy": float(s.mean_driver_accuracy),
                "mean_scope_accuracy": float(s.mean_scope_accuracy),
                "mean_exact_match_rate": float(s.mean_exact_match_rate),
                "mean_evidence_coverage": float(s.mean_evidence_coverage),
                "mean_evidence_precision": float(s.mean_evidence_precision) if s.mean_evidence_precision is not None else None,
                "mean_tool_success_rate": float(s.mean_tool_success_rate) if s.mean_tool_success_rate is not None else None,
                "mean_tool_calls": float(s.mean_tool_calls),
                "budget_exhaustion_rate": float(s.budget_exhaustion_rate),
            }
            for s in report.case_summaries
        ],
    }


def export_report_json(report: RepeatedRunEvaluationReport, output_path: str | Path) -> None:
    """Safely export RepeatedRunEvaluationReport to a JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report_to_dict(report), handle, indent=2, ensure_ascii=False)


def format_dashboard(report: RepeatedRunEvaluationReport) -> str:
    """Format RepeatedRunEvaluationReport into a high-readability CLI dashboard."""
    lines = [
        "=" * 105,
        "                      MetricSleuth Benchmark Repeated Evaluation Dashboard",
        "=" * 105,
        f"Manifest ID:                 {report.manifest_id}",
        f"Total Benchmark Cases:       {report.total_cases}",
        f"Total Evaluation Runs:       {report.total_runs}",
        f"Overall Run Completion Rate: {report.overall_run_completion_rate:.2%}",
        f"Macro Driver Accuracy:       {report.macro_driver_accuracy:.2%}",
        f"Macro Scope Accuracy:        {report.macro_scope_accuracy:.2%}",
        f"Macro Exact Match Rate:      {report.macro_exact_match_rate:.2%}",
        "-" * 105,
        f"{'Case ID':<40} {'Runs':>5} {'Compl%':>7} {'Driver%':>8} {'Scope%':>7} {'Exact%':>7} {'Cov%':>7} {'Prec%':>7} {'Calls':>6}",
        "-" * 105,
    ]
    for s in report.case_summaries:
        prec_str = f"{s.mean_evidence_precision:.1%}" if s.mean_evidence_precision is not None else "N/A"
        lines.append(
            f"{s.case_id:<40} {s.total_runs:>5} {s.run_completion_rate:>7.1%} {s.mean_driver_accuracy:>8.1%} "
            f"{s.mean_scope_accuracy:>7.1%} {s.mean_exact_match_rate:>7.1%} {s.mean_evidence_coverage:>7.1%} "
            f"{prec_str:>7} {float(s.mean_tool_calls):>6.1f}"
        )
    lines.append("=" * 105)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MetricSleuth Benchmark Evaluation Runner")
    parser.add_argument("--manifest-id", type=str, default=None, help="Manifest identifier")
    parser.add_argument("--runs-per-case", type=int, default=1, help="Evaluation runs per case (default 1)")
    parser.add_argument("--cases-path", type=str, default=None, help="Path to benchmark cases JSON")
    parser.add_argument(
        "--model-id",
        type=str,
        default=None,
        help="LLM model identifier (defaults to METRICSLEUTH_AGENT_MODEL, then gpt-4o-mini)",
    )
    parser.add_argument("--hermetic", action="store_true", help="Run hermetic offline simulation")
    parser.add_argument("--database-url", type=str, default=None, help="PostgreSQL connection string")
    parser.add_argument("--output-json", type=str, default=None, help="File path to save JSON report")
    parser.add_argument(
        "--checkpoint-json",
        type=str,
        default=None,
        help="Atomically update a redacted per-run checkpoint after each completed run",
    )

    args = parser.parse_args(argv)

    if args.runs_per_case <= 0:
        print("Error: --runs-per-case must be a positive integer.", file=sys.stderr)
        return 1

    cases_path = Path(args.cases_path) if args.cases_path else DEFAULT_BENCHMARK_CASES
    if not cases_path.is_file():
        print(f"Error: Cases file not found: {cases_path}", file=sys.stderr)
        return 1

    # Load Ground Truth cases
    try:
        cases = load_ground_truth_cases(cases_path)
    except Exception as exc:
        print(f"Error loading Ground Truth cases from {cases_path}: {exc}", file=sys.stderr)
        return 1

    # Check credentials if Live mode
    db_url = args.database_url or os.environ.get("DATABASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not args.hermetic:
        if not api_key:
            print("Live Status: BLOCKED. OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
            return 2
        if not db_url:
            print("Live Status: BLOCKED. DATABASE_URL environment variable is not set.", file=sys.stderr)
            return 2

    configured_model_id = os.environ.get("METRICSLEUTH_AGENT_MODEL", "").strip()
    model_id = args.model_id.strip() if isinstance(args.model_id, str) and args.model_id.strip() else configured_model_id
    if not model_id:
        model_id = DEFAULT_MODEL_ID

    manifest_id = args.manifest_id or datetime.datetime.now(datetime.timezone.utc).strftime("manifest-benchmark-%Y%m%d-%H%M%S")
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    manifest = EvaluationManifest(
        manifest_id=manifest_id,
        model_id=model_id,
        prompt=DEFAULT_PROMPT,
        metric_config_version="v1.0.0",
        dataset_version="v1.0.0",
        run_counts_by_case={c.case_id: args.runs_per_case for c in cases},
        created_at=now_utc,
    )

    mode_label = "Hermetic (Offline Simulation)" if args.hermetic else f"Live Agent ({model_id})"
    print(f"\nStarting MetricSleuth Benchmark Evaluation: {mode_label}")
    print(f"Loaded {len(cases)} cases from {cases_path.name}. Runs per case: {args.runs_per_case} (Total Runs: {manifest.total_run_count}).")

    checkpoint_path = args.checkpoint_json
    if checkpoint_path is None and not args.hermetic and args.output_json:
        output_path = Path(args.output_json)
        checkpoint_path = str(output_path.with_name(output_path.name + ".checkpoint.json"))

    try:
        report = execute_evaluation_pipeline(
            manifest=manifest,
            cases=cases,
            hermetic=args.hermetic,
            database_url=db_url,
            checkpoint_path=checkpoint_path,
        )
    except Exception as exc:
        print(f"Evaluation pipeline failed: {exc}", file=sys.stderr)
        return 1

    print("\n" + format_dashboard(report))

    if args.output_json:
        export_report_json(report, args.output_json)
        print(f"\nReport successfully exported to: {args.output_json}")
    if checkpoint_path:
        print(f"Checkpoint path: {checkpoint_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
