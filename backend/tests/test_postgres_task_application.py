"""Explicit application wiring + actual Analytics SQL; controlled Runner only."""
import datetime
import json
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
from agents.testing import ScriptedModel, assistant_message, function_call

from app.agent_runtime import EvidenceDrivenRunSummary, run_evidence_driven_diagnosis
from app.diagnosis import DiagnosisComposition
from app.data_sources.capabilities import SourceProvider
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.main import create_app
from app.observations.mapper import observations_from_metric_query
from app.persistence.repository import ApplicationStateRepository
from app.persistence.worker import InvestigationWorker
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

    def test_sdk_normal_scope_disclosure_survives_fresh_application_read(self):
        # Scripted decisions, actual SDK tools/SQL/Writer. No provider client or
        # credentials are needed, and unqueried segments are never invented.
        observation_id = "normal_scope_call_sessions_0"
        evidence_id = f"evidence:{observation_id}:supporting"
        payload = {
            "evidence_selections": [{"observation_id": observation_id, "role": "supporting"}],
            "status": "no_material_anomaly", "target_metric": "sessions",
            "target_evidence_id": evidence_id, "driver_evidence_id": None,
            "primary_driver": None, "affected_scope": [], "evidence_ids": [evidence_id],
            "confidence": "0.80", "limitations": ["Controlled aggregate-only investigation."],
        }
        model = ScriptedModel([
            [function_call("query_metric", {
                "metric": "sessions", "start_date": "2026-10-10", "end_date": "2026-10-10",
                "compare_to": "previous_7_days", "filters": {"asin": self.asin}, "group_by": [],
            }, call_id="normal_scope_call")],
            [assistant_message(json.dumps(payload))],
        ])
        summaries = []

        def controlled_runner(prompt, **kwargs):
            kwargs["model"] = model
            summary = run_evidence_driven_diagnosis(prompt, **kwargs)
            summaries.append(summary)
            return summary

        service, worker = build_task_application(self.config, diagnosis_runner=controlled_runner)
        with TestClient(create_app(investigation_tasks_service=service, include_legacy_routes=False)) as client:
            response = client.post("/api/investigations", json={
                "source_id": self.config.source_id, "target_metric": "sessions",
                "target_date": "2026-10-10", "filters": {"asin": self.asin}, "group_by": [],
            })
            self.assertEqual(response.status_code, 202, response.text)
            run_id = response.json()["investigation_run_id"]
            self.assertEqual(worker.run_once(), run_id)

        # Rebuild services: response must come from persisted PostgreSQL facts,
        # not the in-memory SDK summary or original HTTP application.
        fresh_service, _ = build_task_application(self.config, diagnosis_runner=controlled_runner)
        with TestClient(create_app(investigation_tasks_service=fresh_service, include_legacy_routes=False)) as client:
            response = client.get(f"/api/investigations/{run_id}",
                                  params={"source_id": self.config.source_id})
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
        self.assertEqual(body["run"]["status"], "succeeded")
        self.assertEqual([len(body[key]) for key in ("tool_calls", "observations", "evidence", "diagnoses")],
                         [1, 1, 1, 1])
        diagnosis = body["diagnoses"][0]
        self.assertEqual(diagnosis["status"], "no_material_anomaly")
        self.assertEqual(diagnosis["affected_scope"], {})
        self.assertIsNone(diagnosis["primary_driver"])
        self.assertEqual(diagnosis["evidence_ids"], [evidence_id])
        self.assertIn("unqueried segments may still be anomalous", diagnosis["limitations"][-1])
        observation = body["observations"][0]
        self.assertEqual(observation["filters"], {"asin": self.asin})
        self.assertEqual(observation["dimensions"], {})
        self.assertEqual(Decimal(observation["current_value"]), Decimal("100"))
        self.assertEqual(Decimal(observation["baseline_value"]), Decimal("100"))
        self.assertEqual(json.loads(summaries[0].investigation.final_output)["limitations"],
                         payload["limitations"])
        self.assertEqual(len(summaries), 1)
        model.assert_complete()

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

    def test_source_bound_application_leaves_other_queued_tasks_untouched(self):
        calls = []
        sql_values = []

        def controlled_runner(prompt, **kwargs):
            calls.append("synthetic")
            result = kwargs["analytics_tools"].query_metric(
                "sales", datetime.date(2026, 10, 10), datetime.date(2026, 10, 10),
                "previous_7_days", {"asin": self.asin}, [])
            sql_values.append(result.rows[0].current_value)
            raise RuntimeError("controlled_stop")

        def other_runner(*args, **kwargs):
            calls.append("olist")
            raise RuntimeError("controlled_stop")

        other_config = replace(self.config, profile="olist_validation", source_id=f"other-{uuid4()}")
        other_service, other_worker = build_task_application(other_config, diagnosis_runner=other_runner)
        service, worker = build_task_application(self.config, diagnosis_runner=controlled_runner)
        with TestClient(create_app(investigation_tasks_service=other_service, include_legacy_routes=False)) as other_client, \
                TestClient(create_app(investigation_tasks_service=service, include_legacy_routes=False)) as client:
            # The foreign task is older. An unscoped worker would claim it first.
            response = other_client.post("/api/investigations", json={
                "source_id": other_config.source_id, "target_metric": "merchandise_gmv",
                "target_date": "2017-03-20", "filters": {}, "group_by": []})
            self.assertEqual(response.status_code, 202)
            other_run_id = response.json()["investigation_run_id"]
            run_id = self._submit(client)
            try:
                self.assertEqual(worker.run_once(), run_id)
                self.assertIsNone(worker.run_once())
                self.assertEqual(calls, ["synthetic"])
                self.assertEqual(sql_values, [Decimal("80")])
                other_detail = other_client.get(f"/api/investigations/{other_run_id}",
                                               params={"source_id": other_config.source_id}).json()
                self.assertEqual(other_detail["run"]["status"], "queued")
                self.assertIsNone(other_detail["run"]["started_at"])
                self.assertEqual(other_detail["run"]["tool_call_count"], 0)
                self.assertEqual(other_worker.run_once(), other_run_id)
                self.assertEqual(calls, ["synthetic", "olist"])
            finally:
                # Terminalize only this test's generated records, without deletes.
                connection = self.fixture._transaction_connection()
                try:
                    repository = ApplicationStateRepository(connection)
                    for identifier in (run_id, other_run_id):
                        if repository.get_investigation_run(identifier).status.value in {"queued", "running"}:
                            repository.fail_investigation_run(run_id=identifier, failure_code="acceptance_cleanup")
                    connection.commit()
                finally:
                    connection.close()

    def test_source_bound_recovery_does_not_fail_another_sources_running_task(self):
        runner_calls = []

        def forbidden_runner(*args, **kwargs):
            runner_calls.append(True)
            self.fail("Recovery must not replay any Runner")

        other_config = replace(self.config, profile="olist_validation", source_id=f"other-{uuid4()}")
        other_service, other_worker = build_task_application(other_config, diagnosis_runner=forbidden_runner)
        service, worker = build_task_application(self.config, diagnosis_runner=forbidden_runner)
        with TestClient(create_app(investigation_tasks_service=other_service, include_legacy_routes=False)) as other_client, \
                TestClient(create_app(investigation_tasks_service=service, include_legacy_routes=False)) as client:
            response = other_client.post("/api/investigations", json={
                "source_id": other_config.source_id, "target_metric": "merchandise_gmv",
                "target_date": "2017-03-20", "filters": {}, "group_by": []})
            self.assertEqual(response.status_code, 202)
            other_run_id = response.json()["investigation_run_id"]
            run_id = self._submit(client)
            connection = self.fixture._transaction_connection()
            try:
                # Simulate two persisted interrupted runs; no model execution.
                connection.execute("UPDATE app_state.investigation_runs SET status='running', started_at=now() "
                                   "WHERE investigation_run_id IN (%s,%s) AND status='queued'",
                                   (run_id, other_run_id))
                connection.commit()
            finally:
                connection.close()
            try:
                self.assertIsNone(worker.run_once())
                own = client.get(f"/api/investigations/{run_id}", params={"source_id": self.config.source_id}).json()
                other = other_client.get(f"/api/investigations/{other_run_id}",
                                         params={"source_id": other_config.source_id}).json()
                self.assertEqual(own["run"]["status"], "failed")
                self.assertEqual(own["run"]["failure_code"], "worker_interrupted")
                self.assertEqual(other["run"]["status"], "running")
                self.assertIsNone(other["run"]["failure_code"])
                self.assertIsNone(other_worker.run_once())
                other = other_client.get(f"/api/investigations/{other_run_id}",
                                         params={"source_id": other_config.source_id}).json()
                self.assertEqual(other["run"]["failure_code"], "worker_interrupted")
                self.assertEqual(other["diagnoses"], [])
                self.assertEqual(runner_calls, [])
            finally:
                connection = self.fixture._transaction_connection()
                try:
                    repository = ApplicationStateRepository(connection)
                    for identifier in (run_id, other_run_id):
                        if repository.get_investigation_run(identifier).status.value in {"queued", "running"}:
                            repository.fail_investigation_run(run_id=identifier, failure_code="acceptance_cleanup")
                    connection.commit()
                finally:
                    connection.close()

    def test_incorrect_provider_binding_neither_claims_nor_recovers_source_tasks(self):
        service, owner = build_task_application(self.config,
            diagnosis_runner=lambda *args, **kwargs: self.fail("Recovery must not execute Runner"))
        wrong_descriptor = replace(service._sources[self.config.source_id].descriptor,
                                   provider=SourceProvider.POSTGRESQL)
        invoked = []
        wrong_worker = InvestigationWorker(self.fixture._transaction_connection,
            lambda *args: invoked.append(True), expected_source=wrong_descriptor)
        with TestClient(create_app(investigation_tasks_service=service, include_legacy_routes=False)) as client:
            run_id = self._submit(client)
            try:
                self.assertIsNone(wrong_worker.run_once())
                detail = client.get(f"/api/investigations/{run_id}",
                                    params={"source_id": self.config.source_id}).json()
                self.assertEqual(detail["run"]["status"], "queued")
                connection = self.fixture._transaction_connection()
                try:
                    connection.execute("UPDATE app_state.investigation_runs SET status='running',started_at=now() "
                                       "WHERE investigation_run_id=%s AND status='queued'", (run_id,))
                    connection.commit()
                finally:
                    connection.close()
                self.assertIsNone(wrong_worker.run_once())
                detail = client.get(f"/api/investigations/{run_id}",
                                    params={"source_id": self.config.source_id}).json()
                self.assertEqual(detail["run"]["status"], "running")
                self.assertIsNone(detail["run"]["failure_code"])
                self.assertEqual(invoked, [])
            finally:
                # The correctly bound owner may terminalize only its own interrupted task.
                self.assertIsNone(owner.run_once())

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
