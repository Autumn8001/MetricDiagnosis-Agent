"""OpenAI Agents SDK Runtime Spike implementation for MetricSleuth.

Implements pre-execution tool budgeting, strict execution trace verification,
and structured output cross-validation using the official Python OpenAI Agents SDK.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agents import (
    Agent,
    FunctionTool,
    MessageOutputItem,
    RunResult,
    Runner,
    ToolCallItem,
    ToolCallOutputItem,
    function_tool,
    set_default_openai_api,
    set_tracing_disabled,
)
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricRegistry


class RuntimeSpikeError(Exception):
    """Base exception for runtime spike operations."""


class RuntimeConfigError(RuntimeSpikeError):
    """Raised when runtime environment configuration or credentials are missing."""


class RuntimeBudgetExceededError(RuntimeSpikeError):
    """Raised when runtime tool call or turn budgets are exceeded."""


class RuntimeTraceError(RuntimeSpikeError):
    """Raised when the execution trace violates sequential, identity, or parity invariants."""


class RuntimeValidationError(RuntimeSpikeError):
    """Raised when the structured final output fails cross-validation against factual tool outputs."""


def configure_openai_api_from_env() -> None:
    """Select the Agents SDK transport requested by the local environment."""
    api_mode = os.environ.get("OPENAI_API_MODE", "").strip().lower()
    if api_mode:
        if api_mode not in {"responses", "chat_completions"}:
            raise RuntimeConfigError(
                "Environment variable 'OPENAI_API_MODE' must be 'responses' "
                "or 'chat_completions'."
            )
        set_default_openai_api(api_mode)  # type: ignore[arg-type]

    tracing_setting = os.environ.get("OPENAI_AGENTS_DISABLE_TRACING", "").strip().lower()
    if tracing_setting:
        if tracing_setting in {"1", "true", "yes", "on"}:
            set_tracing_disabled(True)
        elif tracing_setting in {"0", "false", "no", "off"}:
            set_tracing_disabled(False)
        else:
            raise RuntimeConfigError(
                "Environment variable 'OPENAI_AGENTS_DISABLE_TRACING' must be a boolean value."
            )


def _validate_positive_int(value: Any, param_name: str) -> int:
    """Validates that a parameter is a strict positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Parameter '{param_name}' must be a positive integer, got {value!r}.")
    return value


class ToolCallBudgetGuard:
    """Thread-safe atomic budget guard for tool invocations per runtime execution."""

    def __init__(self, max_calls: int = 1) -> None:
        _validate_positive_int(max_calls, "max_calls")
        self._max_calls = max_calls
        self._calls = 0
        self._lock = threading.Lock()

    @property
    def current_calls(self) -> int:
        with self._lock:
            return self._calls

    @property
    def max_calls(self) -> int:
        return self._max_calls

    def check_and_consume(self, tool_name: str) -> None:
        """Atomically checks and consumes 1 call budget before invoking the underlying tool.

        Raises:
            RuntimeBudgetExceededError: If the tool call budget has already been exhausted.
        """
        with self._lock:
            if self._calls >= self._max_calls:
                raise RuntimeBudgetExceededError(
                    f"Tool call budget exceeded: '{tool_name}' exceeded maximum {self._max_calls} call(s)."
                )
            self._calls += 1


