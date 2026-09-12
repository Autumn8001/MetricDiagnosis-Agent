"""Hermetic tests for strict SDK Trace Observation Catalog extraction."""

import datetime
from decimal import Decimal
import inspect
import json
import unittest
from unittest.mock import MagicMock

from agents import Agent, MessageOutputItem, RunResult, ToolCallItem, ToolCallOutputItem
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall

from app.agent_runtime import investigation_runtime, investigation_tools
from app.agent_runtime.investigation_runtime import extract_observation_catalog
from app.agent_runtime.investigation_tools import observation_from_json, observation_to_json
from app.agent_runtime.spike import RuntimeTraceError
from app.analytics.models import DateRange
from app.observations.models import Observation, ObservationStatus


NOW = datetime.datetime(2026, 8, 29, 12, 0, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 8, 28), datetime.date(2026, 8, 28))
BASELINE = DateRange(datetime.date(2026, 8, 21), datetime.date(2026, 8, 27))


def make_observation(
    observation_id: str,
    status: ObservationStatus,
    *,
    metric: str = "sales",
    tool_call_id: str = "call_1",
) -> Observation:
    failed = status == ObservationStatus.FAILED
    return Observation(
        observation_id=observation_id,
        tool_name="query_metric",
        tool_call_id=tool_call_id,
        metric=metric,
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters={"marketplace": "US"},
        group_by=("marketplace",),
        dimensions={"marketplace": "US"},
        current_value=None if failed else Decimal("90"),
        baseline_value=None if failed else Decimal("100"),
        relative_change=None if failed else Decimal("-0.1"),
        unit="usd",
        sample_size=None if failed else Decimal("50"),
        source_status="tool_error" if failed else "ok",
        status=status,
        query_or_result_reference=f"tool-result:{observation_id}",
        created_at=NOW,
        error_code="QUERY_FAILED" if failed else None,
        error_message="warehouse query failed" if failed else None,
    )


