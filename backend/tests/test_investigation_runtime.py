"""Hermetic SDK Runner tests for the Phase 6 investigation run contract."""

import datetime
from decimal import Decimal
import json
import unittest
from unittest.mock import MagicMock

from agents import Agent, MessageOutputItem, RunConfig, RunResult, ToolCallItem, ToolCallOutputItem
from agents.testing import ScriptedModel, assistant_message, function_call
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall

from app.agent_runtime.investigation_runtime import (
    InvestigationRunSummary,
    InvestigationToolTraceEntry,
    run_investigation,
    verify_investigation_trace,
)
from app.agent_runtime.spike import RuntimeBudgetExceededError, RuntimeTraceError
from app.analytics.models import DateRange, MetricQueryResult, MetricQueryRow, RelatedMetricQueryResult
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricDefinition


def result_for(metric: str) -> MetricQueryResult:
    return MetricQueryResult(
        metric_id=metric,
        unit="ratio" if metric == "conversion_rate" else "count",
        current_period=DateRange(datetime.date(2026, 8, 28), datetime.date(2026, 8, 28)),
        baseline_period=DateRange(datetime.date(2026, 8, 21), datetime.date(2026, 8, 27)),
        group_by=(),
        rows=(MetricQueryRow({}, Decimal("90"), Decimal("120"), Decimal("-0.25"), "ok", Decimal("1000")),),
    )


