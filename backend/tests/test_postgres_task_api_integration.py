"""Opt-in HTTP + real PostgreSQL acceptance, controlled Runner only."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import unittest

from fastapi.testclient import TestClient

from app.api.task_service import InvestigationTasksService, TaskSourceBinding
from app.data_sources.semantic_adapter import build_capabilities_from_registry
from app.main import create_app
from app.metrics.registry import MetricRegistry
from app.persistence.worker import InvestigationWorker
from tests import test_postgres_persistence_integration as pg_fixture


class PostgresTaskApiAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the explicit local-only database guard and migration execution.
        # No production env/config or model provider is consulted.
        pg_fixture.PostgresPersistenceAcceptanceTests.setUpClass()

    def setUp(self):
        self.fixture = pg_fixture.PostgresPersistenceAcceptanceTests()
        self.fixture.setUp()
        registry = MetricRegistry.from_yaml(
            Path(__file__).resolve().parents[2] / "configs" / "metrics.yaml"
        )
        self.binding = TaskSourceBinding(
            descriptor=self.fixture.descriptor,
            capabilities=build_capabilities_from_registry(registry, self.fixture.descriptor),
            data_version=self.fixture.data_version,
        )
        other_descriptor = replace(self.fixture.descriptor, source_id=f"other-api-{uuid4()}")
        self.other_binding = TaskSourceBinding(
            descriptor=other_descriptor,
            capabilities=build_capabilities_from_registry(registry, other_descriptor),
            data_version="other-controlled-version",
        )
        self.runner_calls = []

    def _client(self, runner):
        worker = InvestigationWorker(self.fixture._transaction_connection, runner)
        service = InvestigationTasksService(
            self.fixture._transaction_connection, worker,
            (self.binding, self.other_binding),
        )
        return TestClient(create_app(investigation_tasks_service=service)), worker

    def _submit(self, client, **updates):
        payload = {
            "source_id": self.binding.descriptor.source_id,
            "target_metric": "sales", "target_date": "2026-10-10",
            "filters": {}, "group_by": ["marketplace"],
        }
        payload.update(updates)
        return client.post("/api/investigations", json=payload)

    def _detail(self, client, run_id, source_id=None):
        return client.get(
            f"/api/investigations/{run_id}",
            params={"source_id": source_id or self.binding.descriptor.source_id},
        )

    def test_http_submit_progress_success_and_new_app_history(self):
        def runner(request, progress):
            self.runner_calls.append(request.run_id)
            self.assertEqual(request.parameters["target_date"], "2026-10-10")
            summary = self.fixture._controlled_summary(request)
            progress(summary.investigation.tool_trace[0], summary.observation_catalog)
            running = self._detail(client, request.run_id)
            self.assertEqual(running.status_code, 200)
            self.assertEqual(running.json()["run"]["status"], "running")
            self.assertEqual(len(running.json()["observations"]), 1)
            self.assertEqual(running.json()["diagnoses"], [])
            return summary

        client, worker = self._client(runner)
        submitted = self._submit(client)
        self.assertEqual(submitted.status_code, 202, submitted.text)
        run_id = submitted.json()["investigation_run_id"]
        self.assertEqual(submitted.json()["status"], "queued")
        self.assertEqual(self.runner_calls, [])
        self.assertEqual(worker.run_once(), run_id)
        detail = self._detail(client, run_id)
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertEqual(body["run"]["status"], "succeeded")
        self.assertEqual(body["run"]["data_version"], self.fixture.data_version)
        for key in ("tool_calls", "observations", "evidence", "diagnoses"):
            self.assertEqual(len(body[key]), 1)
        self.assertNotIn("error_message", body["observations"][0])
        self.assertNotIn("payload", body["evidence"][0])
        self.assertEqual(
            body["diagnoses"][0]["evidence_ids"], [body["evidence"][0]["evidence_id"]],
        )

        # Entirely new application/service/worker instances; no cached result.
        reopened, _worker = self._client(lambda *_args: self.fail("Reads must not run a model."))
        self.assertEqual(self._detail(reopened, run_id).json(), body)
        history = reopened.get(
            "/api/investigations", params={"source_id": self.binding.descriptor.source_id},
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["items"][0]["investigation_run_id"], run_id)
        wrong_source = self._detail(reopened, run_id, self.other_binding.descriptor.source_id)
        self.assertEqual(wrong_source.status_code, 404)

    def test_http_failure_keeps_steps_without_fabricated_result(self):
        private_text = "controlled-private-error-marker"

        def runner(request, progress):
            summary = self.fixture._controlled_summary(request)
            progress(summary.investigation.tool_trace[0], summary.observation_catalog)
            raise RuntimeError(private_text)

        client, worker = self._client(runner)
        response = self._submit(client)
        self.assertEqual(response.status_code, 202)
        run_id = response.json()["investigation_run_id"]
        self.assertEqual(worker.run_once(), run_id)
        detail = self._detail(client, run_id)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["run"]["status"], "failed")
        self.assertEqual(detail.json()["run"]["failure_code"], "execution_failed")
        self.assertEqual(len(detail.json()["observations"]), 1)
        self.assertEqual(detail.json()["evidence"], [])
        self.assertEqual(detail.json()["diagnoses"], [])
        self.assertNotIn(private_text, detail.text)

    def test_http_invalid_capabilities_and_credentials_rejected_without_writes(self):
        client, _worker = self._client(lambda *_args: self.fail("No Runner expected."))
        for updates, expected in (
            ({"target_metric": "invented_metric"}, 400),
            ({"group_by": ["invented_dimension"]}, 400),
            ({"source_id": "unregistered-controlled-source"}, 404),
            ({"target_date": "2026-10-10T00:00:00Z"}, 422),
            ({"database_url": "postgresql://private-marker@invalid/db"}, 422),
            ({"environment": "live"}, 422),
        ):
            with self.subTest(updates=updates):
                response = self._submit(client, **updates)
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("private-marker", response.text)
        history = client.get(
            "/api/investigations", params={"source_id": self.binding.descriptor.source_id},
        )
        self.assertEqual(history.json()["items"], [])

    def test_storage_error_response_suppresses_raw_connection_exception(self):
        worker = InvestigationWorker(
            self.fixture._transaction_connection, lambda *_args: self.fail("No Runner expected."),
        )

        def broken_factory():
            raise RuntimeError("controlled-secret-connection-marker")

        service = InvestigationTasksService(broken_factory, worker, (self.binding,))
        client = TestClient(create_app(investigation_tasks_service=service))
        response = client.get(
            "/api/investigations", params={"source_id": self.binding.descriptor.source_id},
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("controlled-secret-connection-marker", response.text)


if __name__ == "__main__":
    unittest.main()
