from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.persistence.task_read_repository import InvestigationTaskReadRepository


def run_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "investigation_run_id": "run-1",
        "source_id": "shop-1",
        "environment": "sandbox",
        "status": "succeeded",
        "requested_metric": "net_sales",
        "requested_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
        "started_at": None,
        "finished_at": datetime(2026, 10, 10, 0, 1, tzinfo=timezone.utc),
        "data_version": "version-1",
        "query_reference": "query-1",
        "failure_code": None,
        "tool_call_count": 1,
        "observation_count": 1,
        "evidence_count": 1,
        "diagnosis_count": 1,
        # These columns must never be projected to callers.
        "parameters": {"private_prompt": "do not expose"},
        "failure_details": {"message": "private database response"},
    }
    row.update(overrides)
    return row


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.description: list[tuple[str]] = []
        self._result: tuple[str, object] | None = None

    def execute(self, operation: str, params: object = None) -> None:
        self.connection.queries.append((operation, params))
        self._result = self.connection.responses.pop(0)
        if self._result[0] == "tuple":
            self.description = [(name,) for name in self.connection.tuple_fields]

    def fetchone(self) -> object:
        assert self._result is not None
        assert self._result[0] in {"one", "tuple"}
        return self._result[1]

    def fetchall(self) -> list[object]:
        assert self._result is not None
        assert self._result[0] == "all"
        return self._result[1]  # type: ignore[return-value]

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(self, *responses: tuple[str, object]) -> None:
        self.responses = list(responses)
        self.queries: list[tuple[str, object]] = []
        self.tuple_fields: tuple[str, ...] = ()

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


