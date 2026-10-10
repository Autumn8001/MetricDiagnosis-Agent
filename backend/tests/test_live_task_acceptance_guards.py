"""Offline guards for the one-shot real-model persistence acceptance script."""

from __future__ import annotations

from contextlib import redirect_stderr
from decimal import Decimal
import io
import unittest
from unittest.mock import patch

from scripts import verify_live_task_persistence as acceptance


LOCAL_URL = "postgresql://tester@127.0.0.1:55440/metricsleuth_r2_acceptance"
ARGS = [
    "--database-url",
    LOCAL_URL,
    "--model-env-file",
    "explicit-config.env",
    "--allow-model-call",
]


class LiveTaskAcceptanceGuardTests(unittest.TestCase):
    def test_model_call_opt_in_is_required_before_any_external_work(self) -> None:
        stderr = io.StringIO()
        with (
            patch.object(acceptance, "_load_explicit_model_settings") as load_settings,
            patch.object(acceptance, "_open_database") as open_database,
            patch.object(acceptance, "_install_explicit_model_client") as install_client,
            redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as raised:
                acceptance.main(ARGS[:-1])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(stderr.getvalue(), "invalid_arguments\n")
        load_settings.assert_not_called()
        open_database.assert_not_called()
        install_client.assert_not_called()

    def test_unknown_argument_with_token_shaped_value_is_not_echoed(self) -> None:
        stderr = io.StringIO()
        fake_token = "sk-test-shaped-value-do-not-print"
        with (
            patch.object(acceptance, "_load_explicit_model_settings") as load_settings,
            patch.object(acceptance, "_open_database") as open_database,
            patch.object(acceptance, "_install_explicit_model_client") as install_client,
            redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as raised:
                acceptance.main(ARGS + ["--unexpected", fake_token])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(stderr.getvalue(), "invalid_arguments\n")
        self.assertNotIn(fake_token, stderr.getvalue())
        load_settings.assert_not_called()
        open_database.assert_not_called()
        install_client.assert_not_called()

    def test_remote_database_is_rejected_before_environment_or_io(self) -> None:
        args = ARGS.copy()
        args[1] = "postgresql://tester@example.invalid/metricsleuth_r2_acceptance"
        with (
            patch.object(acceptance, "_load_explicit_model_settings") as load_settings,
            patch.object(acceptance, "_open_database") as open_database,
            patch.object(acceptance, "_install_explicit_model_client") as install_client,
        ):
            result = acceptance.main(args)
        self.assertEqual(result, 2)
        load_settings.assert_not_called()
        open_database.assert_not_called()
        install_client.assert_not_called()

    def test_non_acceptance_database_name_is_rejected_before_io(self) -> None:
        args = ARGS.copy()
        args[1] = "postgresql://tester@127.0.0.1:55440/production"
        with (
            patch.object(acceptance, "_load_explicit_model_settings") as load_settings,
            patch.object(acceptance, "_open_database") as open_database,
            patch.object(acceptance, "_install_explicit_model_client") as install_client,
        ):
            result = acceptance.main(args)
        self.assertEqual(result, 2)
        load_settings.assert_not_called()
        open_database.assert_not_called()
        install_client.assert_not_called()

    def test_database_url_options_are_rejected(self) -> None:
        for suffix in ("?sslmode=require", "#fragment"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(acceptance.AcceptanceFailure) as raised:
                    acceptance.validate_database_url(LOCAL_URL + suffix)
                self.assertEqual(
                    raised.exception.code,
                    "dedicated_loopback_test_database_required",
                )

    def test_http_status_metadata_is_only_a_bounded_integer(self) -> None:
        self.assertEqual(acceptance._safe_http_status(500), 500)
        for value in (None, True, 99, 600, "500", "private response"):
            with self.subTest(value=value):
                self.assertIsNone(acceptance._safe_http_status(value))

    def test_explicit_settings_reader_returns_only_configured_fields(self) -> None:
        supplied = {
            "OPENAI_API_KEY": "do-not-print",
            "OPENAI_BASE_URL": "https://model.example.invalid/v1",
            "OPENAI_API_MODE": "chat_completions",
            "METRICSLEUTH_AGENT_MODEL": "model-name",
            "IGNORED_SETTING": "unrelated",
        }
        with patch("dotenv.dotenv_values", return_value=supplied) as dotenv_values:
            settings = acceptance._load_explicit_model_settings("explicit-config.env")
        dotenv_values.assert_called_once_with("explicit-config.env")
        self.assertEqual(
            settings,
            (
                "do-not-print",
                "https://model.example.invalid/v1",
                "chat_completions",
                "model-name",
            ),
        )

    def test_redacted_output_drops_unregistered_text_and_scope(self) -> None:
        result = acceptance._json_safe_detail(
            {
                "run": {
                    "investigation_run_id": "run-id",
                    "source_id": "source-id",
                    "status": "succeeded",
                    "failure_code": None,
                },
                "tool_calls": [
                    {
                        "tool_name": "query_metric",
                        "arguments": {
                            "metric": "sales",
                            "group_by": ["marketplace", "internal_note"],
                            "filters": {
                                "asin": "owned-asin",
                                "marketplace": "US",
                                "internal_note": "private response",
                            },
                        },
                    }
                ],
                "observations": [
                    {
                        "metric": "sales",
                        "status": "anomalous",
                        "current_value": Decimal("80.00"),
                        "baseline_value": Decimal("100.00"),
                        "relative_change": Decimal("-0.2"),
                        "filters": {"asin": "owned-asin", "internal_note": "private"},
                        "dimensions": {"marketplace": "US", "private_dimension": "private"},
                    }
                ],
                "evidence": [],
                "diagnoses": [
                    {
                        "status": "diagnosed",
                        "primary_driver": "orders",
                        "affected_scope": {"marketplace": "US", "private_dimension": "secret"},
                        "evidence_ids": [],
                        "free_text": "must not be emitted",
                    }
                ],
            },
            "owned-asin",
        )
        serialized = str(result)
        self.assertNotIn("private", serialized)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("must not be emitted", serialized)
        self.assertEqual(result["observations"][0]["current_value"], "80.00")
        self.assertEqual(result["tool_trace"][0]["filters"], {"asin": "owned-asin", "marketplace": "US"})
        self.assertFalse(result["evidence_references_valid"])


if __name__ == "__main__":
    unittest.main()
