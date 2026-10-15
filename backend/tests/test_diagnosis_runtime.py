"""Hermetic SDK Runner tests for Evidence-driven Diagnosis integration."""

import datetime
from decimal import Decimal
import json
from unittest.mock import MagicMock, patch
import unittest

from agents import Agent, MessageOutputItem, RunConfig, RunResult, ToolCallItem, ToolCallOutputItem
from agents.testing import ScriptedModel, assistant_message, function_call
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall

from app.agent_runtime import (
    EvidenceDrivenRunSummary,
    RuntimeDiagnosisIntent,
    create_evidence_driven_agent,
    run_evidence_driven_diagnosis,
)
from app.agent_runtime.investigation_tools import observation_to_json
from app.agent_runtime.spike import RuntimeTraceError
from app.analytics.models import DateRange, MetricQueryResult, MetricQueryRow, RelatedMetricQueryResult
from app.analytics.tools import AnalyticsTools
from app.diagnosis import DiagnosisStatus, DiagnosisValidationError
from app.evidence import EvidenceValidationError
from app.metrics.registry import MetricDefinition
from app.observations.mapper import observations_from_tool_result


FIXED_NOW = datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.timezone.utc)
CURRENT_PERIOD = DateRange(datetime.date(2026, 8, 28), datetime.date(2026, 8, 28))
BASELINE_PERIOD = DateRange(datetime.date(2026, 8, 21), datetime.date(2026, 8, 27))


def metric_result(
    metric: str,
    relative_change: str,
    *,
    current: str = "90",
    baseline: str = "100",
) -> MetricQueryResult:
    return MetricQueryResult(
        metric_id=metric,
        unit="ratio" if metric == "conversion_rate" else "count",
        current_period=CURRENT_PERIOD,
        baseline_period=BASELINE_PERIOD,
        group_by=(),
        rows=(
            MetricQueryRow(
                dimensions={},
                current_value=Decimal(current),
                baseline_value=Decimal(baseline),
                relative_change=Decimal(relative_change),
                status="ok",
                sample_size=Decimal("100"),
            ),
        ),
    )


def diagnosed_intent_payload() -> dict:
    return {
        "evidence_selections": [
            {"observation_id": "target_call_sales_0", "role": "supporting"},
            {"observation_id": "driver_call_conversion_rate_0", "role": "supporting"},
            {"observation_id": "control_call_sessions_0", "role": "negative_control"},
        ],
        "status": "diagnosed",
        "target_metric": "sales",
        "target_evidence_id": "evidence:target_call_sales_0:supporting",
        "driver_evidence_id": "evidence:driver_call_conversion_rate_0:supporting",
        "primary_driver": "conversion_rate",
        "affected_scope": [{"dimension": "marketplace", "value": "US"}],
        "evidence_ids": [
            "evidence:target_call_sales_0:supporting",
            "evidence:driver_call_conversion_rate_0:supporting",
            "evidence:control_call_sessions_0:negative_control",
        ],
        "confidence": "0.90",
        "limitations": ["Data contribution only; external cause is unproven."],
    }


def no_anomaly_intent_payload() -> dict:
    return {
        "evidence_selections": [
            {"observation_id": "related_call_rel0_orders_0", "role": "supporting"},
            {"observation_id": "related_call_rel1_conversion_rate_0", "role": "negative_control"},
        ],
        "status": "no_material_anomaly",
        "target_metric": "orders",
        "target_evidence_id": "evidence:related_call_rel0_orders_0:supporting",
        "driver_evidence_id": None,
        "primary_driver": None,
        "affected_scope": [],
        "evidence_ids": [
            "evidence:related_call_rel0_orders_0:supporting",
            "evidence:related_call_rel1_conversion_rate_0:negative_control",
        ],
        "confidence": "0.80",
        "limitations": ["The inspected period showed no material decline."],
    }


class TestEvidenceDrivenDiagnosisRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.analytics = MagicMock(spec=AnalyticsTools)

        def metric_definition(metric_id: str) -> MetricDefinition:
            return MetricDefinition(
                metric_id=metric_id,
                display_name=metric_id.replace("_", " ").title(),
                description="Test-only semantic definition.",
                metric_type="ratio" if metric_id == "conversion_rate" else "additive",
                unit="ratio" if metric_id == "conversion_rate" else "count",
                formula=metric_id,
                source_fields=(metric_id,),
                dimensions=("marketplace",),
                dependencies=(),
                related_metrics=(),
                driver_metrics={
                    "sales": ("orders", "aov"),
                    "orders": ("sessions", "conversion_rate"),
                }.get(metric_id, ()),
            )

        self.analytics.get_metric_definition.side_effect = metric_definition

        def query_metric(*, metric: str, **kwargs):
            values = {
                "sales": metric_result("sales", "-0.20", current="80"),
                "conversion_rate": metric_result("conversion_rate", "-0.30"),
                "sessions": metric_result("sessions", "0.01"),
            }
            return values[metric]

        self.analytics.query_metric.side_effect = query_metric
        self.analytics.query_related_metrics.return_value = RelatedMetricQueryResult(
            source_metric_id="sales",
            results=(
                metric_result("orders", "0.01"),
                metric_result("conversion_rate", "0.02"),
            ),
        )

    def _run_config(self) -> RunConfig:
        return RunConfig(tracing_disabled=True)

    def _diagnosed_model(self, payload: dict | None = None) -> ScriptedModel:
        return ScriptedModel(
            [
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "sales",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "US"},
                        },
                        call_id="target_call",
                    )
                ],
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "conversion_rate",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "US"},
                        },
                        call_id="driver_call",
                    )
                ],
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "sessions",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "DE"},
                        },
                        call_id="control_call",
                    )
                ],
                [assistant_message(json.dumps(payload or diagnosed_intent_payload()))],
            ]
        )

    def _no_anomaly_model(self, payload: dict | None = None) -> ScriptedModel:
        return ScriptedModel(
            [
                [
                    function_call(
                        "query_related_metrics",
                        {
                            "metric": "sales",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "US"},
                        },
                        call_id="related_call",
                    )
                ],
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "sessions",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "DE"},
                        },
                        call_id="unused_call",
                    )
                ],
                [assistant_message(json.dumps(payload or no_anomaly_intent_payload()))],
            ]
        )

    def test_diagnosed_run_uses_real_tools_and_resolves_structured_diagnosis(self) -> None:
        model = self._diagnosed_model()
        summary = run_evidence_driven_diagnosis(
            "Investigate the sales change for 2026-08-28.",
            diagnosis_id="diag-diagnosed",
            analytics_tools=self.analytics,
            model=model,
            run_config=self._run_config(),
            created_at=FIXED_NOW,
        )

        self.assertIsInstance(summary, EvidenceDrivenRunSummary)
        self.assertEqual(summary.investigation.tools_used, ("query_metric", "query_metric", "query_metric"))
        self.assertEqual(summary.investigation.tool_call_ids, ("target_call", "driver_call", "control_call"))
        self.assertEqual(summary.investigation.observation_count, 3)
        self.assertEqual(summary.composition.diagnosis.status, DiagnosisStatus.DIAGNOSED)
        self.assertEqual(summary.composition.diagnosis.change.current_value, Decimal("80"))
        self.assertEqual(summary.composition.diagnosis.change.baseline_value, Decimal("100"))
        self.assertEqual(dict(summary.composition.diagnosis.affected_scope), {"marketplace": "US"})
        self.assertEqual(summary.composition.diagnosis.created_at, FIXED_NOW)
        self.assertEqual(
            RuntimeDiagnosisIntent.model_validate_json(
                summary.investigation.final_output
            ).status,
            DiagnosisStatus.DIAGNOSED,
        )
        self.assertEqual(self.analytics.query_metric.call_count, 3)
        model.assert_complete()

    def test_no_anomaly_run_allows_different_tool_order(self) -> None:
        model = self._no_anomaly_model()
        summary = run_evidence_driven_diagnosis(
            "Check whether orders have a material change.",
            diagnosis_id="diag-no-anomaly",
            analytics_tools=self.analytics,
            model=model,
            run_config=self._run_config(),
            created_at=FIXED_NOW,
        )

        self.assertEqual(summary.investigation.tools_used, ("query_related_metrics", "query_metric"))
        self.assertEqual(summary.investigation.observation_count, 3)
        self.assertEqual(summary.composition.diagnosis.status, DiagnosisStatus.NO_MATERIAL_ANOMALY)
        self.assertEqual(summary.composition.diagnosis.change.current_value, Decimal("90"))
        self.assertEqual(
            tuple(item.evidence_id for item in summary.composition.evidence),
            (
                "evidence:related_call_rel0_orders_0:supporting",
                "evidence:related_call_rel1_conversion_rate_0:negative_control",
            ),
        )
        model.assert_complete()

    def test_each_run_gets_an_independent_budget_guard(self) -> None:
        def one_run_model(call_id: str) -> ScriptedModel:
            payload = no_anomaly_intent_payload()
            payload["evidence_selections"] = [
                {"observation_id": f"{call_id}_sales_0", "role": "supporting"}
            ]
            payload["target_metric"] = "sales"
            payload["target_evidence_id"] = f"evidence:{call_id}_sales_0:supporting"
            payload["driver_evidence_id"] = None
            payload["evidence_ids"] = [f"evidence:{call_id}_sales_0:supporting"]
            return ScriptedModel(
                [
                    [
                        function_call(
                            "query_metric",
                            {
                                "metric": "sales",
                                "start_date": "2026-08-28",
                                "end_date": "2026-08-28",
                            },
                            call_id=call_id,
                        )
                    ],
                    [assistant_message(json.dumps(payload))],
                ]
            )

        self.analytics.query_metric.side_effect = lambda *, metric, **kwargs: metric_result(
            metric, "0.01"
        )
        first = run_evidence_driven_diagnosis(
            "Check sales.",
            diagnosis_id="diag-one",
            analytics_tools=self.analytics,
            model=one_run_model("first_call"),
            max_tool_calls=1,
            run_config=self._run_config(),
            created_at=FIXED_NOW,
        )
        second = run_evidence_driven_diagnosis(
            "Check sales again.",
            diagnosis_id="diag-two",
            analytics_tools=self.analytics,
            model=one_run_model("second_call"),
            max_tool_calls=1,
            run_config=self._run_config(),
            created_at=FIXED_NOW,
        )
        self.assertEqual(first.investigation.tool_calls_count, 1)
        self.assertEqual(second.investigation.tool_calls_count, 1)
        self.assertEqual(self.analytics.query_metric.call_count, 2)

    def test_invalid_arguments_and_summary_types_fail_fast(self) -> None:
        for field, value in (
            ("prompt", ""),
            ("prompt", "   "),
            ("diagnosis_id", ""),
            ("diagnosis_id", "   "),
            ("max_tool_calls", 0),
            ("max_tool_calls", True),
            ("max_turns", -1),
        ):
            call_kwargs = {}
            if field == "prompt":
                prompt = value
                diagnosis_id = "diag"
            elif field == "diagnosis_id":
                prompt = "go"
                diagnosis_id = value
            else:
                prompt = "go"
                diagnosis_id = "diag"
                call_kwargs[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                run_evidence_driven_diagnosis(
                    prompt,
                    diagnosis_id=diagnosis_id,
                    analytics_tools=self.analytics,
                    model=MagicMock(),
                    **call_kwargs,
                )

        with self.assertRaises(RuntimeTraceError):
            EvidenceDrivenRunSummary(investigation=object(), composition=object())

    def test_agent_uses_structured_fact_free_output_without_fixed_path(self) -> None:
        guard = MagicMock()
        agent = create_evidence_driven_agent(self.analytics, model=None, budget_guard=guard)
        self.assertIs(agent.output_type, RuntimeDiagnosisIntent)
        self.assertIn("copy every supplied filter key and exact value", agent.instructions)
        self.assertIn("Never omit a task-bound filter", agent.instructions)
        self.assertEqual(len(agent.tools), 3)
        self.assertEqual(
            {tool.name for tool in agent.tools},
            {
                "get_metric_definition",
                "query_metric",
                "query_related_metrics",
            },
        )
        self.assertIn("When semantic meaning is needed", agent.instructions)
        self.assertIn("do not invent metric formulas", agent.instructions)
        self.assertIn("Observation IDs", agent.instructions)
        self.assertIn("copy every observation_id character-for-character", agent.instructions)
        self.assertIn("same selected anomalous supporting Observation", agent.instructions)
        self.assertIn("primary_driver is always a metric identifier", agent.instructions)
        self.assertIn("related metrics to identify the primary driver", agent.instructions)
        self.assertIn("hard maximum of eight analytics tool calls", agent.instructions)
        self.assertIn("Avoid duplicate evidence", agent.instructions)
        self.assertIn("reserve individual metric queries", agent.instructions)
        self.assertIn("do not use the target metric itself", agent.instructions)
        self.assertIn("metric equal to primary_driver", agent.instructions)
        self.assertIn("Do not splice primary_driver", agent.instructions)
        self.assertIn("cross-check every observation_id and Evidence ID", agent.instructions)
        self.assertIn("evidence:{observation_id}:{role}", agent.instructions)
        self.assertIn("driver_metrics in a definition", agent.instructions)
        self.assertIn("fixed drill-down sequence", agent.instructions)
        self.assertNotIn("root_cause", RuntimeDiagnosisIntent.model_fields)

    def test_non_intent_final_output_is_rejected_after_trace_audit(self) -> None:
        source_observation = observations_from_tool_result(
            metric_result("sales", "-0.20"),
            tool_name="query_metric",
            tool_call_id="fake_call",
            filters={"marketplace": "US"},
            query_or_result_reference="tool-result:fake_call",
            created_at=FIXED_NOW,
        )[0]
        payload = {
            "tool_name": "query_metric",
            "tool_call_id": "fake_call",
            "metric": "sales",
            "observations": [observation_to_json(source_observation)],
        }
        agent = Agent(name="trace-test")
        raw_call = ResponseFunctionToolCall(
            id="item_fake_call",
            call_id="fake_call",
            name="query_metric",
            arguments="{}",
            type="function_call",
        )
        call = ToolCallItem(agent=agent, raw_item=raw_call)
        output = ToolCallOutputItem(
            agent=agent,
            raw_item={"call_id": "fake_call", "output": payload},
            output=payload,
        )
        message = MessageOutputItem(agent=agent, raw_item=MagicMock(), type="message_output_item")
        fake_result = MagicMock(spec=RunResult)
        fake_result.new_items = [call, output, message]
        fake_result.raw_responses = [MagicMock()]
        fake_result.final_output = "not a RuntimeDiagnosisIntent"

        with patch("app.agent_runtime.diagnosis_runtime.Runner.run_sync", return_value=fake_result):
            with self.assertRaisesRegex(RuntimeTraceError, "RuntimeDiagnosisIntent"):
                run_evidence_driven_diagnosis(
                    "go",
                    diagnosis_id="diag-invalid-output",
                    analytics_tools=self.analytics,
                    model=None,
                    run_config=self._run_config(),
                )

    def test_unknown_observation_and_missing_negative_control_fail_closed(self) -> None:
        unknown_payload = diagnosed_intent_payload()
        unknown_payload["evidence_selections"][0]["observation_id"] = "forged-from-message"
        unknown = self._diagnosed_model(unknown_payload)
        with self.assertRaises(EvidenceValidationError):
            run_evidence_driven_diagnosis(
                "go",
                diagnosis_id="diag-unknown-observation",
                analytics_tools=self.analytics,
                model=unknown,
                run_config=self._run_config(),
            )

        missing_control_payload = diagnosed_intent_payload()
        missing_control_payload["evidence_selections"] = missing_control_payload["evidence_selections"][:2]
        missing_control_payload["evidence_ids"] = missing_control_payload["evidence_ids"][:2]
        missing_model = self._diagnosed_model(missing_control_payload)
        with self.assertRaises(DiagnosisValidationError):
            run_evidence_driven_diagnosis(
                "go",
                diagnosis_id="diag-missing-control",
                analytics_tools=self.analytics,
                model=missing_model,
                run_config=self._run_config(),
            )

    def test_intermediate_primary_driver_with_anomalous_direct_driver_is_rejected(self) -> None:
        payload = diagnosed_intent_payload()
        payload["evidence_selections"][1]["observation_id"] = "driver_call_orders_0"
        payload["primary_driver"] = "orders"
        payload["driver_evidence_id"] = "evidence:driver_call_orders_0:supporting"
        payload["evidence_ids"][1] = "evidence:driver_call_orders_0:supporting"

        model = ScriptedModel(
            [
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "sales",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "US"},
                        },
                        call_id="target_call",
                    )
                ],
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "orders",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "US"},
                        },
                        call_id="driver_call",
                    )
                ],
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "conversion_rate",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "US"},
                        },
                        call_id="control_call",
                    )
                ],
                [
                    function_call(
                        "query_metric",
                        {
                            "metric": "sessions",
                            "start_date": "2026-08-28",
                            "end_date": "2026-08-28",
                            "filters": {"marketplace": "DE"},
                        },
                        call_id="sessions_call",
                    )
                ],
                [assistant_message(json.dumps(payload))],
            ]
        )
        self.analytics.query_metric.side_effect = lambda *, metric, **kwargs: {
            "sales": metric_result("sales", "-0.20", current="80"),
            "orders": metric_result("orders", "-0.20", current="80"),
            "conversion_rate": metric_result("conversion_rate", "-0.30"),
            "sessions": metric_result("sessions", "0.01"),
        }[metric]

        with self.assertRaisesRegex(RuntimeTraceError, "intermediate metric.*conversion_rate"):
            run_evidence_driven_diagnosis(
                "Investigate sales.",
                diagnosis_id="diag-intermediate-driver",
                analytics_tools=self.analytics,
                model=model,
                run_config=self._run_config(),
                created_at=FIXED_NOW,
            )
        model.assert_complete()


if __name__ == "__main__":
    unittest.main()
