"""Hermetic tests for the Phase 6 Runtime Analytics Tool Bridge."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
from decimal import Decimal
import inspect
import json
import threading
import unittest
from unittest.mock import MagicMock

from agents import Agent
from agents.exceptions import ModelBehaviorError
from agents.tool_context import ToolContext

from app.agent_runtime.investigation_tools import (
    create_investigation_tools,
    get_metric_definition_adapter,
    observation_to_json,
    query_metric_observations_adapter,
    query_related_metrics_observations_adapter,
)
from app.agent_runtime.spike import RuntimeBudgetExceededError, ToolCallBudgetGuard
from app.analytics.models import DateRange, MetricQueryError, MetricQueryResult, MetricQueryRow, RelatedMetricQueryResult
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricDefinition


FIXED_NOW = datetime.datetime(2026, 8, 29, 12, 0, tzinfo=datetime.timezone.utc)


def metric_result(metric: str = "sales", *, rows: tuple[MetricQueryRow, ...] | None = None) -> MetricQueryResult:
    return MetricQueryResult(
        metric_id=metric,
        unit="usd" if metric == "sales" else "count",
        current_period=DateRange(datetime.date(2026, 8, 28), datetime.date(2026, 8, 28)),
        baseline_period=DateRange(datetime.date(2026, 8, 21), datetime.date(2026, 8, 27)),
        group_by=("marketplace",),
        rows=rows if rows is not None else (
            MetricQueryRow(
                dimensions={"marketplace": "US"},
                current_value=Decimal("15840.00"),
                baseline_value=Decimal("18240.00"),
                relative_change=Decimal("-0.1315789473684210526"),
                status="ok",
                sample_size=Decimal("1498.9"),
            ),
        ),
    )


class CountingAnalyticsTools:
    def __init__(self, result: MetricQueryResult) -> None:
        self.result = result
        self.calls = 0
        self.lock = threading.Lock()

    def query_metric(self, **kwargs):
        with self.lock:
            self.calls += 1
        return self.result

    def query_related_metrics(self, **kwargs):
        with self.lock:
            self.calls += 1
        return RelatedMetricQueryResult(source_metric_id=kwargs["metric"], results=(self.result,))

    def get_metric_definition(self, metric_id: str) -> MetricDefinition:
        return MetricDefinition(
            metric_id=metric_id,
            display_name=metric_id,
            description="Test-only semantic definition.",
            metric_type="additive",
            unit="count",
            formula=metric_id,
            source_fields=(metric_id,),
            dimensions=("marketplace",),
            dependencies=(),
            related_metrics=(),
            driver_metrics=(),
        )


class TestInvestigationTools(unittest.TestCase):
    def setUp(self) -> None:
        self.analytics = MagicMock(spec=AnalyticsTools)
        self.analytics.get_metric_definition.return_value = MetricDefinition(
            metric_id="sales",
            display_name="Sales",
            description="Recognized sales amount.",
            metric_type="sum",
            unit="usd",
            formula="SUM(sales_amount)",
            source_fields=("sales_amount",),
            dimensions=("marketplace", "product_id"),
            dependencies=(),
            related_metrics=("orders", "conversion_rate"),
            driver_metrics=("orders", "aov"),
        )
        self.analytics.query_metric.return_value = metric_result()
        self.analytics.query_related_metrics.return_value = RelatedMetricQueryResult(
            source_metric_id="sales",
            results=(metric_result("orders"), metric_result("sessions")),
        )

    def test_metric_definition_adapter_returns_exact_traceable_registry_envelope(self) -> None:
        guard = ToolCallBudgetGuard(max_calls=8)

        payload = get_metric_definition_adapter(
            self.analytics,
            tool_call_id="call_definition_001",
            metric=" sales ",
            budget_guard=guard,
        )

        self.analytics.get_metric_definition.assert_called_once_with("sales")
        self.assertEqual(
            set(payload),
            {"tool_name", "tool_call_id", "metric", "definition"},
        )
        self.assertEqual(payload["tool_name"], "get_metric_definition")
        self.assertEqual(payload["tool_call_id"], "call_definition_001")
        self.assertEqual(payload["metric"], "sales")
        self.assertEqual(
            set(payload["definition"]),
            {
                "metric_id",
                "display_name",
                "description",
                "metric_type",
                "unit",
                "formula",
                "source_fields",
                "dimensions",
                "dependencies",
                "driver_metrics",
                "related_metrics",
            },
        )
        self.assertEqual(payload["definition"]["source_fields"], ["sales_amount"])
        self.assertEqual(
            payload["definition"]["related_metrics"],
            ["orders", "conversion_rate"],
        )
        self.assertEqual(payload["definition"]["driver_metrics"], ["orders", "aov"])
        self.assertNotIn("sql", payload["definition"])
        self.assertNotIn("table", payload["definition"])
        self.assertEqual(guard.current_calls, 1)
        json.dumps(payload)

    def test_query_metric_adapter_forwards_parameters_and_serializes_observation(self) -> None:
        guard = ToolCallBudgetGuard(max_calls=8)
        payload = query_metric_observations_adapter(
            self.analytics,
            tool_call_id="call_metric_001",
            metric="sales",
            start_date="2026-08-28",
            end_date="2026-08-28",
            compare_to="previous_7_days",
            filters={"marketplace": "US"},
            group_by=["marketplace"],
            budget_guard=guard,
            created_at=FIXED_NOW,
        )

        self.analytics.query_metric.assert_called_once_with(
            metric="sales",
            start_date=datetime.date(2026, 8, 28),
            end_date=datetime.date(2026, 8, 28),
            compare_to="previous_7_days",
            filters={"marketplace": "US"},
            group_by=("marketplace",),
        )
        obs = payload["observations"][0]
        self.assertEqual(obs["tool_call_id"], "call_metric_001")
        self.assertEqual(obs["current_value"], "15840.00")
        self.assertEqual(obs["relative_change"], "-0.1315789473684210526")
        self.assertEqual(obs["status"], "anomalous")
        self.assertEqual(obs["created_at"], "2026-08-29T12:00:00+00:00")
        self.assertEqual(payload["metric_definitions"]["sales"]["driver_metrics"], ["orders", "aov"])
        json.dumps(payload)

    def test_strict_iso_dates_rejected_and_failed_call_consumes_budget(self) -> None:
        invalid_values = ["2026-8-28", " 2026-08-28", "2026-08-28 ", "2026-02-30", "2026-08-28T00:00:00"]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                guard = ToolCallBudgetGuard(max_calls=1)
                with self.assertRaises(ValueError):
                    query_metric_observations_adapter(
                        self.analytics,
                        tool_call_id="call_bad_date",
                        metric="sales",
                        start_date=invalid,
                        end_date="2026-08-28",
                        budget_guard=guard,
                    )
                self.assertEqual(guard.current_calls, 1)
        self.analytics.query_metric.assert_not_called()

    def test_related_metrics_flatten_order_and_unique_ids(self) -> None:
        payload = query_related_metrics_observations_adapter(
            self.analytics,
            tool_call_id="call_related_001",
            metric="sales",
            start_date="2026-08-28",
            end_date="2026-08-28",
            budget_guard=ToolCallBudgetGuard(max_calls=8),
            created_at=FIXED_NOW,
        )
        observations = payload["observations"]
        self.assertEqual([item["metric"] for item in observations], ["orders", "sessions"])
        ids = [item["observation_id"] for item in observations]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(ids[0].startswith("call_related_001_rel0_"))
        self.assertTrue(ids[1].startswith("call_related_001_rel1_"))
        self.assertEqual(
            set(payload["metric_definitions"]),
            {"sales", "orders", "sessions"},
        )
        json.dumps(payload)

    def test_empty_result_returns_empty_observations(self) -> None:
        self.analytics.query_metric.return_value = metric_result(rows=())
        payload = query_metric_observations_adapter(
            self.analytics,
            tool_call_id="call_empty",
            metric="sales",
            start_date="2026-08-28",
            end_date="2026-08-28",
            budget_guard=ToolCallBudgetGuard(max_calls=8),
            created_at=FIXED_NOW,
        )
        self.assertEqual(payload["observations"], [])

    def test_analytics_error_propagates_and_consumes_budget(self) -> None:
        self.analytics.query_metric.side_effect = MetricQueryError("bad dimension")
        guard = ToolCallBudgetGuard(max_calls=8)
        with self.assertRaisesRegex(MetricQueryError, "bad dimension"):
            query_metric_observations_adapter(
                self.analytics,
                tool_call_id="call_failure",
                metric="sales",
                start_date="2026-08-28",
                end_date="2026-08-28",
                budget_guard=guard,
            )
        self.assertEqual(guard.current_calls, 1)

    def test_sdk_tools_share_budget_and_ninth_call_fails_before_analytics(self) -> None:
        guard = ToolCallBudgetGuard(max_calls=8)
        definition_tool, query_tool, related_tool = create_investigation_tools(
            self.analytics,
            budget_guard=guard,
            clock=lambda: FIXED_NOW,
        )
        agent = Agent(name="TestInvestigationAgent")
        query_arguments = json.dumps({
            "metric": "sales",
            "start_date": "2026-08-28",
            "end_date": "2026-08-28",
        })
        definition_arguments = json.dumps({"metric": "sales"})
        tools = (definition_tool, query_tool, related_tool)
        for index in range(8):
            tool = tools[index % len(tools)]
            arguments = (
                definition_arguments
                if tool is definition_tool
                else query_arguments
            )
            context = ToolContext(
                context=None,
                agent=agent,
                tool_call_id=f"call_{index}",
                tool_name=tool.name,
                tool_arguments=arguments,
            )
            output = asyncio.run(tool.on_invoke_tool(context, arguments))
            self.assertEqual(output["tool_call_id"], f"call_{index}")

        context = ToolContext(
            context=None,
            agent=agent,
            tool_call_id="call_9",
            tool_name=query_tool.name,
            tool_arguments=query_arguments,
        )
        with self.assertRaises(RuntimeBudgetExceededError):
            asyncio.run(query_tool.on_invoke_tool(context, query_arguments))
        # Query tools executed five times (three registry-definition tool calls
        # account for the rest of the shared eight-call budget).  Query-result
        # envelopes may read semantic definitions internally without consuming
        # model-facing query budget.
        self.assertEqual(
            self.analytics.query_metric.call_count
            + self.analytics.query_related_metrics.call_count,
            5,
        )

    def test_sdk_schema_hides_context_and_clock(self) -> None:
        definition_tool, query_tool, related_tool = create_investigation_tools(
            self.analytics,
            clock=lambda: FIXED_NOW,
        )
        for tool in (definition_tool, query_tool, related_tool):
            properties = tool.params_json_schema["properties"]
            self.assertNotIn("context", properties)
            self.assertNotIn("created_at", properties)
            self.assertIn("metric", properties)
        self.assertEqual(
            set(definition_tool.params_json_schema["properties"]),
            {"metric"},
        )
        for tool in (query_tool, related_tool):
            properties = tool.params_json_schema["properties"]
            self.assertIn("start_date", properties)
            self.assertIn("filters", properties)

    def test_sdk_filter_schema_exposes_string_map_and_rejects_array_shape(self) -> None:
        _, query_tool, related_tool = create_investigation_tools(
            self.analytics,
            clock=lambda: FIXED_NOW,
        )

        for tool in (query_tool, related_tool):
            with self.subTest(tool=tool.name):
                filters_schema = tool.params_json_schema["properties"]["filters"]
                description = filters_schema["description"]
                self.assertIn('{"marketplace": "US"}', description)
                self.assertIn("object/map", description)
                self.assertIn("[{\"dimension\": \"marketplace\", \"value\": \"US\"}]", description)
                self.assertIn('["marketplace", "US"]', description)

                map_schema = next(
                    item
                    for item in filters_schema["anyOf"]
                    if item.get("type") == "object"
                )
                self.assertEqual(map_schema["type"], "object")
                self.assertEqual(map_schema["additionalProperties"], {"type": "string"})
                self.assertNotIn("$defs", tool.params_json_schema)

    def test_sdk_structured_filters_reach_analytics_mapping(self) -> None:
        _, query_tool, _ = create_investigation_tools(
            self.analytics,
            clock=lambda: FIXED_NOW,
        )
        arguments = json.dumps({
            "metric": "sales",
            "start_date": "2026-08-28",
            "end_date": "2026-08-28",
            "filters": {"marketplace": "US"},
            "group_by": ["marketplace"],
        })
        context = ToolContext(
            context=None,
            agent=Agent(name="FilterBridgeAgent"),
            tool_call_id="call_filter_001",
            tool_name=query_tool.name,
            tool_arguments=arguments,
        )

        output = asyncio.run(query_tool.on_invoke_tool(context, arguments))

        self.assertEqual(output["observations"][0]["filters"], {"marketplace": "US"})
        self.assertEqual(
            self.analytics.query_metric.call_args.kwargs["filters"],
            {"marketplace": "US"},
        )

    def test_sdk_filter_input_rejects_arrays_and_json_strings(self) -> None:
        _, query_tool, _ = create_investigation_tools(
            self.analytics,
            clock=lambda: FIXED_NOW,
        )
        base_arguments = {
            "metric": "sales",
            "start_date": "2026-08-28",
            "end_date": "2026-08-28",
        }
        invalid_filters = [
            ["marketplace", "US"],
            [{"dimension": "marketplace", "value": "US"}],
            '{"marketplace": "US"}',
        ]

        for invalid in invalid_filters:
            with self.subTest(invalid=invalid):
                arguments = json.dumps({**base_arguments, "filters": invalid})
                context = ToolContext(
                    context=None,
                    agent=Agent(name="InvalidFilterBridgeAgent"),
                    tool_call_id="call_invalid_filter",
                    tool_name=query_tool.name,
                    tool_arguments=arguments,
                )
                with self.assertRaises(ModelBehaviorError):
                    asyncio.run(query_tool.on_invoke_tool(context, arguments))

        self.analytics.query_metric.assert_not_called()

    def test_concurrent_budget_never_exceeds_underlying_execution_limit(self) -> None:
        analytics = CountingAnalyticsTools(metric_result())
        guard = ToolCallBudgetGuard(max_calls=8)

        def invoke(index: int) -> str:
            try:
                query_metric_observations_adapter(
                    analytics,
                    tool_call_id=f"concurrent_{index}",
                    metric="sales",
                    start_date="2026-08-28",
                    end_date="2026-08-28",
                    budget_guard=guard,
                    created_at=FIXED_NOW,
                )
                return "ok"
            except RuntimeBudgetExceededError:
                return "blocked"

        with ThreadPoolExecutor(max_workers=16) as pool:
            outcomes = list(pool.map(invoke, range(24)))
        self.assertEqual(outcomes.count("ok"), 8)
        self.assertEqual(outcomes.count("blocked"), 16)
        self.assertEqual(analytics.calls, 8)

    def test_observation_serializer_rejects_wrong_type(self) -> None:
        with self.assertRaises(TypeError):
            observation_to_json(object())

    def test_production_module_does_not_reference_ground_truth(self) -> None:
        source = inspect.getsource(__import__("app.agent_runtime.investigation_tools", fromlist=["*"]))
        forbidden = "ground" + "_truth"
        self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main()
