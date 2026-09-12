"""Hermetic tests for Observation-backed Evidence selection resolution."""

import datetime
from dataclasses import fields
from decimal import Decimal
import unittest

from app.analytics.models import DateRange
from app.evidence import (
    EvidenceRole,
    EvidenceSelection,
    EvidenceSelectionDraft,
    EvidenceValidationError,
    resolve_evidence_selections,
)
from app.observations.models import Observation, ObservationStatus


NOW = datetime.datetime(2026, 2, 1, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 2, 1), datetime.date(2026, 2, 1))
BASELINE = DateRange(datetime.date(2026, 1, 25), datetime.date(2026, 1, 31))


def make_observation(
    observation_id: str,
    status: ObservationStatus,
    *,
    metric: str = "sales",
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
        filters={"marketplace": "US"},
        group_by=tuple((dimensions or {}).keys()),
        dimensions=dimensions or {},
        current_value=None if failed else Decimal("80.00"),
        baseline_value=None if failed else Decimal("100.00"),
        relative_change=None if failed or insufficient else Decimal("-0.20"),
        unit="usd",
        sample_size=None if failed else (Decimal("15") if insufficient else Decimal("500")),
        source_status="failed" if failed else ("insufficient_data" if insufficient else "ok"),
        status=status,
        query_or_result_reference=f"ref:{observation_id}",
        created_at=NOW,
        error_code="QUERY_FAILED" if failed else None,
        error_message="query failed" if failed else None,
    )


class TestEvidenceSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.anomalous = make_observation(
            "obs-anomalous", ObservationStatus.ANOMALOUS, metric="conversion_rate"
        )
        self.normal = make_observation("obs-normal", ObservationStatus.NORMAL)
        self.inconclusive = make_observation(
            "obs-inconclusive", ObservationStatus.INCONCLUSIVE
        )
        self.insufficient = make_observation(
            "obs-insufficient", ObservationStatus.INSUFFICIENT_EVIDENCE
        )
        self.failed = make_observation("obs-failed", ObservationStatus.FAILED)
        self.catalog = [
            self.anomalous,
            self.normal,
            self.inconclusive,
            self.insufficient,
            self.failed,
        ]

    def test_selection_has_only_reference_and_role_fields(self) -> None:
        self.assertEqual(
            {item.name for item in fields(EvidenceSelection)},
            {"observation_id", "role"},
        )
        forbidden = {
            "metric",
            "current_value",
            "baseline_value",
            "relative_change",
            "unit",
            "current_period",
            "baseline_period",
            "filters",
            "dimensions",
            "error",
            "confidence",
            "root_cause",
        }
        self.assertTrue(forbidden.isdisjoint({item.name for item in fields(EvidenceSelection)}))

    def test_selection_normalizes_id_and_validates_role(self) -> None:
        selection = EvidenceSelection("  obs-normal  ", EvidenceRole.SUPPORTING)
        self.assertEqual(selection.observation_id, "obs-normal")
        self.assertEqual(selection.role, EvidenceRole.SUPPORTING)
        with self.assertRaises(EvidenceValidationError):
            EvidenceSelection("obs-normal", "supporting")  # type: ignore[arg-type]
        for bad_id in ("", "   ", None):
            with self.subTest(bad_id=bad_id), self.assertRaises(EvidenceValidationError):
                EvidenceSelection(bad_id, EvidenceRole.SUPPORTING)  # type: ignore[arg-type]

    def test_draft_snapshots_source_list_and_preserves_order(self) -> None:
        source = [
            EvidenceSelection("obs-normal", EvidenceRole.NEGATIVE_CONTROL),
            EvidenceSelection("obs-anomalous", EvidenceRole.SUPPORTING),
        ]
        draft = EvidenceSelectionDraft(source)
        source.clear()
        self.assertEqual(draft.selections, tuple(draft.selections))
        self.assertEqual(draft.selections[0].observation_id, "obs-normal")
        resolved = resolve_evidence_selections(
            draft=draft,
            observation_catalog=self.catalog,
        )
        self.assertEqual(
            [item.observation_id for item in resolved],
            ["obs-normal", "obs-anomalous"],
        )

    def test_draft_allows_empty_selections(self) -> None:
        draft = EvidenceSelectionDraft(())
        resolved = resolve_evidence_selections(
            draft=draft,
            observation_catalog=self.catalog,
        )
        self.assertEqual(resolved, ())
        self.assertIsInstance(resolved, tuple)

    def test_draft_rejects_string_pseudo_sequence_and_non_selection_items(self) -> None:
        for value in ("obs-normal", b"obs-normal", bytearray(b"obs-normal"), [object()]):
            with self.subTest(value=value), self.assertRaises(EvidenceValidationError):
                EvidenceSelectionDraft(value)  # type: ignore[arg-type]

    def test_draft_rejects_duplicate_observation_role_pair(self) -> None:
        selection = EvidenceSelection("obs-normal", EvidenceRole.SUPPORTING)
        with self.assertRaises(EvidenceValidationError):
            EvidenceSelectionDraft([selection, selection])

    def test_status_role_promotions_copy_real_observation_data(self) -> None:
        cases = [
            (self.anomalous, EvidenceRole.SUPPORTING),
            (self.normal, EvidenceRole.NEGATIVE_CONTROL),
            (self.inconclusive, EvidenceRole.LIMITATION),
            (self.insufficient, EvidenceRole.LIMITATION),
            (self.failed, EvidenceRole.LIMITATION),
        ]
        for observation, role in cases:
            with self.subTest(status=observation.status, role=role):
                resolved = resolve_evidence_selections(
                    draft=EvidenceSelectionDraft(
                        [EvidenceSelection(observation.observation_id, role)]
                    ),
                    observation_catalog=self.catalog,
                )
                evidence = resolved[0]
                self.assertEqual(evidence.observation_id, observation.observation_id)
                self.assertEqual(evidence.role, role)
                self.assertEqual(evidence.metric, observation.metric)
                self.assertEqual(evidence.current_period, observation.current_period)
                self.assertEqual(evidence.baseline_period, observation.baseline_period)
                self.assertEqual(evidence.filters, observation.filters)
                self.assertEqual(evidence.group_by, observation.group_by)
                self.assertEqual(evidence.dimensions, observation.dimensions)
                self.assertEqual(evidence.current_value, observation.current_value)
                self.assertEqual(evidence.baseline_value, observation.baseline_value)
                self.assertEqual(evidence.relative_change, observation.relative_change)
                self.assertEqual(evidence.unit, observation.unit)
                self.assertEqual(evidence.sample_size, observation.sample_size)
                self.assertEqual(evidence.observation_status, observation.status)
                self.assertEqual(evidence.source_status, observation.source_status)
                self.assertEqual(
                    evidence.query_or_result_reference,
                    observation.query_or_result_reference,
                )
                self.assertEqual(evidence.created_at, observation.created_at)
                self.assertEqual(evidence.error_code, observation.error_code)
                self.assertEqual(evidence.error_message, observation.error_message)

    def test_same_normal_observation_can_use_two_roles_deterministically(self) -> None:
        draft = EvidenceSelectionDraft(
            [
                EvidenceSelection("obs-normal", EvidenceRole.SUPPORTING),
                EvidenceSelection("obs-normal", EvidenceRole.NEGATIVE_CONTROL),
            ]
        )
        first = resolve_evidence_selections(draft=draft, observation_catalog=self.catalog)
        second = resolve_evidence_selections(draft=draft, observation_catalog=self.catalog)
        self.assertEqual(
            [item.evidence_id for item in first],
            [
                "evidence:obs-normal:supporting",
                "evidence:obs-normal:negative_control",
            ],
        )
        self.assertEqual(first, second)

    def test_unselected_observations_do_not_enter_output(self) -> None:
        draft = EvidenceSelectionDraft(
            [EvidenceSelection("obs-anomalous", EvidenceRole.SUPPORTING)]
        )
        resolved = resolve_evidence_selections(draft=draft, observation_catalog=self.catalog)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].observation_id, "obs-anomalous")

    def test_unknown_observation_id_is_rejected(self) -> None:
        draft = EvidenceSelectionDraft(
            [EvidenceSelection("does-not-exist", EvidenceRole.SUPPORTING)]
        )
        with self.assertRaises(EvidenceValidationError):
            resolve_evidence_selections(draft=draft, observation_catalog=self.catalog)

    def test_duplicate_catalog_ids_are_rejected_even_if_unreferenced(self) -> None:
        draft = EvidenceSelectionDraft(())
        with self.assertRaises(EvidenceValidationError):
            resolve_evidence_selections(
                draft=draft,
                observation_catalog=[self.anomalous, self.anomalous],
            )

    def test_non_observation_catalog_item_is_rejected(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            resolve_evidence_selections(
                draft=EvidenceSelectionDraft(()),
                observation_catalog=[object()],  # type: ignore[list-item]
            )

    def test_string_pseudo_catalog_and_non_draft_inputs_are_rejected(self) -> None:
        draft = EvidenceSelectionDraft(())
        for catalog in ("not-a-catalog", b"not-a-catalog", bytearray(b"not-a-catalog"), None):
            with self.subTest(catalog=catalog), self.assertRaises(EvidenceValidationError):
                resolve_evidence_selections(
                    draft=draft,
                    observation_catalog=catalog,  # type: ignore[arg-type]
                )
        with self.assertRaises(EvidenceValidationError):
            resolve_evidence_selections(
                draft=object(),  # type: ignore[arg-type]
                observation_catalog=[],
            )

    def test_incompatible_status_role_is_rejected_by_promoter(self) -> None:
        draft = EvidenceSelectionDraft(
            [EvidenceSelection("obs-anomalous", EvidenceRole.NEGATIVE_CONTROL)]
        )
        with self.assertRaises(EvidenceValidationError):
            resolve_evidence_selections(draft=draft, observation_catalog=self.catalog)


if __name__ == "__main__":
    unittest.main()
