"""HTTP routes for persisted, source-bound investigation tasks."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from .task_schemas import (
    InvestigationTaskCreate,
    InvestigationSourcesResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskRunView,
)
from .task_service import InvestigationTasksService, TaskServiceError


task_router = APIRouter(tags=["Investigation Tasks"])


def get_task_service(request: Request) -> InvestigationTasksService:
    """Resolve an explicitly configured task service or fail closed."""

    service = getattr(request.app.state, "investigation_tasks_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "task_service_unavailable"},
        )
    return service


def _raise_http_error(exc: TaskServiceError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code},
    ) from exc


@task_router.get(
    "/api/investigation-sources",
    response_model=InvestigationSourcesResponse,
)
def list_investigation_sources(
    service: Annotated[InvestigationTasksService, Depends(get_task_service)],
) -> InvestigationSourcesResponse:
    """List server-configured source capabilities; this does not probe health."""

    try:
        return service.list_sources()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "source_catalog_unavailable"},
        ) from exc


@task_router.post(
    "/api/investigations",
    response_model=TaskRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_investigation(
    payload: InvestigationTaskCreate,
    service: Annotated[InvestigationTasksService, Depends(get_task_service)],
) -> TaskRunView:
    try:
        return service.submit(payload)
    except TaskServiceError as exc:
        _raise_http_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "task_storage_unavailable"},
        ) from exc


@task_router.get("/api/investigations", response_model=TaskListResponse)
def list_investigations(
    source_id: Annotated[str, Query(min_length=1, max_length=128)],
    service: Annotated[InvestigationTasksService, Depends(get_task_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskListResponse:
    try:
        return service.list_runs(source_id, limit=limit, offset=offset)
    except TaskServiceError as exc:
        _raise_http_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "task_storage_unavailable"},
        ) from exc


@task_router.get(
    "/api/investigations/{run_id}", response_model=TaskDetailResponse
)
def get_investigation(
    run_id: Annotated[str, Path(min_length=1, max_length=64)],
    source_id: Annotated[str, Query(min_length=1, max_length=128)],
    service: Annotated[InvestigationTasksService, Depends(get_task_service)],
) -> TaskDetailResponse:
    try:
        return service.get_run(run_id, source_id)
    except TaskServiceError as exc:
        _raise_http_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "task_storage_unavailable"},
        ) from exc


__all__ = ["get_task_service", "list_investigation_sources", "task_router"]
