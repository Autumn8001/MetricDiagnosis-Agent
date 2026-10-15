"""Hermetic tests for the source-bound SDK Runner adapter.

These tests inject a callable in place of the diagnosis Runtime; they do not
make a model or network request and use only fake DB-API connections.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path
import unittest

from agents import RunConfig

from app.api.task_service import TaskSourceBinding
from app.data_sources import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
    build_capabilities_from_registry,
)
from app.metrics.registry import MetricRegistry
from app.persistence.source_runner import (
    SourceInvestigationRunner,
    SourceRunnerRequestError,
)
from app.persistence.task_execution_service import InvestigationTaskRequest


class FakeCursor:
    def __init__(self, *, fail_query: bool = False) -> None:
        self.executed: list[tuple[object, object]] = []
        self.fail_query = fail_query
        self.closed = False

    def execute(self, query: object, params: object = None) -> None:
        self.executed.append((query, params))
        if self.fail_query and len(self.executed) == 3:
            raise RuntimeError("postgres://user:secret@private-host/database")

    def fetchall(self):
        return [
            (
                "US",
                Decimal("700"),
                None,
                Decimal("100"),
                7,
                Decimal("80"),
                None,
            )
        ]

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


class FakeConnection:
    def __init__(self, *, fail_query: bool = False, autocommit: bool = False) -> None:
        self.autocommit = autocommit
        self.cursor_value = FakeCursor(fail_query=fail_query)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_value

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _ModelWithSecretRepr:
    def __repr__(self) -> str:
        return "model(api_key=do-not-print)"


class TestSourceInvestigationRunner(unittest.TestCase):
    def setUp(self) -> None:
        yaml_path = (
            Path(__file__).resolve().parents[2] / "configs" / "metrics.yaml"
        )
        self.registry = MetricRegistry.from_yaml(yaml_path)
        self.descriptor = DataSourceDescriptor(
            source_id="source-test",
            display_name="Isolated test source",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.VALIDATION,
        )
        self.capabilities = build_capabilities_from_registry(
            self.registry,
            self.descriptor,
        )
        self.binding = TaskSourceBinding(
            descriptor=self.descriptor,
            capabilities=self.capabilities,
            data_version="validation-fixture-v1",
        )
        self.connections: list[FakeConnection] = []

        def connection_factory() -> FakeConnection:
            connection = FakeConnection()
            self.connections.append(connection)
            return connection

        self.connection_factory = connection_factory
        self.calls: list[dict[str, object]] = []

        def diagnosis_runner(prompt: str, **kwargs: object) -> object:
            self.calls.append({"prompt": prompt, **kwargs})
            return object()

        self.diagnosis_runner = diagnosis_runner
        self.runner = SourceInvestigationRunner(
            binding=self.binding,
            registry=self.registry,
            analytics_connection_factory=self.connection_factory,
            model=_ModelWithSecretRepr(),
            max_tool_calls=5,
            max_turns=6,
            diagnosis_runner=self.diagnosis_runner,
        )

    def request(
        self,
        *,
        descriptor: DataSourceDescriptor | None = None,
        data_version: str = "validation-fixture-v1",
        parameters: dict[str, object] | None = None,
    ) -> InvestigationTaskRequest:
        return InvestigationTaskRequest(
            run_id="run-unit-123",
            descriptor=descriptor or self.descriptor,
            requested_metric="sales",
            data_version=data_version,
            query_reference="task:query-unit-123",
            parameters=parameters
            or {
                "target_date": "2026-10-10",
                "filters": {"marketplace": "US"},
                "group_by": ["marketplace"],
            },
        )

    def test_descriptor_and_version_must_match_before_runtime(self) -> None:
        other_descriptor = DataSourceDescriptor(
            source_id="other-source",
            display_name="Other source",
            provider=SourceProvider.POSTGRESQL,
            environment=SourceEnvironment.VALIDATION,
        )
        with self.assertRaises(SourceRunnerRequestError):
            self.runner(self.request(descriptor=other_descriptor))
        with self.assertRaises(SourceRunnerRequestError):
            self.runner(self.request(data_version="different-version"))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.connections, [])

    def test_metric_and_requested_dimensions_must_match_registry_contract(self) -> None:
        unsupported_metric = InvestigationTaskRequest(
            run_id="run-unit-123",
            descriptor=self.descriptor,
            requested_metric="not_in_registry",
            data_version="validation-fixture-v1",
            parameters={
                "target_date": "2026-10-10",
                "filters": {},
                "group_by": [],
            },
        )
        with self.assertRaises(SourceRunnerRequestError):
            self.runner(unsupported_metric)
        unsupported_dimension = self.request(
            parameters={
                "target_date": "2026-10-10",
                "filters": {},
                "group_by": ["not_a_dimension"],
            }
        )
        with self.assertRaises(SourceRunnerRequestError):
            self.runner(unsupported_dimension)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.connections, [])

    def test_invalid_date_or_fixed_filter_conflict_never_opens_connection(self) -> None:
        self.runner(self.request())
        tools = self.calls[-1]["analytics_tools"]
        with self.assertRaises(ValueError):
            tools.query_metric(
                metric="sales",
                start_date=datetime.date(2026, 10, 9),
                end_date=datetime.date(2026, 10, 9),
                compare_to="previous_7_days",
                filters={"marketplace": "US"},
            )
        with self.assertRaises(ValueError):
            tools.query_metric(
                metric="sales",
                start_date=datetime.date(2026, 10, 10),
                end_date=datetime.date(2026, 10, 10),
                compare_to="previous_7_days",
                filters={"marketplace": "CA"},
            )
        with self.assertRaises(ValueError):
            tools.query_metric(
                metric="sales",
                start_date=datetime.date(2026, 10, 10),
                end_date=datetime.date(2026, 10, 10),
                compare_to="previous_7_days",
                filters={},
            )
        self.assertEqual(self.connections, [])

    def test_query_uses_new_read_only_connection_and_closes_before_runtime_returns(self) -> None:
        sentinel = object()

        def runner(prompt: str, **kwargs: object) -> object:
            tools = kwargs["analytics_tools"]
            result = tools.query_metric(
                metric="orders",
                start_date=datetime.date(2026, 10, 10),
                end_date=datetime.date(2026, 10, 10),
                compare_to="previous_7_days",
                filters={"marketplace": "US"},
                group_by=["marketplace"],
            )
            self.assertEqual(result.metric_id, "orders")
            self.assertEqual(len(self.connections), 1)
            connection = self.connections[0]
            self.assertTrue(connection.closed)
            self.assertTrue(connection.cursor_value.closed)
            self.assertEqual(connection.commits, 1)
            self.assertEqual(connection.rollbacks, 0)
            self.assertEqual(
                [str(statement) for statement, _ in connection.cursor_value.executed[:2]],
                [
                    "SET TRANSACTION READ ONLY",
                    "SET LOCAL statement_timeout = '10000ms'",
                ],
            )
            # SQL receives the exact filter value carried in the SDK arguments.
            query_params = connection.cursor_value.executed[2][1]
            self.assertIn("US", query_params)
            return sentinel

        self.runner._diagnosis_runner = runner
        self.assertIs(self.runner(self.request()), sentinel)

    def test_empty_fixed_scope_allows_none_filters(self) -> None:
        empty_scope_binding = TaskSourceBinding(
            descriptor=self.descriptor,
            capabilities=self.capabilities,
            data_version="validation-fixture-v1",
        )
        runner = SourceInvestigationRunner(
            binding=empty_scope_binding,
            registry=self.registry,
            analytics_connection_factory=self.connection_factory,
            model=object(),
            diagnosis_runner=lambda _prompt, **_kwargs: _kwargs[
                "analytics_tools"
            ].query_metric(
                metric="sales",
                start_date=datetime.date(2026, 10, 10),
                end_date=datetime.date(2026, 10, 10),
                compare_to="previous_7_days",
                filters=None,
                group_by=["marketplace"],
            ),
        )
        request = self.request(
            parameters={
                "target_date": "2026-10-10",
                "filters": {},
                "group_by": [],
            }
        )
        result = runner(request)
        self.assertEqual(result.metric_id, "sales")
        self.assertEqual(self.connections[0].commits, 1)
        self.assertTrue(self.connections[0].closed)

    def test_query_failure_rolls_back_closes_and_sanitizes_driver_text(self) -> None:
        connection = FakeConnection(fail_query=True)
        self.runner._analytics_connection_factory = lambda: connection
        self.runner(self.request())
        tools = self.calls[-1]["analytics_tools"]
        with self.assertRaisesRegex(RuntimeError, "^analytics_query_failed$") as caught:
            tools.query_metric(
                metric="sales",
                start_date=datetime.date(2026, 10, 10),
                end_date=datetime.date(2026, 10, 10),
                compare_to="previous_7_days",
                filters={"marketplace": "US"},
            )
        self.assertNotIn("private-host", str(caught.exception))
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.commits, 0)
        self.assertTrue(connection.cursor_value.closed)
        self.assertTrue(connection.closed)

    def test_runtime_receives_same_progress_callback_budgets_and_safe_run_config(self) -> None:
        progress = lambda _trace, _observations: None
        self.runner(self.request(), progress)
        call = self.calls[-1]
        self.assertEqual(call["diagnosis_id"], "diagnosis:run-unit-123")
        self.assertIs(call["progress_callback"], progress)
        self.assertIs(call["model"], self.runner._model)
        self.assertEqual(call["max_tool_calls"], 5)
        self.assertEqual(call["max_turns"], 6)
        run_config = call["run_config"]
        self.assertIsInstance(run_config, RunConfig)
        self.assertTrue(run_config.tracing_disabled)
        self.assertFalse(run_config.trace_include_sensitive_data)

    def test_prompt_contains_only_typed_task_fields_and_runner_repr_hides_model(self) -> None:
        self.runner(self.request())
        prompt = self.calls[-1]["prompt"]
        payload = json.loads(prompt)
        self.assertEqual(
            set(payload),
            {
                "metric",
                "target_date",
                "compare_to",
                "filters",
                "group_by",
                "investigation_request",
                "mandatory_query_filters",
            },
        )
        self.assertEqual(payload["compare_to"], "previous_7_days")
        self.assertEqual(payload["filters"], {"marketplace": "US"})
        self.assertEqual(payload["mandatory_query_filters"], {"marketplace": "US"})
        self.assertLessEqual(len(prompt), 8192)
        self.assertNotIn("GroundTruth", prompt)
        self.assertNotIn("api_key", prompt)
        self.assertNotIn("database_url", prompt)
        self.assertIn("explicitly include each supplied filter", payload["investigation_request"])
        self.assertNotIn("do-not-print", repr(self.runner))

    def test_extra_task_parameters_and_noncanonical_dates_fail_closed(self) -> None:
        with self.assertRaises(SourceRunnerRequestError):
            self.runner(
                self.request(
                    parameters={
                        "target_date": "2026-10-10",
                        "filters": {},
                        "group_by": [],
                        "unexpected": "private",
                    }
                )
            )
        with self.assertRaises(SourceRunnerRequestError):
            self.runner(
                self.request(
                    parameters={
                        "target_date": "20261010",
                        "filters": {},
                        "group_by": [],
                    }
                )
            )
        with self.assertRaises(SourceRunnerRequestError):
            self.runner(
                self.request(
                    parameters={
                        "target_date": "2026-10-10",
                        "filters": {"marketplace": "US\nCA"},
                        "group_by": [],
                    }
                )
            )
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
