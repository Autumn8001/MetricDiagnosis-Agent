"""Semantic-layer daily scan that deliberately does not choose investigation actions."""

from __future__ import annotations

import datetime
from typing import Any

from app.analytics.tools import AnalyticsTools
from app.metrics.registry import MetricRegistry
from app.observations.mapper import observations_from_metric_query


class DailyScanError(ValueError):
    """Raised when a controlled manual scan cannot establish a complete snapshot."""


def _observation_payload(observation: object) -> dict[str, Any]:
    return {
        "metric": getattr(observation, "metric"),
        "status": str(getattr(observation, "status")),
        "current_value": float(getattr(observation, "current_value")) if getattr(observation, "current_value") is not None else None,
        "baseline_value": float(getattr(observation, "baseline_value")) if getattr(observation, "baseline_value") is not None else None,
        "relative_change": float(getattr(observation, "relative_change")) if getattr(observation, "relative_change") is not None else None,
        "unit": getattr(observation, "unit"),
        "sample_size": float(getattr(observation, "sample_size")) if getattr(observation, "sample_size") is not None else None,
        "observation_id": getattr(observation, "observation_id"),
    }


def run_manual_daily_scan(
    tools: AnalyticsTools,
    registry: MetricRegistry,
    target_date: datetime.date,
) -> dict[str, Any]:
    """Query every declared metric once at global scope without driving an investigation."""
    created_at = datetime.datetime.now(datetime.timezone.utc)
    observations: list[dict[str, Any]] = []
    for metric_definition in registry.list_metrics():
        metric_id = metric_definition.metric_id
        tool_call_id = f"daily_scan_{target_date.isoformat()}_{metric_id}"
        result = tools.query_metric(metric_id, target_date, target_date, "previous_7_days")
        converted = observations_from_metric_query(
            result,
            tool_name="query_metric",
            tool_call_id=tool_call_id,
            query_or_result_reference=f"daily-scan:{target_date.isoformat()}:{metric_id}",
            created_at=created_at,
        )
        if len(converted) != 1:
            raise DailyScanError(
                f"Global daily scan expected exactly one Observation for {metric_id}, got {len(converted)}."
            )
        observations.append(_observation_payload(converted[0]))
    candidates = [item["metric"] for item in observations if item["status"] == "anomalous"]
    return {
        "schema": "metricsleuth.manual_daily_scan.v1",
        "target_date": target_date.isoformat(),
        "comparison": "previous_7_days",
        "mode": "manual_trigger_discovery",
        "observations": observations,
        "anomaly_candidate_metrics": candidates,
        "next_step": (
            "Human or caller may start the existing Agent investigation for a selected candidate; "
            "this scan does not select a driver, scope, or next query."
        ),
    }
