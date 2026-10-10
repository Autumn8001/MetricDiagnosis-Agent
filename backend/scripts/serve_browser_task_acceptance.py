"""Serve one isolated, controlled Synthetic browser task acceptance run.

Run from ``backend``. This explicit harness never reads .env or model credentials.
The actual FastAPI task routes, PostgreSQL worker and AnalyticsTools execute the
round trip; only the diagnosis decision is controlled and makes no model call.
"""

from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal
import json
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from fastapi import FastAPI

from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary
from app.agent_runtime.investigation_runtime import InvestigationRunSummary, InvestigationToolTraceEntry
from app.analytics.models import DateRange, MetricQueryResult
from app.diagnosis import DiagnosisComposition
from app.diagnosis.builder import build_diagnosis
from app.diagnosis.models import DiagnosisStatus
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.main import create_app
from app.observations.mapper import observations_from_metric_query
from app.task_application import TaskApplicationConfig, build_task_application


DATABASE_NAME = "metricsleuth_r4_browser_acceptance"
TARGET_DATE = dt.date(2026, 10, 10)
SERVER_LIFETIME_SECONDS = 180
WORKER_WAIT_SECONDS = 120
SALES_FIXTURE = "synthetic-eight-days-v1"
DATA_VERSION = SALES_FIXTURE
LIMITATION = "Controlled Runner acceptance; not a model diagnosis"


