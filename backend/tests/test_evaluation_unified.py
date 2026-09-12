"""Hermetic tests for the unified evaluation report."""

from decimal import Decimal
import unittest

from app.evaluation import (
    CoreCaseScore, CoreEvaluationReport, EvidenceCitationScore,
    EvaluationRunStatus, ToolOperationalAggregateReport, ToolOperationalScore,
    UnsupportedClaimScore, UnifiedEvaluationReport, EvaluationValidationError,
    aggregate_tool_operations, build_unified_evaluation_report,
)


def core(ids):
    scores = tuple(CoreCaseScore(i, True, True, True, {"marketplace": True, "asin": True, "traffic_source": True}, Decimal("1"), True, True) for i in ids)
    from app.evaluation import aggregate_core_scores
    return aggregate_core_scores(scores)


def evidence(case, precision):
    if precision is None:
        return EvidenceCitationScore(case, (), (), (), ("o",), (), None, Decimal("0"))
    return EvidenceCitationScore(case, ("e",), ("e",), (), ("o",), ("o",), precision, Decimal("1"))


def claims(diagnosis):
    return UnsupportedClaimScore(diagnosis, ("c",), ("c",), (), {"c": ("e",)}, Decimal("0"))


class TestUnifiedEvaluation(unittest.TestCase):
    def test_composes_and_uses_defined_precision_and_claim_micro(self):
        ids = ("case-a", "case-b")
        op = aggregate_tool_operations((ToolOperationalScore("case-a", EvaluationRunStatus.COMPLETED, 1, 1, Decimal("1"), False), ToolOperationalScore("case-b", EvaluationRunStatus.COMPLETED, 3, 1, Decimal("1") / Decimal("3"), False)))
        report = build_unified_evaluation_report(core(ids), [evidence("case-b", None), evidence("case-a", Decimal("1"))], [claims("diag-a"), claims("diag-b")], op)
        self.assertEqual(report.evidence_scores[0].case_id, "case-a")
        self.assertEqual(report.evidence_citation_precision, Decimal("1"))
        self.assertEqual(report.evidence_coverage, Decimal("0.5"))
        self.assertEqual(report.unsupported_claim_rate, Decimal("0"))
        self.assertEqual(report.operational_report.run_ids, ids)

    def test_rejects_identity_mismatch_duplicate_diagnosis_and_bad_types(self):
        op = aggregate_tool_operations((ToolOperationalScore("a", EvaluationRunStatus.COMPLETED, 1, 1, Decimal("1"), False),))
        with self.assertRaises(EvaluationValidationError):
            build_unified_evaluation_report(core(("a",)), [evidence("b", Decimal("1"))], [], op)
        with self.assertRaises(EvaluationValidationError):
            build_unified_evaluation_report(core(("a",)), [evidence("a", Decimal("1"))], [claims("d"), claims("d")], op)
        with self.assertRaises(EvaluationValidationError):
            build_unified_evaluation_report(object(), [], [], op)  # type: ignore[arg-type]

    def test_model_rejects_forged_derived_rates_and_is_frozen(self):
        op = aggregate_tool_operations((ToolOperationalScore("a", EvaluationRunStatus.COMPLETED, 1, 1, Decimal("1"), False),))
        kwargs = dict(core_report=core(("a",)), evidence_scores=(evidence("a", Decimal("1")),), unsupported_claim_scores=(), operational_report=op, evidence_citation_precision=Decimal("0"), evidence_coverage=Decimal("1"), unsupported_claim_rate=None)
        with self.assertRaises(EvaluationValidationError):
            UnifiedEvaluationReport(**kwargs)
        report = build_unified_evaluation_report(core(("a",)), [evidence("a", Decimal("1"))], [], op)
        with self.assertRaises(AttributeError):
            report.evidence_scores = ()  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
