"""Verify real Olist Analytics SQL through persisted task progress, without a model."""

from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.agent_runtime.investigation_runtime import InvestigationToolTraceEntry  # noqa: E402
from app.main import create_app  # noqa: E402
from app.observations.mapper import observations_from_metric_query  # noqa: E402
from app.task_application import TaskApplicationConfig, build_task_application  # noqa: E402


EXPECTED_DATABASE = "metricsleuth_r2_acceptance"
DEFAULT_TARGET_DATE = dt.date(2017, 3, 20)
FIXED_FAILURE = "controlled_runner_stop"


class AcceptanceFailure(Exception):
    """Safe fixed acceptance classification; never carries a driver error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def validate_database_url(database_url: str) -> None:
    """Refuse any database except the explicitly isolated local acceptance DB."""
    try:
        parsed = urlsplit(database_url)
        host = parsed.hostname
        port = parsed.port
        # Match the local application configuration, not a broader IP range.
        loopback = host in {"localhost", "127.0.0.1"}
        valid = (
            parsed.scheme in {"postgres", "postgresql"}
            and loopback
            and parsed.path == f"/{EXPECTED_DATABASE}"
            and not parsed.query
            and not parsed.fragment
            and (port is None or 1 <= port <= 65535)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise AcceptanceFailure("dedicated_loopback_test_database_required")


def _query_arguments(metric: str, target_date: dt.date, group_by: list[str]) -> dict[str, object]:
    return {
        "metric": metric,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "compare_to": "previous_7_days",
        "filters": {},
        "group_by": group_by,
    }


def _controlled_runner(target_date: dt.date, captured: dict[str, object]):
    """Execute four real metric queries and checkpoint each result immediately."""

    def run(_prompt: str, **kwargs: object) -> object:
        analytics = kwargs["analytics_tools"]
        progress_callback = kwargs["progress_callback"]
        if not callable(progress_callback):
            raise AcceptanceFailure("progress_callback_unavailable")

        steps = (
            ("merchandise_gmv", [], 1),
            ("orders", [], 1),
            ("olist_aov", [], 1),
            ("merchandise_gmv", ["customer_state"], 24),
        )
        output_counts: list[int] = []
        for index, (metric, group_by, expected_rows) in enumerate(steps):
            call_id = str(uuid4())
            arguments = _query_arguments(metric, target_date, group_by)
            result = analytics.query_metric(
                metric=metric,
                start_date=target_date,
                end_date=target_date,
                compare_to="previous_7_days",
                filters={},
                group_by=group_by,
            )
            observations = observations_from_metric_query(
                result,
                tool_name="query_metric",
                tool_call_id=call_id,
                filters={},
                query_or_result_reference=f"analytics-result:{call_id}",
                created_at=dt.datetime.now(dt.timezone.utc),
            )
            if len(observations) != expected_rows:
                raise AcceptanceFailure("analytics_observation_count_mismatch")
            trace = InvestigationToolTraceEntry(
                tool_call_id=call_id,
                tool_name="query_metric",
                arguments=arguments,
                observation_ids=tuple(item.observation_id for item in observations),
            )
            # Checkpoint first, then read through HTTP while the run is running.
            progress_callback(trace, observations)
            client = captured["client"]
            run_id = str(captured["run_id"])
            source_id = str(captured["source_id"])
            response = client.get(
                f"/api/investigations/{run_id}", params={"source_id": source_id}
            )
            if response.status_code != 200:
                raise AcceptanceFailure("progress_read_failed")
            detail = response.json()
            if detail["run"]["status"] != "running":
                raise AcceptanceFailure("run_not_running_during_progress")
            if len(detail["tool_calls"]) != index + 1:
                raise AcceptanceFailure("tool_progress_count_mismatch")
            if len(detail["observations"]) != sum(output_counts) + len(observations):
                raise AcceptanceFailure("observation_progress_count_mismatch")
            output_counts.append(len(observations))
            if index == 0:
                if len(result.rows) != 1:
                    raise AcceptanceFailure("overall_gmv_result_shape_invalid")
                row = result.rows[0]
                captured["gmv_current"] = row.current_value
                captured["gmv_baseline"] = row.baseline_value

        captured["observation_count"] = sum(output_counts)
        captured["tool_call_count"] = len(steps)
        raise RuntimeError(FIXED_FAILURE)

    return run


def _assert(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceFailure(code)


def verify(database_url: str, data_version: str, target_date: dt.date, source_id: str) -> dict[str, object]:
    validate_database_url(database_url)
    if target_date != DEFAULT_TARGET_DATE:
        raise AcceptanceFailure("acceptance_case_requires_2017_03_20")
    if not data_version.strip() or len(data_version) > 128:
        raise AcceptanceFailure("invalid_data_version")
    if not source_id.strip() or len(source_id) > 128:
        raise AcceptanceFailure("invalid_source_id")

    config = TaskApplicationConfig(
        state_database_url=database_url,
        analytics_database_url=database_url,
        profile="olist_validation",
        source_id=source_id,
        data_version=data_version,
        model="controlled-no-model",
    )
    captured: dict[str, object] = {
        "client": None,
        "run_id": None,
        "source_id": source_id,
        "observation_count": 0,
        "tool_call_count": 0,
    }
    service, worker = build_task_application(
        config,
        diagnosis_runner=_controlled_runner(target_date, captured),
    )
    client = TestClient(
        create_app(investigation_tasks_service=service, include_legacy_routes=False)
    )
    captured["client"] = client
    try:
        history = client.get("/api/investigations", params={"source_id": source_id, "limit": 100})
        _assert(history.status_code == 200, "task_history_read_failed")
        _assert(not history.json()["items"], "source_id_already_has_task_history")

        # Olist's declared contract excludes sessions and marketplace. These
        # requests must fail before a task row is created.
        unsupported = (
            {"source_id": source_id, "target_metric": "sessions", "target_date": target_date.isoformat(), "filters": {}, "group_by": []},
            {"source_id": source_id, "target_metric": "merchandise_gmv", "target_date": target_date.isoformat(), "filters": {}, "group_by": ["marketplace"]},
        )
        for payload in unsupported:
            response = client.post("/api/investigations", json=payload)
            _assert(response.status_code == 400, "unsupported_olist_request_not_rejected")
        after_rejections = client.get(
            "/api/investigations", params={"source_id": source_id, "limit": 100}
        )
        _assert(after_rejections.status_code == 200, "task_history_read_failed")
        _assert(not after_rejections.json()["items"], "rejected_request_created_task")

        submit_response = client.post(
            "/api/investigations",
            json={
                "source_id": source_id,
                "target_metric": "merchandise_gmv",
                "target_date": target_date.isoformat(),
                "filters": {},
                "group_by": ["customer_state"],
            },
        )
        _assert(submit_response.status_code == 202, "task_submission_failed")
        run_id = submit_response.json()["investigation_run_id"]
        captured["run_id"] = run_id
        _assert(submit_response.json()["status"] == "queued", "task_not_queued")
        processed = worker.run_once()
        _assert(processed == run_id, "worker_processed_different_task")
        # Worker deliberately maps Runner errors to the same safe failure code.
        # Do not mistake a verification exception after the final checkpoint
        # for the intentional stop that this acceptance case requires.
        _assert(captured["tool_call_count"] == 4 and captured["observation_count"] == 27,
                "controlled_steps_not_completed")

        response = client.get(f"/api/investigations/{run_id}", params={"source_id": source_id})
        _assert(response.status_code == 200, "persisted_detail_read_failed")
        detail = response.json()
        _assert(detail["run"]["status"] == "failed", "controlled_run_not_failed")
        _assert(detail["run"]["failure_code"] == "execution_failed", "unexpected_failure_code")
        _assert(detail["run"]["provider"] == "olist", "unexpected_data_provider")
        _assert(detail["run"]["environment"] == "validation", "unexpected_data_environment")
        _assert(len(detail["tool_calls"]) == 4, "persisted_tool_count_mismatch")
        _assert(len(detail["observations"]) == 27, "persisted_observation_count_mismatch")
        _assert(not detail["evidence"], "unexpected_evidence_created")
        _assert(not detail["diagnoses"], "unexpected_diagnosis_created")

        # A new configured service/API instance must read the committed facts.
        new_service, _new_worker = build_task_application(
            config, diagnosis_runner=_controlled_runner(target_date, captured)
        )
        new_client = TestClient(
            create_app(investigation_tasks_service=new_service, include_legacy_routes=False)
        )
        try:
            reread = new_client.get(
                f"/api/investigations/{run_id}", params={"source_id": source_id}
            )
            _assert(reread.status_code == 200, "fresh_application_read_failed")
            _assert(reread.json() == detail, "fresh_application_result_mismatch")
        finally:
            new_client.close()

        return {
            "source_id": source_id,
            "investigation_run_id": run_id,
            "data_version": data_version,
            "provider": detail["run"]["provider"],
            "environment": detail["run"]["environment"],
            "status": detail["run"]["status"],
            "tool_call_count": len(detail["tool_calls"]),
            "observation_count": len(detail["observations"]),
            "evidence_count": len(detail["evidence"]),
            "diagnosis_count": len(detail["diagnoses"]),
            "unsupported_requests_rejected": True,
            "controlled_runner": True,
            "real_model": False,
            "overall_gmv": {
                "current": _decimal_text(captured.get("gmv_current")),
                "baseline": _decimal_text(captured.get("gmv_baseline")),
            },
        }
    finally:
        client.close()


def _decimal_text(value: object) -> str | None:
    return format(value, "f") if isinstance(value, Decimal) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Persist real Olist Analytics observations through a controlled task runner."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--target-date", type=dt.date.fromisoformat, default=DEFAULT_TARGET_DATE)
    parser.add_argument("--source-id", default=None)
    args = parser.parse_args(argv)
    source_id = args.source_id or str(uuid4())
    try:
        result = verify(args.database_url, args.data_version, args.target_date, source_id)
    except AcceptanceFailure as exc:
        print(json.dumps({"status": "failed", "code": exc.code}), file=sys.stderr)
        return 2
    except Exception:
        # Driver/model/runtime exceptions never leave the script. The runner
        # stop itself is caught and persisted by Worker as a fixed failure code.
        print(json.dumps({"status": "failed", "code": "acceptance_execution_failed"}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
