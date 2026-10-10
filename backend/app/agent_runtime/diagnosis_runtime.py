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
from typing import Any, Callable

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
from app.agent_runtime.spike import (
    RuntimeTraceError,
    ToolCallBudgetGuard,
    configure_openai_api_from_env,
)
from app.analytics.tools import AnalyticsTools
from app.diagnosis.composition import (
    DiagnosisComposition,
    compose_diagnosis_from_observations,
)
from app.diagnosis.models import DiagnosisStatus
from app.observations.models import Observation, ObservationStatus


DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS = DEFAULT_INVESTIGATION_TOOL_BUDGET
DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS = DEFAULT_INVESTIGATION_MAX_TURNS
_STRUCTURED_TRACE_SENTINEL = "structured-diagnosis-output"


@dataclass(frozen=True)
class EvidenceDrivenRunSummary:
    """Immutable audit summary paired with the resolved Diagnosis composition."""

    investigation: InvestigationRunSummary
    composition: DiagnosisComposition
    observation_catalog: tuple[Observation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.investigation, InvestigationRunSummary):
            raise RuntimeTraceError(
                "Field 'investigation' must be an InvestigationRunSummary."
            )
        if not isinstance(self.composition, DiagnosisComposition):
            raise RuntimeTraceError(
                "Field 'composition' must be a DiagnosisComposition."
            )

        catalog = self.observation_catalog
        if isinstance(catalog, (str, bytes)) or not isinstance(catalog, tuple | list):
            raise RuntimeTraceError(
                "Field 'observation_catalog' must be a sequence of Observation values."
            )
        catalog = tuple(catalog)
        if any(not isinstance(item, Observation) for item in catalog):
            raise RuntimeTraceError(
                "Field 'observation_catalog' must contain Observation values."
            )

        observation_ids = tuple(item.observation_id for item in catalog)
        if len(observation_ids) != len(set(observation_ids)):
            raise RuntimeTraceError(
                "Field 'observation_catalog' must not contain duplicate observation_id values."
            )
        if observation_ids != self.investigation.observation_ids:
            raise RuntimeTraceError(
                "Observation catalog IDs must exactly match the validated investigation trace."
            )

        trace_by_call_id = {
            entry.tool_call_id: entry for entry in self.investigation.tool_trace
        }
        for observation in catalog:
            trace_entry = trace_by_call_id.get(observation.tool_call_id)
            if trace_entry is None:
                raise RuntimeTraceError(
                    "Observation catalog contains an observation whose tool_call_id "
                    f"'{observation.tool_call_id}' is absent from the verified trace."
                )
            if observation.tool_name != trace_entry.tool_name:
                raise RuntimeTraceError(
                    "Observation catalog tool_name does not match the verified trace "
                    f"for tool_call_id '{observation.tool_call_id}'."
                )
            if observation.observation_id not in trace_entry.observation_ids:
                raise RuntimeTraceError(
                    "Observation catalog observation_id is not owned by the verified "
                    f"trace tool call '{observation.tool_call_id}'."
                )

        object.__setattr__(self, "observation_catalog", catalog)

    @property
    def observations(self) -> tuple[Observation, ...]:
        """Compatibility alias for callers that use the shorter catalog name."""

        return self.observation_catalog


