"""Hermetic unit tests for OpenAI Agents SDK runtime spike module."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from agents import Agent, MessageOutputItem, RunResult, ToolCallItem, ToolCallOutputItem
from agents.tool_context import ToolContext
from app.agent_runtime.spike import (
    RuntimeBudgetExceededError,
    RuntimeConfigError,
    RuntimeSpikeError,
    RuntimeSpikeOutput,
    RuntimeTraceError,
    RuntimeValidationError,
    ToolCallBudgetGuard,
    _validate_positive_int,
    create_get_metric_definition_tool,
    cross_validate_structured_output,
    get_metric_definition_adapter,
    run_runtime_spike,
    verify_runtime_trace_and_budget,
)
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricDefinition, MetricRegistry
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall


class TestRuntimeSpike(unittest.TestCase):
    """Hermetic test suite for runtime spike components without live OpenAI API calls."""

    def setUp(self) -> None:
        self.mock_sales_def = MetricDefinition(
            metric_id="sales",
            display_name="Sales Revenue",
            description="Total gross sales revenue",
            metric_type="additive",
            unit="usd",
            formula="SUM(ordered_product_sales)",
            source_fields=("ordered_product_sales",),
            dimensions=("marketplace", "asin", "traffic_channel"),
            dependencies=(),
            related_metrics=("orders", "sessions", "conversion_rate", "aov"),
        )
        self.mock_registry = MagicMock(spec=MetricRegistry)
        self.mock_registry.get.return_value = self.mock_sales_def
        self.analytics_tools = AnalyticsTools(registry=self.mock_registry, connection=None)
        self.agent = Agent(name="TestAgent")

    def test_tool_adapter_delegates_to_analytics_tools(self) -> None:
        """Verify the adapter directly delegates to AnalyticsTools.get_metric_definition."""
        data = get_metric_definition_adapter(self.analytics_tools, "sales")

        self.mock_registry.get.assert_called_once_with("sales")
        self.assertEqual(data["metric_id"], "sales")
        self.assertEqual(data["unit"], "usd")
        self.assertEqual(data["metric_type"], "additive")
        self.assertEqual(data["display_name"], "Sales Revenue")

    def test_pre_execution_budget_blocks_second_tool_call(self) -> None:
        """Verify the pre-execution budget guard blocks second call before AnalyticsTools is invoked."""
        guard = ToolCallBudgetGuard(max_calls=1)

        # First call succeeds
        res1 = get_metric_definition_adapter(self.analytics_tools, "sales", budget_guard=guard)
        self.assertEqual(res1["metric_id"], "sales")
        self.assertEqual(self.mock_registry.get.call_count, 1)

        # Second call is blocked before touching AnalyticsTools
        with self.assertRaises(RuntimeBudgetExceededError) as ctx:
            get_metric_definition_adapter(self.analytics_tools, "sales", budget_guard=guard)

        self.assertIn("Tool call budget exceeded", str(ctx.exception))
        # Ensure underlying AnalyticsTools / Registry was NOT called a second time
        self.assertEqual(self.mock_registry.get.call_count, 1)

    def test_pre_execution_budget_concurrent_thread_safety(self) -> None:
        """Verify atomic check-and-consume is thread-safe under concurrent invocations."""
        guard = ToolCallBudgetGuard(max_calls=1)
        successes = []
        errors = []

        def worker() -> None:
            try:
                res = get_metric_definition_adapter(self.analytics_tools, "sales", budget_guard=guard)
                successes.append(res)
            except RuntimeBudgetExceededError as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker) for _ in range(8)]
            for f in futures:
                f.result()

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 7)
        self.assertEqual(self.mock_registry.get.call_count, 1)

    def test_pre_execution_budget_isolated_per_run(self) -> None:
        """Verify separate runtime executions do not share consumed budget."""
        first_run_guard = ToolCallBudgetGuard(max_calls=1)
        second_run_guard = ToolCallBudgetGuard(max_calls=1)

        get_metric_definition_adapter(self.analytics_tools, "sales", budget_guard=first_run_guard)
        get_metric_definition_adapter(self.analytics_tools, "sales", budget_guard=second_run_guard)

        self.assertEqual(first_run_guard.current_calls, 1)
        self.assertEqual(second_run_guard.current_calls, 1)
        self.assertEqual(self.mock_registry.get.call_count, 2)

    def test_function_tool_creation_and_fail_closed_error_config(self) -> None:
        """Verify a second SDK FunctionTool invocation propagates the budget error."""
        guard = ToolCallBudgetGuard(max_calls=1)
        tool = create_get_metric_definition_tool(self.analytics_tools, budget_guard=guard)
        self.assertEqual(tool.name, "get_metric_definition")
        self.assertIn("metric_id", tool.params_json_schema["properties"])
        self.assertIn("metric_id", tool.params_json_schema["required"])

        context = ToolContext(
            context=None,
            agent=self.agent,
            tool_call_id="call_budget_001",
            tool_name=tool.name,
            tool_arguments='{"metric_id": "sales"}',
        )

        first_output = asyncio.run(
            tool.on_invoke_tool(context, '{"metric_id": "sales"}')
        )
        self.assertIsInstance(first_output, dict)
        self.assertEqual(first_output["metric_id"], "sales")

        with self.assertRaises(RuntimeBudgetExceededError):
            asyncio.run(tool.on_invoke_tool(context, '{"metric_id": "sales"}'))

        self.assertEqual(self.mock_registry.get.call_count, 1)

    def test_tool_output_is_json_serializable(self) -> None:
        """Verify the tool returned dictionary is strictly JSON serializable."""
        data = get_metric_definition_adapter(self.analytics_tools, "sales")
        serialized = json.dumps(data)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["metric_id"], "sales")
        self.assertEqual(deserialized["unit"], "usd")
        self.assertIsInstance(deserialized["dimensions"], list)
        self.assertIsInstance(deserialized["related_metrics"], list)

    def test_structured_output_model_validation(self) -> None:
        """Verify RuntimeSpikeOutput validates fields and rejects empty values."""
        valid = RuntimeSpikeOutput(
            metric_id="sales",
            unit="usd",
            tool_used="get_metric_definition",
            summary="Sales metric is total gross revenue in USD.",
        )
        self.assertEqual(valid.metric_id, "sales")
        self.assertEqual(valid.unit, "usd")

        # Test empty or whitespace fields
        for field in ["metric_id", "unit", "tool_used", "summary"]:
            with self.subTest(field=field):
                invalid_kwargs = {
                    "metric_id": "sales",
                    "unit": "usd",
                    "tool_used": "get_metric_definition",
                    "summary": "Some summary",
                }
                invalid_kwargs[field] = "   "
                with self.assertRaises(ValidationError):
                    RuntimeSpikeOutput(**invalid_kwargs)

    def test_invalid_budget_and_turn_arguments_rejected(self) -> None:
        """Verify _validate_positive_int strictly rejects invalid inputs like booleans, 0, floats, strings."""
        for invalid in [True, False, 0, -1, -5, "1", 1.5, None, []]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _validate_positive_int(invalid, "test_param")

    def test_missing_env_vars_fail_fast_before_network(self) -> None:
        """Verify run_runtime_spike fails fast when required environment variables are missing."""
        # 1. Missing METRICSLEUTH_AGENT_MODEL
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeConfigError) as ctx:
                run_runtime_spike()
            self.assertIn("METRICSLEUTH_AGENT_MODEL", str(ctx.exception))

        # 2. Missing OPENAI_API_KEY
        with patch.dict(os.environ, {"METRICSLEUTH_AGENT_MODEL": "gpt-4o-mini"}, clear=True):
            with self.assertRaises(RuntimeConfigError) as ctx:
                run_runtime_spike()
            self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_runtime_spike_rejects_widened_tool_budget_before_env_checks(self) -> None:
        """The public runtime entry point cannot widen the fixed one-call spike budget."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                run_runtime_spike(max_tool_calls=2)

        self.assertIn("requires max_tool_calls=1", str(ctx.exception))

    def _create_mock_run_result(
        self,
        new_items: list,
        turns_count: int = 2,
    ) -> RunResult:
        mock_result = MagicMock(spec=RunResult)
        mock_result.new_items = new_items
        mock_result.raw_responses = [MagicMock() for _ in range(turns_count)]
        return mock_result

    def test_trace_verification_success_path(self) -> None:
        """Verify trace extraction correctly maps prompt message -> tool call -> tool output -> final message."""
        raw_call = ResponseFunctionToolCall(
            id="item_001",
            call_id="call_001",
            name="get_metric_definition",
            arguments='{"metric_id": "sales"}',
            type="function_call",
        )
        item0 = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")
        item1 = ToolCallItem(agent=self.agent, raw_item=raw_call)
        item2 = ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": "call_001", "output": '{"metric_id": "sales", "unit": "usd"}'},
            output={"metric_id": "sales", "unit": "usd"},
        )
        item3 = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")

        mock_result = self._create_mock_run_result([item0, item1, item2, item3], turns_count=2)

        count, tools, has_output, trace, data = verify_runtime_trace_and_budget(
            mock_result,
            expected_tool_name="get_metric_definition",
            max_tool_calls=1,
            max_turns=3,
        )

        self.assertEqual(count, 1)
        self.assertEqual(tools, ("get_metric_definition",))
        self.assertTrue(has_output)
        self.assertEqual(
            trace,
            ("MessageOutput", "ToolCall:get_metric_definition", "ToolCallOutput", "MessageOutput"),
        )
        self.assertEqual(data["metric_id"], "sales")
        self.assertEqual(data["unit"], "usd")

    def test_trace_rejects_zero_tool_calls(self) -> None:
        """Verify trace validator rejects execution without any tool call."""
        item0 = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")
        mock_result = self._create_mock_run_result([item0])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result)
        self.assertIn("No tool calls found", str(ctx.exception))

    def test_trace_rejects_multiple_tool_calls(self) -> None:
        """Verify trace validator rejects execution with more tool calls than budget."""
        raw_call1 = ResponseFunctionToolCall(id="i1", call_id="c1", name="get_metric_definition", arguments="{}", type="function_call")
        raw_call2 = ResponseFunctionToolCall(id="i2", call_id="c2", name="get_metric_definition", arguments="{}", type="function_call")
        mock_result = self._create_mock_run_result([
            ToolCallItem(agent=self.agent, raw_item=raw_call1),
            ToolCallItem(agent=self.agent, raw_item=raw_call2),
        ])

        with self.assertRaises(RuntimeBudgetExceededError) as ctx:
            verify_runtime_trace_and_budget(mock_result, max_tool_calls=1)
        self.assertIn("Tool call budget exceeded in trace", str(ctx.exception))

    def test_trace_rejects_multiple_tool_calls_even_when_budget_allows(self) -> None:
        """The Phase 5 spike contract requires exactly one tool call, not merely an upper bound."""
        raw_call1 = ResponseFunctionToolCall(id="i1", call_id="c1", name="get_metric_definition", arguments="{}", type="function_call")
        raw_call2 = ResponseFunctionToolCall(id="i2", call_id="c2", name="get_metric_definition", arguments="{}", type="function_call")
        mock_result = self._create_mock_run_result([
            ToolCallItem(agent=self.agent, raw_item=raw_call1),
            ToolCallItem(agent=self.agent, raw_item=raw_call2),
        ])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result, max_tool_calls=2)
        self.assertIn("expected exactly one ToolCallItem", str(ctx.exception))

    def test_trace_rejects_wrong_tool_name(self) -> None:
        """Verify trace validator rejects unexpected tool name."""
        raw_call = ResponseFunctionToolCall(id="i1", call_id="c1", name="wrong_tool", arguments="{}", type="function_call")
        mock_result = self._create_mock_run_result([
            ToolCallItem(agent=self.agent, raw_item=raw_call),
        ])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result, expected_tool_name="get_metric_definition")
        self.assertIn("Unexpected tool called", str(ctx.exception))

    def test_trace_rejects_mismatched_call_id(self) -> None:
        """Verify trace validator rejects mismatched call ID between tool call and output."""
        raw_call = ResponseFunctionToolCall(id="i1", call_id="call_aaa", name="get_metric_definition", arguments="{}", type="function_call")
        item1 = ToolCallItem(agent=self.agent, raw_item=raw_call)
        item2 = ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": "call_bbb", "output": '{"metric_id": "sales", "unit": "usd"}'},
            output={"metric_id": "sales", "unit": "usd"},
        )
        item3 = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")
        mock_result = self._create_mock_run_result([item1, item2, item3])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result)
        self.assertIn("call_id mismatch", str(ctx.exception))

    def test_trace_rejects_tool_output_before_tool_call(self) -> None:
        """Verify trace validator rejects invalid order where ToolCallOutput appears before ToolCall."""
        raw_call = ResponseFunctionToolCall(id="i1", call_id="call_001", name="get_metric_definition", arguments="{}", type="function_call")
        item_out = ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": "call_001", "output": '{"metric_id": "sales", "unit": "usd"}'},
            output={"metric_id": "sales", "unit": "usd"},
        )
        item_call = ToolCallItem(agent=self.agent, raw_item=raw_call)
        item_msg = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")
        mock_result = self._create_mock_run_result([item_out, item_call, item_msg])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result)
        self.assertIn("Trace ordering violation", str(ctx.exception))
        self.assertIn("appeared before ToolCall", str(ctx.exception))

    def test_trace_rejects_no_message_output(self) -> None:
        """Verify trace validator rejects execution without any MessageOutputItem."""
        raw_call = ResponseFunctionToolCall(id="i1", call_id="call_001", name="get_metric_definition", arguments="{}", type="function_call")
        item1 = ToolCallItem(agent=self.agent, raw_item=raw_call)
        item2 = ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": "call_001", "output": '{"metric_id": "sales", "unit": "usd"}'},
            output={"metric_id": "sales", "unit": "usd"},
        )
        mock_result = self._create_mock_run_result([item1, item2])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result)
        self.assertIn("No MessageOutputItem found", str(ctx.exception))

    def test_trace_rejects_final_message_before_tool_output(self) -> None:
        """Verify trace validator rejects execution where all MessageOutputs appear before ToolCallOutput."""
        raw_call = ResponseFunctionToolCall(id="i1", call_id="call_001", name="get_metric_definition", arguments="{}", type="function_call")
        item_msg1 = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")
        item_call = ToolCallItem(agent=self.agent, raw_item=raw_call)
        item_out = ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": "call_001", "output": '{"metric_id": "sales", "unit": "usd"}'},
            output={"metric_id": "sales", "unit": "usd"},
        )
        mock_result = self._create_mock_run_result([item_msg1, item_call, item_out])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result)
        self.assertIn("Trace ordering violation", str(ctx.exception))
        self.assertIn("Final MessageOutput", str(ctx.exception))

    def test_trace_rejects_zero_or_exceeded_turns(self) -> None:
        """Verify turns budget checking based on raw_responses length."""
        raw_call = ResponseFunctionToolCall(id="i1", call_id="call_001", name="get_metric_definition", arguments="{}", type="function_call")
        item1 = ToolCallItem(agent=self.agent, raw_item=raw_call)
        item2 = ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": "call_001", "output": '{"metric_id": "sales", "unit": "usd"}'},
            output={"metric_id": "sales", "unit": "usd"},
        )
        item3 = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")

        # 1. Zero raw responses
        zero_res = self._create_mock_run_result([item1, item2, item3], turns_count=0)
        with self.assertRaises(RuntimeTraceError):
            verify_runtime_trace_and_budget(zero_res)

        # 2. Exceeded max_turns (4 > 3)
        exceeded_res = self._create_mock_run_result([item1, item2, item3], turns_count=4)
        with self.assertRaises(RuntimeBudgetExceededError):
            verify_runtime_trace_and_budget(exceeded_res, max_turns=3)

    def test_trace_rejects_non_string_tool_output_fields(self) -> None:
        """Tool output identity fields cannot be coerced from arbitrary values."""
        raw_call = ResponseFunctionToolCall(id="i1", call_id="call_001", name="get_metric_definition", arguments="{}", type="function_call")
        item1 = ToolCallItem(agent=self.agent, raw_item=raw_call)
        item2 = ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": "call_001", "output": '{"metric_id": 123, "unit": "usd"}'},
            output={"metric_id": 123, "unit": "usd"},
        )
        item3 = MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")
        mock_result = self._create_mock_run_result([item1, item2, item3])

        with self.assertRaises(RuntimeTraceError) as ctx:
            verify_runtime_trace_and_budget(mock_result)
        self.assertIn("metric_id", str(ctx.exception))

    def test_cross_validation_rejects_non_string_tool_data(self) -> None:
        """Cross-validation must not stringify malformed factual tool output."""
        final_output = RuntimeSpikeOutput(
            metric_id="123",
            unit="usd",
            tool_used="get_metric_definition",
            summary="Malformed tool output",
        )
        with self.assertRaises(RuntimeValidationError):
            cross_validate_structured_output(final_output, {"metric_id": 123, "unit": "usd"})

    def test_verification_script_returns_two_when_credentials_are_missing(self) -> None:
        """The live verification script exposes missing credentials as BLOCKED (exit 2)."""
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "verify_phase5_runtime_spike.py"
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = ""
        env["METRICSLEUTH_AGENT_MODEL"] = ""
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("Live Status: BLOCKED", completed.stdout)

    def test_cross_validation_rejects_mismatched_metric_id_or_unit_or_tool(self) -> None:
        """Verify cross_validate_structured_output detects any divergence between final output and tool data."""
        tool_data = {"metric_id": "sales", "unit": "usd"}

        # 1. Mismatched metric_id
        bad_metric = RuntimeSpikeOutput(
            metric_id="orders",
            unit="usd",
            tool_used="get_metric_definition",
            summary="Sales metric",
        )
        with self.assertRaises(RuntimeValidationError) as ctx1:
            cross_validate_structured_output(bad_metric, tool_data)
        self.assertIn("metric_id", str(ctx1.exception))

        # 2. Mismatched unit
        bad_unit = RuntimeSpikeOutput(
            metric_id="sales",
            unit="count",
            tool_used="get_metric_definition",
            summary="Sales metric",
        )
        with self.assertRaises(RuntimeValidationError) as ctx2:
            cross_validate_structured_output(bad_unit, tool_data)
        self.assertIn("unit", str(ctx2.exception))

        # 3. Mismatched tool_used
        bad_tool = RuntimeSpikeOutput(
            metric_id="sales",
            unit="usd",
            tool_used="query_metric",
            summary="Sales metric",
        )
        with self.assertRaises(RuntimeValidationError) as ctx3:
            cross_validate_structured_output(bad_tool, tool_data)
        self.assertIn("tool_used", str(ctx3.exception))


if __name__ == "__main__":
    unittest.main()
