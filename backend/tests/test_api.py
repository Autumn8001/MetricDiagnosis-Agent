"""Unit test suite for MetricSleuth FastAPI backend service."""

from __future__ import annotations

import json
import os
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend directory is in sys.path regardless of execution cwd
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from fastapi.testclient import TestClient

from app.api import service as api_service
from app.agent_runtime.investigation_runtime import InvestigationToolTraceEntry
from app.main import app


class TestSystemEndpoints(unittest.TestCase):
    """Test system health, docs, and metadata endpoints."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_check(self) -> None:
        """GET /health should return 200 with service metadata."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "MetricSleuth API")
        self.assertEqual(data["version"], "1.0.0")
        self.assertIn("timestamp", data)
        self.assertTrue(len(data["timestamp"]) > 0)

    def test_docs_and_openapi_available(self) -> None:
        """FastAPI OpenAPI specification and Swagger UI should be accessible."""
        openapi_res = self.client.get("/openapi.json")
        self.assertEqual(openapi_res.status_code, 200)
        openapi_data = openapi_res.json()
        self.assertEqual(openapi_data["info"]["title"], "MetricSleuth API")

        docs_res = self.client.get("/docs")
        self.assertEqual(docs_res.status_code, 200)


class TestMetricGraphEndpoint(unittest.TestCase):
    """Test topological metric dependency graph endpoints."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_get_metrics_graph_success(self) -> None:
        """GET /api/metrics/graph should return 5 nodes and directed edges."""
        response = self.client.get("/api/metrics/graph")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("nodes", data)
        self.assertIn("edges", data)

        node_ids = {node["metric_id"] for node in data["nodes"]}
        expected_metrics = {"sales", "orders", "sessions", "conversion_rate", "aov"}
        self.assertEqual(node_ids, expected_metrics)

    def test_metric_graph_node_attributes(self) -> None:
        """Nodes in the metric graph must contain complete descriptive metadata."""
        response = self.client.get("/api/metrics/graph")
        self.assertEqual(response.status_code, 200)
        nodes = {node["metric_id"]: node for node in response.json()["nodes"]}

        cr = nodes["conversion_rate"]
        self.assertEqual(cr["metric_type"], "ratio")
        self.assertEqual(cr["unit"], "ratio")
        self.assertIn("orders", cr["dependencies"])
        self.assertIn("sessions", cr["dependencies"])

        sales = nodes["sales"]
        self.assertEqual(sales["unit"], "usd")
        self.assertIn("orders", sales["related_metrics"])

    def test_metric_graph_edges_structure(self) -> None:
        """Graph should contain valid dependency and decomposition edges."""
        response = self.client.get("/api/metrics/graph")
        self.assertEqual(response.status_code, 200)
        edges = response.json()["edges"]

        self.assertTrue(len(edges) > 0)
        relationships = {e["relationship"] for e in edges}
        self.assertIn("depends_on", relationships)
        self.assertIn("decomposes_to", relationships)

        edge_pairs = {(e["source"], e["target"]) for e in edges}
        self.assertIn(("conversion_rate", "orders"), edge_pairs)
        self.assertIn(("sales", "orders"), edge_pairs)


class TestScenarioEndpoints(unittest.TestCase):
    """Test scenario listing and anomaly injection endpoints."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_list_scenarios(self) -> None:
        """GET /api/scenarios should return all 10 benchmark scenarios."""
        response = self.client.get("/api/scenarios")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("scenarios", data)
        scenarios = data["scenarios"]
        self.assertEqual(len(scenarios), 10)

        scenario_ids = [s["scenario_id"] for s in scenarios]
        expected_scenarios = [
            "canonical",
            "traffic",
            "no_anomaly",
            "aov_us_asin_b_organic",
            "traffic_uk_asin_b_ads",
            "conversion_de_asin_c_ads",
            "traffic_us_asin_c_organic",
            "aov_uk_asin_a_ads",
            "conversion_us_asin_b_ads",
            "distractor_minor_fluctuation",
        ]
        self.assertEqual(scenario_ids, expected_scenarios)

    def test_scenario_metadata_integrity(self) -> None:
        """Scenario selector metadata must not expose benchmark answers."""
        response = self.client.get("/api/scenarios")
        self.assertEqual(response.status_code, 200)
        scenario_map = {s["scenario_id"]: s for s in response.json()["scenarios"]}

        canonical = scenario_map["canonical"]
        self.assertEqual(
            set(canonical),
            {"scenario_id", "title", "description", "target_metric"},
        )
        self.assertEqual(canonical["target_metric"], "sales")
        self.assertTrue(canonical["title"].startswith("Controlled Case"))
        self.assertNotIn("conversion_rate", canonical["title"])
        self.assertNotIn("US", canonical["description"])
        for scenario in scenario_map.values():
            self.assertTrue(scenario["title"].startswith("Controlled Case"))
            self.assertEqual(
                scenario["description"],
                "Controlled benchmark fixture for preview and data injection; "
                "expected diagnosis is intentionally hidden.",
            )
            self.assertNotIn("primary_driver", scenario)
            self.assertNotIn("affected_scope", scenario)
            self.assertNotIn("expected_status", scenario)

        openapi = self.client.get("/openapi.json").json()
        scenario_properties = set(
            openapi["components"]["schemas"]["ScenarioItem"]["properties"]
        )
        self.assertEqual(
            scenario_properties,
            {"scenario_id", "title", "description", "target_metric"},
        )

    def test_api_scenario_catalog_has_no_evaluation_answer_fields(self) -> None:
        """The product API must select scenarios without importing Ground Truth answers."""
        source = inspect.getsource(api_service)
        self.assertNotIn("load_ground_truth_cases", source)
        self.assertNotIn("GroundTruthCase", source)
        self.assertNotIn("benchmark_cases.json", source)
        self.assertFalse(hasattr(api_service, "get_benchmark_cases"))
        self.assertEqual(
            [(item.scenario_id, item.target_metric) for item in api_service.get_scenario_catalog()],
            [(item["scenario_id"], item["target_metric"]) for item in json.loads(
                (Path(__file__).resolve().parents[2] / "warehouse" / "scenario_catalog.json").read_text(encoding="utf-8")
            )["scenarios"]],
        )

    def test_inject_scenario_without_database_runs_explicit_dry_run(self) -> None:
        """Without DATABASE_URL, a successful fixture dry-run updates selected scenario."""
        completed = MagicMock(returncode=0, stderr="")
        with (
            patch.object(api_service, "_current_scenario", "canonical"),
            patch.dict(os.environ, {}, clear=False),
            patch("app.api.service.subprocess.run", return_value=completed),
        ):
            os.environ.pop("DATABASE_URL", None)
            response = self.client.post(
                "/api/scenarios/inject",
                json={"scenario": "traffic"},
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["scenario"], "traffic")
            self.assertEqual(data["mode"], "dry_run")
            self.assertEqual(api_service._current_scenario, "traffic")

    def test_live_injection_failure_is_fail_closed_without_state_drift(self) -> None:
        """A configured warehouse injection failure must not downgrade or change state."""
        completed = MagicMock(returncode=1, stderr="database unavailable")
        with (
            patch.object(api_service, "_current_scenario", "canonical"),
            patch.dict(os.environ, {"DATABASE_URL": "postgresql://test/warehouse"}, clear=False),
            patch("app.api.service.subprocess.run", return_value=completed) as mock_run,
        ):
            response = self.client.post(
                "/api/scenarios/inject",
                json={"scenario": "traffic"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Live scenario injection failed", response.json()["detail"])
            self.assertEqual(api_service._current_scenario, "canonical")
            mock_run.assert_called_once()

    def test_inject_invalid_scenario_returns_400(self) -> None:
        """POST /api/scenarios/inject with unknown scenario should return 400 Bad Request."""
        response = self.client.post(
            "/api/scenarios/inject",
            json={"scenario": "unknown_scenario_xyz"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())


class TestInvestigationEndpoint(unittest.TestCase):
    """Test Agent Investigation and deterministic Fixture Preview API contracts."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_investigate_mock_canonical_full_contract(self) -> None:
        """Fixture Preview should return the complete diagnostic response contract."""
        payload = {
            "target_metric": "sales",
            "target_date": "2026-01-31",
            "baseline_strategy": "previous_7_days",
            "scenario": "canonical",
            "mock_mode": True,
        }
        response = self.client.post("/api/investigate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # 1. Root response fields
        self.assertTrue(data["request_id"].startswith("fixture-canonical-"))
        self.assertEqual(data["mode"], "mock")
        self.assertEqual(data["target_metric"], "sales")
        self.assertEqual(data["target_date"], "2026-01-31")
        self.assertEqual(data["scenario"], "canonical")

        # 2. Diagnosis contract
        diag = data["diagnosis"]
        self.assertEqual(diag["status"], "diagnosed")
        self.assertEqual(diag["target_metric"], "sales")
        self.assertEqual(diag["primary_driver"], "conversion_rate")
        self.assertEqual(diag["affected_scope"], {"marketplace": "US"})
        self.assertGreaterEqual(diag["confidence"], 0.90)
        self.assertIsNotNone(diag["change"])
        self.assertGreaterEqual(len(diag["evidence_ids"]), 1)
        self.assertTrue(len(diag["limitations"]) > 0)
        self.assertIn("fixture preview only", diag["limitations"][0].lower())

        # 3. Evidence portfolio contract
        evidence = data["evidence"]
        self.assertGreaterEqual(len(evidence), 2)
        roles = {ev["role"] for ev in evidence}
        self.assertIn("supporting", roles)
        self.assertIn("negative_control", roles)

        portfolio_by_id = {item["evidence_id"]: item for item in evidence}
        trace_observation_ids = {
            step["observation_id"]
            for step in data["investigation_trace"]
            if step["observation_id"]
        }
        self.assertLess(len(diag["evidence_ids"]), len(evidence))
        for evidence_id in diag["evidence_ids"]:
            self.assertIn(evidence_id, portfolio_by_id)
            self.assertIn(
                portfolio_by_id[evidence_id]["observation_id"],
                trace_observation_ids,
            )

        supporting_drivers = [
            ev for ev in evidence
            if ev["role"] == "supporting" and ev["metric"] == "conversion_rate"
        ]
        self.assertEqual(len(supporting_drivers), 1)
        self.assertEqual(supporting_drivers[0]["observation_status"], "anomalous")
        self.assertLess(supporting_drivers[0]["relative_change"], 0)

        # 4. Investigation Trace contract
        trace = data["investigation_trace"]
        self.assertEqual(len(trace), 3)
        step_numbers = [step["step_number"] for step in trace]
        self.assertEqual(step_numbers, [1, 2, 3])
        tool_names = [step["tool_name"] for step in trace]
        self.assertEqual(tool_names[0], "query_metric")
        self.assertEqual(tool_names[1], "query_related_metrics")

        self.assertTrue(all("Fixture-only" in step["summary"] for step in trace))

        # 5. Budget usage
        budget = data["budget"]
        self.assertGreater(budget["tool_calls_count"], 0)
        self.assertGreater(budget["max_tool_calls"], 0)
        self.assertGreater(budget["turns_count"], 0)
        self.assertGreater(budget["max_turns"], 0)

    def test_fixture_preview_is_independent_of_selected_scenario(self) -> None:
        """Fixture Preview cannot replay a benchmark answer for the selected scenario."""
        canonical = self.client.post(
            "/api/investigate", json={"scenario": "canonical", "mock_mode": True}
        ).json()
        traffic = self.client.post(
            "/api/investigate", json={"scenario": "traffic", "mock_mode": True}
        ).json()
        self.assertEqual(canonical["scenario"], "canonical")
        self.assertEqual(traffic["scenario"], "traffic")
        self.assertEqual(canonical["diagnosis"]["primary_driver"], traffic["diagnosis"]["primary_driver"])
        self.assertEqual(canonical["diagnosis"]["affected_scope"], traffic["diagnosis"]["affected_scope"])
        self.assertEqual(
            [step["tool_name"] for step in canonical["investigation_trace"]],
            [step["tool_name"] for step in traffic["investigation_trace"]],
        )

    def test_investigate_default_parameters(self) -> None:
        """POST /api/investigate with minimal payload should use defaults."""
        payload = {"mock_mode": True}
        response = self.client.post("/api/investigate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["target_metric"], "sales")
        self.assertEqual(data["target_date"], "2026-01-31")

    def test_investigate_validation_error(self) -> None:
        """POST /api/investigate with invalid type should return 422 Unprocessable Entity."""
        payload = {"mock_mode": "not_a_boolean_or_valid"}
        response = self.client.post("/api/investigate", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_investigate_unknown_scenario_is_fail_closed(self) -> None:
        """Unknown scenario IDs must not silently use the first benchmark case."""
        response = self.client.post(
            "/api/investigate",
            json={"mock_mode": True, "scenario": "unknown-scenario"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown investigation scenario", response.json()["detail"])


class TestManualDailyScanEndpoint(unittest.TestCase):
    """Test the product-facing trigger-discovery boundary."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_scan_fails_closed_without_database_url(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            response = self.client.post("/api/scans/daily", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    @patch("app.api.service.run_manual_daily_scan")
    @patch("psycopg.connect")
    def test_scan_returns_candidates_without_a_diagnosis(
        self,
        mock_connect: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        mock_connect.return_value.__enter__.return_value = MagicMock()
        mock_scan.return_value = {
            "schema": "metricsleuth.manual_daily_scan.v1",
            "target_date": "2026-01-31",
            "comparison": "previous_7_days",
            "mode": "manual_trigger_discovery",
            "observations": [
                {
                    "metric": "sales",
                    "status": "anomalous",
                    "current_value": -12.0,
                    "baseline_value": 100.0,
                    "relative_change": -0.12,
                    "unit": "usd",
                    "sample_size": 50.0,
                    "observation_id": "daily_scan_2026-01-31_sales_0",
                }
            ],
            "anomaly_candidate_metrics": ["sales"],
            "next_step": "A caller may start an investigation.",
        }
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test/warehouse"}, clear=False):
            response = self.client.post("/api/scans/daily", json={"target_date": "2026-01-31"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "manual_trigger_discovery")
        self.assertEqual(data["anomaly_candidate_metrics"], ["sales"])
        self.assertNotIn("diagnosis", data)
        self.assertNotIn("primary_driver", data)


class TestLiveApiWiring(unittest.TestCase):
    """Test live autonomous agent investigation wiring, fail-closed behavior, and trace auditing."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_live_investigation_fail_closed_without_openai_key(self) -> None:
        """Explicit mock_mode=False without OPENAI_API_KEY must fail closed with 400."""
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            response = self.client.post("/api/investigate", json={"mock_mode": False})
            self.assertEqual(response.status_code, 400)
            self.assertIn("OPENAI_API_KEY", response.json()["detail"])

    def test_live_investigation_fail_closed_without_database_url(self) -> None:
        """Explicit mock_mode=False without DATABASE_URL must fail closed with 400."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            response = self.client.post("/api/investigate", json={"mock_mode": False})
            self.assertEqual(response.status_code, 400)
            self.assertIn("DATABASE_URL", response.json()["detail"])

    @patch("psycopg.connect")
    @patch("app.api.service.inject_scenario_data")
    @patch("app.agent_runtime.diagnosis_runtime.run_evidence_driven_diagnosis")
    def test_live_investigation_model_resolution_and_runtime_wiring(
        self,
        mock_run_diagnosis: MagicMock,
        mock_inject: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        """Verify model resolution priority and correct passing of model parameter to runtime."""
        mock_inject.return_value = ("live", "Scenario applied")
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn

        mock_summary = MagicMock()
        mock_summary.composition.diagnosis.diagnosis_id = "diag_test_01"
        mock_summary.composition.diagnosis.status.value = "diagnosed"
        mock_summary.composition.diagnosis.target_metric = "sales"
        mock_summary.composition.diagnosis.primary_driver = "orders"
        mock_summary.composition.diagnosis.affected_scope = {"marketplace": "US"}
        mock_summary.composition.diagnosis.confidence = 0.90
        mock_summary.composition.diagnosis.change = None
        mock_summary.composition.diagnosis.evidence_ids = ("evidence:runtime:selected",)
        mock_summary.composition.diagnosis.limitations = []
        mock_summary.composition.diagnosis.created_at = None
        mock_summary.composition.evidence = []
        mock_summary.investigation.observation_ids = ("call_01_obs",)
        mock_summary.investigation.tool_call_ids = ("call_01",)
        mock_summary.investigation.tools_used = ("query_metric",)
        mock_summary.investigation.tool_calls_count = 1
        mock_summary.investigation.tool_trace = (
            InvestigationToolTraceEntry(
                tool_call_id="call_01",
                tool_name="query_metric",
                arguments={"metric": "sales"},
                observation_ids=("call_01_obs",),
            ),
        )
        mock_summary.investigation.max_tool_calls = 8
        mock_summary.investigation.turns_count = 1
        mock_summary.investigation.max_turns = 6
        mock_run_diagnosis.return_value = mock_summary

        env_patch = {
            "OPENAI_API_KEY": "sk-test",
            "DATABASE_URL": "postgresql://test:5432/warehouse",
        }

        # Case 1: Explicit request model
        with patch.dict(os.environ, env_patch, clear=False):
            res = self.client.post(
                "/api/investigate",
                json={"mock_mode": False, "model": "gpt-4o"},
            )
            self.assertEqual(res.status_code, 200)
            mock_run_diagnosis.assert_called()
            self.assertEqual(mock_run_diagnosis.call_args.kwargs["model"], "gpt-4o")
            self.assertEqual(
                res.json()["diagnosis"]["evidence_ids"],
                ["evidence:runtime:selected"],
            )

        # Case 2: Environment variable fallback
        with patch.dict(
            os.environ,
            {**env_patch, "METRICSLEUTH_AGENT_MODEL": "gpt-4-turbo"},
            clear=False,
        ):
            res = self.client.post(
                "/api/investigate",
                json={"mock_mode": False},
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(mock_run_diagnosis.call_args.kwargs["model"], "gpt-4-turbo")

        # Case 3: Default fallback
        with patch.dict(os.environ, env_patch, clear=False):
            os.environ.pop("METRICSLEUTH_AGENT_MODEL", None)
            res = self.client.post(
                "/api/investigate",
                json={"mock_mode": False},
            )
            self.assertEqual(res.status_code, 200)
            self.assertEqual(mock_run_diagnosis.call_args.kwargs["model"], "gpt-4o-mini")

    @patch("psycopg.connect")
    @patch("app.api.service.inject_scenario_data")
    @patch("app.agent_runtime.diagnosis_runtime.run_evidence_driven_diagnosis")
    def test_live_investigation_real_trace_returned(
        self,
        mock_run_diagnosis: MagicMock,
        mock_inject: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        """Verify that live investigation returns the trusted Runtime tool trace."""
        mock_inject.return_value = ("live", "Scenario applied")
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn

        def fake_run(analytics_tools, **kwargs):
            summary = MagicMock()
            summary.composition.diagnosis.diagnosis_id = "diag_trace_test"
            summary.composition.diagnosis.status.value = "diagnosed"
            summary.composition.diagnosis.target_metric = "sales"
            summary.composition.diagnosis.primary_driver = "conversion_rate"
            summary.composition.diagnosis.affected_scope = {"marketplace": "US"}
            summary.composition.diagnosis.confidence = 0.92
            summary.composition.diagnosis.change = None
            summary.composition.diagnosis.evidence_ids = ("evidence:runtime:trace",)
            summary.composition.diagnosis.limitations = []
            summary.composition.diagnosis.created_at = None
            summary.composition.evidence = []
            summary.investigation.observation_ids = (
                "call_step_1_sales_0",
                "call_step_1_orders_0",
                "call_step_2_cr_0",
            )
            summary.investigation.tool_call_ids = ("call_step_1", "call_step_2")
            summary.investigation.tools_used = ("query_related_metrics", "query_metric")
            summary.investigation.tool_calls_count = 2
            summary.investigation.tool_trace = (
                InvestigationToolTraceEntry(
                    tool_call_id="call_step_1",
                    tool_name="query_related_metrics",
                    arguments={
                        "metric": "sales",
                        "start_date": "2026-01-31",
                        "end_date": "2026-01-31",
                        "compare_to": "previous_7_days",
                    },
                    observation_ids=(
                        "call_step_1_sales_0",
                        "call_step_1_orders_0",
                    ),
                ),
                InvestigationToolTraceEntry(
                    tool_call_id="call_step_2",
                    tool_name="query_metric",
                    arguments={
                        "metric": "conversion_rate",
                        "start_date": "2026-01-31",
                        "end_date": "2026-01-31",
                        "compare_to": "previous_7_days",
                        "filters": {"marketplace": "US"},
                    },
                    observation_ids=("call_step_2_cr_0",),
                ),
            )
            summary.investigation.max_tool_calls = 8
            summary.investigation.turns_count = 2
            summary.investigation.max_turns = 6
            return summary

        mock_run_diagnosis.side_effect = fake_run

        env_patch = {
            "OPENAI_API_KEY": "sk-live-test",
            "DATABASE_URL": "postgresql://test:5432/warehouse",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            response = self.client.post(
                "/api/investigate",
                json={
                    "mock_mode": False,
                    "target_metric": "sales",
                    "model": "gpt-4o",
                },
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(
                data["diagnosis"]["evidence_ids"],
                ["evidence:runtime:trace"],
            )

            trace = data["investigation_trace"]
            self.assertEqual(len(trace), 2)

            # Step 1 must be query_related_metrics with real arguments
            self.assertEqual(trace[0]["step_number"], 1)
            self.assertEqual(trace[0]["tool_name"], "query_related_metrics")
            self.assertEqual(trace[0]["tool_call_id"], "call_step_1")
            self.assertEqual(trace[0]["arguments"]["metric"], "sales")
            self.assertEqual(trace[0]["observation_id"], "call_step_1_sales_0")
            self.assertIn("call_step_1", trace[0]["observation_id"])

            # Step 2 must be query_metric for conversion_rate with real filters
            self.assertEqual(trace[1]["step_number"], 2)
            self.assertEqual(trace[1]["tool_name"], "query_metric")
            self.assertEqual(trace[1]["tool_call_id"], "call_step_2")
            self.assertEqual(trace[1]["arguments"]["metric"], "conversion_rate")
            self.assertEqual(trace[1]["arguments"]["filters"], {"marketplace": "US"})
            self.assertIn("call_step_2", trace[1]["observation_id"])

    @patch("psycopg.connect")
    @patch("app.api.service.inject_scenario_data")
    @patch("app.agent_runtime.diagnosis_runtime.run_evidence_driven_diagnosis")
    def test_live_trace_supports_definition_without_observation(
        self,
        mock_run_diagnosis: MagicMock,
        mock_inject: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        """Semantic definition calls are represented without fabricated observations."""
        mock_inject.return_value = ("live", "Scenario applied")
        mock_connect.return_value.__enter__.return_value = MagicMock()

        summary = MagicMock()
        summary.composition.diagnosis.diagnosis_id = "diag_definition_trace"
        summary.composition.diagnosis.status.value = "no_material_anomaly"
        summary.composition.diagnosis.target_metric = "sales"
        summary.composition.diagnosis.primary_driver = None
        summary.composition.diagnosis.affected_scope = {}
        summary.composition.diagnosis.confidence = 0.80
        summary.composition.diagnosis.change = None
        summary.composition.diagnosis.evidence_ids = ()
        summary.composition.diagnosis.limitations = ("Definition lookup only.",)
        summary.composition.diagnosis.created_at = None
        summary.composition.evidence = []
        summary.investigation.tool_trace = (
            InvestigationToolTraceEntry(
                tool_call_id="call_definition",
                tool_name="get_metric_definition",
                arguments={"metric": "sales"},
                observation_ids=(),
            ),
        )
        summary.investigation.tool_call_ids = ("call_definition",)
        summary.investigation.tools_used = ("get_metric_definition",)
        summary.investigation.tool_calls_count = 1
        summary.investigation.observation_ids = ()
        summary.investigation.max_tool_calls = 8
        summary.investigation.turns_count = 1
        summary.investigation.max_turns = 6
        mock_run_diagnosis.return_value = summary

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-live-test",
                "DATABASE_URL": "postgresql://test:5432/warehouse",
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/investigate",
                json={"mock_mode": False, "model": "gpt-4o"},
            )

        self.assertEqual(response.status_code, 200)
        trace = response.json()["investigation_trace"]
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["tool_name"], "get_metric_definition")
        self.assertEqual(trace[0]["tool_call_id"], "call_definition")
        self.assertEqual(trace[0]["arguments"], {"metric": "sales"})
        self.assertIsNone(trace[0]["observation_id"])
        self.assertIsNone(trace[0]["current_value"])
        self.assertIn("no Observation produced", trace[0]["summary"])

    @patch("psycopg.connect")
    @patch("app.api.service.inject_scenario_data")
    @patch("app.agent_runtime.diagnosis_runtime.run_evidence_driven_diagnosis")
    def test_live_trace_observation_identity_mismatch_fails_closed(
        self,
        mock_run_diagnosis: MagicMock,
        mock_inject: MagicMock,
        mock_connect: MagicMock,
    ) -> None:
        """An Observation not reconciled with the aggregate Runtime trace is rejected."""
        mock_inject.return_value = ("live", "Scenario applied")
        mock_connect.return_value.__enter__.return_value = MagicMock()

        summary = MagicMock()
        summary.composition.diagnosis.diagnosis_id = "diag_bad_trace"
        summary.composition.diagnosis.status.value = "no_material_anomaly"
        summary.composition.diagnosis.target_metric = "sales"
        summary.composition.diagnosis.primary_driver = None
        summary.composition.diagnosis.affected_scope = {}
        summary.composition.diagnosis.confidence = 0.80
        summary.composition.diagnosis.change = None
        summary.composition.diagnosis.evidence_ids = ()
        summary.composition.diagnosis.limitations = ("Trace mismatch.",)
        summary.composition.diagnosis.created_at = None
        summary.composition.evidence = []
        summary.investigation.tool_trace = (
            InvestigationToolTraceEntry(
                tool_call_id="call_bad",
                tool_name="query_metric",
                arguments={"metric": "sales"},
                observation_ids=("obs_not_in_summary",),
            ),
        )
        summary.investigation.tool_call_ids = ("call_bad",)
        summary.investigation.tools_used = ("query_metric",)
        summary.investigation.tool_calls_count = 1
        summary.investigation.observation_ids = ()
        summary.investigation.max_tool_calls = 8
        summary.investigation.turns_count = 1
        summary.investigation.max_turns = 6
        mock_run_diagnosis.return_value = summary

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-live-test",
                "DATABASE_URL": "postgresql://test:5432/warehouse",
            },
            clear=False,
        ):
            response = self.client.post(
                "/api/investigate",
                json={"mock_mode": False},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be reconciled", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
