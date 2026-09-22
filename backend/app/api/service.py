"""Domain service coordinating metrics, scenarios, and investigation logic for the API."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from collections.abc import Mapping
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
REPOSITORY_ROOT = BACKEND_ROOT.parent if (BACKEND_ROOT / "backend").exists() else BACKEND_ROOT
# Handle running within backend directory
if (BACKEND_ROOT / "configs").exists():
    REPOSITORY_ROOT = BACKEND_ROOT
elif (BACKEND_ROOT.parent / "configs").exists():
    REPOSITORY_ROOT = BACKEND_ROOT.parent

from app.analytics.models import DateRange
from app.analytics.tools import AnalyticsTools
from app.diagnosis import (
    Diagnosis,
    DiagnosisChange,
    DiagnosisComposition,
)
from app.metrics.registry import MetricRegistry

from .schemas import (
    BudgetUsage,
    DiagnosisChangeItem,
    DiagnosisItem,
    EvidenceItem,
    InvestigationRequest,
    InvestigationResponse,
    MetricGraphEdge,
    MetricGraphNode,
    MetricGraphResponse,
    ScenarioItem,
    ScenarioListResponse,
    TraceStepItem,
)


CONFIG_PATH = REPOSITORY_ROOT / "configs" / "metrics.yaml"
SCENARIO_CATALOG_PATH = REPOSITORY_ROOT / "warehouse" / "scenario_catalog.json"
_registry: Optional[MetricRegistry] = None
_scenario_catalog: Optional[tuple["ScenarioCatalogEntry", ...]] = None
_current_scenario: str = "canonical"


@dataclass(frozen=True)
class ScenarioCatalogEntry:
    """Selector and injection metadata deliberately separated from Ground Truth."""

    scenario_id: str
    target_metric: str


def get_metric_registry() -> MetricRegistry:
    """Load or return cached MetricRegistry."""
    global _registry
    if _registry is None:
        if not CONFIG_PATH.is_file():
            raise FileNotFoundError(f"Metrics configuration not found at {CONFIG_PATH}")
        _registry = MetricRegistry.from_yaml(CONFIG_PATH)
    return _registry


def get_scenario_catalog() -> tuple[ScenarioCatalogEntry, ...]:
    """Load public scenario IDs without importing evaluation answers into the API process."""
    global _scenario_catalog
    if _scenario_catalog is not None:
        return _scenario_catalog
    if not SCENARIO_CATALOG_PATH.is_file():
        raise FileNotFoundError(f"Scenario catalog not found at {SCENARIO_CATALOG_PATH}")
    raw = json.loads(SCENARIO_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema") != "metricsleuth.stage1_scenario_catalog.v1":
        raise ValueError("Scenario catalog has an invalid schema.")
    items = raw.get("scenarios")
    if not isinstance(items, list) or not items:
        raise ValueError("Scenario catalog must contain a non-empty scenarios list.")

    catalog: list[ScenarioCatalogEntry] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"scenario_id", "target_metric"}:
            raise ValueError("Each scenario catalog item must contain only scenario_id and target_metric.")
        scenario_id = item.get("scenario_id")
        target_metric = item.get("target_metric")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError("Scenario catalog scenario_id must be a non-empty string.")
        if not isinstance(target_metric, str) or not target_metric.strip():
            raise ValueError("Scenario catalog target_metric must be a non-empty string.")
        if scenario_id in seen_ids:
            raise ValueError(f"Scenario catalog contains duplicate scenario_id: {scenario_id}")
        seen_ids.add(scenario_id)
        catalog.append(ScenarioCatalogEntry(scenario_id=scenario_id, target_metric=target_metric))
    _scenario_catalog = tuple(catalog)
    return _scenario_catalog


def get_metric_graph() -> MetricGraphResponse:
    """Build topological metric dependency graph from registry."""
    registry = get_metric_registry()
    metrics = registry.list_metrics()

    nodes: list[MetricGraphNode] = []
    edges: list[MetricGraphEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for m in metrics:
        nodes.append(
            MetricGraphNode(
                metric_id=m.metric_id,
                display_name=m.display_name,
                description=m.description,
                metric_type=m.metric_type,
                unit=m.unit,
                formula=m.formula,
                dependencies=list(m.dependencies),
                related_metrics=list(m.related_metrics),
            )
        )
        for dep in m.dependencies:
            edge_key = (m.metric_id, dep, "depends_on")
            if edge_key not in seen_edges:
                edges.append(MetricGraphEdge(source=m.metric_id, target=dep, relationship="depends_on"))
                seen_edges.add(edge_key)

    # Add business decomposition edges for Sales
    # Sales = Orders * AOV
    if ("sales", "orders", "decomposes_to") not in seen_edges:
        edges.append(MetricGraphEdge(source="sales", target="orders", relationship="decomposes_to"))
        edges.append(MetricGraphEdge(source="sales", target="aov", relationship="decomposes_to"))
        # Orders = Sessions * CR
        edges.append(MetricGraphEdge(source="orders", target="sessions", relationship="decomposes_to"))
        edges.append(MetricGraphEdge(source="orders", target="conversion_rate", relationship="decomposes_to"))

    return MetricGraphResponse(nodes=nodes, edges=edges)


def get_scenarios() -> ScenarioListResponse:
    """Return selector-safe scenario metadata without benchmark answers."""
    cases = get_scenario_catalog()
    scenarios: list[ScenarioItem] = []

    for index, case in enumerate(cases, start=1):
        case_number = f"{index:02d}"
        scenarios.append(
            ScenarioItem(
                scenario_id=case.scenario_id,
                title=f"Controlled Case {case_number} / 受控基准场景 {case_number}",
                description=(
                    "Controlled benchmark fixture for preview and data injection; "
                    "expected diagnosis is intentionally hidden."
                ),
                target_metric=case.target_metric,
            )
        )

    return ScenarioListResponse(scenarios=scenarios)


def inject_scenario_data(scenario: str) -> tuple[str, str]:
    """Inject scenario data into database, or run dry-run if no database is connected.

    Returns (mode, message).
    """
    global _current_scenario

    valid_cases = {c.scenario_id for c in get_scenario_catalog()}
    if scenario not in valid_cases:
        raise ValueError(
            f"Unknown scenario '{scenario}'. Valid scenarios: {sorted(valid_cases)}"
        )

    db_url = os.environ.get("DATABASE_URL")

    if db_url:
        env = os.environ.copy()
        env["DATABASE_URL"] = db_url
        completed = subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "warehouse" / "anomaly_injector.py"),
                "--scenario",
                scenario,
                "--database-url",
                db_url,
            ],
            cwd=REPOSITORY_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            _current_scenario = scenario
            return "live", f"Scenario '{scenario}' successfully injected into PostgreSQL warehouse."
        raise RuntimeError(
            f"Live scenario injection failed for '{scenario}': {completed.stderr.strip()}"
        )
    else:
        # Run in dry-run mode
        completed = subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "warehouse" / "anomaly_injector.py"),
                "--scenario",
                scenario,
                "--dry-run",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Dry-run injection failed: {completed.stderr.strip()}")
        _current_scenario = scenario
        return "dry_run", f"Dry-run scenario '{scenario}' applied (no live DATABASE_URL configured)."


def resolve_live_model(request_model: Optional[str] = None) -> str:
    """Resolve model for live investigation following priority:
    1. Explicit request model
    2. Environment variable METRICSLEUTH_AGENT_MODEL
    3. Default fallback 'gpt-4o-mini'
    """
    if request_model and request_model.strip():
        return request_model.strip()
    env_model = os.environ.get("METRICSLEUTH_AGENT_MODEL")
    if env_model and env_model.strip():
        return env_model.strip()
    return "gpt-4o-mini"


def execute_investigation(request: InvestigationRequest) -> InvestigationResponse:
    """Execute a live Agent Investigation or fixed Fixture Preview."""
    target_scenario = request.scenario or _current_scenario
    scenarios = get_scenario_catalog()
    matched_scenario = next((item for item in scenarios if item.scenario_id == target_scenario), None)
    if matched_scenario is None:
        raise ValueError(f"Unknown investigation scenario '{target_scenario}'.")

    if request.mock_mode:
        return _run_mock_investigation(request, matched_scenario)

    # Fail-closed guards for live investigation
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        raise ValueError("Missing required OPENAI_API_KEY for live investigation.")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url or not db_url.strip():
        raise ValueError("Missing required DATABASE_URL for live investigation.")

    return _run_live_investigation(request, matched_scenario, db_url)


def _run_mock_investigation(
    request: InvestigationRequest,
    scenario: ScenarioCatalogEntry,
) -> InvestigationResponse:
    """Return a generic UI fixture without accessing evaluation Ground Truth.

    This fixture is intentionally independent of the selected scenario.  It
    demonstrates page layout only; it is not a scripted investigation result.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    request_id = f"fixture-{scenario.scenario_id}-{int(time.time())}"
    ev_target_id = f"evidence:{request_id}_target:supporting"
    ev_driver_id = f"evidence:{request_id}_driver:supporting"
    ev_control_id = f"evidence:{request_id}_control:negative_control"
    trace = [
        TraceStepItem(
            step_number=1, tool_name="query_metric", tool_call_id=f"call_{request_id}_1",
            arguments={"metric": request.target_metric}, observation_id=f"obs_{request_id}_target",
            metric=request.target_metric, current_value=15840.0, baseline_value=18240.0,
            relative_change=-0.1316, summary="Fixture-only overall metric example; not selected scenario output.",
        ),
        TraceStepItem(
            step_number=2, tool_name="query_related_metrics", tool_call_id=f"call_{request_id}_2",
            arguments={"metric": request.target_metric}, observation_id=f"obs_{request_id}_related",
            metric=request.target_metric, summary="Fixture-only related-metrics example; no Agent call was made.",
        ),
        TraceStepItem(
            step_number=3, tool_name="query_metric", tool_call_id=f"call_{request_id}_3",
            arguments={"metric": "conversion_rate", "group_by": ["marketplace"]}, observation_id=f"obs_{request_id}_driver",
            metric="conversion_rate", current_value=0.04, baseline_value=0.08, relative_change=-0.50,
            dimensions={"marketplace": "US"}, summary="Fixture-only segment example; not selected scenario output.",
        ),
    ]
    evidence_list = [
        EvidenceItem(evidence_id=ev_target_id, observation_id=f"obs_{request_id}_target", metric=request.target_metric, role="supporting", observation_status="anomalous", current_value=15840.0, baseline_value=18240.0, relative_change=-0.1316, unit="usd", sample_size=2850.0),
        EvidenceItem(evidence_id=ev_driver_id, observation_id=f"obs_{request_id}_driver", metric="conversion_rate", role="supporting", observation_status="anomalous", current_value=0.04, baseline_value=0.08, relative_change=-0.50, unit="ratio", sample_size=500.0, dimensions={"marketplace": "US"}, filters={"marketplace": "US"}),
        EvidenceItem(evidence_id=ev_control_id, observation_id=f"obs_{request_id}_related", metric="sessions", role="negative_control", observation_status="normal", current_value=100.0, baseline_value=100.0, relative_change=0.0, unit="count", sample_size=500.0, dimensions={"marketplace": "DE"}, filters={"marketplace": "DE"}),
    ]
    change_item = DiagnosisChangeItem(
        current_value=15840.0,
        baseline_value=18240.0,
        relative_change=-0.1316,
        unit="usd",
        evidence_id=ev_target_id,
    )
    diagnosis_item = DiagnosisItem(
        diagnosis_id=f"diag_{request_id}",
        status="diagnosed",
        target_metric=request.target_metric,
        primary_driver="conversion_rate",
        affected_scope={"marketplace": "US"},
        confidence=0.92,
        change=change_item,
        evidence_ids=[ev_target_id, ev_driver_id],
        limitations=["Fixture Preview only: static UI illustration, not a selected-scenario result or Agent conclusion."],
        created_at=now.isoformat(),
    )
    budget_item = BudgetUsage(
        tool_calls_count=len(trace),
        max_tool_calls=8,
        turns_count=len(trace),
        max_turns=10,
    )

    return InvestigationResponse(
        request_id=request_id,
        mode="mock",
        target_metric=request.target_metric,
        target_date=request.target_date,
        scenario=scenario.scenario_id,
        diagnosis=diagnosis_item,
        evidence=evidence_list,
        investigation_trace=trace,
        budget=budget_item,
    )


