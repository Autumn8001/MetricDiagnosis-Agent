"""Explicit local Lab API / existing Worker entry point; no automatic migrations."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID

from app.data_sources import DataSourceDescriptor, SourceEnvironment, SourceProvider
from app.sandbox.dataset_writer import SandboxTarget
from app.task_application import _connection_factory
from app.lab.service import LabService, LabTasksFacade, LabMetricsFacade
from app.main import create_app


def build_lab_application(*, state_database_url, targets, model, diagnosis_runner=None):
    lab = LabService(state_factory=_connection_factory(state_database_url),
                     state_database_url=state_database_url, targets=targets,
                     model=model, diagnosis_runner=diagnosis_runner)
    app = create_app(investigation_tasks_service=LabTasksFacade(lab),
                     metric_read_service=LabMetricsFacade(lab), lab_service=lab,
                     include_legacy_routes=False)
    return app, lab


def load_targets(path):
    """Read only an explicit private project configuration, never discover keys."""
    file = Path(path)
    if file.stat().st_mode & 0o077 or file.stat().st_size > 32768:
        raise ValueError('private_lab_configuration_required')
    rows = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError('invalid_lab_configuration')
    targets=[]
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'source_id', 'display_name', 'database_url'}:
            raise ValueError('invalid_lab_configuration')
        source_id = str(UUID(row['source_id']))
        descriptor = DataSourceDescriptor(source_id, row['display_name'],
                                          SourceProvider.SYNTHETIC, SourceEnvironment.SANDBOX)
        targets.append(SandboxTarget(row['database_url'], descriptor))
    return targets


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local Sandbox Lab; migrations and empty targets must be prepared explicitly')
    parser.add_argument('mode', choices=('api', 'worker'))
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--once', action='store_true')
    args=parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or args.mode=='api' and args.once:
        parser.error('invalid_local_arguments')
    try:
        if args.mode=='worker' and not os.environ.get('OPENAI_API_KEY', '').strip():
            raise ValueError('model_credentials_missing')
        targets=load_targets(os.environ['METRICSLEUTH_LAB_TARGETS_FILE'])
        app, lab=build_lab_application(state_database_url=os.environ['METRICSLEUTH_STATE_DATABASE_URL'],
                                      targets=targets, model=os.environ['METRICSLEUTH_TASK_MODEL'])
        lab.recover_interrupted()
        if args.mode=='api':
            import uvicorn
            uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
        else:
            while True:
                run_id=lab.run_once()
                if args.once:
                    print('task_processed' if run_id is not None else 'no_task_available')
                    return 0
                time.sleep(2)
    except KeyboardInterrupt:
        return 0
    except Exception:
        print('lab_application_unavailable',file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
