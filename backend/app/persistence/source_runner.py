"""Source-bound adapter from persisted tasks to the existing SDK runtime.

This module binds one in-memory source descriptor, semantic registry and
capability contract to the existing Evidence-driven diagnosis runtime.  It does
not own an Agent loop, select scenarios, open long-lived database connections,
discover environment configuration, or migrate a database.  The default
diagnosis Runtime retains its existing ``OPENAI_API_MODE`` and
``OPENAI_AGENTS_DISABLE_TRACING`` bootstrap for compatibility; this adapter
still passes an explicit RunConfig with tracing disabled for each task.
The bound ``data_version`` is a provenance label and does not imply a database
snapshot or repeatable read across separate analytics queries.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import datetime
import json
import unicodedata
from typing import Any

from agents import RunConfig

from app.agent_runtime.diagnosis_runtime import run_evidence_driven_diagnosis
from app.analytics.read_connection import (
    AnalyticsConnectionFactory,
    ShortReadConnection as _ShortReadConnection,
)
from app.analytics.tools import AnalyticsTools
from app.data_sources.capabilities import (
    CapabilityContractError,
    DataSourceCapabilities,
    DataSourceDescriptor,
)
from app.metrics.registry import MetricRegistry
from app.persistence.task_execution_service import InvestigationTaskRequest


DiagnosisRunner = Callable[..., Any]
_TASK_PARAMETER_KEYS = frozenset({"target_date", "filters", "group_by"})
_MAX_FILTER_VALUE_LENGTH = 256
_MAX_PROMPT_LENGTH = 16_384


class SourceRunnerConfigurationError(ValueError):
    """Raised when the source-bound runtime adapter is configured incorrectly."""


class SourceRunnerRequestError(ValueError):
    """Raised when a persisted task does not match this runner's source binding."""


class _BoundAnalyticsTools(AnalyticsTools):
    """Analytics tools that cannot escape one task's date and fixed filters."""

    def __init__(
        self,
        registry: MetricRegistry,
        connection: _ShortReadConnection,
        capabilities: DataSourceCapabilities,
        *,
        target_date: datetime.date,
        fixed_filters: Mapping[str, str],
    ) -> None:
        super().__init__(registry, connection, capabilities)
        self._target_date = target_date
        self._fixed_filters = dict(fixed_filters)

    def query_metric(
        self,
        metric: str,
        start_date: datetime.date,
        end_date: datetime.date,
        compare_to: str,
        filters: Mapping[str, str] | None = None,
        group_by: Sequence[str] | None = None,
    ):
        if (
            not isinstance(start_date, datetime.date)
            or isinstance(start_date, datetime.datetime)
            or not isinstance(end_date, datetime.date)
            or isinstance(end_date, datetime.datetime)
            or start_date != self._target_date
            or end_date != self._target_date
            or compare_to != "previous_7_days"
        ):
            raise ValueError("task query must match its bound date and comparison")

        if filters is not None and not isinstance(filters, Mapping):
            raise ValueError("filters must be a mapping")
        for dimension, value in self._fixed_filters.items():
            if filters is None or dimension not in filters or filters[dimension] != value:
                raise ValueError(
                    "query must explicitly include each task-bound filter unchanged"
                )

        # The inherited analytics boundary validates the metric, dimensions,
        # filters and their source capability contract before opening a cursor.
        return super().query_metric(
            metric=metric,
            start_date=start_date,
            end_date=end_date,
            compare_to=compare_to,
            filters=filters,
            group_by=group_by,
        )


