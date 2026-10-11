"""Strict response schemas for the source-bound metric observation endpoint."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict


class MetricObservationView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    metric: str
    status: Literal[
        "normal",
        "anomalous",
        "inconclusive",
        "insufficient_evidence",
        "failed",
    ]
    source_status: str
    current_period_start: date
    current_period_end: date
    baseline_period_start: date
    baseline_period_end: date
    current_value: Decimal | None
    baseline_value: Decimal | None
    relative_change: Decimal | None
    unit: str
    sample_size: Decimal | None


class MetricReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_id: str
    provider: Literal["postgresql", "shopify", "olist", "synthetic"]
    environment: Literal["live", "sandbox", "benchmark", "validation"]
    data_version: str
    data_version_kind: Literal["label"]
    persisted: Literal[False]
    scope: Literal["source_global"]
    target_metric: str
    target_date: date
    comparison: Literal["previous_7_days"]
    queried_at: AwareDatetime
    query_reference: str
    observation: MetricObservationView | None
    anomaly_candidate: bool | None
