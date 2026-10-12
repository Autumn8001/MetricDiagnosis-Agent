"""Publish the in-memory synthetic benchmark into an explicitly named local sandbox."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from app.data_sources import DataSourceDescriptor, SourceEnvironment, SourceProvider

_ALLOWED_SCENARIOS = frozenset({"no_anomaly", "canonical", "traffic"})
_TARGET_DATE = dt.date(2026, 1, 31)
_LOCK_KEY = (1296388933, 1396787796)


class SandboxDatasetWriterError(RuntimeError):
    """Safe, stable error that never includes connection or driver details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SandboxTarget:
    database_url: str = field(repr=False)
    descriptor: DataSourceDescriptor

    def __post_init__(self) -> None:
        if not isinstance(self.database_url, str):
            raise SandboxDatasetWriterError("sandbox_target_invalid")
        try:
            parsed = urlsplit(self.database_url)
            port = parsed.port
            database = parsed.path[1:]
            safe_url = (
                parsed.scheme == "postgresql"
                and parsed.hostname in {"127.0.0.1", "localhost"}
                and port is not None
                and 1 <= port <= 65535
                and bool(database)
                and len(database) <= 63
                and re.fullmatch(r"metricsleuth_sandbox_[a-z0-9_]+", database) is not None
                and not parsed.query
                and not parsed.fragment
                and "?" not in self.database_url
                and "#" not in self.database_url
                and "/" not in database
            )
        except (ValueError, TypeError):
            safe_url = False
        if not safe_url:
            raise SandboxDatasetWriterError("sandbox_target_invalid")

        descriptor = self.descriptor
        try:
            valid_descriptor = (
                isinstance(descriptor, DataSourceDescriptor)
                and descriptor.provider is SourceProvider.SYNTHETIC
                and descriptor.environment is SourceEnvironment.SANDBOX
                and str(UUID(descriptor.source_id)) == descriptor.source_id
            )
        except (ValueError, TypeError, AttributeError):
            valid_descriptor = False
        if not valid_descriptor:
            raise SandboxDatasetWriterError("sandbox_source_invalid")


@dataclass(frozen=True)
class Publication:
    source_id: str
    data_version: str
    row_count: int
    checksum: str
    target_date: dt.date


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SandboxDatasetWriterError("sandbox_publish_failed")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (Exception, SystemExit):
        raise SandboxDatasetWriterError("sandbox_publish_failed") from None
    return module


def _load_seed():
    repo_root = Path(__file__).resolve().parents[3]
    return _load_module("_sandbox_seed", repo_root / "warehouse" / "seed.py")


def build_sandbox_rows(scenario: str) -> list[tuple]:
    """Build deterministic 31-day rows, replacing only the 18 target-date segments."""
    if not isinstance(scenario, str) or scenario not in _ALLOWED_SCENARIOS:
        raise SandboxDatasetWriterError("sandbox_scenario_invalid")
    repo_root = Path(__file__).resolve().parents[3]
    seed = _load_seed()
    injector = _load_module(
        "_sandbox_anomaly_injector", repo_root / "warehouse" / "anomaly_injector.py"
    )
    current = injector.apply_scenario(
        injector.generate_current_normal_records(), scenario
    )
    replacements = {
        (row["date"], row["asin"], row["marketplace"], row["traffic_source"]): tuple(
            row[key]
            for key in (
                "date", "asin", "marketplace", "traffic_source", "impressions",
                "clicks", "sessions", "orders", "sales", "ad_spend", "refunds",
            )
        )
        for row in current
    }
    rows = []
    for row in seed.generate_normal_records():
        key = (row[0], row[1], row[2], row[3])
        rows.append(replacements.get(key, row))
    if len(rows) != 558 or len(replacements) != 18:
        raise SandboxDatasetWriterError("sandbox_publish_failed")
    return rows


def _checksum(rows: list[tuple]) -> str:
    serializable = [
        [value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value for value in row]
        for row in rows
    ]
    payload = json.dumps(serializable, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _default_connection_factory(database_url: str):
    import psycopg

    return psycopg.connect(database_url, connect_timeout=5, autocommit=False)


_RELATION_GUARD_SQL = """SELECT c.relname FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
AND n.nspname <> 'information_schema' AND left(n.nspname, 3) <> 'pg_' LIMIT 1"""

def publish_sandbox_dataset(
    target: SandboxTarget,
    scenario: str,
    connection_factory=None,
) -> Publication:
    """Create and populate a fresh local sandbox in one guarded transaction."""
    if not isinstance(target, SandboxTarget):
        raise SandboxDatasetWriterError("sandbox_target_invalid")
    if not isinstance(scenario, str) or scenario not in _ALLOWED_SCENARIOS:
        raise SandboxDatasetWriterError("sandbox_scenario_invalid")
    conn = None
    try:
        rows = build_sandbox_rows(scenario)
        products = list(_load_seed().PRODUCTS)
        checksum = _checksum(rows)
        data_version = f"sandbox-{checksum}"
        schema_sql = (
            Path(__file__).resolve().parents[3] / "warehouse" / "schema.sql"
        ).read_text(encoding="utf-8")
        conn = (
            _default_connection_factory(target.database_url)
            if connection_factory is None
            else connection_factory()
        )
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '10000ms'")
                cur.execute("SET LOCAL lock_timeout = '3000ms'")
                cur.execute(
                    "SELECT current_database(), host(inet_server_addr()), inet_server_port()"
                )
                database, address, port = cur.fetchone()
                parsed = urlsplit(target.database_url)
                try:
                    loopback = address is not None and ipaddress.ip_address(address).is_loopback
                except ValueError:
                    loopback = False
                if database != parsed.path[1:] or not loopback or port != parsed.port:
                    raise SandboxDatasetWriterError("sandbox_target_mismatch")
                cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", _LOCK_KEY)
                cur.execute(_RELATION_GUARD_SQL)
                if cur.fetchone() is not None:
                    raise SandboxDatasetWriterError("sandbox_target_not_empty")
                cur.execute(schema_sql)
                cur.execute(
                    """
                    CREATE TABLE warehouse.sandbox_dataset_manifest (
                        source_id UUID PRIMARY KEY, data_version TEXT NOT NULL,
                        row_count INTEGER NOT NULL, checksum TEXT NOT NULL,
                        target_date DATE NOT NULL, scenario_id TEXT NOT NULL
                    )
                    """
                )
                cur.executemany(
                    "INSERT INTO warehouse.dim_products (asin, product_name, category) VALUES (%s, %s, %s)",
                    products,
                )
                cur.executemany(
                    """INSERT INTO warehouse.fact_daily_performance (
                        date, asin, marketplace, traffic_source, impressions, clicks,
                        sessions, orders, sales, ad_spend, refunds
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    rows,
                )
                cur.execute(
                    """INSERT INTO warehouse.sandbox_dataset_manifest
                    (source_id, data_version, row_count, checksum, target_date, scenario_id)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        target.descriptor.source_id,
                        data_version,
                        len(rows),
                        checksum,
                        _TARGET_DATE,
                        scenario,
                    ),
                )
        return Publication(
            target.descriptor.source_id, data_version, len(rows), checksum, _TARGET_DATE
        )
    except SandboxDatasetWriterError:
        raise
    except Exception:
        raise SandboxDatasetWriterError("sandbox_publish_failed") from None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
