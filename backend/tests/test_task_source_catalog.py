"""Hermetic tests for the in-memory investigation source catalog."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.api.task_schemas import InvestigationSourceView
from app.api.task_service import InvestigationTasksService, TaskSourceBinding
from app.data_sources.capabilities import (
    DataSourceCapabilities,
    DataSourceDescriptor,
    MetricCapability,
    SourceEnvironment,
    SourceProvider,
)
from app.main import create_app
from app.task_application import TaskApplicationConfig, build_task_application


class _Worker:
    def submit(self, request: object) -> str:
        return request.run_id


def _binding(
    source_id: str,
    *,
    provider: SourceProvider = SourceProvider.SYNTHETIC,
    environment: SourceEnvironment = SourceEnvironment.SANDBOX,
    display_name: str | None = None,
    data_version: str = "fixture-version",
) -> TaskSourceBinding:
    descriptor = DataSourceDescriptor(
        source_id=source_id,
        display_name=display_name or f"Configured {source_id}",
        provider=provider,
        environment=environment,
    )
    capabilities = DataSourceCapabilities(
        descriptor,
        [
            MetricCapability(
                "orders",
                True,
                grain=("date", "country"),
                dimensions=("country",),
            ),
            MetricCapability(
                "unsupported_metric",
                False,
                unavailable_reason="Not declared for this configured source",
            ),
        ],
    )
    return TaskSourceBinding(descriptor, capabilities, data_version)


class InvestigationSourceCatalogTests(unittest.TestCase):
    def _client(self, sources: list[TaskSourceBinding]):
        connection_factory = Mock(side_effect=AssertionError("catalog must not connect"))
        service = InvestigationTasksService(connection_factory, _Worker(), sources)  # type: ignore[arg-type]
        app = create_app(investigation_tasks_service=service)
        return TestClient(app), connection_factory

    def test_empty_configured_allow_list_returns_empty_items_without_connecting(self) -> None:
        client, connection_factory = self._client([])

        response = client.get("/api/investigation-sources")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"items": []})
        connection_factory.assert_not_called()

    def test_configured_sources_and_metrics_have_stable_order_and_exact_contract(self) -> None:
        sources = [
            _binding("z-synthetic"),
            _binding(
                "a-olist",
                provider=SourceProvider.OLIST,
                environment=SourceEnvironment.VALIDATION,
                data_version="olist-static-v1",
            ),
        ]
        client, connection_factory = self._client(sources)

        response = client.get("/api/investigation-sources")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"items"})
        self.assertEqual([item["source_id"] for item in body["items"]], ["a-olist", "z-synthetic"])
        for item in body["items"]:
            self.assertEqual(
                set(item),
                {"source_id", "display_name", "provider", "environment", "data_version", "metrics"},
            )
            self.assertEqual([metric["metric_id"] for metric in item["metrics"]], ["orders", "unsupported_metric"])
            supported, unsupported = item["metrics"]
            self.assertEqual(
                supported,
                {
                    "metric_id": "orders",
                    "supported": True,
                    "grain": ["date", "country"],
                    "dimensions": ["country"],
                    "unavailable_reason": None,
                },
            )
            self.assertEqual(
                unsupported,
                {
                    "metric_id": "unsupported_metric",
                    "supported": False,
                    "grain": [],
                    "dimensions": [],
                    "unavailable_reason": "Not declared for this configured source",
                },
            )
        connection_factory.assert_not_called()

    def test_response_lists_are_detached_from_immutable_source_capabilities(self) -> None:
        binding = _binding("source-a")
        connection_factory = Mock(side_effect=AssertionError("catalog must not connect"))
        service = InvestigationTasksService(connection_factory, _Worker(), [binding])  # type: ignore[arg-type]

        first = service.list_sources()
        first.items[0].metrics[0].grain.append("mutated")
        second = service.list_sources()

        self.assertEqual(
            second.items[0].metrics[0].grain,
            ["date", "country"],
        )
        self.assertEqual(binding.capabilities.metrics["orders"].grain, ("date", "country"))
        connection_factory.assert_not_called()

    def test_catalog_contract_forbids_unreviewed_fields(self) -> None:
        with self.assertRaises(ValidationError):
            InvestigationSourceView(
                source_id="source-a",
                display_name="Configured source",
                provider="synthetic",
                environment="sandbox",
                data_version="fixture-version",
                metrics=[],
                dsn="postgresql://private",
            )

    def test_default_app_fails_closed_without_source_configuration(self) -> None:
        response = TestClient(create_app()).get("/api/investigation-sources")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "task_service_unavailable"}})

    def test_catalog_errors_return_a_fixed_code_without_echoing_exception_text(self) -> None:
        client, _ = self._client([_binding("source-a")])
        service = client.app.state.investigation_tasks_service
        with patch.object(
            service,
            "list_sources",
            side_effect=RuntimeError("postgresql://sensitive-password"),
        ):
            response = client.get("/api/investigation-sources")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": {"code": "source_catalog_unavailable"}})
        self.assertNotIn("sensitive-password", response.text)

    def test_built_synthetic_and_olist_profiles_are_listed_without_io(self) -> None:
        config_values = {
            "state_database_url": "postgresql://test:private-marker@127.0.0.1/state",
            "analytics_database_url": "postgresql://test@localhost/analytics",
            "source_id": "configured-profile",
            "data_version": "configured-version",
            "model": "controlled-test-model",
        }
        connection_factory = Mock(side_effect=AssertionError("catalog must not connect"))

        for profile, provider, environment in (
            ("synthetic", "synthetic", "sandbox"),
            ("olist_validation", "olist", "validation"),
        ):
            with self.subTest(profile=profile), patch(
                "app.task_application._connection_factory",
                return_value=connection_factory,
            ):
                config = TaskApplicationConfig(profile=profile, **config_values)
                controlled_runner = Mock()
                service, worker = build_task_application(config, diagnosis_runner=controlled_runner)
                response = TestClient(create_app(investigation_tasks_service=service)).get(
                    "/api/investigation-sources"
                )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(len(body["items"]), 1)
            item = body["items"][0]
            self.assertEqual(item["source_id"], "configured-profile")
            self.assertEqual(item["provider"], provider)
            self.assertEqual(item["environment"], environment)
            self.assertEqual(item["data_version"], "configured-version")
            binding = service._sources["configured-profile"]
            self.assertEqual(
                [metric["metric_id"] for metric in item["metrics"]],
                sorted(binding.capabilities.metrics),
            )
            for metric in item["metrics"]:
                capability = binding.capabilities.metrics[metric["metric_id"]]
                self.assertEqual(metric["supported"], capability.supported)
                self.assertEqual(metric["grain"], list(capability.grain))
                self.assertEqual(metric["dimensions"], list(capability.dimensions))
                self.assertEqual(metric["unavailable_reason"], capability.unavailable_reason)
            self.assertEqual(set(item), {
                "source_id", "display_name", "provider", "environment", "data_version", "metrics"
            })
            self.assertNotIn("private-marker", response.text)
            self.assertNotIn("controlled-test-model", response.text)
            controlled_runner.assert_not_called()
            connection_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
