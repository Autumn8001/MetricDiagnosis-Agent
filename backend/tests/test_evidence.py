"""Hermetic unit tests for Evidence domain models and promotion functions."""

import datetime
from decimal import Decimal
import unittest

from app.analytics.models import DateRange
from app.evidence.models import (
    Evidence,
    EvidenceError,
    EvidenceRole,
    EvidenceValidationError,
)
from app.evidence.promoter import promote_observation_to_evidence
from app.observations.models import Observation, ObservationStatus


class TestEvidence(unittest.TestCase):
    """Test suite for Evidence models and explicit promotion logic."""

    def setUp(self) -> None:
        self.utc_now = datetime.datetime(2026, 1, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.current_period = DateRange(datetime.date(2026, 1, 15), datetime.date(2026, 1, 15))
        self.baseline_period = DateRange(datetime.date(2026, 1, 8), datetime.date(2026, 1, 14))

        self.anomalous_obs = Observation(
            observation_id="obs_sales_cr_0",
            tool_name="query_metric",
            tool_call_id="call_001",
            metric="conversion_rate",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={"marketplace": "US"},
            group_by=("asin",),
            dimensions={"asin": "ASIN-A"},
            current_value=Decimal("0.1000"),
            baseline_value=Decimal("0.2000"),
            relative_change=Decimal("-0.5000"),
            unit="ratio",
            sample_size=Decimal("500"),
            source_status="ok",
            status=ObservationStatus.ANOMALOUS,
            query_or_result_reference="ref_cr_us_asin_a",
            created_at=self.utc_now,
        )

        self.normal_obs = Observation(
            observation_id="obs_sessions_0",
            tool_name="query_metric",
            tool_call_id="call_002",
            metric="sessions",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={"marketplace": "US"},
            group_by=(),
            dimensions={},
            current_value=Decimal("500"),
            baseline_value=Decimal("505"),
            relative_change=Decimal("-0.0099"),
            unit="count",
            sample_size=Decimal("500"),
            source_status="ok",
            status=ObservationStatus.NORMAL,
            query_or_result_reference="ref_sessions_us",
            created_at=self.utc_now,
        )

        self.inconclusive_obs = Observation(
            observation_id="obs_borderline_0",
            tool_name="query_metric",
            tool_call_id="call_003",
            metric="aov",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={},
            group_by=(),
            dimensions={},
            current_value=Decimal("46.00"),
            baseline_value=Decimal("50.00"),
            relative_change=Decimal("-0.0800"),
            unit="usd",
            sample_size=Decimal("500"),
            source_status="ok",
            status=ObservationStatus.INCONCLUSIVE,
            query_or_result_reference="ref_aov_borderline",
            created_at=self.utc_now,
        )

        self.insufficient_obs = Observation(
            observation_id="obs_insuff_0",
            tool_name="query_metric",
            tool_call_id="call_004",
            metric="conversion_rate",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={"marketplace": "DE"},
            group_by=(),
            dimensions={},
            current_value=Decimal("0.10"),
            baseline_value=Decimal("0.15"),
            relative_change=None,
            unit="ratio",
            sample_size=Decimal("15"),
            source_status="insufficient_data",
            status=ObservationStatus.INSUFFICIENT_EVIDENCE,
            query_or_result_reference="ref_cr_de_small",
            created_at=self.utc_now,
        )

        self.failed_obs = Observation(
            observation_id="obs_failed_0",
            tool_name="query_metric",
            tool_call_id="call_005",
            metric="sales",
            current_period=self.current_period,
            baseline_period=self.baseline_period,
            filters={},
            group_by=(),
            dimensions={},
            current_value=None,
            baseline_value=None,
            relative_change=None,
            unit="usd",
            sample_size=None,
            source_status="failed",
            status=ObservationStatus.FAILED,
            query_or_result_reference="ref_failed_query",
            created_at=self.utc_now,
            error_code="TIMEOUT",
            error_message="Query timed out",
        )

    def test_anomalous_to_supporting(self) -> None:
        """Verify anomalous observation can be promoted to supporting evidence."""
        ev = promote_observation_to_evidence(self.anomalous_obs, role=EvidenceRole.SUPPORTING)
        self.assertEqual(ev.evidence_id, "evidence:obs_sales_cr_0:supporting")
        self.assertEqual(ev.observation_id, "obs_sales_cr_0")
        self.assertEqual(ev.role, EvidenceRole.SUPPORTING)
        self.assertEqual(ev.observation_status, ObservationStatus.ANOMALOUS)
        self.assertEqual(ev.metric, "conversion_rate")
        self.assertEqual(ev.current_value, Decimal("0.1000"))
        self.assertEqual(ev.relative_change, Decimal("-0.5000"))
        self.assertIsNone(ev.error_code)
        self.assertIsNone(ev.error_message)

    def test_normal_to_negative_control(self) -> None:
        """Verify normal observation can be promoted to negative_control evidence (e.g. ruling out Traffic driver)."""
        ev = promote_observation_to_evidence(self.normal_obs, role=EvidenceRole.NEGATIVE_CONTROL)
        self.assertEqual(ev.evidence_id, "evidence:obs_sessions_0:negative_control")
        self.assertEqual(ev.role, EvidenceRole.NEGATIVE_CONTROL)
        self.assertEqual(ev.observation_status, ObservationStatus.NORMAL)
        self.assertEqual(ev.metric, "sessions")
        self.assertEqual(ev.relative_change, Decimal("-0.0099"))

    def test_normal_to_supporting(self) -> None:
        """Verify normal observation can be promoted to supporting evidence (e.g. supporting no_material_anomaly)."""
        ev = promote_observation_to_evidence(self.normal_obs, role=EvidenceRole.SUPPORTING)
        self.assertEqual(ev.evidence_id, "evidence:obs_sessions_0:supporting")
        self.assertEqual(ev.role, EvidenceRole.SUPPORTING)
        self.assertEqual(ev.observation_status, ObservationStatus.NORMAL)

    def test_failed_to_limitation_preserves_error_and_none_values(self) -> None:
        """Verify failed observation promoted to limitation evidence keeps None values and error fields."""
        ev = promote_observation_to_evidence(self.failed_obs, role=EvidenceRole.LIMITATION)
        self.assertEqual(ev.evidence_id, "evidence:obs_failed_0:limitation")
        self.assertEqual(ev.role, EvidenceRole.LIMITATION)
        self.assertEqual(ev.observation_status, ObservationStatus.FAILED)
        self.assertEqual(ev.source_status, "failed")
        self.assertIsNone(ev.current_value)
        self.assertIsNone(ev.baseline_value)
        self.assertIsNone(ev.relative_change)
        self.assertIsNone(ev.sample_size)
        self.assertEqual(ev.error_code, "TIMEOUT")
        self.assertEqual(ev.error_message, "Query timed out")

    def test_insufficient_evidence_to_limitation(self) -> None:
        """Verify insufficient_evidence observation can be promoted to limitation evidence."""
        ev = promote_observation_to_evidence(self.insufficient_obs, role=EvidenceRole.LIMITATION)
        self.assertEqual(ev.evidence_id, "evidence:obs_insuff_0:limitation")
        self.assertEqual(ev.role, EvidenceRole.LIMITATION)
        self.assertEqual(ev.observation_status, ObservationStatus.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(ev.relative_change)

    def test_inconclusive_to_limitation(self) -> None:
        """Verify inconclusive observation can be promoted to limitation evidence."""
        ev = promote_observation_to_evidence(self.inconclusive_obs, role=EvidenceRole.LIMITATION)
        self.assertEqual(ev.evidence_id, "evidence:obs_borderline_0:limitation")
        self.assertEqual(ev.role, EvidenceRole.LIMITATION)
        self.assertEqual(ev.observation_status, ObservationStatus.INCONCLUSIVE)

    def test_incompatible_roles_rejected(self) -> None:
        """Verify incompatible combinations of ObservationStatus and EvidenceRole raise EvidenceValidationError."""
        incompatible_cases = [
            (self.anomalous_obs, EvidenceRole.NEGATIVE_CONTROL),
            (self.anomalous_obs, EvidenceRole.LIMITATION),
            (self.normal_obs, EvidenceRole.LIMITATION),
            (self.inconclusive_obs, EvidenceRole.SUPPORTING),
            (self.inconclusive_obs, EvidenceRole.NEGATIVE_CONTROL),
            (self.insufficient_obs, EvidenceRole.SUPPORTING),
            (self.insufficient_obs, EvidenceRole.NEGATIVE_CONTROL),
            (self.failed_obs, EvidenceRole.SUPPORTING),
            (self.failed_obs, EvidenceRole.NEGATIVE_CONTROL),
        ]

        for obs, bad_role in incompatible_cases:
            with self.subTest(status=obs.status, bad_role=bad_role):
                with self.assertRaises(EvidenceValidationError):
                    promote_observation_to_evidence(obs, role=bad_role)

    def test_deterministic_evidence_id_and_repromotion(self) -> None:
        """Verify evidence_id is deterministic and repromotion produces identical Evidence instances."""
        ev1 = promote_observation_to_evidence(self.anomalous_obs, role=EvidenceRole.SUPPORTING)
        ev2 = promote_observation_to_evidence(self.anomalous_obs, role=EvidenceRole.SUPPORTING)

        self.assertEqual(ev1.evidence_id, "evidence:obs_sales_cr_0:supporting")
        self.assertEqual(ev1.evidence_id, ev2.evidence_id)
        self.assertEqual(ev1, ev2)

    def test_normal_roles_produce_distinct_deterministic_ids(self) -> None:
        """Verify same Normal Observation promoted to supporting vs negative_control yields distinct IDs."""
        ev_sup = promote_observation_to_evidence(self.normal_obs, role=EvidenceRole.SUPPORTING)
        ev_neg = promote_observation_to_evidence(self.normal_obs, role=EvidenceRole.NEGATIVE_CONTROL)

        self.assertEqual(ev_sup.evidence_id, "evidence:obs_sessions_0:supporting")
        self.assertEqual(ev_neg.evidence_id, "evidence:obs_sessions_0:negative_control")
        self.assertNotEqual(ev_sup.evidence_id, ev_neg.evidence_id)

    def test_mismatched_evidence_id_rejected(self) -> None:
        """Verify directly constructing Evidence with mismatched or fabricated evidence_id is rejected."""
        base_kwargs = {
            "evidence_id": "unrelated_id",
            "observation_id": "obs_sessions_0",
            "role": EvidenceRole.NEGATIVE_CONTROL,
            "tool_name": "query_metric",
            "tool_call_id": "call_002",
            "metric": "sessions",
            "current_period": self.current_period,
            "baseline_period": self.baseline_period,
            "filters": {"marketplace": "US"},
            "group_by": (),
            "dimensions": {},
            "current_value": Decimal("500"),
            "baseline_value": Decimal("505"),
            "relative_change": Decimal("-0.0099"),
            "unit": "count",
            "sample_size": Decimal("500"),
            "observation_status": ObservationStatus.NORMAL,
            "source_status": "ok",
            "query_or_result_reference": "ref_sessions_us",
            "created_at": self.utc_now,
        }

        # 1. Completely unrelated ID
        with self.assertRaises(EvidenceValidationError):
            Evidence(**base_kwargs)

        # 2. ID with wrong role suffix
        kwargs_wrong_role = dict(base_kwargs)
        kwargs_wrong_role["evidence_id"] = "evidence:obs_sessions_0:supporting"  # role is NEGATIVE_CONTROL
        with self.assertRaises(EvidenceValidationError):
            Evidence(**kwargs_wrong_role)

    def test_role_compatibility_policy_is_immutable(self) -> None:
        """Verify _ALLOWED_ROLE_MAP cannot be mutated at runtime."""
        from app.evidence.models import _ALLOWED_ROLE_MAP

        with self.assertRaises(TypeError):
            _ALLOWED_ROLE_MAP[ObservationStatus.ANOMALOUS] = frozenset({EvidenceRole.NEGATIVE_CONTROL})  # type: ignore

    def test_field_fidelity_from_observation(self) -> None:
        """Verify all fields from source Observation are faithfully copied without mutation."""
        obs = self.anomalous_obs
        ev = promote_observation_to_evidence(obs, role=EvidenceRole.SUPPORTING)

        self.assertEqual(ev.observation_id, obs.observation_id)
        self.assertEqual(ev.tool_name, obs.tool_name)
        self.assertEqual(ev.tool_call_id, obs.tool_call_id)
        self.assertEqual(ev.metric, obs.metric)
        self.assertEqual(ev.current_period, obs.current_period)
        self.assertEqual(ev.baseline_period, obs.baseline_period)
        self.assertEqual(ev.filters, obs.filters)
        self.assertEqual(ev.group_by, obs.group_by)
        self.assertEqual(ev.dimensions, obs.dimensions)
        self.assertEqual(ev.current_value, obs.current_value)
        self.assertEqual(ev.baseline_value, obs.baseline_value)
        self.assertEqual(ev.relative_change, obs.relative_change)
        self.assertEqual(ev.unit, obs.unit)
        self.assertEqual(ev.sample_size, obs.sample_size)
        self.assertEqual(ev.observation_status, obs.status)
        self.assertEqual(ev.source_status, obs.source_status)
        self.assertEqual(ev.query_or_result_reference, obs.query_or_result_reference)
        self.assertEqual(ev.created_at, obs.created_at)

    def test_filters_dimensions_group_by_independent_immutability(self) -> None:
        """Verify Evidence mappings and tuples are immutable and isolated from external modifications."""
        ev = promote_observation_to_evidence(self.anomalous_obs, role=EvidenceRole.SUPPORTING)

        with self.assertRaises(TypeError):
            ev.filters["marketplace"] = "DE"  # type: ignore

        with self.assertRaises(TypeError):
            ev.dimensions["asin"] = "ASIN-B"  # type: ignore

        self.assertIsInstance(ev.group_by, tuple)

    def test_naive_datetime_and_empty_identifiers_rejected(self) -> None:
        """Verify direct construction of Evidence validates timezone-aware created_at and non-empty strings."""
        naive_dt = datetime.datetime(2026, 1, 15, 12, 0, 0)
        base_kwargs = {
            "evidence_id": "evidence:obs_1:supporting",
            "observation_id": "obs_1",
            "role": EvidenceRole.SUPPORTING,
            "tool_name": "query_metric",
            "tool_call_id": "call_1",
            "metric": "sales",
            "current_period": self.current_period,
            "baseline_period": self.baseline_period,
            "filters": {},
            "group_by": (),
            "dimensions": {},
            "current_value": Decimal("100"),
            "baseline_value": Decimal("100"),
            "relative_change": Decimal("0"),
            "unit": "usd",
            "sample_size": Decimal("50"),
            "observation_status": ObservationStatus.NORMAL,
            "source_status": "ok",
            "query_or_result_reference": "ref_1",
            "created_at": self.utc_now,
        }

        # Test naive datetime
        kwargs_naive = dict(base_kwargs)
        kwargs_naive["created_at"] = naive_dt
        with self.assertRaises(EvidenceValidationError):
            Evidence(**kwargs_naive)

        # Test empty identifiers
        for bad_id in ["", "   "]:
            kwargs_bad_id = dict(base_kwargs)
            kwargs_bad_id["observation_id"] = bad_id
            with self.assertRaises(EvidenceValidationError):
                Evidence(**kwargs_bad_id)

    def test_non_observation_and_non_evidence_role_input_rejected(self) -> None:
        """Verify promote_observation_to_evidence validates input types."""
        with self.assertRaises(EvidenceValidationError):
            promote_observation_to_evidence("not_an_observation", role=EvidenceRole.SUPPORTING)  # type: ignore

        with self.assertRaises(EvidenceValidationError):
            promote_observation_to_evidence(self.anomalous_obs, role="supporting")  # type: ignore

    def test_failed_evidence_numerical_values_rejected(self) -> None:
        """Verify direct construction of failed Evidence with numerical values is rejected."""
        base_kwargs = {
            "evidence_id": "evidence:obs_fail:limitation",
            "observation_id": "obs_fail",
            "role": EvidenceRole.LIMITATION,
            "tool_name": "query_metric",
            "tool_call_id": "call_fail",
            "metric": "sales",
            "current_period": self.current_period,
            "baseline_period": self.baseline_period,
            "filters": {},
            "group_by": (),
            "dimensions": {},
            "current_value": None,
            "baseline_value": None,
            "relative_change": None,
            "unit": "usd",
            "sample_size": None,
            "observation_status": ObservationStatus.FAILED,
            "source_status": "failed",
            "query_or_result_reference": "ref_fail",
            "created_at": self.utc_now,
            "error_code": "ERR",
            "error_message": "Some error",
        }

        for field_name, bad_val in [
            ("current_value", Decimal("100")),
            ("baseline_value", Decimal("100")),
            ("relative_change", Decimal("-0.10")),
            ("sample_size", Decimal("50")),
        ]:
            with self.subTest(field=field_name):
                kwargs = dict(base_kwargs)
                kwargs[field_name] = bad_val
                with self.assertRaises(EvidenceValidationError):
                    Evidence(**kwargs)

    def test_non_failed_evidence_with_errors_rejected(self) -> None:
        """Verify non-failed Evidence cannot carry error_code or error_message."""
        base_kwargs = {
            "evidence_id": "evidence:obs_norm:supporting",
            "observation_id": "obs_norm",
            "role": EvidenceRole.SUPPORTING,
            "tool_name": "query_metric",
            "tool_call_id": "call_norm",
            "metric": "sales",
            "current_period": self.current_period,
            "baseline_period": self.baseline_period,
            "filters": {},
            "group_by": (),
            "dimensions": {},
            "current_value": Decimal("100"),
            "baseline_value": Decimal("100"),
            "relative_change": Decimal("0"),
            "unit": "usd",
            "sample_size": Decimal("50"),
            "observation_status": ObservationStatus.NORMAL,
            "source_status": "ok",
            "query_or_result_reference": "ref_norm",
            "created_at": self.utc_now,
            "error_code": "SHOULD_BE_NONE",
        }
        with self.assertRaises(EvidenceValidationError):
            Evidence(**base_kwargs)

    def test_evidence_no_root_cause_attribute(self) -> None:
        """Verify Evidence model contains no root_cause attribute."""
        ev = promote_observation_to_evidence(self.anomalous_obs, role=EvidenceRole.SUPPORTING)
        self.assertFalse(hasattr(ev, "root_cause"))


if __name__ == "__main__":
    unittest.main()
