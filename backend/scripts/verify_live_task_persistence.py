"""One-shot real-model persistence acceptance on isolated Synthetic data."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import date, timedelta
from decimal import Decimal
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

EXPECTED_DATABASE = "metricsleuth_r2_acceptance"
TARGET_DATE = date(2026, 10, 10)
DATA_VERSION = "synthetic-live-acceptance-2026-10-10-v1"
MAX_TOOL_CALLS = 8
MAX_TURNS = 10
_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SAFE_EXCEPTION = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
_ALLOWED_METRICS = frozenset({"sales", "orders", "sessions", "conversion_rate", "aov"})
_ALLOWED_SCOPE_VALUES = frozenset({"US", "test"})
_ALLOWED_DIMENSIONS = frozenset({"asin", "marketplace", "traffic_source"})
_ALLOWED_TOOLS = frozenset({"query_metric", "query_related_metrics", "get_metric_definition"})
_OBSERVATION_STATUSES = frozenset({"anomalous", "normal", "inconclusive", "insufficient_evidence", "failed"})
_DIAGNOSIS_STATUSES = frozenset({"diagnosed", "no_material_anomaly", "insufficient_evidence", "budget_exhausted", "tool_failure"})


class AcceptanceFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code if _SAFE_CODE.fullmatch(code) else "acceptance_failed"
        super().__init__(self.code)


class SafeArgumentParser(argparse.ArgumentParser):
    """Keep argparse errors from echoing user-supplied argument values."""

    def error(self, _message: str) -> None:
        self.exit(2, "invalid_arguments\n")


def validate_database_url(database_url: str) -> None:
    """Allow only the dedicated local acceptance database, without URL options."""
    try:
        parsed = urlsplit(database_url)
        port = parsed.port
        valid = (
            parsed.scheme in {"postgres", "postgresql"}
            and parsed.hostname in {"localhost", "127.0.0.1"}
            and parsed.path == f"/{EXPECTED_DATABASE}"
            and not parsed.query
            and not parsed.fragment
            and (port is None or 1 <= port <= 65535)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise AcceptanceFailure("dedicated_loopback_test_database_required")


def _load_explicit_model_settings(env_file: str) -> tuple[str, str | None, str, str]:
    """Read only explicitly selected settings; never report values."""
    from dotenv import dotenv_values

    try:
        values = dotenv_values(env_file)
    except Exception:
        raise AcceptanceFailure("model_environment_file_unavailable") from None

    key, base, mode, model = (values.get(name) for name in (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_MODE", "METRICSLEUTH_AGENT_MODEL"
    ))
    if not isinstance(key, str) or not key.strip():
        raise AcceptanceFailure("model_api_key_missing")
    if base is not None and (not isinstance(base, str) or not base.strip()):
        raise AcceptanceFailure("model_base_url_invalid")
    if not isinstance(model, str) or not model.strip():
        raise AcceptanceFailure("model_name_missing")
    if mode is not None and not isinstance(mode, str):
        raise AcceptanceFailure("model_api_mode_invalid")
    mode = (mode or "responses").strip().lower()
    if mode not in {"responses", "chat_completions"}:
        raise AcceptanceFailure("model_api_mode_invalid")
    return key.strip(), base.strip() if base else None, mode, model.strip()


def _install_explicit_model_client(settings: tuple[str, str | None, str, str]):
    """Configure SDK credentials only after opt-in and URL checks."""
    from agents import set_default_openai_client, set_tracing_disabled
    from openai import AsyncOpenAI

    api_key, base_url, api_mode, model = settings
    os.environ["OPENAI_API_KEY"] = api_key
    if base_url:
        os.environ["OPENAI_BASE_URL"] = base_url
    else:
        os.environ.pop("OPENAI_BASE_URL", None)
    os.environ["OPENAI_API_MODE"] = api_mode
    os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60)
    set_default_openai_client(client, use_for_tracing=False)
    set_tracing_disabled(True)
    return client, model, api_mode


def _close_async_client(client: Any) -> None:
    try:
        close_result = client.close()
        if hasattr(close_result, "__await__"):
            asyncio.run(close_result)
    except Exception:
        pass


def _open_database(database_url: str):
    import psycopg

    try:
        return psycopg.connect(database_url, autocommit=False, connect_timeout=5)
    except Exception:
        raise AcceptanceFailure("acceptance_database_unavailable") from None


@contextmanager
def _database(database_url: str):
    connection = _open_database(database_url)
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _preflight_database(database_url: str) -> None:
    """Refuse missing schema or any existing queued/running Worker task."""
    try:
        with _database(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_database(),
                       to_regclass('warehouse.dim_products'),
                       to_regclass('warehouse.fact_daily_performance'),
                       to_regclass('app_state.investigation_runs')
                """
            )
            database, products, facts, runs = cursor.fetchone()
            if database != EXPECTED_DATABASE:
                raise AcceptanceFailure("dedicated_database_name_mismatch")
            if products is None or facts is None or runs is None:
                raise AcceptanceFailure("required_existing_tables_missing")
            cursor.execute(
                """SELECT count(*) FROM app_state.investigation_runs
                   WHERE execution_mode = 'worker' AND status IN ('queued', 'running')"""
            )
            if cursor.fetchone()[0] != 0:
                raise AcceptanceFailure("active_worker_tasks_present")
            connection.rollback()
    except AcceptanceFailure:
        raise
    except Exception:
        raise AcceptanceFailure("acceptance_database_preflight_failed") from None


