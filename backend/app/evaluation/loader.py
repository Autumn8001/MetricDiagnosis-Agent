"""Explicit-path Ground Truth loader for the Evaluation boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.diagnosis.models import DiagnosisStatus

from .models import EvaluationConfigError, EvaluationError, GroundTruthCase


_CASE_KEYS = frozenset(
    {
        "case_id",
        "scenario",
        "target_metric",
        "status",
        "primary_driver",
        "affected_scope",
        "expected_stable_metrics",
        "negative_controls",
        "causal_boundary",
    }
)


class _DuplicateJSONKey(ValueError):
    pass


class _InvalidJSONConstant(ValueError):
    pass


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(f"Duplicate JSON object key: {key!r}.")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise _InvalidJSONConstant(f"Non-standard JSON constant is not allowed: {value}.")


def _parse_status(value: object, index: int) -> DiagnosisStatus:
    if not isinstance(value, str):
        raise EvaluationConfigError(f"Case at index {index} field 'status' must be a string.")
    try:
        return DiagnosisStatus(value)
    except ValueError as exc:
        raise EvaluationConfigError(
            f"Case at index {index} has unknown status {value!r}."
        ) from exc


def load_ground_truth_cases(path: str | Path) -> tuple[GroundTruthCase, ...]:
    """Load and validate Ground Truth from a caller-supplied path.

    There is intentionally no default path.  Keeping path ownership at the
    evaluation boundary prevents the runtime from discovering or reading
    benchmark truth implicitly.
    """
    if not isinstance(path, (str, Path)):
        raise EvaluationConfigError("Ground Truth path must be an explicit str or Path.")
    if isinstance(path, str) and not path.strip():
        raise EvaluationConfigError("Ground Truth path must be a non-empty string.")

    try:
        source = Path(path)
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(
                handle,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_non_json_constant,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJSONKey, _InvalidJSONConstant) as exc:
        raise EvaluationConfigError(f"Unable to load valid Ground Truth JSON from {path!s}.") from exc
    except (TypeError, ValueError) as exc:
        raise EvaluationConfigError(f"Invalid Ground Truth path or JSON input: {path!s}.") from exc

    if not isinstance(payload, list):
        raise EvaluationConfigError("Ground Truth JSON top-level value must be a list.")

    cases: list[GroundTruthCase] = []
    seen_case_ids: set[str] = set()
    seen_scenarios: set[str] = set()
    for index, raw_case in enumerate(payload):
        if not isinstance(raw_case, dict):
            raise EvaluationConfigError(f"Ground Truth case at index {index} must be an object.")
        if set(raw_case) != _CASE_KEYS:
            missing = sorted(_CASE_KEYS - set(raw_case))
            extra = sorted(set(raw_case) - _CASE_KEYS)
            raise EvaluationConfigError(
                f"Ground Truth case at index {index} has invalid keys; missing={missing}, extra={extra}."
            )

        try:
            case = GroundTruthCase(
                case_id=raw_case["case_id"],
                scenario=raw_case["scenario"],
                target_metric=raw_case["target_metric"],
                status=_parse_status(raw_case["status"], index),
                primary_driver=raw_case["primary_driver"],
                affected_scope=raw_case["affected_scope"],
                expected_stable_metrics=raw_case["expected_stable_metrics"],
                negative_controls=raw_case["negative_controls"],
                causal_boundary=raw_case["causal_boundary"],
            )
        except EvaluationError as exc:
            raise EvaluationConfigError(f"Invalid Ground Truth case at index {index}: {exc}") from exc
        except (TypeError, ValueError, KeyError) as exc:
            raise EvaluationConfigError(f"Invalid Ground Truth case at index {index}.") from exc

        if case.case_id in seen_case_ids:
            raise EvaluationConfigError(f"Duplicate Ground Truth case_id: {case.case_id!r}.")
        if case.scenario in seen_scenarios:
            raise EvaluationConfigError(f"Duplicate Ground Truth scenario: {case.scenario!r}.")
        seen_case_ids.add(case.case_id)
        seen_scenarios.add(case.scenario)
        cases.append(case)

    return tuple(cases)
