"""Hermetic guards for the opt-in Olist PostgreSQL task acceptance CLI."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_olist_task_progress.py"
SPEC = importlib.util.spec_from_file_location("verify_olist_task_progress", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OlistTaskProgressAcceptanceGuardTests(unittest.TestCase):
    def test_accepts_only_the_named_loopback_database(self):
        MODULE.validate_database_url(
            "postgresql://tester@127.0.0.1:55440/metricsleuth_r2_acceptance"
        )
        MODULE.validate_database_url("postgresql://tester@localhost/metricsleuth_r2_acceptance")

    def test_rejects_non_loopback_wrong_database_and_url_options(self):
        invalid_urls = (
            "postgresql://tester@db.example/metricsleuth_r2_acceptance",
            "postgresql://tester@127.0.0.1/production",
            "postgresql://tester@127.0.0.1/metricsleuth_r2_acceptance?sslmode=disable",
            "postgresql://tester@127.0.0.1/metricsleuth_r2_acceptance#fragment",
            "sqlite:///metricsleuth_r2_acceptance",
            "postgresql://tester@[::1]/metricsleuth_r2_acceptance",
        )
        for value in invalid_urls:
            with self.subTest(database_url=value):
                with self.assertRaises(MODULE.AcceptanceFailure):
                    MODULE.validate_database_url(value)

    def test_invalid_database_guard_runs_before_application_factory(self):
        with patch.object(MODULE, "build_task_application", side_effect=AssertionError("must not build")) as factory:
            with self.assertRaises(MODULE.AcceptanceFailure):
                MODULE.verify(
                    "postgresql://tester@127.0.0.1/production",
                    "local-olist-v1",
                    MODULE.DEFAULT_TARGET_DATE,
                    "source-1",
                )
        factory.assert_not_called()

    def test_non_fixture_date_is_rejected_before_application_factory(self):
        with patch.object(MODULE, "build_task_application") as factory:
            with self.assertRaises(MODULE.AcceptanceFailure):
                MODULE.verify("postgresql://tester@127.0.0.1/metricsleuth_r2_acceptance",
                              "local-olist-v1", MODULE.dt.date(2017, 3, 21), "source-1")
        factory.assert_not_called()

    def test_cli_requires_explicit_database_and_data_version_without_environment_fallback(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://not-used"}):
            with self.assertRaises(SystemExit) as caught:
                MODULE.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_returns_safe_classification_for_invalid_database(self):
        with patch.object(MODULE, "build_task_application", side_effect=AssertionError("must not build")) as factory:
            with patch("sys.stderr") as stderr:
                code = MODULE.main([
                    "--database-url", "postgresql://tester@example.invalid/metricsleuth_r2_acceptance",
                    "--data-version", "local-olist-v1",
                ])
        self.assertEqual(code, 2)
        factory.assert_not_called()
        self.assertNotIn("example.invalid", str(stderr.write.call_args_list))


if __name__ == "__main__":
    unittest.main()
