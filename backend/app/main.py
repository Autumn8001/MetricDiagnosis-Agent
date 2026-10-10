"""MetricSleuth FastAPI application entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.api.task_routes import task_router

if TYPE_CHECKING:
    from app.api.task_service import InvestigationTasksService


def create_app(
    *, investigation_tasks_service: InvestigationTasksService | None = None,
    include_legacy_routes: bool = True,
) -> FastAPI:
    """Build the API without opening connections, starting workers or migrating.

    Persistent tasks are disabled unless a caller explicitly supplies a service
    with server-owned source bindings. This is not a production auth boundary.
    """

    application = FastAPI(
        title="MetricSleuth API",
        version="1.0.0",
        description="Evidence-driven Business Metric Investigation Agent REST API",
    )
    application.state.investigation_tasks_service = investigation_tasks_service

    @application.exception_handler(RequestValidationError)
    async def safe_task_validation(request: Request, exc: RequestValidationError):
        # Pydantic's default response echoes submitted values, including extra
        # fields. Never echo a mistakenly submitted connection string/secret.
        if request.url.path == "/api/investigations" or request.url.path.startswith("/api/investigations/"):
            return JSONResponse(status_code=422, content={"detail": {"code": "invalid_task_request"}})
        return await request_validation_exception_handler(request, exc)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
        ] + (["*"] if include_legacy_routes else []),
        allow_credentials=include_legacy_routes,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if include_legacy_routes:
        application.include_router(api_router)
    else:
        @application.get("/health")
        def local_task_health():
            return {"status": "ok", "mode": "local_tasks"}
    application.include_router(task_router)
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
