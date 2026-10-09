from __future__ import annotations

import datetime
from decimal import Decimal
import unittest

from app.agent_runtime import (
    EvidenceDrivenRunSummary,
    InvestigationRunSummary,
    InvestigationToolTraceEntry,
    RuntimeTraceError,
)
from app.analytics.models import DateRange
from app.data_sources.capabilities import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.diagnosis import Diagnosis, DiagnosisChange, DiagnosisComposition, DiagnosisStatus
from app.evidence import EvidenceRole, promote_observation_to_evidence
from app.observations import Observation, ObservationStatus
from app.persistence import (
    EvidenceDrivenRunPersistenceWriter,
    InvestigationPersistenceValidationError,
)
from app.persistence.models import RunStatus


NOW = datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.timezone.utc)
CURRENT = DateRange(datetime.date(2026, 8, 28), datetime.date(2026, 8, 28))
BASELINE = DateRange(datetime.date(2026, 8, 21), datetime.date(2026, 8, 27))
DESCRIPTOR = DataSourceDescriptor(
    source_id="synthetic-main",
    display_name="Synthetic benchmark",
    provider=SourceProvider.SYNTHETIC,
    environment=SourceEnvironment.BENCHMARK,
)


def make_observation(
    observation_id: str,
    tool_call_id: str,
    tool_name: str,
    *,
    status: ObservationStatus,
    metric: str,
    dimensions: dict[str, str],
) -> Observation:
    is_failed = status is ObservationStatus.FAILED
    return Observation(
        observation_id=observation_id,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        metric=metric,
        current_period=CURRENT,
        baseline_period=BASELINE,
        filters={},
        group_by=("marketplace",),
        dimensions=dimensions,
        current_value=None if is_failed else Decimal("80"),
        baseline_value=None if is_failed else Decimal("100"),
        relative_change=None if is_failed else Decimal("-0.20"),
        unit="usd",
        sample_size=None if is_failed else Decimal("500"),
        source_status="failed" if is_failed else "ok",
        status=status,
        query_or_result_reference=f"ref:{observation_id}",
        created_at=NOW,
        error_code="tool_error" if is_failed else None,
        error_message="tool failed" if is_failed else None,
    )


def make_summary() -> EvidenceDrivenRunSummary:
    first = make_observation(
        "obs-target",
        "call-target",
        "query_metric",
        status=ObservationStatus.ANOMALOUS,
        metric="sales",
        dimensions={"marketplace": "US"},
    )
    second = make_observation(
        "obs-driver",
        "call-driver",
        "query_metric",
        status=ObservationStatus.ANOMALOUS,
        metric="conversion_rate",
        dimensions={"marketplace": "US"},
    )
    target_evidence = promote_observation_to_evidence(
        first,
        role=EvidenceRole.SUPPORTING,
    )
    driver_evidence = promote_observation_to_evidence(
        second,
        role=EvidenceRole.SUPPORTING,
    )
    diagnosis = Diagnosis(
        diagnosis_id="diag:writer",
        status=DiagnosisStatus.DIAGNOSED,
        target_metric="sales",
        change=DiagnosisChange(
            current_value=first.current_value,
            baseline_value=first.baseline_value,
            relative_change=first.relative_change,
            unit=first.unit,
            evidence_id=target_evidence.evidence_id,
        ),
        primary_driver="conversion_rate",
        affected_scope={"marketplace": "US"},
        evidence_ids=(target_evidence.evidence_id, driver_evidence.evidence_id),
        confidence=Decimal("0.9"),
        limitations=("Data-level contribution only.",),
        created_at=NOW,
    )
    investigation = InvestigationRunSummary(
        final_output="audited structured run",
        tool_calls_count=2,
        max_tool_calls=8,
        tools_used=("query_metric", "query_metric"),
        tool_call_ids=("call-target", "call-driver"),
        observation_ids=("obs-target", "obs-driver"),
        observation_count=2,
        tool_trace=(
            InvestigationToolTraceEntry(
                tool_call_id="call-target",
                tool_name="query_metric",
                arguments={"metric": "sales"},
                observation_ids=("obs-target",),
            ),
            InvestigationToolTraceEntry(
                tool_call_id="call-driver",
                tool_name="query_metric",
                arguments={"metric": "conversion_rate"},
                observation_ids=("obs-driver",),
            ),
        ),
        trace_sequence=(),
        turns_count=2,
        max_turns=10,
    )
    return EvidenceDrivenRunSummary(
        investigation=investigation,
        composition=DiagnosisComposition(
            evidence=(target_evidence, driver_evidence),
            diagnosis=diagnosis,
        ),
        observation_catalog=(first, second),
    )


