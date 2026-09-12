import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch


def _load_bootstrap_module_without_repo_dotenv():
    module_path = Path(__file__).parents[1] / "app" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "_metricsleuth_environment_bootstrap_under_test",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load MetricSleuth environment bootstrap")

    module = importlib.util.module_from_spec(spec)
    missing = object()
    previous_brotli = sys.modules.get("brotli", missing)
    try:
        with (
            patch.object(Path, "is_file", return_value=False),
            patch("dotenv.load_dotenv") as load_dotenv,
        ):
            spec.loader.exec_module(module)
        load_dotenv.assert_not_called()
    finally:
        if previous_brotli is missing:
            sys.modules.pop("brotli", None)
        else:
            sys.modules["brotli"] = previous_brotli
    return module


class TestEnvironmentBootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootstrap = _load_bootstrap_module_without_repo_dotenv()

    def test_loads_only_nearest_parent_with_override_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outer = Path(temp_dir)
            project = outer / "project"
            start_path = project / "backend" / "app" / "__init__.py"
            start_path.parent.mkdir(parents=True)
            (outer / ".env").write_text("OUTER=value", encoding="utf-8")
            (project / ".env").write_text("INNER=value", encoding="utf-8")

            with patch("dotenv.load_dotenv") as load_dotenv:
                loaded_path = self.bootstrap._load_local_dotenv(start_path)

        self.assertEqual(loaded_path, project / ".env")
        load_dotenv.assert_called_once_with(
            dotenv_path=project / ".env",
            override=False,
        )

    def test_does_not_override_existing_provider_environment(self):
        existing = {
            "OPENAI_API_KEY": "already-set-key",
            "OPENAI_BASE_URL": "https://already-set.invalid/v1",
            "METRICSLEUTH_AGENT_MODEL": "already-set-model",
        }
        dotenv_values = "\n".join(
            [
                "OPENAI_API_KEY=dotenv-key",
                "OPENAI_BASE_URL=https://dotenv.invalid/v1",
                "METRICSLEUTH_AGENT_MODEL=dotenv-model",
                "METRICSLEUTH_BOOTSTRAP_TEST=loaded",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text(dotenv_values, encoding="utf-8")
            start_path = root / "backend" / "app" / "__init__.py"
            start_path.parent.mkdir(parents=True)
            with patch.dict(os.environ, existing, clear=True):
                loaded_path = self.bootstrap._load_local_dotenv(start_path)
                self.assertEqual(loaded_path, root / ".env")
                for name, value in existing.items():
                    self.assertEqual(os.environ[name], value)
                self.assertEqual(
                    os.environ["METRICSLEUTH_BOOTSTRAP_TEST"],
                    "loaded",
                )

    def test_missing_dotenv_returns_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            start_path = Path(temp_dir) / "backend" / "app" / "__init__.py"
            start_path.parent.mkdir(parents=True)
            with patch("dotenv.load_dotenv") as load_dotenv:
                loaded_path = self.bootstrap._load_local_dotenv(start_path)
        self.assertIsNone(loaded_path)
        load_dotenv.assert_not_called()

    def test_brotli_bridge_installs_brotlicffi_into_empty_slot(self):
        fake_brotlicffi = ModuleType("brotlicffi")
        missing = object()
        previous_brotli = sys.modules.pop("brotli", missing)
        try:
            with patch.dict(sys.modules, {"brotlicffi": fake_brotlicffi}):
                self.assertTrue(self.bootstrap._install_brotli_compat())
                self.assertIs(sys.modules["brotli"], fake_brotlicffi)
        finally:
            sys.modules.pop("brotli", None)
            if previous_brotli is not missing:
                sys.modules["brotli"] = previous_brotli

    def test_brotli_bridge_preserves_existing_implementation(self):
        existing_brotli = ModuleType("brotli")
        fake_brotlicffi = ModuleType("brotlicffi")
        with patch.dict(
            sys.modules,
            {"brotli": existing_brotli, "brotlicffi": fake_brotlicffi},
        ):
            self.assertFalse(self.bootstrap._install_brotli_compat())
            self.assertIs(sys.modules["brotli"], existing_brotli)


if __name__ == "__main__":
    unittest.main()