def _to_api_json(value: object) -> object:
    """Convert the immutable runtime JSON snapshot to response JSON values."""
    if isinstance(value, Mapping):
        converted: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Runtime trace argument mapping keys must be strings.")
            converted[key] = _to_api_json(item)
        return converted
    if isinstance(value, tuple):
        return [_to_api_json(item) for item in value]
    if isinstance(value, list):
        return [_to_api_json(item) for item in value]
    return value


def _build_live_trace_items(summary: object) -> list[TraceStepItem]:
    """Map only the Runtime''s validated SDK trace into API trace items.

    ``InvestigationRunSummary.tool_trace`` is the sole source of call identity,
    ordering, tool names, arguments, and Observation ownership. Composition
    Evidence is used only to display facts for the first Observation represented
    by a step. A call can legitimately have no Observation (for example,
    ``get_metric_definition``), and unpromoted Observations are shown by ID
    without inventing values.
    """
    investigation = getattr(summary, "investigation", None)
    composition = getattr(summary, "composition", None)
    if investigation is None or composition is None:
        raise ValueError("Runtime summary is missing investigation or composition.")

    raw_trace = getattr(investigation, "tool_trace", None)
    try:
        entries = tuple(raw_trace)
    except (TypeError, ValueError) as exc:
        raise ValueError("Runtime summary tool_trace must be a sequence.") from exc

    try:
        expected_call_ids = tuple(investigation.tool_call_ids)
        expected_tool_names = tuple(investigation.tools_used)
        expected_observation_ids = tuple(investigation.observation_ids)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Runtime summary investigation identity fields are invalid.") from exc

    expected_count = getattr(investigation, "tool_calls_count", len(entries))
    if expected_count != len(entries):
        raise ValueError("Runtime summary tool_trace count does not match tool_calls_count.")
    if len(expected_call_ids) != len(entries) or len(expected_tool_names) != len(entries):
        raise ValueError("Runtime summary tool_trace identity arrays are inconsistent.")

    normalized_entries: list[tuple[str, str, dict[str, object], tuple[str, ...]]] = []
    flattened_observation_ids: list[str] = []
    for index, entry in enumerate(entries):
        call_id = getattr(entry, "tool_call_id", None)
        tool_name = getattr(entry, "tool_name", None)
        raw_arguments = getattr(entry, "arguments", None)
        raw_observation_ids = getattr(entry, "observation_ids", None)
        if not isinstance(call_id, str) or not call_id.strip():
            raise ValueError(f"Runtime trace entry {index + 1} has an invalid tool_call_id.")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError(f"Runtime trace entry {index + 1} has an invalid tool_name.")
        if call_id != expected_call_ids[index] or tool_name != expected_tool_names[index]:
            raise ValueError(
                f"Runtime trace entry {index + 1} does not match the summary identity arrays."
            )
        if not isinstance(raw_arguments, Mapping):
            raise ValueError(f"Runtime trace entry {index + 1} has invalid arguments.")
        converted_arguments = _to_api_json(raw_arguments)
        if not isinstance(converted_arguments, dict):
            raise ValueError(f"Runtime trace entry {index + 1} arguments are not a JSON object.")
        try:
            observation_ids = tuple(raw_observation_ids)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Runtime trace entry {index + 1} has invalid observation_ids."
            ) from exc
        if any(not isinstance(observation_id, str) or not observation_id.strip() for observation_id in observation_ids):
            raise ValueError(f"Runtime trace entry {index + 1} has an invalid observation ID.")
        flattened_observation_ids.extend(observation_ids)
        normalized_entries.append(
            (call_id, tool_name, converted_arguments, observation_ids)
        )

    if tuple(flattened_observation_ids) != expected_observation_ids:
        raise ValueError(
            "Runtime trace Observation IDs cannot be reconciled with the investigation summary."
        )

    # Composition Evidence must itself originate from this run. It may cover
    # only selected Observations; unselected trace Observations remain facts-free.
    evidence_by_observation_id: dict[str, object] = {}
    try:
        composition_evidence = tuple(composition.evidence)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Runtime composition Evidence is invalid.") from exc
    expected_observation_id_set = set(expected_observation_ids)
    for evidence in composition_evidence:
        evidence_observation_id = getattr(evidence, "observation_id", None)
        if (
            not isinstance(evidence_observation_id, str)
            or not evidence_observation_id.strip()
        ):
            raise ValueError("Composition Evidence contains an invalid observation ID.")
        if evidence_observation_id not in expected_observation_id_set:
            raise ValueError(
                "Composition Evidence references an Observation outside this runtime trace."
            )
        evidence_by_observation_id.setdefault(evidence_observation_id, evidence)

    trace_items: list[TraceStepItem] = []
    for index, (call_id, tool_name, arguments, observation_ids) in enumerate(normalized_entries):
        first_observation_id = observation_ids[0] if observation_ids else None
        first_evidence = (
            evidence_by_observation_id.get(first_observation_id)
            if first_observation_id is not None
            else None
        )

        metric = arguments.get("metric")
        if not isinstance(metric, str):
            metric = None
        current_value: Optional[float] = None
        baseline_value: Optional[float] = None
        relative_change: Optional[float] = None
        dimensions: dict[str, str] = {}
        if first_evidence is not None:
            evidence_metric = getattr(first_evidence, "metric", None)
            if isinstance(evidence_metric, str) and evidence_metric.strip():
                # For a related-metrics call, ``metric`` remains the requested
                # source metric while these values belong to the first row.
                if tool_name != "query_related_metrics":
                    metric = evidence_metric
            try:
                current_raw = getattr(first_evidence, "current_value", None)
                baseline_raw = getattr(first_evidence, "baseline_value", None)
                relative_raw = getattr(first_evidence, "relative_change", None)
                current_value = float(current_raw) if current_raw is not None else None
                baseline_value = float(baseline_raw) if baseline_raw is not None else None
                relative_change = float(relative_raw) if relative_raw is not None else None
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"Evidence facts for Observation ''{first_observation_id}'' are invalid."
                ) from exc
            raw_dimensions = getattr(first_evidence, "dimensions", {})
            converted_dimensions = _to_api_json(raw_dimensions)
            if not isinstance(converted_dimensions, dict):
                raise ValueError(
                    f"Evidence dimensions for Observation ''{first_observation_id}'' are invalid."
                )
            dimensions = converted_dimensions

        metric_label = metric or "metric"
        if tool_name == "get_metric_definition":
            summary_text = (
                f"Semantic definition lookup for {metric_label}; no Observation produced."
            )
        elif tool_name == "query_related_metrics":
            summary_text = (
                f"Query related metrics for {metric_label} ({len(observation_ids)} observations); "
                "first Observation shown when available."
            )
        elif relative_change is not None:
            summary_text = f"Query {metric_label}: observed {relative_change:+.2%} change"
        else:
            summary_text = f"Query {metric_label}"

        if first_observation_id is not None and first_evidence is None:
            summary_text += (
                f" Observation ''{first_observation_id}'' was not promoted to this diagnosis Evidence portfolio; "
                "facts omitted."
            )

        trace_items.append(
            TraceStepItem(
                step_number=index + 1,
                tool_name=tool_name,
                tool_call_id=call_id,
                arguments=arguments,
                observation_id=first_observation_id,
                status="ok",
                metric=metric,
                current_value=current_value,
                baseline_value=baseline_value,
                relative_change=relative_change,
                dimensions=dimensions,
                summary=summary_text,
            )
        )
    return trace_items


