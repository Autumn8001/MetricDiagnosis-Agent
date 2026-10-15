"""OpenAI Agents SDK bridges for controlled MetricSleuth analytics queries.

This module only adapts existing AnalyticsTools results into traceable Observation
payloads. The SDK Runner remains responsible for choosing whether and how to call
these tools; no investigation workflow or next-dimension policy lives here.
"""

from __future__ import annotations

import datetime
import copy
from decimal import Decimal, DecimalException
import re
from typing import Any, Callable, Mapping, Sequence

from agents import FunctionTool, function_tool
from agents.tool_context import ToolContext
from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.spike import RuntimeTraceError, ToolCallBudgetGuard
from app.analytics.models import DateRange
from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricDefinition
from app.observations.mapper import observations_from_tool_result
from app.observations.models import Observation, ObservationStatus


DEFAULT_INVESTIGATION_TOOL_BUDGET = 8
GET_METRIC_DEFINITION_TOOL_NAME = "get_metric_definition"
_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

_OBSERVATION_JSON_KEYS = frozenset(
    {
        "observation_id",
        "tool_name",
        "tool_call_id",
        "metric",
        "current_period",
        "baseline_period",
        "filters",
        "group_by",
        "dimensions",
        "current_value",
        "baseline_value",
        "relative_change",
        "unit",
        "sample_size",
        "source_status",
        "status",
        "query_or_result_reference",
        "created_at",
        "error_code",
        "error_message",
    }
)
_PERIOD_JSON_KEYS = frozenset({"start_date", "end_date"})
_METRIC_DEFINITION_JSON_KEYS = frozenset(
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
_DIAGNOSIS_PROTOCOL = (
    "A primary_driver must be a metric identifier, never a dimension or dimension "
    "value. If a related metric is anomalous, investigate it across relevant allowed "
    "dimensions before diagnosed. For a diagnosed result, select one anomalous supporting Observation whose "
    "metric equals primary_driver and whose filters plus dimensions cover every "
    "affected_scope item. Do not combine a driver from one Observation with scope "
    "from another. Copy IDs character-for-character; use that Observation's "
    "evidence:{observation_id}:supporting value as driver_evidence_id. If no one "
    "Observation jointly supports the claim, continue investigating or use a "
    "non-success status."
)


def _require_bound_filters(tool: FunctionTool, required_filters: Mapping[str, str] | None) -> FunctionTool:
    """Make task-bound filter keys mandatory in the model-facing tool schema."""
    if not required_filters:
        return tool
    schema = copy.deepcopy(tool.params_json_schema)
    filters_schema = dict(schema.get("properties", {}).get("filters", {}))
    filters_schema.pop("anyOf", None)
    properties = dict(filters_schema.get("properties", {}))
    for key, value in required_filters.items():
        properties[key] = {"type": "string", "const": value}
    filters_schema.update({"type": "object", "properties": properties})
    filters_schema["required"] = list(required_filters)
    filters_schema.pop("default", None)
    schema.setdefault("properties", {})["filters"] = filters_schema
    schema["required"] = list(dict.fromkeys([*schema.get("required", []), "filters"]))
    tool.params_json_schema = schema
    return tool


class DimensionFilter(BaseModel):
    """Legacy structured filter item kept for package API compatibility.

    Production FunctionTools expose filters as a string-valued JSON object map;
    this model remains available to callers importing the earlier public symbol.
    """

    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(
        min_length=1,
        description="Semantic dimension name, such as marketplace or asin.",
    )
    value: str = Field(
        description="String value for the selected semantic dimension, such as US.",
    )


def _parse_iso_date(value: str, field_name: str) -> datetime.date:
    """Parse one canonical YYYY-MM-DD date without coercion or whitespace trimming."""
    if not isinstance(value, str) or _ISO_DATE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"'{field_name}' must use canonical YYYY-MM-DD format.")
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"'{field_name}' must be a valid calendar date in YYYY-MM-DD format.") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"'{field_name}' must use canonical YYYY-MM-DD format.")
    return parsed


def _decimal_to_string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _metric_definition_to_json(definition: MetricDefinition) -> dict[str, Any]:
    """Serialize only fields declared by the semantic registry."""
    if not isinstance(definition, MetricDefinition):
        raise TypeError(
            f"Expected MetricDefinition, got {type(definition).__name__}."
        )
    return {
        "metric_id": definition.metric_id,
        "display_name": definition.display_name,
        "description": definition.description,
        "metric_type": definition.metric_type,
        "unit": definition.unit,
        "formula": definition.formula,
        "source_fields": list(definition.source_fields),
        "dimensions": list(definition.dimensions),
        "dependencies": list(definition.dependencies),
        "driver_metrics": list(definition.driver_metrics),
        "related_metrics": list(definition.related_metrics),
    }


