"""Strict, safe HTTP contract for one source-bound metric observation."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Annotated, Final

from fastapi import APIRouter, HTTPException, Query, Request, status

from .metric_read_schemas import MetricReadResponse
from .metric_read_service import MetricReadService, MetricReadServiceError


metric_read_router = APIRouter(tags=["Metric Observations"])
_EXPECTED_KEYS: Final[frozenset[str]] = frozenset(
    {"source_id", "target_metric", "target_date"}
)
_CANONICAL_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _invalid_request() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "invalid_metric_request"},
    )


def get_metric_read_service(request: Request) -> MetricReadService:
    service = getattr(request.app.state, "metric_read_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "metric_service_unavailable"},
        )
    return service


@metric_read_router.get("/api/metrics/observation", response_model=MetricReadResponse)
def read_metric_observation(
    request: Request,
    source_id: Annotated[str, Query(min_length=1, max_length=128)],
    target_metric: Annotated[str, Query(min_length=1, max_length=128)],
    target_date: Annotated[str, Query(min_length=1, max_length=10)],
) -> MetricReadResponse:
    pairs = request.query_params.multi_items()
    if len(pairs) != 3 or {key for key, _ in pairs} != _EXPECTED_KEYS:
        raise _invalid_request()
    query: dict[str, str] = {}
    for key, value in pairs:
        if key in query:
            raise _invalid_request()
        query[key] = value

    # The typed arguments document the OpenAPI contract. Read the original
    # multi-value query above so duplicates cannot be hidden by FastAPI.
    del source_id, target_metric, target_date

    source_id = query["source_id"]
    target_metric = query["target_metric"]
    raw_date = query["target_date"]
    if (
        not source_id.strip()
        or len(source_id) > 128
        or not target_metric.strip()
        or len(target_metric) > 128
        or not _CANONICAL_DATE.fullmatch(raw_date)
    ):
        raise _invalid_request()
    try:
        target_date = date.fromisoformat(raw_date)
        if target_date.isoformat() != raw_date:
            raise ValueError
        target_date - timedelta(days=7)
    except (ValueError, OverflowError):
        raise _invalid_request() from None

    service = get_metric_read_service(request)
    try:
        return service.read(
            source_id=source_id,
            target_metric=target_metric,
            target_date=target_date,
        )
    except MetricReadServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code},
        ) from None


__all__ = ["get_metric_read_service", "metric_read_router"]
