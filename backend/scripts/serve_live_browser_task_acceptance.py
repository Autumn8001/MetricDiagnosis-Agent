"""Serve one isolated browser-submitted investigation through the real SDK worker.

This is an explicit, bounded acceptance harness.  It only accepts the dedicated
local PostgreSQL database used by the existing live-model persistence check and
requires an opt-in model-call flag.  It never prints model credentials, prompt
content, model responses, or raw exceptions.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


EXPECTED_DATABASE = "metricsleuth_r2_acceptance"
TARGET_DATE = date(2026, 10, 10)
DATA_VERSION = "synthetic-live-browser-acceptance-2026-10-15-v1"
MAX_TOOL_CALLS = 8
MAX_TURNS = 10
WORKER_WAIT_SECONDS = 150
SERVER_LIFETIME_SECONDS = 210
SAFE_EXCEPTION = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")


class AcceptanceFailure(Exception):
    """A stable, non-sensitive acceptance failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, "invalid_arguments\n")


def validate_database_url(database_url: str) -> None:
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


def load_model_settings(env_file: str) -> tuple[str, str | None, str, str]:
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
    mode = (mode or "responses").strip().lower()
    if mode not in {"responses", "chat_completions"}:
        raise AcceptanceFailure("model_api_mode_invalid")
    return key.strip(), base.strip() if base else None, mode, model.strip()


def install_model_client(settings: tuple[str, str | None, str, str]):
    from agents import set_default_openai_client, set_tracing_disabled
    from openai import AsyncOpenAI

    key, base_url, mode, model = settings
    os.environ["OPENAI_API_KEY"] = key
    if base_url:
        os.environ["OPENAI_BASE_URL"] = base_url
    else:
        os.environ.pop("OPENAI_BASE_URL", None)
    os.environ["OPENAI_API_MODE"] = mode
    os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    client = AsyncOpenAI(api_key=key, base_url=base_url, max_retries=0, timeout=60)
    set_default_openai_client(client, use_for_tracing=False)
    set_tracing_disabled(True)
    return client, model, mode


def close_model_client(client: Any) -> None:
    try:
        result = client.close()
        if hasattr(result, "__await__"):
            asyncio.run(result)
    except Exception:
        pass


def connect(database_url: str):
    import psycopg

    try:
        return psycopg.connect(database_url, autocommit=False, connect_timeout=5)
    except Exception:
        raise AcceptanceFailure("acceptance_database_unavailable") from None


@contextmanager
def database(database_url: str):
    connection = connect(database_url)
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def preflight_database(database_url: str) -> None:
    try:
        with database(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT current_database(), to_regclass('warehouse.dim_products'),
                          to_regclass('warehouse.fact_daily_performance'),
                          to_regclass('app_state.investigation_runs')"""
            )
            database_name, products, facts, runs = cursor.fetchone()
            if database_name != EXPECTED_DATABASE or not all((products, facts, runs)):
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


def insert_fixture(database_url: str, asin: str) -> None:
    try:
        with database(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO warehouse.dim_products (asin, product_name, category)
                   VALUES (%s, %s, %s)""",
                (asin, "MetricSleuth live browser acceptance product", "Acceptance fixture"),
            )
            for offset in range(7, -1, -1):
                day = TARGET_DATE - timedelta(days=offset)
                is_target = day == TARGET_DATE
                cursor.execute(
                    """INSERT INTO warehouse.fact_daily_performance
                       (date, asin, marketplace, traffic_source, impressions, clicks,
                        sessions, orders, sales, ad_spend, refunds)
                       VALUES (%s, %s, 'US', 'test', 100, 10, 100, %s, %s, 0, 0)""",
                    (day, asin, 8 if is_target else 10,
                     Decimal("80.00") if is_target else Decimal("100.00")),
                )
            connection.commit()
    except Exception:
        raise AcceptanceFailure("synthetic_fixture_insert_failed") from None


def build_application(database_url: str, source_id: str, model: str):
    from app.main import create_app
    from app.task_application import TaskApplicationConfig, build_task_application

    config = TaskApplicationConfig(
        database_url, database_url, "synthetic", source_id, DATA_VERSION,
        model, MAX_TOOL_CALLS, MAX_TURNS,
    )
    service, worker = build_task_application(config)
    return create_app(investigation_tasks_service=service, include_legacy_routes=False), worker


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--model-env-file", required=True)
    parser.add_argument("--port", type=int, default=8014)
    parser.add_argument("--allow-model-call", action="store_true", required=True)
    args = parser.parse_args(argv)
    validate_database_url(args.database_url)
    if not 1 <= args.port <= 65535 or not Path(args.model_env_file).is_file():
        parser.error("invalid_arguments")
    return args


