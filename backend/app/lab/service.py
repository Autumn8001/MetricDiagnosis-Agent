"""Source-bound experiment publication and reuse of the existing task runtime."""
from contextlib import contextmanager
from datetime import date
import hashlib
from uuid import NAMESPACE_URL, uuid5

from app.api.task_schemas import InvestigationTaskCreate, InvestigationSourcesResponse
from app.api.task_service import TaskServiceError
from app.api.metric_read_service import MetricReadServiceError
from app.data_sources import CapabilityContractError
from app.persistence.task_execution_service import InvestigationTaskRequest
from app.sandbox.dataset_writer import SandboxTarget, publish_sandbox_dataset
from app.sandbox.manifest_reader import read_sandbox_publication, SandboxManifestError
from app.task_application import TaskApplicationConfig, _source_context, build_task_application, build_metric_read_service
from .repository import LabError, LabRepository


SCENARIOS = (
    {'scenario_id': 'no_anomaly', 'title': '正常业务基线', 'description': '生成无注入异常的隔离实验数据。'},
    {'scenario_id': 'canonical', 'title': '受控异常 A', 'description': '发布可由指标查询验证的受控数据变化，调查答案不会提供给 Agent。'},
    {'scenario_id': 'traffic', 'title': '受控异常 B', 'description': '使用另一种受控变化验证调查动作，调查答案不会提供给 Agent。'},
)


class LabService:
    def __init__(self, *, state_factory, state_database_url, targets, model,
                 diagnosis_runner=None, publisher=publish_sandbox_dataset):
        if not 1 <= len(targets) <= 20 or any(not isinstance(t, SandboxTarget) for t in targets):
            raise ValueError('invalid_lab_targets')
        self.targets = {target.descriptor.source_id: target for target in targets}
        if len(self.targets) != len(targets): raise ValueError('duplicate_lab_sources')
        # Never permit two source identities to point at the same physical name.
        from urllib.parse import urlsplit
        identities = [(urlsplit(t.database_url).port, urlsplit(t.database_url).path) for t in targets]
        if len(set(identities)) != len(targets): raise ValueError('duplicate_lab_targets')
        if not callable(state_factory): raise ValueError('invalid_lab_state_factory')
        TaskApplicationConfig(state_database_url, targets[0].database_url, 'synthetic',
                              targets[0].descriptor.source_id, 'lab-configuration', model)
        state = urlsplit(state_database_url)
        if (state.port or 5432, state.path) in identities: raise ValueError('lab_state_must_be_separate')
        self.repository = LabRepository(state_factory)
        self._state_url, self._model = state_database_url, model
        self._runner, self._publisher = diagnosis_runner, publisher
        self._cache = {}

    def __repr__(self): return 'LabService(targets=[configured], state=[configured])'

    def _target(self, source_id):
        target = self.targets.get(source_id)
        if target is None: raise LabError(404, 'lab_target_not_found')
        return target

    def get(self, experiment_id):
        record = self.repository.get(experiment_id)
        if record is None or record['source_id'] not in self.targets:
            raise LabError(404, 'lab_experiment_not_found')
        return record

    def list(self, limit=20, offset=0):
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise LabError(422, 'invalid_lab_request')
        return {'items': self.repository.list(self.targets, limit, offset), 'limit': limit, 'offset': offset}

    def catalog(self):
        records = self.repository.list(self.targets, 100)
        by_source = {record['source_id']: record for record in records}
        return {'target_date': date(2026, 1, 31), 'scenarios': list(SCENARIOS), 'targets': [
            {'source_id': source, 'display_name': target.descriptor.display_name,
             'provider': 'synthetic', 'environment': 'sandbox',
             'state': by_source[source]['status'] if source in by_source else 'available',
             'experiment_id': by_source[source]['experiment_id'] if source in by_source else None}
            for source, target in self.targets.items()]}

    def reserve(self, source_id, scenario, idempotency_key):
        target = self._target(source_id)
        if scenario not in {item['scenario_id'] for item in SCENARIOS}:
            raise LabError(422, 'invalid_lab_request')
        return self.repository.reserve(target.descriptor, scenario, idempotency_key)

    @contextmanager
    def _publication_lock(self, source_id):
        connection = self.repository.factory()
        try:
            with connection.cursor() as cursor:
                key = int.from_bytes(hashlib.sha256(('lab:' + source_id).encode()).digest()[:8], signed=True)
                cursor.execute('SELECT pg_try_advisory_lock(%s)', (key,))
                acquired = cursor.fetchone()[0]
            connection.commit()
            yield acquired
        finally:
            # Session advisory lock is released even if the writer fails.
            connection.close()

    def publish(self, experiment_id):
        record = self.get(experiment_id)
        target = self._target(record['source_id'])
        with self._publication_lock(record['source_id']) as acquired:
            if not acquired or not self.repository.claim(experiment_id): return
            try:
                publication = self._publisher(target, record['scenario_id'])
                # Validate the committed manifest using a fresh read-only connection.
                actual = read_sandbox_publication(target, expected_data_version=publication.data_version,
                                                  expected_scenario=record["scenario_id"])
                if actual != publication: raise RuntimeError('publication_mismatch')
            except Exception:
                self.repository.finish(experiment_id, failure='publication_failed')
                return
            self.repository.finish(experiment_id, version=publication.data_version)

    def recover_interrupted(self):
        """Recover only owned records; never republish data or replay a model."""
        for record in self.repository.list(self.targets, 100):
            if record['status'] not in ('queued', 'publishing'): continue
            with self._publication_lock(record['source_id']) as acquired:
                if not acquired: continue  # A live publisher holds the session lock.
                try:
                    publication = read_sandbox_publication(self._target(record['source_id']), expected_scenario=record["scenario_id"])
                except SandboxManifestError as error:
                    failure = ('publication_recovery_unavailable' if error.code == 'sandbox_manifest_read_failed'
                               else 'publication_interrupted')
                    self.repository.finish(record['experiment_id'], failure=failure)
                except Exception:
                    self.repository.finish(record['experiment_id'], failure='publication_recovery_unavailable')
                else:
                    self.repository.finish(record['experiment_id'], version=publication.data_version)

    def context(self, source_id):
        target = self._target(source_id)
        records = self.repository.list([source_id], 1)
        if not records or records[0]['status'] != 'published': raise LabError(409, 'lab_not_published')
        record = records[0]
        key = (source_id, record['data_version'])
        if key not in self._cache:
            config = TaskApplicationConfig(self._state_url, target.database_url, 'sandbox_manifest',
                                           source_id, record['data_version'], self._model)
            source_context = _source_context(config)
            tasks, worker = build_task_application(config, diagnosis_runner=self._runner, source_context=source_context)
            metrics = build_metric_read_service(config, source_context=source_context)
            self._cache[key] = (tasks, worker, metrics, source_context[1])
        return self._cache[key]

    def investigate(self, experiment_id, target_metric):
        record = self.get(experiment_id)
        tasks, worker, _, binding = self.context(record['source_id'])
        try: binding.capabilities.validate_query(target_metric, group_by=[], filters={})
        except CapabilityContractError: raise LabError(400, 'lab_metric_not_supported') from None
        record = self.repository.choose_metric(experiment_id, target_metric)
        # The same experiment always creates the same run ID, including a crash
        # after task commit but before the experiment/run link commit.
        run_id = str(uuid5(NAMESPACE_URL, 'metricsleuth:lab:' + experiment_id))
        request = InvestigationTaskRequest(
            run_id=run_id, descriptor=binding.descriptor, requested_metric=target_metric,
            data_version=binding.data_version, query_reference='lab-task:' + experiment_id,
            parameters={'target_date': record['target_date'].isoformat(), 'group_by': [], 'filters': {}},
        )
        try:
            detail = tasks.get_run(run_id, record['source_id'])
        except TaskServiceError as error:
            if error.status_code != 404: raise
            try: worker.submit(request)
            except Exception:
                # A concurrent submit may already have committed this exact ID.
                # Read/verify it rather than retrying or constructing a result.
                pass
            detail = tasks.get_run(run_id, record['source_id'])
        run = detail.run
        if (run.source_id != record['source_id'] or run.environment != 'sandbox'
            or run.provider != 'synthetic' or run.data_version != record['data_version']
            or run.requested_metric != target_metric or run.query_reference != request.query_reference):
            raise LabError(409, 'lab_investigation_conflict')
        self.repository.link(experiment_id, run_id)
        return run

    def run_once(self):
        for record in self.repository.list(self.targets, 100):
            if record['status'] == 'published':
                _, worker, _, _ = self.context(record['source_id'])
                run_id = worker.run_once()
                if run_id is not None: return run_id
        return None