def _insert_synthetic_fixture(database_url: str, asin: str) -> None:
    """Insert only this run's product and seven baseline plus one target row."""
    try:
        with _database(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO warehouse.dim_products (asin, product_name, category)
                   VALUES (%s, %s, %s)""",
                (asin, "MetricSleuth isolated acceptance product", "Acceptance fixture"),
            )
            for offset in range(7, -1, -1):
                day = TARGET_DATE - timedelta(days=offset)
                target = day == TARGET_DATE
                cursor.execute(
                    """INSERT INTO warehouse.fact_daily_performance
                       (date, asin, marketplace, traffic_source, impressions, clicks,
                        sessions, orders, sales, ad_spend, refunds)
                       VALUES (%s, %s, 'US', 'test', 100, 10, 100, %s, %s, 0, 0)""",
                    (day, asin, 8 if target else 10, Decimal("80.00") if target else Decimal("100.00")),
                )
            connection.commit()
    except Exception:
        raise AcceptanceFailure("synthetic_fixture_insert_failed") from None


def _registered(value: object, allowed: frozenset[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _safe_http_status(value: object) -> int | None:
    return value if type(value) is int and 100 <= value <= 599 else None


def _safe_group_by(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if _registered(item, _ALLOWED_DIMENSIONS)]


def _safe_scope(asin: str, *mappings: object) -> dict[str, str]:
    scope: dict[str, str] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            if key == "asin" and value == asin:
                scope[key] = asin
            elif key in {"marketplace", "traffic_source"} and isinstance(value, str) and value in _ALLOWED_SCOPE_VALUES:
                scope[key] = value
    return scope


def _json_safe_detail(detail: dict[str, Any], asin: str) -> dict[str, object]:
    """Project persisted facts into the explicitly allowed output vocabulary."""
    calls, raw_observations = detail.get("tool_calls", []), detail.get("observations", [])
    raw_evidence, raw_diagnoses = detail.get("evidence", []), detail.get("diagnoses", [])
    trace = [
        {
            "tool_name": _registered(call.get("tool_name"), _ALLOWED_TOOLS) or "unknown_tool",
            "metric": _registered((call.get("arguments") or {}).get("metric"), _ALLOWED_METRICS),
            "group_by": _safe_group_by((call.get("arguments") or {}).get("group_by")),
            "filters": _safe_scope(asin, (call.get("arguments") or {}).get("filters")),
        }
        for call in calls
    ]
    observations = [
        {
            "metric": _registered(item.get("metric"), _ALLOWED_METRICS),
            "status": _registered(item.get("status"), _OBSERVATION_STATUSES) or "unknown",
            "current_value": _decimal_text(item.get("current_value")),
            "baseline_value": _decimal_text(item.get("baseline_value")),
            "relative_change": _decimal_text(item.get("relative_change")),
            "scope": _safe_scope(asin, item.get("dimensions"), item.get("filters")),
        }
        for item in raw_observations
    ]
    diagnoses = [
        {
            "status": _registered(item.get("status"), _DIAGNOSIS_STATUSES) or "unknown",
            "primary_driver": _registered(item.get("primary_driver"), _ALLOWED_METRICS),
            "affected_scope": _safe_scope(asin, item.get("affected_scope")),
            "evidence_reference_count": len(item.get("evidence_ids") or []),
        }
        for item in raw_diagnoses
    ]
    evidence_ids = {item.get("evidence_id") for item in raw_evidence}
    diagnosis_reference_count = sum(len(item.get("evidence_ids") or []) for item in raw_diagnoses)
    refs_valid = bool(raw_diagnoses) and all(
        bool(item.get("evidence_ids"))
        and set(item.get("evidence_ids") or []).issubset(evidence_ids)
        for item in raw_diagnoses
    )
    return {
        "run": {
            "run_id": detail["run"]["investigation_run_id"],
            "source_id": detail["run"]["source_id"],
            "status": detail["run"]["status"],
            "failure_code": _safe_code(detail["run"].get("failure_code")),
            "tool_call_count": len(calls),
            "observation_count": len(raw_observations),
            "evidence_count": len(raw_evidence),
            "diagnosis_count": len(raw_diagnoses),
        },
        "tool_trace": trace,
        "observations": observations,
        "diagnoses": diagnoses,
        "diagnosis_evidence_reference_count": diagnosis_reference_count,
        "evidence_references_valid": refs_valid,
    }


def _decimal_text(value: object) -> str | None:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, str) and len(value) <= 64:
        try:
            parsed = Decimal(value)
        except Exception:
            return None
        return format(parsed, "f") if parsed.is_finite() else None
    return None


def _safe_code(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_CODE.fullmatch(value) else None


def run_acceptance(database_url: str, model_env_file: str) -> dict[str, object]:
    """Run one task through API, real SDK, PostgreSQL Worker, and fresh read."""
    from fastapi.testclient import TestClient

    from app.agent_runtime.diagnosis_runtime import run_evidence_driven_diagnosis
    from app.main import create_app
    from app.task_application import TaskApplicationConfig, build_task_application

    validate_database_url(database_url)
    settings = _load_explicit_model_settings(model_env_file)
    _preflight_database(database_url)
    asin = str(uuid4())
    source_id = str(uuid4())
    _insert_synthetic_fixture(database_url, asin)
    sdk_client, model, api_mode = _install_explicit_model_client(settings)
    capture: dict[str, object] = dict.fromkeys(
        ("turn_count", "tool_call_count", "exception_type", "http_status")
    )

    def live_diagnosis_runner(*args: object, **kwargs: object):
        try:
            summary = run_evidence_driven_diagnosis(*args, **kwargs)
            investigation = summary.investigation
            capture["turn_count"] = investigation.turns_count
            capture["tool_call_count"] = investigation.tool_calls_count
            return summary
        except BaseException as exc:
            name = type(exc).__name__
            capture["exception_type"] = name if _SAFE_EXCEPTION.fullmatch(name) else "OtherError"
            capture["http_status"] = _safe_http_status(getattr(exc, "status_code", None))
            raise

    config = TaskApplicationConfig(database_url, database_url, "synthetic", source_id,
                                   DATA_VERSION, model, MAX_TOOL_CALLS, MAX_TURNS)
    try:
        service, worker = build_task_application(config, diagnosis_runner=live_diagnosis_runner)
        app = create_app(investigation_tasks_service=service, include_legacy_routes=False)
        with TestClient(app) as client, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            submit = client.post("/api/investigations", json={
                "source_id": source_id, "target_metric": "sales",
                "target_date": TARGET_DATE.isoformat(), "filters": {"asin": asin},
                "group_by": ["marketplace"],
            })
            if submit.status_code != 202:
                raise AcceptanceFailure("task_submission_failed")
            run_id = submit.json().get("investigation_run_id")
            if not isinstance(run_id, str):
                raise AcceptanceFailure("task_run_identifier_missing")
            _assert_only_own_task_queued(database_url, run_id)
            prior_disable = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            try:
                processed = worker.run_once()
            finally:
                logging.disable(prior_disable)
            if processed != run_id:
                raise AcceptanceFailure("worker_processed_unexpected_task")
            response = client.get(f"/api/investigations/{run_id}", params={"source_id": source_id})
            if response.status_code != 200:
                raise AcceptanceFailure("persisted_task_read_failed")
            first_detail = response.json()
            fresh_service, _ = build_task_application(config, diagnosis_runner=live_diagnosis_runner)
            fresh_app = create_app(investigation_tasks_service=fresh_service, include_legacy_routes=False)
            with TestClient(fresh_app) as fresh_client:
                reread = fresh_client.get(f"/api/investigations/{run_id}", params={"source_id": source_id})
            if reread.status_code != 200 or reread.json() != first_detail:
                raise AcceptanceFailure("fresh_application_read_mismatch")

        safe = _json_safe_detail(first_detail, asin)
        run = safe["run"]
        successful = (
            run["status"] == "succeeded"
            and run["diagnosis_count"] == 1
            and run["evidence_count"] > 0
            and safe["diagnosis_evidence_reference_count"] > 0
            and safe["evidence_references_valid"] is True
            and capture["tool_call_count"] is not None
            and capture["tool_call_count"] <= MAX_TOOL_CALLS
            and capture["turn_count"] is not None
            and capture["turn_count"] <= MAX_TURNS
        )
        return {
            "status": "passed" if successful else "failed",
            "model": "configured",
            "api_mode": api_mode,
            "data_profile": "synthetic",
            "data_version": DATA_VERSION,
            "asin": asin,
            "runtime": {
                "model_execution": "response_received" if capture["turn_count"] is not None else "failed_or_unknown",
                "turn_count": capture["turn_count"],
                "tool_call_count": capture["tool_call_count"]
                if capture["tool_call_count"] is not None
                else run["tool_call_count"],
                "exception_type": capture["exception_type"],
                "http_status": capture["http_status"],
                "max_turns": MAX_TURNS,
                "max_tool_calls": MAX_TOOL_CALLS,
            },
            "persistence": safe,
        }
    finally:
        _close_async_client(sdk_client)


def _assert_only_own_task_queued(database_url: str, run_id: str) -> None:
    try:
        with _database(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT investigation_run_id FROM app_state.investigation_runs
                   WHERE execution_mode = 'worker' AND status = 'queued'"""
            )
            queued_ids = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT count(*) FROM app_state.investigation_runs
                   WHERE execution_mode = 'worker' AND status = 'running'"""
            )
            running = cursor.fetchone()[0]
            if queued_ids != [run_id] or running != 0:
                raise AcceptanceFailure("unexpected_active_worker_tasks")
            connection.rollback()
    except AcceptanceFailure:
        raise
    except Exception:
        raise AcceptanceFailure("acceptance_queue_check_failed") from None


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--model-env-file", required=True)
    parser.add_argument("--allow-model-call", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        # These guards run before reading model settings, opening PostgreSQL,
        # or constructing the OpenAI client.
        validate_database_url(args.database_url)
        settings_file = Path(args.model_env_file)
        if not settings_file.is_file():
            raise AcceptanceFailure("model_environment_file_unavailable")
        result = run_acceptance(args.database_url, str(settings_file))
    except AcceptanceFailure as exc:
        print(json.dumps({"status": "failed", "code": exc.code}, sort_keys=True))
        return 2
    except Exception:
        # Do not print driver errors, SDK responses, request bodies, or tracebacks.
        print(json.dumps({"status": "failed", "code": "acceptance_execution_failed"}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
