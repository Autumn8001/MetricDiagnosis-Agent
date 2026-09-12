"""Hermetic tests for Evidence citation precision and obligation coverage."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
import unittest

from app.analytics.models import DateRange
from app.diagnosis import (
    Diagnosis,
    DiagnosisChange,
    DiagnosisComposition,
    DiagnosisStatus,
)
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.evaluation import (
    EvidenceCitationScore,
    EvaluationValidationError,
    load_ground_truth_cases,
    score_evidence_citations,
)
from app.observations import Observation, ObservationStatus


ROOT = Path(__file__).resolve().parents[2]
GROUND_TRUTH = ROOT / "warehouse" / "ground_truth.json"
NOW = datetime.datetime(2026, 2, 2, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 2, 2), datetime.date(2026, 2, 2))
BASELINE = DateRange(datetime.date(2026, 1, 26), datetime.date(2026, 2, 1))


def make_observation(
    observation_id: str,
    metric: str,
    status: ObservationStatus,
    *,
    filters: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
) -> Observation:
    failed = status == ObservationStatus.FAILED
    insufficient = status == ObservationStatus.INSUFFICIENT_EVIDENCE
    return Observation(
        observation_id=observation_id,
        tool_name="query_metric",
        tool_call_id=f"call:{observation_id}",
        metric=metric,
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters=filters or {},
        group_by=tuple((dimensions or {}).keys()),
        dimensions=dimensions or {},
        current_value=None if failed else Decimal("80"),
        baseline_value=None if failed else Decimal("100"),
        relative_change=None if failed or insufficient else (
            Decimal("-0.20")
            if status == ObservationStatus.ANOMALOUS
            else Decimal("0.01")
        ),
        unit="ratio" if metric == "conversion_rate" else "usd",
        sample_size=None if failed else Decimal("500"),
        source_status="failed" if failed else (
            "insufficient_data" if insufficient else "ok"
        ),
        status=status,
        query_or_result_reference=f"ref:{observation_id}",
        created_at=NOW,
        error_code="QUERY_FAILED" if failed else None,
        error_message="query failed" if failed else None,
    )


def evidence(
    observation_id: str,
    metric: str,
    status: ObservationStatus,
    *,
    role: EvidenceRole,
    filters: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
):
    return promote_observation_to_evidence(
        make_observation(
            observation_id,
            metric,
            status,
            filters=filters,
            dimensions=dimensions,
        ),
        role=role,
    )


def make_diagnosis(
    evidence_items,
    *,
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED,
    evidence_ids=None,
) -> Diagnosis:
    items = tuple(evidence_items)
    ids = tuple(evidence_ids if evidence_ids is not None else (item.evidence_id for item in items))
    if status == DiagnosisStatus.BUDGET_EXHAUSTED:
        return Diagnosis(
            diagnosis_id="diag:score-budget",
            status=status,
            target_metric="sales",
            change=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=ids,
            confidence=None,
            limitations=("Scoring-only synthetic diagnosis.",),
            created_at=NOW,
        )

    target = next(item for item in items if item.metric == "sales")
    if status == DiagnosisStatus.NO_MATERIAL_ANOMALY:
        primary_driver = None
        scope = {}
    else:
        primary_driver = "conversion_rate"
        scope = {
            "marketplace": "US",
            "asin": "ASIN-A",
            "traffic_source": "Ads",
        }
    return Diagnosis(
        diagnosis_id=f"diag:score-{status.value}",
        status=status,
        target_metric="sales",
        change=DiagnosisChange(
            current_value=target.current_value,
            baseline_value=target.baseline_value,
            relative_change=target.relative_change,
            unit=target.unit,
            evidence_id=target.evidence_id,
        ),
        primary_driver=primary_driver,
        affected_scope=scope,
        evidence_ids=ids,
        confidence=Decimal("0.90"),
        limitations=("Scoring-only synthetic diagnosis.",),
        created_at=NOW,
    )


def composition(evidence_items, diagnosis: Diagnosis) -> DiagnosisComposition:
    return DiagnosisComposition(evidence=tuple(evidence_items), diagnosis=diagnosis)


class TestEvidenceCitationScoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canonical, cls.traffic, cls.no_anomaly = load_ground_truth_cases(GROUND_TRUTH)

    def canonical_evidence(self):
        return (
            evidence("target", "sales", ObservationStatus.ANOMALOUS, role=EvidenceRole.SUPPORTING),
            evidence(
                "driver",
                "conversion_rate",
                ObservationStatus.ANOMALOUS,
                role=EvidenceRole.SUPPORTING,
                filters={"marketplace": "US", "asin": "ASIN-A"},
                dimensions={"traffic_source": "Ads"},
            ),
            evidence("aov", "aov", ObservationStatus.NORMAL, role=EvidenceRole.SUPPORTING),
            evidence(
                "sessions-de",
                "sessions",
                ObservationStatus.NORMAL,
                role=EvidenceRole.NEGATIVE_CONTROL,
                dimensions={"marketplace": "DE"},
            ),
            evidence(
                "marketplace-uk",
                "sessions",
                ObservationStatus.NORMAL,
                role=EvidenceRole.NEGATIVE_CONTROL,
                dimensions={"marketplace": "UK"},
            ),
            evidence(
                "asin-b",
                "conversion_rate",
                ObservationStatus.NORMAL,
                role=EvidenceRole.NEGATIVE_CONTROL,
                dimensions={"asin": "ASIN-B"},
            ),
            evidence(
                "asin-c",
                "conversion_rate",
                ObservationStatus.NORMAL,
                role=EvidenceRole.NEGATIVE_CONTROL,
                dimensions={"asin": "ASIN-C"},
            ),
            evidence(
                "organic",
                "conversion_rate",
                ObservationStatus.NORMAL,
                role=EvidenceRole.NEGATIVE_CONTROL,
                dimensions={"traffic_source": "Organic"},
            ),
        )

    def test_canonical_perfect_citations_have_precision_and_coverage_one(self) -> None:
        items = self.canonical_evidence()
        result = score_evidence_citations(
            self.canonical,
            composition(items, make_diagnosis(items)),
        )

        self.assertEqual(result.citation_precision, Decimal("1"))
        self.assertEqual(result.evidence_coverage, Decimal("1"))
        self.assertEqual(result.matched_citation_ids, result.cited_evidence_ids)
        self.assertEqual(result.unsupported_citation_ids, ())
        self.assertEqual(result.covered_obligation_ids, result.obligation_ids)

    def test_related_citations_can_be_relevant_but_cover_only_some_obligations(self) -> None:
        items = self.canonical_evidence()
        cited = items[:3]
        result = score_evidence_citations(
            self.canonical,
            composition(items, make_diagnosis(items, evidence_ids=[item.evidence_id for item in cited])),
        )

        self.assertEqual(result.citation_precision, Decimal("1"))
        self.assertLess(result.evidence_coverage, Decimal("1"))
        self.assertEqual(len(result.covered_obligation_ids), 3)

    def test_unrelated_citation_lowers_precision(self) -> None:
        items = self.canonical_evidence()
        unrelated = evidence(
            "unrelated",
            "inventory",
            ObservationStatus.NORMAL,
            role=EvidenceRole.SUPPORTING,
        )
        portfolio = (items[0], unrelated)
        result = score_evidence_citations(
            self.canonical,
            composition(portfolio, make_diagnosis(portfolio)),
        )

        self.assertEqual(result.citation_precision, Decimal("0.5"))
        self.assertEqual(result.matched_citation_ids, (items[0].evidence_id,))
        self.assertEqual(result.unsupported_citation_ids, (unrelated.evidence_id,))

    def test_uncited_portfolio_evidence_does_not_improve_coverage(self) -> None:
        items = self.canonical_evidence()
        cited = (items[0],)
        result = score_evidence_citations(
            self.canonical,
            composition(items, make_diagnosis(items, evidence_ids=[items[0].evidence_id])),
        )

        self.assertEqual(result.citation_precision, Decimal("1"))
        self.assertEqual(result.evidence_coverage, Decimal("1") / Decimal("9"))
        self.assertNotIn(items[1].evidence_id, result.cited_evidence_ids)
        self.assertEqual(cited[0].evidence_id, result.cited_evidence_ids[0])

    def test_zero_citations_have_undefined_precision_and_zero_coverage(self) -> None:
        diagnosis = make_diagnosis((), status=DiagnosisStatus.BUDGET_EXHAUSTED)
        result = score_evidence_citations(
            self.canonical,
            composition((), diagnosis),
        )

        self.assertIsNone(result.citation_precision)
        self.assertEqual(result.evidence_coverage, Decimal("0"))
        self.assertEqual(result.matched_citation_ids, ())
        self.assertEqual(result.unsupported_citation_ids, ())
        self.assertEqual(result.covered_obligation_ids, ())

    def test_one_evidence_can_cover_stable_metric_and_negative_control(self) -> None:
        items = self.canonical_evidence()
        sessions_de = items[3]
        target = items[0]
        portfolio = (target, sessions_de)
        result = score_evidence_citations(
            self.canonical,
            composition(portfolio, make_diagnosis(portfolio)),
        )

        self.assertEqual(result.citation_precision, Decimal("1"))
        self.assertIn(
            "obligation:stable_metric:sessions",
            result.covered_obligation_ids,
        )
        self.assertIn(
            "obligation:negative_control:marketplace:DE",
            result.covered_obligation_ids,
        )

    def test_conflicting_filter_and_dimension_does_not_match_control(self) -> None:
        conflict = evidence(
            "conflict",
            "inventory",
            ObservationStatus.NORMAL,
            role=EvidenceRole.NEGATIVE_CONTROL,
            filters={"marketplace": "US"},
            dimensions={"marketplace": "DE"},
        )
        diagnosis = make_diagnosis((conflict,), status=DiagnosisStatus.BUDGET_EXHAUSTED)
        result = score_evidence_citations(
            self.canonical,
            composition((conflict,), diagnosis),
        )

        self.assertEqual(result.citation_precision, Decimal("0"))
        self.assertEqual(result.evidence_coverage, Decimal("0"))
        self.assertEqual(result.unsupported_citation_ids, (conflict.evidence_id,))

    def test_no_anomaly_case_can_be_fully_covered(self) -> None:
        stable_items = tuple(
            evidence(
                f"stable-{metric}",
                metric,
                ObservationStatus.NORMAL,
                role=EvidenceRole.SUPPORTING,
            )
            for metric in ("sales", "orders", "sessions", "conversion_rate", "aov")
        )
        controls = tuple(
            evidence(
                f"control-{dimension}-{value}",
                "sessions",
                ObservationStatus.NORMAL,
                role=EvidenceRole.NEGATIVE_CONTROL,
                dimensions={dimension: value},
            )
            for dimension, values in (
                ("marketplace", ("US", "DE", "UK")),
                ("asin", ("ASIN-A", "ASIN-B", "ASIN-C")),
                ("traffic_source", ("Ads", "Organic")),
            )
            for value in values
        )
        items = stable_items + controls
        result = score_evidence_citations(
            self.no_anomaly,
            composition(items, make_diagnosis(items, status=DiagnosisStatus.NO_MATERIAL_ANOMALY)),
        )

        self.assertEqual(result.citation_precision, Decimal("1"))
        self.assertEqual(result.evidence_coverage, Decimal("1"))
        self.assertEqual(len(result.obligation_ids), 13)

    def test_score_model_snapshots_ids_and_rejects_invalid_invariants(self) -> None:
        cited = ["evidence:one:supporting"]
        score = EvidenceCitationScore(
            case_id="case-model",
            cited_evidence_ids=cited,
            matched_citation_ids=cited,
            unsupported_citation_ids=[],
            obligation_ids=["obligation:one"],
            covered_obligation_ids=["obligation:one"],
            citation_precision=Decimal("1"),
            evidence_coverage=Decimal("1"),
        )
        cited.clear()
        self.assertEqual(score.cited_evidence_ids, ("evidence:one:supporting",))

        invalid = [
            dict(matched_citation_ids=(), citation_precision=Decimal("0.5")),
            dict(obligation_ids=(), covered_obligation_ids=(), evidence_coverage=Decimal("0")),
            dict(covered_obligation_ids=("obligation:unknown",)),
            dict(evidence_coverage=Decimal("1.1")),
            dict(cited_evidence_ids=("duplicate", "duplicate")),
        ]
        base = dict(
            case_id="case-model",
            cited_evidence_ids=("evidence:one:supporting",),
            matched_citation_ids=("evidence:one:supporting",),
            unsupported_citation_ids=(),
            obligation_ids=("obligation:one",),
            covered_obligation_ids=("obligation:one",),
            citation_precision=Decimal("1"),
            evidence_coverage=Decimal("1"),
        )
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(EvaluationValidationError):
                EvidenceCitationScore(**{**base, **override})

    def test_scoring_is_deterministic_and_rejects_wrong_input_types(self) -> None:
        items = self.canonical_evidence()
        current = composition(items, make_diagnosis(items))
        first = score_evidence_citations(self.canonical, current)
        second = score_evidence_citations(self.canonical, current)
        self.assertEqual(first, second)
        with self.assertRaises(EvaluationValidationError):
            score_evidence_citations(object(), current)  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            score_evidence_citations(self.canonical, object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
