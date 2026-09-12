"""Agent runtime package for MetricSleuth.

Provides OpenAI Agents SDK runtime integration, tool adapters, and structured output models.
"""

from app.agent_runtime.investigation_tools import (
    DEFAULT_INVESTIGATION_TOOL_BUDGET,
    DimensionFilter,
    GET_METRIC_DEFINITION_TOOL_NAME,
    create_get_metric_definition_tool,
    create_investigation_tools,
    create_query_metric_tool,
    create_query_related_metrics_tool,
    observation_from_json,
    observation_to_json,
    get_metric_definition_adapter,
    query_metric_observations_adapter,
    query_related_metrics_observations_adapter,
)
from app.agent_runtime.investigation_runtime import (
    DEFAULT_INVESTIGATION_MAX_TURNS,
    INVESTIGATION_TOOL_NAMES,
    InvestigationRunSummary,
    InvestigationToolTraceEntry,
    create_investigation_agent,
    extract_observation_catalog,
    run_investigation,
    verify_investigation_trace,
)
from app.agent_runtime.diagnosis_intent import (
    RuntimeDiagnosisIntent,
    RuntimeEvidenceSelection,
    RuntimeScopeItem,
    runtime_intent_to_drafts,
)
from app.agent_runtime.diagnosis_runtime import (
    DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
    DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
    EvidenceDrivenRunSummary,
    create_evidence_driven_agent,
    run_evidence_driven_diagnosis,
)

from app.agent_runtime.spike import (
    RuntimeBudgetExceededError,
    RuntimeConfigError,
    RuntimeSpikeError,
    RuntimeSpikeOutput,
    RuntimeSpikeRunSummary,
    RuntimeTraceError,
    RuntimeValidationError,
    ToolCallBudgetGuard,
    cross_validate_structured_output,
    run_runtime_spike,
    verify_runtime_trace_and_budget,
)

__all__ = [
    "DEFAULT_INVESTIGATION_TOOL_BUDGET",
    "DEFAULT_INVESTIGATION_MAX_TURNS",
    "DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS",
    "DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS",
    "DimensionFilter",
    "GET_METRIC_DEFINITION_TOOL_NAME",
    "INVESTIGATION_TOOL_NAMES",
    "InvestigationRunSummary",
    "InvestigationToolTraceEntry",
    "EvidenceDrivenRunSummary",
    "RuntimeBudgetExceededError",
    "RuntimeDiagnosisIntent",
    "RuntimeEvidenceSelection",
    "RuntimeScopeItem",
    "RuntimeConfigError",
    "RuntimeSpikeError",
    "RuntimeSpikeOutput",
    "RuntimeSpikeRunSummary",
    "RuntimeTraceError",
    "RuntimeValidationError",
    "ToolCallBudgetGuard",
    "create_get_metric_definition_tool",
    "create_investigation_tools",
    "create_investigation_agent",
    "create_evidence_driven_agent",
    "extract_observation_catalog",
    "create_query_metric_tool",
    "create_query_related_metrics_tool",
    "cross_validate_structured_output",
    "get_metric_definition_adapter",
    "observation_to_json",
    "observation_from_json",
    "query_metric_observations_adapter",
    "query_related_metrics_observations_adapter",
    "run_investigation",
    "run_evidence_driven_diagnosis",
    "runtime_intent_to_drafts",
    "run_runtime_spike",
    "verify_runtime_trace_and_budget",
    "verify_investigation_trace",
]
