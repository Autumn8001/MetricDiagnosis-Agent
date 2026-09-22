"""Official Agents SDK run contract for MetricSleuth investigations.

The SDK Runner owns the model/tool loop. This module only constructs the Agent,
starts a bounded run, and audits the resulting public RunItem trace.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from agents import (
    Agent,
    MessageOutputItem,
    RunConfig,
    RunResult,
    Runner,
    ToolCallItem,
    ToolCallOutputItem,
)

from app.agent_runtime.investigation_tools import (
    DEFAULT_INVESTIGATION_TOOL_BUDGET,
    GET_METRIC_DEFINITION_TOOL_NAME,
    create_investigation_tools,
    observation_from_json,
)
from app.agent_runtime.spike import (
    RuntimeBudgetExceededError,
    RuntimeTraceError,
    ToolCallBudgetGuard,
    configure_openai_api_from_env,
)
from app.analytics.tools import AnalyticsTools
from app.observations.models import Observation


DEFAULT_INVESTIGATION_MAX_TURNS = 10
INVESTIGATION_TOOL_NAMES = (
    GET_METRIC_DEFINITION_TOOL_NAME,
    "query_metric",
    "query_related_metrics",
)
_METRIC_DEFINITION_OUTPUT_KEYS = frozenset(
    {"tool_name", "tool_call_id", "metric", "definition"}
)
_METRIC_DEFINITION_KEYS = frozenset(
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
    }
)
_METRIC_DEFINITION_STRING_FIELDS = (
    "metric_id",
    "display_name",
    "description",
    "metric_type",
    "unit",
    "formula",
)
_METRIC_DEFINITION_LIST_FIELDS = (
    "source_fields",
    "dimensions",
    "dependencies",
    "driver_metrics",
    "related_metrics",
)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"'{field_name}' must be a positive integer.")
    return value


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeTraceError(f"'{field_name}' must be a non-empty string.")
    return value.strip()


def _parse_output_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeTraceError("Tool output must be a JSON object.") from exc
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeTraceError("Tool output must be a mapping or JSON object string.")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}.")


def _freeze_json_value(value: Any) -> Any:
    """Return an immutable defensive snapshot of a parsed JSON value."""
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeTraceError("Tool arguments object keys must be strings.")
            frozen[key] = _freeze_json_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise RuntimeTraceError("Tool arguments contain a non-JSON value.")


def _parse_tool_call_arguments(item: ToolCallItem) -> Mapping[str, Any]:
    try:
        raw_arguments = item.raw_item.arguments
    except AttributeError as exc:
        raise RuntimeTraceError(
            "ToolCallItem.raw_item must expose JSON arguments."
        ) from exc
    if not isinstance(raw_arguments, str):
        raise RuntimeTraceError("Tool call arguments must be a JSON object string.")
    try:
        parsed = json.loads(
            raw_arguments,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeTraceError("Tool call arguments must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeTraceError("Tool call arguments must be a JSON object.")
    frozen = _freeze_json_value(parsed)
    if not isinstance(frozen, Mapping):
        raise RuntimeTraceError("Tool call arguments must be a JSON object.")
    return frozen


def _verify_metric_definition_payload(payload: Mapping[str, Any]) -> None:
    """Validate the exact semantic-definition JSON boundary."""
    if set(payload) != _METRIC_DEFINITION_OUTPUT_KEYS:
        raise RuntimeTraceError(
            "get_metric_definition output must contain exactly "
            "tool_name, tool_call_id, metric, and definition."
        )
    metric = _non_empty_string(payload["metric"], "tool output metric")
    definition = payload["definition"]
    if not isinstance(definition, Mapping):
        raise RuntimeTraceError("Tool output 'definition' must be an object.")
    if set(definition) != _METRIC_DEFINITION_KEYS:
        raise RuntimeTraceError(
            "Tool output 'definition' must contain exactly the semantic registry fields."
        )
    for field_name in _METRIC_DEFINITION_STRING_FIELDS:
        _non_empty_string(
            definition[field_name],
            f"tool output definition.{field_name}",
        )
    for field_name in _METRIC_DEFINITION_LIST_FIELDS:
        value = definition[field_name]
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise RuntimeTraceError(
                f"'tool output definition.{field_name}' must be a list[str]."
            )
    if definition["metric_id"].strip() != metric:
        raise RuntimeTraceError(
            "Tool output metric must match definition.metric_id."
        )


def _snapshot_string_tuple(
    value: Sequence[str],
    field_name: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RuntimeTraceError(f"'{field_name}' must be a sequence of strings.")
    snapshot = tuple(value)
    if not allow_empty and not snapshot:
        raise RuntimeTraceError(f"'{field_name}' must not be empty.")
    if any(not isinstance(item, str) or not item.strip() for item in snapshot):
        raise RuntimeTraceError(
            f"'{field_name}' must contain only non-empty strings."
        )
    return snapshot


@dataclass(frozen=True)
class InvestigationToolTraceEntry:
    """One audited model tool call with immutable JSON arguments and output facts."""

    tool_call_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        call_id = _non_empty_string(self.tool_call_id, "tool_call_id")
        tool_name = _non_empty_string(self.tool_name, "tool_name")
        if not isinstance(self.arguments, Mapping):
            raise RuntimeTraceError("'arguments' must be a mapping.")
        observation_ids = _snapshot_string_tuple(
            self.observation_ids,
            "observation_ids",
        )
        if len(set(observation_ids)) != len(observation_ids):
            raise RuntimeTraceError(
                "Trace entry observation_ids must not contain duplicates."
            )
        object.__setattr__(self, "tool_call_id", call_id)
        object.__setattr__(self, "tool_name", tool_name)
        object.__setattr__(self, "arguments", _freeze_json_value(self.arguments))
        object.__setattr__(self, "observation_ids", observation_ids)


@dataclass(frozen=True)
class InvestigationRunSummary:
    """Immutable audit summary of one bounded SDK investigation run."""

    final_output: str
    tool_calls_count: int
    max_tool_calls: int
    tools_used: tuple[str, ...]
    tool_call_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    observation_count: int
    tool_trace: tuple[InvestigationToolTraceEntry, ...]
    trace_sequence: tuple[str, ...]
    turns_count: int
    max_turns: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.tool_calls_count, bool)
            or not isinstance(self.tool_calls_count, int)
            or self.tool_calls_count < 0
        ):
            raise RuntimeTraceError("'tool_calls_count' must be a non-negative integer.")
        _positive_int(self.max_tool_calls, "max_tool_calls")
        if self.tool_calls_count > self.max_tool_calls:
            raise RuntimeTraceError("'tool_calls_count' must not exceed 'max_tool_calls'.")
        if (
            isinstance(self.observation_count, bool)
            or not isinstance(self.observation_count, int)
            or self.observation_count < 0
        ):
            raise RuntimeTraceError("'observation_count' must be a non-negative integer.")
        if (
            isinstance(self.turns_count, bool)
            or not isinstance(self.turns_count, int)
            or self.turns_count < 0
        ):
            raise RuntimeTraceError("'turns_count' must be a non-negative integer.")
        _positive_int(self.max_turns, "max_turns")
        if self.turns_count > self.max_turns:
            raise RuntimeTraceError("'turns_count' must not exceed 'max_turns'.")

        tools_used = _snapshot_string_tuple(self.tools_used, "tools_used")
        tool_call_ids = _snapshot_string_tuple(self.tool_call_ids, "tool_call_ids")
        observation_ids = _snapshot_string_tuple(
            self.observation_ids,
            "observation_ids",
        )
        trace_sequence = _snapshot_string_tuple(
            self.trace_sequence,
            "trace_sequence",
        )
        if isinstance(self.tool_trace, (str, bytes)) or not isinstance(
            self.tool_trace, Sequence
        ):
            raise RuntimeTraceError("'tool_trace' must be a sequence.")
        tool_trace = tuple(self.tool_trace)
        if any(
            not isinstance(entry, InvestigationToolTraceEntry)
            for entry in tool_trace
        ):
            raise RuntimeTraceError(
                "'tool_trace' must contain InvestigationToolTraceEntry values."
            )
        trace_call_ids = tuple(entry.tool_call_id for entry in tool_trace)
        trace_tool_names = tuple(entry.tool_name for entry in tool_trace)
        trace_observation_ids = tuple(
            observation_id
            for entry in tool_trace
            for observation_id in entry.observation_ids
        )
        if len(tool_trace) != self.tool_calls_count:
            raise RuntimeTraceError(
                "tool_trace length must equal tool_calls_count."
            )
        if trace_call_ids != tool_call_ids:
            raise RuntimeTraceError(
                "tool_trace call IDs must exactly match tool_call_ids."
            )
        if trace_tool_names != tools_used:
            raise RuntimeTraceError(
                "tool_trace tool names must exactly match tools_used."
            )
        if trace_observation_ids != observation_ids:
            raise RuntimeTraceError(
                "tool_trace observation IDs must exactly match observation_ids."
            )
        if len(observation_ids) != self.observation_count:
            raise RuntimeTraceError(
                "observation_ids length must equal observation_count."
            )
        if len(set(tool_call_ids)) != len(tool_call_ids):
            raise RuntimeTraceError("tool_call_ids must not contain duplicates.")
        if len(set(observation_ids)) != len(observation_ids):
            raise RuntimeTraceError("observation_ids must not contain duplicates.")

        object.__setattr__(self, "tools_used", tools_used)
        object.__setattr__(self, "tool_call_ids", tool_call_ids)
        object.__setattr__(self, "observation_ids", observation_ids)
        object.__setattr__(self, "tool_trace", tool_trace)
        object.__setattr__(self, "trace_sequence", trace_sequence)


def create_investigation_agent(
    analytics_tools: AnalyticsTools,
    *,
    model: Any,
    budget_guard: ToolCallBudgetGuard,
) -> Agent:
    """Create a bounded MetricSleuth Agent without encoding an investigation workflow."""
    tools = create_investigation_tools(analytics_tools, budget_guard=budget_guard)
    return Agent(
        name="MetricSleuthInvestigationAgent",
        model=model,
        tools=list(tools),
        instructions=(
            "Investigate the requested business metric using only the available controlled "
            "analytics tools. When semantic meaning is needed, use get_metric_definition and "
            "do not invent metric formulas, dependencies, relationships, units, or dimensions. "
            "Inspect every returned Observation before deciding whether another query is useful. "
            "Choose tools, metrics, filters, and grouping dimensions from semantic definitions "
            "and evidence available in the conversation; do not follow a fixed drill-down sequence. Stop when "
            "the question is answered, evidence is insufficient, or the tool budget is exhausted. "
            "Report data-level anomaly contribution only and never claim an external business root cause."
        ),
    )


def verify_investigation_trace(
    result: RunResult,
    *,
    allowed_tool_names: Sequence[str] = INVESTIGATION_TOOL_NAMES,
    max_tool_calls: int = DEFAULT_INVESTIGATION_TOOL_BUDGET,
    max_turns: int = DEFAULT_INVESTIGATION_MAX_TURNS,
) -> InvestigationRunSummary:
    """Audit a multi-tool SDK trace using public RunResult and RunItem fields only."""
    _positive_int(max_tool_calls, "max_tool_calls")
    _positive_int(max_turns, "max_turns")
    allowed = tuple(allowed_tool_names)
    if not allowed or any(not isinstance(name, str) or not name.strip() for name in allowed):
        raise ValueError("'allowed_tool_names' must contain non-empty strings.")
    if len(set(allowed)) != len(allowed):
        raise ValueError("'allowed_tool_names' must not contain duplicates.")
    allowed_set = set(allowed)

    turns_count = len(result.raw_responses)
    if turns_count < 1 or turns_count > max_turns:
        raise RuntimeTraceError(
            f"Model turn count must be within 1..{max_turns}, got {turns_count}."
        )

    items = list(result.new_items)
    call_records: list[tuple[int, str, str, ToolCallItem]] = []
    output_records: dict[str, tuple[int, ToolCallOutputItem]] = {}
    trace: list[str] = []

    for index, item in enumerate(items):
        if isinstance(item, ToolCallItem):
            tool_name = _non_empty_string(item.tool_name, "ToolCallItem.tool_name")
            call_id = _non_empty_string(item.call_id, "ToolCallItem.call_id")
            if tool_name not in allowed_set:
                raise RuntimeTraceError(f"Unexpected investigation tool: '{tool_name}'.")
            if any(existing_id == call_id for _, existing_id, _, _ in call_records):
                raise RuntimeTraceError(f"Duplicate ToolCallItem.call_id: '{call_id}'.")
            call_records.append((index, call_id, tool_name, item))
            trace.append(f"ToolCall:{tool_name}:{call_id}")
        elif isinstance(item, ToolCallOutputItem):
            call_id = _non_empty_string(item.call_id, "ToolCallOutputItem.call_id")
            if call_id in output_records:
                raise RuntimeTraceError(f"Duplicate ToolCallOutputItem.call_id: '{call_id}'.")
            output_records[call_id] = (index, item)
            trace.append(f"ToolCallOutput:{call_id}")
        elif isinstance(item, MessageOutputItem):
            trace.append("MessageOutput")
        else:
            trace.append(type(item).__name__)

    if not call_records:
        raise RuntimeTraceError("Investigation trace must contain at least one tool call.")
    if len(call_records) > max_tool_calls:
        raise RuntimeBudgetExceededError(
            f"Investigation trace contains {len(call_records)} tool calls; maximum is {max_tool_calls}."
        )
    if not items or not isinstance(items[-1], MessageOutputItem):
        raise RuntimeTraceError("Investigation trace must end with the final MessageOutputItem.")

    call_ids = {call_id for _, call_id, _, _ in call_records}
    output_ids = set(output_records)
    missing_outputs = call_ids - output_ids
    orphan_outputs = output_ids - call_ids
    if missing_outputs:
        raise RuntimeTraceError(f"Missing ToolCallOutputItem for call IDs: {sorted(missing_outputs)}.")
    if orphan_outputs:
        raise RuntimeTraceError(f"Orphan ToolCallOutputItem call IDs: {sorted(orphan_outputs)}.")

    observation_ids: list[str] = []
    seen_observation_ids: set[str] = set()
    tools_used: list[str] = []
    ordered_call_ids: list[str] = []
    tool_trace: list[InvestigationToolTraceEntry] = []

    for call_index, call_id, tool_name, call_item in call_records:
        output_index, output_item = output_records[call_id]
        if output_index <= call_index:
            raise RuntimeTraceError(f"Tool output for '{call_id}' must occur after its tool call.")
        payload = _parse_output_payload(output_item.output)
        payload_call_id = _non_empty_string(payload.get("tool_call_id"), "tool output tool_call_id")
        payload_tool_name = _non_empty_string(payload.get("tool_name"), "tool output tool_name")
        if payload_call_id != call_id:
            raise RuntimeTraceError(
                f"Tool output call identity mismatch: trace '{call_id}', payload '{payload_call_id}'."
            )
        if payload_tool_name != tool_name:
            raise RuntimeTraceError(
                f"Tool output name mismatch: trace '{tool_name}', payload '{payload_tool_name}'."
            )
        arguments = _parse_tool_call_arguments(call_item)
        call_observation_ids: list[str] = []
        if tool_name == GET_METRIC_DEFINITION_TOOL_NAME:
            _verify_metric_definition_payload(payload)
            tools_used.append(tool_name)
            ordered_call_ids.append(call_id)
            tool_trace.append(
                InvestigationToolTraceEntry(
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    observation_ids=(),
                )
            )
            continue
        observations = payload.get("observations")
        if not isinstance(observations, list):
            raise RuntimeTraceError("Tool output 'observations' must be a list.")
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise RuntimeTraceError("Every observation output must be an object.")
            observation_id = _non_empty_string(
                observation.get("observation_id"), "observation_id"
            )
            observation_call_id = _non_empty_string(
                observation.get("tool_call_id"), "observation tool_call_id"
            )
            observation_tool_name = _non_empty_string(
                observation.get("tool_name"), "observation tool_name"
            )
            _non_empty_string(observation.get("status"), "observation status")
            if observation_call_id != call_id or observation_tool_name != tool_name:
                raise RuntimeTraceError(
                    f"Observation '{observation_id}' does not match its tool call identity."
                )
            if observation_id in seen_observation_ids:
                raise RuntimeTraceError(f"Duplicate observation_id in run: '{observation_id}'.")
            seen_observation_ids.add(observation_id)
            observation_ids.append(observation_id)
            call_observation_ids.append(observation_id)
        tools_used.append(tool_name)
        ordered_call_ids.append(call_id)
        tool_trace.append(
            InvestigationToolTraceEntry(
                tool_call_id=call_id,
                tool_name=tool_name,
                arguments=arguments,
                observation_ids=tuple(call_observation_ids),
            )
        )

    final_output = result.final_output
    if not isinstance(final_output, str) or not final_output.strip():
        raise RuntimeTraceError("Investigation final_output must be a non-empty string.")

    return InvestigationRunSummary(
        final_output=final_output.strip(),
        tool_calls_count=len(call_records),
        max_tool_calls=max_tool_calls,
        tools_used=tuple(tools_used),
        tool_call_ids=tuple(ordered_call_ids),
        observation_ids=tuple(observation_ids),
        observation_count=len(observation_ids),
        tool_trace=tuple(tool_trace),
        trace_sequence=tuple(trace),
        turns_count=turns_count,
        max_turns=max_turns,
    )


def extract_observation_catalog(
    result: RunResult,
    *,
    allowed_tool_names: Sequence[str] = INVESTIGATION_TOOL_NAMES,
    max_tool_calls: int = DEFAULT_INVESTIGATION_TOOL_BUDGET,
    max_turns: int = DEFAULT_INVESTIGATION_MAX_TURNS,
) -> tuple[Observation, ...]:
    """Extract trusted Observations from validated local FunctionTool outputs.

    ``verify_investigation_trace`` is deliberately the first operation.  Once the
    trace identity and ordering contract has passed, only ``ToolCallOutputItem``
    payloads are parsed.  Model messages and ``final_output`` are never used as a
    source of Observation facts.
    """
    summary = verify_investigation_trace(
        result,
        allowed_tool_names=allowed_tool_names,
        max_tool_calls=max_tool_calls,
        max_turns=max_turns,
    )

    catalog: list[Observation] = []
    rebuilt_ids: list[str] = []
    try:
        items = list(result.new_items)
    except Exception as exc:
        raise RuntimeTraceError("Investigation trace new_items must be iterable.") from exc

    outputs_by_call_id = {
        item.call_id: item
        for item in items
        if isinstance(item, ToolCallOutputItem)
    }
    # Tool outputs may complete out of order when calls are concurrent.  The
    # verified ToolCall order is the deterministic catalog order used by the
    # summary and all downstream evidence references.
    for call_id, tool_name in zip(summary.tool_call_ids, summary.tools_used):
        if tool_name == GET_METRIC_DEFINITION_TOOL_NAME:
            continue
        item = outputs_by_call_id[call_id]
        payload = _parse_output_payload(item.output)
        observations = payload.get("observations")
        if not isinstance(observations, list):
            raise RuntimeTraceError("Tool output 'observations' must be a list.")
        for observation_payload in observations:
            observation = observation_from_json(observation_payload)
            catalog.append(observation)
            rebuilt_ids.append(observation.observation_id)

    if tuple(rebuilt_ids) != summary.observation_ids:
        raise RuntimeTraceError(
            "Observation catalog IDs do not match the validated investigation summary."
        )
    return tuple(catalog)


def run_investigation(
    prompt: str,
    *,
    analytics_tools: AnalyticsTools,
    model: Any,
    max_tool_calls: int = DEFAULT_INVESTIGATION_TOOL_BUDGET,
    max_turns: int = DEFAULT_INVESTIGATION_MAX_TURNS,
    run_config: RunConfig | None = None,
) -> InvestigationRunSummary:
    """Run one bounded investigation through the official SDK Runner."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' must be a non-empty string.")
    _positive_int(max_tool_calls, "max_tool_calls")
    _positive_int(max_turns, "max_turns")
    configure_openai_api_from_env()

    guard = ToolCallBudgetGuard(max_calls=max_tool_calls)
    agent = create_investigation_agent(
        analytics_tools,
        model=model,
        budget_guard=guard,
    )
    result = Runner.run_sync(
        agent,
        input=prompt.strip(),
        max_turns=max_turns,
        run_config=run_config,
    )
    return verify_investigation_trace(
        result,
        max_tool_calls=max_tool_calls,
        max_turns=max_turns,
    )