class SourceInvestigationRunner:
    """Run a persisted task through the existing SDK diagnosis runtime."""

    def __init__(
        self,
        *,
        binding: Any,
        registry: MetricRegistry,
        analytics_connection_factory: AnalyticsConnectionFactory,
        model: Any,
        max_tool_calls: int = 8,
        max_turns: int = 8,
        diagnosis_runner: DiagnosisRunner = run_evidence_driven_diagnosis,
    ) -> None:
        if not isinstance(registry, MetricRegistry):
            raise SourceRunnerConfigurationError("registry must be a MetricRegistry")
        descriptor = getattr(binding, "descriptor", None)
        capabilities = getattr(binding, "capabilities", None)
        data_version = getattr(binding, "data_version", None)
        if not isinstance(descriptor, DataSourceDescriptor):
            raise SourceRunnerConfigurationError(
                "binding.descriptor must be a DataSourceDescriptor"
            )
        if not isinstance(capabilities, DataSourceCapabilities):
            raise SourceRunnerConfigurationError(
                "binding.capabilities must be DataSourceCapabilities"
            )
        if capabilities.descriptor != descriptor:
            raise SourceRunnerConfigurationError(
                "capabilities descriptor must match runner descriptor"
            )
        if not isinstance(data_version, str) or not data_version.strip():
            raise SourceRunnerConfigurationError("binding.data_version must be non-empty")
        if not callable(analytics_connection_factory):
            raise SourceRunnerConfigurationError(
                "analytics_connection_factory must be callable"
            )
        if model is None:
            raise SourceRunnerConfigurationError("model must be configured")
        if isinstance(max_tool_calls, bool) or not isinstance(max_tool_calls, int) or max_tool_calls <= 0:
            raise SourceRunnerConfigurationError("max_tool_calls must be positive")
        if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns <= 0:
            raise SourceRunnerConfigurationError("max_turns must be positive")
        if not callable(diagnosis_runner):
            raise SourceRunnerConfigurationError("diagnosis_runner must be callable")

        self._registry = registry
        self._descriptor = descriptor
        self._capabilities = capabilities
        self._binding = binding
        self._data_version = data_version.strip()
        self._analytics_connection_factory = analytics_connection_factory
        self._model = model
        self._max_tool_calls = max_tool_calls
        self._max_turns = max_turns
        self._diagnosis_runner = diagnosis_runner

    def __call__(
        self,
        request: InvestigationTaskRequest,
        progress_callback: Callable[[Any, tuple[Any, ...]], None] | None = None,
    ) -> Any:
        target_date, fixed_filters, requested_group_by = self._validate_request(request)
        prompt = _build_prompt(
            metric=request.requested_metric,
            target_date=target_date,
            filters=fixed_filters,
            group_by=requested_group_by,
        )
        tools = _BoundAnalyticsTools(
            self._registry,
            _ShortReadConnection(self._analytics_connection_factory),
            self._capabilities,
            target_date=target_date,
            fixed_filters=fixed_filters,
        )
        run_config = RunConfig(
            tracing_disabled=True,
            trace_include_sensitive_data=False,
        )
        return self._diagnosis_runner(
            prompt,
            diagnosis_id=f"diagnosis:{request.run_id}",
            analytics_tools=tools,
            model=self._model,
            max_tool_calls=self._max_tool_calls,
            max_turns=self._max_turns,
            run_config=run_config,
            progress_callback=progress_callback,
            include_definition_tool=False,
            required_filters=fixed_filters,
        )

    def _validate_request(
        self,
        request: InvestigationTaskRequest,
    ) -> tuple[datetime.date, dict[str, str], tuple[str, ...]]:
        if not isinstance(request, InvestigationTaskRequest):
            raise SourceRunnerRequestError("request must be an InvestigationTaskRequest")
        if request.descriptor != self._descriptor:
            raise SourceRunnerRequestError("request source does not match runner binding")
        if request.data_version != self._data_version:
            raise SourceRunnerRequestError("request data version does not match runner binding")
        if not self._registry.has_metric(request.requested_metric):
            raise SourceRunnerRequestError("requested metric is not in the semantic registry")

        parameters = request.parameters
        if not isinstance(parameters, Mapping) or set(parameters) != _TASK_PARAMETER_KEYS:
            raise SourceRunnerRequestError("task parameters must contain only date, filters and group_by")
        raw_date = parameters.get("target_date")
        if not isinstance(raw_date, str):
            raise SourceRunnerRequestError("target_date must be an ISO calendar date")
        try:
            target_date = datetime.date.fromisoformat(raw_date)
        except ValueError:
            raise SourceRunnerRequestError("target_date must be an ISO calendar date") from None
        if target_date.isoformat() != raw_date:
            raise SourceRunnerRequestError("target_date must use YYYY-MM-DD format")

        raw_filters = parameters.get("filters")
        if not isinstance(raw_filters, Mapping):
            raise SourceRunnerRequestError("filters must be a string mapping")
        fixed_filters: dict[str, str] = {}
        for dimension, value in raw_filters.items():
            if (
                not isinstance(dimension, str)
                or not dimension.strip()
                or not isinstance(value, str)
                or len(value) > _MAX_FILTER_VALUE_LENGTH
                or any(unicodedata.category(character) == "Cc" for character in value)
            ):
                raise SourceRunnerRequestError("filters must contain bounded strings")
            fixed_filters[dimension] = value

        raw_group_by = parameters.get("group_by")
        if (
            isinstance(raw_group_by, (str, bytes))
            or not isinstance(raw_group_by, Sequence)
            or any(not isinstance(item, str) for item in raw_group_by)
        ):
            raise SourceRunnerRequestError("group_by must be a sequence of dimensions")
        try:
            normalized_group_by, normalized_filter_dims = self._capabilities.validate_query(
                request.requested_metric,
                group_by=raw_group_by,
                filters=fixed_filters,
            )
        except CapabilityContractError:
            raise SourceRunnerRequestError("requested metric or dimensions are unsupported") from None
        if set(normalized_filter_dims) != set(fixed_filters):
            raise SourceRunnerRequestError("filters must use canonical dimension names")
        return target_date, fixed_filters, normalized_group_by

    def __repr__(self) -> str:
        return (
            "SourceInvestigationRunner(source_id=[bound], model=[configured], "
            f"max_tool_calls={self._max_tool_calls}, max_turns={self._max_turns})"
        )


def _build_prompt(
    *,
    metric: str,
    target_date: datetime.date,
    filters: Mapping[str, str],
    group_by: Sequence[str],
) -> str:
    """Serialize only the requested investigation fields and fixed instructions."""
    payload = {
        "metric": metric,
        "target_date": target_date.isoformat(),
        "compare_to": "previous_7_days",
        "filters": dict(filters),
        "group_by": list(group_by),
        "investigation_request": (
            "Use the controlled analytics tools to inspect the requested metric, "
            "follow relevant evidence, and report only data-supported findings. "
            "Every analytics tool call must explicitly include each supplied filter "
            "with its exact value; these filters define the data scope and cannot "
            "be omitted or changed. MANDATORY TOOL ARGUMENT RULE: copy the complete "
            "filters object from this request into every query_metric and "
            "query_related_metrics call, including the first query. Never send "
            "filters=null or an empty filters object when this request has fixed filters."
        ),
        "mandatory_query_filters": dict(filters),
    }
    prompt = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(prompt) > _MAX_PROMPT_LENGTH:
        raise SourceRunnerRequestError("serialized task prompt exceeds its size limit")
    return prompt
