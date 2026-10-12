import datetime as dt
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

from app.data_sources import DataSourceDescriptor, SourceEnvironment, SourceProvider
from app.sandbox.dataset_writer import (
    SandboxDatasetWriterError,
    SandboxTarget,
    build_sandbox_rows,
    _checksum,
    publish_sandbox_dataset,
)


def descriptor(**changes):
    values = {
        "source_id": "246e8a1d-0aa2-4e28-a8f1-d3a886cb2af3",
        "display_name": "Local test sandbox",
        "provider": SourceProvider.SYNTHETIC,
        "environment": SourceEnvironment.SANDBOX,
    }
    values.update(changes)
    return DataSourceDescriptor(**values)


def target(url="postgresql://user:sentinel@127.0.0.1:55432/metricsleuth_sandbox_unit", desc=None):
    return SandboxTarget(url, desc or descriptor())


class _Transaction:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.in_transaction = True

    def __exit__(self, exc_type, exc, traceback):
        self.conn.rolled_back = exc_type is not None
        self.conn.committed = exc_type is None
        self.conn.in_transaction = False


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        if "SELECT current_database()" in sql:
            self.result = (self.conn.database, self.conn.address, self.conn.port)
        elif "FROM pg_class" in sql:
            self.result = ("occupied",) if self.conn.occupied else None
        elif self.conn.fail_on_execute:
            raise RuntimeError("driver detail sentinel")

    def executemany(self, sql, rows):
        self.conn.statements.append((sql, list(rows)))
        if self.conn.fail_on_execute:
            raise RuntimeError("driver detail sentinel")

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self, *, database="metricsleuth_sandbox_unit", address="127.0.0.1", port=55432,
                 occupied=False, fail_on_execute=False):
        self.database = database
        self.address = address
        self.port = port
        self.occupied = occupied
        self.fail_on_execute = fail_on_execute
        self.statements = []
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def transaction(self):
        return _Transaction(self)

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True


class SandboxDatasetWriterTests(unittest.TestCase):
    def test_target_rejects_unsafe_urls_and_source_descriptors(self):
        invalid_urls = (
            "postgresql://localhost/metricsleuth_sandbox_unit",
            "postgresql://localhost:5432/metricsleuth_sandbox_unit?sslmode=require",
            "postgresql://example.com:5432/metricsleuth_sandbox_unit",
            "postgresql://127.0.0.1:5432/metricsleuth_live",
            "postgresql://127.0.0.1:5432/METRICSLEUTH_SANDBOX_UNIT",
            "postgresql://127.0.0.1:5432/metricsleuth_sandbox_" + "x" * 50,
            "postgresql://127.0.0.1:5432/metricsleuth_sandbox_bad-name",
            "postgresql://127.0.0.1:5432/metricsleuth_sandbox_bad%20name",
            "postgresql://127.0.0.1:5432/metricsleuth_sandbox_bad;name",
            "postgresql://127.0.0.1:5432/metricsleuth_sandbox_",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(SandboxDatasetWriterError) as caught:
                    target(url)
                self.assertEqual(caught.exception.code, "sandbox_target_invalid")
                self.assertNotIn("sentinel", str(caught.exception))

        for desc in (
            descriptor(provider=SourceProvider.POSTGRESQL),
            descriptor(environment=SourceEnvironment.LIVE),
            descriptor(source_id="not-a-uuid"),
        ):
            with self.subTest(desc=desc):
                with self.assertRaises(SandboxDatasetWriterError):
                    target(desc=desc)

    def test_invalid_inputs_fail_before_connection_factory(self):
        factory = Mock(side_effect=AssertionError("must not connect"))
        with self.assertRaises(SandboxDatasetWriterError):
            publish_sandbox_dataset(target(), "legacy_scenario", factory)
        with self.assertRaises(SandboxDatasetWriterError):
            publish_sandbox_dataset(object(), "canonical", factory)
        self.assertFalse(factory.called)

    def test_url_is_hidden_and_target_is_frozen(self):
        sandbox = target()
        self.assertNotIn("sentinel", repr(sandbox))
        with self.assertRaises(FrozenInstanceError):
            sandbox.database_url = "other"

    def test_generation_failure_is_safe_and_does_not_connect(self):
        factory = Mock(side_effect=AssertionError("must not connect"))
        with patch("app.sandbox.dataset_writer.build_sandbox_rows", side_effect=RuntimeError("private sentinel")):
            with self.assertRaises(SandboxDatasetWriterError) as caught:
                publish_sandbox_dataset(target(), "canonical", factory)
        self.assertEqual(caught.exception.code, "sandbox_publish_failed")
        self.assertNotIn("sentinel", str(caught.exception))
        factory.assert_not_called()

    def test_generated_dataset_is_deterministic_and_replaces_only_target_day(self):
        rows = build_sandbox_rows("no_anomaly")
        repeat = build_sandbox_rows("no_anomaly")
        canonical = build_sandbox_rows("canonical")
        traffic = build_sandbox_rows("traffic")
        products = [
            ("ASIN-A", "Wireless Noise-Canceling Headphones", "Electronics"),
            ("ASIN-B", "Ergonomic Office Mouse", "Electronics"),
            ("ASIN-C", "USB-C Fast Charging Hub", "Accessories"),
        ]
        self.assertEqual((len(rows), len(products)), (558, 3))
        self.assertEqual(rows, repeat)
        self.assertEqual(len({row[0] for row in rows}), 31)
        self.assertEqual(sum(row[0] == dt.date(2026, 1, 31) for row in rows), 18)
        baseline = [row for row in rows if row[0] < dt.date(2026, 1, 31)]
        self.assertEqual(baseline, [row for row in canonical if row[0] < dt.date(2026, 1, 31)])
        self.assertEqual(baseline, [row for row in traffic if row[0] < dt.date(2026, 1, 31)])
        self.assertNotEqual(rows, canonical)
        self.assertNotEqual(rows, traffic)
        self.assertEqual(_checksum(rows), _checksum(repeat))

    def test_safe_identity_empty_target_and_failure_handling(self):
        for connection, expected in (
            (_Connection(database="wrong_db"), "sandbox_target_mismatch"),
            (_Connection(address="192.168.1.9"), "sandbox_target_mismatch"),
            (_Connection(port=5432), "sandbox_target_mismatch"),
            (_Connection(occupied=True), "sandbox_target_not_empty"),
            (_Connection(fail_on_execute=True), "sandbox_publish_failed"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(SandboxDatasetWriterError) as caught:
                    publish_sandbox_dataset(target(), "canonical", lambda: connection)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn("sentinel", str(caught.exception))
                self.assertTrue(connection.closed)
                self.assertTrue(connection.rolled_back)

    def test_success_returns_opaque_metadata_and_commits(self):
        connection = _Connection()
        publication = publish_sandbox_dataset(
            target(), "canonical", lambda: connection
        )
        self.assertEqual(publication.source_id, descriptor().source_id)
        self.assertEqual(publication.row_count, 558)
        self.assertEqual(publication.target_date, dt.date(2026, 1, 31))
        self.assertEqual(publication.data_version, f"sandbox-{publication.checksum}")
        self.assertNotIn("canonical", repr(publication))
        self.assertNotIn("sentinel", repr(publication))
        self.assertTrue(connection.committed)
        self.assertTrue(connection.closed)
        sql = "\n".join(statement for statement, _ in connection.statements)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn("sandbox_dataset_manifest", sql)
        self.assertNotRegex(sql, r"\b(DELETE|UPDATE|TRUNCATE|DROP)\b")


if __name__ == "__main__":
    unittest.main()
