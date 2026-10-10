"""Hermetic tests for idempotent investigation checkpoint facts."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import re
import unittest

from app.analytics.models import DateRange
from app.data_sources.capabilities import SourceEnvironment
from app.observations.models import Observation, ObservationStatus
from app.persistence import (
    ApplicationStateRepository,
    PersistenceRepositoryError,
    PersistenceValidationError,
    RunStatus,
)


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.rowcount = connection.rowcount
        self.row = connection.next_row

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.connection.calls.append((sql, params))

    def fetchone(self) -> object | None:
        return self.row

    def fetchall(self) -> list[object]:
        result = self.connection.fetchall_results[self.connection.fetchall_count]
        self.connection.fetchall_count += 1
        return result

    def close(self) -> None:
        pass


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 1
        self.next_row: object | None = None
        self.fetchall_results: list[list[object]] = [[], []]
        self.fetchall_count = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)


def _observation(**overrides: object) -> Observation:
    fields: dict[str, object] = {
        "observation_id": "observation-checkpoint-1",
        "tool_name": "query_metric",
        "tool_call_id": "tool-call-checkpoint-1",
        "metric": "sales",
        "current_period": DateRange(date(2026, 10, 1), date(2026, 10, 7)),
        "baseline_period": DateRange(date(2026, 9, 24), date(2026, 9, 30)),
        "filters": {"marketplace": "US"},
        "group_by": ("marketplace",),
        "dimensions": {"marketplace": "US"},
        "current_value": Decimal("80"),
        "baseline_value": Decimal("100"),
        "relative_change": Decimal("-0.2"),
        "unit": "usd",
        "sample_size": Decimal("100"),
        "source_status": "ok",
        "status": ObservationStatus.ANOMALOUS,
        "query_or_result_reference": "query:checkpoint-1",
        "created_at": datetime(2026, 10, 9, tzinfo=timezone.utc),
    }
    fields.update(overrides)
    return Observation(**fields)  # type: ignore[arg-type]


class IdempotentCheckpointRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = _Connection()
        self.repository = ApplicationStateRepository(self.connection)

    def _record_tool_call(self, *, idempotent: bool = False) -> None:
        self.repository.record_tool_call(
            "tool-call-checkpoint-1",
            "run-checkpoint-1",
            "source-checkpoint-1",
            SourceEnvironment.VALIDATION,
            "query_metric",
            status=RunStatus.SUCCEEDED,
            arguments={"metric": "sales"},
            dimensions={"marketplace": "US"},
            filters={"marketplace": "US"},
            data_version="version-checkpoint-1",
            query_reference="query:checkpoint-1",
            result_reference="result:checkpoint-1",
            idempotent=idempotent,
        )

    def _record_observation(
        self, observation: Observation | None = None, *, idempotent: bool = False
    ) -> None:
        self.repository.record_observation(
            observation or _observation(),
            "run-checkpoint-1",
            "source-checkpoint-1",
            SourceEnvironment.VALIDATION,
            data_version="version-checkpoint-1",
            idempotent=idempotent,
        )

    def test_default_mode_keeps_plain_insert_sql(self) -> None:
        self._record_tool_call()
        self._record_observation()

        self.assertEqual(len(self.connection.calls), 2)
        for sql, _ in self.connection.calls:
            self.assertIn("INSERT INTO app_state.", sql)
            self.assertNotIn("ON CONFLICT", sql)

    def test_tool_call_idempotency_compares_all_explicit_non_key_columns(self) -> None:
        self._record_tool_call(idempotent=True)
        sql, _ = self.connection.calls[-1]

        self.assertIn(
            "ON CONFLICT (tool_call_id) DO UPDATE SET\n"
            "                tool_call_id = EXCLUDED.tool_call_id",
            sql,
        )
        compared = set(
            re.findall(
                r"app_state\.tool_calls\.([a-z_]+) IS NOT DISTINCT FROM EXCLUDED",
                sql,
            )
        )
        self.assertEqual(
            compared,
            {
                "investigation_run_id",
                "source_id",
                "environment",
                "tool_name",
                "status",
                "arguments",
                "dimensions",
                "filters",
                "data_version",
                "query_reference",
                "result_reference",
            },
        )
        self.assertNotIn("tool_call_id IS NOT DISTINCT FROM", sql)

    def test_observation_idempotency_compares_all_columns_including_timestamp(self) -> None:
        self._record_observation(idempotent=True)
        sql, _ = self.connection.calls[-1]

        compared = set(
            re.findall(
                r"app_state\.observations\.([a-z_]+) IS NOT DISTINCT FROM EXCLUDED",
                sql,
            )
        )
        self.assertEqual(
            compared,
            {
                "investigation_run_id",
                "tool_call_id",
                "source_id",
                "environment",
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
                "data_version",
                "query_reference",
                "error_code",
                "error_message",
                "created_at",
            },
        )
        self.assertIn("created_at IS NOT DISTINCT FROM EXCLUDED.created_at", sql)

    def test_zero_rowcount_rejects_fact_reuse_without_revealing_details(self) -> None:
        self.connection.rowcount = 0

        for operation in (self._record_tool_call, self._record_observation):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(
                    PersistenceRepositoryError,
                    "Idempotent fact conflicts with an existing record",
                ):
                    operation(idempotent=True)

    def test_observation_error_fields_remain_sanitized_in_idempotent_mode(self) -> None:
        failed = _observation(
            status=ObservationStatus.FAILED,
            source_status="failed",
            current_value=None,
            baseline_value=None,
            relative_change=None,
            sample_size=None,
            error_code="DatabaseError password=private-value",
            error_message="postgres://user:private-value@example.invalid/db",
        )

        self._record_observation(failed, idempotent=True)

        sql, params = self.connection.calls[-1]
        self.assertIn("error_code IS NOT DISTINCT FROM EXCLUDED.error_code", sql)
        self.assertIn("error_message IS NOT DISTINCT FROM EXCLUDED.error_message", sql)
        self.assertEqual(params[-3], "tool_error")
        self.assertIsNone(params[-2])
        self.assertNotIn("private-value", repr(params))

    def test_idempotent_flag_requires_an_actual_bool_before_sql(self) -> None:
        for invalid in (1, "true", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(PersistenceValidationError):
                    self.repository.record_tool_call(
                        "tool-call-checkpoint-1",
                        "run-checkpoint-1",
                        "source-checkpoint-1",
                        SourceEnvironment.VALIDATION,
                        "query_metric",
                        idempotent=invalid,  # type: ignore[arg-type]
                    )
                with self.assertRaises(PersistenceValidationError):
                    self.repository.record_observation(
                        _observation(),
                        "run-checkpoint-1",
                        "source-checkpoint-1",
                        SourceEnvironment.VALIDATION,
                        idempotent=invalid,  # type: ignore[arg-type]
                    )

        self.assertEqual(self.connection.calls, [])

    def test_lock_running_run_uses_row_lock_and_checks_scope_and_version(self) -> None:
        self.connection.next_row = (
            "running",
            "source-checkpoint-1",
            "validation",
            "version-checkpoint-1",
        )

        result = self.repository.lock_running_run(
            "run-checkpoint-1",
            "source-checkpoint-1",
            SourceEnvironment.VALIDATION,
            "version-checkpoint-1",
        )

        self.assertIsNone(result)
        sql, params = self.connection.calls[-1]
        self.assertIn("FOR UPDATE", sql)
        self.assertEqual(params, ("run-checkpoint-1",))

        for row in (
            None,
            (
                "succeeded",
                "source-checkpoint-1",
                "validation",
                "version-checkpoint-1",
            ),
            ("running", "other-source", "validation", "version-checkpoint-1"),
            ("running", "source-checkpoint-1", "sandbox", "version-checkpoint-1"),
            ("running", "source-checkpoint-1", "validation", "other-version"),
        ):
            with self.subTest(row=row):
                self.connection.next_row = row
                with self.assertRaisesRegex(
                    PersistenceRepositoryError,
                    "unavailable for checkpoint persistence",
                ):
                    self.repository.lock_running_run(
                        "run-checkpoint-1",
                        "source-checkpoint-1",
                        SourceEnvironment.VALIDATION,
                        "version-checkpoint-1",
                    )

    def test_get_run_fact_ids_returns_two_sorted_read_only_lists(self) -> None:
        self.connection.fetchall_results = [[("tool-z",), ("tool-a",)], []]
        result = self.repository.get_run_fact_ids("run-checkpoint-1")
        self.assertEqual(result, (("tool-a", "tool-z"), ()))
        tool_sql, tool_params = self.connection.calls[-2]
        observation_sql, observation_params = self.connection.calls[-1]
        self.assertIn("tool_calls", tool_sql)
        self.assertIn("ORDER BY tool_call_id", tool_sql)
        self.assertIn("observations", observation_sql)
        self.assertIn("ORDER BY observation_id", observation_sql)
        self.assertEqual(tool_params, ("run-checkpoint-1",))
        self.assertEqual(observation_params, ("run-checkpoint-1",))


if __name__ == "__main__":
    unittest.main()