def _report_tool_progress(
    context: ToolContext,
    payload: Mapping[str, Any],
    progress_callback: Callable[[Any, tuple[Observation, ...]], None] | None,
) -> None:
    """Report a completed tool result using the same facts as the SDK payload."""
    if progress_callback is None:
        return

    # Keep this import local: investigation_runtime owns the canonical trace
    # argument parser and imports this module for the SDK tools.
    from types import SimpleNamespace

    from app.agent_runtime.investigation_runtime import (
        InvestigationToolTraceEntry,
        _parse_tool_call_arguments,
    )

    tool_call_id = payload.get("tool_call_id")
    tool_name = payload.get("tool_name")
    if (
        not isinstance(tool_call_id, str)
        or tool_call_id != context.tool_call_id
        or not isinstance(tool_name, str)
        or tool_name != context.tool_name
    ):
        raise RuntimeTraceError("Completed tool payload identity does not match SDK context.")

    # ToolContext.tool_arguments preserves the original JSON supplied to the
    # SDK. Do not rebuild it from Python parameters: omitted schema defaults
    # must remain omitted in the persisted trace.
    call_item = SimpleNamespace(
        raw_item=SimpleNamespace(arguments=context.tool_arguments)
    )
    arguments = _parse_tool_call_arguments(call_item)

    observation_payloads = payload.get("observations", [])
    if not isinstance(observation_payloads, list):
        raise RuntimeTraceError("Completed tool observations must be a list.")
    observations = tuple(
        observation_from_json(item) for item in observation_payloads
    )
    trace_entry = InvestigationToolTraceEntry(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        observation_ids=tuple(item.observation_id for item in observations),
    )
    # Deliberately do not catch callback errors. A persistence failure must
    # fail the tool invocation so the run cannot report unpersisted progress.
    progress_callback(trace_entry, observations)


def get_metric_definition_adapter(
    analytics_tools: AnalyticsTools,
    *,
    tool_call_id: str,
    metric: str,
    budget_guard: ToolCallBudgetGuard,
) -> dict[str, Any]:
    """Read one injected semantic definition under the shared run budget."""
    budget_guard.check_and_consume(GET_METRIC_DEFINITION_TOOL_NAME)
    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        raise ValueError("SDK ToolContext must provide a non-empty tool_call_id.")
    if not isinstance(metric, str) or not metric.strip():
        raise ValueError("'metric' must be a non-empty string.")

    clean_metric = metric.strip()
    definition = analytics_tools.get_metric_definition(clean_metric)
    return {
        "tool_name": GET_METRIC_DEFINITION_TOOL_NAME,
        "tool_call_id": tool_call_id,
        "metric": clean_metric,
        "definition": _metric_definition_to_json(definition),
    }


def observation_to_json(observation: Observation) -> dict[str, Any]:
    """Serialize an Observation at the explicit SDK tool-output JSON boundary."""
    if not isinstance(observation, Observation):
        raise TypeError(f"Expected Observation, got {type(observation).__name__}.")
    return {
        "observation_id": observation.observation_id,
        "tool_name": observation.tool_name,
        "tool_call_id": observation.tool_call_id,
        "metric": observation.metric,
        "current_period": {
            "start_date": observation.current_period.start_date.isoformat(),
            "end_date": observation.current_period.end_date.isoformat(),
        },
        "baseline_period": {
            "start_date": observation.baseline_period.start_date.isoformat(),
            "end_date": observation.baseline_period.end_date.isoformat(),
        },
        "filters": dict(observation.filters),
        "group_by": list(observation.group_by),
        "dimensions": dict(observation.dimensions),
        "current_value": _decimal_to_string(observation.current_value),
        "baseline_value": _decimal_to_string(observation.baseline_value),
        "relative_change": _decimal_to_string(observation.relative_change),
        "unit": observation.unit,
        "sample_size": _decimal_to_string(observation.sample_size),
        "source_status": observation.source_status,
        "status": observation.status.value,
        "query_or_result_reference": observation.query_or_result_reference,
        "created_at": observation.created_at.isoformat(),
        "error_code": observation.error_code,
        "error_message": observation.error_message,
    }


