"""Read-only, source-scoped views of persisted worker investigations."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_FAILURE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_PAGE_SIZE = 100
_MAX_DETAIL_FACTS = 1000

_RUN_FIELDS = (
    "investigation_run_id",
    "source_id",
    "environment",
    "status",
    "requested_metric",
    "requested_at",
    "started_at",
    "finished_at",
    "data_version",
    "query_reference",
    "failure_code",
    "tool_call_count",
    "observation_count",
    "evidence_count",
    "diagnosis_count",
)

_TOOL_CALL_FIELDS = (
    "tool_call_id",
    "tool_name",
    "status",
    "arguments",
    "data_version",
    "query_reference",
    "result_reference",
    "requested_at",
)

_OBSERVATION_FIELDS = (
    "observation_id",
    "tool_call_id",
    "metric",
    "status",
    "source_status",
    "current_period_start",
    "current_period_end",
    "baseline_period_start",
    "baseline_period_end",
    "filters",
    "group_by",
    "dimensions",
    "current_value",
    "baseline_value",
    "relative_change",
    "unit",
    "sample_size",
    "query_reference",
    "data_version",
    "error_code",
    "created_at",
)

_EVIDENCE_FIELDS = (
    "evidence_id",
    "observation_id",
    "tool_call_id",
    "role",
    "data_version",
    "query_reference",
    "created_at",
)

_DIAGNOSIS_FIELDS = (
    "diagnosis_id",
    "status",
    "target_metric",
    "primary_driver",
    "affected_scope",
    "change",
    "evidence_ids",
    "confidence",
    "limitations",
    "data_version",
    "query_reference",
    "created_at",
)


class InvestigationTaskReadRepository:
    """Expose persisted worker runs with explicit, scoped field projections.

    The caller owns connection lifetime and transaction/isolation boundaries.
    This class does not open connections, commit, or read configuration.
    """

    def __init__(self, connection: Any) -> None:
        if not callable(getattr(connection, "cursor", None)):
            raise TypeError("connection must provide cursor().")
        self._connection = connection

    def list_runs(
        self,
        source_id: str,
        environment: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        source, env = _scope(source_id, environment)
        if type(limit) is not int or not 1 <= limit <= _MAX_PAGE_SIZE:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

        sql = """
            SELECT r.investigation_run_id, r.source_id, r.environment, r.status,
                   r.requested_metric, r.requested_at, r.started_at, r.finished_at,
                   r.data_version, r.query_reference,
                   CASE
                       WHEN r.failure_details->>'code' ~ '^[a-z0-9][a-z0-9_-]{0,63}$'
                       THEN r.failure_details->>'code'
                       ELSE NULL
                   END AS failure_code,
                   (SELECT count(*) FROM app_state.tool_calls AS t
                    WHERE t.investigation_run_id = r.investigation_run_id
                      AND t.source_id = r.source_id AND t.environment = r.environment)
                       AS tool_call_count,
                   (SELECT count(*) FROM app_state.observations AS o
                    WHERE o.investigation_run_id = r.investigation_run_id
                      AND o.source_id = r.source_id AND o.environment = r.environment)
                       AS observation_count,
                   (SELECT count(*) FROM app_state.evidence AS e
                    WHERE e.investigation_run_id = r.investigation_run_id
                      AND e.source_id = r.source_id AND e.environment = r.environment)
                       AS evidence_count,
                   (SELECT count(*) FROM app_state.diagnoses AS d
                    WHERE d.investigation_run_id = r.investigation_run_id
                      AND d.source_id = r.source_id AND d.environment = r.environment)
                       AS diagnosis_count
            FROM app_state.investigation_runs AS r
            WHERE r.source_id = %s AND r.environment = %s
              AND r.execution_mode = 'worker'
            ORDER BY r.requested_at DESC, r.investigation_run_id DESC
            LIMIT %s OFFSET %s
        """
        rows = self._fetch_all(sql, (source, env, limit, offset))
        return [_project(row, _RUN_FIELDS) for row in rows]

    def get_run(
        self, run_id: str, source_id: str, environment: str
    ) -> dict[str, object] | None:
        run, source, env = _ident(run_id, "run_id"), *_scope(source_id, environment)
        sql = _run_select() + """
            WHERE r.investigation_run_id = %s
              AND r.source_id = %s AND r.environment = %s
              AND r.execution_mode = 'worker'
        """
        row = self._fetch_one(sql, (run, source, env))
        return None if row is None else _project(row, _RUN_FIELDS)

    def get_details(
        self, run_id: str, source_id: str, environment: str
    ) -> dict[str, object] | None:
        run, source, env = _ident(run_id, "run_id"), *_scope(source_id, environment)
        run_row = self._fetch_one(
            _run_select()
            + """
                WHERE r.investigation_run_id = %s
                  AND r.source_id = %s AND r.environment = %s
                  AND r.execution_mode = 'worker'
            """,
            (run, source, env),
        )
        if run_row is None:
            return None

        scoped_join = """
            FROM app_state.{table} AS f
            JOIN app_state.investigation_runs AS r
              ON r.investigation_run_id = f.investigation_run_id
             AND r.source_id = f.source_id AND r.environment = f.environment
            {related_join}
            WHERE f.investigation_run_id = %s
              AND f.source_id = %s AND f.environment = %s
              AND r.investigation_run_id = %s
              AND r.source_id = %s AND r.environment = %s
              AND r.execution_mode = 'worker'
        """
        queries = (
            (
                "tool_calls",
                "SELECT f.tool_call_id, f.tool_name, f.status, f.arguments, "
                "f.data_version, f.query_reference, f.result_reference, "
                "f.requested_at",
                _TOOL_CALL_FIELDS,
                "f.requested_at, f.tool_call_id",
                "",
            ),
            (
                "observations",
                "SELECT f.observation_id, f.tool_call_id, f.metric, f.status, "
                "f.source_status, f.current_period_start, f.current_period_end, "
                "f.baseline_period_start, f.baseline_period_end, f.filters, "
                "f.group_by, f.dimensions, f.current_value, f.baseline_value, "
                "f.relative_change, f.unit, f.sample_size, f.query_reference, "
                "f.data_version, f.error_code, f.created_at",
                _OBSERVATION_FIELDS,
                "f.created_at, f.observation_id",
                "",
            ),
            (
                "evidence",
                "SELECT f.evidence_id, f.observation_id, o.tool_call_id, f.role, "
                "f.data_version, f.query_reference, f.created_at",
                _EVIDENCE_FIELDS,
                "f.created_at, f.evidence_id",
                """JOIN app_state.observations AS o
                  ON o.observation_id = f.observation_id
                 AND o.investigation_run_id = f.investigation_run_id
                 AND o.source_id = f.source_id AND o.environment = f.environment""",
            ),
            (
                "diagnoses",
                "SELECT f.diagnosis_id, f.status, f.target_metric, f.primary_driver, "
                "f.affected_scope, f.change, f.evidence_ids, f.confidence, "
                "f.limitations, f.data_version, f.query_reference, f.created_at",
                _DIAGNOSIS_FIELDS,
                "f.created_at, f.diagnosis_id",
                "",
            ),
        )
        detail_lists: dict[str, list[dict[str, object]]] = {}
        for table, projection, fields, order_by, related_join in queries:
            sql = (
                projection
                + "\n"
                + scoped_join.format(table=table, related_join=related_join)
                + f" ORDER BY {order_by} LIMIT %s"
            )
            rows = self._fetch_all(sql, (run, source, env, run, source, env, _MAX_DETAIL_FACTS + 1))
            if len(rows) > _MAX_DETAIL_FACTS:
                raise ValueError("Investigation detail exceeds the supported result size.")
            detail_lists[table] = [_project(row, fields) for row in rows]

        return {
            "run": _project(run_row, _RUN_FIELDS),
            "tool_calls": detail_lists["tool_calls"],
            "observations": detail_lists["observations"],
            "evidence": detail_lists["evidence"],
            "diagnoses": detail_lists["diagnoses"],
        }

    def _fetch_one(self, sql: str, params: tuple[object, ...]) -> object | None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if row is None or isinstance(row, Mapping):
                return row
            return _row_mapping(row, cursor.description)
        finally:
            cursor.close()

    def _fetch_all(self, sql: str, params: tuple[object, ...]) -> list[object]:
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            if not rows:
                return []
            if isinstance(rows[0], Mapping):
                return list(rows)
            return [_row_mapping(row, cursor.description) for row in rows]
        finally:
            cursor.close()


def _run_select() -> str:
    return """
        SELECT r.investigation_run_id, r.source_id, r.environment, r.status,
               r.requested_metric, r.requested_at, r.started_at, r.finished_at,
               r.data_version, r.query_reference,
               CASE
                   WHEN r.failure_details->>'code' ~ '^[a-z0-9][a-z0-9_-]{0,63}$'
                   THEN r.failure_details->>'code'
                   ELSE NULL
               END AS failure_code,
               (SELECT count(*) FROM app_state.tool_calls AS t
                WHERE t.investigation_run_id = r.investigation_run_id
                  AND t.source_id = r.source_id AND t.environment = r.environment)
                   AS tool_call_count,
               (SELECT count(*) FROM app_state.observations AS o
                WHERE o.investigation_run_id = r.investigation_run_id
                  AND o.source_id = r.source_id AND o.environment = r.environment)
                   AS observation_count,
               (SELECT count(*) FROM app_state.evidence AS e
                WHERE e.investigation_run_id = r.investigation_run_id
                  AND e.source_id = r.source_id AND e.environment = r.environment)
                   AS evidence_count,
               (SELECT count(*) FROM app_state.diagnoses AS d
                WHERE d.investigation_run_id = r.investigation_run_id
                  AND d.source_id = r.source_id AND d.environment = r.environment)
                   AS diagnosis_count
        FROM app_state.investigation_runs AS r
    """


def _scope(source_id: str, environment: str) -> tuple[str, str]:
    return _ident(source_id, "source_id"), _ident(environment, "environment")


def _ident(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    return value.strip()


def _row_mapping(row: object, description: Sequence[object] | None) -> dict[str, object]:
    if isinstance(row, Mapping):
        return dict(row)
    if not isinstance(row, (tuple, list)) or description is None:
        raise ValueError("Database returned a row without column metadata.")
    names: list[str] = []
    for column in description:
        name = getattr(column, "name", None)
        if name is None:
            try:
                name = column[0]
            except (IndexError, TypeError):
                name = None
        if not isinstance(name, str):
            raise ValueError("Database returned invalid column metadata.")
        names.append(name)
    if len(names) != len(row):
        raise ValueError("Database returned a row with an invalid shape.")
    return dict(zip(names, row, strict=True))


def _project(row: object, fields: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(row, Mapping):
        raise ValueError("Database returned an invalid row mapping.")
    projected: dict[str, object] = {}
    for field in fields:
        if field not in row:
            raise ValueError("Database result is missing a required field.")
        value = row[field]
        if field == "failure_code" and (
            not isinstance(value, str) or _FAILURE_CODE_RE.fullmatch(value) is None
        ):
            value = None
        projected[field] = value
    return projected


__all__ = ["InvestigationTaskReadRepository"]
