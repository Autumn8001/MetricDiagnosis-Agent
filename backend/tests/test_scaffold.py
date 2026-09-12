import importlib
import unittest
from unittest.mock import patch


class TestScaffold(unittest.TestCase):
    def test_app_import_and_version(self):
        with patch("dotenv.load_dotenv"):
            app = importlib.import_module("app")

        self.assertTrue(hasattr(app, "__version__"))
        self.assertEqual(app.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
