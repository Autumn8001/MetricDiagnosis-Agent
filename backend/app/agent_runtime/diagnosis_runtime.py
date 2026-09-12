"""Hermetic Evidence-driven Diagnosis runtime integration.

The official Agents SDK owns the model/tool loop.  This module only wires the
existing investigation tools to the fact-free diagnosis intent and then sends
the resulting, audited Observation catalog through the existing domain
composition boundary.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

from agents import Agent, RunConfig, RunResult, Runner

from app.agent_runtime.diagnosis_intent import (
    RuntimeDiagnosisIntent,
    runtime_intent_to_drafts,
)
from app.agent_runtime.investigation_runtime import (
    DEFAULT_INVESTIGATION_MAX_TURNS,
    INVESTIGATION_TOOL_NAMES,
    InvestigationRunSummary,
    extract_observation_catalog,
    verify_investigation_trace,
)
from app.agent_runtime.investigation_tools import (
    DEFAULT_INVESTIGATION_TOOL_BUDGET,
    create_investigation_tools,
)
from app.agent_runtime.spike import RuntimeTraceError, ToolCallBudgetGuard
from app.analytics.tools import AnalyticsTools
from app.diagnosis.composition import (
    DiagnosisComposition,
    compose_diagnosis_from_observations,
)


DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS = DEFAULT_INVESTIGATION_TOOL_BUDGET
DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS = DEFAULT_INVESTIGATION_MAX_TURNS
_STRUCTURED_TRACE_SENTINEL = "structured-diagnosis-output"


@dataclass(frozen=True)
class EvidenceDrivenRunSummary:
    """Immutable audit summary paired with the resolved Diagnosis composition."""

    investigation: InvestigationRunSummary
    composition: DiagnosisComposition

    def __post_init__(self) -> None:
        if not isinstance(self.investigation, InvestigationRunSummary):
            raise RuntimeTraceError(
                "Field 'investigation' must be an InvestigationRunSummary."
            )
        if not isinstance(self.composition, DiagnosisComposition):
            raise RuntimeTraceError(
                "Field 'composition' must be a DiagnosisComposition."
            )


def create_evidence_driven_agent(
    analytics_tools: AnalyticsTools,
    *,
    model: Any,
    budget_guard: ToolCallBudgetGuard,
) -> Agent:
    """Create an SDK Agent whose output is fact-free diagnosis intent.

    The prompt describes the evidence boundary but intentionally does not
    prescribe a metric or dimension drill-down order.  Tool outputs are the
    only source of Observation identifiers and facts; the final structured
    output contains references and diagnosis intent only.
    """
    tools = create_investigation_tools(analytics_tools, budget_guard=budget_guard)
    return Agent(
        name="MetricSleuthEvidenceDrivenDiagnosisAgent",
        model=model,
        tools=list(tools),
        output_type=RuntimeDiagnosisIntent,
        instructions=(
            "Investigate the requested business metric using only the available controlled "
            "analytics tools. When semantic meaning is needed, use get_metric_definition and "
            "do not invent metric formulas, dependencies, relationships, units, or dimensions. "
            "Choose tools, metrics, filters, and grouping dimensions from semantic definitions "
            "and observations returned by the tools; do not follow a fixed drill-down sequence. "
            "For query_metric and query_related_metrics, the current period is exactly one day: "
            "set start_date and end_date both to the requested target date. Request the seven-day "
            "baseline with compare_to='previous_7_days'; never encode the baseline by widening "
            "the current-period date range. "
            "Treat tool Output as the sole source of factual Observation IDs. In your final "
            "structured intent, cite only Observation IDs that appeared in tool Output and use "
            "the deterministic Evidence ID format evidence:{observation_id}:{role}. "
            "Allowed roles are 'supporting', 'negative_control', or 'limitation'. "
            "For 'diagnosed' status: set primary_driver to the identified driver metric, provide "
            "the identified affected_scope items (dimension and value), and cite target_evidence_id "
            "from the target metric observation. "
            "For 'no_material_anomaly' status: set primary_driver to null and affected_scope to []. "
            "Always include at least one limitation in limitations (e.g. 'Data-level contribution only'). "
            "Set confidence to a decimal string in [0, 1] (e.g. '0.90'). "
            "Do not invent current values, baseline values, relative changes, units, periods, "
            "dimensions, sample sizes, or error details. Do not provide an external business "
            "root cause. If the available evidence cannot support a successful diagnosis, use "
            "an appropriate non-success status and state the limitation; budget or tool failure "
            "may finish without evidence."
        ),
    )


def _trace_audit_view(result: RunResult) -> SimpleNamespace:
    """Adapt structured SDK output to the legacy string-only trace audit.

    ``verify_investigation_trace`` predates structured output and intentionally
    requires a non-empty string ``final_output``.  Its trace facts are still
    valid for this run, so preserve the original ``new_items`` and
    ``raw_responses`` objects and replace only that audit-only field.  The
    caller separately checks the real structured output after the audit.
    """
    try:
        new_items = result.new_items
        raw_responses = result.raw_responses
    except AttributeError as exc:
        raise RuntimeTraceError("SDK RunResult is missing trace fields.") from exc
    return SimpleNamespace(
        new_items=new_items,
        raw_responses=raw_responses,
        final_output=_STRUCTURED_TRACE_SENTINEL,
    )


def run_evidence_driven_diagnosis(
    prompt: str,
    *,
    diagnosis_id: str,
    analytics_tools: AnalyticsTools,
    model: Any,
    max_tool_calls: int = DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
    max_turns: int = DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
    run_config: RunConfig | None = None,
    created_at: datetime.datetime | None = None,
) -> EvidenceDrivenRunSummary:
    """Run one bounded SDK investigation and resolve a structured Diagnosis.

    This function has no independent agent loop.  ``Runner.run_sync`` executes
    the official SDK loop, then the existing trace verifier, Observation
    extractor, and domain composition resolver provide the trust boundaries.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' must be a non-empty string.")
    if not isinstance(diagnosis_id, str) or not diagnosis_id.strip():
        raise ValueError("'diagnosis_id' must be a non-empty string.")
    if isinstance(max_tool_calls, bool) or not isinstance(max_tool_calls, int) or max_tool_calls <= 0:
        raise ValueError("'max_tool_calls' must be a positive integer.")
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns <= 0:
        raise ValueError("'max_turns' must be a positive integer.")

    guard = ToolCallBudgetGuard(max_calls=max_tool_calls)
    agent = create_evidence_driven_agent(
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

    audit_result = _trace_audit_view(result)
    investigation = verify_investigation_trace(
        audit_result,
        allowed_tool_names=INVESTIGATION_TOOL_NAMES,
        max_tool_calls=max_tool_calls,
        max_turns=max_turns,
    )
    observation_catalog = extract_observation_catalog(
        audit_result,
        allowed_tool_names=INVESTIGATION_TOOL_NAMES,
        max_tool_calls=max_tool_calls,
        max_turns=max_turns,
    )

    final_output = result.final_output
    if not isinstance(final_output, RuntimeDiagnosisIntent):
        raise RuntimeTraceError(
            "Evidence-driven run final_output must be a RuntimeDiagnosisIntent, "
            f"got {type(final_output).__name__}."
        )
    investigation = replace(
        investigation,
        final_output=final_output.model_dump_json(),
    )

    evidence_selection_draft, diagnosis_draft = runtime_intent_to_drafts(final_output)
    timestamp = (
        datetime.datetime.now(datetime.timezone.utc)
        if created_at is None
        else created_at
    )
    composition = compose_diagnosis_from_observations(
        diagnosis_id=diagnosis_id.strip(),
        evidence_selection_draft=evidence_selection_draft,
        diagnosis_draft=diagnosis_draft,
        observation_catalog=observation_catalog,
        created_at=timestamp,
    )
    return EvidenceDrivenRunSummary(
        investigation=investigation,
        composition=composition,
    )


__all__ = [
    "DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS",
    "DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS",
    "EvidenceDrivenRunSummary",
    "RuntimeTraceError",
    "create_evidence_driven_agent",
    "run_evidence_driven_diagnosis",
]
