"""Offline safety and controlled-runner contract tests for the browser harness."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
import io
import json
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.analytics.models import DateRange, MetricQueryResult, MetricQueryRow
from scripts import serve_browser_task_acceptance as acceptance


SOURCE_ID = "3989c537-a555-4828-80e5-28b45a9624fa"
DATABASE_URL = "postgresql://acceptance@127.0.0.1:55440/metricsleuth_r4_browser_acceptance"


class BrowserTaskAcceptanceGuardsTests(unittest.TestCase):
    def test_database_url_requires_exact_loopback_database_without_password(self) -> None:
        self.assertEqual(acceptance.validate_database_url(DATABASE_URL),
                         (acceptance.DATABASE_NAME, 55440))
        rejected = (
            "postgresql://acceptance:secret@127.0.0.1:55440/metricsleuth_r4_browser_acceptance",
            "postgresql://acceptance:@127.0.0.1/metricsleuth_r4_browser_acceptance",
            "postgresql:///metricsleuth_r4_browser_acceptance",
            "postgresql://acceptance@example.invalid/metricsleuth_r4_browser_acceptance",
            "postgresql://acceptance@127.0.0.1:70000/metricsleuth_r4_browser_acceptance",
            DATABASE_URL + "?sslmode=disable",
            DATABASE_URL + "#fragment",
            DATABASE_URL.replace(acceptance.DATABASE_NAME, "metricsleuth_r2_acceptance"),
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(acceptance.AcceptanceFailure):
                acceptance.validate_database_url(value)

    def test_invalid_database_is_rejected_before_connection_and_secret_is_not_echoed(self) -> None:
        stderr = io.StringIO()
        with patch.object(acceptance, "_connect") as connect, redirect_stderr(stderr):
            result = acceptance.main([
                "--database-url", "postgresql://u:do-not-print@remote.invalid/private",
                "--source-id", SOURCE_ID,
            ])
        self.assertEqual(result, 2)
        connect.assert_not_called()
        self.assertNotIn("do-not-print", stderr.getvalue())
        self.assertNotIn("remote.invalid", stderr.getvalue())

    def test_malformed_port_is_rejected_without_echoing_sensitive_shape(self) -> None:
        sensitive_port = "5432-password-like-value"
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                acceptance._parse_args([
                    "--database-url", DATABASE_URL,
                    "--source-id", SOURCE_ID,
                    "--port", sensitive_port,
                ])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(stderr.getvalue(), "invalid_arguments\n")
        self.assertNotIn(sensitive_port, stderr.getvalue())

    def test_prepare_refuses_existing_application_schema_before_migrations(self) -> None:
        class Cursor:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, _params=None):
                self.connection.queries.append(query)

            def fetchone(self):
                return (acceptance.DATABASE_NAME,)

            def fetchall(self):
                return [("app_state",)]

        class Connection:
            queries = []

            def cursor(self):
                return Cursor(self)

        connection = Connection()
        with self.assertRaises(acceptance.AcceptanceFailure) as raised:
            acceptance._prepare_fixture(connection)
        self.assertEqual(raised.exception.code, "acceptance_database_not_fresh")
        self.assertEqual(len(connection.queries), 2)
        self.assertFalse(any("CREATE SCHEMA" in query for query in connection.queries))

    def test_manifest_is_explicit_and_product_routes_are_real_task_routes(self) -> None:
        app, _worker = acceptance.build_acceptance_app(DATABASE_URL, SOURCE_ID)
        with TestClient(app) as client:
            response = client.get("/__acceptance__/manifest")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                "acceptance_kind": "controlled_browser_task",
                "database": acceptance.DATABASE_NAME,
                "source_id": SOURCE_ID,
                "target_date": "2026-10-10",
                "controlled_runner": True,
                "real_model": False,
                "fixture": "synthetic-eight-days-v1",
            })
            self.assertEqual(client.get("/health").json(), {"status": "ok", "mode": "local_tasks"})
            sources = client.get("/api/investigation-sources")
            self.assertEqual(sources.status_code, 200)
            self.assertEqual(sources.json()["items"][0]["data_version"], acceptance.SALES_FIXTURE)
            self.assertEqual(sources.json()["items"][0]["provider"], "synthetic")
            self.assertEqual(sources.json()["items"][0]["environment"], "sandbox")
            self.assertEqual(client.get("/api/scenarios").status_code, 404)

    def test_controlled_runner_contract_maps_fake_analytics_result_and_persists_progress_shape(self) -> None:
        class FakeAnalytics:
            _target_date = acceptance.TARGET_DATE
            _fixed_filters = {}

            def __init__(self):
                self.calls = []

            def query_metric(self, **kwargs):
                self.calls.append(kwargs)
                return MetricQueryResult(
                    metric_id="sales",
                    unit="usd",
                    current_period=DateRange(acceptance.TARGET_DATE, acceptance.TARGET_DATE),
                    baseline_period=DateRange(dt.date(2026, 10, 3), dt.date(2026, 10, 9)),
                    group_by=(),
                    rows=(MetricQueryRow(
                        dimensions={}, current_value=Decimal("100.00"),
                        baseline_value=Decimal("100.00"), relative_change=Decimal("0"),
                        status="ok", sample_size=Decimal("100"),
                    ),),
                )

        prompt = json.dumps({
            "metric": "sales", "target_date": "2026-10-10",
            "compare_to": "previous_7_days", "filters": {}, "group_by": [],
            "investigation_request": "controlled test only",
        })
        analytics = FakeAnalytics()
        progress = []
        summary = acceptance.controlled_diagnosis_runner(
            prompt,
            diagnosis_id="diagnosis:offline-acceptance",
            analytics_tools=analytics,
            max_tool_calls=8,
            max_turns=10,
            progress_callback=lambda trace, observations: progress.append((trace, observations)),
        )
        self.assertEqual(analytics.calls, [{
            "metric": "sales", "start_date": acceptance.TARGET_DATE,
            "end_date": acceptance.TARGET_DATE, "compare_to": "previous_7_days",
            "filters": {}, "group_by": [],
        }])
        self.assertEqual(summary.observation_catalog[0].current_value, Decimal("100.00"))
        self.assertEqual(summary.observation_catalog[0].baseline_value, Decimal("100.00"))
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress[0][0].tool_call_id, summary.investigation.tool_call_ids[0])
        self.assertEqual(summary.composition.diagnosis.status.value, "no_material_anomaly")
        self.assertEqual(summary.composition.diagnosis.limitations, (acceptance.LIMITATION,))
        self.assertIn("offline", summary.composition.diagnosis.diagnosis_id)

    def test_controlled_runner_rejects_out_of_scope_prompt_without_querying(self) -> None:
        class FakeAnalytics:
            _target_date = acceptance.TARGET_DATE
            _fixed_filters = {}

            def query_metric(self, **_kwargs):
                raise AssertionError("out-of-scope task must not query")

        with self.assertRaisesRegex(RuntimeError, "acceptance_request_out_of_scope"):
            acceptance.controlled_diagnosis_runner(
                '{"metric":"orders"}', diagnosis_id="diagnosis:invalid",
                analytics_tools=FakeAnalytics(), max_tool_calls=8, max_turns=10,
                progress_callback=lambda *_args: None,
            )


if __name__ == "__main__":
    unittest.main()
