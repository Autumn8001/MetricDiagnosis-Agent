"""Tests for the immutable Evaluation Manifest contract."""

from __future__ import annotations

import ast
import datetime
from collections import OrderedDict
from dataclasses import fields, is_dataclass
import inspect
import unittest

from app.evaluation import EvaluationManifest, EvaluationValidationError
import app.evaluation.manifest as manifest_module


class TestEvaluationManifest(unittest.TestCase):
    def make_manifest(self, **overrides: object) -> EvaluationManifest:
        values: dict[str, object] = {
            "manifest_id": "  manifest-001  ",
            "model_id": "  model-v1  ",
            "prompt": "\nComplete prompt, including whitespace.\n",
            "metric_config_version": "  metrics-v1  ",
            "dataset_version": "  dataset-v1  ",
            "run_counts_by_case": OrderedDict(
                ((" case-a ", 2), ("case-b", 3)),
            ),
            "created_at": datetime.datetime(
                2026,
                8,
                31,
                20,
                0,
                tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
            ),
        }
        values.update(overrides)
        return EvaluationManifest(**values)  # type: ignore[arg-type]

    def test_constructs_normalizes_fields_and_preserves_prompt(self) -> None:
        manifest = self.make_manifest()

        self.assertEqual(manifest.manifest_id, "manifest-001")
        self.assertEqual(manifest.model_id, "model-v1")
        self.assertEqual(manifest.prompt, "\nComplete prompt, including whitespace.\n")
        self.assertEqual(manifest.metric_config_version, "metrics-v1")
        self.assertEqual(manifest.dataset_version, "dataset-v1")
        self.assertEqual(
            list(manifest.run_counts_by_case.items()),
            [("case-a", 2), ("case-b", 3)],
        )
        self.assertEqual(
            manifest.created_at,
            datetime.datetime(2026, 8, 31, 12, tzinfo=datetime.timezone.utc),
        )
        self.assertEqual(manifest.created_at.tzinfo, datetime.timezone.utc)
        self.assertEqual(manifest.total_run_count, 5)

    def test_source_mapping_is_snapshotted_and_manifest_mapping_is_read_only(self) -> None:
        source = OrderedDict(((" case-a ", 2), ("case-b", 3)))
        manifest = self.make_manifest(run_counts_by_case=source)

        source["case-c"] = 10
        source[" case-a "] = 9

        self.assertEqual(dict(manifest.run_counts_by_case), {"case-a": 2, "case-b": 3})
        with self.assertRaises(TypeError):
            manifest.run_counts_by_case["case-c"] = 1  # type: ignore[index]

    def test_dataclass_is_frozen_and_has_exact_constructor_fields(self) -> None:
        manifest = self.make_manifest()

        self.assertTrue(is_dataclass(EvaluationManifest))
        self.assertEqual(
            [field.name for field in fields(EvaluationManifest)],
            [
                "manifest_id",
                "model_id",
                "prompt",
                "metric_config_version",
                "dataset_version",
                "run_counts_by_case",
                "created_at",
            ],
        )
        with self.assertRaises(AttributeError):
            manifest.model_id = "other"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            EvaluationManifest(
                "manifest",
                "model",
                "prompt",
                "metrics",
                "dataset",
                {"case": 1},
                datetime.datetime.now(datetime.timezone.utc),
                total_run_count=99,  # type: ignore[call-arg]
            )

    def test_total_run_count_is_derived(self) -> None:
        manifest = self.make_manifest(run_counts_by_case={"a": 4, "b": 6})

        self.assertEqual(manifest.total_run_count, 10)
        self.assertNotIn("total_run_count", inspect.signature(EvaluationManifest).parameters)

    def test_rejects_invalid_scalar_strings(self) -> None:
        required_string_fields = (
            "manifest_id",
            "model_id",
            "metric_config_version",
            "dataset_version",
        )
        for field_name in required_string_fields:
            for value in ("", " \t", None, 42, True):
                with self.subTest(field_name=field_name, value=value), self.assertRaises(
                    EvaluationValidationError
                ):
                    self.make_manifest(**{field_name: value})

    def test_rejects_empty_or_non_string_prompt_but_keeps_non_empty_whitespace(self) -> None:
        for value in ("", " \t\n", None, 42, False):
            with self.subTest(value=value), self.assertRaises(EvaluationValidationError):
                self.make_manifest(prompt=value)

        prompt = "  prompt with intentional padding  "
        self.assertEqual(self.make_manifest(prompt=prompt).prompt, prompt)

    def test_rejects_invalid_run_counts_mapping_and_case_ids(self) -> None:
        for value in (None, "not-a-mapping", [("case", 1)], 42, {}):
            with self.subTest(value=value), self.assertRaises(EvaluationValidationError):
                self.make_manifest(run_counts_by_case=value)

        for value in ({"": 1}, {" \t": 1}, {42: 1}, {None: 1}):
            with self.subTest(value=value), self.assertRaises(EvaluationValidationError):
                self.make_manifest(run_counts_by_case=value)

        duplicate_ids = OrderedDict((("case", 1), (" case ", 2)))
        with self.assertRaises(EvaluationValidationError):
            self.make_manifest(run_counts_by_case=duplicate_ids)

    def test_rejects_bool_zero_negative_and_non_integer_run_counts(self) -> None:
        for count in (True, False, 0, -1, 1.0, 1.5, "1", None):
            with self.subTest(count=count), self.assertRaises(EvaluationValidationError):
                self.make_manifest(run_counts_by_case={"case": count})

    def test_rejects_naive_or_non_datetime_created_at(self) -> None:
        invalid_values = (
            datetime.datetime(2026, 8, 31, 12),
            datetime.date(2026, 8, 31),
            "2026-08-31T12:00:00Z",
            None,
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(EvaluationValidationError):
                self.make_manifest(created_at=value)

    def test_manifest_module_has_no_external_io_or_runtime_loader_imports(self) -> None:
        tree = ast.parse(inspect.getsource(manifest_module))
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)

        self.assertEqual(
            set(imported_modules),
            {
                "__future__",
                "datetime",
                "dataclasses",
                "types",
                "typing",
                "models",
            },
        )
        forbidden = ("loader", "runtime", "sdk", "psycopg", "requests", "urllib", "socket")
        source = inspect.getsource(manifest_module).lower()
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