class AcceptanceFailure(Exception):
    """A fixed safe failure code suitable for terminal output."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SafeArgumentParser(argparse.ArgumentParser):
    """Do not let argparse echo attacker-controlled argument fragments."""

    def error(self, _message: str) -> None:
        self.exit(2, "invalid_arguments\n")


def validate_database_url(database_url: str) -> tuple[str, int | None]:
    """Validate the isolated loopback database URL without connecting."""
    try:
        parsed = urlsplit(database_url)
        port = parsed.port
        valid = (
            parsed.scheme in {"postgres", "postgresql"}
            and parsed.hostname in {"localhost", "127.0.0.1"}
            and (port is None or 1 <= port <= 65535)
            and parsed.username is not None
            and bool(unquote(parsed.username))
            and parsed.password is None
            and unquote(parsed.path.removeprefix("/")) == DATABASE_NAME
            and not parsed.query
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
        port = None
    if not valid:
        raise AcceptanceFailure("dedicated_loopback_acceptance_database_required")
    return DATABASE_NAME, port


def _one_value(connection: Any, query: str) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    if row is None:
        raise AcceptanceFailure("acceptance_database_check_failed")
    return row[0]


def _assert_database_identity(connection: Any) -> None:
    if _one_value(connection, "SELECT current_database()") != DATABASE_NAME:
        raise AcceptanceFailure("acceptance_database_identity_mismatch")


def _assert_fresh_database(connection: Any) -> None:
    _assert_database_identity(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('app_state', 'warehouse')"
        )
        rows = cursor.fetchall()
    if rows:
        raise AcceptanceFailure("acceptance_database_not_fresh")


def _prepare_fixture(connection: Any) -> None:
    _assert_fresh_database(connection)
    root = Path(__file__).resolve().parents[2]
    try:
        migration_paths = sorted((root / "backend" / "migrations").glob("*.sql"))
        if not migration_paths:
            raise AcceptanceFailure("acceptance_migrations_missing")
        with connection.cursor() as cursor:
            for migration_path in migration_paths:
                cursor.execute(migration_path.read_text(encoding="utf-8"))
            cursor.execute((root / "warehouse" / "schema.sql").read_text(encoding="utf-8"))
        connection.commit()
    except AcceptanceFailure:
        connection.rollback()
        raise
    except Exception:
        connection.rollback()
        raise AcceptanceFailure("acceptance_fixture_prepare_failed") from None


def _seed_fixture(connection: Any) -> None:
    product_id = f"r4-controlled-{uuid4()}"
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO warehouse.dim_products (asin, product_name, category) "
                "VALUES (%s, %s, %s)",
                (product_id, "Controlled browser acceptance fixture", "sandbox"),
            )
            for offset in range(7, -1, -1):
                current_day = TARGET_DATE - dt.timedelta(days=offset)
                cursor.execute(
                    "INSERT INTO warehouse.fact_daily_performance "
                    "(date, asin, marketplace, traffic_source, impressions, clicks, "
                    "sessions, orders, sales, ad_spend, refunds) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (current_day, product_id, "US", "controlled", 100, 10, 100, 10,
                     Decimal("100.00"), Decimal("0.00"), Decimal("0.00")),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise AcceptanceFailure("acceptance_fixture_seed_failed") from None


def _verify_fixture_and_empty_history(connection: Any, source_id: str) -> None:
    _assert_database_identity(connection)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*), min(date), max(date), sum(sales), sum(orders), sum(sessions) "
                "FROM warehouse.fact_daily_performance"
            )
            fact_row = cursor.fetchone()
            cursor.execute(
                "SELECT date, count(*), sum(sales), sum(orders), sum(sessions) "
                "FROM warehouse.fact_daily_performance GROUP BY date ORDER BY date"
            )
            daily_rows = cursor.fetchall()
            cursor.execute("SELECT count(*) FROM warehouse.dim_products")
            product_count = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM app_state.data_sources")
            source_count = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM app_state.investigation_runs")
            run_count = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM app_state.sync_runs")
            sync_count = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM app_state.data_sources WHERE source_id = %s",
                (source_id,),
            )
            source_id_count = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM warehouse.fact_daily_performance "
                "WHERE NOT (date >= %s AND date <= %s)",
                (TARGET_DATE - dt.timedelta(days=7), TARGET_DATE),
            )
            outside_window_count = cursor.fetchone()[0]
    except Exception:
        raise AcceptanceFailure("acceptance_fixture_verification_failed") from None
    if (
        fact_row != (8, TARGET_DATE - dt.timedelta(days=7), TARGET_DATE,
                     Decimal("800.00"), 80, 800)
        or daily_rows != [
            (TARGET_DATE - dt.timedelta(days=offset), 1, Decimal("100.00"), 10, 100)
            for offset in range(7, -1, -1)
        ]
        or product_count != 1
        or source_count != 0
        or run_count != 0
        or sync_count != 0
        or source_id_count != 0
        or outside_window_count != 0
    ):
        raise AcceptanceFailure("acceptance_fixture_not_exact")


def _connect(database_url: str) -> Any:
    try:
        import psycopg

        return psycopg.connect(database_url, autocommit=False, connect_timeout=5)
    except Exception:
        raise AcceptanceFailure("acceptance_database_unavailable") from None


def _validate_prompt(prompt: str, analytics_tools: Any) -> None:
    try:
        payload = json.loads(prompt)
        valid = (
            payload == {
                "metric": "sales",
                "target_date": TARGET_DATE.isoformat(),
                "compare_to": "previous_7_days",
                "filters": {},
                "group_by": [],
                "investigation_request": payload.get("investigation_request"),
            }
            and isinstance(payload.get("investigation_request"), str)
            and getattr(analytics_tools, "_target_date", None) == TARGET_DATE
            and getattr(analytics_tools, "_fixed_filters", None) == {}
        )
    except Exception:
        valid = False
    if not valid:
        raise RuntimeError("acceptance_request_out_of_scope")


def controlled_diagnosis_runner(
    prompt: str,
    *,
    diagnosis_id: str,
    analytics_tools: Any,
    max_tool_calls: int,
    max_turns: int,
    progress_callback: Any,
    **_ignored: Any,
) -> EvidenceDrivenRunSummary:
    """Use one actual semantic SQL query and controlled final intent; no model."""
    _validate_prompt(prompt, analytics_tools)
    result = analytics_tools.query_metric(
        metric="sales",
        start_date=TARGET_DATE,
        end_date=TARGET_DATE,
        compare_to="previous_7_days",
        filters={},
        group_by=[],
    )
    if not isinstance(result, MetricQueryResult) or len(result.rows) != 1:
        raise RuntimeError("acceptance_metric_result_invalid")

    call_id = f"controlled-sales-{uuid4()}"
    created_at = dt.datetime.now(dt.timezone.utc)
    observations = observations_from_metric_query(
        result,
        tool_name="query_metric",
        tool_call_id=call_id,
        filters={},
        query_or_result_reference=f"analytics-result:{call_id}",
        created_at=created_at,
    )
    if len(observations) != 1:
        raise RuntimeError("acceptance_observation_invalid")
    observation = observations[0]
    if (
        observation.status.value != "normal"
        or observation.current_value is None
        or observation.baseline_value is None
        or observation.relative_change is None
        or observation.current_value != Decimal("100.00")
        or observation.baseline_value != Decimal("100.00")
        or observation.relative_change != Decimal("0")
    ):
        raise RuntimeError("acceptance_fixture_values_mismatch")

    trace = InvestigationToolTraceEntry(
        tool_call_id=call_id,
        tool_name="query_metric",
        arguments={
            "metric": "sales",
            "start_date": TARGET_DATE.isoformat(),
            "end_date": TARGET_DATE.isoformat(),
            "compare_to": "previous_7_days",
            "filters": {},
            "group_by": [],
        },
        observation_ids=(observation.observation_id,),
    )
    progress_callback(trace, observations)
    evidence = promote_observation_to_evidence(observation, role=EvidenceRole.SUPPORTING)
    diagnosis = build_diagnosis(
        diagnosis_id=diagnosis_id,
        status=DiagnosisStatus.NO_MATERIAL_ANOMALY,
        target_metric="sales",
        evidence=(evidence,),
        target_evidence_id=evidence.evidence_id,
        confidence=Decimal("1"),
        limitations=(LIMITATION,),
        created_at=created_at,
    )
    summary = InvestigationRunSummary(
        final_output="Controlled SQL-backed browser acceptance result.",
        tool_calls_count=1,
        max_tool_calls=max_tool_calls,
        tools_used=("query_metric",),
        tool_call_ids=(call_id,),
        observation_ids=(observation.observation_id,),
        observation_count=1,
        tool_trace=(trace,),
        trace_sequence=(call_id,),
        turns_count=1,
        max_turns=max_turns,
    )
    return EvidenceDrivenRunSummary(
        investigation=summary,
        composition=DiagnosisComposition(evidence=(evidence,), diagnosis=diagnosis),
        observation_catalog=observations,
    )


def build_acceptance_app(database_url: str, source_id: str) -> tuple[FastAPI, Any]:
    config = TaskApplicationConfig(
        state_database_url=database_url,
        analytics_database_url=database_url,
        profile="synthetic",
        source_id=source_id,
        data_version=DATA_VERSION,
        model="controlled-no-model",
        max_tool_calls=8,
        max_turns=10,
    )
    service, worker = build_task_application(config, diagnosis_runner=controlled_diagnosis_runner)
    application = create_app(investigation_tasks_service=service, include_legacy_routes=False)
    manifest = {
        "acceptance_kind": "controlled_browser_task",
        "database": DATABASE_NAME,
        "source_id": source_id,
        "target_date": TARGET_DATE.isoformat(),
        "controlled_runner": True,
        "real_model": False,
        "fixture": SALES_FIXTURE,
    }
    application.add_api_route(
        "/__acceptance__/manifest", lambda: manifest, methods=["GET"],
        include_in_schema=False,
    )
    return application, worker


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = SafeArgumentParser(description="One controlled PostgreSQL task browser acceptance")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--port", type=int, default=8013)
    parser.add_argument("--prepare-synthetic-fixture", action="store_true")
    args = parser.parse_args(argv)
    validate_database_url(args.database_url)
    try:
        if str(UUID(args.source_id)) != args.source_id.lower():
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        parser.error("invalid_source_id")
    if not 1 <= args.port <= 65535:
        parser.error("invalid_port")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        connection = _connect(args.database_url)
        try:
            if args.prepare_synthetic_fixture:
                _prepare_fixture(connection)
                _seed_fixture(connection)
            _verify_fixture_and_empty_history(connection, args.source_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        application, worker = build_acceptance_app(args.database_url, args.source_id)
        import uvicorn

        logging.getLogger("uvicorn.error").disabled = True
        logging.getLogger("uvicorn.access").disabled = True
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host="127.0.0.1",
                port=args.port,
                access_log=False,
                log_config=None,
                log_level="critical",
                timeout_graceful_shutdown=5,
            )
        )
        server_thread = threading.Thread(target=server.run, name="acceptance-api", daemon=True)
        server_thread.start()
        startup_deadline = time.monotonic() + 15
        while not server.started and server_thread.is_alive() and time.monotonic() < startup_deadline:
            time.sleep(0.05)
        if not server.started:
            server.should_exit = True
            server_thread.join(timeout=7)
            raise AcceptanceFailure("acceptance_server_start_failed")

        worker_done = threading.Event()
        worker_failed = threading.Event()
        worker_stop = threading.Event()

        def run_one_task() -> None:
            deadline = time.monotonic() + WORKER_WAIT_SECONDS
            while not worker_stop.is_set() and time.monotonic() < deadline:
                try:
                    if worker.run_once() is not None:
                        worker_done.set()
                        return
                except Exception:
                    worker_failed.set()
                    return
                time.sleep(0.25)
            worker_failed.set()

        print(f"acceptance_server_ready http://127.0.0.1:{args.port}")
        worker_thread = threading.Thread(target=run_one_task, name="acceptance-worker", daemon=True)
        worker_thread.start()
        server_deadline = time.monotonic() + SERVER_LIFETIME_SECONDS
        try:
            while time.monotonic() < server_deadline and server_thread.is_alive():
                if worker_failed.is_set():
                    print("acceptance_worker_failed", file=sys.stderr)
                    return 1
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            worker_stop.set()
            server.should_exit = True
            server_thread.join(timeout=7)
            worker_thread.join(timeout=7)
        if worker_done.is_set():
            print("acceptance_task_executed")
            return 0
        if worker_failed.is_set():
            print("acceptance_worker_failed", file=sys.stderr)
            return 1
        print("acceptance_server_lifetime_expired", file=sys.stderr)
        return 1
    except AcceptanceFailure as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except Exception:
        print("acceptance_setup_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