class SpyRepository:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.fail_at = fail_at

    def _record(self, name: str, **payload: object) -> None:
        self.events.append((name, payload))
        if name == self.fail_at:
            raise RuntimeError(f"repository failure at {name}")

    def upsert_data_source(self, source, *, data_version=None):
        self._record(
            "upsert_data_source",
            source=source,
            source_id=source.source_id,
            environment=source.environment,
            data_version=data_version,
        )

    def create_investigation_run(self, **kwargs):
        self._record("create_investigation_run", **kwargs)

    def transition_investigation_run(self, **kwargs):
        self._record("transition_investigation_run", **kwargs)

    def record_tool_call(self, tool_call_id, investigation_run_id, source_id, environment, tool_name, **kwargs):
        self._record(
            "record_tool_call",
            tool_call_id=tool_call_id,
            investigation_run_id=investigation_run_id,
            source_id=source_id,
            environment=environment,
            tool_name=tool_name,
            **kwargs,
        )

    def record_observation(self, observation, investigation_run_id, source_id, environment, **kwargs):
        self._record(
            "record_observation",
            observation=observation,
            investigation_run_id=investigation_run_id,
            source_id=source_id,
            environment=environment,
            **kwargs,
        )

    def record_evidence(self, evidence, investigation_run_id, source_id, environment, **kwargs):
        self._record(
            "record_evidence",
            evidence=evidence,
            investigation_run_id=investigation_run_id,
            source_id=source_id,
            environment=environment,
            **kwargs,
        )

    def record_diagnosis(self, diagnosis, investigation_run_id, source_id, environment, **kwargs):
        self._record(
            "record_diagnosis",
            diagnosis=diagnosis,
            investigation_run_id=investigation_run_id,
            source_id=source_id,
            environment=environment,
            **kwargs,
        )


class TestEvidenceDrivenRunPersistenceWriter(unittest.TestCase):
    def test_success_writes_in_dependency_order_and_binds_one_descriptor(self) -> None:
        repository = SpyRepository()
        summary = make_summary()

        returned_run_id = EvidenceDrivenRunPersistenceWriter(
            repository,
            DESCRIPTOR,
            data_version="benchmark-v1",
        ).write(
            summary,
            run_id="run:writer",
            requested_metric="sales",
            parameters={"target_date": "2026-08-28"},
            query_reference="query:writer",
        )

        self.assertEqual(returned_run_id, "run:writer")
        self.assertEqual(
            [name for name, _ in repository.events],
            [
                "upsert_data_source",
                "create_investigation_run",
                "transition_investigation_run",
                "record_tool_call",
                "record_observation",
                "record_tool_call",
                "record_observation",
                "record_evidence",
                "record_evidence",
                "record_diagnosis",
                "transition_investigation_run",
            ],
        )
        for name, payload in repository.events:
            if name == "upsert_data_source":
                self.assertEqual(payload["source_id"], DESCRIPTOR.source_id)
                self.assertEqual(payload["environment"], DESCRIPTOR.environment)
            elif name in {
                "record_tool_call",
                "record_observation",
                "record_evidence",
                "record_diagnosis",
            }:
                self.assertEqual(payload["source_id"], DESCRIPTOR.source_id)
                self.assertEqual(payload["environment"], DESCRIPTOR.environment)
        self.assertEqual(repository.events[1][1]["source_id"], DESCRIPTOR.source_id)
        self.assertEqual(repository.events[1][1]["environment"], DESCRIPTOR.environment)
        self.assertEqual(repository.events[2][1]["target_status"], RunStatus.RUNNING)
        self.assertEqual(repository.events[-1][1]["target_status"], RunStatus.SUCCEEDED)

    def test_invalid_summary_fails_before_any_repository_write(self) -> None:
        repository = SpyRepository()
        summary = make_summary()
        object.__setattr__(summary, "observation_catalog", (summary.observation_catalog[0],))

        with self.assertRaises(InvestigationPersistenceValidationError):
            EvidenceDrivenRunPersistenceWriter(repository, DESCRIPTOR).write(
                summary,
                run_id="run:invalid",
                requested_metric="sales",
            )

        self.assertEqual(repository.events, [])

    def test_repository_error_propagates_without_success_transition(self) -> None:
        repository = SpyRepository(fail_at="record_evidence")

        with self.assertRaisesRegex(RuntimeError, "record_evidence"):
            EvidenceDrivenRunPersistenceWriter(repository, DESCRIPTOR).write(
                make_summary(),
                run_id="run:failing",
                requested_metric="sales",
            )

        self.assertNotIn(
            ("transition_investigation_run", {"run_id": "run:failing", "target_status": RunStatus.SUCCEEDED}),
            repository.events,
        )


class TestEvidenceDrivenRunSummaryCatalog(unittest.TestCase):
    def test_catalog_is_immutable_and_matches_verified_trace(self) -> None:
        summary = make_summary()

        self.assertIsInstance(summary.observation_catalog, tuple)
        self.assertIs(summary.observations, summary.observation_catalog)
        self.assertEqual(
            tuple(item.observation_id for item in summary.observation_catalog),
            summary.investigation.observation_ids,
        )

    def test_catalog_tool_identity_mismatch_is_rejected(self) -> None:
        summary = make_summary()
        bad_observation = make_observation(
            "obs-target",
            "call-target",
            "query_related_metrics",
            status=ObservationStatus.ANOMALOUS,
            metric="sales",
            dimensions={"marketplace": "US"},
        )

        with self.assertRaisesRegex(RuntimeTraceError, "tool_name"):
            EvidenceDrivenRunSummary(
                investigation=summary.investigation,
                composition=summary.composition,
                observation_catalog=(bad_observation, summary.observation_catalog[1]),
            )

    def test_catalog_observation_must_belong_to_its_trace_call(self) -> None:
        summary = make_summary()
        misplaced_observation = make_observation(
            "obs-driver",
            "call-target",
            "query_metric",
            status=ObservationStatus.ANOMALOUS,
            metric="conversion_rate",
            dimensions={"marketplace": "US"},
        )

        with self.assertRaisesRegex(RuntimeTraceError, "not owned"):
            EvidenceDrivenRunSummary(
                investigation=summary.investigation,
                composition=summary.composition,
                observation_catalog=(summary.observation_catalog[0], misplaced_observation),
            )


if __name__ == "__main__":
    unittest.main()
