"""Explicit six-run development evaluation on fresh isolated Sandbox databases.

No reset, migration, retry, external data or alternative runtime. Ground Truth
remains in this evaluator; product requests contain only metric/date/scope.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from scripts.prepare_sandbox_evaluation import prepare
from scripts.score_persisted_task import restore_composition, score_detail
from scripts.serve_live_browser_task_acceptance import (
    AcceptanceEventLog, SafeArgumentParser, SAFE_EXCEPTION, close_model_client,
    install_model_client, load_model_settings, preflight_database, validate_database_url,
)
from app.evaluation import load_ground_truth_cases, score_core_case, score_evidence_citations


def stop_after_error(name, http_status=None):
    return http_status in (401, 403, 422) or name in {
        "AuthenticationError", "PermissionDeniedError", "BadRequestError", "APITimeoutError",
        "APIConnectionError", "UserError", "ModelBehaviorError", "RuntimeTraceError",
    }


def score_run(detail, case):
    result = score_detail(detail, source_id=detail.run.source_id, data_version=detail.run.data_version,
                          expected_metric=case.target_metric, expected_status=case.status.value,
                          expected_driver=case.primary_driver)
    if detail.run.status != "succeeded":
        return {**result, "exact_match": False, "evidence_coverage": None,
                "scope_accuracy": None, "missing_obligations": None}
    composition = restore_composition(detail)
    core = score_core_case(case, composition.diagnosis)
    citations = score_evidence_citations(case, composition)
    return {**result, "exact_match": core.exact_match, "scope_accuracy": str(core.scope_accuracy),
            "scope_correct": dict(core.scope_correct),
            "evidence_coverage": str(citations.evidence_coverage),
            "missing_obligations": [o for o in citations.obligation_ids if o not in citations.covered_obligation_ids],
            "diagnosed_scope": dict(composition.diagnosis.affected_scope)}


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--model-env-file", required=True)
    parser.add_argument("--safe-log-file", required=True)
    parser.add_argument("--allow-six-model-investigations", action="store_true", required=True)
    args = parser.parse_args(argv)
    log = client = None
    try:
        validate_database_url(args.database_url)
        log = AcceptanceEventLog(args.safe_log_file)
        plan = prepare()
        log.emit({"event": "plan_frozen", "plan": plan, "authorized_maximum": 6,
                  "request_timeout_seconds": 120})
        preflight_database(args.database_url)
        settings = load_model_settings(args.model_env_file)
        client, model, mode = install_model_client(settings, request_timeout_seconds=120)
        log.emit({"event": "model_configuration", "api_mode": mode,
                  "configured_model": model if model == "gemini-3.8-flash-high" else "configured_other"})
        import psycopg
        from psycopg import sql
        from app.agent_runtime.diagnosis_runtime import run_evidence_driven_diagnosis
        from app.api.task_schemas import InvestigationTaskCreate
        from app.data_sources import DataSourceDescriptor, SourceEnvironment, SourceProvider
        from app.sandbox.dataset_writer import SandboxTarget, publish_sandbox_dataset
        from app.task_application import TaskApplicationConfig, build_task_application

        cases = {c.case_id: c for c in load_ground_truth_cases(ROOT / "warehouse/benchmark_cases.json")}
        parsed = urlsplit(args.database_url)

        def uri(database):
            return urlunsplit(parsed._replace(path="/" + database))

        batch = uuid4().hex[:12]
        attempted = succeeded = exact = passed = 0
        stop = False
        for prepared in plan["cases"]:
            name = f"metricsleuth_sandbox_r6_{batch}_{prepared['scenario']}"
            source_id = str(uuid4())
            log.emit({"event": "dataset_reserved", "database": name, "source_id": source_id,
                      "case_id": prepared["case_id"]})
            with psycopg.connect(uri("postgres"), autocommit=True) as admin:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            target = SandboxTarget(uri(name), DataSourceDescriptor(
                source_id, "Isolated evaluation source", SourceProvider.SYNTHETIC, SourceEnvironment.SANDBOX))
            publication = publish_sandbox_dataset(target, prepared["scenario"])
            if publication.data_version != prepared["data_version"]:
                raise ValueError("published_input_version_mismatch")
            log.emit({"event": "dataset_published", "source_id": source_id,
                      "data_version": publication.data_version, "row_count": publication.row_count})

            telemetry = {}

            def runner(*runner_args, **kwargs):
                started = time.monotonic()
                telemetry["started"] = True
                try:
                    summary = run_evidence_driven_diagnosis(*runner_args, **kwargs)
                    telemetry.update(turns=summary.investigation.turns_count,
                                     tool_calls=summary.investigation.tool_calls_count,
                                     tokens=dict(summary.token_usage) if summary.token_usage is not None else None)
                    return summary
                except Exception as exc:
                    kind = type(exc).__name__
                    telemetry["exception_type"] = kind if SAFE_EXCEPTION.fullmatch(kind) else "OtherError"
                    status = getattr(exc, "status_code", None)
                    telemetry["http_status"] = status if type(status) is int and 100 <= status <= 599 else None
                    raise
                finally:
                    telemetry["duration_ms"] = int((time.monotonic() - started) * 1000)

            config = TaskApplicationConfig(args.database_url, uri(name), "sandbox_manifest",
                                           source_id, publication.data_version, model, 8, 10)
            service, worker = build_task_application(config, diagnosis_runner=runner)
            for repetition in (1, 2):
                telemetry.clear()
                telemetry.update(started=False, turns=None, tool_calls=None, exception_type=None,
                                 http_status=None, tokens=None, cost=None)
                run = service.submit(InvestigationTaskCreate.model_validate(
                    {"source_id": source_id, **prepared["task_input"]}))
                log.emit({"event": "task_submitted", "run_id": run.investigation_run_id,
                          "source_id": source_id, "case_id": prepared["case_id"], "repetition": repetition})
                previous = logging.root.manager.disable
                try:
                    logging.disable(logging.CRITICAL)
                    processed = worker.run_once()
                finally:
                    logging.disable(previous)
                if processed != run.investigation_run_id:
                    raise ValueError("expected_task_not_processed")
                attempted += int(telemetry["started"])
                log.emit({"event": "runner_finished", "run_id": run.investigation_run_id,
                          "telemetry": dict(telemetry)})
                detail = service.get_run(run.investigation_run_id, source_id)
                score = score_run(detail, cases[prepared["case_id"]])
                succeeded += int(detail.run.status == "succeeded")
                exact += int(score["exact_match"])
                passed += int(score["exact_match"] and score["semantic_passed"]
                              and score["provenance_passed"] and score["evidence_coverage"] == "1")
                record = {"event": "run_scored", "case_id": prepared["case_id"], "repetition": repetition,
                          "run_id": run.investigation_run_id, "source_id": source_id,
                          "status": detail.run.status, "failure_code": detail.run.failure_code,
                          "counts": {"tools": len(detail.tool_calls), "observations": len(detail.observations),
                                     "evidence": len(detail.evidence), "diagnoses": len(detail.diagnoses)},
                          "telemetry": dict(telemetry), "score": score}
                log.emit(record)
                print(json.dumps(record, sort_keys=True), flush=True)
                if stop_after_error(telemetry["exception_type"], telemetry["http_status"]):
                    stop = True
                    break
            if stop:
                break
        result = {"event": "batch_finished", "planned": 6, "attempted": attempted,
                  "succeeded": succeeded, "failed": attempted - succeeded, "not_executed": 6 - attempted,
                  "exact_matches": exact, "strict_passed": passed, "stopped_early": stop, "real_model": True,
                  "external_business_data": False, "stop_timing": "not_evaluated"}
        log.emit(result)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if passed == 6 else 1
    except Exception as exc:
        kind = type(exc).__name__
        result = {"event": "batch_aborted", "exception_type": kind if SAFE_EXCEPTION.fullmatch(kind) else "OtherError"}
        if log is not None:
            try:
                log.emit(result)
            except OSError:
                pass
        print(json.dumps(result), flush=True)
        return 2
    finally:
        if client is not None:
            close_model_client(client)
        if log is not None:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
