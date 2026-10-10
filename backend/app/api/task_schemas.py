"""Request and response models for persisted worker investigations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvestigationTaskCreate(BaseModel):
    """Client-controlled, bounded query intent for an allow-listed source."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1, max_length=128)
    target_metric: str = Field(min_length=1, max_length=128)
    target_date: date
    filters: dict[str, str] = Field(default_factory=dict, max_length=32)
    group_by: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("target_date", mode="before")
    @classmethod
    def validate_canonical_date(cls, value: object) -> date:
        if not isinstance(value, str):
            raise ValueError("target_date must be an ISO calendar date")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("target_date must be an ISO calendar date") from exc
        if parsed.isoformat() != value:
            raise ValueError("target_date must use canonical YYYY-MM-DD format")
        return parsed

    @field_validator("source_id", "target_metric")
    @classmethod
    def reject_blank_identifiers(cls, value: str) -> str:
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not key or len(key) > 64:
                raise ValueError("filter names must contain 1 to 64 characters")
            if len(item) > 256 or any(unicodedata.category(character) == "Cc" for character in item):
                raise ValueError("filter values must contain at most 256 characters")
        return value

    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 64 for item in value):
            raise ValueError("dimensions must contain 1 to 64 characters")
        if len(set(value)) != len(value):
            raise ValueError("group_by dimensions must be unique")
        return value


class TaskRunView(BaseModel):
    """Explicit public projection of a persisted worker run."""

    model_config = ConfigDict(extra="forbid")

    investigation_run_id: str
    source_id: str
    environment: str
    provider: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    requested_metric: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    data_version: str | None
    query_reference: str | None
    failure_code: str | None
    tool_call_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    diagnosis_count: int = Field(ge=0)


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskRunView]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ToolCallView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    tool_name: str
    status: str
    arguments: dict[str, Any]
    data_version: str | None
    query_reference: str | None
    result_reference: str | None
    requested_at: datetime


class ObservationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    tool_call_id: str | None
    metric: str
    status: str
    source_status: str | None
    current_period_start: date | None
    current_period_end: date | None
    baseline_period_start: date | None
    baseline_period_end: date | None
    filters: dict[str, Any]
    group_by: list[str]
    dimensions: dict[str, Any]
    current_value: Decimal | None
    baseline_value: Decimal | None
    relative_change: Decimal | None
    unit: str | None
    sample_size: Decimal | None
    query_reference: str | None
    data_version: str | None
    error_code: str | None
    created_at: datetime


class EvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    observation_id: str
    tool_call_id: str | None
    role: str
    data_version: str | None
    query_reference: str | None
    created_at: datetime


class DiagnosisChangeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_value: Decimal | None
    baseline_value: Decimal | None
    relative_change: Decimal | None
    unit: str
    evidence_id: str


class DiagnosisView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis_id: str
    status: str
    target_metric: str
    primary_driver: str | None
    affected_scope: dict[str, str]
    change: DiagnosisChangeView | None
    evidence_ids: list[str]
    confidence: Decimal | None
    limitations: list[str]
    data_version: str | None
    query_reference: str | None
    created_at: datetime

    @field_validator("change", mode="before")
    @classmethod
    def empty_change_is_absent(cls, value: object) -> object:
        # Persistence stores an absent DiagnosisChange as an empty JSON object.
        return None if value == {} else value


class TaskDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: TaskRunView
    tool_calls: list[ToolCallView]
    observations: list[ObservationView]
    evidence: list[EvidenceView]
    diagnoses: list[DiagnosisView]


__all__ = [
    "DiagnosisView",
    "DiagnosisChangeView",
    "EvidenceView",
    "InvestigationTaskCreate",
    "ObservationView",
    "TaskDetailResponse",
    "TaskListResponse",
    "TaskRunView",
    "ToolCallView",
]