class LabTasksFacade:
    """Dispatch configured published sources to the existing task service."""
    def __init__(self, lab): self.lab = lab
    def _tasks(self, source_id):
        try: return self.lab.context(source_id)[0]
        except LabError as error:
            if error.status_code in (404,409): raise TaskServiceError(404, 'source_not_found') from None
            raise TaskServiceError(503, 'task_storage_unavailable') from None
        except Exception: raise TaskServiceError(503, 'task_storage_unavailable') from None
    def list_sources(self):
        items=[]
        for record in self.lab.repository.list(self.lab.targets, 100):
            if record['status']=='published': items.extend(self._tasks(record['source_id']).list_sources().items)
        return InvestigationSourcesResponse(items=items)
    def submit(self, payload: InvestigationTaskCreate): return self._tasks(payload.source_id).submit(payload)
    def list_runs(self, source_id, **kwargs): return self._tasks(source_id).list_runs(source_id, **kwargs)
    def get_run(self, run_id, source_id): return self._tasks(source_id).get_run(run_id, source_id)


class LabMetricsFacade:
    def __init__(self, lab): self.lab = lab
    def _metrics(self, source_id):
        try: return self.lab.context(source_id)[2]
        except LabError as error:
            if error.status_code in (404,409): raise MetricReadServiceError(404, 'source_not_found') from None
            raise MetricReadServiceError(503, 'metric_query_unavailable') from None
        except Exception: raise MetricReadServiceError(503, 'metric_query_unavailable') from None
    def read(self, **kwargs): return self._metrics(kwargs['source_id']).read(**kwargs)
    def scan(self, **kwargs): return self._metrics(kwargs['source_id']).scan(**kwargs)
