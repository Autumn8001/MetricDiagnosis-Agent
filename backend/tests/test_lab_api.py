"""Offline HTTP safety and configuration checks. SQL acceptance is separate."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from app.main import create_app
from app.lab.repository import LabError
from app.lab_application import load_targets
from app.lab.service import LabService
from app.sandbox.dataset_writer import SandboxTarget
from app.data_sources import DataSourceDescriptor, SourceEnvironment, SourceProvider


class LabAPITests(unittest.TestCase):
    def test_unconfigured_lab_is_unavailable(self):
        response=TestClient(create_app(include_legacy_routes=False)).get('/api/lab/catalog')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['detail']['code'],'lab_service_unavailable')

    def test_validation_does_not_echo_values_or_accept_target_urls(self):
        service=Mock()
        client=TestClient(create_app(lab_service=service,include_legacy_routes=False))
        response=client.post('/api/lab/experiments',json={'source_id':str(uuid4()),'scenario_id':'canonical',
            'idempotency_key':str(uuid4()),'database_url':'private-marker'})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('private-marker',response.text)
        service.reserve.assert_not_called()
        self.assertEqual(client.get('/api/lab/experiments/not-an-id').status_code,422)

    def test_safe_service_failures(self):
        service=Mock();service.reserve.side_effect=LabError(409,'lab_target_unavailable')
        client=TestClient(create_app(lab_service=service,include_legacy_routes=False))
        response=client.post('/api/lab/experiments',json={'source_id':str(uuid4()),'scenario_id':'canonical','idempotency_key':str(uuid4())})
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['detail']['code'],'lab_target_unavailable')
        service.catalog.side_effect=RuntimeError('private-driver-marker')
        response=client.get('/api/lab/catalog')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private-driver-marker',response.text)

    def test_private_configuration_only_and_no_credentials_in_service_repr(self):
        import json
        source=str(uuid4())
        row={'source_id':source,'display_name':'Test slot','database_url':'postgresql://test@127.0.0.1:55445/metricsleuth_sandbox_r5004_unit'}
        with tempfile.TemporaryDirectory() as root:
            file=Path(root)/'targets.json';file.write_text(json.dumps([row]));file.chmod(0o600)
            targets=load_targets(file)
            lab=LabService(state_factory=Mock(),state_database_url='postgresql://test@localhost:55445/test_state',
                targets=targets,model='unused')
            self.assertNotIn('postgresql',repr(lab))
            file.chmod(0o644)
            with self.assertRaises(ValueError):load_targets(file)

    def test_physical_aliases_and_shared_state_database_rejected(self):
        def target(host):
            return SandboxTarget(f'postgresql://test@{host}:55445/metricsleuth_sandbox_r5004_unit',
                DataSourceDescriptor(str(uuid4()),'Sandbox',SourceProvider.SYNTHETIC,SourceEnvironment.SANDBOX))
        one,two=target('localhost'),target('127.0.0.1')
        with self.assertRaisesRegex(ValueError,'duplicate_lab_targets'):
            LabService(state_factory=Mock(),state_database_url='postgresql://localhost/test_state',targets=[one,two],model='unused')
        with self.assertRaisesRegex(ValueError,'lab_state_must_be_separate'):
            LabService(state_factory=Mock(),state_database_url=one.database_url,targets=[one],model='unused')

    def test_migration_excludes_secrets_and_enforces_run_source_link(self):
        from app.persistence.migrations import load_migration
        sql=load_migration('005_lab_experiments.sql')
        self.assertIn('FOREIGN KEY (investigation_run_id, source_id, environment)',sql)
        self.assertIn("CHECK (environment = 'sandbox')",sql)
        self.assertIn('idempotency_key text NOT NULL UNIQUE',sql)
        self.assertNotIn('database_url',sql);self.assertNotIn('api_key',sql)

if __name__=='__main__':unittest.main()