class TestInvestigationRuntime(unittest.TestCase):
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
            dimensions=("marketplace",),
            dependencies=(),
            related_metrics=("orders", "conversion_rate"),
        )
        self.analytics.query_related_metrics.return_value = RelatedMetricQueryResult(
            source_metric_id="sales",
            results=(result_for("orders"), result_for("conversion_rate")),
        )
        self.analytics.query_metric.return_value = result_for("conversion_rate")
        self.agent = Agent(name="TraceTestAgent")

    def test_scripted_runner_executes_two_tools_and_returns_audited_summary(self) -> None:
        model = ScriptedModel([
            [function_call(
                "get_metric_definition",
                {"metric": "sales"},
                call_id="call_definition",
            )],
            [function_call("query_related_metrics", {
                "metric": "sales", "start_date": "2026-08-28", "end_date": "2026-08-28"
            }, call_id="call_related")],
            [function_call("query_metric", {
                "metric": "conversion_rate", "start_date": "2026-08-28", "end_date": "2026-08-28",
                "filters": {"marketplace": "US"},
                "group_by": ["marketplace"],
            }, call_id="call_metric")],
            [assistant_message("Conversion rate is the material data-level driver; external cause is unproven.")],
        ])

        summary = run_investigation(
            "Investigate sales on 2026-08-28.",
            analytics_tools=self.analytics,
            model=model,
            run_config=RunConfig(tracing_disabled=True),
        )

        self.assertEqual(summary.tool_calls_count, 3)
        self.assertEqual(
            summary.tools_used,
            ("get_metric_definition", "query_related_metrics", "query_metric"),
        )
        self.assertEqual(
            summary.tool_call_ids,
            ("call_definition", "call_related", "call_metric"),
        )
        self.assertEqual(summary.turns_count, 4)
        self.assertEqual(summary.observation_count, 3)
        self.assertTrue(all(item.startswith("call_") for item in summary.observation_ids))
        self.assertEqual(
            tuple(entry.tool_call_id for entry in summary.tool_trace),
            summary.tool_call_ids,
        )
        self.assertEqual(
            tuple(entry.tool_name for entry in summary.tool_trace),
            summary.tools_used,
        )
        self.assertEqual(dict(summary.tool_trace[0].arguments), {"metric": "sales"})
        query_arguments = summary.tool_trace[2].arguments
        self.assertEqual(query_arguments["metric"], "conversion_rate")
        self.assertEqual(query_arguments["start_date"], "2026-08-28")
        self.assertEqual(query_arguments["end_date"], "2026-08-28")
        self.assertEqual(query_arguments["group_by"], ("marketplace",))
        self.assertEqual(
            dict(query_arguments["filters"]),
            {"marketplace": "US"},
        )
        with self.assertRaises(TypeError):
            query_arguments["metric"] = "sales"  # type: ignore[index]
        with self.assertRaises(TypeError):
            query_arguments["filters"]["marketplace"] = "DE"  # type: ignore[index]
        self.analytics.get_metric_definition.assert_any_call("sales")
        self.analytics.query_related_metrics.assert_called_once()
        self.analytics.query_metric.assert_called_once()
        model.assert_complete()

    def test_scripted_runner_allows_a_different_tool_sequence(self) -> None:
        model = ScriptedModel([
            [function_call("query_metric", {
                "metric": "sales", "start_date": "2026-08-28", "end_date": "2026-08-28"
            }, call_id="first_metric")],
            [function_call("query_related_metrics", {
                "metric": "sales", "start_date": "2026-08-28", "end_date": "2026-08-28"
            }, call_id="second_related")],
            [assistant_message("The scripted alternate path completed.")],
        ])
        summary = run_investigation(
            "Inspect sales without assuming a drill-down order.",
            analytics_tools=self.analytics,
            model=model,
            run_config=RunConfig(tracing_disabled=True),
        )
        self.assertEqual(summary.tools_used, ("query_metric", "query_related_metrics"))
        model.assert_complete()

    def _call(
        self,
        call_id: str = "c1",
        name: str = "query_metric",
        arguments: str = "{}",
    ) -> ToolCallItem:
        raw = ResponseFunctionToolCall(
            id=f"item_{call_id}",
            call_id=call_id,
            name=name,
            arguments=arguments,
            type="function_call",
        )
        return ToolCallItem(agent=self.agent, raw_item=raw)

    def _output(self, call_id: str = "c1", *, payload=None) -> ToolCallOutputItem:
        body = payload if payload is not None else {
            "tool_name": "query_metric", "tool_call_id": call_id, "metric": "sales",
            "observations": [{
                "observation_id": f"obs_{call_id}", "tool_call_id": call_id,
                "tool_name": "query_metric", "status": "anomalous"
            }],
        }
        return ToolCallOutputItem(agent=self.agent, raw_item={"call_id": call_id, "output": body}, output=body)

    def _message(self) -> MessageOutputItem:
        return MessageOutputItem(agent=self.agent, raw_item=MagicMock(), type="message_output_item")

    def _definition_payload(
        self,
        call_id: str = "definition_call",
        metric: str = "sales",
    ) -> dict:
        return {
            "tool_name": "get_metric_definition",
            "tool_call_id": call_id,
            "metric": metric,
            "definition": {
                "metric_id": metric,
                "display_name": "Sales",
                "description": "Recognized sales amount.",
                "metric_type": "sum",
                "unit": "usd",
                "formula": "SUM(sales_amount)",
                "source_fields": ["sales_amount"],
                "dimensions": ["marketplace"],
                "dependencies": [],
                "driver_metrics": [],
                "related_metrics": ["orders", "conversion_rate"],
            },
        }

    def _result(self, items, *, turns: int = 2, final_output: str = "done") -> RunResult:
        result = MagicMock(spec=RunResult)
        result.new_items = items
        result.raw_responses = [MagicMock() for _ in range(turns)]
        result.final_output = final_output
        return result

    def test_invalid_run_arguments_fail_fast(self) -> None:
        for prompt in ["", "   ", None]:
            with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                run_investigation(prompt, analytics_tools=self.analytics, model=MagicMock())
        for field, value in [("max_tool_calls", 0), ("max_tool_calls", True), ("max_turns", -1)]:
            kwargs = {field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                run_investigation("go", analytics_tools=self.analytics, model=MagicMock(), **kwargs)

    def test_trace_rejects_wrong_duplicate_and_orphan_call_identity(self) -> None:
        cases = [
            ([self._call(name="wrong_tool"), self._output(), self._message()], "Unexpected"),
            ([self._call(), self._call(), self._output(), self._message()], "Duplicate ToolCallItem"),
            ([self._call(), self._output(), self._output(), self._message()], "Duplicate ToolCallOutputItem"),
            ([self._call(), self._output("orphan"), self._message()], "Missing ToolCallOutputItem"),
        ]
        for items, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(RuntimeTraceError, expected):
                verify_investigation_trace(self._result(items))

    def test_trace_rejects_output_order_and_final_message_violations(self) -> None:
        cases = [
            [self._output(), self._call(), self._message()],
            [self._call(), self._output()],
            [self._call(), self._output(), self._message(), self._call("c2"), self._output("c2")],
        ]
        for items in cases:
            with self.subTest(length=len(items)), self.assertRaises(RuntimeTraceError):
                verify_investigation_trace(self._result(items))

    def test_trace_rejects_envelope_and_observation_identity_mismatches(self) -> None:
        bad_payloads = [
            {"tool_name": "query_metric", "tool_call_id": "other", "observations": []},
            {"tool_name": "query_related_metrics", "tool_call_id": "c1", "observations": []},
            {"tool_name": "query_metric", "tool_call_id": "c1", "observations": {}},
            {"tool_name": "query_metric", "tool_call_id": "c1", "observations": ["bad"]},
            {"tool_name": "query_metric", "tool_call_id": "c1", "observations": [{
                "observation_id": "obs", "tool_call_id": "other", "tool_name": "query_metric", "status": "normal"
            }]},
            {"tool_name": "query_metric", "tool_call_id": "c1", "observations": [{
                "observation_id": "obs", "tool_call_id": "c1", "tool_name": "query_metric", "status": ""
            }]},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload), self.assertRaises(RuntimeTraceError):
                verify_investigation_trace(self._result([self._call(), self._output(payload=payload), self._message()]))

    def test_trace_rejects_duplicate_observation_ids_across_outputs(self) -> None:
        payload1 = {"tool_name": "query_metric", "tool_call_id": "c1", "observations": [{
            "observation_id": "same", "tool_call_id": "c1", "tool_name": "query_metric", "status": "normal"
        }]}
        payload2 = {"tool_name": "query_metric", "tool_call_id": "c2", "observations": [{
            "observation_id": "same", "tool_call_id": "c2", "tool_name": "query_metric", "status": "normal"
        }]}
        items = [self._call("c1"), self._output("c1", payload=payload1), self._call("c2"), self._output("c2", payload=payload2), self._message()]
        with self.assertRaisesRegex(RuntimeTraceError, "Duplicate observation_id"):
            verify_investigation_trace(self._result(items))

    def test_trace_accepts_json_string_output_and_empty_observations(self) -> None:
        payload = {"tool_name": "query_metric", "tool_call_id": "c1", "observations": []}
        output = self._output(payload=json.dumps(payload))
        summary = verify_investigation_trace(self._result([self._call(), output, self._message()]))
        self.assertEqual(summary.observation_count, 0)

    def test_trace_accepts_definition_without_creating_observations(self) -> None:
        call_id = "definition_call"
        items = [
            self._call(call_id, "get_metric_definition"),
            self._output(
                call_id,
                payload=self._definition_payload(call_id),
            ),
            self._message(),
        ]

        summary = verify_investigation_trace(self._result(items))

        self.assertEqual(summary.tool_calls_count, 1)
        self.assertEqual(summary.tools_used, ("get_metric_definition",))
        self.assertEqual(summary.tool_call_ids, (call_id,))
        self.assertEqual(summary.observation_count, 0)
        self.assertEqual(summary.observation_ids, ())
        self.assertEqual(summary.tool_trace[0].observation_ids, ())

    def test_trace_rejects_malformed_definition_envelopes(self) -> None:
        call_id = "definition_call"
        valid = self._definition_payload(call_id)
        missing_envelope_key = dict(valid)
        missing_envelope_key.pop("metric")
        extra_envelope_key = dict(valid, table="fact_daily")
        non_object_definition = dict(valid, definition=[])
        missing_definition_key = {
            **valid,
            "definition": {
                key: value
                for key, value in valid["definition"].items()
                if key != "formula"
            },
        }
        bad_list_type = {
            **valid,
            "definition": {
                **valid["definition"],
                "dimensions": "marketplace",
            },
        }
        metric_mismatch = {
            **valid,
            "definition": {
                **valid["definition"],
                "metric_id": "orders",
            },
        }
        for payload in (
            missing_envelope_key,
            extra_envelope_key,
            non_object_definition,
            missing_definition_key,
            bad_list_type,
            metric_mismatch,
        ):
            with self.subTest(payload=payload), self.assertRaises(RuntimeTraceError):
                verify_investigation_trace(
                    self._result(
                        [
                            self._call(call_id, "get_metric_definition"),
                            self._output(call_id, payload=payload),
                            self._message(),
                        ]
                    )
                )

    def test_trace_rejects_invalid_or_non_object_tool_arguments(self) -> None:
        invalid_arguments = (
            "not-json",
            "[]",
            "null",
            '{"metric":"sales","metric":"orders"}',
            '{"value":NaN}',
            '{"value":1e999}',
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments), self.assertRaises(RuntimeTraceError):
                verify_investigation_trace(
                    self._result(
                        [
                            self._call(arguments=arguments),
                            self._output(),
                            self._message(),
                        ]
                    )
                )

    def test_trace_entry_is_a_recursive_defensive_snapshot(self) -> None:
        source = {
            "filters": [
                {
                    "dimension": "marketplace",
                    "value": "US",
                }
            ]
        }
        entry = InvestigationToolTraceEntry(
            tool_call_id="call_snapshot",
            tool_name="query_metric",
            arguments=source,
            observation_ids=("obs_snapshot",),
        )

        source["filters"][0]["value"] = "DE"
        source["filters"].append({"dimension": "asin", "value": "ASIN-A"})

        self.assertEqual(len(entry.arguments["filters"]), 1)
        self.assertEqual(entry.arguments["filters"][0]["value"], "US")
        with self.assertRaises(TypeError):
            entry.arguments["filters"][0]["value"] = "UK"  # type: ignore[index]
        with self.assertRaises(TypeError):
            entry.arguments["filters"][0] = {}  # type: ignore[index]

    def test_summary_rejects_drift_from_tool_trace(self) -> None:
        entry = InvestigationToolTraceEntry(
            tool_call_id="c1",
            tool_name="query_metric",
            arguments={"metric": "sales"},
            observation_ids=("obs_c1",),
        )
        valid = {
            "final_output": "done",
            "tool_calls_count": 1,
            "max_tool_calls": 8,
            "tools_used": ("query_metric",),
            "tool_call_ids": ("c1",),
            "observation_ids": ("obs_c1",),
            "observation_count": 1,
            "tool_trace": (entry,),
            "trace_sequence": (),
            "turns_count": 1,
            "max_turns": 10,
        }
        invalid_values = (
            ("tool_calls_count", 0),
            ("tools_used", ("query_related_metrics",)),
            ("tool_call_ids", ("other",)),
            ("observation_ids", ("other_observation",)),
            ("observation_count", 0),
            ("tool_trace", ()),
        )
        for field_name, value in invalid_values:
            kwargs = dict(valid)
            kwargs[field_name] = value
            with self.subTest(field=field_name), self.assertRaises(RuntimeTraceError):
                InvestigationRunSummary(**kwargs)

    def test_trace_rejects_invalid_output_final_text_turns_and_budget(self) -> None:
        invalid_output = self._output(payload="not-json")
        with self.assertRaises(RuntimeTraceError):
            verify_investigation_trace(self._result([self._call(), invalid_output, self._message()]))
        with self.assertRaises(RuntimeTraceError):
            verify_investigation_trace(self._result([self._call(), self._output(), self._message()], final_output=" "))
        with self.assertRaises(RuntimeTraceError):
            verify_investigation_trace(self._result([self._call(), self._output(), self._message()], turns=0))
        items = [self._call("c1"), self._output("c1"), self._call("c2"), self._output("c2"), self._message()]
        with self.assertRaises(RuntimeBudgetExceededError):
            verify_investigation_trace(self._result(items), max_tool_calls=1)


if __name__ == "__main__":
    unittest.main()
