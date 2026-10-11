"""Server-bound, single-metric read service using the existing analytics layer."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from app.analytics.read_connection import AnalyticsConnectionFactory, ShortReadConnection
from app.analytics.tools import AnalyticsTools
from app.data_sources.capabilities import CapabilityContractError, UnknownMetricError
from app.metrics.registry import MetricRegistry
from app.observations.mapper import observations_from_metric_query

from .metric_read_schemas import MetricObservationView, MetricReadResponse
from .task_service import TaskSourceBinding


class MetricReadServiceError(Exception):
    """Safe API classification for metric observation reads."""

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(code)


class MetricReadService:
    """Query only the one configured source, registry and analytics factory."""

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

    def read(self, *, source_id: str, target_metric: str, target_date: date) -> MetricReadResponse:
        binding = self._binding
        descriptor = binding.descriptor
        if source_id != descriptor.source_id:
            raise MetricReadServiceError(404, "source_not_found")

        try:
            capability = binding.capabilities.get_metric_capability(target_metric)
        except (UnknownMetricError, ValueError):
            raise MetricReadServiceError(400, "metric_not_supported") from None
        if not capability.supported or not self._registry.has_metric(target_metric):
            raise MetricReadServiceError(400, "metric_not_supported")
        try:
            binding.capabilities.validate_query(
                target_metric,
                group_by=[],
                filters={},
            )
        except CapabilityContractError:
            raise MetricReadServiceError(400, "metric_not_supported") from None

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
