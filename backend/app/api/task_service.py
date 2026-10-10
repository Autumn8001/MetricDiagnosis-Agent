"""Application boundary for source-bound, persisted investigation tasks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from app.data_sources.capabilities import (
    CapabilityContractError,
    DataSourceCapabilities,
    DataSourceDescriptor,
)
from app.persistence.task_execution_service import InvestigationTaskRequest
from app.persistence.task_read_repository import InvestigationTaskReadRepository
from app.persistence.worker import InvestigationWorker

from .task_schemas import (
    InvestigationSourceMetricCapability,
    InvestigationSourcesResponse,
    InvestigationSourceView,
    InvestigationTaskCreate,
    TaskDetailResponse,
    TaskListResponse,
    TaskRunView,
)


class TaskServiceError(Exception):
    """A safe, stable API failure classification."""

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TaskSourceBinding:
    """Immutable application allow-list entry for one source and environment."""

    descriptor: DataSourceDescriptor
    capabilities: DataSourceCapabilities
    data_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, DataSourceDescriptor):
            raise ValueError("descriptor must be a DataSourceDescriptor")
        if not isinstance(self.capabilities, DataSourceCapabilities):
            raise ValueError("capabilities must be DataSourceCapabilities")
        if self.capabilities.descriptor != self.descriptor:
            raise ValueError("capabilities descriptor must match source binding")
        if not isinstance(self.data_version, str) or not self.data_version.strip():
            raise ValueError("data_version must be a non-empty string")
        object.__setattr__(self, "data_version", self.data_version.strip())


class InvestigationTasksService:
    """Submit and read worker-backed investigations using configured sources only."""

    def __init__(
        self,
        connection_factory: object,
        worker: InvestigationWorker,
        sources: Sequence[TaskSourceBinding],
    ) -> None:
        if not callable(connection_factory):
            raise ValueError("connection_factory must be callable")
        if not callable(getattr(worker, "submit", None)):
            raise ValueError("worker must provide submit(request)")
        bindings: dict[str, TaskSourceBinding] = {}
        for binding in sources:
            if not isinstance(binding, TaskSourceBinding):
                raise ValueError("sources must contain TaskSourceBinding values")
            source_id = binding.descriptor.source_id
            if source_id in bindings:
                raise ValueError("source_id must be unique")
            bindings[source_id] = binding
        self._connection_factory = connection_factory
        self._worker = worker
        self._sources = bindings

    def list_sources(self) -> InvestigationSourcesResponse:
        """Return configured source identity and declared metric capabilities.

        This is an in-memory projection of the server-owned allow-list. It does
        not test connectivity, synchronization freshness, or database health.
        Fresh response models and lists are created on every call so callers
        cannot mutate the configured capability objects through the response.
        """

        items: list[InvestigationSourceView] = []
        for source_id in sorted(self._sources):
            binding = self._sources[source_id]
            descriptor = binding.descriptor
            metrics = [
                InvestigationSourceMetricCapability(
                    metric_id=metric_id,
                    supported=capability.supported,
                    grain=list(capability.grain),
                    dimensions=list(capability.dimensions),
                    unavailable_reason=capability.unavailable_reason,
                )
                for metric_id, capability in sorted(binding.capabilities.metrics.items())
            ]
            items.append(
                InvestigationSourceView(
                    source_id=descriptor.source_id,
                    display_name=descriptor.display_name,
                    provider=descriptor.provider.value,
                    environment=descriptor.environment.value,
                    data_version=binding.data_version,
                    metrics=metrics,
                )
            )
        return InvestigationSourcesResponse(items=items)

    def submit(self, payload: InvestigationTaskCreate) -> TaskRunView:
        binding = self._binding(payload.source_id)
        try:
            normalized_group_by, normalized_filter_dimensions = binding.capabilities.validate_query(
                payload.target_metric,
                group_by=payload.group_by,
                filters=payload.filters,
            )
        except CapabilityContractError as exc:
            raise TaskServiceError(400, "metric_or_dimensions_not_supported") from exc

        run_id = str(uuid4())
        query_reference = f"task:{uuid4()}"
        filters_by_normalized_dimension = {
            key.strip(): value for key, value in payload.filters.items()
        }
        request = InvestigationTaskRequest(
            run_id=run_id,
            descriptor=binding.descriptor,
            requested_metric=payload.target_metric,
            data_version=binding.data_version,
            query_reference=query_reference,
            parameters={
                "target_date": payload.target_date.isoformat(),
                "filters": {
                    dimension: filters_by_normalized_dimension[dimension]
                    for dimension in normalized_filter_dimensions
                },
                "group_by": list(normalized_group_by),
            },
        )
        try:
            created_run_id = self._worker.submit(request)
            if created_run_id != run_id:
                raise RuntimeError("worker returned a different task identifier")
            run = self._read(
                lambda reader: reader.get_run(
                    run_id,
                    binding.descriptor.source_id,
                    binding.descriptor.environment.value,
                )
            )
            if run is None:
                raise RuntimeError("submitted task was not readable")
            return self._run_view(run, binding)
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskServiceError(503, "task_storage_unavailable") from exc

    def list_runs(
        self, source_id: str, *, limit: int = 20, offset: int = 0
    ) -> TaskListResponse:
        binding = self._binding(source_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TaskServiceError(400, "invalid_pagination")
        if type(offset) is not int or offset < 0:
            raise TaskServiceError(400, "invalid_pagination")
        try:
            rows = self._read(
                lambda reader: reader.list_runs(
                    source_id,
                    binding.descriptor.environment.value,
                    limit=limit,
                    offset=offset,
                )
            )
            return TaskListResponse(
                items=[self._run_view(row, binding) for row in rows],
                limit=limit,
                offset=offset,
            )
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskServiceError(503, "task_storage_unavailable") from exc

    def get_run(self, run_id: str, source_id: str) -> TaskDetailResponse:
        binding = self._binding(source_id)
        try:
            details = self._read(
                lambda reader: reader.get_details(
                    run_id,
                    source_id,
                    binding.descriptor.environment.value,
                )
            )
            if details is None:
                raise TaskServiceError(404, "investigation_not_found")
            run = self._run_view(details["run"], binding)
            return TaskDetailResponse(
                run=run,
                tool_calls=details["tool_calls"],
                observations=details["observations"],
                evidence=details["evidence"],
                diagnoses=details["diagnoses"],
            )
        except TaskServiceError:
            raise
        except Exception as exc:
            raise TaskServiceError(503, "task_storage_unavailable") from exc

    def _binding(self, source_id: str) -> TaskSourceBinding:
        binding = self._sources.get(source_id)
        if binding is None:
            raise TaskServiceError(404, "source_not_found")
        return binding

    def _read(self, operation: object) -> object:
        connection = None
        try:
            connection = self._connection_factory()  # type: ignore[operator]
            if bool(getattr(connection, "autocommit", False)):
                raise RuntimeError("read connections must have autocommit disabled")
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            finally:
                cursor.close()
            result = operation(InvestigationTaskReadRepository(connection))  # type: ignore[operator]
            connection.commit()
            return result
        except BaseException:
            if connection is not None:
                try:
                    connection.rollback()
                except BaseException:
                    pass
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _run_view(row: dict[str, object], binding: TaskSourceBinding) -> TaskRunView:
        # The read repository controls the row projection; provider is supplied
        # from the configured allow-list, never from request or stored JSON.
        return TaskRunView(
            **row,
            provider=binding.descriptor.provider.value,
        )


__all__ = ["InvestigationTasksService", "TaskServiceError", "TaskSourceBinding"]
