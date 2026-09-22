"""Pydantic data models and schemas for the MetricSleuth API."""

from __future__ import annotations

import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Metric Graph Models
# ---------------------------------------------------------------------------

class MetricGraphNode(BaseModel):
    """Metadata node in the metric dependency graph."""

    metric_id: str
    display_name: str
    description: str
    metric_type: str
    unit: str
    formula: str
    dependencies: list[str] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)


class MetricGraphEdge(BaseModel):
    """Directed dependency or decomposition edge between metrics."""

    source: str
    target: str
    relationship: str = "depends_on"


class MetricGraphResponse(BaseModel):
    """Complete topological metric dependency graph."""

    nodes: list[MetricGraphNode]
    edges: list[MetricGraphEdge]


# ---------------------------------------------------------------------------
# Scenario Models
# ---------------------------------------------------------------------------

class ScenarioItem(BaseModel):
    """Public scenario-selector metadata with benchmark answers intentionally excluded."""

    scenario_id: str
    title: str
    description: str
    target_metric: str


class ScenarioListResponse(BaseModel):
    """List of available benchmark demonstration scenarios."""

    scenarios: list[ScenarioItem]


class InjectScenarioRequest(BaseModel):
    """Request to inject a specific anomaly scenario into the warehouse."""

    scenario: str


class InjectScenarioResponse(BaseModel):
    """Result of an anomaly scenario injection."""

    status: str
    scenario: str
    message: str
    mode: str = "live"


# ---------------------------------------------------------------------------
# Investigation Models
# ---------------------------------------------------------------------------

class InvestigationRequest(BaseModel):
    """Request for a live Agent Investigation or deterministic Fixture Preview."""

    target_metric: str = "sales"
    target_date: str = "2026-01-31"
    baseline_strategy: str = "previous_7_days"
    prompt: Optional[str] = None
    scenario: Optional[str] = None
    mock_mode: bool = Field(
        default=False,
        description="Run a fixed Fixture Preview without calling a model.",
    )
    model: Optional[str] = None


class DiagnosisChangeItem(BaseModel):
    """Observed value change for the investigated target metric."""

    current_value: Optional[float] = None
    baseline_value: Optional[float] = None
    relative_change: Optional[float] = None
    unit: Optional[str] = None
    evidence_id: Optional[str] = None


class DiagnosisItem(BaseModel):
    """Structured diagnostic conclusion derived from cited evidence."""

    diagnosis_id: str
    status: str
    target_metric: str
    primary_driver: Optional[str] = None
    affected_scope: dict[str, str] = Field(default_factory=dict)
    confidence: Optional[float] = None
    change: Optional[DiagnosisChangeItem] = None
    evidence_ids: list[str]
    limitations: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None


class EvidenceItem(BaseModel):
    """Promoted and cited Evidence item supporting or bounding the diagnosis."""

    evidence_id: str
    observation_id: str
    metric: str
    role: str
    observation_status: str
    current_value: Optional[float] = None
    baseline_value: Optional[float] = None
    relative_change: Optional[float] = None
    unit: str
    sample_size: Optional[float] = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    filters: dict[str, str] = Field(default_factory=dict)


class TraceStepItem(BaseModel):
    """One step in a live investigation or fixed fixture-preview trajectory."""

    step_number: int
    tool_name: str
    tool_call_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    observation_id: Optional[str] = None
    status: str = "ok"
    metric: Optional[str] = None
    current_value: Optional[float] = None
    baseline_value: Optional[float] = None
    relative_change: Optional[float] = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    summary: Optional[str] = None


class BudgetUsage(BaseModel):
    """Resource budget utilization for the investigation session."""

    tool_calls_count: int
    max_tool_calls: int
    turns_count: int
    max_turns: int


class InvestigationResponse(BaseModel):
    """Live Agent Investigation or Fixture Preview result with evidence and trace."""

    request_id: str
    mode: str
    target_metric: str
    target_date: str
    scenario: Optional[str] = None
    diagnosis: DiagnosisItem
    evidence: list[EvidenceItem]
    investigation_trace: list[TraceStepItem]
    budget: BudgetUsage


# ---------------------------------------------------------------------------
# Manual Trigger Discovery Models
# ---------------------------------------------------------------------------

class DailyScanRequest(BaseModel):
    """Request a global semantic-metric scan; this does not start an Agent run."""

    target_date: datetime.date = datetime.date(2026, 1, 31)


class DailyScanObservationItem(BaseModel):
    """One global Observation produced by a manual trigger scan."""

    metric: str
    status: str
    current_value: Optional[float] = None
    baseline_value: Optional[float] = None
    relative_change: Optional[float] = None
    unit: str
    sample_size: Optional[float] = None
    observation_id: str


class DailyScanResponse(BaseModel):
    """Candidate metrics only; driver, scope, and next action remain undecided."""

    target_date: str
    comparison: str
    mode: str
    observations: list[DailyScanObservationItem]
    anomaly_candidate_metrics: list[str]
    next_step: str


# ---------------------------------------------------------------------------
# Health Model
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Service health check response."""

    status: str
    service: str
    version: str
    timestamp: str
