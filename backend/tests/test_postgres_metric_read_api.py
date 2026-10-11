"""Opt-in actual PostgreSQL reads; no migrations, seeding, models or state writes.

Requires the preserved R4 browser fixture and Olist validation fixture on the
dedicated local acceptance cluster. Never point these tests at business data.
"""
import os
import unittest
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.main import create_app
from app.task_application import TaskApplicationConfig, build_metric_read_service


class PostgresMetricReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.urls = (
            os.environ.get("METRICSLEUTH_METRIC_SYNTHETIC_TEST_URL", ""),
            os.environ.get("METRICSLEUTH_METRIC_OLIST_TEST_URL", ""),
        )
        if not all(cls.urls):
            raise unittest.SkipTest("explicit isolated metric-read databases required")
        expected = ("metricsleuth_r4_browser_acceptance", "metricsleuth_r2_acceptance")
        for url, name in zip(cls.urls, expected):
            parsed = urlsplit(url)
            if not (
                parsed.scheme == "postgresql" and parsed.hostname == "127.0.0.1"
                and parsed.port == 55440 and parsed.username == "metricsleuth_test"
                and parsed.password is None and parsed.path == f"/{name}"
                and not parsed.query and not parsed.fragment
            ):
                raise RuntimeError("isolated_metric_test_configuration_required")

    def setUp(self):
        self.before = tuple(self._counts(url) for url in self.urls)
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.assertEqual(tuple(self._counts(url) for url in self.urls), self.before)

    @staticmethod
    def _counts(url):
        import psycopg
        with psycopg.connect(url, connect_timeout=5) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            return tuple(connection.execute(f"SELECT count(*) FROM app_state.{table}").fetchone()[0]
                         for table in ("investigation_runs", "tool_calls", "observations", "evidence", "diagnoses"))

    def _client(self, profile):
        synthetic = profile == "synthetic"
        url = self.urls[0 if synthetic else 1]
        source_id = ("3989c537-a555-4828-80e5-28b45a9624fa" if synthetic
                     else "bbaf0fe3-c61a-4d03-acca-4e10b69d24b7")
        version = "synthetic-eight-days-v1" if synthetic else "olist-public-raw-files-20261010"
        config = TaskApplicationConfig(url, url, profile, source_id, version, "unused-no-model")
        client = TestClient(create_app(metric_read_service=build_metric_read_service(config),
                                       include_legacy_routes=False))
        self.clients.append(client)
        return client, source_id

    def test_synthetic_actual_values_and_new_application_read(self):
        for _ in range(2):
            client, source_id = self._client("synthetic")
            response = client.get("/api/metrics/observation", params={
                "source_id": source_id, "target_metric": "sales", "target_date": "2026-10-10"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            observation = data["observation"]
            self.assertEqual((observation["current_value"], observation["baseline_value"]), ("100.00", "100.00"))
            self.assertEqual(observation["status"], "normal")
            self.assertEqual(observation["baseline_period_start"], "2026-10-03")
            self.assertEqual(observation["baseline_period_end"], "2026-10-09")
            self.assertEqual(data["anomaly_candidate"], False)
            self.assertEqual(data["persisted"], False)
            self.assertEqual(data["data_version_kind"], "label")
            self.assertTrue(data["query_reference"].startswith("metric-read:"))

    def test_missing_data_is_not_normal_zero(self):
        client, source_id = self._client("synthetic")
        response = client.get("/api/metrics/observation", params={
            "source_id": source_id, "target_metric": "sales", "target_date": "2026-09-01"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["observation"]["status"], "insufficient_evidence")
        self.assertIsNone(data["observation"]["current_value"])
        self.assertIsNone(data["observation"]["baseline_value"])
        self.assertIsNone(data["anomaly_candidate"])

    def test_olist_actual_public_static_gmv(self):
        client, source_id = self._client("olist_validation")
        response = client.get("/api/metrics/observation", params={
            "source_id": source_id, "target_metric": "merchandise_gmv", "target_date": "2017-03-20"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["provider"], data["environment"]), ("olist", "validation"))
        self.assertEqual(data["observation"]["current_value"], "16861.09")
        self.assertEqual(data["observation"]["baseline_value"], "13355.61")
        # Positive movement is not classified as a decline anomaly by the mapper.
        self.assertEqual(data["observation"]["status"], "inconclusive")
        self.assertIsNone(data["anomaly_candidate"])

    def test_olist_unsupported_metric_and_cross_source_rejected(self):
        client, source_id = self._client("olist_validation")
        for source, metric, status, code in (
            (source_id, "sessions", 400, "metric_not_supported"),
            ("3989c537-a555-4828-80e5-28b45a9624fa", "orders", 404, "source_not_found"),
        ):
            response = client.get("/api/metrics/observation", params={
                "source_id": source, "target_metric": metric, "target_date": "2017-03-20"})
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json(), {"detail": {"code": code}})

    def test_synthetic_scan_reads_five_actual_metrics_and_preserves_source_scope(self):
        client, source_id = self._client("synthetic")
        response = client.get("/api/metrics/scan", params={
            "source_id": source_id, "target_date": "2026-10-10"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([item["target_metric"] for item in data["items"]], [
            "sales", "orders", "sessions", "conversion_rate", "aov",
        ])
        sales = data["items"][0]
        self.assertEqual((sales["observation"]["current_value"],
                          sales["observation"]["baseline_value"]), ("100.00", "100.00"))
        self.assertEqual(data["source_id"], source_id)
        self.assertEqual(data["provider"], "synthetic")
        self.assertEqual(data["environment"], "sandbox")
        self.assertEqual(data["data_version"], "synthetic-eight-days-v1")
        self.assertEqual(data["scope"], "source_global")
        self.assertEqual(data["comparison"], "previous_7_days")
        self.assertIs(data["persisted"], False)
        self.assertIs(data["snapshot_consistent"], False)

    def test_olist_scan_reads_three_real_metrics_and_excludes_unsupported_sessions(self):
        client, source_id = self._client("olist_validation")
        response = client.get("/api/metrics/scan", params={
            "source_id": source_id, "target_date": "2017-03-20"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        metric_ids = [item["target_metric"] for item in data["items"]]
        self.assertEqual(metric_ids, ["merchandise_gmv", "orders", "olist_aov"])
        self.assertNotIn("sessions", metric_ids)
        self.assertEqual(data["items"][0]["observation"]["current_value"], "16861.09")
        self.assertEqual(data["items"][0]["observation"]["baseline_value"], "13355.61")
        self.assertEqual(data["provider"], "olist")
        self.assertEqual(data["environment"], "validation")

    def test_scan_missing_data_is_not_zero_and_foreign_source_is_rejected(self):
        client, source_id = self._client("synthetic")
        response = client.get("/api/metrics/scan", params={
            "source_id": source_id, "target_date": "2026-09-01"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(all(
            item["observation"]["status"] == "insufficient_evidence"
            and item["observation"]["current_value"] is None
            and item["observation"]["baseline_value"] is None
            and item["observation"]["relative_change"] is None
            for item in data["items"]
        ))
        self.assertTrue(all(item["anomaly_candidate"] is None for item in data["items"]))
        self.assertEqual(data["anomaly_candidate_metrics"], [])
        foreign = client.get("/api/metrics/scan", params={
            "source_id": "bbaf0fe3-c61a-4d03-acca-4e10b69d24b7",
            "target_date": "2026-10-10"})
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json(), {"detail": {"code": "source_not_found"}})
