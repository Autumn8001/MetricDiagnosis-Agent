"""Hermetic tests for Evidence-driven structured Diagnosis contracts."""

import datetime
from decimal import Decimal
from dataclasses import fields
import unittest

from app.analytics.models import DateRange
from app.diagnosis import (
    Diagnosis,
    DiagnosisChange,
    DiagnosisStatus,
    DiagnosisValidationError,
    build_diagnosis,
)
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.observations.models import Observation, ObservationStatus


NOW = datetime.datetime(2026, 1, 31, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 1, 31), datetime.date(2026, 1, 31))
BASELINE = DateRange(datetime.date(2026, 1, 24), datetime.date(2026, 1, 30))


def evidence(
    obs_id: str,
    metric: str,
    status: ObservationStatus,
    role: EvidenceRole,
    *,
    filters=None,
    dimensions=None,
):
    failed = status == ObservationStatus.FAILED
    obs = Observation(
        observation_id=obs_id,
        tool_name="query_metric",
        tool_call_id=f"call_{obs_id}",
        metric=metric,
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters=filters or {},
        group_by=tuple((dimensions or {}).keys()),
        dimensions=dimensions or {},
        current_value=None if failed else Decimal("80"),
        baseline_value=None if failed else Decimal("100"),
        relative_change=None if failed else (Decimal("-0.20") if status == ObservationStatus.ANOMALOUS else Decimal("0.01")),
        unit="count",
        sample_size=None if failed else Decimal("500"),
        source_status="failed" if failed else "ok",
        status=status,
        query_or_result_reference=f"ref:{obs_id}",
        created_at=NOW,
        error_code="QUERY_FAILED" if failed else None,
        error_message="query failed" if failed else None,
    )
    return promote_observation_to_evidence(obs, role=role)