class RuntimeSpikeOutput(BaseModel):
    """Structured output model for MetricSleuth runtime spike."""

    metric_id: str = Field(description="The metric identifier investigated (e.g. 'sales')")
    unit: str = Field(description="The unit of the metric (e.g. 'usd')")
    tool_used: str = Field(description="The name of the tool used (e.g. 'get_metric_definition')")
    summary: str = Field(description="Brief factual summary of the metric definition")

    @field_validator("metric_id", "unit", "tool_used", "summary")
    @classmethod
    def validate_non_empty(cls, value: str, info: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string.")
        return value.strip()


def _get_default_analytics_tools() -> AnalyticsTools:
    """Creates a default AnalyticsTools instance backed by the default metrics YAML."""
    config_path = Path(__file__).resolve().parent.parent.parent.parent / "configs" / "metrics.yaml"
    if not config_path.is_file():
        config_path = Path("configs/metrics.yaml").resolve()
    registry = MetricRegistry.from_yaml(config_path)
    return AnalyticsTools(registry=registry, connection=None)


def get_metric_definition_adapter(
    tools: AnalyticsTools,
    metric_id: str,
    *,
    budget_guard: ToolCallBudgetGuard | None = None,
) -> dict[str, Any]:
    """Retrieves metric definition from AnalyticsTools with pre-execution budget enforcement.

    Raises:
        RuntimeBudgetExceededError: If the tool call budget has already been exhausted before execution.
    """
    if budget_guard is not None:
        budget_guard.check_and_consume("get_metric_definition")

    clean_id = metric_id.strip() if isinstance(metric_id, str) else str(metric_id)
    metric_def = tools.get_metric_definition(clean_id)
    return {
        "metric_id": metric_def.metric_id,
        "display_name": metric_def.display_name,
        "description": metric_def.description,
        "metric_type": metric_def.metric_type,
        "unit": metric_def.unit,
        "formula": metric_def.formula,
        "dimensions": list(metric_def.dimensions),
        "related_metrics": list(metric_def.related_metrics),
    }


def create_get_metric_definition_tool(
    analytics_tools: AnalyticsTools | None = None,
    *,
    budget_guard: ToolCallBudgetGuard | None = None,
) -> FunctionTool:
    """Creates an OpenAI Agents SDK FunctionTool wrapping AnalyticsTools.get_metric_definition.

    Uses failure_error_function=None to ensure Fail-Closed exception propagation through the Runner.
    """
    tools = analytics_tools if analytics_tools is not None else _get_default_analytics_tools()
    guard = budget_guard if budget_guard is not None else ToolCallBudgetGuard(max_calls=1)

    def get_metric_definition(metric_id: str) -> dict[str, Any]:
        """Retrieve the semantic definition, unit, calculation type, and dimensions for a metric.

        Args:
            metric_id: Identifier of the metric to look up (e.g. 'sales', 'orders', 'sessions', 'conversion_rate', 'aov').

        Returns:
            Dictionary containing metric metadata including metric_id, display_name, metric_type, unit, and dimensions.
        """
        return get_metric_definition_adapter(tools, metric_id, budget_guard=guard)

    return function_tool(get_metric_definition, failure_error_function=None)


@dataclass(frozen=True)
class RuntimeSpikeRunSummary:
    """Sanitized summary of an OpenAI Agents SDK run execution."""

    model: str
    tool_calls_count: int
    max_tool_calls: int
    tools_used: tuple[str, ...]
    tool_result_returned: bool
    final_output: RuntimeSpikeOutput
    trace_sequence: tuple[str, ...]
    turns_count: int
    max_turns: int


def _parse_tool_output_payload(raw_output: Any) -> dict[str, Any]:
    """Parses tool output payload into a dictionary."""
    if isinstance(raw_output, dict):
        return dict(raw_output)
    if isinstance(raw_output, str):
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            raise RuntimeTraceError(f"Failed to parse tool output JSON string: {e}") from e
    raise RuntimeTraceError(f"Tool output must be a dict or valid JSON dict string, got {type(raw_output).__name__}.")


def _require_non_empty_string(value: Any, field_name: str, *, error_type: type[RuntimeSpikeError]) -> str:
    """Return a normalized non-empty string or raise the requested runtime error type."""
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def verify_runtime_trace_and_budget(
    result: RunResult,
    *,
    expected_tool_name: str = "get_metric_definition",
    max_tool_calls: int = 1,
    max_turns: int = 3,
) -> tuple[int, tuple[str, ...], bool, tuple[str, ...], dict[str, Any]]:
    """Analyzes SDK RunResult items to verify tool calls, order, call ID binding, and turns budget.

    Invariants enforced:
    1. Turns count (len(result.raw_responses)) satisfies 1 <= turns_count <= max_turns.
    2. Tool call count in trace is exactly 1 and does not exceed max_tool_calls.
    3. Tool call name strictly matches expected_tool_name.
    4. Tool output call_id matches tool call call_id.
    5. Order invariant: ToolCall -> matching ToolCallOutput -> last MessageOutput.

    Returns:
        (tool_calls_count, tools_used, tool_result_returned, trace_sequence, parsed_tool_data)
    """
    _validate_positive_int(max_tool_calls, "max_tool_calls")
    _validate_positive_int(max_turns, "max_turns")

    raw_responses = getattr(result, "raw_responses", None)
    if raw_responses is None or isinstance(raw_responses, (str, bytes)):
        raise RuntimeTraceError("Invalid RunResult: missing or invalid raw_responses sequence.")
    try:
        turns_count = len(raw_responses)
    except TypeError as exc:
        raise RuntimeTraceError("Invalid RunResult: raw_responses must support len().") from exc
    if turns_count < 1:
        raise RuntimeTraceError("Zero model responses recorded in RunResult.")
    if turns_count > max_turns:
        raise RuntimeBudgetExceededError(
            f"Turns budget exceeded: actual turns {turns_count} > max_turns {max_turns}."
        )

    new_items = getattr(result, "new_items", None)
    if new_items is None or isinstance(new_items, (str, bytes)):
        raise RuntimeTraceError("Invalid RunResult: missing or invalid new_items sequence.")
    try:
        iter(new_items)
    except TypeError as exc:
        raise RuntimeTraceError("Invalid RunResult: new_items must be iterable.") from exc

    tool_call_items: list[tuple[int, ToolCallItem]] = []
    tool_output_items: list[tuple[int, ToolCallOutputItem]] = []
    message_items: list[tuple[int, MessageOutputItem]] = []
    trace_sequence: list[str] = []

    for idx, item in enumerate(new_items):
        if isinstance(item, ToolCallItem):
            tool_name = item.tool_name or ""
            tool_call_items.append((idx, item))
            trace_sequence.append(f"ToolCall:{tool_name}")
        elif isinstance(item, ToolCallOutputItem):
            tool_output_items.append((idx, item))
            trace_sequence.append("ToolCallOutput")
        elif isinstance(item, MessageOutputItem):
            message_items.append((idx, item))
            trace_sequence.append("MessageOutput")
        else:
            trace_sequence.append(type(item).__name__)

    # The runtime spike contract has exactly one tool call.  The configured
    # budget remains an upper bound so an over-budget trace reports a budget
    # failure first, but a trace containing two calls is invalid even when a
    # caller supplied a larger upper bound.
    tool_calls_count = len(tool_call_items)
    if tool_calls_count == 0:
        raise RuntimeTraceError("Trace validation failed: No tool calls found in execution trace.")
    if tool_calls_count > max_tool_calls:
        raise RuntimeBudgetExceededError(
            f"Tool call budget exceeded in trace: actual {tool_calls_count} > max {max_tool_calls}."
        )
    if tool_calls_count != 1:
        raise RuntimeTraceError(
            f"Trace validation failed: expected exactly one ToolCallItem, found {tool_calls_count}."
        )

    call_idx, call_item = tool_call_items[0]
    actual_tool_name = call_item.tool_name
    if actual_tool_name != expected_tool_name:
        raise RuntimeTraceError(
            f"Unexpected tool called in trace: {actual_tool_name!r}, expected {expected_tool_name!r}."
        )

    call_id = call_item.call_id
    if not isinstance(call_id, str) or not call_id.strip():
        raise RuntimeTraceError("ToolCallItem missing call_id in execution trace.")

    # Invariant 3: ToolCallOutput count and ID binding
    if len(tool_output_items) == 0:
        raise RuntimeTraceError("Trace validation failed: No ToolCallOutputItem found in execution trace.")
    if len(tool_output_items) > 1:
        raise RuntimeTraceError("Trace validation failed: Multiple ToolCallOutputItems found in execution trace.")

    output_idx, output_item = tool_output_items[0]
    output_call_id = output_item.call_id
    if not isinstance(output_call_id, str) or not output_call_id.strip():
        raise RuntimeTraceError("ToolCallOutputItem missing call_id in execution trace.")
    if output_call_id != call_id:
        raise RuntimeTraceError(
            f"ToolCallOutput call_id mismatch: output call_id '{output_call_id}' != call call_id '{call_id}'."
        )

    # Invariant 4: MessageOutput presence and position
    if len(message_items) == 0:
        raise RuntimeTraceError("Trace validation failed: No MessageOutputItem found in execution trace.")

    last_msg_idx, _ = message_items[-1]

    # Invariant 5: Strict partial order: ToolCall -> matching ToolCallOutput -> last MessageOutput
    if output_idx <= call_idx:
        raise RuntimeTraceError(
            f"Trace ordering violation: ToolCallOutput (index {output_idx}) appeared before ToolCall (index {call_idx})."
        )
    if last_msg_idx <= output_idx:
        raise RuntimeTraceError(
            f"Trace ordering violation: Final MessageOutput (index {last_msg_idx}) appeared before ToolCallOutput (index {output_idx})."
        )

    # Parse and validate tool output data payload
    parsed_tool_data = _parse_tool_output_payload(output_item.output)
    for required_field in ("metric_id", "unit"):
        if required_field not in parsed_tool_data:
            raise RuntimeTraceError(
                f"Tool output payload missing required '{required_field}' key."
            )
        _require_non_empty_string(
            parsed_tool_data[required_field],
            required_field,
            error_type=RuntimeTraceError,
        )

    return (
        tool_calls_count,
        (actual_tool_name,),
        True,
        tuple(trace_sequence),
        parsed_tool_data,
    )


def cross_validate_structured_output(
    final_output: RuntimeSpikeOutput,
    tool_data: dict[str, Any],
    *,
    expected_tool_name: str = "get_metric_definition",
) -> None:
    """Cross-validates that RuntimeSpikeOutput strictly matches the factual tool output."""
    if not isinstance(final_output, RuntimeSpikeOutput):
        raise RuntimeValidationError(
            f"Structured output must be RuntimeSpikeOutput, got {type(final_output).__name__}."
        )
    if not isinstance(tool_data, dict):
        raise RuntimeValidationError(
            f"Tool output data must be a dictionary, got {type(tool_data).__name__}."
        )

    expected_tool_name = _require_non_empty_string(
        expected_tool_name,
        "expected_tool_name",
        error_type=RuntimeValidationError,
    )
    if final_output.tool_used != expected_tool_name:
        raise RuntimeValidationError(
            f"Structured output tool_used '{final_output.tool_used}' does not match expected '{expected_tool_name}'."
        )

    expected_metric_id = _require_non_empty_string(
        tool_data.get("metric_id"),
        "metric_id",
        error_type=RuntimeValidationError,
    )
    if final_output.metric_id != expected_metric_id:
        raise RuntimeValidationError(
            f"Structured output metric_id '{final_output.metric_id}' does not match factual tool output '{expected_metric_id}'."
        )

    expected_unit = _require_non_empty_string(
        tool_data.get("unit"),
        "unit",
        error_type=RuntimeValidationError,
    )
    if final_output.unit != expected_unit:
        raise RuntimeValidationError(
            f"Structured output unit '{final_output.unit}' does not match factual tool output '{expected_unit}'."
        )


def run_runtime_spike(
    prompt: str | None = None,
    *,
    analytics_tools: AnalyticsTools | None = None,
    max_turns: int = 3,
    max_tool_calls: int = 1,
) -> RuntimeSpikeRunSummary:
    """Executes a minimal, real OpenAI Agents SDK run with local function tool integration.

    Fail-fast checks:
    - METRICSLEUTH_AGENT_MODEL must be non-empty in os.environ.
    - OPENAI_API_KEY must be non-empty in os.environ.
    - max_turns must be a positive integer.
    - This Phase 5 spike has a fixed tool-call budget of exactly 1.
    """
    _validate_positive_int(max_tool_calls, "max_tool_calls")
    _validate_positive_int(max_turns, "max_turns")
    if max_tool_calls != 1:
        raise ValueError(
            "Phase 5 runtime spike requires max_tool_calls=1; "
            "the fixed budget cannot be widened by callers."
        )

    model_name = os.environ.get("METRICSLEUTH_AGENT_MODEL", "").strip()
    if not model_name:
        raise RuntimeConfigError(
            "Environment variable 'METRICSLEUTH_AGENT_MODEL' is required but not set or empty."
        )

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeConfigError(
            "Environment variable 'OPENAI_API_KEY' is required but not set or empty."
        )

    configure_openai_api_from_env()

    target_prompt = (
        prompt
        if prompt is not None
        else (
            "Please use the get_metric_definition tool to look up the semantic definition "
            "for the metric 'sales', and return the structured output."
        )
    )

    budget_guard = ToolCallBudgetGuard(max_calls=max_tool_calls)
    tool = create_get_metric_definition_tool(analytics_tools, budget_guard=budget_guard)

    agent = Agent(
        name="MetricSleuthSpikeAgent",
        instructions=(
            "You are a metric investigation agent. "
            "Always call the get_metric_definition tool to look up requested metric definitions before responding. "
            "Do not guess or assume units. Return the structured definition summary."
        ),
        model=model_name,
        tools=[tool],
        output_type=RuntimeSpikeOutput,
    )

    result = Runner.run_sync(agent, input=target_prompt, max_turns=max_turns)

    final_output = result.final_output
    if not isinstance(final_output, RuntimeSpikeOutput):
        raise RuntimeSpikeError(
            f"Expected structured output RuntimeSpikeOutput, got {type(final_output).__name__}."
        )

    (
        tool_count,
        tools_used,
        tool_result_returned,
        trace_sequence,
        tool_data,
    ) = verify_runtime_trace_and_budget(
        result,
        expected_tool_name="get_metric_definition",
        max_tool_calls=max_tool_calls,
        max_turns=max_turns,
    )

    cross_validate_structured_output(
        final_output,
        tool_data,
        expected_tool_name="get_metric_definition",
    )

    turns_count = len(result.raw_responses)

    return RuntimeSpikeRunSummary(
        model=model_name,
        tool_calls_count=tool_count,
        max_tool_calls=max_tool_calls,
        tools_used=tools_used,
        tool_result_returned=tool_result_returned,
        final_output=final_output,
        trace_sequence=trace_sequence,
        turns_count=turns_count,
        max_turns=max_turns,
    )