def _run_live_investigation(
    request: InvestigationRequest,
    scenario: ScenarioCatalogEntry,
    database_url: str,
) -> InvestigationResponse:
    """Execute live autonomous investigation using Agents SDK runtime."""
    import psycopg
    from app.agent_runtime.diagnosis_runtime import (
        DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
        DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
        run_evidence_driven_diagnosis,
    )

    registry = get_metric_registry()
    request_id = f"live-{scenario.scenario_id}-{int(time.time())}"
    resolved_model = resolve_live_model(request.model)

    # Inject target scenario
    inject_scenario_data(scenario.scenario_id)

    with psycopg.connect(database_url) as conn:
        tools = AnalyticsTools(registry=registry, connection=conn)
        prompt = (
            request.prompt
            or f"Please investigate the {request.target_metric} anomaly for {request.target_date} "
            f"compared to the previous_7_days baseline. Identify primary driver and segment if any."
        )
        summary = run_evidence_driven_diagnosis(
            prompt=prompt,
            diagnosis_id=f"diag_{request_id}",
            analytics_tools=tools,
            model=resolved_model,
            max_tool_calls=DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
            max_turns=DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
        )

    diag = summary.composition.diagnosis
    change_item = (
        DiagnosisChangeItem(
            current_value=float(diag.change.current_value) if diag.change and diag.change.current_value is not None else None,
            baseline_value=float(diag.change.baseline_value) if diag.change and diag.change.baseline_value is not None else None,
            relative_change=float(diag.change.relative_change) if diag.change and diag.change.relative_change is not None else None,
            unit=diag.change.unit if diag.change else None,
            evidence_id=diag.change.evidence_id if diag.change else None,
        )
        if diag.change
        else None
    )

    diagnosis_item = DiagnosisItem(
        diagnosis_id=diag.diagnosis_id,
        status=diag.status.value,
        target_metric=diag.target_metric,
        primary_driver=diag.primary_driver,
        affected_scope=dict(diag.affected_scope),
        confidence=float(diag.confidence) if diag.confidence is not None else None,
        change=change_item,
        evidence_ids=list(diag.evidence_ids),
        limitations=list(diag.limitations),
        created_at=diag.created_at.isoformat() if diag.created_at else None,
    )

    evidence_list = [
        EvidenceItem(
            evidence_id=ev.evidence_id,
            observation_id=ev.observation_id,
            metric=ev.metric,
            role=ev.role.value,
            observation_status=ev.observation_status.value,
            current_value=float(ev.current_value) if ev.current_value is not None else None,
            baseline_value=float(ev.baseline_value) if ev.baseline_value is not None else None,
            relative_change=float(ev.relative_change) if ev.relative_change is not None else None,
            unit=ev.unit,
            sample_size=float(ev.sample_size) if ev.sample_size is not None else None,
            dimensions=dict(ev.dimensions),
            filters=dict(ev.filters),
        )
        for ev in summary.composition.evidence
    ]

    trace_items = _build_live_trace_items(summary)

    budget_item = BudgetUsage(
        tool_calls_count=summary.investigation.tool_calls_count,
        max_tool_calls=summary.investigation.max_tool_calls,
        turns_count=summary.investigation.turns_count,
        max_turns=summary.investigation.max_turns,
    )

    return InvestigationResponse(
        request_id=request_id,
        mode="live",
        target_metric=request.target_metric,
        target_date=request.target_date,
        scenario=scenario.scenario_id,
        diagnosis=diagnosis_item,
        evidence=evidence_list,
        investigation_trace=trace_items,
        budget=budget_item,
    )