def create_evidence_driven_agent(
    analytics_tools: AnalyticsTools,
    *,
    model: Any,
    budget_guard: ToolCallBudgetGuard,
    progress_callback: Callable[[Any, tuple[Observation, ...]], None] | None = None,
) -> Agent:
    """Create an SDK Agent whose output is fact-free diagnosis intent.

    The prompt describes the evidence boundary but intentionally does not
    prescribe a metric or dimension drill-down order.  Tool outputs are the
    only source of Observation identifiers and facts; the final structured
    output contains references and diagnosis intent only.
    """
    if progress_callback is None:
        tools = create_investigation_tools(
            analytics_tools,
            budget_guard=budget_guard,
        )
    else:
        tools = create_investigation_tools(
            analytics_tools,
            budget_guard=budget_guard,
            progress_callback=progress_callback,
        )
    return Agent(
        name="MetricSleuthEvidenceDrivenDiagnosisAgent",
        model=model,
        tools=list(tools),
        output_type=RuntimeDiagnosisIntent,
        instructions=(
            "Investigate the requested business metric using only the available controlled "
            "analytics tools. Query outputs include controlled metric definitions; use "
            "get_metric_definition only when the needed definition is not already present. "
            "driver_metrics in a definition are the direct metrics that can explain movement in "
            "that metric (they are not formula dependencies or a fixed workflow). Before a "
            "diagnosed intent names a primary_driver that has driver_metrics, observe every one "
            "of those direct drivers. If any is anomalous, continue with that anomalous driver "
            "instead of stopping at the intermediate metric. When the target definition declares "
            "related metrics, investigate the relevant related metrics to identify the primary "
            "driver before attributing scope. "
            "Each run has a hard maximum of eight analytics tool calls. Avoid duplicate evidence: "
            "when declared related metrics need comparison, use query_related_metrics before "
            "querying those same related metrics individually; reserve individual metric queries "
            "for drilling a candidate driver at a scope. Before each additional tool call, decide "
            "whether its result can change the diagnosis; if the remaining budget or evidence "
            "cannot support a successful diagnosis, finish with an appropriate non-success status. "
            "A primary_driver is always a metric identifier, never a dimension or dimension value. "
            "If a related metric is anomalous, do not use the target metric itself as its primary "
            "driver and do not finish diagnosed yet: investigate that candidate driver across "
            "relevant allowed dimensions until one driver Observation jointly supports a scope, "
            "or until the evidence or budget justifies a non-success status. "
            "When semantic meaning is needed, use get_metric_definition and "
            "do not invent metric formulas, dependencies, relationships, units, or dimensions. "
            "Choose tools, metrics, filters, and grouping dimensions from semantic definitions "
            "and observations returned by the tools; do not follow a fixed drill-down sequence. "
            "For query_metric and query_related_metrics, the current period is exactly one day: "
            "set start_date and end_date both to the requested target date. Request the seven-day "
            "baseline with compare_to='previous_7_days'; never encode the baseline by widening "
            "the current-period date range. "
            "Treat tool Output as the sole source of factual Observation IDs. In your final "
            "structured intent, copy every observation_id character-for-character from the current "
            "tool Output; never invent, derive, shorten, or paraphrase an Observation ID. Use "
            "the deterministic Evidence ID format evidence:{observation_id}:{role}. "
            "Allowed roles are 'supporting', 'negative_control', or 'limitation'. "
            "For 'diagnosed' status, one and the same selected anomalous supporting Observation "
            "must have metric equal to primary_driver and filters/dimensions covering every "
            "affected_scope dimension and value. Do not splice primary_driver from one Evidence "
            "item with affected_scope from another. Set driver_evidence_id to that exact "
            "Observation's deterministic Evidence ID and include it in evidence_ids. If no "
            "single Observation satisfies this joint support requirement, use an appropriate "
            "non-success status instead. Cite "
            "target_evidence_id from the target metric Observation. "
            "For 'no_material_anomaly' status: set primary_driver to null and affected_scope to []. "
            "Always include at least one limitation in limitations (e.g. 'Data-level contribution only'). "
            "Set confidence to a decimal string in [0, 1] (e.g. '0.90'). "
            "Do not invent current values, baseline values, relative changes, units, periods, "
            "dimensions, sample sizes, or error details. Before finishing, cross-check every "
            "observation_id and Evidence ID against the current tool outputs and ensure the "
            "diagnosed joint-support rule is satisfied. Do not provide an external business root "
            "cause. If the available evidence cannot support a successful diagnosis, use an "
            "appropriate non-success status and state the limitation; budget or tool failure may "
            "finish without evidence."
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


def _verify_primary_driver_semantic_closure(
    intent: RuntimeDiagnosisIntent,
    observation_catalog: tuple[Observation, ...],
    analytics_tools: AnalyticsTools,
) -> None:
    """Reject a diagnosed intermediate metric before domain composition.

    ``driver_metrics`` is the controlled semantic graph for *what can explain a
    metric*, distinct from formula dependencies and generic related metrics. A
    model may freely choose the investigation path, but it cannot finish on a
    non-leaf metric while declared direct drivers remain uninspected or an
    observed direct driver is anomalous.
    """
    if intent.status is not DiagnosisStatus.DIAGNOSED:
        return
    if intent.primary_driver is None:
        return

    definition = analytics_tools.get_metric_definition(intent.primary_driver)
    direct_drivers = definition.driver_metrics
    if not direct_drivers:
        return

    observed_metrics = {item.metric for item in observation_catalog}
    missing = tuple(metric for metric in direct_drivers if metric not in observed_metrics)
    if missing:
        raise RuntimeTraceError(
            "Diagnosed primary_driver is not semantically closed: declared direct "
            f"driver metrics were not observed: {', '.join(missing)}."
        )

    anomalous = tuple(
        metric
        for metric in direct_drivers
        if any(
            item.metric == metric and item.status is ObservationStatus.ANOMALOUS
            for item in observation_catalog
        )
    )
    if anomalous:
        raise RuntimeTraceError(
            "Diagnosed primary_driver is an intermediate metric with anomalous "
            f"direct driver metrics: {', '.join(anomalous)}."
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
    progress_callback: Callable[[Any, tuple[Observation, ...]], None] | None = None,
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

    configure_openai_api_from_env()

    guard = ToolCallBudgetGuard(max_calls=max_tool_calls)
    if progress_callback is None:
        agent = create_evidence_driven_agent(
            analytics_tools,
            model=model,
            budget_guard=guard,
        )
    else:
        agent = create_evidence_driven_agent(
            analytics_tools,
            model=model,
            budget_guard=guard,
            progress_callback=progress_callback,
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

    _verify_primary_driver_semantic_closure(
        final_output,
        observation_catalog,
        analytics_tools,
    )

    evidence_selection_draft, diagnosis_draft = runtime_intent_to_drafts(final_output)
    timestamp = (
        datetime.datetime.now(datetime.timezone.utc)
        if created_at is None
        else created_at
    )
    try:
        composition = compose_diagnosis_from_observations(
            diagnosis_id=diagnosis_id.strip(),
            evidence_selection_draft=evidence_selection_draft,
            diagnosis_draft=diagnosis_draft,
            observation_catalog=observation_catalog,
            created_at=timestamp,
        )
    except Exception as exc:
        # Keep the domain exception type intact.  The compact reference-only note
        # is for live-evaluation diagnosis; it never includes metric values,
        # database configuration, or provider credentials.
        exc.add_note(
            "Runtime intent references: "
            + repr(
                {
                    "status": final_output.status.value,
                    "primary_driver": final_output.primary_driver,
                    "driver_evidence_id": final_output.driver_evidence_id,
                    "affected_scope": [
                        {"dimension": item.dimension, "value": item.value}
                        for item in final_output.affected_scope
                    ],
                    "evidence_selections": [
                        {"observation_id": item.observation_id, "role": item.role.value}
                        for item in final_output.evidence_selections
                    ],
                }
            )
        )
        raise
    return EvidenceDrivenRunSummary(
        investigation=investigation,
        composition=composition,
        observation_catalog=observation_catalog,
    )


__all__ = [
    "DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS",
    "DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS",
    "EvidenceDrivenRunSummary",
    "RuntimeTraceError",
    "create_evidence_driven_agent",
    "run_evidence_driven_diagnosis",
]
