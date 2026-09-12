"""Hermetic tests for operational aggregate semantics."""

from decimal import Decimal
import unittest

from app.evaluation import (
    EvaluationRunStatus,
    EvaluationValidationError,
    ToolOperationalAggregateReport,
    ToolOperationalScore,
    aggregate_tool_operations,
)


def score(case: str, attempted: int, succeeded: int, budget: bool = False) -> ToolOperationalScore:
    status = EvaluationRunStatus.BUDGET_EXHAUSTED if budget else EvaluationRunStatus.COMPLETED
    rate = None if attempted == 0 else Decimal(succeeded) / Decimal(attempted)
    return ToolOperationalScore(case, status, attempted, succeeded, rate, budget)


class TestOperationalAggregate(unittest.TestCase):
    def test_uses_call_micro_and_run_denominators(self) -> None:
        report = aggregate_tool_operations((score("a", 1, 1), score("b", 4, 2, True)))
        self.assertEqual(report.run_count, 2)
        self.assertEqual(report.tool_success_rate, Decimal("3") / Decimal("5"))
        self.assertEqual(report.average_tool_call_count, Decimal("5") / Decimal("2"))
        self.assertEqual(report.budget_exhaustion_rate, Decimal("0.5"))

    def test_order_and_snapshot_are_stable(self) -> None:
        source = [score("a", 2, 1)]
        report = aggregate_tool_operations(source)
        source.clear()
        self.assertEqual(report.run_ids, ("a",))
        self.assertEqual(report, aggregate_tool_operations((score("a", 2, 1),)))

    def test_zero_attempts_still_count_runs(self) -> None:
        report = aggregate_tool_operations((score("a", 0, 0), score("b", 0, 0, True)))
        self.assertIsNone(report.tool_success_rate)
        self.assertEqual(report.average_tool_call_count, Decimal("0"))
        self.assertEqual(report.budget_exhaustion_rate, Decimal("0.5"))

    def test_empty_input_has_undefined_rates(self) -> None:
        report = aggregate_tool_operations(())
        self.assertEqual(report.run_count, 0)
        self.assertIsNone(report.tool_success_rate)
        self.assertIsNone(report.average_tool_call_count)
        self.assertIsNone(report.budget_exhaustion_rate)

    def test_rejects_bad_inputs_and_duplicate_ids(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            aggregate_tool_operations("scores")  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            aggregate_tool_operations((score("a", 1, 1), score("a", 1, 1)))
        with self.assertRaises(EvaluationValidationError):
            aggregate_tool_operations((object(),))  # type: ignore[arg-type]

    def test_model_rejects_inconsistent_formulas_and_counts(self) -> None:
        base = dict(
            run_count=1, run_ids=("a",), tool_calls_attempted=2,
            tool_calls_succeeded=1, tool_success_rate=Decimal("1"),
            average_tool_call_count=Decimal("2"), budget_exhausted_run_count=0,
            budget_exhaustion_rate=Decimal("0"),
        )
        with self.assertRaises(EvaluationValidationError):
            ToolOperationalAggregateReport(**base)
        with self.assertRaises(EvaluationValidationError):
            ToolOperationalAggregateReport(**{**base, "tool_success_rate": Decimal("0.5"), "tool_calls_succeeded": 3})
        with self.assertRaises(EvaluationValidationError):
            ToolOperationalAggregateReport(**{**base, "tool_success_rate": Decimal("0.5"), "run_count": 2})

    def test_model_rejects_non_finite_values(self) -> None:
        with self.assertRaises(EvaluationValidationError):
            ToolOperationalAggregateReport(
                1, ("a",), 1, 1, Decimal("NaN"), Decimal("1"), 0, Decimal("0")
            )


if __name__ == "__main__":
    unittest.main()
