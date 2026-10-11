"""Hermetic contract tests for the source-bound metric observation API."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.analytics.models import DateRange, MetricQueryResult, MetricQueryRow
from app.main import create_app
from app.api.metric_read_service import MetricReadService, MetricReadServiceError
from app.api.task_service import TaskSourceBinding
from app.data_sources.capabilities import (
    DataSourceCapabilities,
    DataSourceDescriptor,
    MetricCapability,
    SourceEnvironment,
    SourceProvider,
)
from app.data_sources.semantic_adapter import build_capabilities_from_registry
from app.metrics.registry import MetricRegistry
from app.task_application import TaskApplicationConfig, build_metric_read_service


def _registry(profile: str = "synthetic") -> MetricRegistry:
    root = Path(__file__).resolve().parents[2]
    filename = "metrics.yaml" if profile == "synthetic" else "olist_validation_metrics.yaml"
    return MetricRegistry.from_yaml(root / "configs" / filename)


def _binding(registry: MetricRegistry, *, source_id: str = "source-test") -> TaskSourceBinding:
    descriptor = DataSourceDescriptor(
        source_id=source_id,
        display_name="Test source",
        provider=SourceProvider.SYNTHETIC,
        environment=SourceEnvironment.SANDBOX,
    )
    return TaskSourceBinding(
        descriptor,
        build_capabilities_from_registry(registry, descriptor),
        "test-label-v1",
    )


def _result(
    *,
    metric_id: str = "sales",
    status: str = "ok",
    current: Decimal | None = Decimal("80.00"),
    baseline: Decimal | None = Decimal("100.00"),
    change: Decimal | None = Decimal("-0.20"),
    rows: bool = True,
) -> MetricQueryResult:
    target = date(2026, 10, 10)
    current_period = DateRange(target, target)
    baseline_period = DateRange(date(2026, 10, 3), date(2026, 10, 9))
    query_rows = ()
    if rows:
        query_rows = (
            MetricQueryRow(
                dimensions={},
                current_value=current,
                baseline_value=baseline,
                relative_change=change,
                status=status,
                sample_size=Decimal("140.0"),
            ),
        )
    return MetricQueryResult(
        metric_id=metric_id,
        unit="usd",
        current_period=current_period,
        baseline_period=baseline_period,
        group_by=(),
        rows=query_rows,
    )


class MetricReadApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = _registry()
        self.binding = _binding(self.registry)
        self.connection_factory = Mock()
        self.service = MetricReadService(
            binding=self.binding,
            registry=self.registry,
            analytics_connection_factory=self.connection_factory,
        )
        self.client = TestClient(create_app(metric_read_service=self.service))
        self.url = "/api/metrics/observation"
        self.query = {
            "source_id": "source-test",
            "target_metric": "sales",
            "target_date": "2026-10-10",
        }

    def _request_with_result(self, result: MetricQueryResult):
        with patch("app.api.metric_read_service.AnalyticsTools.query_metric", return_value=result) as query:
            response = self.client.get(self.url, params=self.query)
        return response, query

    def test_supported_read_returns_traceable_decimal_observation_and_fixed_scope(self) -> None:
        response, query = self._request_with_result(_result())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"], "synthetic")
        self.assertEqual(body["environment"], "sandbox")
        self.assertEqual(body["data_version"], "test-label-v1")
        self.assertEqual(body["data_version_kind"], "label")
        self.assertIs(body["persisted"], False)
        self.assertEqual(body["scope"], "source_global")
        self.assertEqual(body["comparison"], "previous_7_days")
        self.assertEqual(body["query_reference"].split(":", 1)[0], "metric-read")
        self.assertTrue(body["queried_at"].endswith("Z") or "+00:00" in body["queried_at"])
        self.assertEqual(body["observation"]["current_value"], "80.00")
        self.assertEqual(body["observation"]["baseline_value"], "100.00")
        self.assertEqual(body["observation"]["relative_change"], "-0.20")
        self.assertIs(body["anomaly_candidate"], True)
        query.assert_called_once_with(
            metric="sales",
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 10),
            compare_to="previous_7_days",
            filters={},
            group_by=[],
        )
        self.connection_factory.assert_not_called()

    def test_normal_and_inconclusive_rows_map_without_inventing_candidate(self) -> None:
        normal, _ = self._request_with_result(
            _result(change=Decimal("0.02"), current=Decimal("102"))
        )
        self.assertEqual(normal.json()["observation"]["status"], "normal")
        self.assertIs(normal.json()["anomaly_candidate"], False)

        inconclusive, _ = self._request_with_result(
            _result(change=Decimal("-0.07"), current=Decimal("93"))
        )
        self.assertEqual(inconclusive.json()["observation"]["status"], "inconclusive")
        self.assertIsNone(inconclusive.json()["anomaly_candidate"])

    def test_insufficient_and_null_values_are_preserved(self) -> None:
        response, _ = self._request_with_result(
            _result(
                status="insufficient_data",
                current=None,
                baseline=None,
                change=None,
            )
        )
        body = response.json()
        self.assertEqual(body["observation"]["status"], "insufficient_evidence")
        self.assertEqual(body["observation"]["source_status"], "insufficient_data")
        self.assertIsNone(body["observation"]["current_value"])
        self.assertIsNone(body["observation"]["baseline_value"])
        self.assertIsNone(body["observation"]["relative_change"])
        self.assertIsNone(body["anomaly_candidate"])

    def test_empty_rows_have_no_observation_or_candidate(self) -> None:
        response, _ = self._request_with_result(_result(rows=False))
        self.assertIsNone(response.json()["observation"])
        self.assertIsNone(response.json()["anomaly_candidate"])

    def test_source_and_metric_are_rejected_before_query(self) -> None:
        with patch("app.api.metric_read_service.AnalyticsTools.query_metric") as query:
            unknown_source = self.client.get(self.url, params={**self.query, "source_id": "other"})
            self.assertEqual(unknown_source.status_code, 404)
            self.assertEqual(unknown_source.json(), {"detail": {"code": "source_not_found"}})
            unknown_metric = self.client.get(self.url, params={**self.query, "target_metric": "private-marker"})
            self.assertEqual(unknown_metric.status_code, 400)
            self.assertEqual(unknown_metric.json(), {"detail": {"code": "metric_not_supported"}})
            query.assert_not_called()
        self.connection_factory.assert_not_called()

    def test_unsupported_capability_is_rejected_before_query(self) -> None:
        unsupported = MetricCapability(
            metric_id="sales", supported=False, unavailable_reason="test capability"
        )
        capabilities = DataSourceCapabilities(self.binding.descriptor, (unsupported,))
        service = MetricReadService(
            binding=TaskSourceBinding(self.binding.descriptor, capabilities, "label"),
            registry=self.registry,
            analytics_connection_factory=self.connection_factory,
        )
        with patch("app.api.metric_read_service.AnalyticsTools.query_metric") as query:
            with self.assertRaisesRegex(MetricReadServiceError, "metric_not_supported"):
                service.read(source_id="source-test", target_metric="sales", target_date=date(2026, 10, 10))
            query.assert_not_called()
        self.connection_factory.assert_not_called()

    def test_query_failure_is_fixed_and_does_not_echo_driver_text(self) -> None:
        with patch(
            "app.api.metric_read_service.AnalyticsTools.query_metric",
            side_effect=RuntimeError("private-marker password=secret"),
        ):
            response = self.client.get(self.url, params=self.query)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "metric_query_unavailable"}})
        self.assertNotIn("private-marker", response.text)
        self.assertNotIn("secret", response.text)

    def test_response_projection_failure_uses_the_same_safe_unavailable_code(self) -> None:
        with patch("app.api.metric_read_service.AnalyticsTools.query_metric", return_value=_result()), patch(
            "app.api.metric_read_service.MetricObservationView",
            side_effect=RuntimeError("projection private-marker"),
        ):
            response = self.client.get(self.url, params=self.query)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "metric_query_unavailable"}})
        self.assertNotIn("private-marker", response.text)

    def test_unconfigured_service_returns_fixed_503(self) -> None:
        response = TestClient(create_app()).get(self.url, params=self.query)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "metric_service_unavailable"}})

    def test_unknown_duplicate_and_malformed_query_inputs_are_uniform_and_safe(self) -> None:
        cases = (
            ("?source_id=source-test&target_metric=sales&target_date=2026-10-10&dsn=private-marker", 422),
            ("?source_id=source-test&source_id=private-marker&target_metric=sales&target_date=2026-10-10", 422),
            ("?source_id=%20%20&target_metric=sales&target_date=2026-10-10", 422),
            ("?source_id=source-test&target_metric=sales&target_date=2026-1-01", 422),
            ("?source_id=source-test&target_metric=sales&target_date=0001-01-01", 422),
            ("?source_id=" + "x" * 129 + "&target_metric=sales&target_date=2026-10-10", 422),
            ("?source_id=source-test&target_metric=" + "x" * 129 + "&target_date=2026-10-10", 422),
        )
        for suffix, expected_status in cases:
            with self.subTest(suffix=suffix[:80]):
                response = self.client.get(self.url + suffix)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json(), {"detail": {"code": "invalid_metric_request"}})
                self.assertNotIn("private-marker", response.text)
        self.connection_factory.assert_not_called()

    def test_builder_is_connection_free_and_keeps_profile_registries_distinct(self) -> None:
        config = TaskApplicationConfig(
            state_database_url="postgresql://test@127.0.0.1/state",
            analytics_database_url="postgresql://test@localhost/analytics",
            profile="synthetic",
            source_id="shared-source-id",
            data_version="label",
            model="not-called",
        )
        with patch("app.task_application._connection_factory") as factory:
            synthetic = build_metric_read_service(config)
            olist = build_metric_read_service(
                TaskApplicationConfig(
                    state_database_url=config.state_database_url,
                    analytics_database_url=config.analytics_database_url,
                    profile="olist_validation",
                    source_id="shared-source-id",
                    data_version="label",
                    model="not-called",
                )
            )
        self.assertEqual(synthetic._binding.descriptor.provider.value, "synthetic")
        self.assertEqual(olist._binding.descriptor.provider.value, "olist")
        self.assertNotEqual(
            {item.metric_id for item in synthetic._registry.list_metrics()},
            {item.metric_id for item in olist._registry.list_metrics()},
        )
        self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
