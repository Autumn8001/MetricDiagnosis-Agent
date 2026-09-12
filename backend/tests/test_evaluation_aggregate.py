"""Hermetic tests for deterministic Evaluation Core aggregation."""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.evaluation import (
    CoreCaseScore,
    CoreEvaluationReport,
    EvaluationValidationError,
    aggregate_core_scores,
)


DIMENSIONS = ("marketplace", "asin", "traffic_source")


def score(
    case_id: str,
    *,
    status: bool,
    target: bool,
    driver: bool,
    scope: tuple[bool, bool, bool],
    exact: bool,
    no_anomaly: bool,
) -> CoreCaseScore:
    scope_correct = dict(zip(DIMENSIONS, scope))
    scope_accuracy = Decimal(sum(scope)) / Decimal("3")
    return CoreCaseScore(
        case_id=case_id,
        status_correct=status,
        target_metric_correct=target,
        driver_correct=driver,
        scope_correct=scope_correct,
        scope_accuracy=scope_accuracy,
        exact_match=exact,
        no_anomaly_correct=no_anomaly,
    )


def report_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "case_count": 1,
        "status_accuracy": Decimal("1"),
        "target_metric_accuracy": Decimal("1"),
        "driver_accuracy": Decimal("1"),
        "no_anomaly_accuracy": Decimal("1"),
        "exact_match_rate": Decimal("1"),
        "scope_accuracy_by_dimension": {
            "marketplace": Decimal("1"),
            "asin": Decimal("1"),
            "traffic_source": Decimal("1"),
        },
        "macro_scope_accuracy": Decimal("1"),
        "case_ids": ("case-1",),
    }
    values.update(overrides)
    return values


