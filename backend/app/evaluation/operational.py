"""Per-run operational outcomes and protocol-level tool scoring.

The evaluation boundary needs an explicit outcome for every attempted run.
Runtime/trace failures do not produce an ``EvidenceDrivenRunSummary`` because
that summary is deliberately created only after a successful audit and
composition step.  ``EvaluationRunOutcome`` is therefore a small, immutable
envelope that callers construct from observed facts, including partial facts
from a failed run.

Tool success here is intentionally a protocol-level measure: a tool call is
successful when it has a valid paired output in an audited run.  It is not
Diagnosis accuracy and it is not a measure of whether the business query
returned the right answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from app.diagnosis.models import DiagnosisStatus

from .models import EvaluationValidationError

if TYPE_CHECKING:
    from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary


class EvaluationRunStatus(StrEnum):
    """Terminal operational status observed for one evaluation run."""

    COMPLETED = "completed"
    TOOL_FAILURE = "tool_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RUNTIME_FAILURE = "runtime_failure"


_FAILED_RUN_STATUSES = frozenset(
    {
        EvaluationRunStatus.TOOL_FAILURE,
        EvaluationRunStatus.BUDGET_EXHAUSTED,
        EvaluationRunStatus.RUNTIME_FAILURE,
    }
)


def _clean_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def _clean_optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _clean_string(value, field_name)


def _validate_int(value: object, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationValidationError(
            f"Field '{field_name}' must be an integer, not bool or {type(value).__name__}."
        )
    if value < minimum:
        raise EvaluationValidationError(
            f"Field '{field_name}' must be >= {minimum}."
        )
    return value


def _validate_optional_turns(value: object, max_turns: int) -> int | None:
    if value is None:
        return None
    turns = _validate_int(value, "turns_count", minimum=1)
    if turns > max_turns:
        raise EvaluationValidationError(
            "Field 'turns_count' must not exceed 'max_turns'."
        )
    return turns


def _validate_rate(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise EvaluationValidationError(f"Field '{field_name}' must be a Decimal.")
    try:
        valid = value.is_finite() and Decimal("0") <= value <= Decimal("1")
    except (ArithmeticError, ValueError):
        valid = False
    if not valid:
        raise EvaluationValidationError(
            f"Field '{field_name}' must be a finite Decimal in [0, 1]."
        )
    return value


@dataclass(frozen=True)
class EvaluationRunOutcome:
    """Immutable, observed outcome envelope for one evaluation run.

    ``tool_calls_attempted`` and ``tool_calls_succeeded`` are supplied by the
    caller for failed runs.  This model never infers a count from an exception
    or from a missing summary.
    """

    case_id: str
    status: EvaluationRunStatus
    tool_calls_attempted: int
    tool_calls_succeeded: int
    max_tool_calls: int
    turns_count: int | None
    max_turns: int
    failure_code: str | None

    def __post_init__(self) -> None:
        case_id = _clean_string(self.case_id, "case_id")
        if not isinstance(self.status, EvaluationRunStatus):
            raise EvaluationValidationError(
                "Field 'status' must be an EvaluationRunStatus."
            )

        attempted = _validate_int(
            self.tool_calls_attempted,
            "tool_calls_attempted",
            minimum=0,
        )
        succeeded = _validate_int(
            self.tool_calls_succeeded,
            "tool_calls_succeeded",
            minimum=0,
        )
        max_tool_calls = _validate_int(
            self.max_tool_calls,
            "max_tool_calls",
            minimum=1,
        )
        if succeeded > attempted:
            raise EvaluationValidationError(
                "tool_calls_succeeded must not exceed tool_calls_attempted."
            )
        if attempted > max_tool_calls:
            raise EvaluationValidationError(
                "tool_calls_attempted must not exceed max_tool_calls."
            )

        max_turns = _validate_int(self.max_turns, "max_turns", minimum=1)
        turns_count = _validate_optional_turns(self.turns_count, max_turns)
        failure_code = _clean_optional_string(self.failure_code, "failure_code")

        if self.status == EvaluationRunStatus.COMPLETED:
            if failure_code is not None:
                raise EvaluationValidationError(
                    "Completed runs must not have a failure_code."
                )
        elif self.status in _FAILED_RUN_STATUSES:
            if failure_code is None:
                raise EvaluationValidationError(
                    "Failed runs must have a non-empty failure_code."
                )
        else:
            # The enum check above is intentionally followed by an explicit
            # branch so a future enum member cannot silently bypass the
            # completed/failed failure-code contract.
            raise EvaluationValidationError(
                f"Unsupported EvaluationRunStatus: {self.status!r}."
            )

        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "tool_calls_attempted", attempted)
        object.__setattr__(self, "tool_calls_succeeded", succeeded)
        object.__setattr__(self, "max_tool_calls", max_tool_calls)
        object.__setattr__(self, "turns_count", turns_count)
        object.__setattr__(self, "max_turns", max_turns)
        object.__setattr__(self, "failure_code", failure_code)


def completed_run_outcome(
    case_id: str,
    summary: EvidenceDrivenRunSummary,
) -> EvaluationRunOutcome:
    """Create an outcome from an already audited evidence-driven run.

    ``verify_investigation_trace`` has established a paired, valid output for
    every call in this summary, so protocol-level succeeded calls equal the
    observed attempted calls.  Diagnosis status is only used to classify the
    terminal status; Ground Truth is deliberately not read here.
    """
    # Keep the SDK-backed Runtime dependency out of Evaluation's import path;
    # this concrete type is needed only when adapting an actual run summary.
    from app.agent_runtime.diagnosis_runtime import EvidenceDrivenRunSummary

    if not isinstance(summary, EvidenceDrivenRunSummary):
        raise EvaluationValidationError(
            "Expected EvidenceDrivenRunSummary instance, "
            f"got {type(summary).__name__}."
        )

    investigation = summary.investigation
    diagnosis_status = summary.composition.diagnosis.status
    if diagnosis_status == DiagnosisStatus.BUDGET_EXHAUSTED:
        status = EvaluationRunStatus.BUDGET_EXHAUSTED
        failure_code = "budget_exhausted"
    elif diagnosis_status == DiagnosisStatus.TOOL_FAILURE:
        status = EvaluationRunStatus.TOOL_FAILURE
        failure_code = "tool_failure"
    else:
        status = EvaluationRunStatus.COMPLETED
        failure_code = None

    attempted = investigation.tool_calls_count
    return EvaluationRunOutcome(
        case_id=case_id,
        status=status,
        tool_calls_attempted=attempted,
        tool_calls_succeeded=attempted,
        max_tool_calls=investigation.max_tool_calls,
        turns_count=investigation.turns_count,
        max_turns=investigation.max_turns,
        failure_code=failure_code,
    )


def failed_run_outcome(
    case_id: str,
    status: EvaluationRunStatus,
    tool_calls_attempted: int,
    tool_calls_succeeded: int,
    max_tool_calls: int,
    turns_count: int | None,
    max_turns: int,
    failure_code: str,
) -> EvaluationRunOutcome:
    """Construct an explicitly observed failed-run outcome.

    The factory accepts the caller's measured counters and status verbatim. It
    does not catch runtime exceptions, inspect exception messages, or infer
    whether a failure was caused by a tool, budget, or runtime condition.
    """
    if not isinstance(status, EvaluationRunStatus) or status not in _FAILED_RUN_STATUSES:
        raise EvaluationValidationError(
            "failed_run_outcome only accepts TOOL_FAILURE, BUDGET_EXHAUSTED, "
            "or RUNTIME_FAILURE status."
        )
    return EvaluationRunOutcome(
        case_id=case_id,
        status=status,
        tool_calls_attempted=tool_calls_attempted,
        tool_calls_succeeded=tool_calls_succeeded,
        max_tool_calls=max_tool_calls,
        turns_count=turns_count,
        max_turns=max_turns,
        failure_code=failure_code,
    )


@dataclass(frozen=True)
class ToolOperationalScore:
    """Protocol-level tool operational score for one run."""

    case_id: str
    run_status: EvaluationRunStatus
    tool_calls_attempted: int
    tool_calls_succeeded: int
    tool_success_rate: Decimal | None
    budget_exhausted: bool

    def __post_init__(self) -> None:
        case_id = _clean_string(self.case_id, "case_id")
        if not isinstance(self.run_status, EvaluationRunStatus):
            raise EvaluationValidationError(
                "Field 'run_status' must be an EvaluationRunStatus."
            )
        attempted = _validate_int(
            self.tool_calls_attempted,
            "tool_calls_attempted",
            minimum=0,
        )
        succeeded = _validate_int(
            self.tool_calls_succeeded,
            "tool_calls_succeeded",
            minimum=0,
        )
        if succeeded > attempted:
            raise EvaluationValidationError(
                "tool_calls_succeeded must not exceed tool_calls_attempted."
            )
        if not isinstance(self.budget_exhausted, bool):
            raise EvaluationValidationError("Field 'budget_exhausted' must be bool.")

        rate = self.tool_success_rate
        if rate is not None:
            rate = _validate_rate(rate, "tool_success_rate")
        if attempted == 0:
            if rate is not None:
                raise EvaluationValidationError(
                    "tool_success_rate must be None when no tool calls were attempted."
                )
        else:
            expected_rate = Decimal(succeeded) / Decimal(attempted)
            if rate != expected_rate:
                raise EvaluationValidationError(
                    "tool_success_rate must equal succeeded calls divided by attempted calls."
                )

        expected_budget = self.run_status == EvaluationRunStatus.BUDGET_EXHAUSTED
        if self.budget_exhausted != expected_budget:
            raise EvaluationValidationError(
                "budget_exhausted must be true exactly for BUDGET_EXHAUSTED runs."
            )

        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "tool_calls_attempted", attempted)
        object.__setattr__(self, "tool_calls_succeeded", succeeded)
        object.__setattr__(self, "tool_success_rate", rate)


def score_tool_operations(outcome: EvaluationRunOutcome) -> ToolOperationalScore:
    """Score protocol-level tool success for one explicit run outcome."""
    if not isinstance(outcome, EvaluationRunOutcome):
        raise EvaluationValidationError(
            f"Expected EvaluationRunOutcome instance, got {type(outcome).__name__}."
        )
    attempted = outcome.tool_calls_attempted
    rate = (
        None
        if attempted == 0
        else Decimal(outcome.tool_calls_succeeded) / Decimal(attempted)
    )
    return ToolOperationalScore(
        case_id=outcome.case_id,
        run_status=outcome.status,
        tool_calls_attempted=attempted,
        tool_calls_succeeded=outcome.tool_calls_succeeded,
        tool_success_rate=rate,
        budget_exhausted=outcome.status == EvaluationRunStatus.BUDGET_EXHAUSTED,
    )


__all__ = [
    "EvaluationRunOutcome",
    "EvaluationRunStatus",
    "ToolOperationalScore",
    "completed_run_outcome",
    "failed_run_outcome",
    "score_tool_operations",
]
