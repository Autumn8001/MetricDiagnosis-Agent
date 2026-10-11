"""Offline guards for the one-shot real-model persistence acceptance script."""

from __future__ import annotations

from contextlib import redirect_stderr
from decimal import Decimal
from copy import deepcopy
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
SOURCE_ID = "synthetic-source"
DATA_VERSION = "synthetic-version-v1"


def _valid_persisted_detail() -> dict[str, object]:
    return {
        "run": {
            "investigation_run_id": "run-1",
            "source_id": SOURCE_ID,
            "environment": "sandbox",
            "provider": "synthetic",
            "status": "succeeded",
            "data_version": DATA_VERSION,
            "tool_call_count": 1,
            "observation_count": 1,
            "evidence_count": 1,
            "diagnosis_count": 1,
        },
        "tool_calls": [
            {
                "tool_call_id": "call-1",
                "data_version": DATA_VERSION,
                # ToolCall query references are nullable in the current writer.
                "query_reference": None,
            }
        ],
        "observations": [
            {
                "observation_id": "observation-1",
                "tool_call_id": "call-1",
                "query_reference": "query-1",
                "data_version": DATA_VERSION,
            }
        ],
        "evidence": [
            {
                "evidence_id": "evidence-1",
                "observation_id": "observation-1",
                "tool_call_id": "call-1",
                "query_reference": "query-1",
                "data_version": DATA_VERSION,
            }
        ],
        "diagnoses": [
            {
                "diagnosis_id": "diagnosis-1",
                "evidence_ids": ["evidence-1"],
                "change": {"evidence_id": "evidence-1"},
                "data_version": DATA_VERSION,
            }
        ],
    }


class LiveTaskAcceptanceGuardTests(unittest.TestCase):
    def validate(self, detail: object) -> dict[str, object]:
        return acceptance._validate_persisted_provenance(
            detail,
            source_id=SOURCE_ID,
            data_version=DATA_VERSION,
        )

    def test_complete_persisted_chain_passes_without_tool_call_query_reference(self) -> None:
        result = self.validate(_valid_persisted_detail())
        self.assertTrue(result["passed"])
        self.assertEqual(result["failure_codes"], [])
        self.assertTrue(all(result["checks"].values()))

    def test_every_vector_requires_unique_nonblank_identifiers(self) -> None:
        for vector, identifier in (
            ("tool_calls", "tool_call_id"),
            ("observations", "observation_id"),
            ("evidence", "evidence_id"),
            ("diagnoses", "diagnosis_id"),
        ):
            for invalid in ("  ", "duplicate"):
                with self.subTest(vector=vector, invalid=invalid):
                    detail = _valid_persisted_detail()
                    detail[vector].append(deepcopy(detail[vector][0]))
                    detail[vector][1][identifier] = (
                        detail[vector][0][identifier] if invalid == "duplicate" else invalid
                    )
                    result = self.validate(detail)
                    self.assertFalse(result["passed"])
                    self.assertIn("unique_identifiers_invalid", result["failure_codes"])

    def test_source_provider_environment_and_version_are_bound(self) -> None:
        mutations = (
            ("source_id", "other-source"),
            ("provider", "shopify"),
            ("environment", "live"),
            ("data_version", "other-version"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                detail = _valid_persisted_detail()
                detail["run"][field] = value
                result = self.validate(detail)
                self.assertFalse(result["checks"]["run_metadata"])

    def test_each_fact_vector_must_match_declared_count(self) -> None:
        for count_field in (
            "tool_call_count",
            "observation_count",
            "evidence_count",
            "diagnosis_count",
        ):
            with self.subTest(count_field=count_field):
                detail = _valid_persisted_detail()
                detail["run"][count_field] += 1
                result = self.validate(detail)
                self.assertFalse(result["checks"]["declared_counts"])

    def test_observation_must_link_to_a_persisted_tool_call(self) -> None:
        detail = _valid_persisted_detail()
        detail["observations"][0]["tool_call_id"] = "missing-call"
        result = self.validate(detail)
        self.assertFalse(result["checks"]["observation_tool_links"])

    def test_evidence_must_link_observation_call_and_query_reference(self) -> None:
        mutations = (
            ("observation_id", "missing-observation"),
            ("tool_call_id", "different-call"),
            ("query_reference", "different-query"),
            ("query_reference", "  "),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                detail = _valid_persisted_detail()
                detail["evidence"][0][field] = value
                result = self.validate(detail)
                self.assertFalse(result["checks"]["evidence_links"])

    def test_every_fact_version_must_match_the_expected_data_version(self) -> None:
        for vector in ("tool_calls", "observations", "evidence", "diagnoses"):
            with self.subTest(vector=vector):
                detail = _valid_persisted_detail()
                detail[vector][0]["data_version"] = "stale-version"
                result = self.validate(detail)
                self.assertFalse(result["checks"]["data_versions"])

    def test_diagnosis_citations_must_exist_be_unique_and_include_change_evidence(self) -> None:
        cases = (
            ["missing-evidence"],
            ["evidence-1", "evidence-1"],
            None,
            "evidence-1",
            [["evidence-1"]],
        )
        for references in cases:
            with self.subTest(references=repr(references)):
                detail = _valid_persisted_detail()
                detail["diagnoses"][0]["evidence_ids"] = references
                result = self.validate(detail)
                self.assertFalse(result["checks"]["diagnosis_references"])

        for change in (
            {"evidence_id": "uncited-evidence"},
            {},
            {"evidence_id": None},
            {"evidence_id": "  "},
        ):
            with self.subTest(change=change):
                detail = _valid_persisted_detail()
                detail["diagnoses"][0]["change"] = change
                result = self.validate(detail)
                self.assertFalse(result["checks"]["diagnosis_references"])

    def test_incomplete_or_failed_run_cannot_pass(self) -> None:
        for mutation in ("no_diagnosis", "no_facts", "failed_run"):
            with self.subTest(mutation=mutation):
                detail = _valid_persisted_detail()
                if mutation == "no_diagnosis":
                    detail["diagnoses"] = []
                    detail["run"]["diagnosis_count"] = 0
                elif mutation == "no_facts":
                    detail["observations"] = []
                    detail["run"]["observation_count"] = 0
                else:
                    detail["run"]["status"] = "failed"
                result = self.validate(detail)
                self.assertFalse(result["passed"])

    def test_malformed_failure_output_contains_no_raw_text(self) -> None:
        result = self.validate({"private_payload": "must not appear"})
        serialized = str(result)
        self.assertNotIn("must not appear", serialized)
        self.assertEqual(result["failure_codes"], ["detail_shape_invalid"])

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