class TestCoreEvaluationAggregate(unittest.TestCase):
    def test_aggregates_mixed_scores_with_exact_decimal_rates_and_order(self) -> None:
        scores = [
            score(
                "case-1",
                status=True,
                target=True,
                driver=True,
                scope=(True, True, True),
                exact=True,
                no_anomaly=True,
            ),
            score(
                "case-2",
                status=True,
                target=False,
                driver=False,
                scope=(True, False, False),
                exact=False,
                no_anomaly=False,
            ),
            score(
                "case-3",
                status=False,
                target=True,
                driver=False,
                scope=(False, True, False),
                exact=False,
                no_anomaly=True,
            ),
        ]

        report = aggregate_core_scores(scores)

        self.assertEqual(report.case_count, 3)
        self.assertEqual(report.status_accuracy, Decimal("2") / Decimal("3"))
        self.assertEqual(report.target_metric_accuracy, Decimal("2") / Decimal("3"))
        self.assertEqual(report.driver_accuracy, Decimal("1") / Decimal("3"))
        self.assertEqual(report.no_anomaly_accuracy, Decimal("2") / Decimal("3"))
        self.assertEqual(report.exact_match_rate, Decimal("1") / Decimal("3"))
        self.assertEqual(
            dict(report.scope_accuracy_by_dimension),
            {
                "marketplace": Decimal("2") / Decimal("3"),
                "asin": Decimal("2") / Decimal("3"),
                "traffic_source": Decimal("1") / Decimal("3"),
            },
        )
        expected_macro = sum(
            report.scope_accuracy_by_dimension.values(),
            Decimal("0"),
        ) / Decimal("3")
        self.assertEqual(report.macro_scope_accuracy, expected_macro)
        self.assertEqual(report.case_ids, ("case-1", "case-2", "case-3"))

    def test_single_case_report_has_exact_zero_or_one_rates(self) -> None:
        report = aggregate_core_scores(
            (
                score(
                    "single",
                    status=True,
                    target=True,
                    driver=True,
                    scope=(True, True, True),
                    exact=True,
                    no_anomaly=False,
                ),
            )
        )

        self.assertEqual(report.case_count, 1)
        self.assertEqual(report.status_accuracy, Decimal("1"))
        self.assertEqual(report.target_metric_accuracy, Decimal("1"))
        self.assertEqual(report.driver_accuracy, Decimal("1"))
        self.assertEqual(report.no_anomaly_accuracy, Decimal("0"))
        self.assertEqual(report.exact_match_rate, Decimal("1"))
        self.assertEqual(dict(report.scope_accuracy_by_dimension), {
            dimension: Decimal("1") for dimension in DIMENSIONS
        })
        self.assertEqual(report.macro_scope_accuracy, Decimal("1"))

    def test_input_list_mutation_does_not_change_report_snapshot(self) -> None:
        source = [
            score(
                "source-case",
                status=True,
                target=True,
                driver=True,
                scope=(True, True, True),
                exact=True,
                no_anomaly=True,
            )
        ]
        report = aggregate_core_scores(source)
        source.clear()

        self.assertEqual(report.case_count, 1)
        self.assertEqual(report.case_ids, ("source-case",))

    def test_rejects_empty_string_non_scores_and_duplicate_case_ids(self) -> None:
        valid = score(
            "duplicate",
            status=True,
            target=True,
            driver=True,
            scope=(True, True, True),
            exact=True,
            no_anomaly=True,
        )
        invalid_inputs = [
            [],
            "not-a-score-sequence",
            [valid, object()],
            [valid, valid],
        ]
        for invalid in invalid_inputs:
            with self.subTest(invalid=invalid):
                with self.assertRaises(EvaluationValidationError):
                    aggregate_core_scores(invalid)  # type: ignore[arg-type]

    def test_report_freezes_case_ids_and_scope_mapping_sources(self) -> None:
        case_ids = ["case-source"]
        scope = {
            "marketplace": Decimal("1"),
            "asin": Decimal("0"),
            "traffic_source": Decimal("1"),
        }
        report = CoreEvaluationReport(
            **report_kwargs(
                scope_accuracy_by_dimension=scope,
                macro_scope_accuracy=Decimal("2") / Decimal("3"),
                case_ids=case_ids,
            )
        )
        case_ids.clear()
        scope["marketplace"] = Decimal("0")

        self.assertEqual(report.case_ids, ("case-source",))
        self.assertEqual(report.scope_accuracy_by_dimension["marketplace"], Decimal("1"))
        with self.assertRaises(TypeError):
            report.scope_accuracy_by_dimension["marketplace"] = Decimal("0")  # type: ignore[index]

    def test_report_rejects_invalid_case_count_and_case_ids(self) -> None:
        invalid = [
            {"case_count": True},
            {"case_count": 0},
            {"case_count": 2},
            {"case_ids": ()},
            {"case_ids": "case-1"},
            {"case_ids": ("case-1", "case-1")},
            {"case_ids": ("",)},
        ]
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(EvaluationValidationError):
                CoreEvaluationReport(**report_kwargs(**override))

    def test_report_rejects_non_decimal_out_of_range_and_non_finite_rates(self) -> None:
        scalar_fields = (
            "status_accuracy",
            "target_metric_accuracy",
            "driver_accuracy",
            "no_anomaly_accuracy",
            "exact_match_rate",
            "macro_scope_accuracy",
        )
        for field_name in scalar_fields:
            for value in (0.5, Decimal("-0.01"), Decimal("1.01"), Decimal("NaN"), Decimal("Infinity")):
                with self.subTest(field_name=field_name, value=value):
                    with self.assertRaises(EvaluationValidationError):
                        CoreEvaluationReport(**report_kwargs(**{field_name: value}))

        for value in (0.5, Decimal("NaN"), Decimal("1.01")):
            with self.subTest(scope_value=value):
                scope = {
                    "marketplace": Decimal("1"),
                    "asin": Decimal("1"),
                    "traffic_source": value,
                }
                with self.assertRaises(EvaluationValidationError):
                    CoreEvaluationReport(**report_kwargs(scope_accuracy_by_dimension=scope))

    def test_report_rejects_wrong_scope_shape_and_macro(self) -> None:
        for scope in (
            {"marketplace": Decimal("1"), "asin": Decimal("1")},
            {
                "marketplace": Decimal("1"),
                "asin": Decimal("1"),
                "traffic_source": Decimal("1"),
                "extra": Decimal("1"),
            },
        ):
            with self.subTest(scope=scope), self.assertRaises(EvaluationValidationError):
                CoreEvaluationReport(**report_kwargs(scope_accuracy_by_dimension=scope))

        with self.assertRaises(EvaluationValidationError):
            CoreEvaluationReport(**report_kwargs(macro_scope_accuracy=Decimal("0")))


if __name__ == "__main__":
    unittest.main()
