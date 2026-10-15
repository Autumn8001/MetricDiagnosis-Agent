"""Offline safety guards for the browser-submitted live-model harness."""

from __future__ import annotations

from contextlib import redirect_stderr
import io
import unittest
from unittest.mock import patch

from scripts import serve_live_browser_task_acceptance as acceptance


LOCAL_URL = "postgresql://tester@127.0.0.1:55440/metricsleuth_r2_acceptance"


class LiveBrowserTaskAcceptanceGuardTests(unittest.TestCase):
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