def main(argv: list[str] | None = None) -> int:
    client = None
    server = None
    server_thread = None
    worker_thread = None
    try:
        args = parse_args(argv)
        settings = load_model_settings(args.model_env_file)
        preflight_database(args.database_url)
        source_id = str(uuid4())
        asin = str(uuid4())
        insert_fixture(args.database_url, asin)
        client, model, mode = install_model_client(settings)
        application, worker = build_application(args.database_url, source_id, model)
        state = {"submitted": False, "processed": None, "exception_type": None}
        state_lock = threading.Lock()
        acceptance_complete = threading.Event()
        original_submit = application.state.investigation_tasks_service.submit

        def submit_and_signal(payload: Any):
            result = original_submit(payload)
            with state_lock:
                state["submitted"] = True
            return result

        application.state.investigation_tasks_service.submit = submit_and_signal

        def complete_acceptance() -> dict[str, str]:
            """End the explicit harness after the browser has read its terminal result."""
            acceptance_complete.set()
            return {"status": "accepted"}

        manifest = {
            "acceptance_kind": "live_model_browser_task",
            "database": EXPECTED_DATABASE,
            "source_id": source_id,
            "target_date": TARGET_DATE.isoformat(),
            "target_metric": "sales",
            "request_filters": {"asin": asin},
            "max_tool_calls": MAX_TOOL_CALLS,
            "max_turns": MAX_TURNS,
            "controlled_runner": False,
            "real_model": True,
            "data_profile": "synthetic",
            "data_version": DATA_VERSION,
            "api_mode": mode,
        }
        application.add_api_route("/__acceptance__/manifest", lambda: manifest, methods=["GET"], include_in_schema=False)
        application.add_api_route("/__acceptance__/complete", complete_acceptance, methods=["POST"], include_in_schema=False)

        import uvicorn

        logging.getLogger("uvicorn.error").disabled = True
        logging.getLogger("uvicorn.access").disabled = True
        server = uvicorn.Server(uvicorn.Config(
            application, host="127.0.0.1", port=args.port, access_log=False,
            log_config=None, log_level="critical", timeout_graceful_shutdown=5,
        ))
        server_thread = threading.Thread(target=server.run, name="live-browser-api", daemon=True)
        server_thread.start()
        startup_deadline = time.monotonic() + 15
        while not server.started and server_thread.is_alive() and time.monotonic() < startup_deadline:
            time.sleep(0.05)
        if not server.started:
            raise AcceptanceFailure("acceptance_server_start_failed")

        stop_worker = threading.Event()

        def run_worker() -> None:
            deadline = time.monotonic() + WORKER_WAIT_SECONDS
            while not stop_worker.is_set() and time.monotonic() < deadline:
                with state_lock:
                    submitted = state["submitted"]
                if submitted:
                    try:
                        processed = worker.run_once()
                        with state_lock:
                            state["processed"] = processed
                    except BaseException as exc:
                        name = type(exc).__name__
                        with state_lock:
                            state["exception_type"] = name if SAFE_EXCEPTION.fullmatch(name) else "OtherError"
                    return
                time.sleep(0.1)

        worker_thread = threading.Thread(target=run_worker, name="live-browser-worker", daemon=True)
        worker_thread.start()
        print(f"acceptance_server_ready http://127.0.0.1:{args.port}", flush=True)
        deadline = time.monotonic() + SERVER_LIFETIME_SECONDS
        while time.monotonic() < deadline and server_thread.is_alive():
            with state_lock:
                processed = state["processed"]
                failure = state["exception_type"]
            if acceptance_complete.is_set():
                print(json.dumps({"worker": "processed" if processed else "failed", "exception_type": failure}, sort_keys=True), flush=True)
                return 0 if processed is not None else 1
            time.sleep(0.2)
        raise AcceptanceFailure("acceptance_server_lifetime_expired")
    except AcceptanceFailure as exc:
        print(json.dumps({"status": "failed", "code": exc.code}, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"status": "failed", "code": "acceptance_setup_failed"}, sort_keys=True))
        return 1
    finally:
        if worker_thread is not None:
            stop_worker.set()
            worker_thread.join(timeout=7)
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=7)
        if client is not None:
            close_model_client(client)


if __name__ == "__main__":
    raise SystemExit(main())
