"""Hermetic tests for resolving untrusted Diagnosis drafts against Evidence."""

import datetime
from dataclasses import fields
from decimal import Decimal
import unittest

from app.analytics.models import DateRange
from app.diagnosis import (
    DiagnosisDraft,
    DiagnosisStatus,
    DiagnosisValidationError,
    resolve_diagnosis_draft,
)
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.observations.models import Observation, ObservationStatus


NOW = datetime.datetime(2026, 1, 31, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 1, 31), datetime.date(2026, 1, 31))
BASELINE = DateRange(datetime.date(2026, 1, 24), datetime.date(2026, 1, 30))


def make_evidence(
    observation_id: str,
    metric: str,
    status: ObservationStatus,
    role: EvidenceRole,
    *,
    filters: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
) -> object:
    failed = status == ObservationStatus.FAILED
    observation = Observation(
        observation_id=observation_id,
        tool_name="query_metric",
        tool_call_id=f"call_{observation_id}",
        metric=metric,
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters=filters or {},
        group_by=tuple((dimensions or {}).keys()),
        dimensions=dimensions or {},
        current_value=None if failed else Decimal("80"),
        baseline_value=None if failed else Decimal("100"),
        relative_change=None if failed else (
            Decimal("-0.20")
            if status == ObservationStatus.ANOMALOUS
            else Decimal("0.01")
        ),
        unit="count",
        sample_size=None if failed else Decimal("500"),
        source_status="failed" if failed else "ok",
        status=status,
        query_or_result_reference=f"ref:{observation_id}",
        created_at=NOW,
        error_code="QUERY_FAILED" if failed else None,
        error_message="query failed" if failed else None,
    )
    return promote_observation_to_evidence(observation, role=role)


