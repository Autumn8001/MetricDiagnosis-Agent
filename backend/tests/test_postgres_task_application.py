"""Explicit application wiring + actual Analytics SQL; controlled Runner only."""
import datetime
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
import unittest
from uuid import uuid4

import httpx

from fastapi.testclient import TestClient

from app.agent_runtime import EvidenceDrivenRunSummary
from app.diagnosis import DiagnosisComposition
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.main import create_app
from app.observations.mapper import observations_from_metric_query
from app.persistence.repository import ApplicationStateRepository
from app.task_application import TaskApplicationConfig, build_task_application
from tests import test_postgres_persistence_integration as pg


class PostgresTaskApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg.PostgresPersistenceAcceptanceTests.setUpClass()
        cls.fixture = pg.PostgresPersistenceAcceptanceTests()
        # Explicit isolated test DB guard has already executed. Only additive
        # synthetic test data; no injector, production or external data access.
        connection = cls.fixture._transaction_connection()
        try:
            connection.execute((Path(__file__).resolve().parents[2] / "warehouse" / "schema.sql").read_text())
            connection.commit()
        finally:
            connection.close()

    def setUp(self):
        self.fixture.setUp()
        self.asin = f"acceptance-{uuid4()}"
        connection = self.fixture._transaction_connection()
        try:
            connection.execute("INSERT INTO warehouse.dim_products VALUES (%s, %s, %s)",
                               (self.asin, "Controlled application fixture", "test"))
            for day in range(3, 11):
                connection.execute(
                    "INSERT INTO warehouse.fact_daily_performance "
                    "(date,asin,marketplace,traffic_source,impressions,clicks,sessions,orders,sales,ad_spend,refunds) "
                    "VALUES (%s,%s,'US','test',100,10,100,10,%s,0,0)",
                    (datetime.date(2026, 10, day), self.asin, 80 if day == 10 else 100),
                )
            connection.commit()
        finally:
            connection.close()
        self.config = TaskApplicationConfig(
            self.fixture._database_url, self.fixture._database_url,
            "synthetic", f"application-{uuid4()}", f"fixture-version-{uuid4()}", "controlled-test-model",
        )

    def _submit(self, client):
        response = client.post("/api/investigations", json={
            "source_id": self.config.source_id, "target_metric": "sales", "target_date": "2026-10-10",
            "filters": {"asin": self.asin}, "group_by": ["marketplace"],
        })
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["investigation_run_id"]

    def test_application_reads_real_metric_and_persists_result(self):
        def controlled_runner(prompt, **kwargs):
            tools = kwargs["analytics_tools"]
            result = tools.query_metric("sales", datetime.date(2026, 10, 10), datetime.date(2026, 10, 10),
                                        "previous_7_days", {"asin": self.asin}, ["marketplace"])
            self.assertEqual(result.rows[0].current_value, Decimal("80"))
            self.assertEqual(result.rows[0].baseline_value, Decimal("100"))
            # Use the actual result mapper. Only action selection/final intent
            # are controlled, not the metric values or Observation creation.
            run_id = kwargs["diagnosis_id"].removeprefix("diagnosis:")
            request = replace(self.fixture._request(run_id), descriptor=service._sources[self.config.source_id].descriptor)
            base = self.fixture._controlled_summary(request, diagnosis_id=kwargs["diagnosis_id"])
            trace = base.investigation.tool_trace[0]
            observations = observations_from_metric_query(
                result, tool_name="query_metric", tool_call_id=trace.tool_call_id,
                filters={"asin": self.asin}, query_or_result_reference=f"tool-result:{trace.tool_call_id}",
                created_at=base.observation_catalog[0].created_at,
            )
            evidence = promote_observation_to_evidence(observations[0], role=EvidenceRole.SUPPORTING)
            trace = replace(trace, arguments={"metric": "sales", "start_date": "2026-10-10",
                "end_date": "2026-10-10", "compare_to": "previous_7_days",
                "filters": {"asin": self.asin}, "group_by": ["marketplace"]},
                observation_ids=(observations[0].observation_id,))
            diagnosis = replace(base.composition.diagnosis, affected_scope={"marketplace": "US"},
                evidence_ids=(evidence.evidence_id,),
                change=replace(base.composition.diagnosis.change, evidence_id=evidence.evidence_id))
            summary = EvidenceDrivenRunSummary(
                investigation=replace(base.investigation, tool_trace=(trace,),
                    observation_ids=trace.observation_ids),
                composition=DiagnosisComposition(evidence=(evidence,), diagnosis=diagnosis),
                observation_catalog=observations,
            )
            kwargs["progress_callback"](trace, observations)
            return summary

        service, worker = build_task_application(self.config, diagnosis_runner=controlled_runner)
        client = TestClient(create_app(investigation_tasks_service=service, include_legacy_routes=False))
        run_id = self._submit(client)
        self.assertEqual(worker.run_once(), run_id)
        response = client.get(f"/api/investigations/{run_id}", params={"source_id": self.config.source_id})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["run"]["status"], "succeeded")
        self.assertEqual(body["run"]["provider"], "synthetic")
        self.assertEqual(body["observations"][0]["filters"], {"asin": self.asin})
        self.assertEqual(Decimal(body["observations"][0]["current_value"]), Decimal("80"))

    def test_read_only_sql_rejects_writes_without_exposing_driver_error(self):
        def controlled_runner(prompt, **kwargs):
            with kwargs["analytics_tools"]._connection.cursor() as cursor:
                cursor.execute("UPDATE warehouse.fact_daily_performance SET sales = 0 WHERE asin = %s", (self.asin,))

        service, worker = build_task_application(self.config, diagnosis_runner=controlled_runner)
        client = TestClient(create_app(investigation_tasks_service=service, include_legacy_routes=False))
        run_id = self._submit(client)
        self.assertEqual(worker.run_once(), run_id)
        response = client.get(f"/api/investigations/{run_id}", params={"source_id": self.config.source_id})
        self.assertEqual(response.json()["run"]["status"], "failed")
        self.assertEqual(response.json()["diagnoses"], [])
        connection = self.fixture._transaction_connection()
        try:
            value = connection.execute("SELECT sum(sales) FROM warehouse.fact_daily_performance WHERE asin = %s", (self.asin,)).fetchone()[0]
            self.assertEqual(value, Decimal("780"))
        finally:
            connection.close()

    def test_omitted_capabilities_preserved_but_explicit_empty_clears(self):
        connection = self.fixture._transaction_connection()
        try:
            repository = ApplicationStateRepository(connection)
            repository.upsert_data_source(self.fixture.descriptor, capabilities={"supported": True}, data_version="v1")
            repository.upsert_data_source(self.fixture.descriptor, data_version="v2")
            row = connection.execute("SELECT capabilities,data_version FROM app_state.data_sources WHERE source_id = %s", (self.fixture.source_id,)).fetchone()
            self.assertEqual(row, ({"supported": True}, "v2"))
            repository.upsert_data_source(self.fixture.descriptor, capabilities={})
            self.assertEqual(connection.execute("SELECT capabilities FROM app_state.data_sources WHERE source_id = %s", (self.fixture.source_id,)).fetchone()[0], {})
            connection.commit()
        finally:
            connection.close()

    def test_local_api_entrypoint_starts_as_separate_process(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        environment = os.environ.copy()
        environment.update({
            "METRICSLEUTH_STATE_DATABASE_URL": self.fixture._database_url,
            "METRICSLEUTH_ANALYTICS_DATABASE_URL": self.fixture._database_url,
            "METRICSLEUTH_TASK_PROFILE": self.config.profile,
            "METRICSLEUTH_TASK_SOURCE_ID": self.config.source_id,
            "METRICSLEUTH_TASK_DATA_VERSION": self.config.data_version,
            "METRICSLEUTH_TASK_MODEL": self.config.model,
        })
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "app.task_application", "api", "--port", str(port)],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1) as client:
                deadline = time.monotonic() + 20
                while True:
                    self.assertIsNone(process.poll(), "Local API exited before readiness")
                    try:
                        response = client.get("/health")
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    self.assertLess(time.monotonic(), deadline, "Local API did not become ready")
                    time.sleep(0.1)
                self.assertEqual(response.json()["mode"], "local_tasks")
                history = client.get("/api/investigations", params={"source_id": self.config.source_id})
                self.assertEqual(history.status_code, 200)
                self.assertEqual(history.json()["items"], [])
                self.assertEqual(client.post("/api/scenarios/inject", json={}).status_code, 404)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