class TestInvestigationObservationCatalog(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = Agent(name="CatalogTraceTestAgent")

    def _call(
        self,
        call_id: str,
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

    def _output(self, call_id: str, observations: list[Observation], *, as_json: bool = False) -> ToolCallOutputItem:
        body = {
            "tool_name": "query_metric",
            "tool_call_id": call_id,
            "metric": "sales",
            "observations": [observation_to_json(item) for item in observations],
        }
        output: object = json.dumps(body) if as_json else body
        return ToolCallOutputItem(
            agent=self.agent,
            raw_item={"call_id": call_id, "output": output},
            output=output,
        )

    def _message(self, content: str = "Investigation complete.") -> MessageOutputItem:
        return MessageOutputItem(
            agent=self.agent,
            raw_item={"content": content},
            type="message_output_item",
        )

    def _result(self, items: list[object], *, turns: int = 2, final_output: str = "done") -> RunResult:
        result = MagicMock(spec=RunResult)
        result.new_items = items
        result.raw_responses = [MagicMock() for _ in range(turns)]
        result.final_output = final_output
        return result

    def _valid_payload(self, status: ObservationStatus = ObservationStatus.NORMAL) -> dict[str, object]:
        return observation_to_json(make_observation("obs_one", status))

    def test_normal_anomalous_and_failed_json_roundtrip(self) -> None:
        for status in (
            ObservationStatus.NORMAL,
            ObservationStatus.ANOMALOUS,
            ObservationStatus.FAILED,
        ):
            with self.subTest(status=status):
                original = make_observation(f"obs_{status.value}", status)
                payload = observation_to_json(original)
                rebuilt = observation_from_json(payload)
                self.assertEqual(observation_to_json(rebuilt), payload)
                self.assertEqual(rebuilt, original)

    def test_payload_requires_exact_serializer_keys(self) -> None:
        payload = self._valid_payload()
        missing = dict(payload)
        missing.pop("metric")
        extra = dict(payload)
        extra["unexpected"] = "value"
        for invalid in (missing, extra):
            with self.subTest(payload=invalid), self.assertRaises(RuntimeTraceError):
                observation_from_json(invalid)

    def test_period_and_created_at_are_strict(self) -> None:
        invalid_periods = [
            None,
            {"start_date": "2026-08-28"},
            {"start_date": "2026-08-28", "end_date": "2026-08-28", "extra": "x"},
            {"start_date": "2026-2-28", "end_date": "2026-08-28"},
            {"start_date": "2026-02-30", "end_date": "2026-08-28"},
        ]
        for invalid_period in invalid_periods:
            payload = self._valid_payload()
            payload["current_period"] = invalid_period
            with self.subTest(period=invalid_period), self.assertRaises(RuntimeTraceError):
                observation_from_json(payload)

        for invalid_created_at in ("2026-08-29T12:00:00", "not-a-date", NOW):
            payload = self._valid_payload()
            payload["created_at"] = invalid_created_at
            with self.subTest(created_at=invalid_created_at), self.assertRaises(RuntimeTraceError):
                observation_from_json(payload)

    def test_decimal_fields_accept_only_finite_strings_or_null(self) -> None:
        for field_name in ("current_value", "baseline_value", "relative_change", "sample_size"):
            for invalid in (1, 1.5, True, "NaN", "Infinity", "-Infinity"):
                payload = self._valid_payload()
                payload[field_name] = invalid
                with self.subTest(field=field_name, value=invalid), self.assertRaises(RuntimeTraceError):
                    observation_from_json(payload)

        failed_payload = self._valid_payload(ObservationStatus.FAILED)
        for field_name in ("current_value", "baseline_value", "relative_change", "sample_size"):
            failed_payload[field_name] = None
        self.assertEqual(observation_from_json(failed_payload).status, ObservationStatus.FAILED)

    def test_status_collections_and_mapping_types_are_strict(self) -> None:
        payload = self._valid_payload()
        payload["status"] = "not_a_status"
        with self.assertRaises(RuntimeTraceError):
            observation_from_json(payload)

        invalid_values = {
            "filters": ["marketplace", "US"],
            "dimensions": {"marketplace": 1},
            "group_by": ("marketplace",),
        }
        for field_name, invalid in invalid_values.items():
            bad_payload = self._valid_payload()
            bad_payload[field_name] = invalid
            with self.subTest(field=field_name), self.assertRaises(RuntimeTraceError):
                observation_from_json(bad_payload)

        bad_group = self._valid_payload()
        bad_group["group_by"] = ["marketplace", 1]
        with self.assertRaises(RuntimeTraceError):
            observation_from_json(bad_group)

    def test_failed_observation_domain_invariants_are_wrapped(self) -> None:
        for field_name, value in (
            ("current_value", "1"),
            ("baseline_value", "1"),
            ("relative_change", "0"),
            ("sample_size", "1"),
            ("error_code", None),
            ("error_message", ""),
        ):
            payload = self._valid_payload(ObservationStatus.FAILED)
            payload[field_name] = value
            with self.subTest(field=field_name), self.assertRaises(RuntimeTraceError):
                observation_from_json(payload)

    def test_non_mapping_payload_is_rejected(self) -> None:
        for invalid in (None, [], "{}", 1):
            with self.subTest(payload=invalid), self.assertRaises(RuntimeTraceError):
                observation_from_json(invalid)  # type: ignore[arg-type]

    def test_multi_output_catalog_preserves_trace_order_and_is_tuple(self) -> None:
        first = make_observation("obs_first", ObservationStatus.NORMAL)
        second = make_observation("obs_second", ObservationStatus.ANOMALOUS, tool_call_id="call_2")
        result = self._result([
            self._call("call_1"),
            self._output("call_1", [first]),
            self._call("call_2"),
            self._output("call_2", [second], as_json=True),
            self._message(),
        ])

        catalog = extract_observation_catalog(result)

        self.assertIsInstance(catalog, tuple)
        self.assertEqual(catalog, (first, second))
        self.assertEqual([item.observation_id for item in catalog], ["obs_first", "obs_second"])

    def test_out_of_order_outputs_use_deterministic_tool_call_order(self) -> None:
        first = make_observation("obs_first", ObservationStatus.NORMAL)
        second = make_observation(
            "obs_second", ObservationStatus.ANOMALOUS, tool_call_id="call_2"
        )
        result = self._result([
            self._call(
                "call_1",
                arguments=json.dumps(
                    {
                        "metric": "sales",
                        "start_date": "2026-08-28",
                        "end_date": "2026-08-28",
                    }
                ),
            ),
            self._call(
                "call_2",
                arguments=json.dumps(
                    {
                        "metric": "orders",
                        "start_date": "2026-08-28",
                        "end_date": "2026-08-28",
                    }
                ),
            ),
            self._output("call_2", [second]),
            self._output("call_1", [first]),
            self._message(),
        ])

        summary = investigation_runtime.verify_investigation_trace(result)
        catalog = extract_observation_catalog(result)

        self.assertEqual(catalog, (first, second))
        self.assertEqual(
            tuple(entry.tool_call_id for entry in summary.tool_trace),
            ("call_1", "call_2"),
        )
        self.assertEqual(
            tuple(entry.observation_ids for entry in summary.tool_trace),
            (("obs_first",), ("obs_second",)),
        )
        self.assertEqual(summary.tool_trace[0].arguments["metric"], "sales")
        self.assertEqual(summary.tool_trace[1].arguments["metric"], "orders")

    def test_message_json_is_never_added_to_catalog(self) -> None:
        actual = make_observation("obs_actual", ObservationStatus.NORMAL)
        fake = observation_to_json(make_observation("obs_from_message", ObservationStatus.ANOMALOUS))
        result = self._result(
            [
                self._call("call_1"),
                self._output("call_1", [actual]),
                self._message(content=json.dumps({"observations": [fake]})),
            ],
            final_output=json.dumps({"observations": [fake]}),
        )

        catalog = extract_observation_catalog(result)

        self.assertEqual(tuple(item.observation_id for item in catalog), ("obs_actual",))

    def test_trace_identity_and_duplicate_observation_checks_are_preserved(self) -> None:
        observation = make_observation("obs_identity", ObservationStatus.NORMAL)
        bad_envelope = self._output("call_1", [observation])
        bad_envelope.output["tool_call_id"] = "other"  # type: ignore[index]
        result = self._result([self._call("call_1"), bad_envelope, self._message()])
        with self.assertRaises(RuntimeTraceError):
            extract_observation_catalog(result)

        duplicate = make_observation("obs_duplicate", ObservationStatus.NORMAL)
        duplicate_for_second_call = make_observation(
            "obs_duplicate", ObservationStatus.NORMAL, tool_call_id="call_2"
        )
        result = self._result([
            self._call("call_1"),
            self._output("call_1", [duplicate]),
            self._call("call_2"),
            self._output("call_2", [duplicate_for_second_call]),
            self._message(),
        ])
        with self.assertRaises(RuntimeTraceError):
            extract_observation_catalog(result)

    def test_catalog_extraction_does_not_read_evaluation_files(self) -> None:
        source = (
            inspect.getsource(investigation_tools)
            + inspect.getsource(investigation_runtime)
        ).lower()
        self.assertNotIn("ground_truth", source)


if __name__ == "__main__":
    unittest.main()
