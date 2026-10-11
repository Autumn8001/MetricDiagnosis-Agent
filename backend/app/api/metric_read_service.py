"""Server-bound metric reads and bounded scans using the existing analytics layer."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from app.analytics.read_connection import AnalyticsConnectionFactory, ShortReadConnection
from app.analytics.tools import AnalyticsTools
from app.data_sources.capabilities import CapabilityContractError, UnknownMetricError
from app.metrics.registry import MetricRegistry
from app.observations.mapper import observations_from_metric_query

from .metric_read_schemas import MetricObservationView, MetricReadResponse, MetricScanResponse
from .task_service import TaskSourceBinding


class MetricReadServiceError(Exception):
    """Safe API classification for metric observation reads."""

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(code)


class MetricReadService:
    """Query only the one configured source, registry and analytics factory."""

    MAX_SCAN_METRICS = 5

    def __init__(
        self,
        *,
        binding: TaskSourceBinding,
        registry: MetricRegistry,
        analytics_connection_factory: AnalyticsConnectionFactory,
    ) -> None:
        if not isinstance(binding, TaskSourceBinding):
            raise ValueError("binding must be a TaskSourceBinding")
        if not isinstance(registry, MetricRegistry):
            raise ValueError("registry must be a MetricRegistry")
        if not callable(analytics_connection_factory):
            raise ValueError("analytics_connection_factory must be callable")
        self._binding = binding
        self._registry = registry
        self._analytics_connection_factory = analytics_connection_factory

    def _validate_global_metric(self, metric_id: str) -> None:
        binding = self._binding
        try:
            capability = binding.capabilities.get_metric_capability(metric_id)
            if not capability.supported or not self._registry.has_metric(metric_id):
                raise MetricReadServiceError(400, "metric_not_supported")
            binding.capabilities.validate_query(metric_id, group_by=[], filters={})
        except (CapabilityContractError, UnknownMetricError):
            raise MetricReadServiceError(400, "metric_not_supported") from None

    def read(self, *, source_id: str, target_metric: str, target_date: date) -> MetricReadResponse:
        binding = self._binding
        descriptor = binding.descriptor
        if source_id != descriptor.source_id:
            raise MetricReadServiceError(404, "source_not_found")

        self._validate_global_metric(target_metric)

        query_id = str(uuid4())
        query_reference = f"metric-read:{query_id}"
        try:
            result = AnalyticsTools(
                self._registry,
                ShortReadConnection(self._analytics_connection_factory),
                binding.capabilities,
            ).query_metric(
                metric=target_metric,
                start_date=target_date,
                end_date=target_date,
                compare_to="previous_7_days",
                filters={},
                group_by=[],
            )
            queried_at = datetime.now(timezone.utc)
            mapped = observations_from_metric_query(
                result,
                tool_name="analytics.query_metric",
                tool_call_id=query_id,
                filters={},
                query_or_result_reference=query_reference,
                created_at=queried_at,
            )
            if len(mapped) > 1:
                raise ValueError("global metric query returned multiple rows")

            observation = None
            anomaly_candidate = None
            if mapped:
                source_observation = mapped[0]
                observation = MetricObservationView(
                    metric=source_observation.metric,
                    status=source_observation.status.value,
                    source_status=source_observation.source_status,
                    current_period_start=source_observation.current_period.start_date,
                    current_period_end=source_observation.current_period.end_date,
                    baseline_period_start=source_observation.baseline_period.start_date,
                    baseline_period_end=source_observation.baseline_period.end_date,
                    current_value=source_observation.current_value,
                    baseline_value=source_observation.baseline_value,
                    relative_change=source_observation.relative_change,
                    unit=source_observation.unit,
                    sample_size=source_observation.sample_size,
                )
                if source_observation.status.value == "anomalous":
                    anomaly_candidate = True
                elif source_observation.status.value == "normal":
                    anomaly_candidate = False

            return MetricReadResponse(
                source_id=descriptor.source_id,
                provider=descriptor.provider.value,
                environment=descriptor.environment.value,
                data_version=binding.data_version,
                data_version_kind="label",
                persisted=False,
                scope="source_global",
                target_metric=target_metric,
                target_date=target_date,
                comparison="previous_7_days",
                queried_at=queried_at,
                query_reference=query_reference,
                observation=observation,
                anomaly_candidate=anomaly_candidate,
            )
        except Exception:
            raise MetricReadServiceError(503, "metric_query_unavailable") from None

    def scan(self, *, source_id: str, target_date: date) -> MetricScanResponse:
        """Read every supported global metric for one date, without persistence."""
        binding = self._binding
        descriptor = binding.descriptor
        if source_id != descriptor.source_id:
            raise MetricReadServiceError(404, "source_not_found")

        selected = [
            definition.metric_id
            for definition in self._registry.list_metrics()
            if definition.metric_id in binding.capabilities.metrics
            and binding.capabilities.metrics[definition.metric_id].supported
        ]
        if not selected:
            raise MetricReadServiceError(400, "no_supported_metrics")
        if len(selected) > self.MAX_SCAN_METRICS:
            raise MetricReadServiceError(400, "metric_scan_over_budget")

        # Validate the complete batch before allowing its first SQL read.
        for metric_id in selected:
            self._validate_global_metric(metric_id)

        items = [
            self.read(
                source_id=source_id,
                target_metric=metric_id,
                target_date=target_date,
            )
            for metric_id in selected
        ]
        try:
            completed_at = datetime.now(timezone.utc)
            return MetricScanResponse(
                source_id=descriptor.source_id,
                provider=descriptor.provider.value,
                environment=descriptor.environment.value,
                data_version=binding.data_version,
                data_version_kind="label",
                persisted=False,
                scope="source_global",
                target_date=target_date,
                comparison="previous_7_days",
                snapshot_consistent=False,
                completed_at=completed_at,
                items=items,
                anomaly_candidate_metrics=[
                    item.target_metric for item in items if item.anomaly_candidate is True
                ],
            )
        except Exception:
            raise MetricReadServiceError(503, "metric_query_unavailable") from None