def _parse_observation_period(value: Any, field_name: str) -> DateRange:
    if not isinstance(value, Mapping):
        raise TypeError(f"'{field_name}' must be a mapping.")
    if set(value) != _PERIOD_JSON_KEYS:
        raise ValueError(f"'{field_name}' must contain exactly start_date and end_date.")
    start_date = _parse_iso_date(value["start_date"], f"{field_name}.start_date")
    end_date = _parse_iso_date(value["end_date"], f"{field_name}.end_date")
    return DateRange(start_date=start_date, end_date=end_date)


def _parse_string_mapping(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"'{field_name}' must be a Mapping[str, str].")
    parsed = dict(value)
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in parsed.items()):
        raise TypeError(f"'{field_name}' must be a Mapping[str, str].")
    return parsed


def _parse_group_by(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("'group_by' must be a list[str].")
    if any(not isinstance(item, str) for item in value):
        raise TypeError("'group_by' must be a list[str].")
    return list(value)


def _parse_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"'{field_name}' must be a decimal string or null.")
    try:
        parsed = Decimal(value)
    except (DecimalException, TypeError, ValueError) as exc:
        raise ValueError(f"'{field_name}' must be a valid decimal string.") from exc
    if not parsed.is_finite():
        raise ValueError(f"'{field_name}' must be finite.")
    return parsed


def _parse_created_at(value: Any) -> datetime.datetime:
    if not isinstance(value, str):
        raise TypeError("'created_at' must be an ISO datetime string.")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("'created_at' must be a valid ISO datetime string.") from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("'created_at' must be timezone-aware.")
    return parsed


def observation_from_json(payload: Mapping[str, Any]) -> Observation:
    """Rebuild one Observation from the exact JSON boundary emitted by ``observation_to_json``.

    This is intentionally a strict, fail-closed parser.  It is the only supported
    conversion from a local FunctionTool Observation payload back into the domain
    model, so malformed or non-finite values cannot enter a trusted catalog.
    """
    try:
        if not isinstance(payload, Mapping):
            raise TypeError("Observation payload must be a mapping.")
        if set(payload) != _OBSERVATION_JSON_KEYS:
            raise ValueError("Observation payload must contain exactly the serializer keys.")

        return Observation(
            observation_id=payload["observation_id"],
            tool_name=payload["tool_name"],
            tool_call_id=payload["tool_call_id"],
            metric=payload["metric"],
            current_period=_parse_observation_period(payload["current_period"], "current_period"),
            baseline_period=_parse_observation_period(payload["baseline_period"], "baseline_period"),
            filters=_parse_string_mapping(payload["filters"], "filters"),
            group_by=_parse_group_by(payload["group_by"]),
            dimensions=_parse_string_mapping(payload["dimensions"], "dimensions"),
            current_value=_parse_decimal(payload["current_value"], "current_value"),
            baseline_value=_parse_decimal(payload["baseline_value"], "baseline_value"),
            relative_change=_parse_decimal(payload["relative_change"], "relative_change"),
            unit=payload["unit"],
            sample_size=_parse_decimal(payload["sample_size"], "sample_size"),
            source_status=payload["source_status"],
            status=ObservationStatus(payload["status"]),
            query_or_result_reference=payload["query_or_result_reference"],
            created_at=_parse_created_at(payload["created_at"]),
            error_code=payload["error_code"],
            error_message=payload["error_message"],
        )
    except RuntimeTraceError:
        raise
    except Exception as exc:
        raise RuntimeTraceError("Invalid Observation JSON payload.") from exc


