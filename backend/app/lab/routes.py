"""Explicit Lab resources. Credentials and physical database targets stay server-owned."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from app.api.task_schemas import TaskRunView
from .repository import LabError

router = APIRouter(prefix='/api/lab', tags=['Sandbox Lab'])


class CreateExperiment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: UUID
    scenario_id: Literal['no_anomaly', 'canonical', 'traffic']
    idempotency_key: UUID


class StartInvestigation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_metric: Literal['sales', 'orders', 'sessions', 'conversion_rate', 'aov'] = 'sales'


class ExperimentView(BaseModel):
    experiment_id: str
    source_id: str
    environment: Literal['sandbox']
    provider: Literal['synthetic']
    scenario_id: str
    target_date: date
    status: Literal['queued', 'publishing', 'published', 'failed']
    created_at: datetime
    updated_at: datetime
    data_version: str | None
    failure_code: str | None
    requested_metric: str | None
    investigation_run_id: str | None
    data_version_kind: Literal['label'] = 'label'
    snapshot_consistent: Literal[False] = False


class ExperimentList(BaseModel):
    items: list[ExperimentView]
    limit: int
    offset: int


def service(request: Request):
    lab = getattr(request.app.state, 'lab_service', None)
    if lab is None: raise HTTPException(503, detail={'code': 'lab_service_unavailable'})
    return lab


def _invoke(operation):
    try: return operation()
    except LabError as error: raise HTTPException(error.status_code, detail={'code': error.code}) from None
    except Exception: raise HTTPException(503, detail={'code': 'lab_storage_unavailable'}) from None


@router.get('/catalog')
def catalog(lab=Depends(service)): return _invoke(lab.catalog)


@router.post('/experiments', response_model=ExperimentView, status_code=202)
def create_experiment(payload: CreateExperiment, background: BackgroundTasks, lab=Depends(service)):
    record, created = _invoke(lambda: lab.reserve(str(payload.source_id), payload.scenario_id, str(payload.idempotency_key)))
    if created: background.add_task(lab.publish, record['experiment_id'])
    return record


@router.get('/experiments', response_model=ExperimentList)
def experiments(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), lab=Depends(service)):
    return _invoke(lambda: lab.list(limit, offset))


@router.get('/experiments/{experiment_id}', response_model=ExperimentView)
def experiment(experiment_id: UUID, lab=Depends(service)):
    return _invoke(lambda: lab.get(str(experiment_id)))


@router.post('/experiments/{experiment_id}/investigations', response_model=TaskRunView, status_code=202)
def investigate(experiment_id: UUID, payload: StartInvestigation, lab=Depends(service)):
    return _invoke(lambda: lab.investigate(str(experiment_id), payload.target_metric))
