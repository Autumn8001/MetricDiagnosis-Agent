"""Short PostgreSQL transactions for experiment identity, publication and linking."""
from contextlib import contextmanager
from uuid import uuid4

from app.persistence.repository import ApplicationStateRepository


class LabError(RuntimeError):
    def __init__(self, status: int, code: str):
        self.status_code, self.code = status, code
        super().__init__(code)


_FIELDS = ('experiment_id', 'source_id', 'environment', 'provider', 'scenario_id',
           'target_date', 'status', 'created_at', 'updated_at', 'data_version',
           'failure_code', 'requested_metric', 'investigation_run_id')
_COLUMNS = ', '.join(_FIELDS)


def _record(row):
    return dict(zip(_FIELDS, row, strict=True)) if row is not None else None


class LabRepository:
    def __init__(self, factory): self.factory = factory

    @contextmanager
    def transaction(self):
        connection = self.factory()
        try:
            if connection.autocommit is not False:
                raise LabError(503, 'lab_storage_unavailable')
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '5000ms'")
                    yield connection, cursor
        finally:
            connection.close()

    def reserve(self, descriptor, scenario, idempotency_key):
        with self.transaction() as (connection, cursor):
            # Serialize reservations, including concurrent same-key/different-source
            # requests. Publication itself never holds this transaction open.
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (7_419_500_400,))
            cursor.execute(f'SELECT {_COLUMNS}, idempotency_key FROM app_state.lab_experiments WHERE idempotency_key=%s OR source_id=%s',
                           (idempotency_key, descriptor.source_id))
            rows = cursor.fetchall()
            if rows:
                for row in rows:
                    record = _record(row[:-1])
                    if row[-1] == idempotency_key:
                        if record['source_id'] != descriptor.source_id or record['scenario_id'] != scenario:
                            raise LabError(409, 'lab_idempotency_conflict')
                        return record, False
                raise LabError(409, 'lab_target_unavailable')
            ApplicationStateRepository(connection).upsert_data_source(descriptor)
            cursor.execute(f'''INSERT INTO app_state.lab_experiments
                (experiment_id,source_id,scenario_id,idempotency_key,target_date)
                VALUES (%s,%s,%s,%s,DATE '2026-01-31') RETURNING {_COLUMNS}''',
                (str(uuid4()), descriptor.source_id, scenario, idempotency_key))
            return _record(cursor.fetchone()), True

    def get(self, experiment_id):
        with self.transaction() as (_, cursor):
            cursor.execute(f'SELECT {_COLUMNS} FROM app_state.lab_experiments WHERE experiment_id=%s', (experiment_id,))
            return _record(cursor.fetchone())

    def list(self, source_ids, limit=20, offset=0):
        with self.transaction() as (_, cursor):
            cursor.execute(f'''SELECT {_COLUMNS} FROM app_state.lab_experiments
                WHERE source_id=ANY(%s) ORDER BY created_at DESC, experiment_id DESC LIMIT %s OFFSET %s''',
                (list(source_ids), limit, offset))
            return [_record(row) for row in cursor.fetchall()]

    def claim(self, experiment_id):
        with self.transaction() as (_, cursor):
            cursor.execute("UPDATE app_state.lab_experiments SET status='publishing',updated_at=now() WHERE experiment_id=%s AND status='queued' RETURNING experiment_id", (experiment_id,))
            return cursor.fetchone() is not None

    def finish(self, experiment_id, *, version=None, failure=None):
        with self.transaction() as (_, cursor):
            cursor.execute('''UPDATE app_state.lab_experiments
                SET status=%s,data_version=%s,failure_code=%s,updated_at=now()
                WHERE experiment_id=%s AND status IN ('queued','publishing') RETURNING experiment_id''',
                ('published' if version is not None else 'failed', version, failure, experiment_id))
            return cursor.fetchone() is not None

    def choose_metric(self, experiment_id, metric):
        with self.transaction() as (_, cursor):
            cursor.execute(f'SELECT {_COLUMNS} FROM app_state.lab_experiments WHERE experiment_id=%s FOR UPDATE', (experiment_id,))
            record = _record(cursor.fetchone())
            if record is None: raise LabError(404, 'lab_experiment_not_found')
            if record['status'] != 'published': raise LabError(409, 'lab_not_published')
            if record['requested_metric'] not in (None, metric): raise LabError(409, 'lab_investigation_conflict')
            cursor.execute('UPDATE app_state.lab_experiments SET requested_metric=%s,updated_at=now() WHERE experiment_id=%s', (metric, experiment_id))
            return record

    def link(self, experiment_id, run_id):
        with self.transaction() as (_, cursor):
            cursor.execute('''UPDATE app_state.lab_experiments SET investigation_run_id=%s,updated_at=now()
                WHERE experiment_id=%s AND status='published'
                AND (investigation_run_id IS NULL OR investigation_run_id=%s) RETURNING experiment_id''',
                (run_id, experiment_id, run_id))
            if cursor.fetchone() is None: raise LabError(409, 'lab_investigation_conflict')
