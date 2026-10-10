"""Controlled tests for SDK tool progress callbacks."""

import asyncio
import datetime
from decimal import Decimal
import json
import unittest

from agents import Agent
from agents.tool_context import ToolContext

from app.agent_runtime.investigation_tools import create_investigation_tools
from app.agent_runtime.spike import ToolCallBudgetGuard
from app.analytics.models import (
    DateRange,
    MetricQueryResult,
    MetricQueryRow,
    RelatedMetricQueryResult,
)
from app.metrics.registry import MetricDefinition


FIXED_NOW = datetime.datetime(2026, 8, 29, 12, 0, tzinfo=datetime.timezone.utc)


def _result(metric: str) -> MetricQueryResult:
    return MetricQueryResult(
        metric_id=metric,
        unit="count",
        current_period=DateRange(
            datetime.date(2026, 8, 28), datetime.date(2026, 8, 28)
        ),
        baseline_period=DateRange(
            datetime.date(2026, 8, 21), datetime.date(2026, 8, 27)
        ),
        group_by=("marketplace",),
        rows=(
            MetricQueryRow(
                dimensions={"marketplace": "US"},
                current_value=Decimal("80"),
                baseline_value=Decimal("100"),
                relative_change=Decimal("-0.2"),
                status="ok",
                sample_size=Decimal("10"),
            ),
        ),
    )


class FakeAnalyticsTools:
    def __init__(self) -> None:
        self.query_metric_calls: list[dict[str, object]] = []
        self.query_related_calls: list[dict[str, object]] = []

    def get_metric_definition(self, metric_id: str) -> MetricDefinition:
        return MetricDefinition(
            metric_id=metric_id,
            display_name=metric_id,
            description="Controlled test metric.",
            metric_type="additive",
            unit="count",
            formula=metric_id,
            source_fields=(metric_id,),
            dimensions=("marketplace",),
            dependencies=(),
            related_metrics=(),
            driver_metrics=(),
        )

    def query_metric(self, **kwargs: object) -> MetricQueryResult:
        self.query_metric_calls.append(kwargs)
        return _result(str(kwargs["metric"]))

    def query_related_metrics(self, **kwargs: object) -> RelatedMetricQueryResult:
        self.query_related_calls.append(kwargs)
        source_metric = str(kwargs["metric"])
        return RelatedMetricQueryResult(
            source_metric_id=source_metric,
            results=(_result("orders"), _result("sessions")),
        )


class TestRuntimeProgress(unittest.TestCase):
    def setUp(self) -> None:
        self.analytics = FakeAnalyticsTools()
        self.events = []
        self.definition_tool, self.query_tool, self.related_tool = (
            create_investigation_tools(
                self.analytics,
                budget_guard=ToolCallBudgetGuard(max_calls=8),
                clock=lambda: FIXED_NOW,
                progress_callback=lambda trace, observations: self.events.append(
                    (trace, observations)
                ),
            )
        )
        self.agent = Agent(name="RuntimeProgressTestAgent")

    def _invoke(self, tool, call_id: str, raw_arguments: str):
        context = ToolContext(
            context=None,
            agent=self.agent,
            tool_call_id=call_id,
            tool_name=tool.name,
            tool_arguments=raw_arguments,
        )
        return asyncio.run(tool.on_invoke_tool(context, raw_arguments))

    def test_definition_reports_trace_and_empty_observation_tuple(self) -> None:
        raw = '{"metric":"sales"}'

        payload = self._invoke(self.definition_tool, "call_definition", raw)

        self.assertEqual(payload["tool_name"], self.events[0][0].tool_name)
        trace, observations = self.events[0]
        self.assertEqual(trace.tool_call_id, payload["tool_call_id"])
        self.assertEqual(trace.tool_name, payload["tool_name"])
        self.assertEqual(dict(trace.arguments), {"metric": "sales"})
        self.assertEqual(trace.observation_ids, ())
        self.assertEqual(observations, ())

    def test_query_reports_original_arguments_without_python_defaults(self) -> None:
        raw = '{"metric":"sales","start_date":"2026-08-28","end_date":"2026-08-28"}'

        payload = self._invoke(self.query_tool, "call_query", raw)

        trace, observations = self.events[0]
        self.assertEqual(dict(trace.arguments), json.loads(raw))
        self.assertNotIn("compare_to", trace.arguments)
        self.assertNotIn("filters", trace.arguments)
        self.assertNotIn("group_by", trace.arguments)
        self.assertEqual(trace.tool_call_id, payload["tool_call_id"])
        self.assertEqual(trace.tool_name, payload["tool_name"])
        self.assertEqual(trace.observation_ids, tuple(item["observation_id"] for item in payload["observations"]))
        self.assertEqual(len(observations), len(payload["observations"]))
        self.assertEqual(observations[0].observation_id, payload["observations"][0]["observation_id"])
        self.assertEqual(self.analytics.query_metric_calls[0]["compare_to"], "previous_7_days")

    def test_related_metrics_reports_all_observations(self) -> None:
        raw = '{"metric":"sales","start_date":"2026-08-28","end_date":"2026-08-28","filters":{"marketplace":"US"}}'

        payload = self._invoke(self.related_tool, "call_related", raw)

        trace, observations = self.events[0]
        self.assertEqual(trace.tool_call_id, payload["tool_call_id"])
        self.assertEqual(trace.tool_name, payload["tool_name"])
        self.assertEqual(dict(trace.arguments), json.loads(raw))
        self.assertEqual(len(observations), 2)
        self.assertEqual(
            trace.observation_ids,
            tuple(item.observation_id for item in observations),
        )
        self.assertEqual(
            tuple(item.metric for item in observations),
            ("orders", "sessions"),
        )

    def test_callback_failure_propagates_after_payload_is_built(self) -> None:
        failure = RuntimeError("progress persistence failed")
        definition_tool, query_tool, _ = create_investigation_tools(
            self.analytics,
            budget_guard=ToolCallBudgetGuard(max_calls=8),
            clock=lambda: FIXED_NOW,
            progress_callback=lambda _trace, _observations: (_ for _ in ()).throw(failure),
        )
        raw = '{"metric":"sales","start_date":"2026-08-28","end_date":"2026-08-28"}'

        with self.assertRaisesRegex(RuntimeError, "progress persistence failed") as raised:
            self._invoke(query_tool, "call_callback_failure", raw)

        self.assertIs(raised.exception, failure)
        self.assertEqual(len(self.analytics.query_metric_calls), 1)

    def test_no_callback_keeps_tool_result_contract_and_does_not_emit_progress(self) -> None:
        _, query_tool, _ = create_investigation_tools(
            self.analytics,
            budget_guard=ToolCallBudgetGuard(max_calls=8),
            clock=lambda: FIXED_NOW,
        )
        raw = '{"metric":"sales","start_date":"2026-08-28","end_date":"2026-08-28"}'
        context = ToolContext(
            context=None,
            agent=self.agent,
            tool_call_id="call_without_callback",
            tool_name=query_tool.name,
            tool_arguments=raw,
        )

        payload = asyncio.run(query_tool.on_invoke_tool(context, raw))

        self.assertEqual(payload["tool_call_id"], "call_without_callback")
        self.assertEqual(payload["tool_name"], "query_metric")
        self.assertEqual(len(payload["observations"]), 1)
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
