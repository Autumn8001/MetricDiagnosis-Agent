"""Read one published Sandbox manifest without changing data or claiming a snapshot."""
from __future__ import annotations

import datetime as dt
import ipaddress
import re
from urllib.parse import urlsplit

from .dataset_writer import (
    Publication, SandboxTarget, _ALLOWED_SCENARIOS, _TARGET_DATE,
    _default_connection_factory,
)


class SandboxManifestError(RuntimeError):
    """Stable public classification; no database URL, SQL or driver exception."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def read_sandbox_publication(
    target: SandboxTarget, *, expected_data_version: str | None = None,
    connection_factory=None, expected_scenario: str | None = None,
) -> Publication:
    """Resolve server-owned source/version from a single published manifest.

    The checksum/version is a publication label, not a database snapshot. The
    caller still exposes snapshot_consistent=false and must not infer temporal
    consistency across separate metric queries.
    """
    if not isinstance(target, SandboxTarget):
        raise SandboxManifestError('sandbox_target_invalid')
    if expected_data_version is not None and (
        not isinstance(expected_data_version, str) or not expected_data_version.strip()
        or len(expected_data_version) > 128
    ):
        raise SandboxManifestError('sandbox_version_invalid')
    if expected_scenario is not None and (not isinstance(expected_scenario, str) or expected_scenario not in _ALLOWED_SCENARIOS):
        raise SandboxManifestError("sandbox_scenario_invalid")
    expected = expected_data_version.strip() if expected_data_version is not None else None
    connection = None
    try:
        connection = (_default_connection_factory(target.database_url)
                      if connection_factory is None else connection_factory())
        if getattr(connection, 'autocommit', None) is not False:
            raise SandboxManifestError('sandbox_read_transaction_required')
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute("SET LOCAL statement_timeout = '5000ms'")
                cursor.execute('SELECT current_database(), host(inet_server_addr()), inet_server_port()')
                identity = cursor.fetchone()
                parsed = urlsplit(target.database_url)
                if (not identity or len(identity) != 3 or identity[0] != parsed.path[1:]
                    or identity[1] is None or not ipaddress.ip_address(identity[1]).is_loopback
                    or identity[2] != parsed.port):
                    raise SandboxManifestError('sandbox_target_mismatch')
                cursor.execute('''SELECT source_id::text, data_version, row_count,
                                  checksum, target_date, scenario_id
                                  FROM warehouse.sandbox_dataset_manifest LIMIT 2''')
                rows = cursor.fetchall()
                if not rows:
                    raise SandboxManifestError('sandbox_manifest_missing')
                if len(rows) != 1 or len(rows[0]) != 6:
                    raise SandboxManifestError('sandbox_manifest_invalid')
                source_id, version, row_count, checksum, target_date, scenario = rows[0]
                if source_id != target.descriptor.source_id:
                    raise SandboxManifestError('sandbox_source_mismatch')
                if (not isinstance(checksum, str) or re.fullmatch(r'[0-9a-f]{64}', checksum) is None
                    or version != 'sandbox-' + checksum or type(row_count) is not int or row_count != 558
                    or type(target_date) is not dt.date or target_date != _TARGET_DATE
                    or not isinstance(scenario, str) or scenario not in _ALLOWED_SCENARIOS):
                    raise SandboxManifestError('sandbox_manifest_invalid')
                if expected_scenario is not None and scenario != expected_scenario:
                    raise SandboxManifestError("sandbox_scenario_mismatch")
                if expected is not None and version != expected:
                    raise SandboxManifestError('sandbox_version_unavailable')
                return Publication(source_id, version, row_count, checksum, target_date)
    except SandboxManifestError:
        raise
    except Exception:
        raise SandboxManifestError('sandbox_manifest_read_failed') from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
