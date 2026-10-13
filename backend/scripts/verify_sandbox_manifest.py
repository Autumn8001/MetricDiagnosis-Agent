"""R5-003 SQL/API acceptance in a private temporary PostgreSQL cluster.

Requires Linux ARM/x86 binaries supplied by the operator. Does not download,
install, connect existing clusters, invoke a model, or remove external databases.
All owned processes stop in finally; temporary cluster data is then removed.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--postgres-bin',type=Path,required=True)
    args=parser.parse_args()
    binary=args.postgres_bin.resolve()
    for name in ('postgres','initdb','pg_ctl'):
        if not (binary/name).is_file():parser.error('postgres binaries required')
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from app.data_sources import DataSourceDescriptor,SourceEnvironment,SourceProvider
    from app.sandbox.dataset_writer import SandboxTarget,publish_sandbox_dataset
    from app.sandbox.manifest_reader import read_sandbox_publication,SandboxManifestError
    from app.task_application import TaskApplicationConfig,_source_context,build_task_application,build_metric_read_service
    from app.main import create_app
    checks=[]
    with tempfile.TemporaryDirectory(prefix='metricsleuth-r5003-pg-') as temporary:
        root=Path(temporary);data=root/'data';socket_dir=root/'sockets';socket_dir.mkdir(mode=0o700)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        environment={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'}
        log=(root/'postgres.log').open('wb')
        started=False
        def run(command):
            result=subprocess.run(command,env=environment,stdout=log,stderr=log,timeout=30)
            if result.returncode:raise RuntimeError('isolated_postgres_command_failed')
        def uri(name):return f'postgresql://metricsleuth_test@127.0.0.1:{port}/{name}'
        try:
            run([str(binary/'initdb'),'-D',str(data),'-U','metricsleuth_test','--auth=trust','--no-locale','-E','UTF8'])
            run([str(binary/'pg_ctl'),'-D',str(data),'-l',str(root/'server.log'),'-o',f'-h 127.0.0.1 -p {port} -k {socket_dir} -c shared_buffers=16MB -c max_connections=10','-w','start'])
            started=True
            names=('metricsleuth_sandbox_r5003_primary','metricsleuth_sandbox_r5003_empty',
                   'metricsleuth_r2_r5003_control','metricsleuth_r4_r5003_control')
            with psycopg.connect(uri('postgres'),autocommit=True) as admin:
                for name in names:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            for name in names[2:]:
                with psycopg.connect(uri(name)) as connection:
                    connection.execute('CREATE TABLE untouched_fixture (value TEXT)')
                    connection.execute("INSERT INTO untouched_fixture VALUES ('r5003-control')")
            def fingerprint(name):
                with psycopg.connect(uri(name)) as connection:
                    connection.execute('SET TRANSACTION READ ONLY')
                    rows=connection.execute('SELECT * FROM untouched_fixture').fetchall()
                    return hashlib.sha256(repr(rows).encode()).hexdigest()
            controls_before=[fingerprint(name) for name in names[2:]]
            source=str(uuid4())
            descriptor=DataSourceDescriptor(source,'R5-003 Synthetic Sandbox',SourceProvider.SYNTHETIC,SourceEnvironment.SANDBOX)
            target=SandboxTarget(uri(names[0]),descriptor)
            published=publish_sandbox_dataset(target,'canonical')
            first=read_sandbox_publication(target)
            second=read_sandbox_publication(target,expected_data_version=published.data_version)
            assert first==second==published
            checks.append('publication_reconnect_read')
            def rejected(target,code,**kwargs):
                try:read_sandbox_publication(target,**kwargs)
                except SandboxManifestError as error:assert error.code==code
                else:raise AssertionError('rejection missing')
            rejected(target,'sandbox_version_unavailable',expected_data_version='missing-version')
            foreign=SandboxTarget(target.database_url,replace(descriptor,source_id=str(uuid4())))
            rejected(foreign,'sandbox_source_mismatch')
            empty=SandboxTarget(uri(names[1]),descriptor)
            rejected(empty,'sandbox_manifest_read_failed')
            rejected(target,'sandbox_target_mismatch',connection_factory=lambda:psycopg.connect(uri(names[1])))
            checks.append('missing_version_foreign_source_empty_wrong_database_rejected')
            config=TaskApplicationConfig(uri(names[2]),target.database_url,'sandbox_manifest',source,'','unused-no-model')
            for _ in range(2):
                context=_source_context(config)
                service,worker=build_task_application(config,diagnosis_runner=lambda **kwargs:None,source_context=context)
                metric_service=build_metric_read_service(config,source_context=context)
                with TestClient(create_app(investigation_tasks_service=service,metric_read_service=metric_service,include_legacy_routes=False)) as client:
                    catalog=client.get('/api/investigation-sources')
                    assert catalog.status_code==200
                    assert catalog.json()['items'][0]['data_version']==published.data_version
                    response=client.get('/api/metrics/scan',params={'source_id':source,'target_date':'2026-01-31'})
                    assert response.status_code==200
                    body=response.json();assert body['data_version']==published.data_version
                    assert body['snapshot_consistent'] is False
                    sales=next(item for item in body['items'] if item['target_metric']=='sales')
                    assert sales['observation']['current_value']=='45760.00'
                    assert sales['anomaly_candidate'] is True
            checks.append('fresh_application_catalog_and_actual_metric_scan')
            assert controls_before==[fingerprint(name) for name in names[2:]]
            with psycopg.connect(target.database_url) as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                assert connection.execute('SELECT count(*) FROM warehouse.fact_daily_performance').fetchone()[0]==558
                assert connection.execute('SELECT count(*) FROM warehouse.sandbox_dataset_manifest').fetchone()[0]==1
            checks.append('owned_controls_and_published_rows_unchanged')
        finally:
            if started:run([str(binary/'pg_ctl'),'-D',str(data),'-m','fast','-w','stop'])
            log.close()
    print(json.dumps({'status':'passed','checks':checks,'postgres':'16.4' if 'pg16' in str(binary) else 'operator_supplied',
                      'real_model_called':False,'external_business_data':False,
                      'existing_r2_r4_databases_accessed':False,'snapshot_consistent':False,'temporary_cluster_stopped':True}))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        print('sandbox_manifest_acceptance_failed',file=sys.stderr)
        raise SystemExit(1)