class TestDiagnosisDraft(unittest.TestCase):
    def setUp(self) -> None:
        self.target = make_evidence(
            "target", "sales", ObservationStatus.ANOMALOUS, EvidenceRole.SUPPORTING
        )
        self.driver = make_evidence(
            "driver",
            "conversion_rate",
            ObservationStatus.ANOMALOUS,
            EvidenceRole.SUPPORTING,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        self.control = make_evidence(
            "control", "sessions", ObservationStatus.NORMAL, EvidenceRole.NEGATIVE_CONTROL
        )
        self.normal_target = make_evidence(
            "normal-target", "sales", ObservationStatus.NORMAL, EvidenceRole.SUPPORTING
        )

    def diagnosed_draft(self, evidence_ids: list[str] | None = None) -> DiagnosisDraft:
        return DiagnosisDraft(
            status=DiagnosisStatus.DIAGNOSED,
            target_metric="sales",
            target_evidence_id=self.target.evidence_id,
            primary_driver="conversion_rate",
            affected_scope={
                "marketplace": "US",
                "asin": "ASIN-A",
                "traffic_source": "Ads",
            },
            evidence_ids=evidence_ids or [
                self.driver.evidence_id,
                self.target.evidence_id,
                self.control.evidence_id,
            ],
            confidence=Decimal("0.90"),
            limitations=["Data contribution only; external cause is unproven."],
        )

    def test_diagnosed_resolves_only_referenced_evidence_in_draft_order(self) -> None:
        unrelated = self.normal_target
        draft = self.diagnosed_draft()
        diagnosis = resolve_diagnosis_draft(
            diagnosis_id="diag:draft",
            draft=draft,
            evidence_catalog=[unrelated, self.control, self.target, self.driver],
            created_at=NOW,
        )

        self.assertEqual(diagnosis.evidence_ids, draft.evidence_ids)
        self.assertEqual(diagnosis.change.evidence_id, self.target.evidence_id)
        self.assertEqual(diagnosis.change.current_value, self.target.current_value)
        self.assertEqual(diagnosis.change.baseline_value, self.target.baseline_value)
        self.assertEqual(diagnosis.change.relative_change, self.target.relative_change)

    def test_no_material_anomaly_resolves_and_copies_catalog_change(self) -> None:
        draft = DiagnosisDraft(
            status=DiagnosisStatus.NO_MATERIAL_ANOMALY,
            target_metric="sales",
            target_evidence_id=self.normal_target.evidence_id,
            primary_driver=None,
            affected_scope={},
            evidence_ids=[self.normal_target.evidence_id],
            confidence=Decimal("0.80"),
            limitations=["Synthetic benchmark only."],
        )
        diagnosis = resolve_diagnosis_draft(
            diagnosis_id="diag:normal-draft",
            draft=draft,
            evidence_catalog=[self.normal_target],
            created_at=NOW,
        )

        self.assertEqual(diagnosis.status, DiagnosisStatus.NO_MATERIAL_ANOMALY)
        self.assertEqual(diagnosis.change.current_value, self.normal_target.current_value)
        self.assertEqual(diagnosis.change.relative_change, self.normal_target.relative_change)

    def test_budget_exhausted_draft_allows_empty_evidence(self) -> None:
        draft = DiagnosisDraft(
            status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales",
            target_evidence_id=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=(),
            confidence=None,
            limitations=["Investigation call budget exhausted."],
        )
        diagnosis = resolve_diagnosis_draft(
            diagnosis_id="diag:budget-draft",
            draft=draft,
            evidence_catalog=[self.target],
            created_at=NOW,
        )

        self.assertEqual(diagnosis.status, DiagnosisStatus.BUDGET_EXHAUSTED)
        self.assertEqual(diagnosis.evidence_ids, ())
        self.assertIsNone(diagnosis.change)

    def test_unknown_evidence_reference_is_rejected(self) -> None:
        draft = DiagnosisDraft(
            status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales",
            target_evidence_id=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=["evidence:does-not-exist:limitation"],
            confidence=None,
            limitations=["No usable evidence."],
        )
        with self.assertRaises(DiagnosisValidationError):
            resolve_diagnosis_draft(
                diagnosis_id="diag:unknown",
                draft=draft,
                evidence_catalog=[],
                created_at=NOW,
            )

    def test_duplicate_catalog_evidence_id_is_rejected_even_if_unreferenced(self) -> None:
        draft = DiagnosisDraft(
            status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales",
            target_evidence_id=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=(),
            confidence=None,
            limitations=["Budget exhausted."],
        )
        with self.assertRaises(DiagnosisValidationError):
            resolve_diagnosis_draft(
                diagnosis_id="diag:duplicate-catalog",
                draft=draft,
                evidence_catalog=[self.target, self.target],
                created_at=NOW,
            )

    def test_target_evidence_must_be_selected(self) -> None:
        draft = self.diagnosed_draft([self.driver.evidence_id, self.control.evidence_id])
        with self.assertRaises(DiagnosisValidationError):
            resolve_diagnosis_draft(
                diagnosis_id="diag:target-not-selected",
                draft=draft,
                evidence_catalog=[self.target, self.driver, self.control],
                created_at=NOW,
            )

    def test_non_evidence_catalog_item_is_rejected(self) -> None:
        draft = DiagnosisDraft(
            status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales",
            target_evidence_id=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=(),
            confidence=None,
            limitations=["Budget exhausted."],
        )
        with self.assertRaises(DiagnosisValidationError):
            resolve_diagnosis_draft(
                diagnosis_id="diag:bad-catalog",
                draft=draft,
                evidence_catalog=[object()],
                created_at=NOW,
            )

    def test_string_pseudo_sequences_are_rejected(self) -> None:
        common = dict(
            status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales",
            target_evidence_id=None,
            primary_driver=None,
            affected_scope={},
            confidence=None,
        )
        for override in (
            {"evidence_ids": "not-a-sequence", "limitations": ["budget"]},
            {"evidence_ids": [], "limitations": "not-a-sequence"},
        ):
            with self.subTest(override=override), self.assertRaises(DiagnosisValidationError):
                DiagnosisDraft(**{**common, **override})

        draft = DiagnosisDraft(
            evidence_ids=(),
            limitations=["budget"],
            **common,
        )
        with self.assertRaises(DiagnosisValidationError):
            resolve_diagnosis_draft(
                diagnosis_id="diag:string-catalog",
                draft=draft,
                evidence_catalog="not-a-catalog",  # type: ignore[arg-type]
                created_at=NOW,
            )

    def test_draft_rejects_duplicate_ids_and_limitations(self) -> None:
        common = dict(
            status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales",
            target_evidence_id=None,
            primary_driver=None,
            affected_scope={},
            confidence=None,
        )
        for override in (
            {"evidence_ids": ["same", "same"], "limitations": ["budget"]},
            {"evidence_ids": [], "limitations": ["budget", "budget"]},
        ):
            with self.subTest(override=override), self.assertRaises(DiagnosisValidationError):
                DiagnosisDraft(**{**common, **override})

    def test_draft_defensively_snapshots_scope_ids_and_limitations(self) -> None:
        scope = {"marketplace": "US"}
        evidence_ids = [self.target.evidence_id]
        limitations = ["boundary"]
        draft = DiagnosisDraft(
            status=DiagnosisStatus.BUDGET_EXHAUSTED,
            target_metric="sales",
            target_evidence_id=None,
            primary_driver=None,
            affected_scope=scope,
            evidence_ids=evidence_ids,
            confidence=None,
            limitations=limitations,
        )

        scope["marketplace"] = "DE"
        evidence_ids.clear()
        limitations.clear()
        self.assertEqual(dict(draft.affected_scope), {"marketplace": "US"})
        self.assertEqual(draft.evidence_ids, (self.target.evidence_id,))
        self.assertEqual(draft.limitations, ("boundary",))
        with self.assertRaises(TypeError):
            draft.affected_scope["marketplace"] = "UK"

    def test_resolver_reuses_builder_and_rejects_missing_negative_control(self) -> None:
        draft = self.diagnosed_draft([self.target.evidence_id, self.driver.evidence_id])
        with self.assertRaises(DiagnosisValidationError):
            resolve_diagnosis_draft(
                diagnosis_id="diag:missing-control",
                draft=draft,
                evidence_catalog=[self.target, self.driver],
                created_at=NOW,
            )

    def test_non_draft_input_is_rejected(self) -> None:
        with self.assertRaises(DiagnosisValidationError):
            resolve_diagnosis_draft(
                diagnosis_id="diag:not-draft",
                draft=object(),  # type: ignore[arg-type]
                evidence_catalog=[],
                created_at=NOW,
            )

    def test_draft_has_only_intent_and_reference_fields(self) -> None:
        names = {item.name for item in fields(DiagnosisDraft)}
        self.assertEqual(
            names,
            {
                "status",
                "target_metric",
                "target_evidence_id",
                "driver_evidence_id",
                "primary_driver",
                "affected_scope",
                "evidence_ids",
                "confidence",
                "limitations",
            },
        )
        forbidden = {
            "current_value",
            "baseline_value",
            "relative_change",
            "unit",
            "change",
            "root_cause",
        }
        self.assertTrue(forbidden.isdisjoint(names))

    def test_draft_validates_status_confidence_and_limitations(self) -> None:
        common = dict(
            target_metric="sales",
            target_evidence_id=None,
            driver_evidence_id=None,
            primary_driver=None,
            affected_scope={},
            evidence_ids=(),
            limitations=["boundary"],
        )
        for override in (
            {"status": "budget_exhausted", "confidence": None},
            {"status": DiagnosisStatus.BUDGET_EXHAUSTED, "confidence": 0.5},
            {"status": DiagnosisStatus.BUDGET_EXHAUSTED, "confidence": Decimal("NaN")},
            {"status": DiagnosisStatus.BUDGET_EXHAUSTED, "confidence": Decimal("1.01")},
            {"status": DiagnosisStatus.BUDGET_EXHAUSTED, "confidence": None, "limitations": []},
        ):
            with self.subTest(override=override), self.assertRaises(DiagnosisValidationError):
                DiagnosisDraft(**{**common, **override})


if __name__ == "__main__":
    unittest.main()
