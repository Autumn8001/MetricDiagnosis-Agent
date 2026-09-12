"""Deterministic aggregation of per-run operational tool scores."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .models import EvaluationValidationError
from .operational import ToolOperationalScore


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(f"Field '{field}' must be a non-empty string.")
    return value.strip()


def _rate(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or not Decimal("0") <= value <= Decimal("1"):
        raise EvaluationValidationError(f"Field '{field}' must be a finite Decimal in [0, 1].")
    return value


def _average(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < Decimal("0"):
        raise EvaluationValidationError(f"Field '{field}' must be a finite non-negative Decimal.")
    return value


def _ids(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (tuple, list)):
        raise EvaluationValidationError("Field 'run_ids' must be a list or tuple of strings.")
    result = tuple(_string(item, "run_ids item") for item in value)
    if len(result) != len(set(result)):
        raise EvaluationValidationError("Field 'run_ids' must not contain duplicates.")
    return result


@dataclass(frozen=True)
class ToolOperationalAggregateReport:
    """Aggregate operational metrics with explicit micro/run denominators.

    Tool success is call-level micro: total succeeded calls / total attempted
    calls. Average calls uses run_count as denominator. Budget exhaustion uses
    budget-exhausted runs / run_count. Empty input is represented by zero counts
    and ``None`` rates/average rather than fabricated zero percentages.
    """

    run_count: int
    run_ids: tuple[str, ...]
    tool_calls_attempted: int
    tool_calls_succeeded: int
    tool_success_rate: Decimal | None
    average_tool_call_count: Decimal | None
    budget_exhausted_run_count: int
    budget_exhaustion_rate: Decimal | None

    def __post_init__(self) -> None:
        if isinstance(self.run_count, bool) or not isinstance(self.run_count, int) or self.run_count < 0:
            raise EvaluationValidationError("run_count must be a non-negative int.")
        ids = _ids(self.run_ids)
        if self.run_count != len(ids):
            raise EvaluationValidationError("run_count must equal len(run_ids).")
        counts = (self.tool_calls_attempted, self.tool_calls_succeeded, self.budget_exhausted_run_count)
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts):
            raise EvaluationValidationError("Operational counts must be non-negative integers.")
        if self.tool_calls_succeeded > self.tool_calls_attempted:
            raise EvaluationValidationError("Succeeded calls must not exceed attempted calls.")
        if self.budget_exhausted_run_count > self.run_count:
            raise EvaluationValidationError("Budget-exhausted runs must not exceed run_count.")
        success = self.tool_success_rate
        average = self.average_tool_call_count
        budget = self.budget_exhaustion_rate
        if self.tool_calls_attempted == 0:
            if success is not None:
                raise EvaluationValidationError("tool_success_rate must be None with zero attempts.")
        elif success != Decimal(self.tool_calls_succeeded) / Decimal(self.tool_calls_attempted):
            raise EvaluationValidationError("tool_success_rate formula is inconsistent.")
        if self.run_count == 0:
            if average is not None or budget is not None:
                raise EvaluationValidationError("Empty reports require None average and budget rate.")
        else:
            if average != Decimal(self.tool_calls_attempted) / Decimal(self.run_count):
                raise EvaluationValidationError("average_tool_call_count formula is inconsistent.")
            if budget != Decimal(self.budget_exhausted_run_count) / Decimal(self.run_count):
                raise EvaluationValidationError("budget_exhaustion_rate formula is inconsistent.")
        if success is not None:
            _rate(success, "tool_success_rate")
        if average is not None:
            _average(average, "average_tool_call_count")
        if budget is not None:
            _rate(budget, "budget_exhaustion_rate")
        object.__setattr__(self, "run_ids", ids)


def aggregate_tool_operations(
    scores: Sequence[ToolOperationalScore],
) -> ToolOperationalAggregateReport:
    """Aggregate scores using call-level micro and run-level denominators."""
    if isinstance(scores, (str, bytes, bytearray)) or not isinstance(scores, Sequence):
        raise EvaluationValidationError("scores must be a sequence of ToolOperationalScore.")
    items = tuple(scores)
    if any(not isinstance(item, ToolOperationalScore) for item in items):
        raise EvaluationValidationError("scores must contain only ToolOperationalScore instances.")
    ids = tuple(item.case_id for item in items)
    if len(ids) != len(set(ids)):
        raise EvaluationValidationError("scores must not contain duplicate case_id values.")
    attempted = sum(item.tool_calls_attempted for item in items)
    succeeded = sum(item.tool_calls_succeeded for item in items)
    budget_count = sum(item.budget_exhausted for item in items)
    run_count = len(items)
    return ToolOperationalAggregateReport(
        run_count=run_count,
        run_ids=ids,
        tool_calls_attempted=attempted,
        tool_calls_succeeded=succeeded,
        tool_success_rate=None if attempted == 0 else Decimal(succeeded) / Decimal(attempted),
        average_tool_call_count=None if run_count == 0 else Decimal(attempted) / Decimal(run_count),
        budget_exhausted_run_count=budget_count,
        budget_exhaustion_rate=None if run_count == 0 else Decimal(budget_count) / Decimal(run_count),
    )


__all__ = ["ToolOperationalAggregateReport", "aggregate_tool_operations"]
