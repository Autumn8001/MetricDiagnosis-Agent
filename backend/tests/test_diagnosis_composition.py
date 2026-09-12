"""Hermetic tests for the Observation-to-Diagnosis composition boundary."""

import datetime
from dataclasses import fields
from decimal import Decimal
import unittest

from app.analytics.models import DateRange
from app.diagnosis import (
    DiagnosisComposition,
    DiagnosisDraft,
    DiagnosisStatus,
    DiagnosisValidationError,
    compose_diagnosis_from_observations,
)
from app.evidence import (
    EvidenceRole,
    EvidenceSelection,
    EvidenceSelectionDraft,
    EvidenceValidationError,
)
from app.observations.models import Observation, ObservationStatus


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
        current_value=None if failed else Decimal("80.00"),
        baseline_value=None if failed else Decimal("100.00"),
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


class TestDiagnosisComposition(unittest.TestCase):
    def setUp(self) -> None:
        self.target = make_observation(
            "target", "sales", ObservationStatus.ANOMALOUS
        )
        self.driver = make_observation(
            "driver",
            "conversion_rate",
            ObservationStatus.ANOMALOUS,
            filters={"marketplace": "US", "asin": "ASIN-A"},
            dimensions={"traffic_source": "Ads"},
        )
        self.control = make_observation(
            "control", "sessions", ObservationStatus.NORMAL
        )
        self.extra = make_observation("extra", "aov", ObservationStatus.NORMAL)
        self.catalog = [self.target, self.driver, self.control, self.extra]

    def diagnosed_inputs(self, *, include_extra: bool = False):
        selections = [
            EvidenceSelection("target", EvidenceRole.SUPPORTING),
            EvidenceSelection("driver", EvidenceRole.SUPPORTING),
            EvidenceSelection("control", EvidenceRole.NEGATIVE_CONTROL),
        ]
        if include_extra:
            selections.append(EvidenceSelection("extra", EvidenceRole.SUPPORTING))
        portfolio_ids = [
            "evidence:target:supporting",
            "evidence:driver:supporting",
            "evidence:control:negative_control",
        ]
        if include_extra:
            portfolio_ids.append("evidence:extra:supporting")
        draft = DiagnosisDraft(
            status=DiagnosisStatus.DIAGNOSED,
            target_metric="sales",
            target_evidence_id="evidence:target:supporting",
            primary_driver="conversion_rate",
            affected_scope={
                "marketplace": "US",
                "asin": "ASIN-A",
                "traffic_source": "Ads",
            },
            evidence_ids=portfolio_ids[:3],
            confidence=Decimal("0.90"),
            limitations=["Data contribution only; external cause is unproven."],
        )
        return EvidenceSelectionDraft(selections), draft

    def test_diagnosed_composes_observation_evidence_diagnosis_chain(self) -> None:
        selection_draft, diagnosis_draft = self.diagnosed_inputs()
        composition = compose_diagnosis_from_observations(
            diagnosis_id="diag:composition",
            evidence_selection_draft=selection_draft,
            diagnosis_draft=diagnosis_draft,
            observation_catalog=self.catalog,
            created_at=NOW,
        )

        self.assertIsInstance(composition, DiagnosisComposition)
        self.assertIsInstance(composition.evidence, tuple)
        self.assertEqual(
            composition.diagnosis.evidence_ids,
            (
                "evidence:target:supporting",
                "evidence:driver:supporting",
                "evidence:control:negative_control",
            ),
        )
        self.assertEqual(
            [item.observation_id for item in composition.evidence],
            ["target", "driver", "control"],
        )
        self.assertEqual(
            composition.diagnosis.change.current_value,
            self.target.current_value,
        )
        self.assertEqual(
            composition.diagnosis.change.baseline_value,
            self.target.baseline_value,
        )
        self.assertEqual(
            composition.diagnosis.change.relative_change,
            self.target.relative_change,
        )
        self.assertEqual(composition.diagnosis.change.unit, "usd")
        self.assertEqual(
            composition.diagnosis.change.evidence_id,
            composition.evidence[0].evidence_id,
        )

    def test_no_material_anomaly_composes_successfully(self) -> None:
        normal = make_observation("normal-target", "sales", ObservationStatus.NORMAL)
        composition = compose_diagnosis_from_observations(
            diagnosis_id="diag:no-anomaly",
            evidence_selection_draft=EvidenceSelectionDraft(
                [EvidenceSelection("normal-target", EvidenceRole.SUPPORTING)]
            ),
            diagnosis_draft=DiagnosisDraft(
                status=DiagnosisStatus.NO_MATERIAL_ANOMALY,
                target_metric="sales",
                target_evidence_id="evidence:normal-target:supporting",
                primary_driver=None,
                affected_scope={},
                evidence_ids=["evidence:normal-target:supporting"],
                confidence=Decimal("0.80"),
                limitations=["Synthetic benchmark only."],
            ),
            observation_catalog=[normal],
            created_at=NOW,
        )

        self.assertEqual(
            composition.diagnosis.status,
            DiagnosisStatus.NO_MATERIAL_ANOMALY,
        )
        self.assertEqual(
            composition.diagnosis.evidence_ids,
            (composition.evidence[0].evidence_id,),
        )
        self.assertEqual(
            composition.diagnosis.change.current_value,
            normal.current_value,
        )

    def test_budget_exhausted_allows_empty_portfolio(self) -> None:
        composition = compose_diagnosis_from_observations(
            diagnosis_id="diag:budget",
            evidence_selection_draft=EvidenceSelectionDraft(()),
            diagnosis_draft=DiagnosisDraft(
                status=DiagnosisStatus.BUDGET_EXHAUSTED,
                target_metric="sales",
                target_evidence_id=None,
                primary_driver=None,
                affected_scope={},
                evidence_ids=(),
                confidence=None,
                limitations=["Investigation call budget exhausted."],
            ),
            observation_catalog=self.catalog,
            created_at=NOW,
        )

        self.assertEqual(composition.evidence, ())
        self.assertEqual(composition.diagnosis.evidence_ids, ())
        self.assertIsNone(composition.diagnosis.change)

    def test_portfolio_retains_evidence_not_cited_by_diagnosis(self) -> None:
        selection_draft, diagnosis_draft = self.diagnosed_inputs(include_extra=True)
        composition = compose_diagnosis_from_observations(
            diagnosis_id="diag:subset",
            evidence_selection_draft=selection_draft,
            diagnosis_draft=diagnosis_draft,
            observation_catalog=self.catalog,
            created_at=NOW,
        )

        self.assertEqual(len(composition.evidence), 4)
        self.assertEqual(composition.evidence[-1].observation_id, "extra")
        self.assertNotIn(
            composition.evidence[-1].evidence_id,
            composition.diagnosis.evidence_ids,
        )

    def test_unknown_observation_reference_propagates(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            compose_diagnosis_from_observations(
                diagnosis_id="diag:unknown-observation",
                evidence_selection_draft=EvidenceSelectionDraft(
                    [EvidenceSelection("missing", EvidenceRole.SUPPORTING)]
                ),
                diagnosis_draft=DiagnosisDraft(
                    status=DiagnosisStatus.BUDGET_EXHAUSTED,
                    target_metric="sales",
                    target_evidence_id=None,
                    primary_driver=None,
                    affected_scope={},
                    evidence_ids=(),
                    confidence=None,
                    limitations=["No usable evidence."],
                ),
                observation_catalog=self.catalog,
                created_at=NOW,
            )

    def test_illegal_status_role_propagates(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            compose_diagnosis_from_observations(
                diagnosis_id="diag:illegal-role",
                evidence_selection_draft=EvidenceSelectionDraft(
                    [EvidenceSelection("target", EvidenceRole.NEGATIVE_CONTROL)]
                ),
                diagnosis_draft=DiagnosisDraft(
                    status=DiagnosisStatus.BUDGET_EXHAUSTED,
                    target_metric="sales",
                    target_evidence_id=None,
                    primary_driver=None,
                    affected_scope={},
                    evidence_ids=(),
                    confidence=None,
                    limitations=["No usable evidence."],
                ),
                observation_catalog=self.catalog,
                created_at=NOW,
            )

    def test_diagnosis_reference_outside_portfolio_propagates(self) -> None:
        selection_draft, diagnosis_draft = self.diagnosed_inputs()
        invalid_draft = DiagnosisDraft(
            status=diagnosis_draft.status,
            target_metric=diagnosis_draft.target_metric,
            target_evidence_id=diagnosis_draft.target_evidence_id,
            primary_driver=diagnosis_draft.primary_driver,
            affected_scope=diagnosis_draft.affected_scope,
            evidence_ids=[*diagnosis_draft.evidence_ids, "evidence:missing:supporting"],
            confidence=diagnosis_draft.confidence,
            limitations=diagnosis_draft.limitations,
        )
        with self.assertRaises(DiagnosisValidationError):
            compose_diagnosis_from_observations(
                diagnosis_id="diag:missing-evidence",
                evidence_selection_draft=selection_draft,
                diagnosis_draft=invalid_draft,
                observation_catalog=self.catalog,
                created_at=NOW,
            )

    def test_missing_negative_control_propagates(self) -> None:
        selection_draft = EvidenceSelectionDraft(
            [
                EvidenceSelection("target", EvidenceRole.SUPPORTING),
                EvidenceSelection("driver", EvidenceRole.SUPPORTING),
            ]
        )
        diagnosis_draft = DiagnosisDraft(
            status=DiagnosisStatus.DIAGNOSED,
            target_metric="sales",
            target_evidence_id="evidence:target:supporting",
            primary_driver="conversion_rate",
            affected_scope={"marketplace": "US"},
            evidence_ids=[
                "evidence:target:supporting",
                "evidence:driver:supporting",
            ],
            confidence=Decimal("0.90"),
            limitations=["Missing control is intentional for this failure test."],
        )
        with self.assertRaises(DiagnosisValidationError):
            compose_diagnosis_from_observations(
                diagnosis_id="diag:no-control",
                evidence_selection_draft=selection_draft,
                diagnosis_draft=diagnosis_draft,
                observation_catalog=self.catalog,
                created_at=NOW,
            )

    def test_composition_snapshots_source_list_and_requires_valid_types(self) -> None:
        selection_draft, diagnosis_draft = self.diagnosed_inputs()
        composed = compose_diagnosis_from_observations(
            diagnosis_id="diag:snapshot-source",
            evidence_selection_draft=selection_draft,
            diagnosis_draft=diagnosis_draft,
            observation_catalog=self.catalog,
            created_at=NOW,
        )
        source = list(composed.evidence)
        snapshot = DiagnosisComposition(evidence=source, diagnosis=composed.diagnosis)
        source.clear()

        self.assertIsInstance(snapshot.evidence, tuple)
        self.assertEqual(len(snapshot.evidence), 3)
        self.assertEqual(snapshot.evidence, composed.evidence)
        with self.assertRaises(AttributeError):
            snapshot.evidence = ()  # type: ignore[misc]

        for invalid in (
            "not-evidence",
            b"not-evidence",
            bytearray(b"not-evidence"),
            [object()],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(DiagnosisValidationError):
                DiagnosisComposition(evidence=invalid, diagnosis=composed.diagnosis)  # type: ignore[arg-type]

    def test_composition_rejects_duplicate_ids_non_diagnosis_and_missing_refs(self) -> None:
        selection_draft, diagnosis_draft = self.diagnosed_inputs()
        composed = compose_diagnosis_from_observations(
            diagnosis_id="diag:direct-validation",
            evidence_selection_draft=selection_draft,
            diagnosis_draft=diagnosis_draft,
            observation_catalog=self.catalog,
            created_at=NOW,
        )
        duplicate = [composed.evidence[0], composed.evidence[0]]
        with self.assertRaises(DiagnosisValidationError):
            DiagnosisComposition(evidence=duplicate, diagnosis=composed.diagnosis)
        with self.assertRaises(DiagnosisValidationError):
            DiagnosisComposition(evidence=composed.evidence, diagnosis=object())  # type: ignore[arg-type]

        with self.assertRaises(DiagnosisValidationError):
            DiagnosisComposition(evidence=[composed.evidence[0]], diagnosis=composed.diagnosis)

    def test_composition_has_only_portfolio_and_diagnosis_fields(self) -> None:
        names = {item.name for item in fields(DiagnosisComposition)}
        self.assertEqual(names, {"evidence", "diagnosis"})
        self.assertNotIn("root_cause", names)
        self.assertNotIn("current_value", names)
        self.assertNotIn("relative_change", names)


if __name__ == "__main__":
    unittest.main()