def _query_observations_adapter(
    analytics_tools: AnalyticsTools,
    *,
    operation: str,
    tool_call_id: str,
    metric: str,
    start_date: str,
    end_date: str,
    compare_to: str,
    filters: Mapping[str, str] | None,
    group_by: Sequence[str] | None,
    budget_guard: ToolCallBudgetGuard,
    created_at: datetime.datetime | None,
) -> dict[str, Any]:
    """Shared adapter implementation without choosing an investigation path."""
    budget_guard.check_and_consume(operation)

    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        raise ValueError("SDK ToolContext must provide a non-empty tool_call_id.")

    parsed_start = _parse_iso_date(start_date, "start_date")
    parsed_end = _parse_iso_date(end_date, "end_date")
    filter_snapshot = dict(filters) if filters is not None else {}
    group_snapshot = tuple(group_by) if group_by is not None else ()

    query = getattr(analytics_tools, operation)
    result = query(
        metric=metric,
        start_date=parsed_start,
        end_date=parsed_end,
        compare_to=compare_to,
        filters=filter_snapshot,
        group_by=group_snapshot,
    )

    timestamp = created_at or datetime.datetime.now(datetime.timezone.utc)
    observations = observations_from_tool_result(
        result,
        tool_name=operation,
        tool_call_id=tool_call_id,
        filters=filter_snapshot,
        query_or_result_reference=f"tool-result:{tool_call_id}",
        created_at=timestamp,
    )
    # Semantic definitions travel with query results so the Agent can interpret
    # a candidate metric without spending another scarce tool call.  This is a
    # registry read, not a query and never exposes benchmark ground truth.
    definition_ids = [metric]
    if operation == "query_related_metrics":
        definition_ids.extend(item.metric_id for item in result.results)
    metric_definitions = {
        metric_id: _metric_definition_to_json(
            analytics_tools.get_metric_definition(metric_id)
        )
        for metric_id in dict.fromkeys(definition_ids)
    }

    payload = {
        "tool_name": operation,
        "tool_call_id": tool_call_id,
        "metric": metric,
        "metric_definitions": metric_definitions,
        "observations": [observation_to_json(item) for item in observations],
        "diagnosis_protocol": _DIAGNOSIS_PROTOCOL,
    }
    return payload


