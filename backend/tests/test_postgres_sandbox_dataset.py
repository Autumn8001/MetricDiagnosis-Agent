"""Opt-in first publication into three NEW isolated Sandbox databases.

Never creates/drops databases or overwrites existing data. Explicit local fixture
URLs are required; the two preserved acceptance databases are read-only controls.
"""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient

from app.data_sources.capabilities import DataSourceDescriptor, SourceEnvironment, SourceProvider
from app.main import create_app
from app.metrics.registry import MetricRegistry
from app.task_application import TaskApplicationConfig, build_metric_read_service


class PostgresSandboxDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get("METRICSLEUTH_SANDBOX_TEST_URLS", "")
        if not raw:
            raise unittest.SkipTest("explicit NEW isolated Sandbox databases required")
        try:
            urls = json.loads(raw)
            if not isinstance(urls, dict) or set(urls) != {"normal", "canonical", "rollback"}:
                raise ValueError()
            for mode, url in urls.items():
                parsed = urlsplit(url)
                if not (
                    parsed.scheme == "postgresql" and parsed.hostname == "127.0.0.1"
                    and parsed.port == 55440 and parsed.username == "metricsleuth_test"
                    and parsed.password is None and not parsed.query and not parsed.fragment
                    and parsed.path.startswith("/metricsleuth_sandbox_r5002_")
                    and parsed.path.endswith(f"_{mode}")
                ):
                    raise ValueError()
            if len(set(urls.values())) != 3:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError("isolated_sandbox_test_configuration_required") from None
        cls.urls = urls
        from app.sandbox.dataset_writer import SandboxTarget
        cls.targets = {
            mode: SandboxTarget(url, DataSourceDescriptor(
                source_id=str(uuid4()), display_name="Isolated Synthetic Sandbox",
                provider=SourceProvider.SYNTHETIC, environment=SourceEnvironment.SANDBOX,
            )) for mode, url in urls.items()
        }
        cls.protected_before = cls._protected_fingerprints()

    def tearDown(self):
        self.assertEqual(self._protected_fingerprints(), self.protected_before)

    @staticmethod
    def _digest(url, table):
        import psycopg
        from psycopg import sql
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SET LOCAL statement_timeout = 10000")
            if conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None:
                return None
            query = sql.SQL(
                "SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                "FROM (SELECT md5(to_jsonb(t)::text) h FROM {} t) rows"
            ).format(sql.Identifier(*table.split(".")))
            return conn.execute(query).fetchone()

    @classmethod
    def _protected_fingerprints(cls):
        import psycopg
        root = Path(__file__).resolve().parents[2]
        synthetic = MetricRegistry.from_yaml(root / "configs/metrics.yaml").table
        olist = MetricRegistry.from_yaml(root / "configs/olist_validation_metrics.yaml").table
        result = []
        for name in ("metricsleuth_r4_browser_acceptance", "metricsleuth_r2_acceptance"):
            url = f"postgresql://metricsleuth_test@127.0.0.1:55440/{name}"
            with psycopg.connect(url, connect_timeout=5) as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                identity = conn.execute("SELECT current_database(), inet_server_port()").fetchone()
                if identity != (name, 55440):
                    raise RuntimeError("protected_fixture_identity_mismatch")
                counts = tuple(conn.execute(f"SELECT count(*) FROM app_state.{table}").fetchone()[0]
                               for table in ("investigation_runs", "tool_calls", "observations", "evidence", "diagnoses"))
            result.append((identity, counts, cls._digest(url, synthetic), cls._digest(url, olist)))
        return tuple(result)

    def test_01_publish_and_read_through_existing_metric_api(self):
        import psycopg
        from app.sandbox.dataset_writer import publish_sandbox_dataset
        for mode, scenario, expected_sales in (
            ("normal", "no_anomaly", "52000.00"),
            ("canonical", "canonical", "45760.00"),
        ):
            target = self.targets[mode]
            publication = publish_sandbox_dataset(target, scenario)
            self.assertEqual(publication.source_id, target.descriptor.source_id)
            self.assertEqual(publication.row_count, 558)
            self.assertTrue(publication.data_version.startswith("sandbox-"))
            self.assertNotIn(scenario, publication.data_version)
            self.assertEqual(len(publication.checksum), 64)
            with psycopg.connect(self.urls[mode], connect_timeout=5) as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                self.assertEqual(conn.execute("SELECT count(*) FROM warehouse.dim_products").fetchone()[0], 3)
                self.assertEqual(conn.execute("SELECT count(*) FROM warehouse.fact_daily_performance").fetchone()[0], 558)
                manifest = conn.execute(
                    "SELECT source_id::text,data_version,row_count,checksum,scenario_id "
                    "FROM warehouse.sandbox_dataset_manifest"
                ).fetchall()
                self.assertEqual(manifest, [(publication.source_id, publication.data_version, 558, publication.checksum, scenario)])
            config = TaskApplicationConfig(
                self.urls[mode], self.urls[mode], "synthetic", publication.source_id,
                publication.data_version, "unused-no-model",
            )
            for _ in range(2):
                with TestClient(create_app(metric_read_service=build_metric_read_service(config),
                                           include_legacy_routes=False)) as client:
                    response = client.get("/api/metrics/scan", params={
                        "source_id": publication.source_id, "target_date": "2026-01-31",
                    })
                    self.assertEqual(response.status_code, 200)
                    body = response.json()
                    self.assertEqual(body["provider"], "synthetic")
                    self.assertEqual(body["environment"], "sandbox")
                    self.assertEqual(body["data_version"], publication.data_version)
                    self.assertIs(body["persisted"], False)
                    self.assertIs(body["snapshot_consistent"], False)
                    self.assertEqual(len(body["items"]), 5)
                    sales = next(item for item in body["items"] if item["target_metric"] == "sales")
                    self.assertEqual(sales["observation"]["current_value"], expected_sales)
                    self.assertEqual(sales["anomaly_candidate"], mode == "canonical")
                    if mode == "normal":
                        self.assertEqual(body["anomaly_candidate_metrics"], [])
                    else:
                        self.assertIn("sales", body["anomaly_candidate_metrics"])
                    self.assertTrue(all(item["query_reference"].startswith("metric-read:") for item in body["items"]))

    def test_02_nonempty_target_is_not_overwritten(self):
        from app.sandbox.dataset_writer import publish_sandbox_dataset, SandboxDatasetWriterError
        target = self.targets["normal"]
        before = self._digest(self.urls["normal"], "warehouse.fact_daily_performance")
        self.assertIsNotNone(before)
        with self.assertRaises(SandboxDatasetWriterError) as rejected:
            publish_sandbox_dataset(target, "canonical")
        self.assertEqual(rejected.exception.code, "sandbox_target_not_empty")
        self.assertEqual(self._digest(self.urls["normal"], "warehouse.fact_daily_performance"), before)

    def test_03_connection_to_wrong_actual_database_is_rejected(self):
        import psycopg
        from app.sandbox.dataset_writer import publish_sandbox_dataset, SandboxDatasetWriterError
        with self.assertRaises(SandboxDatasetWriterError) as rejected:
            publish_sandbox_dataset(self.targets["rollback"], "canonical", connection_factory=lambda: psycopg.connect(
                "postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r4_browser_acceptance", connect_timeout=5,
            ))
        self.assertEqual(rejected.exception.code, "sandbox_target_mismatch")

    def test_04_constraint_failure_rolls_back_schema_and_rows(self):
        import psycopg
        from app.sandbox import dataset_writer
        bad_rows = list(dataset_writer.build_sandbox_rows("canonical"))
        invalid_row = list(bad_rows[-1])
        invalid_row[8] = -1
        bad_rows[-1] = tuple(invalid_row)
        with patch.object(dataset_writer, "build_sandbox_rows", return_value=bad_rows):
            with self.assertRaises(dataset_writer.SandboxDatasetWriterError) as rejected:
                dataset_writer.publish_sandbox_dataset(self.targets["rollback"], "canonical")
        self.assertEqual(rejected.exception.code, "sandbox_publish_failed")
        self.assertIsInstance(rejected.exception.__context__, psycopg.errors.CheckViolation)
        with psycopg.connect(self.urls["rollback"], connect_timeout=5) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            self.assertIsNone(conn.execute("SELECT to_regclass('warehouse.fact_daily_performance')").fetchone()[0])
            self.assertIsNone(conn.execute("SELECT to_regclass('warehouse.sandbox_dataset_manifest')").fetchone()[0])
            self.assertIsNone(conn.execute("SELECT oid FROM pg_namespace WHERE nspname='warehouse'").fetchone())


if __name__ == "__main__":
    unittest.main()
