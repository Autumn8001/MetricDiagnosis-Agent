"""FastAPI route definitions for MetricSleuth API endpoints."""

from __future__ import annotations

import datetime
from fastapi import APIRouter, HTTPException, status

from .schemas import (
    HealthResponse,
    InjectScenarioRequest,
    InjectScenarioResponse,
    InvestigationRequest,
    InvestigationResponse,
    MetricGraphResponse,
    ScenarioListResponse,
)
from .service import (
    execute_investigation,
    get_metric_graph,
    get_scenarios,
    inject_scenario_data,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["System"])
def health_check() -> HealthResponse:
    """Service liveness and health check endpoint."""
    return HealthResponse(
        status="ok",
        service="MetricSleuth API",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


@router.get("/api/metrics/graph", response_model=MetricGraphResponse, tags=["Metrics"])
def get_metrics_dependency_graph() -> MetricGraphResponse:
    """Retrieve topological metric dependency graph for visualization."""
    try:
        return get_metric_graph()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load metric dependency graph: {exc}",
        ) from exc


@router.get("/api/scenarios", response_model=ScenarioListResponse, tags=["Scenarios"])
def list_scenarios() -> ScenarioListResponse:
    """List selector-safe controlled scenarios without benchmark answers."""
    try:
        return get_scenarios()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load benchmark scenarios: {exc}",
        ) from exc


@router.post("/api/scenarios/inject", response_model=InjectScenarioResponse, tags=["Scenarios"])
def inject_scenario(payload: InjectScenarioRequest) -> InjectScenarioResponse:
    """Trigger synthetic anomaly injection for the selected scenario."""
    try:
        mode, message = inject_scenario_data(payload.scenario)
        return InjectScenarioResponse(
            status="ok",
            scenario=payload.scenario,
            message=message,
            mode=mode,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scenario injection failed: {exc}",
        ) from exc


@router.post("/api/investigate", response_model=InvestigationResponse, tags=["Investigation"])
def run_investigation(request: InvestigationRequest) -> InvestigationResponse:
    """Run a live Agent Investigation or fixed Fixture Preview without a model call."""
    try:
        return execute_investigation(request)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Investigation execution failed: {exc}",
        ) from exc
