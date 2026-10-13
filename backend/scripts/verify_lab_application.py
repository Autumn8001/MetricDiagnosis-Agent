"""R5-004 real PostgreSQL/HTTP lifecycle acceptance; owned cluster, no model."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab_acceptance_support import temporary_postgres, controlled_lab_runner


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--postgres-bin',type=Path,required=True);args=parser.parse_args()
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from app.data_sources import DataSourceDescriptor,SourceEnvironment,SourceProvider
    from app.sandbox.dataset_writer import SandboxTarget,publish_sandbox_dataset
    from app.lab_application import build_lab_application
    checks=[]
    with temporary_postgres(args.postgres_bin) as uri:
        names=['metricsleuth_lab_r5004_state']+[f'metricsleuth_sandbox_r5004_{name}' for name in ('normal','canonical','recovery','busy')]+['metricsleuth_r5004_untouched_control']
        with psycopg.connect(uri('postgres'),autocommit=True) as admin:
            for name in names:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        with psycopg.connect(uri(names[0]),autocommit=True) as connection:
            for migration in sorted((Path(__file__).resolve().parents[1]/'migrations').glob('*.sql')):
                connection.execute(migration.read_text())
        for name in (names[-1],names[4]):
            with psycopg.connect(uri(name)) as connection:
                connection.execute('CREATE TABLE preserved_fixture (value TEXT)')
                connection.execute("INSERT INTO preserved_fixture VALUES ('unchanged-control')")
        def digest(name):
            with psycopg.connect(uri(name)) as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                rows=connection.execute('SELECT * FROM preserved_fixture').fetchall()
                return hashlib.sha256(repr(rows).encode()).hexdigest()
        before=(digest(names[-1]),digest(names[4]))
        targets=[SandboxTarget(uri(name),DataSourceDescriptor(str(uuid4()),'Isolated '+name.rsplit('_',1)[-1],
            SourceProvider.SYNTHETIC,SourceEnvironment.SANDBOX)) for name in names[1:5]]
        def build():return build_lab_application(state_database_url=uri(names[0]),targets=targets,model='unused-controlled-model',diagnosis_runner=controlled_lab_runner)
        app,lab=build()
        with TestClient(app) as client:
            assert client.get('/api/investigation-sources').json()['items']==[]
            assert len(client.get('/api/lab/catalog').json()['targets'])==4
            normal_body={'source_id':targets[0].descriptor.source_id,'scenario_id':'no_anomaly','idempotency_key':str(uuid4())}
            created=client.post('/api/lab/experiments',json=normal_body)
            assert created.status_code==202
            normal_id=created.json()['experiment_id']
            normal=client.get('/api/lab/experiments/'+normal_id).json()
            assert normal['status']=='published' and normal['snapshot_consistent'] is False
            replay=client.post('/api/lab/experiments',json=normal_body)
            assert replay.json()['experiment_id']==normal_id
            assert client.post('/api/lab/experiments',json={**normal_body,'scenario_id':'canonical'}).status_code==409
            assert client.post('/api/lab/experiments',json={**normal_body,'idempotency_key':str(uuid4())}).status_code==409
            assert client.post('/api/lab/experiments',json={**normal_body,'source_id':str(uuid4())}).status_code==404
            checks.append('publication_idempotency_and_source_isolation')
            scan=client.get('/api/metrics/scan',params={'source_id':normal['source_id'],'target_date':'2026-01-31'}).json()
            sales=next(item for item in scan['items'] if item['target_metric']=='sales')
            assert sales['observation']['current_value']=='52000.00' and sales['anomaly_candidate'] is False
            investigation=client.post('/api/lab/experiments/'+normal_id+'/investigations',json={'target_metric':'sales'})
            assert investigation.status_code==202
            run_id=investigation.json()['investigation_run_id']
            repeated=client.post('/api/lab/experiments/'+normal_id+'/investigations',json={'target_metric':'sales'})
            assert repeated.json()['investigation_run_id']==run_id
            assert client.post('/api/lab/experiments/'+normal_id+'/investigations',json={'target_metric':'orders'}).status_code==409
            assert lab.run_once()==run_id
            detail=client.get('/api/investigations/'+run_id,params={'source_id':normal['source_id']}).json()
            assert detail['run']['status']=='succeeded'
            assert len(detail['tool_calls'])==len(detail['observations'])==len(detail['evidence'])==len(detail['diagnoses'])==1
            assert detail['diagnoses'][0]['status']=='no_material_anomaly'
            checks.append('normal_sql_investigation_and_single_durable_link')
            body={'source_id':targets[1].descriptor.source_id,'scenario_id':'canonical','idempotency_key':str(uuid4())}
            canonical=client.post('/api/lab/experiments',json=body).json();canonical_id=canonical['experiment_id']
            canonical=client.get('/api/lab/experiments/'+canonical_id).json();assert canonical['status']=='published'
            run=client.post('/api/lab/experiments/'+canonical_id+'/investigations',json={'target_metric':'sales'}).json()
            assert lab.run_once()==run['investigation_run_id']
            failure=client.get('/api/investigations/'+run['investigation_run_id'],params={'source_id':canonical['source_id']}).json()
            assert failure['run']['status']=='failed'
            assert len(failure['tool_calls'])==len(failure['observations'])==1
            assert failure['evidence']==failure['diagnoses']==[]
            checks.append('failed_sql_run_preserves_steps_without_fabricated_diagnosis')
            busy=client.post('/api/lab/experiments',json={'source_id':targets[3].descriptor.source_id,'scenario_id':'traffic','idempotency_key':str(uuid4())}).json()
            busy=client.get('/api/lab/experiments/'+busy['experiment_id']).json()
            assert busy['status']=='failed' and busy['failure_code']=='publication_failed'
            assert before==(digest(names[-1]),digest(names[4]))
            checks.append('nonempty_targets_and_control_rows_preserved')
        # Simulate a process loss after warehouse commit, before state commit.
        recovery,_=lab.reserve(targets[2].descriptor.source_id,'no_anomaly',str(uuid4()))
        lab.repository.claim(recovery['experiment_id'])
        with lab._publication_lock(recovery['source_id']) as acquired:
            assert acquired
            publish_sandbox_dataset(targets[2],'no_anomaly')
            lab.recover_interrupted()
            assert lab.get(recovery['experiment_id'])['status']=='publishing'
        fresh_app,fresh_lab=build();fresh_lab.recover_interrupted()
        assert fresh_lab.get(recovery['experiment_id'])['status']=='published'
        checks.append('live_publisher_lock_and_committed_publication_recovery')
        # A lost HTTP response after run commit but before association does not
        # submit another run. Retry repairs the same deterministic association.
        with psycopg.connect(uri(names[0])) as connection:
            connection.execute('UPDATE app_state.lab_experiments SET investigation_run_id=NULL WHERE experiment_id=%s',(normal_id,))
        with TestClient(fresh_app) as client:
            repaired=client.post('/api/lab/experiments/'+normal_id+'/investigations',json={'target_metric':'sales'})
            assert repaired.json()['investigation_run_id']==run_id
            assert client.get('/api/lab/experiments/'+normal_id).json()['investigation_run_id']==run_id
            history=client.get('/api/lab/experiments').json()['items'];assert len(history)==4
            restored=client.get('/api/investigations/'+run_id,params={'source_id':normal['source_id']}).json()
            assert restored==detail
        checks.append('fresh_application_history_and_orphan_link_repair')
        with psycopg.connect(uri(names[0])) as connection:
            connection.execute('SET TRANSACTION READ ONLY')
            assert connection.execute('SELECT count(*) FROM app_state.investigation_runs').fetchone()[0]==2
    print(json.dumps({'status':'passed','checks':checks,'controlled_sql_runner':True,
        'real_model_called':False,'external_business_data':False,'existing_r2_r4_databases_accessed':False,
        'temporary_cluster_stopped':True}))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        print('lab_application_acceptance_failed',file=sys.stderr)
        raise SystemExit(1)
