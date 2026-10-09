from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.data_sources.capabilities import (
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.persistence import (
    InvestigationRunHandle,
    InvestigationTaskExecutionService,
    InvestigationTaskRequest,
    TaskExecutionFailure,
    TaskExecutionValidationError,
)
from app.persistence.models import RunStatus

from tests.test_persistence_investigation_writer import make_summary


DESCRIPTOR = DataSourceDescriptor(
    source_id="synthetic-main",
    display_name="Synthetic benchmark",
    provider=SourceProvider.SYNTHETIC,
    environment=SourceEnvironment.BENCHMARK,
)
REQUEST = InvestigationTaskRequest(
    run_id="run:task-service",
    descriptor=DESCRIPTOR,
    requested_metric="sales",
    data_version="benchmark-v1",
    parameters={"filters": {"marketplace": "US"}},
    query_reference="query:task-service",
)


class SpyCoordinator:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.handle = InvestigationRunHandle(
            run_id=REQUEST.run_id,
            descriptor=DESCRIPTOR,
            data_version=REQUEST.data_version,
        )
        self.start_error: Exception | None = None
        self.complete_error: Exception | None = None

    def start(self, descriptor, **kwargs):
        self.events.append(("start", (descriptor, kwargs)))
        if self.start_error is not None:
            raise self.start_error
        return self.handle

    def complete(self, handle, summary, *, query_reference=None):
        self.events.append(("complete", (handle, summary, query_reference)))
        if self.complete_error is not None:
            raise self.complete_error
        return handle.run_id

    def fail(self, handle, failure_code):
        self.events.append(("fail", (handle, failure_code)))
        return RunStatus.FAILED


class TestTaskExecutionRequest(unittest.TestCase):
    def test_request_is_strict_and_deeply_immutable(self) -> None:
        request = InvestigationTaskRequest(
            "run:immutable",
            DESCRIPTOR,
            "sales",
            parameters={"nested": [{"value": 1}]},
        )

        with self.assertRaises(TypeError):
            request.parameters["new"] = "value"  # type: ignore[index]
        with self.assertRaises(TypeError):
            request.parameters["nested"][0]["value"] = 2  # type: ignore[index]
        self.assertEqual(request.parameters, {"nested": ({"value": 1},)})

    def test_sensitive_nested_parameter_is_rejected(self) -> None:
        with self.assertRaises(TaskExecutionValidationError):
            InvestigationTaskRequest(
                "run:secret",
                DESCRIPTOR,
                "sales",
                parameters={"filters": {"api_key": "must-not-cross-boundary"}},
            )

    def test_non_json_parameter_is_rejected(self) -> None:
        with self.assertRaises(TaskExecutionValidationError):
            InvestigationTaskRequest(
                "run:not-json",
                DESCRIPTOR,
                "sales",
                parameters={"bad": object()},
            )
        with self.assertRaises(TaskExecutionValidationError):
            InvestigationTaskRequest(
                "run:not-finite",
                DESCRIPTOR,
                "sales",
                parameters={"bad": float("nan")},
            )


class TestInvestigationTaskExecutionService(unittest.TestCase):
    def test_success_order_keeps_runner_between_short_transactions(self) -> None:
        coordinator = SpyCoordinator()
        summary = make_summary()

        def runner(request: InvestigationTaskRequest):
            coordinator.events.append(("runner", request))
            return summary

        result = InvestigationTaskExecutionService(coordinator, runner).execute(REQUEST)

        self.assertIs(result, summary)
        self.assertEqual(
            [name for name, _payload in coordinator.events],
            ["start", "runner", "complete"],
        )
        start_payload = coordinator.events[0][1][1]  # type: ignore[index]
        self.assertEqual(start_payload["run_id"], REQUEST.run_id)
        self.assertIs(start_payload["parameters"], REQUEST.parameters)
        complete_payload = coordinator.events[2][1]  # type: ignore[index]
        self.assertEqual(complete_payload[2], REQUEST.query_reference)

    def test_runner_exception_is_rethrown_and_mapped_to_default_code(self) -> None:
        coordinator = SpyCoordinator()
        runner_error = RuntimeError("model output must never be persisted")

        def runner(_request: InvestigationTaskRequest):
            coordinator.events.append(("runner", None))
            raise runner_error

        with self.assertRaises(RuntimeError) as raised:
            InvestigationTaskExecutionService(coordinator, runner).execute(REQUEST)

        self.assertIs(raised.exception, runner_error)
        self.assertEqual(
            [name for name, _payload in coordinator.events],
            ["start", "runner", "fail"],
        )
        self.assertEqual(coordinator.events[-1][1][1], "execution_failed")  # type: ignore[index]
        self.assertNotIn(runner_error.args[0], repr(coordinator.events[-1]))

    def test_caller_controlled_code_is_strict_and_used(self) -> None:
        coordinator = SpyCoordinator()

        def runner(_request: InvestigationTaskRequest):
            raise ValueError("transient runner failure")

        with self.assertRaises(ValueError):
            InvestigationTaskExecutionService(coordinator, runner).execute(
                REQUEST,
                failure_code="tool_timeout",
            )

        self.assertEqual(coordinator.events[-1][1][1], "tool_timeout")  # type: ignore[index]

        coordinator = SpyCoordinator()
        with self.assertRaises(TaskExecutionValidationError):
            InvestigationTaskExecutionService(coordinator, runner).execute(
                REQUEST,
                failure_code="Tool Timeout",
            )
        self.assertEqual(coordinator.events, [])

    def test_runner_controlled_failure_uses_its_code_and_rethrows(self) -> None:
        coordinator = SpyCoordinator()
        runner_error = TaskExecutionFailure("agent_budget_exhausted")

        def runner(_request: InvestigationTaskRequest):
            raise runner_error

        with self.assertRaises(TaskExecutionFailure) as raised:
            InvestigationTaskExecutionService(coordinator, runner).execute(REQUEST)

        self.assertIs(raised.exception, runner_error)
        self.assertEqual(coordinator.events[-1][1][1], "agent_budget_exhausted")  # type: ignore[index]

    def test_start_failure_does_not_run_or_fail(self) -> None:
        coordinator = SpyCoordinator()
        coordinator.start_error = RuntimeError("start failed")
        runner_calls: list[object] = []

        def runner(request: InvestigationTaskRequest):
            runner_calls.append(request)
            return make_summary()

        with self.assertRaisesRegex(RuntimeError, "start failed"):
            InvestigationTaskExecutionService(coordinator, runner).execute(REQUEST)

        self.assertEqual(runner_calls, [])
        self.assertEqual([name for name, _ in coordinator.events], ["start"])

    def test_complete_failure_is_propagated_without_fail(self) -> None:
        coordinator = SpyCoordinator()
        coordinator.complete_error = RuntimeError("complete failed")

        with self.assertRaisesRegex(RuntimeError, "complete failed"):
            InvestigationTaskExecutionService(
                coordinator,
                lambda _request: make_summary(),
            ).execute(REQUEST)

        self.assertEqual(
            [name for name, _payload in coordinator.events],
            ["start", "complete"],
        )

    def test_invalid_request_and_secret_bypass_never_call_coordinator(self) -> None:
        coordinator = SpyCoordinator()
        service = InvestigationTaskExecutionService(
            coordinator,
            lambda _request: make_summary(),
        )

        with self.assertRaises(TaskExecutionValidationError):
            service.execute(object())  # type: ignore[arg-type]

        forged = InvestigationTaskRequest(
            run_id="run:forged",
            descriptor=DESCRIPTOR,
            requested_metric="sales",
            parameters={"safe": True},
        )
        object.__setattr__(forged, "parameters", {"nested": {"token": "secret"}})
        with self.assertRaises(TaskExecutionValidationError):
            service.execute(forged)
        self.assertEqual(coordinator.events, [])

    def test_service_does_not_read_database_environment(self) -> None:
        coordinator = SpyCoordinator()
        with patch.dict(os.environ, {"DATABASE_URL": "must-not-be-read"}):
            result = InvestigationTaskExecutionService(
                coordinator,
                lambda _request: make_summary(),
            ).execute(REQUEST)

        self.assertIsNotNone(result)
        self.assertEqual(
            [name for name, _payload in coordinator.events],
            ["start", "complete"],
        )


if __name__ == "__main__":
    unittest.main()
