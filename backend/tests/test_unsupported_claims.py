"""Hermetic tests for Diagnosis claim extraction and support scoring."""

from __future__ import annotations

import datetime
from decimal import Decimal
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
    DiagnosisClaim,
    DiagnosisClaimKind,
    EvaluationValidationError,
    UnsupportedClaimScore,
    build_diagnosis_claims,
    derive_diagnosis_claim_id,
    score_unsupported_claims,
)
from app.observations import Observation, ObservationStatus


NOW = datetime.datetime(2026, 2, 2, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 2, 2), datetime.date(2026, 2, 2))
BASELINE = DateRange(datetime.date(2026, 1, 26), datetime.date(2026, 2, 1))


def make_evidence(
    observation_id: str,
    metric: str,
    status: ObservationStatus,
    *,
    role: EvidenceRole,
    filters: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
):
    failed = status == ObservationStatus.FAILED
    insufficient = status == ObservationStatus.INSUFFICIENT_EVIDENCE
    filters = filters or {}
    dimensions = dimensions or {}
    group_by = tuple(dict.fromkeys((*filters, *dimensions)))
    observation = Observation(
        observation_id=observation_id,
        tool_name="query_metric",
        tool_call_id=f"call:{observation_id}",
        metric=metric,
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters=filters,
        group_by=group_by,
        dimensions=dimensions,
        current_value=None if failed else Decimal("80"),
        baseline_value=None if failed else Decimal("100"),
        relative_change=None if failed or insufficient else (
            Decimal("-0.20")
            if status == ObservationStatus.ANOMALOUS
            else Decimal("0.01")
        ),
        unit="usd" if metric == "sales" else "ratio",
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
    return promote_observation_to_evidence(observation, role=role)


def make_diagnosis(
    evidence_items,
    *,
    status: DiagnosisStatus = DiagnosisStatus.DIAGNOSED,
    evidence_ids=None,
    scope=None,
    change_override=None,
) -> Diagnosis:
    items = tuple(evidence_items)
    ids = tuple(
        evidence_ids
        if evidence_ids is not None
        else (item.evidence_id for item in items)
    )
    if status not in {DiagnosisStatus.DIAGNOSED, DiagnosisStatus.NO_MATERIAL_ANOMALY}:
        return Diagnosis(
            diagnosis_id=f"diag:{status.value}",
            status=status,
            target_metric="sales",
            change=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=ids,
            confidence=None,
            limitations=("Synthetic scoring state.",),
            created_at=NOW,
        )

    target = next(item for item in items if item.metric == "sales")
    change = change_override or DiagnosisChange(
        current_value=target.current_value,
        baseline_value=target.baseline_value,
        relative_change=target.relative_change,
        unit=target.unit,
        evidence_id=target.evidence_id,
    )
    diagnosed = status == DiagnosisStatus.DIAGNOSED
    return Diagnosis(
        diagnosis_id=f"diag:{status.value}",
        status=status,
        target_metric="sales",
        change=change,
        primary_driver="conversion_rate" if diagnosed else None,
        affected_scope=(
            scope
            if scope is not None
            else {
                "marketplace": "US",
                "asin": "ASIN-A",
                "traffic_source": "Ads",
            }
            if diagnosed
            else {}
        ),
        evidence_ids=ids,
        confidence=Decimal("0.90"),
        limitations=("Synthetic scoring state.",),
        created_at=NOW,
    )


def compose(items, diagnosis):
    return DiagnosisComposition(evidence=tuple(items), diagnosis=diagnosis)


class TestDiagnosisClaims(unittest.TestCase):
    def test_claim_expansion_is_ordered_and_deterministic(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        driver = make_evidence(
            "driver", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        diagnosis = make_diagnosis((target, driver))
        expected = (
            "claim:target_change:sales",
            "claim:primary_driver:conversion_rate",
            "claim:scope_member:marketplace:US",
            "claim:scope_member:asin:ASIN-A",
            "claim:scope_member:traffic_source:Ads",
        )
        first = build_diagnosis_claims(diagnosis)
        second = build_diagnosis_claims(diagnosis)
        self.assertEqual(tuple(item.claim_id for item in first), expected)
        self.assertEqual(first, second)

    def test_no_anomaly_and_non_success_claim_sets(self) -> None:
        normal = make_evidence(
            "normal", "sales", ObservationStatus.NORMAL,
            role=EvidenceRole.SUPPORTING,
        )
        no_anomaly = make_diagnosis(
            (normal,), status=DiagnosisStatus.NO_MATERIAL_ANOMALY
        )
        self.assertEqual(
            tuple(item.claim_id for item in build_diagnosis_claims(no_anomaly)),
            ("claim:target_change:sales",),
        )
        budget = make_diagnosis((), status=DiagnosisStatus.BUDGET_EXHAUSTED)
        self.assertEqual(build_diagnosis_claims(budget), ())

    def test_claim_model_derivation_and_validation(self) -> None:
        claim = DiagnosisClaim(
            claim_id="claim:scope_member:marketplace:US",
            kind=DiagnosisClaimKind.SCOPE_MEMBER,
            dimension="marketplace",
            dimension_value="US",
        )
        self.assertEqual(
            derive_diagnosis_claim_id(
                DiagnosisClaimKind.SCOPE_MEMBER,
                dimension="marketplace",
                dimension_value="US",
            ),
            claim.claim_id,
        )
        invalid = (
            dict(kind="scope_member", dimension="marketplace", dimension_value="US"),
            dict(
                kind=DiagnosisClaimKind.TARGET_CHANGE,
                metric="sales",
                claim_id="claim:target_change:orders",
            ),
            dict(
                kind=DiagnosisClaimKind.SCOPE_MEMBER,
                dimension="market:place",
                dimension_value="US",
                claim_id="claim:scope_member:market:place:US",
            ),
            dict(
                kind=DiagnosisClaimKind.PRIMARY_DRIVER,
                metric="sales",
                dimension="marketplace",
                claim_id="claim:primary_driver:sales",
            ),
        )
        for override in invalid:
            values = {
                "claim_id": "claim:target_change:sales",
                "kind": DiagnosisClaimKind.TARGET_CHANGE,
                "metric": "sales",
            }
            values.update(override)
            with self.subTest(override=override), self.assertRaises(EvaluationValidationError):
                DiagnosisClaim(**values)

    def test_scoring_perfect_diagnosed_composition_has_five_supported_claims(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        driver = make_evidence(
            "driver", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        result = score_unsupported_claims(compose((target, driver), make_diagnosis((target, driver))))
        self.assertEqual(result.unsupported_claim_rate, Decimal("0"))
        self.assertEqual(len(result.claim_ids), 5)
        self.assertEqual(result.supported_claim_ids, result.claim_ids)
        self.assertEqual(result.unsupported_claim_ids, ())
        self.assertEqual(
            result.supporting_evidence_ids_by_claim["claim:primary_driver:conversion_rate"],
            (driver.evidence_id,),
        )
        self.assertEqual(
            result.supporting_evidence_ids_by_claim["claim:scope_member:marketplace:US"],
            (driver.evidence_id,),
        )

    def test_unsupported_driver_partial_scope_and_fake_change_are_detected(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        driver_marketplace_only = make_evidence(
            "driver", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US"},
        )
        missing_driver = make_diagnosis((target,), scope={"marketplace": "US"})
        missing_result = score_unsupported_claims(compose((target,), missing_driver))
        self.assertEqual(
            missing_result.unsupported_claim_ids,
            (
                "claim:primary_driver:conversion_rate",
                "claim:scope_member:marketplace:US",
            ),
        )

        partial = make_diagnosis((target, driver_marketplace_only))
        partial_result = score_unsupported_claims(
            compose((target, driver_marketplace_only), partial)
        )
        self.assertEqual(
            partial_result.unsupported_claim_ids,
            (
                "claim:scope_member:marketplace:US",
                "claim:scope_member:asin:ASIN-A",
                "claim:scope_member:traffic_source:Ads",
            ),
        )

        fake_change = DiagnosisChange(
            current_value=Decimal("999"),
            baseline_value=target.baseline_value,
            relative_change=target.relative_change,
            unit=target.unit,
            evidence_id=target.evidence_id,
        )
        fake_result = score_unsupported_claims(
            compose((target, driver_marketplace_only), make_diagnosis(
                (target, driver_marketplace_only), change_override=fake_change
            ))
        )
        self.assertIn("claim:target_change:sales", fake_result.unsupported_claim_ids)

    def test_uncited_portfolio_evidence_cannot_support_claim(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        driver = make_evidence(
            "driver", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        diagnosis = make_diagnosis(
            (target, driver), evidence_ids=(target.evidence_id,)
        )
        result = score_unsupported_claims(compose((target, driver), diagnosis))
        self.assertNotIn(
            driver.evidence_id,
            tuple(
                evidence_id
                for evidence_ids in result.supporting_evidence_ids_by_claim.values()
                for evidence_id in evidence_ids
            ),
        )
        self.assertEqual(len(result.unsupported_claim_ids), 4)

    def test_scope_filter_dimension_conflict_fails_closed(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        conflict = make_evidence(
            "conflict", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US"},
            dimensions={"marketplace": "DE"},
        )
        result = score_unsupported_claims(
            compose((target, conflict), make_diagnosis((target, conflict), scope={"marketplace": "US"}))
        )
        self.assertIn("claim:primary_driver:conversion_rate", result.supported_claim_ids)
        self.assertIn("claim:scope_member:marketplace:US", result.unsupported_claim_ids)

    def test_scope_claims_require_one_full_scope_primary_driver_evidence(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        global_driver = make_evidence(
            "global-driver", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        unrelated_scoped = make_evidence(
            "unrelated-scoped", "sessions", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        diagnosis = make_diagnosis((target, global_driver, unrelated_scoped))
        result = score_unsupported_claims(
            compose((target, global_driver, unrelated_scoped), diagnosis)
        )
        expected_scope_claims = (
            "claim:scope_member:marketplace:US",
            "claim:scope_member:asin:ASIN-A",
            "claim:scope_member:traffic_source:Ads",
        )
        self.assertIn("claim:primary_driver:conversion_rate", result.supported_claim_ids)
        self.assertEqual(result.unsupported_claim_ids, expected_scope_claims)

        split_driver_scope = (
            make_evidence(
                "driver-marketplace", "conversion_rate", ObservationStatus.ANOMALOUS,
                role=EvidenceRole.SUPPORTING, filters={"marketplace": "US"},
            ),
            make_evidence(
                "driver-asin-traffic", "conversion_rate", ObservationStatus.ANOMALOUS,
                role=EvidenceRole.SUPPORTING, filters={"asin": "ASIN-A"},
                dimensions={"traffic_source": "Ads"},
            ),
        )
        split_diagnosis = make_diagnosis((target, *split_driver_scope))
        split_result = score_unsupported_claims(
            compose((target, *split_driver_scope), split_diagnosis)
        )
        self.assertEqual(split_result.unsupported_claim_ids, expected_scope_claims)

    def test_no_anomaly_and_empty_claim_scores(self) -> None:
        normal = make_evidence(
            "normal", "sales", ObservationStatus.NORMAL,
            role=EvidenceRole.SUPPORTING,
        )
        no_anomaly = make_diagnosis((normal,), status=DiagnosisStatus.NO_MATERIAL_ANOMALY)
        result = score_unsupported_claims(compose((normal,), no_anomaly))
        self.assertEqual(result.unsupported_claim_rate, Decimal("0"))
        self.assertEqual(result.supported_claim_ids, ("claim:target_change:sales",))

        budget = make_diagnosis((), status=DiagnosisStatus.BUDGET_EXHAUSTED)
        empty = score_unsupported_claims(compose((), budget))
        self.assertEqual(empty.claim_ids, ())
        self.assertIsNone(empty.unsupported_claim_rate)

    def test_one_evidence_supports_driver_and_all_scope_members(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        driver = make_evidence(
            "driver", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        result = score_unsupported_claims(compose((target, driver), make_diagnosis((target, driver))))
        for claim_id in result.claim_ids[1:]:
            self.assertEqual(result.supporting_evidence_ids_by_claim[claim_id], (driver.evidence_id,))

    def test_score_model_is_deeply_immutable_and_validated(self) -> None:
        claim_ids = ["claim:target_change:sales"]
        supported = ["claim:target_change:sales"]
        evidence_ids = ["evidence:target:supporting"]
        support_map = {"claim:target_change:sales": evidence_ids}
        score = UnsupportedClaimScore(
            diagnosis_id="diag:model",
            claim_ids=claim_ids,
            supported_claim_ids=supported,
            unsupported_claim_ids=[],
            supporting_evidence_ids_by_claim=support_map,
            unsupported_claim_rate=Decimal("0"),
        )
        claim_ids.clear()
        supported.clear()
        evidence_ids.clear()
        support_map.clear()
        self.assertEqual(score.claim_ids, ("claim:target_change:sales",))
        self.assertEqual(score.supporting_evidence_ids_by_claim["claim:target_change:sales"], ("evidence:target:supporting",))
        with self.assertRaises(TypeError):
            score.supporting_evidence_ids_by_claim["new"] = ()  # type: ignore[index]

        base = dict(
            diagnosis_id="diag:model",
            claim_ids=("claim:target_change:sales",),
            supported_claim_ids=("claim:target_change:sales",),
            unsupported_claim_ids=(),
            supporting_evidence_ids_by_claim={"claim:target_change:sales": ("evidence:target:supporting",)},
            unsupported_claim_rate=Decimal("0"),
        )
        invalid = (
            {"supported_claim_ids": (), "unsupported_claim_ids": (), "supporting_evidence_ids_by_claim": {}},
            {"supporting_evidence_ids_by_claim": {}},
            {"unsupported_claim_rate": None},
            {"unsupported_claim_rate": Decimal("1.1")},
            {"unsupported_claim_ids": ("claim:target_change:sales",), "unsupported_claim_rate": Decimal("1")},
        )
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(EvaluationValidationError):
                UnsupportedClaimScore(**{**base, **override})

    def test_determinism_and_wrong_types_fail_fast(self) -> None:
        target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
        )
        driver = make_evidence(
            "driver", "conversion_rate", ObservationStatus.ANOMALOUS,
            role=EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        current = compose((target, driver), make_diagnosis((target, driver)))
        self.assertEqual(score_unsupported_claims(current), score_unsupported_claims(current))
        with self.assertRaises(EvaluationValidationError):
            score_unsupported_claims(object())  # type: ignore[arg-type]
        with self.assertRaises(EvaluationValidationError):
            build_diagnosis_claims(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
