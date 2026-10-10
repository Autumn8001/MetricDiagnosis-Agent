"""Hermetic tests for the persisted investigation task HTTP boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from uuid import UUID

_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from fastapi.testclient import TestClient

from app.api.task_service import (
    InvestigationTasksService,
    TaskServiceError,
    TaskSourceBinding,
)
from app.main import create_app
from app.data_sources.capabilities import (
    DataSourceCapabilities,
    DataSourceDescriptor,
    MetricCapability,
    SourceEnvironment,
    SourceProvider,
)


def _binding(source_id: str = "shopify-demo") -> TaskSourceBinding:
    descriptor = DataSourceDescriptor(
        source_id=source_id,
        display_name="Shopify Demo Store",
        provider=SourceProvider.SHOPIFY,
        environment=SourceEnvironment.SANDBOX,
    )
    capabilities = DataSourceCapabilities(
        descriptor,
        [
            MetricCapability(
                "sales", True, grain=("date", "country"), dimensions=("country",)
            ),
            MetricCapability(
                "sessions",
                True,
                grain=("date", "traffic_source"),
                dimensions=("traffic_source",),
            ),
        ],
    )
    return TaskSourceBinding(descriptor, capabilities, "shopify-sync-2026-10-10")


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self.connection = connection
        self.last_sql = ""
        self.params: tuple[object, ...] = ()

    def execute(self, sql: str, params: object = ()) -> None:
        self.last_sql = sql
        self.params = tuple(params) if isinstance(params, (tuple, list)) else ()
        if sql.startswith("SET TRANSACTION"):
            self.connection.read_only_setup = True

    def fetchone(self) -> object | None:
        if "FROM app_state.investigation_runs AS r" not in self.last_sql:
            return None
        requested_source = self.params[1]
        if self.params[0] != self.connection.run_row["investigation_run_id"]:
            return None
        if requested_source != self.connection.run_row["source_id"]:
            return None
        if self.params[2] != self.connection.run_row["environment"]:
            return None
        return dict(self.connection.run_row)

    def fetchall(self) -> list[object]:
        return []

    def close(self) -> None:
        pass


class _Connection:
    autocommit = False

    def __init__(self, run_row: dict[str, object]) -> None:
        self.run_row = run_row
        self.read_only_setup = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _Worker:
    def __init__(self) -> None:
        self.request = None
        self.run_once_called = False
        self.failure: Exception | None = None

    def submit(self, request: object) -> str:
        if self.failure is not None:
            raise self.failure
        self.request = request
        return request.run_id


def _run_row(
    source_id: str = "shopify-demo",
    run_id: str = "11111111-1111-4111-8111-111111111111",
) -> dict[str, object]:
    return {
        "investigation_run_id": run_id,
        "source_id": source_id,
        "environment": "sandbox",
        "status": "queued",
        "requested_metric": "sales",
        "requested_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
        "started_at": None,
        "finished_at": None,
        "data_version": "shopify-sync-2026-10-10",
        "query_reference": "task:22222222-2222-4222-8222-222222222222",
        "failure_code": None,
        "tool_call_count": 0,
        "observation_count": 0,
        "evidence_count": 0,
        "diagnosis_count": 0,
    }


class TestInvestigationTaskAPI(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.client = TestClient(self.app)
        self.worker = _Worker()
        self.connections: list[_Connection] = []
        self.service = InvestigationTasksService(
            self._connect,
            self.worker,  # type: ignore[arg-type]
            [_binding(), _binding("another-store")],
        )
        self.app.state.investigation_tasks_service = self.service

    def _connect(self) -> _Connection:
        run_id = self.worker.request.run_id if self.worker.request is not None else None
        connection = _Connection(_run_row(run_id=run_id or _run_row()["investigation_run_id"]))
        self.connections.append(connection)
        return connection

    def test_routes_fail_closed_when_task_service_is_not_configured(self) -> None:
        del self.app.state.investigation_tasks_service
        response = self.client.get("/api/investigations", params={"source_id": "x"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], {"code": "task_service_unavailable"})

    def test_validation_response_does_not_echo_accidental_credentials(self) -> None:
        response = self.client.post(
            "/api/investigations",
            json={"source_id": "shopify-demo", "target_metric": "sales",
                  "target_date": "2026-10-09", "password": "controlled-private-marker"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": {"code": "invalid_task_request"}})
        self.assertNotIn("controlled-private-marker", response.text)
        self.assertIsNone(self.worker.request)

    def test_submit_is_queued_source_bound_and_does_not_run_worker(self) -> None:
        response = self.client.post(
            "/api/investigations",
            json={
                "source_id": "shopify-demo",
                "target_metric": "sales",
                "target_date": "2026-10-09",
                "filters": {"country": "US"},
                "group_by": ("country",),
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "queued")
        request = self.worker.request
        self.assertIsNotNone(request)
        self.assertEqual(request.descriptor, _binding().descriptor)
        self.assertEqual(request.data_version, "shopify-sync-2026-10-10")
        self.assertEqual(
            dict(request.parameters),
            {
                "target_date": "2026-10-09",
                "filters": {"country": "US"},
                "group_by": ("country",),
            },
        )
        self.assertTrue(UUID(request.run_id))
        self.assertTrue(request.query_reference.startswith("task:"))
        self.assertFalse(self.worker.run_once_called)
        self.assertEqual(len(self.connections), 1)
        self.assertTrue(self.connections[0].read_only_setup)
        self.assertTrue(self.connections[0].committed)
        self.assertTrue(self.connections[0].closed)

    def test_client_cannot_select_provider_environment_dsn_model_or_run_id(self) -> None:
        response = self.client.post(
            "/api/investigations",
            json={
                "source_id": "shopify-demo",
                "target_metric": "sales",
                "target_date": "2026-10-09",
                "provider": "postgresql",
                "environment": "live",
                "dsn": "secret",
                "model": "other-model",
                "run_id": "forged",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.worker.request)

    def test_date_must_be_canonical_calendar_date(self) -> None:
        for value in ("2026-10-09T00:00:00Z", "20261009", "2026-1-9"):
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/investigations",
                    json={
                        "source_id": "shopify-demo",
                        "target_metric": "sales",
                        "target_date": value,
                    },
                )
                self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.worker.request)

    def test_source_and_capability_errors_are_stable_and_safe(self) -> None:
        unknown_source = self.client.post(
            "/api/investigations",
            json={
                "source_id": "not-configured",
                "target_metric": "sales",
                "target_date": "2026-10-09",
            },
        )
        self.assertEqual(unknown_source.status_code, 404)
        self.assertEqual(unknown_source.json()["detail"], {"code": "source_not_found"})

        unsupported = self.client.post(
            "/api/investigations",
            json={
                "source_id": "shopify-demo",
                "target_metric": "sessions",
                "target_date": "2026-10-09",
                "group_by": ["country"],
            },
        )
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(
            unsupported.json()["detail"],
            {"code": "metric_or_dimensions_not_supported"},
        )
        self.assertIsNone(self.worker.request)

    def test_storage_errors_never_echo_exception_text(self) -> None:
        self.worker.failure = RuntimeError("postgres://private-password")
        response = self.client.post(
            "/api/investigations",
            json={
                "source_id": "shopify-demo",
                "target_metric": "sales",
                "target_date": "2026-10-09",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], {"code": "task_storage_unavailable"})
        self.assertNotIn("private-password", response.text)

    def test_list_and_detail_are_source_scoped_and_typed(self) -> None:
        listing = self.client.get(
            "/api/investigations",
            params={"source_id": "shopify-demo", "limit": 5, "offset": 2},
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json(), {"items": [], "limit": 5, "offset": 2})

        run_id = _run_row()["investigation_run_id"]
        other_source = self.client.get(
            f"/api/investigations/{run_id}", params={"source_id": "another-store"}
        )
        self.assertEqual(other_source.status_code, 404)
        self.assertEqual(
            other_source.json()["detail"], {"code": "investigation_not_found"}
        )

        detail = self.client.get(
            f"/api/investigations/{run_id}", params={"source_id": "shopify-demo"}
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["run"]["provider"], "shopify")
        self.assertEqual(detail.json()["tool_calls"], [])
        self.assertEqual(detail.json()["diagnoses"], [])
        self.assertTrue(all(connection.read_only_setup for connection in self.connections))

    def test_run_id_from_another_source_is_indistinguishable_from_missing(self) -> None:
        client = self.client
        response = client.get(
            "/api/investigations/not-the-owned-run",
            params={"source_id": "shopify-demo"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], {"code": "investigation_not_found"})

    def test_source_binding_rejects_mismatched_descriptor_and_duplicate_ids(self) -> None:
        original = _binding()
        wrong_descriptor = DataSourceDescriptor(
            source_id="different-source",
            display_name="Another Store",
            provider=SourceProvider.SHOPIFY,
            environment=SourceEnvironment.SANDBOX,
        )
        with self.assertRaises(ValueError):
            TaskSourceBinding(wrong_descriptor, original.capabilities, "v1")
        with self.assertRaises(ValueError):
            InvestigationTasksService(self._connect, self.worker, [original, original])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
