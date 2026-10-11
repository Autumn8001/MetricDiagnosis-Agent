"""Hermetic tests for the bounded, source-bound manual metric scan API."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.analytics.models import DateRange, MetricQueryResult, MetricQueryRow
from app.api.metric_read_service import MetricReadService
from app.api.task_service import TaskSourceBinding
from app.data_sources.capabilities import (
    DataSourceCapabilities,
    MetricCapability,
    MetricNotSupportedError,
)
from app.data_sources.semantic_adapter import build_capabilities_from_registry
from app.main import create_app
from app.metrics.registry import MetricRegistry
from app.task_application import TaskApplicationConfig, build_metric_read_service


def _registry(profile: str = "synthetic") -> MetricRegistry:
    root = Path(__file__).resolve().parents[2]
    filename = "metrics.yaml" if profile == "synthetic" else "olist_validation_metrics.yaml"
    return MetricRegistry.from_yaml(root / "configs" / filename)


def _config(profile: str = "synthetic") -> TaskApplicationConfig:
    return TaskApplicationConfig(
        state_database_url="postgresql://test@127.0.0.1/state",
        analytics_database_url="postgresql://test@127.0.0.1/analytics",
        profile=profile,
        source_id="source-test",
        data_version="scan-label-v1",
        model="unused-no-model",
    )


def _query_result(metric_id: str, change: Decimal) -> MetricQueryResult:
    target = date(2026, 10, 10)
    baseline = Decimal("100.00")
    return MetricQueryResult(
        metric_id=metric_id,
        unit="usd",
        current_period=DateRange(target, target),
        baseline_period=DateRange(date(2026, 10, 3), date(2026, 10, 9)),
        group_by=(),
        rows=(MetricQueryRow(
            dimensions={}, current_value=(baseline * (Decimal("1") + change)).quantize(Decimal("0.01")),
            baseline_value=baseline, relative_change=change,
            status="ok", sample_size=Decimal("140"),
        ),),
    )


class MetricScanApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = build_metric_read_service(_config())
        self.client = TestClient(create_app(metric_read_service=self.service, include_legacy_routes=False))
        self.url = "/api/metrics/scan"
        self.params = {"source_id": "source-test", "target_date": "2026-10-10"}

    def tearDown(self) -> None:
        self.client.close()

    def test_synthetic_scan_reads_all_five_metrics_and_reports_only_anomaly_candidates(self) -> None:
        def result(*, metric: str, **_kwargs):
            change = Decimal("-0.20") if metric == "sales" else Decimal("0.01")
            return _query_result(metric, change)

        with patch("app.api.metric_read_service.AnalyticsTools.query_metric", side_effect=result) as query:
            response = self.client.get(self.url, params=self.params)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["target_metric"] for item in body["items"]], [
            "sales", "orders", "sessions", "conversion_rate", "aov",
        ])
        self.assertEqual(query.call_count, 5)
        self.assertEqual(body["anomaly_candidate_metrics"], ["sales"])
        self.assertEqual(body["source_id"], "source-test")
        self.assertEqual(body["provider"], "synthetic")
        self.assertEqual(body["environment"], "sandbox")
        self.assertEqual(body["data_version"], "scan-label-v1")
        self.assertEqual(body["data_version_kind"], "label")
        self.assertIs(body["persisted"], False)
        self.assertEqual(body["scope"], "source_global")
        self.assertEqual(body["target_date"], "2026-10-10")
        self.assertEqual(body["comparison"], "previous_7_days")
        self.assertIs(body["snapshot_consistent"], False)
        self.assertTrue(body["completed_at"].endswith("Z") or "+00:00" in body["completed_at"])
        self.assertEqual(body["items"][0]["observation"]["current_value"], "80.00")
        self.assertTrue(all(item["scope"] == "source_global" for item in body["items"]))

    def test_olist_scan_reads_only_three_declared_capabilities_and_preserves_inconclusive(self) -> None:
        service = build_metric_read_service(_config("olist_validation"))
        client = TestClient(create_app(metric_read_service=service, include_legacy_routes=False))
        try:
            with patch(
                "app.api.metric_read_service.AnalyticsTools.query_metric",
                side_effect=lambda *, metric, **_kwargs: _query_result(metric, Decimal("-0.07")),
            ) as query:
                response = client.get(self.url, params=self.params)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            metrics = [item["target_metric"] for item in body["items"]]
            self.assertEqual(metrics, ["merchandise_gmv", "orders", "olist_aov"])
            self.assertNotIn("sessions", metrics)
            self.assertEqual(query.call_count, 3)
            self.assertEqual(body["provider"], "olist")
            self.assertEqual(body["environment"], "validation")
            self.assertEqual(body["anomaly_candidate_metrics"], [])
            self.assertTrue(all(item["anomaly_candidate"] is None for item in body["items"]))
        finally:
            client.close()

    def test_exact_query_validation_is_safe_and_does_not_start_reads(self) -> None:
        cases = (
            "?source_id=source-test&target_date=2026-10-10&extra=private-marker",
            "?source_id=source-test&source_id=private-marker&target_date=2026-10-10",
            "?source_id=source-test&target_date=2026-10-10&target_date=2026-10-09",
            "?source_id=source-test",
            "?target_date=2026-10-10",
            "?source_id=source-test&target_date=2026-1-01",
            "?source_id=source-test&target_date=0001-01-01",
        )
        with patch("app.api.metric_read_service.AnalyticsTools.query_metric") as query:
            for suffix in cases:
                with self.subTest(suffix=suffix):
                    response = self.client.get(self.url + suffix)
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(response.json(), {"detail": {"code": "invalid_metric_request"}})
                    self.assertNotIn("private-marker", response.text)
            query.assert_not_called()

    def test_null_observations_are_not_normal_and_not_candidates(self) -> None:
        def missing(*, metric: str, **_kwargs):
            target = date(2026, 10, 10)
            return MetricQueryResult(
                metric_id=metric,
                unit="usd",
                current_period=DateRange(target, target),
                baseline_period=DateRange(date(2026, 10, 3), date(2026, 10, 9)),
                group_by=(), rows=(),
            )

        with patch("app.api.metric_read_service.AnalyticsTools.query_metric", side_effect=missing):
            response = self.client.get(self.url, params=self.params)
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["anomaly_candidate_metrics"], [])
        self.assertTrue(all(item["observation"] is None for item in body["items"]))

    def test_query_failure_returns_no_partial_batch_or_raw_exception(self) -> None:
        def fail_second(*, metric: str, **kwargs):
            if metric == "orders":
                raise RuntimeError("private-marker password=secret")
            return _query_result(metric, Decimal("-0.20"))

        with patch("app.api.metric_read_service.AnalyticsTools.query_metric", side_effect=fail_second):
            response = self.client.get(self.url, params=self.params)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "metric_query_unavailable"}})
        self.assertNotIn("private-marker", response.text)
        self.assertNotIn("secret", response.text)
        self.assertNotIn('"items"', response.text)

    def test_unsupported_capability_is_excluded_without_being_overridden(self) -> None:
        registry = _registry()
        descriptor = self.service._binding.descriptor
        caps = []
        for metric_id, capability in self.service._binding.capabilities.metrics.items():
            if metric_id == "sales":
                caps.append(MetricCapability(metric_id, supported=False, unavailable_reason="not connected"))
            else:
                caps.append(capability)
        binding = TaskSourceBinding(
            descriptor, DataSourceCapabilities(descriptor, caps), "label",
        )
        service = MetricReadService(
            binding=binding, registry=registry,
            analytics_connection_factory=Mock(),
        )
        client = TestClient(create_app(metric_read_service=service, include_legacy_routes=False))
        try:
            with patch(
                "app.api.metric_read_service.AnalyticsTools.query_metric",
                side_effect=lambda *, metric, **_kwargs: _query_result(metric, Decimal("0.01")),
            ) as query:
                response = client.get(self.url, params=self.params)
            self.assertEqual(response.status_code, 200)
            metrics = [item["target_metric"] for item in response.json()["items"]]
            self.assertNotIn("sales", metrics)
            self.assertEqual(query.call_count, 4)
        finally:
            client.close()

    def test_all_selected_capabilities_are_validated_before_first_query(self) -> None:
        original = DataSourceCapabilities.validate_query

        def fail_later_metric(capabilities, metric_id, *args, **kwargs):
            if metric_id == "orders":
                raise MetricNotSupportedError("test validation failure")
            return original(capabilities, metric_id, *args, **kwargs)

        with patch.object(DataSourceCapabilities, "validate_query", new=fail_later_metric), patch(
            "app.api.metric_read_service.AnalyticsTools.query_metric"
        ) as query:
            response = self.client.get(self.url, params=self.params)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": {"code": "metric_not_supported"}})
        query.assert_not_called()

    def test_empty_and_over_budget_scans_fail_before_query(self) -> None:
        registry = _registry()
        descriptor = self.service._binding.descriptor
        unsupported = DataSourceCapabilities(
            descriptor,
            [MetricCapability(metric.metric_id, False, unavailable_reason="not connected")
             for metric in registry.list_metrics()],
        )
        empty_service = MetricReadService(
            binding=TaskSourceBinding(descriptor, unsupported, "label"),
            registry=registry, analytics_connection_factory=Mock(),
        )

        definitions = registry.list_metrics()
        definitions.append(replace(definitions[0], metric_id="extra_metric"))
        expanded_registry = MetricRegistry(
            registry.table, registry._time_dimension, registry.sample_size_field,
            registry.dimensions, {metric.metric_id: metric for metric in definitions},
        )
        expanded_caps = list(self.service._binding.capabilities.metrics.values())
        original = expanded_caps[0]
        expanded_caps.append(MetricCapability(
            "extra_metric", True, grain=original.grain, dimensions=original.dimensions,
        ))
        over_budget_service = MetricReadService(
            binding=TaskSourceBinding(descriptor, DataSourceCapabilities(descriptor, expanded_caps), "label"),
            registry=expanded_registry, analytics_connection_factory=Mock(),
        )

        for service, expected in (
            (empty_service, "no_supported_metrics"),
            (over_budget_service, "metric_scan_over_budget"),
        ):
            client = TestClient(create_app(metric_read_service=service, include_legacy_routes=False))
            try:
                with patch("app.api.metric_read_service.AnalyticsTools.query_metric") as query:
                    response = client.get(self.url, params=self.params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"detail": {"code": expected}})
                query.assert_not_called()
            finally:
                client.close()

    def test_cross_source_and_unconfigured_service_are_rejected(self) -> None:
        with patch("app.api.metric_read_service.AnalyticsTools.query_metric") as query:
            response = self.client.get(self.url, params={**self.params, "source_id": "other"})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": {"code": "source_not_found"}})
            query.assert_not_called()
        unconfigured = TestClient(create_app(include_legacy_routes=False))
        try:
            response = unconfigured.get(self.url, params=self.params)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"detail": {"code": "metric_service_unavailable"}})
        finally:
            unconfigured.close()


if __name__ == "__main__":
    unittest.main()
