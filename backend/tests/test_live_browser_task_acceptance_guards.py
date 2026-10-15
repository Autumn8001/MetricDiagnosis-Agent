"""Offline safety guards for the browser-submitted live-model harness."""

from __future__ import annotations

from contextlib import redirect_stderr
from concurrent.futures import ThreadPoolExecutor
import io
import json
import socket
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from app.api.task_schemas import InvestigationTaskCreate
from app.api.task_service import TaskServiceError
from app.main import create_app
from tests.test_live_task_acceptance_guards import _valid_persisted_detail, SOURCE_ID, DATA_VERSION

from scripts import serve_live_browser_task_acceptance as acceptance


LOCAL_URL = "postgresql://tester@127.0.0.1:55440/metricsleuth_r2_acceptance"


class LiveBrowserTaskAcceptanceGuardTests(unittest.TestCase):
    def test_bounded_client_timeout_preserves_no_retries_and_disables_tracing(self):
        for timeout in (60, 120):
            with (
                patch("openai.AsyncOpenAI") as client,
                patch("agents.set_default_openai_client"),
                patch("agents.set_tracing_disabled") as tracing,
                patch.dict(acceptance.os.environ),
            ):
                acceptance.install_model_client(("test-only", None, "chat_completions", "test-model"),
                                                request_timeout_seconds=timeout)
                client.assert_called_once_with(api_key="test-only", base_url=None, max_retries=0, timeout=timeout)
                tracing.assert_called_once_with(True)
        for invalid in (True, 0, 61, 600, "120"):
            with self.subTest(invalid=invalid), self.assertRaises(acceptance.AcceptanceFailure):
                acceptance.install_model_client((), request_timeout_seconds=invalid)

    def test_event_log_survives_close_and_cannot_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "acceptance.jsonl"
            log = acceptance.AcceptanceEventLog(str(path))
            log.emit({"event": "worker_finished", "exception_type": "ProviderFailure"})
            log.close()
            original = path.read_bytes()
            self.assertEqual(json.loads(original)["exception_type"], "ProviderFailure")
            with self.assertRaises(acceptance.AcceptanceFailure):
                acceptance.AcceptanceEventLog(str(path))
            self.assertEqual(path.read_bytes(), original)

    def test_event_log_rejects_repository_and_relative_paths(self):
        for path in ("relative.jsonl", str(acceptance.REPOSITORY_ROOT / "do-not-create.jsonl")):
            with self.subTest(path=path), self.assertRaises(acceptance.AcceptanceFailure):
                acceptance.AcceptanceEventLog(path)

    def test_unavailable_log_stops_before_settings_or_database_access(self):
        args = SimpleNamespace(safe_log_file="relative.jsonl")
        with (
            patch.object(acceptance, "parse_args", return_value=args),
            patch.object(acceptance, "load_model_settings") as settings,
            patch.object(acceptance, "preflight_database") as database,
            patch("builtins.print"),
        ):
            self.assertEqual(acceptance.main([]), 2)
        settings.assert_not_called()
        database.assert_not_called()

    def test_log_write_failure_stops_before_model_settings_and_is_sanitized(self):
        log = Mock()
        log.emit.side_effect = OSError("private path do-not-print")
        with (
            patch.object(acceptance, "parse_args", return_value=SimpleNamespace(safe_log_file="unused")),
            patch.object(acceptance, "AcceptanceEventLog", return_value=log),
            patch.object(acceptance, "load_model_settings") as settings,
            patch("builtins.print") as output,
        ):
            self.assertEqual(acceptance.main([]), 2)
        settings.assert_not_called()
        self.assertNotIn("do-not-print", str(output.call_args_list))
        log.close.assert_called_once()

    def test_runner_failure_telemetry_records_type_without_raw_error_or_model_secret(self):
        class ProviderFailure(Exception):
            status_code = 401
        with (
            patch("app.agent_runtime.diagnosis_runtime.run_evidence_driven_diagnosis",
                  side_effect=ProviderFailure("private upstream response do-not-print")),
            patch("app.task_application.build_task_application", return_value=(Mock(), Mock())) as build,
        ):
            app, _ = acceptance.build_application(LOCAL_URL, "test-source", "sk-do-not-print")
            runner = build.call_args.kwargs["diagnosis_runner"]
            with self.assertRaises(ProviderFailure):
                runner("test prompt")
        telemetry = app.state.acceptance_telemetry
        self.assertEqual(telemetry["status"], "failed")
        self.assertEqual(telemetry["exception_type"], "ProviderFailure")
        self.assertEqual(telemetry["http_status"], 401)
        self.assertIsNone(telemetry["turns"])
        self.assertIsNone(telemetry["tokens"])
        self.assertNotIn("do-not-print", json.dumps(telemetry))

    def test_runner_telemetry_preserves_summary_and_never_invents_usage(self):
        summary = SimpleNamespace(investigation=SimpleNamespace(turns_count=3, tool_calls_count=2))
        with (
            patch("app.agent_runtime.diagnosis_runtime.run_evidence_driven_diagnosis", return_value=summary),
            patch("app.task_application.build_task_application", return_value=(Mock(), Mock())) as build,
        ):
            app, _ = acceptance.build_application(LOCAL_URL, "test-source", "gemini-3.8-flash-high")
            result = build.call_args.kwargs["diagnosis_runner"]("test prompt")
        self.assertIs(result, summary)
        self.assertEqual(app.state.acceptance_telemetry["turns"], 3)
        self.assertEqual(app.state.acceptance_telemetry["tool_calls"], 2)
        self.assertIsNone(app.state.acceptance_telemetry["cost"])

    def test_only_dedicated_loopback_database_is_accepted(self) -> None:
        acceptance.validate_database_url(LOCAL_URL)
        for value in (
            "postgresql://tester@example.invalid/metricsleuth_r2_acceptance",
            "postgresql://tester@127.0.0.1:55440/production",
            LOCAL_URL + "?sslmode=require",
            LOCAL_URL + "#fragment",
        ):
            with self.subTest(value=value):
                with self.assertRaises(acceptance.AcceptanceFailure) as raised:
                    acceptance.validate_database_url(value)
                self.assertEqual(raised.exception.code, "dedicated_loopback_test_database_required")

    def test_model_opt_in_is_required_before_settings_or_database_access(self) -> None:
        output = io.StringIO()
        with (
            patch.object(acceptance, "load_model_settings") as settings,
            patch.object(acceptance, "connect") as connect,
            redirect_stderr(output),
        ):
            with self.assertRaises(SystemExit) as raised:
                acceptance.main([
                    "--database-url", LOCAL_URL,
                    "--model-env-file", "does-not-need-to-exist.env",
                ])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(output.getvalue(), "invalid_arguments\n")
        settings.assert_not_called()
        connect.assert_not_called()

    def test_model_settings_reader_returns_only_explicit_fields(self) -> None:
        supplied = {
            "OPENAI_API_KEY": "do-not-print",
            "OPENAI_BASE_URL": "https://model.example.invalid/v1",
            "OPENAI_API_MODE": "chat_completions",
            "METRICSLEUTH_AGENT_MODEL": "model-name",
            "UNRELATED": "not-used",
        }
        with patch("dotenv.dotenv_values", return_value=supplied):
            result = acceptance.load_model_settings("explicit.env")
        self.assertEqual(result, ("do-not-print", "https://model.example.invalid/v1", "chat_completions", "model-name"))

    def test_safe_argument_parser_never_echoes_token_shaped_input(self) -> None:
        output = io.StringIO()
        token = "token-shaped-value-do-not-print"
        with redirect_stderr(output):
            with self.assertRaises(SystemExit) as raised:
                acceptance.parse_args([
                    "--database-url", LOCAL_URL,
                    "--model-env-file", token,
                    "--allow-model-call",
                    "--unexpected", token,
                ])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(output.getvalue(), "invalid_arguments\n")
        self.assertNotIn(token, output.getvalue())


class BrowserAcceptanceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.detail = _valid_persisted_detail()
        self.service = SimpleNamespace(
            submit=Mock(return_value=SimpleNamespace(investigation_run_id="run-1")),
            get_run=Mock(return_value=SimpleNamespace(model_dump=lambda **_: self.detail)),
        )
        self.app = create_app(investigation_tasks_service=self.service, include_legacy_routes=False)
        self.state = {"submitted": False, "processed": None, "exception_type": None}
        self.complete = threading.Event()
        self.original_submit = self.service.submit
        self.manifest = {"source_id": SOURCE_ID, "data_version": DATA_VERSION,
                         "target_metric": "sales", "target_date": "2026-10-10",
                         "request_filters": {"asin": "fixture-product"}}
        acceptance.install_acceptance_boundary(self.app, self.manifest, self.state, threading.Lock(), self.complete)
        self.payload = {key: self.manifest[key] for key in ("source_id", "target_metric", "target_date")}
        self.payload.update(filters=self.manifest["request_filters"], group_by=[])
        self.client = TestClient(self.app)

    def submit(self, **updates):
        return self.service.submit(InvestigationTaskCreate(**(self.payload | updates)))

    def test_backend_rejects_scope_changes_before_submission(self):
        for updates in ({"source_id": "other"}, {"target_metric": "orders"},
                        {"target_date": "2026-10-09"}, {"filters": {}},
                        {"group_by": ["marketplace"]}):
            with self.subTest(updates=updates), self.assertRaises(TaskServiceError):
                self.submit(**updates)
        self.original_submit.assert_not_called()
        self.assertFalse(self.state.get("attempted", False))

    def test_concurrent_submissions_only_write_once(self):
        def attempt(_):
            try:
                self.submit()
                return True
            except TaskServiceError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(8))), 1)
        self.original_submit.assert_called_once()
        self.assertEqual(self.state["run_id"], "run-1")

    def test_uncertain_submission_is_not_retried(self):
        self.original_submit.side_effect = RuntimeError("private upstream error")
        with self.assertRaises(RuntimeError):
            self.submit()
        with self.assertRaises(TaskServiceError):
            self.submit()
        self.original_submit.assert_called_once()
        self.assertFalse(self.state["submitted"])

    def test_completion_waits_for_same_worker_run_and_fresh_valid_chain(self):
        self.submit()
        request = {"run_id": "run-1"}
        self.assertEqual(self.client.post("/__acceptance__/complete", json=request).status_code, 409)
        self.state["processed"] = "other-run"
        self.assertEqual(self.client.post("/__acceptance__/complete", json=request).status_code, 409)
        self.state["processed"] = "run-1"
        self.assertEqual(self.client.post("/__acceptance__/complete", json={"run_id": "other-run"}).status_code, 409)
        self.detail["evidence"][0]["observation_id"] = "broken-link"
        self.assertEqual(self.client.post("/__acceptance__/complete", json=request).status_code, 409)
        self.assertFalse(self.complete.is_set())
        self.detail["evidence"][0]["observation_id"] = "observation-1"
        self.assertEqual(self.client.post("/__acceptance__/complete", json=request).status_code, 200)
        self.assertTrue(self.complete.is_set())
        self.service.get_run.assert_called_with("run-1", SOURCE_ID)

    def test_failed_task_cannot_be_accepted_as_success(self):
        self.submit()
        self.state["processed"] = "run-1"
        self.detail["run"]["status"] = "failed"
        self.assertEqual(self.client.post("/__acceptance__/complete", json={"run_id": "run-1"}).status_code, 409)
        self.assertFalse(self.complete.is_set())

    def test_readback_errors_are_sanitized(self):
        self.submit()
        self.state["processed"] = "run-1"
        self.service.get_run.side_effect = RuntimeError("private upstream error")
        response = self.client.post("/__acceptance__/complete", json={"run_id": "run-1"})
        self.assertEqual(response.json(), {"detail": {"code": "acceptance_readback_failed"}})
        self.assertFalse(self.complete.is_set())

    def test_http_server_survives_worker_completion_until_readback_acknowledgement(self):
        """Actual loopback HTTP/lifecycle, in-memory facts and controlled Worker."""
        self.service.submit = self.original_submit
        app = create_app(investigation_tasks_service=self.service, include_legacy_routes=False)
        worker_finished = threading.Event()
        outcome = []
        worker = Mock()
        worker.run_once.return_value = "run-1"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        args = SimpleNamespace(database_url=LOCAL_URL, model_env_file="unused.env", port=port,
                               safe_log_file="controlled-test-log")
        with (
            patch.object(acceptance, "AcceptanceEventLog"),
            patch.object(acceptance, "parse_args", return_value=args),
            patch.object(acceptance, "load_model_settings", return_value=()),
            patch.object(acceptance, "preflight_database"),
            patch.object(acceptance, "insert_fixture"),
            patch.object(acceptance, "install_model_client", return_value=(None, "controlled-test", "chat_completions")),
            patch.object(acceptance, "build_application", return_value=(app, worker)),
            patch.object(acceptance, "uuid4", side_effect=[SOURCE_ID, "fixture-product"]),
            patch.object(acceptance, "DATA_VERSION", DATA_VERSION),
            patch.object(acceptance, "SERVER_LIFETIME_SECONDS", 8),
            patch("builtins.print"),
        ):
            thread = threading.Thread(target=lambda: outcome.append(acceptance.main([])))
            thread.start()
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1) as client:
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            if client.get("/__acceptance__/manifest").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if time.monotonic() > deadline:
                            self.fail("acceptance server did not start")
                        worker_finished.wait(0.05)
                    self.assertEqual(client.post("/__acceptance__/complete", json={"run_id": "run-1"}).status_code, 409)
                    self.submit()
                    deadline = time.monotonic() + 4
                    while not worker.run_once.called and time.monotonic() < deadline:
                        worker_finished.wait(0.05)
                    self.assertTrue(worker.run_once.called)
                    # The previous bug exited here, before the browser could read.
                    worker_finished.wait(0.4)
                    self.assertTrue(thread.is_alive())
                    self.assertEqual(client.get("/__acceptance__/manifest").status_code, 200)
                    self.assertEqual(client.post("/__acceptance__/complete", json={"run_id": "run-1"}).status_code, 200)
            finally:
                thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome, [0])
            worker.run_once.assert_called_once()
