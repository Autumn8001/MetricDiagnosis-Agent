"""Manifest provenance and startup contracts; no external I/O."""
import contextlib
import datetime as dt
import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
from dataclasses import replace
from app.data_sources import DataSourceDescriptor, SourceEnvironment, SourceProvider
from app.sandbox.dataset_writer import SandboxTarget, Publication
from app.sandbox.manifest_reader import SandboxManifestError, read_sandbox_publication
from app.task_application import TaskApplicationConfig, TaskApplicationConfigError, _source_context, build_task_application


class Cursor:
    def __init__(self, source, rows=None):
        checksum='a'*64
        self.rows=rows if rows is not None else [(source,'sandbox-'+checksum,558,checksum,dt.date(2026,1,31),'canonical')]
        self.statements=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql):self.statements.append(sql)
    def fetchone(self):return ('metricsleuth_sandbox_r5003_unit','127.0.0.1',55443)
    def fetchall(self):return self.rows


class Connection:
    autocommit=False
    def __init__(self,source,rows=None):self.cur=Cursor(source,rows);self.closed=False
    def transaction(self):return contextlib.nullcontext()
    def cursor(self):return self.cur
    def close(self):self.closed=True


class SandboxManifestTests(unittest.TestCase):
    def setUp(self):
        self.source=str(uuid4())
        self.target=SandboxTarget('postgresql://test@127.0.0.1:55443/metricsleuth_sandbox_r5003_unit',
            DataSourceDescriptor(self.source,'Sandbox',SourceProvider.SYNTHETIC,SourceEnvironment.SANDBOX))
    def config(self,version=''):
        return TaskApplicationConfig(self.target.database_url,self.target.database_url,'sandbox_manifest',self.source,version,'unused-model')

    def test_published_label_is_read_only_and_connection_closed(self):
        conn=Connection(self.source)
        value=read_sandbox_publication(self.target,connection_factory=lambda:conn)
        self.assertEqual(value.data_version,'sandbox-'+'a'*64);self.assertTrue(conn.closed)
        self.assertEqual(conn.cur.statements[0],'SET TRANSACTION READ ONLY')
        self.assertTrue(all(not s.startswith(('INSERT','UPDATE','DELETE','CREATE')) for s in conn.cur.statements))
        self.assertNotIn('scenario',repr(value))

    def test_missing_wrong_source_and_multiple_manifest_rows(self):
        for rows,code in (([],'sandbox_manifest_missing'),(Connection(str(uuid4())).cur.rows,'sandbox_source_mismatch'),
                          (Connection(self.source).cur.rows*2,'sandbox_manifest_invalid')):
            with self.subTest(code=code):
                conn=Connection(self.source,rows)
                with self.assertRaises(SandboxManifestError) as error:read_sandbox_publication(self.target,connection_factory=lambda:conn)
                self.assertEqual(error.exception.code,code);self.assertTrue(conn.closed)

    def test_requested_version_and_invalid_manifest_fields(self):
        with self.assertRaisesRegex(SandboxManifestError,'sandbox_version_unavailable'):
            read_sandbox_publication(self.target,expected_data_version='missing',connection_factory=lambda:Connection(self.source))
        for index,value in ((1,'wrong'),(2,557),(2,True),(3,'invalid'),(4,dt.date(2026,2,1)),(5,'not-a-scene')):
            row=list(Connection(self.source).cur.rows[0]);row[index]=value
            with self.subTest(index=index),self.assertRaisesRegex(SandboxManifestError,'sandbox_manifest_invalid'):
                read_sandbox_publication(self.target,connection_factory=lambda:Connection(self.source,[tuple(row)]))

    def test_expected_scenario_does_not_accept_another_publication(self):
        with self.assertRaisesRegex(SandboxManifestError, 'sandbox_scenario_mismatch'):
            read_sandbox_publication(self.target, expected_scenario='no_anomaly', connection_factory=lambda: Connection(self.source))
        with self.assertRaisesRegex(SandboxManifestError, 'sandbox_scenario_invalid'):
            read_sandbox_publication(self.target, expected_scenario=[], connection_factory=lambda: Connection(self.source))

    def test_wrong_database_and_autocommit(self):
        conn=Connection(self.source);conn.cur.fetchone=lambda:('other','127.0.0.1',55443)
        with self.assertRaisesRegex(SandboxManifestError,'sandbox_target_mismatch'):read_sandbox_publication(self.target,connection_factory=lambda:conn)
        conn=Connection(self.source);conn.autocommit=True
        with self.assertRaisesRegex(SandboxManifestError,'sandbox_read_transaction_required'):read_sandbox_publication(self.target,connection_factory=lambda:conn)

    def test_driver_error_is_redacted_and_closed(self):
        conn=Connection(self.source);conn.cur.execute=Mock(side_effect=RuntimeError('private-driver-marker'))
        with self.assertRaises(SandboxManifestError) as error:read_sandbox_publication(self.target,connection_factory=lambda:conn)
        self.assertEqual(str(error.exception),'sandbox_manifest_read_failed');self.assertTrue(conn.closed)

    def test_explicit_manifest_profile_builds_existing_binding(self):
        publication=Publication(self.source,'sandbox-'+'a'*64,558,'a'*64,dt.date(2026,1,31))
        with patch('app.sandbox.manifest_reader.read_sandbox_publication',return_value=publication) as reader:
            registry,binding=_source_context(self.config())
        self.assertIsNone(reader.call_args.kwargs['expected_data_version'])
        self.assertEqual(binding.data_version,publication.data_version)
        self.assertEqual(binding.descriptor.environment,SourceEnvironment.SANDBOX)
        self.assertEqual(registry.table,'warehouse.fact_daily_performance')
        with patch('app.sandbox.manifest_reader.read_sandbox_publication') as reader:
            build_task_application(self.config(),diagnosis_runner=Mock(),source_context=(registry,binding))
        reader.assert_not_called()

    def test_configuration_resolves_only_version_from_manifest(self):
        env=dict(METRICSLEUTH_STATE_DATABASE_URL=self.target.database_url,
            METRICSLEUTH_ANALYTICS_DATABASE_URL=self.target.database_url,
            METRICSLEUTH_TASK_PROFILE='sandbox_manifest',METRICSLEUTH_TASK_SOURCE_ID=self.source,
            METRICSLEUTH_TASK_MODEL='unused-model')
        with patch.dict(os.environ,env,clear=True):self.assertEqual(TaskApplicationConfig.from_environment().data_version,'')
        for key in ('METRICSLEUTH_TASK_SOURCE_ID','METRICSLEUTH_TASK_MODEL'):
            altered=dict(env);altered.pop(key)
            with patch.dict(os.environ,altered,clear=True),self.assertRaises(TaskApplicationConfigError):TaskApplicationConfig.from_environment()
        env['METRICSLEUTH_TASK_PROFILE']='synthetic'
        with patch.dict(os.environ,env,clear=True),self.assertRaises(TaskApplicationConfigError):TaskApplicationConfig.from_environment()

    def test_wrong_profile_location_rejected_before_connect(self):
        with patch('app.sandbox.manifest_reader.read_sandbox_publication') as reader:
            with self.assertRaises(TaskApplicationConfigError):_source_context(replace(self.config(),analytics_database_url='postgresql://test@localhost:55443/protected_db'))
        reader.assert_not_called()

if __name__=='__main__':unittest.main()