def query_metric_observations_adapter(
    analytics_tools: AnalyticsTools,
    *,
    tool_call_id: str,
    metric: str,
    start_date: str,
    end_date: str,
    compare_to: str = "previous_7_days",
    filters: Mapping[str, str] | None = None,
    group_by: Sequence[str] | None = None,
    budget_guard: ToolCallBudgetGuard,
    created_at: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Execute query_metric and return JSON-safe traceable Observations."""
    return _query_observations_adapter(
        analytics_tools,
        operation="query_metric",
        tool_call_id=tool_call_id,
        metric=metric,
        start_date=start_date,
        end_date=end_date,
        compare_to=compare_to,
        filters=filters,
        group_by=group_by,
        budget_guard=budget_guard,
        created_at=created_at,
    )


def query_related_metrics_observations_adapter(
    analytics_tools: AnalyticsTools,
    *,
    tool_call_id: str,
    metric: str,
    start_date: str,
    end_date: str,
    compare_to: str = "previous_7_days",
    filters: Mapping[str, str] | None = None,
    group_by: Sequence[str] | None = None,
    budget_guard: ToolCallBudgetGuard,
    created_at: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Execute query_related_metrics and return flattened JSON-safe Observations."""
    return _query_observations_adapter(
        analytics_tools,
        operation="query_related_metrics",
        tool_call_id=tool_call_id,
        metric=metric,
        start_date=start_date,
        end_date=end_date,
        compare_to=compare_to,
        filters=filters,
        group_by=group_by,
        budget_guard=budget_guard,
        created_at=created_at,
    )


def create_query_metric_tool(
    analytics_tools: AnalyticsTools,
    *,
    budget_guard: ToolCallBudgetGuard,
    clock: Callable[[], datetime.datetime] | None = None,
    progress_callback: Callable[[Any, tuple[Observation, ...]], None] | None = None,
    required_filters: Mapping[str, str] | None = None,
) -> FunctionTool:
    """Create the fail-closed SDK query_metric tool."""
    now = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def query_metric(
        context: ToolContext,
        metric: str,
        start_date: str,
        end_date: str,
        compare_to: str = "previous_7_days",
        filters: dict[str, str] | None = None,
        group_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Query one controlled metric and return traceable observations.

        Args:
            metric: Metric identifier declared in the semantic registry.
            start_date: Single-day current-period date in YYYY-MM-DD format. Must equal end_date.
            end_date: Single-day current-period date in YYYY-MM-DD format. Must equal start_date.
            compare_to: Baseline strategy; use previous_7_days instead of widening the current date range.
            filters: Optional JSON object mapping each semantic dimension name to its string value.
                Example: ``{"marketplace": "US"}``. Use an object/map, not an array, tuple,
                or JSON string; do not use ``[{"dimension": "marketplace", "value": "US"}]``
                or ``["marketplace", "US"]``.
            group_by: Optional semantic dimensions used to segment the result.
        """
        payload = query_metric_observations_adapter(
            analytics_tools,
            tool_call_id=context.tool_call_id,
            metric=metric,
            start_date=start_date,
            end_date=end_date,
            compare_to=compare_to,
            filters=filters,
            group_by=group_by,
            budget_guard=budget_guard,
            created_at=now(),
        )
        _report_tool_progress(context, payload, progress_callback)
        return payload

    # A free-form string map is represented by ``additionalProperties`` in JSON
    # Schema, which the SDK's strict-schema normalizer rejects.  Keep the
    # Python/Pydantic input contract strict while allowing this schema shape;
    # invocation still rejects arrays and JSON strings before the adapter runs.
    return _require_bound_filters(
        function_tool(query_metric, failure_error_function=None, strict_mode=False), required_filters
    )


def create_get_metric_definition_tool(
    analytics_tools: AnalyticsTools,
    *,
    budget_guard: ToolCallBudgetGuard,
    progress_callback: Callable[[Any, tuple[Observation, ...]], None] | None = None,
    required_filters: Mapping[str, str] | None = None,
) -> FunctionTool:
    """Create the fail-closed production semantic-definition tool."""

    def get_metric_definition(
        context: ToolContext,
        metric: str,
    ) -> dict[str, Any]:
        """Retrieve the controlled semantic definition for a metric.

        Args:
            metric: Metric identifier to look up in the configured semantic registry.
        """
        payload = get_metric_definition_adapter(
            analytics_tools,
            tool_call_id=context.tool_call_id,
            metric=metric,
            budget_guard=budget_guard,
        )
        _report_tool_progress(context, payload, progress_callback)
        return payload

    return function_tool(get_metric_definition, failure_error_function=None)


def create_query_related_metrics_tool(
    analytics_tools: AnalyticsTools,
    *,
    budget_guard: ToolCallBudgetGuard,
    clock: Callable[[], datetime.datetime] | None = None,
    progress_callback: Callable[[Any, tuple[Observation, ...]], None] | None = None,
    required_filters: Mapping[str, str] | None = None,
) -> FunctionTool:
    """Create the fail-closed SDK query_related_metrics tool."""
    now = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def query_related_metrics(
        context: ToolContext,
        metric: str,
        start_date: str,
        end_date: str,
        compare_to: str = "previous_7_days",
        filters: dict[str, str] | None = None,
        group_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Query declared related metrics and return traceable observations.

        Args:
            metric: Source metric identifier declared in the semantic registry.
            start_date: Single-day current-period date in YYYY-MM-DD format. Must equal end_date.
            end_date: Single-day current-period date in YYYY-MM-DD format. Must equal start_date.
            compare_to: Baseline strategy; use previous_7_days instead of widening the current date range.
            filters: Optional JSON object mapping each semantic dimension name to its string value.
                Example: ``{"marketplace": "US"}``. Use an object/map, not an array, tuple,
                or JSON string; do not use ``[{"dimension": "marketplace", "value": "US"}]``
                or ``["marketplace", "US"]``.
            group_by: Optional semantic dimensions used to segment the result.
        """
        payload = query_related_metrics_observations_adapter(
            analytics_tools,
            tool_call_id=context.tool_call_id,
            metric=metric,
            start_date=start_date,
            end_date=end_date,
            compare_to=compare_to,
            filters=filters,
            group_by=group_by,
            budget_guard=budget_guard,
            created_at=now(),
        )
        _report_tool_progress(context, payload, progress_callback)
        return payload

    return _require_bound_filters(
        function_tool(query_related_metrics, failure_error_function=None, strict_mode=False),
        required_filters,
    )


def create_investigation_tools(
    analytics_tools: AnalyticsTools,
    *,
    budget_guard: ToolCallBudgetGuard | None = None,
    max_tool_calls: int = DEFAULT_INVESTIGATION_TOOL_BUDGET,
    clock: Callable[[], datetime.datetime] | None = None,
    progress_callback: Callable[[Any, tuple[Observation, ...]], None] | None = None,
    required_filters: Mapping[str, str] | None = None,
) -> tuple[FunctionTool, FunctionTool, FunctionTool]:
    """Create all controlled tools with one per-run shared call budget."""
    guard = budget_guard or ToolCallBudgetGuard(max_calls=max_tool_calls)
    return (
        create_get_metric_definition_tool(
            analytics_tools,
            budget_guard=guard,
            progress_callback=progress_callback,
            required_filters=required_filters,
        ),
        create_query_metric_tool(
            analytics_tools,
            budget_guard=guard,
            clock=clock,
            progress_callback=progress_callback,
            required_filters=required_filters,
        ),
        create_query_related_metrics_tool(
            analytics_tools,
            budget_guard=guard,
            clock=clock,
            progress_callback=progress_callback,
            required_filters=required_filters,
        ),
    )