class InvestigationTaskReadRepositoryTests(unittest.TestCase):
    def test_list_is_worker_only_scoped_and_paged_with_counts(self) -> None:
        connection = FakeConnection(("all", [run_row()]))
        repository = InvestigationTaskReadRepository(connection)

        rows = repository.list_runs("shop-1", "sandbox", limit=7, offset=14)

        self.assertEqual(rows[0]["investigation_run_id"], "run-1")
        self.assertEqual(rows[0]["tool_call_count"], 1)
        self.assertNotIn("parameters", rows[0])
        self.assertNotIn("failure_details", rows[0])
        sql, params = connection.queries[0]
        self.assertIn("r.source_id = %s AND r.environment = %s", sql)
        self.assertIn("r.execution_mode = 'worker'", sql)
        self.assertIn("ORDER BY r.requested_at DESC, r.investigation_run_id DESC", sql)
        self.assertEqual(params, ("shop-1", "sandbox", 7, 14))
        for child in ("tool_calls", "observations", "evidence", "diagnoses"):
            self.assertIn(f"FROM app_state.{child}", sql)
            self.assertIn("source_id = r.source_id AND", sql)
        self.assertNotIn("SELECT *", sql)

    def test_invalid_pagination_is_rejected_without_query(self) -> None:
        for kwargs in (
            {"limit": True},
            {"limit": 0},
            {"limit": 101},
            {"offset": True},
            {"offset": -1},
        ):
            connection = FakeConnection()
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    InvestigationTaskReadRepository(connection).list_runs(
                        "shop-1", "sandbox", **kwargs
                    )
                self.assertEqual(connection.queries, [])

    def test_get_run_rejects_invalid_failure_code_and_supports_tuple_rows(self) -> None:
        fields = tuple(run_row().keys())
        values = list(run_row(failure_code="password=hunter2").values())
        # Simulate a DB-API cursor returning a positional row and description.
        connection = FakeConnection(("tuple", tuple(values)))
        connection.tuple_fields = fields

        result = InvestigationTaskReadRepository(connection).get_run(
            "run-1", "shop-1", "sandbox"
        )

        assert result is not None
        self.assertIsNone(result["failure_code"])
        self.assertNotIn("parameters", result)
        self.assertEqual(connection.queries[0][1], ("run-1", "shop-1", "sandbox"))

    def test_details_project_allowlisted_facts_and_scope_every_query(self) -> None:
        started = run_row()
        tool = {
            "tool_call_id": "tool-1",
            "tool_name": "metric_breakdown",
            "status": "succeeded",
            "arguments": {"metric": "net_sales"},
            "data_version": "version-1",
            "query_reference": "tool-query",
            "result_reference": "result-1",
            "requested_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
            "secret": "must not leak",
        }
        observation = {
            "observation_id": "obs-1",
            "tool_call_id": "tool-1",
            "metric": "net_sales",
            "status": "anomalous",
            "source_status": "ok",
            "current_period_start": date(2026, 10, 1),
            "current_period_end": date(2026, 10, 7),
            "baseline_period_start": date(2026, 9, 24),
            "baseline_period_end": date(2026, 9, 30),
            "filters": {"country": "US"},
            "group_by": ["country"],
            "dimensions": {"country": "US"},
            "current_value": Decimal("80.0"),
            "baseline_value": Decimal("100.0"),
            "relative_change": Decimal("-0.2"),
            "unit": "USD",
            "sample_size": Decimal("20"),
            "query_reference": "obs-query",
            "data_version": "version-1",
            "error_code": None,
            "created_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
            "error_message": "sensitive external response",
        }
        evidence = {
            "evidence_id": "ev-1",
            "observation_id": "obs-1",
            "tool_call_id": "tool-1",
            "role": "supporting",
            "data_version": "version-1",
            "query_reference": "ev-query",
            "created_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
            "payload": {"large": "arbitrary private payload"},
        }
        diagnosis = {
            "diagnosis_id": "diag-1",
            "status": "diagnosed",
            "target_metric": "net_sales",
            "primary_driver": "country",
            "affected_scope": {"country": "US"},
            "change": {"current_value": 80, "baseline_value": 100},
            "evidence_ids": ["ev-1"],
            "confidence": Decimal("0.9"),
            "limitations": ["small sample"],
            "data_version": "version-1",
            "query_reference": "diag-query",
            "created_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
            "failure_message": "private failure text",
        }
        connection = FakeConnection(
            ("one", started),
            ("all", [tool]),
            ("all", [observation]),
            ("all", [evidence]),
            ("all", [diagnosis]),
        )

        result = InvestigationTaskReadRepository(connection).get_details(
            "run-1", "shop-1", "sandbox"
        )

        assert result is not None
        self.assertEqual(result["tool_calls"][0]["requested_at"], tool["requested_at"])
        self.assertEqual(result["observations"][0]["current_value"], Decimal("80.0"))
        self.assertEqual(result["evidence"][0]["tool_call_id"], "tool-1")
        self.assertNotIn("payload", result["evidence"][0])
        self.assertNotIn("error_message", result["observations"][0])
        self.assertNotIn("failure_message", result["diagnoses"][0])
        self.assertNotIn("secret", result["tool_calls"][0])
        for sql, params in connection.queries:
            self.assertIn("source_id = %s AND r.environment = %s", sql)
            self.assertIn("execution_mode = 'worker'", sql)
            self.assertIn(("run-1", "shop-1", "sandbox"), [params[:3]])
            self.assertNotIn("SELECT *", sql)
            self.assertNotIn("f.payload", sql)
            self.assertNotIn("f.error_message", sql)
        evidence_sql = connection.queries[3][0]
        self.assertIn("JOIN app_state.observations AS o", evidence_sql)

    def test_get_details_missing_scoped_run_does_not_read_facts(self) -> None:
        connection = FakeConnection(("one", None))
        result = InvestigationTaskReadRepository(connection).get_details(
            "run-1", "other-shop", "live"
        )
        self.assertIsNone(result)
        self.assertEqual(len(connection.queries), 1)
        self.assertEqual(connection.queries[0][1], ("run-1", "other-shop", "live"))

    def test_details_raise_when_fact_limit_would_truncate(self) -> None:
        tools = [
            {
                "tool_call_id": f"tool-{index}",
                "tool_name": "metric_breakdown",
                "status": "succeeded",
                "arguments": {},
                "data_version": None,
                "query_reference": None,
                "result_reference": None,
                "requested_at": None,
            }
            for index in range(1001)
        ]
        connection = FakeConnection(("one", run_row()), ("all", tools))
        with self.assertRaises(ValueError):
            InvestigationTaskReadRepository(connection).get_details(
                "run-1", "shop-1", "sandbox"
            )
        self.assertEqual(connection.queries[1][1][-1], 1001)


if __name__ == "__main__":
    unittest.main()