class TestDiagnosis(unittest.TestCase):
    def setUp(self) -> None:
        self.target = evidence("sales", "sales", ObservationStatus.ANOMALOUS, EvidenceRole.SUPPORTING)
        self.driver = evidence(
            "cr_scope", "conversion_rate", ObservationStatus.ANOMALOUS, EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"}, dimensions={"traffic_source": "Ads"},
        )
        self.control = evidence("sessions", "sessions", ObservationStatus.NORMAL, EvidenceRole.NEGATIVE_CONTROL)
        self.normal_target = evidence("sales_normal", "sales", ObservationStatus.NORMAL, EvidenceRole.SUPPORTING)
        self.limitation = evidence("limited", "aov", ObservationStatus.INCONCLUSIVE, EvidenceRole.LIMITATION)
        self.failed = evidence("failed", "sales", ObservationStatus.FAILED, EvidenceRole.LIMITATION)

    def diagnosed(self):
        return build_diagnosis(
            diagnosis_id="diag:1", status=DiagnosisStatus.DIAGNOSED, target_metric="sales",
            evidence=[self.target, self.driver, self.control], target_evidence_id=self.target.evidence_id,
            primary_driver="conversion_rate",
            affected_scope={"marketplace": "US", "asin": "ASIN-A", "traffic_source": "Ads"},
            confidence=Decimal("0.90"), limitations=["Data contribution only; external cause is unproven."],
            created_at=NOW,
        )

    def test_diagnosed_copies_change_and_references_evidence(self) -> None:
        diagnosis = self.diagnosed()
        self.assertEqual(diagnosis.change.current_value, self.target.current_value)
        self.assertEqual(diagnosis.change.relative_change, self.target.relative_change)
        self.assertEqual(diagnosis.evidence_ids, (self.target.evidence_id, self.driver.evidence_id, self.control.evidence_id))
        self.assertEqual(diagnosis.affected_scope["traffic_source"], "Ads")

    def test_no_material_anomaly_success(self) -> None:
        diagnosis = build_diagnosis(
            diagnosis_id="diag:normal", status=DiagnosisStatus.NO_MATERIAL_ANOMALY,
            target_metric="sales", evidence=[self.normal_target],
            target_evidence_id=self.normal_target.evidence_id, confidence=Decimal("0.80"),
            limitations=["Synthetic benchmark only."], created_at=NOW,
        )
        self.assertIsNone(diagnosis.primary_driver)
        self.assertEqual(dict(diagnosis.affected_scope), {})

    def test_non_success_states_success(self) -> None:
        insufficient = build_diagnosis(
            diagnosis_id="diag:insufficient", status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
            target_metric="sales", evidence=[self.limitation], limitations=["Evidence is inconclusive."], created_at=NOW,
        )
        budget = build_diagnosis(
            diagnosis_id="diag:budget", status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales", evidence=[], limitations=["Eight-call budget exhausted."], created_at=NOW,
        )
        failure_without_evidence = build_diagnosis(
            diagnosis_id="diag:failure0", status=DiagnosisStatus.TOOL_FAILURE,
            target_metric="sales", evidence=[], limitations=["Tool failed before an Observation existed."], created_at=NOW,
        )
        failure = build_diagnosis(
            diagnosis_id="diag:failure", status=DiagnosisStatus.TOOL_FAILURE,
            target_metric="sales", evidence=[self.failed], limitations=["Warehouse query failed."], created_at=NOW,
        )
        self.assertEqual(insufficient.status, DiagnosisStatus.INSUFFICIENT_EVIDENCE)
        self.assertEqual(budget.evidence_ids, ())
        self.assertEqual(failure_without_evidence.evidence_ids, ())
        self.assertEqual(failure.evidence_ids, (self.failed.evidence_id,))

    def test_diagnosed_requires_target_driver_scope_and_negative_control_support(self) -> None:
        cases = [
            dict(evidence=[self.driver, self.control], target_evidence_id="missing"),
            dict(evidence=[self.target, self.control], target_evidence_id=self.target.evidence_id),
            dict(evidence=[self.target, self.driver], target_evidence_id=self.target.evidence_id),
            dict(evidence=[self.target, self.driver, self.control], target_evidence_id=self.target.evidence_id,
                 affected_scope={"marketplace": "DE"}),
        ]
        for overrides in cases:
            kwargs = dict(
                diagnosis_id="bad", status=DiagnosisStatus.DIAGNOSED, target_metric="sales",
                evidence=[self.target, self.driver, self.control], target_evidence_id=self.target.evidence_id,
                primary_driver="conversion_rate", affected_scope={"marketplace": "US"},
                confidence=Decimal("0.5"), limitations=["boundary"], created_at=NOW,
            )
            kwargs.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(DiagnosisValidationError):
                build_diagnosis(**kwargs)

    def test_diagnosed_requires_one_driver_evidence_to_cover_full_scope(self) -> None:
        global_driver = evidence(
            "global_cr", "conversion_rate", ObservationStatus.ANOMALOUS,
            EvidenceRole.SUPPORTING,
        )
        unrelated_scoped = evidence(
            "scoped_sessions", "sessions", ObservationStatus.ANOMALOUS,
            EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        split_driver_scope = (
            evidence(
                "cr_marketplace", "conversion_rate", ObservationStatus.ANOMALOUS,
                EvidenceRole.SUPPORTING, filters={"marketplace": "US"},
            ),
            evidence(
                "cr_asin_traffic", "conversion_rate", ObservationStatus.ANOMALOUS,
                EvidenceRole.SUPPORTING, filters={"asin": "ASIN-A"},
                dimensions={"traffic_source": "Ads"},
            ),
        )
        invalid_portfolios = (
            [self.target, global_driver, unrelated_scoped, self.control],
            [self.target, *split_driver_scope, self.control],
        )
        for portfolio in invalid_portfolios:
            with self.subTest(
                evidence_ids=tuple(item.evidence_id for item in portfolio)
            ), self.assertRaises(DiagnosisValidationError):
                build_diagnosis(
                    diagnosis_id="bad-joint-support",
                    status=DiagnosisStatus.DIAGNOSED,
                    target_metric="sales",
                    evidence=portfolio,
                    target_evidence_id=self.target.evidence_id,
                    primary_driver="conversion_rate",
                    affected_scope={
                        "marketplace": "US", "asin": "ASIN-A",
                        "traffic_source": "Ads",
                    },
                    confidence=Decimal("0.5"), limitations=["boundary"],
                    created_at=NOW,
                )

    def test_no_anomaly_rejects_anomalous_evidence(self) -> None:
        with self.assertRaises(DiagnosisValidationError):
            build_diagnosis(
                diagnosis_id="bad-normal", status=DiagnosisStatus.NO_MATERIAL_ANOMALY,
                target_metric="sales", evidence=[self.normal_target, self.target],
                target_evidence_id=self.normal_target.evidence_id, confidence=Decimal("0.5"),
                limitations=["boundary"], created_at=NOW,
            )

    def test_tool_failure_rejects_non_failed_or_non_limitation_evidence(self) -> None:
        for item in (self.limitation, self.control):
            with self.subTest(item=item.evidence_id), self.assertRaises(DiagnosisValidationError):
                build_diagnosis(
                    diagnosis_id="bad-failure", status=DiagnosisStatus.TOOL_FAILURE,
                    target_metric="sales", evidence=[item], limitations=["failed"], created_at=NOW,
                )

    def test_direct_model_state_invariants(self) -> None:
        base = dict(
            diagnosis_id="direct", target_metric="sales", change=None, primary_driver=None,
            affected_scope={}, evidence_ids=(), confidence=None, limitations=("boundary",), created_at=NOW,
        )
        invalid = [
            dict(status=DiagnosisStatus.DIAGNOSED),
            dict(status=DiagnosisStatus.NO_MATERIAL_ANOMALY),
            dict(status=DiagnosisStatus.INSUFFICIENT_EVIDENCE, primary_driver="orders"),
            dict(status=DiagnosisStatus.BUDGET_EXHAUSTED, confidence=Decimal("0.1")),
            dict(status=DiagnosisStatus.TOOL_FAILURE, change=DiagnosisChange(Decimal("1"), Decimal("2"), Decimal("-0.5"), "usd", "ev"), evidence_ids=("ev",)),
        ]
        for override in invalid:
            kwargs = {**base, **override}
            with self.subTest(override=override), self.assertRaises(DiagnosisValidationError):
                Diagnosis(**kwargs)

    def test_confidence_evidence_and_limitations_validation(self) -> None:
        diagnosis = self.diagnosed()
        change = diagnosis.change
        base = dict(
            diagnosis_id="bad", status=DiagnosisStatus.DIAGNOSED, target_metric="sales",
            change=change, primary_driver="conversion_rate", affected_scope={"marketplace": "US"},
            evidence_ids=diagnosis.evidence_ids, confidence=Decimal("0.5"),
            limitations=("boundary",), created_at=NOW,
        )
        for override in (
            {"confidence": Decimal("1.01")},
            {"confidence": Decimal("NaN")},
            {"confidence": Decimal("Infinity")},
            {"evidence_ids": (change.evidence_id, change.evidence_id)},
            {"evidence_ids": ("other",)},
            {"limitations": ()},
        ):
            with self.subTest(override=override), self.assertRaises(DiagnosisValidationError):
                Diagnosis(**{**base, **override})

    def test_deep_immutability_source_isolation_and_utc(self) -> None:
        scope = {"marketplace": "US"}
        evidence_ids = [self.target.evidence_id, self.driver.evidence_id, self.control.evidence_id]
        limitations = ["boundary"]
        diagnosis = Diagnosis(
            diagnosis_id="immutable", status=DiagnosisStatus.DIAGNOSED, target_metric="sales",
            change=DiagnosisChange(Decimal("80"), Decimal("100"), Decimal("-0.2"), "count", self.target.evidence_id),
            primary_driver="conversion_rate", affected_scope=scope, evidence_ids=evidence_ids,
            confidence=Decimal("0.9"), limitations=limitations,
            created_at=datetime.datetime(2026, 1, 31, 20, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
        )
        scope["marketplace"] = "DE"; evidence_ids.clear(); limitations.clear()
        self.assertEqual(diagnosis.affected_scope["marketplace"], "US")
        self.assertEqual(len(diagnosis.evidence_ids), 3)
        self.assertEqual(diagnosis.created_at, NOW)
        with self.assertRaises(TypeError):
            diagnosis.affected_scope["marketplace"] = "UK"

    def test_builder_rejects_duplicate_or_non_evidence(self) -> None:
        common = dict(
            diagnosis_id="bad", status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales", limitations=["budget"], created_at=NOW,
        )
        for items in ([self.target, self.target], [object()]):
            with self.subTest(items=items), self.assertRaises(DiagnosisValidationError):
                build_diagnosis(evidence=items, **common)

    def test_string_collections_are_rejected(self) -> None:
        base = dict(
            diagnosis_id="bad-collection", status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales", change=None, primary_driver=None, affected_scope={},
            evidence_ids=(), confidence=None, limitations=("budget",), created_at=NOW,
        )
        for override in ({"evidence_ids": "evidence-id"}, {"limitations": "budget"}):
            with self.subTest(override=override), self.assertRaises(DiagnosisValidationError):
                Diagnosis(**{**base, **override})

    def test_no_root_cause_field(self) -> None:
        names = {item.name for item in fields(Diagnosis)}
        self.assertNotIn("root_cause", names)
        self.assertFalse(hasattr(self.diagnosed(), "root_cause"))


if __name__ == "__main__":
    unittest.main()
