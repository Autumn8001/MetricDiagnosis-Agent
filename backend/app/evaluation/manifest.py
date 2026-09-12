"""Immutable metadata contract for reproducible evaluation runs."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .models import EvaluationValidationError


def _normalize_identifier(value: object, field_name: str) -> str:
    """Validate and trim a manifest identifier or version string."""
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def _validate_prompt(value: object) -> str:
    """Validate a complete prompt without changing its original contents."""
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            "Field 'prompt' must be a non-whitespace string."
        )
    return value


def _snapshot_run_counts(value: object) -> Mapping[str, int]:
    """Validate and defensively snapshot per-case positive run counts."""
    if not isinstance(value, Mapping):
        raise EvaluationValidationError(
            "Field 'run_counts_by_case' must be a non-empty mapping."
        )

    snapshot: dict[str, int] = {}
    for raw_case_id, raw_count in value.items():
        case_id = _normalize_identifier(raw_case_id, "run_counts_by_case case_id")
        if case_id in snapshot:
            raise EvaluationValidationError(
                "Field 'run_counts_by_case' must not contain duplicate normalized case_ids."
            )
        if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count <= 0:
            raise EvaluationValidationError(
                "Each run_counts_by_case value must be a positive integer, not bool."
            )
        snapshot[case_id] = raw_count

    if not snapshot:
        raise EvaluationValidationError(
            "Field 'run_counts_by_case' must be a non-empty mapping."
        )
    return MappingProxyType(snapshot)


def _normalize_created_at(value: object) -> datetime.datetime:
    """Require an aware timestamp and represent it in UTC."""
    if not isinstance(value, datetime.datetime):
        raise EvaluationValidationError(
            "Field 'created_at' must be a timezone-aware datetime."
        )
    try:
        is_aware = value.tzinfo is not None and value.utcoffset() is not None
    except Exception as exc:
        raise EvaluationValidationError(
            "Field 'created_at' must be a timezone-aware datetime."
        ) from exc
    if not is_aware:
        raise EvaluationValidationError(
            "Field 'created_at' must be a timezone-aware datetime."
        )
    try:
        return value.astimezone(datetime.timezone.utc)
    except Exception as exc:
        raise EvaluationValidationError(
            "Field 'created_at' could not be normalized to UTC."
        ) from exc


@dataclass(frozen=True)
class EvaluationManifest:
    """Immutable inputs and run counts needed to reproduce an evaluation."""

    manifest_id: str
    model_id: str
    prompt: str
    metric_config_version: str
    dataset_version: str
    run_counts_by_case: Mapping[str, int]
    created_at: datetime.datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "manifest_id",
            _normalize_identifier(self.manifest_id, "manifest_id"),
        )
        object.__setattr__(
            self,
            "model_id",
            _normalize_identifier(self.model_id, "model_id"),
        )
        object.__setattr__(self, "prompt", _validate_prompt(self.prompt))
        object.__setattr__(
            self,
            "metric_config_version",
            _normalize_identifier(self.metric_config_version, "metric_config_version"),
        )
        object.__setattr__(
            self,
            "dataset_version",
            _normalize_identifier(self.dataset_version, "dataset_version"),
        )
        object.__setattr__(
            self,
            "run_counts_by_case",
            _snapshot_run_counts(self.run_counts_by_case),
        )
        object.__setattr__(
            self,
            "created_at",
            _normalize_created_at(self.created_at),
        )

    @property
    def total_run_count(self) -> int:
        """Return the total number of runs represented by this manifest."""
        return sum(self.run_counts_by_case.values())


__all__ = ["EvaluationManifest"]
