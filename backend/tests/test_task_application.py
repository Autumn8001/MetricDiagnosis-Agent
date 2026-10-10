"""Local startup contracts; no database or model access."""
import contextlib
import io
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.task_application import TaskApplicationConfig, TaskApplicationConfigError, build_task_application, main


class TaskApplicationTests(unittest.TestCase):
    def config(self, **changes):
        values = dict(state_database_url="postgresql://test:private-marker@127.0.0.1/test",
                      analytics_database_url="postgresql://test@localhost/test",
                      profile="synthetic", source_id="test-sandbox", data_version="version1",
                      model="controlled-test-model")
        values.update(changes)
        return TaskApplicationConfig(**values)

    def test_credentials_not_in_repr(self):
        self.assertNotIn("private-marker", repr(self.config()))

    def test_building_both_profiles_does_not_connect_or_invoke_model(self):
        for profile, provider, environment in (("synthetic", "synthetic", "sandbox"),
                                               ("olist_validation", "olist", "validation")):
            with self.subTest(profile=profile), patch("app.task_application._connection_factory") as factory:
                connection = factory.return_value
                runner = unittest.mock.Mock()
                service, worker = build_task_application(self.config(profile=profile), diagnosis_runner=runner)
                connection.assert_not_called()
                runner.assert_not_called()
                binding = service._sources["test-sandbox"]
                self.assertEqual(binding.descriptor.provider.value, provider)
                self.assertEqual(binding.descriptor.environment.value, environment)

    def test_local_profiles_and_budgets_fail_closed(self):
        for changes in ({"profile": "shopify"}, {"profile": "live"},
                        {"state_database_url": "postgresql://prod.example/live"},
                        {"state_database_url": "postgresql://localhost/test?host=prod"},
                        {"max_tool_calls": True}, {"max_tool_calls": 51}, {"max_turns": 0}):
            with self.subTest(changes=changes), self.assertRaises(TaskApplicationConfigError):
                self.config(**changes)

    def test_legacy_environment_does_not_enable_application(self):
        with patch.dict(os.environ, {"DATABASE_URL": "private-marker"}, clear=True):
            with self.assertRaisesRegex(TaskApplicationConfigError, "task_configuration_missing"):
                TaskApplicationConfig.from_environment()

    def test_task_only_application_has_no_injection_routes(self):
        client = TestClient(create_app(include_legacy_routes=False))
        self.assertEqual(client.get("/health").json()["mode"], "local_tasks")
        self.assertEqual(client.post("/api/scenarios/inject", json={}).status_code, 404)
        self.assertEqual(client.post("/api/investigate", json={}).status_code, 404)
        self.assertEqual(client.get("/api/investigations?source_id=x").status_code, 503)
        response = client.options("/api/investigations", headers={
            "Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET",
        })
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_missing_credentials_prevents_worker_claim(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "app.task_application.TaskApplicationConfig.from_environment", return_value=self.config()
        ), patch("app.task_application.build_task_application") as build:
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(main(["worker", "--once"]), 2)
            build.assert_not_called()
            self.assertEqual(output.getvalue().strip(), "model_credentials_missing")


if __name__ == "__main__":
    unittest.main()
