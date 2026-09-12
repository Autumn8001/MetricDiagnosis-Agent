"""Unit tests for the 3-Case Live Autonomous Investigation verification script."""

from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from typing import Any

_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.api.schemas import (
    BudgetUsage,
    DiagnosisItem,
    EvidenceItem,
    InvestigationResponse,
    TraceStepItem,
)
from scripts.verify_phase6_live_investigation import (
    _build_live_artifact,
    _json_safe,
    _write_live_artifact,
    assert_scenario_results,
    run_live_investigation_api,
)


class TestLiveValidationScript(unittest.TestCase):
    """Test verification script pre-flight checks and scenario assertion engine."""

    def _build_valid_mock_results(self) -> dict[str, dict[str, Any]]:
        """Construct deterministic synthetic results meeting all 3-Case invariants."""
        return {
            "canonical": {
                "tool_calls_count": 2,
                "turns_count": 2,
                "tools_used": ["query_related_metrics", "query_metric"],
                "call_log": [
                    {
                        "operation": "query_related_metrics",
                        "kwargs": {"metric": "sales"},
                    },
                    {
                        "operation": "query_metric",
                        "kwargs": {
                            "metric": "conversion_rate",
                            "group_by": ["marketplace", "asin", "traffic_source"],
                        },
                    },
                ],
                "observation_ids": ["call_01_obs", "call_02_obs"],
                "evidence_ids": ["ev_cr_drop"],
                "evidence_list": [
                    MagicMock(
                        evidence_id="ev_cr_drop",
                        observation_id="call_02_obs",
                        metric="conversion_rate",
                        role=MagicMock(value="primary_driver"),
                    )
                ],
                "diagnosis_status": "diagnosed",
                "primary_driver": "conversion_rate",
                "affected_scope": {
                    "marketplace": "US",
                    "asin": "ASIN-A",
                    "traffic_source": "Ads",
                },
                "confidence": 0.95,
            },
            "traffic": {
                "tool_calls_count": 2,
                "turns_count": 2,
                "tools_used": ["query_related_metrics", "query_metric"],
                "call_log": [
                    {
                        "operation": "query_related_metrics",
                        "kwargs": {"metric": "sales"},
                    },
                    {
                        "operation": "query_metric",
                        "kwargs": {
                            "metric": "sessions",
                            "group_by": ["traffic_source"],
                        },
                    },
                ],
                "observation_ids": ["call_traffic_01_obs", "call_traffic_02_obs"],
                "evidence_ids": ["ev_sessions_drop"],
                "evidence_list": [
                    MagicMock(
                        evidence_id="ev_sessions_drop",
                        observation_id="call_traffic_02_obs",
                        metric="sessions",
                        role=MagicMock(value="primary_driver"),
                    )
                ],
                "diagnosis_status": "diagnosed",
                "primary_driver": "sessions",
                "affected_scope": {
                    "marketplace": "US",
                    "asin": "ASIN-A",
                    "traffic_source": "Ads",
                },
                "confidence": 0.90,
            },
            "no_anomaly": {
                "tool_calls_count": 1,
                "turns_count": 1,
                "tools_used": ["query_metric"],
                "call_log": [
                    {
                        "operation": "query_metric",
                        "kwargs": {"metric": "sales"},
                    }
                ],
                "observation_ids": ["call_normal_01_obs"],
                "evidence_ids": ["ev_normal_check"],
                "evidence_list": [
                    MagicMock(
                        evidence_id="ev_normal_check",
                        observation_id="call_normal_01_obs",
                        metric="sales",
                        role=MagicMock(value="context"),
                    )
                ],
                "diagnosis_status": "no_material_anomaly",
                "primary_driver": None,
                "affected_scope": {},
                "confidence": 0.98,
            },
        }

    def test_assert_scenario_results_passes_on_valid_three_cases(self) -> None:
        """assert_scenario_results must pass without error when all invariants hold."""
        valid_results = self._build_valid_mock_results()
        # Should execute cleanly and output pass records
        assert_scenario_results(valid_results)

    def test_assert_scenario_results_rejects_identical_call_sequences(self) -> None:
        """Dynamic branching invariant must fail if canonical and traffic traces are identical."""
        results = self._build_valid_mock_results()
        # Make traffic call_log match canonical
        results["traffic"]["call_log"] = list(results["canonical"]["call_log"])

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("Autonomous dynamic branching FAILED", str(ctx.exception))

    def test_assert_scenario_results_compares_filters_and_group_by(self) -> None:
        """Different filter/grouping choices must count as different real query branches."""
        results = self._build_valid_mock_results()
        results["traffic"]["call_log"] = [
            {
                "operation": "query_related_metrics",
                "kwargs": {"metric": "sales"},
            },
            {
                "operation": "query_metric",
                "kwargs": {
                    "metric": "conversion_rate",
                    "filters": {"marketplace": "UK"},
                    "group_by": ["traffic_source"],
                },
            },
        ]

        assert_scenario_results(results)

    def test_assert_scenario_results_rejects_missing_default_scenario(self) -> None:
        """Default complete-suite verification must fail when any scenario is absent."""
        results = self._build_valid_mock_results()
        del results["traffic"]

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("Scenario completeness FAILED", str(ctx.exception))
        self.assertIn("traffic", str(ctx.exception))

    def test_assert_scenario_results_allows_explicit_subset(self) -> None:
        """A selected CLI subset is valid only when declared as the expected set."""
        results = self._build_valid_mock_results()
        canonical_only = {"canonical": results["canonical"]}

        assert_scenario_results(canonical_only, expected_scenarios=("canonical",))

    def test_assert_scenario_results_rejects_wrong_canonical_driver(self) -> None:
        """Canonical scenario must fail if primary_driver is not conversion_rate."""
        results = self._build_valid_mock_results()
        results["canonical"]["primary_driver"] = "sessions"

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("primary_driver 'conversion_rate'", str(ctx.exception))

    def test_assert_scenario_results_rejects_wrong_traffic_driver(self) -> None:
        """Traffic scenario must fail if primary_driver is not sessions."""
        results = self._build_valid_mock_results()
        results["traffic"]["primary_driver"] = "aov"

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("primary_driver 'sessions'", str(ctx.exception))

    def test_assert_scenario_results_rejects_wrong_traffic_scope(self) -> None:
        """Traffic driver acceptance must also identify the benchmark's exact scope."""
        results = self._build_valid_mock_results()
        for dimension, wrong_value in {
            "marketplace": "UK",
            "asin": "ASIN-B",
            "traffic_source": "Organic",
        }.items():
            with self.subTest(dimension=dimension):
                results = self._build_valid_mock_results()
                results["traffic"]["affected_scope"][dimension] = wrong_value
                with self.assertRaisesRegex(AssertionError, "affected_scope"):
                    assert_scenario_results(results)

    def test_dynamic_branching_ignores_semantic_definition_calls(self) -> None:
        """Different semantic lookups alone must not masquerade as dynamic analytics branching."""
        results = self._build_valid_mock_results()
        shared_query = {
            "operation": "query_metric",
            "kwargs": {"metric": "sales", "group_by": ["marketplace"]},
        }
        results["canonical"]["call_log"] = [
            {"operation": "get_metric_definition", "kwargs": {"metric_id": "sales"}},
            shared_query,
        ]
        results["traffic"]["call_log"] = [
            {"operation": "get_metric_definition", "kwargs": {"metric_id": "sessions"}},
            dict(shared_query),
        ]
        with self.assertRaisesRegex(AssertionError, "dynamic branching FAILED"):
            assert_scenario_results(results)

    def _artifact_results(self) -> dict[str, dict[str, Any]]:
        """Build public-shaped service results without invoking a provider or database."""
        result: dict[str, dict[str, Any]] = {}
        for scenario, status, driver, scope in (
            (
                "canonical",
                "diagnosed",
                "conversion_rate",
                {"marketplace": "US", "asin": "ASIN-A", "traffic_source": "Ads"},
            ),
            (
                "traffic",
                "diagnosed",
                "sessions",
                {"marketplace": "US", "asin": "ASIN-A", "traffic_source": "Ads"},
            ),
            ("no_anomaly", "no_material_anomaly", None, {}),
        ):
            evidence_id = f"evidence:{scenario}:0:supporting"
            observation_id = f"obs:{scenario}:0"
            diagnosis = {
                "diagnosis_id": f"diag:{scenario}",
                "status": status,
                "target_metric": "sales",
                "primary_driver": driver,
                "affected_scope": scope,
                "confidence": Decimal("0.90"),
                "change": None,
                "evidence_ids": [evidence_id],
                "limitations": ["Data-level contribution only"],
                "created_at": "2026-09-12T00:00:00+00:00",
            }
            evidence = {
                "evidence_id": evidence_id,
                "observation_id": observation_id,
                "metric": driver or "sales",
                "role": "supporting",
                "observation_status": "normal" if scenario == "no_anomaly" else "anomalous",
                "current_value": Decimal("1.0"),
                "baseline_value": Decimal("1.1"),
                "relative_change": Decimal("-0.1"),
                "unit": "count",
                "sample_size": Decimal("100"),
                "dimensions": scope,
                "filters": {},
            }
            response = {
                "diagnosis": diagnosis,
                "evidence": [evidence],
                "budget": {
                    "tool_calls_count": 1,
                    "max_tool_calls": 8,
                    "turns_count": 1,
                    "max_turns": 10,
                },
            }
            result[scenario] = {
                "tool_calls_count": 1,
                "turns_count": 1,
                "tools_used": ["query_metric"],
                "call_log": [
                    {
                        "operation": "query_metric",
                        "tool_call_id": f"call:{scenario}:0",
                        "kwargs": {"metric": driver or "sales", "group_by": []},
                    }
                ],
                "observation_ids": [observation_id],
                "evidence_ids": [evidence_id],
                "evidence_list": [evidence],
                "diagnosis_status": status,
                "primary_driver": driver,
                "affected_scope": scope,
                "response": response,
            }
        return result

    def test_live_artifact_success_is_redacted_and_atomically_written(self) -> None:
        """A complete verified result set produces a readable, secret-free artifact."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "live.json"
            with patch.dict(
                os.environ,
                {"OPENAI_BASE_URL": "https://proxy.example/v1?token=must-not-leak"},
                clear=False,
            ):
                artifact = _build_live_artifact(
                    mode="service",
                    model="gpt-test-explicit",
                    scenarios=("canonical", "traffic", "no_anomaly"),
                    results=self._artifact_results(),
                )
            _write_live_artifact(target, artifact)
            loaded = json.loads(target.read_text(encoding="utf-8"))
            serialized = target.read_text(encoding="utf-8")
            self.assertEqual(loaded["overall_status"], "PASS")
            self.assertEqual(loaded["model"], "gpt-test-explicit")
            self.assertEqual(loaded["scenario_set"], ["canonical", "traffic", "no_anomaly"])
            self.assertEqual(loaded["provider_host"], "proxy.example")
            self.assertFalse(loaded["is_official_openai"])
            self.assertEqual(set(loaded["scenarios"]), set(("canonical", "traffic", "no_anomaly")))
            self.assertNotIn("must-not-leak", serialized)
            self.assertNotIn("database_url", serialized.lower())

    def test_live_artifact_rejects_incomplete_results_without_overwriting(self) -> None:
        """An incomplete/failed run must not replace an existing PASS artifact."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "live.json"
            sentinel = '{"overall_status":"PASS","sentinel":true}\n'
            target.write_text(sentinel, encoding="utf-8")
            with self.assertRaises(ValueError):
                _build_live_artifact(
                    mode="direct",
                    model="gpt-test",
                    scenarios=("canonical",),
                    results={"canonical": self._artifact_results()["canonical"]},
                )
            self.assertEqual(target.read_text(encoding="utf-8"), sentinel)

    def test_json_safe_rejects_secret_fields_and_unknown_objects(self) -> None:
        """Artifact serialization must fail closed instead of dumping arbitrary objects."""
        with self.assertRaises(ValueError):
            _json_safe({"api_key": "secret"})
        with self.assertRaises(TypeError):
            _json_safe({"value": object()})

    def test_cli_dry_run_check_never_writes_artifact(self) -> None:
        """Pre-flight checks do not create a PASS artifact, even with credentials configured."""
        script_path = _backend_root / "scripts" / "verify_phase6_live_investigation.py"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "dry-run.json"
            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "sk-mock-key-for-test"
            env["DATABASE_URL"] = "postgresql://mock:mock@localhost:5432/mockdb"
            completed = subprocess.run(
                [sys.executable, str(script_path), "--dry-run-check", "--output-json", str(target)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertFalse(target.exists())

    def test_assert_scenario_results_rejects_no_anomaly_false_positive(self) -> None:
        """No-anomaly scenario must fail if a false-positive primary_driver is reported."""
        results = self._build_valid_mock_results()
        results["no_anomaly"]["primary_driver"] = "conversion_rate"

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("must have primary_driver None", str(ctx.exception))

    def test_assert_scenario_results_rejects_no_anomaly_insufficient_evidence(self) -> None:
        """The negative control must positively establish no material anomaly."""
        results = self._build_valid_mock_results()
        results["no_anomaly"]["diagnosis_status"] = "insufficient_evidence"

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("expected status 'no_material_anomaly'", str(ctx.exception))

    def test_assert_scenario_results_rejects_budget_overrun(self) -> None:
        """Scenarios exceeding tool budget must be rejected."""
        results = self._build_valid_mock_results()
        results["canonical"]["tool_calls_count"] = 9  # exceeds default max 8

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("exceeded tool call budget", str(ctx.exception))

    def test_assert_scenario_results_rejects_citation_absent_from_portfolio(self) -> None:
        """Every diagnosis citation must identify an item in the returned portfolio."""
        results = self._build_valid_mock_results()
        results["canonical"]["evidence_ids"] = ["ev_missing"]

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("absent from its portfolio", str(ctx.exception))

    def test_assert_scenario_results_rejects_citation_from_foreign_observation(self) -> None:
        """A cited portfolio item cannot originate outside this investigation run."""
        results = self._build_valid_mock_results()
        results["canonical"]["evidence_list"][0].observation_id = "obs_from_other_run"

        with self.assertRaises(AssertionError) as ctx:
            assert_scenario_results(results)
        self.assertIn("not produced in this run", str(ctx.exception))

    def test_assert_scenario_results_allows_unreferenced_portfolio_item(self) -> None:
        """Uncited portfolio context may exist without becoming a diagnosis citation."""
        results = self._build_valid_mock_results()
        results["canonical"]["evidence_list"].append(
            MagicMock(
                evidence_id="ev_uncited_context",
                observation_id="obs_from_other_run",
            )
        )

        assert_scenario_results(results)

    @patch("app.api.service.inject_scenario_data")
    @patch("app.api.service.execute_investigation")
    def test_api_service_mode_uses_diagnosis_citations_not_entire_portfolio(
        self,
        mock_execute: MagicMock,
        mock_inject: MagicMock,
    ) -> None:
        """API service aggregation must preserve the diagnosis-selected citation set."""
        cited_id = "evidence:api:cited"
        mock_inject.return_value = ("live", "Scenario applied")
        mock_execute.return_value = InvestigationResponse(
            request_id="api-test",
            mode="live",
            target_metric="sales",
            target_date="2026-01-31",
            scenario="canonical",
            diagnosis=DiagnosisItem(
                diagnosis_id="diag-api-test",
                status="diagnosed",
                target_metric="sales",
                primary_driver="conversion_rate",
                affected_scope={
                    "marketplace": "US",
                    "asin": "ASIN-A",
                    "traffic_source": "Ads",
                },
                evidence_ids=[cited_id],
            ),
            evidence=[
                EvidenceItem(
                    evidence_id=cited_id,
                    observation_id="obs-api-cited",
                    metric="conversion_rate",
                    role="supporting",
                    observation_status="anomalous",
                    unit="ratio",
                ),
                EvidenceItem(
                    evidence_id="evidence:api:uncited",
                    observation_id="obs-from-other-run",
                    metric="sessions",
                    role="negative_control",
                    observation_status="normal",
                    unit="count",
                ),
            ],
            investigation_trace=[
                TraceStepItem(
                    step_number=1,
                    tool_name="query_metric",
                    tool_call_id="call-api-1",
                    arguments={"metric": "conversion_rate"},
                    observation_id="obs-api-cited",
                )
            ],
            budget=BudgetUsage(
                tool_calls_count=1,
                max_tool_calls=8,
                turns_count=1,
                max_turns=10,
            ),
        )

        with patch.dict(os.environ, {}, clear=False):
            results = run_live_investigation_api(
                database_url="postgresql://test/warehouse",
                api_key="test-key",
                model="test-model",
                scenarios=("canonical",),
            )

        self.assertEqual(results["canonical"]["evidence_ids"], [cited_id])
        self.assertEqual(mock_inject.call_count, 2)

    @patch("app.api.service.inject_scenario_data")
    @patch("app.api.service.execute_investigation")
    def test_api_service_mode_rejects_non_live_injection(
        self,
        mock_execute: MagicMock,
        mock_inject: MagicMock,
    ) -> None:
        """LIVE verification must not continue after a dry-run-only injection."""
        mock_inject.side_effect = [
            ("dry_run", "No warehouse write"),
            ("live", "Restore applied"),
        ]

        with self.assertRaisesRegex(RuntimeError, "not injected into the live warehouse"):
            run_live_investigation_api(
                database_url="postgresql://test/warehouse",
                api_key="test-key",
                model="test-model",
                scenarios=("canonical",),
            )

        mock_execute.assert_not_called()
        self.assertEqual(mock_inject.call_count, 2)

    def test_cli_dry_run_check_blocked_without_credentials(self) -> None:
        """Running script with --dry-run-check without keys must output BLOCKED and exit with code 2."""
        script_path = _backend_root / "scripts" / "verify_phase6_live_investigation.py"
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        env.pop("DATABASE_URL", None)

        completed = subprocess.run(
            [sys.executable, str(script_path), "--dry-run-check"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("Pre-flight Status: BLOCKED (Fail-Closed)", completed.stdout)
        self.assertIn("[MISSING]", completed.stdout)

    def test_cli_dry_run_check_ready_with_credentials(self) -> None:
        """Running script with --dry-run-check with keys configured must output READY and exit with 0."""
        script_path = _backend_root / "scripts" / "verify_phase6_live_investigation.py"
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = "sk-mock-key-for-test"
        env["DATABASE_URL"] = "postgresql://mock:mock@localhost:5432/mockdb"

        completed = subprocess.run(
            [sys.executable, str(script_path), "--dry-run-check"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Pre-flight Status: READY", completed.stdout)


if __name__ == "__main__":
    unittest.main()
