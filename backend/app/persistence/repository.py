"""Small, parameterized repository for MetricSleuth application state.

The repository deliberately accepts an already-open DB-API connection.  It does
not know how to discover credentials, open a connection, run migrations, or
commit a transaction.  The service/worker that owns the connection is also the
owner of transaction boundaries.

This module is intentionally scoped to the ``app_state`` schema created by
``migrations/001_app_state.sql``.  It is a persistence adapter, not a second
domain model: Observation, Evidence, and Diagnosis remain the authorities for
their own invariants and are only mapped to storage rows here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
import re
from app.data_sources.capabilities import (
    DataSourceCapabilities,
    DataSourceDescriptor,
    SourceEnvironment,
    SourceProvider,
)
from app.diagnosis.models import Diagnosis
from app.evidence.models import Evidence
from app.observations.models import Observation
from app.persistence.models import (
    DataSourceState,
    InvalidRunTransitionError,
    PersistenceRepositoryError,
    PersistenceValidationError,
    RunState,
    RunStatus,
)


_SENSITIVE_KEY_PARTS = frozenset(
    {
        "password",
        "token",
        "secret",
        "apikey",
        "authorization",
        "connectionurl",
        "databaseurl",
    }
)
_SENSITIVE_KEY_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")
# Failure codes are an intentionally small machine-facing vocabulary.  They
# are not an exception message field: callers must classify a failure before
# crossing the persistence boundary, and the database receives only this
# bounded identifier.
_FAILURE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _identifier(value: object, field_name: str) -> str:
    """Return a trimmed identifier or fail before any SQL is executed."""

    if not isinstance(value, str) or not value.strip():
        raise PersistenceValidationError(
            f"Field '{field_name}' must be a non-empty string."
        )
    return value.strip()


def _optional_identifier(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field_name)


def _resolve_alias(
    primary: object,
    alias: object,
    field_name: str,
    alias_name: str,
) -> object:
    """Resolve a readable alias while rejecting contradictory callers."""

    if primary is not None and alias is not None:
        primary_clean = _identifier(primary, field_name)
        alias_clean = _identifier(alias, alias_name)
        if primary_clean != alias_clean:
            raise PersistenceValidationError(
                f"'{field_name}' and '{alias_name}' must identify the same value."
            )
        return primary_clean
    return primary if primary is not None else alias


def _enum_value(value: object, enum_type: type[Enum], field_name: str) -> str:
    if not isinstance(value, enum_type):
        raise PersistenceValidationError(
            f"Field '{field_name}' must be a {enum_type.__name__} enum member."
        )
    return str(value.value)


def _read_enum(value: object, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise PersistenceRepositoryError(
            f"Stored field '{field_name}' contains an invalid value: {value!r}."
        ) from exc


def _optional_text(value: object, field_name: str) -> str | None:
    return _optional_identifier(value, field_name)


def _failure_code(value: object) -> str:
    """Validate a safe, bounded failure classification before opening SQL."""

    if not isinstance(value, str) or not _FAILURE_CODE_RE.fullmatch(value):
        raise PersistenceValidationError(
            "failure_code must be 1-64 lowercase ASCII letters, digits, '_' or '-'."
        )
    return value


def _sensitive_key(key: str) -> bool:
    """Recognize credential-like key spellings, including camelCase names."""

    lowered = key.strip().lower()
    compact = _SENSITIVE_KEY_SEPARATOR_RE.sub("", lowered)
    if compact in _SENSITIVE_KEY_PARTS:
        return True

    # ``access_token``, ``api_key`` and ``database_url`` are covered after
    # compaction.  Prefix/suffix checks also cover ``clientSecret`` and
    # ``password_hash`` without rejecting ordinary values such as ``tokenizer``
    # only when the key itself clearly carries a credential term.
    return any(
        compact.startswith(part) or compact.endswith(part)
        for part in _SENSITIVE_KEY_PARTS
    )


def _json_ready(value: object, path: str) -> object:
    """Normalize supported domain values and reject unsafe JSON recursively."""

    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise PersistenceValidationError(
                    f"JSON object keys at '{path}' must be non-empty strings."
                )
            key = raw_key.strip()
            if _sensitive_key(key):
                raise PersistenceValidationError(
                    f"Sensitive key '{key}' is not allowed in '{path}'."
                )
            if key in normalized:
                raise PersistenceValidationError(
                    f"Duplicate JSON key '{key}' at '{path}'."
                )
            normalized[key] = _json_ready(raw_value, f"{path}.{key}")
        return normalized

    if isinstance(value, (list, tuple)):
        return [_json_ready(item, f"{path}[{index}]") for index, item in enumerate(value)]

    if isinstance(value, Enum):
        return _json_ready(value.value, path)

    # PostgreSQL numeric/date columns accept these domain types directly.  For
    # JSONB snapshots, use stable textual representations instead of relying on
    # a driver-specific JSON adapter.
    if isinstance(value, (Decimal, datetime, date)):
        return value.isoformat() if isinstance(value, (datetime, date)) else str(value)

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    raise PersistenceValidationError(
        f"Value at '{path}' of type {type(value).__name__} is not JSON serializable."
    )


def _json_parameter(value: object, field_name: str, *, object_only: bool = False) -> str:
    normalized = _json_ready(value, field_name)
    if object_only and not isinstance(normalized, dict):
        raise PersistenceValidationError(f"Field '{field_name}' must be a JSON object.")
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise PersistenceValidationError(
            f"Field '{field_name}' must be JSON serializable."
        ) from exc


def _json_object(value: object | None, field_name: str) -> str:
    return _json_parameter({} if value is None else value, field_name, object_only=True)


def _capabilities_payload(
    value: DataSourceCapabilities | Mapping[str, object] | None,
    descriptor: DataSourceDescriptor,
) -> str:
    if value is None:
        raw: Mapping[str, object] = {}
    elif isinstance(value, DataSourceCapabilities):
        if value.descriptor.source_id != descriptor.source_id:
            raise PersistenceValidationError(
                "Capabilities descriptor source_id does not match data source."
            )
        if value.descriptor.environment != descriptor.environment:
            raise PersistenceValidationError(
                "Capabilities descriptor environment does not match data source."
            )
        raw = {
            metric_id: {
                "supported": capability.supported,
                "grain": capability.grain,
                "dimensions": capability.dimensions,
                **(
                    {"unavailable_reason": capability.unavailable_reason}
                    if capability.unavailable_reason is not None
                    else {}
                ),
            }
            for metric_id, capability in value.metrics.items()
        }
    elif isinstance(value, Mapping):
        raw = value
    else:
        raise PersistenceValidationError(
            "Field 'capabilities' must be a mapping or DataSourceCapabilities."
        )
    return _json_object(raw, "capabilities")


def _run_id(
    investigation_run_id: object,
    alias: object,
) -> str:
    resolved = _resolve_alias(
        investigation_run_id,
        alias,
        "investigation_run_id",
        "run_id",
    )
    return _identifier(resolved, "investigation_run_id")


def _required_source(source_id: object, environment: object) -> tuple[str, str]:
    source = _identifier(source_id, "source_id")
    env = _enum_value(environment, SourceEnvironment, "environment")
    return source, env


@dataclass(frozen=True)
class InvestigationRunSummary:
    """Minimal historical run view returned by the repository."""

    investigation_run_id: str
    source_id: str
    environment: SourceEnvironment
    status: RunStatus
    requested_metric: str | None
    data_version: str | None
    query_reference: str | None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def run_id(self) -> str:
        return self.investigation_run_id

    @property
    def current_status(self) -> RunStatus:
        return self.status

    def as_dict(self) -> dict[str, object]:
        """Return an API-friendly primitive snapshot without sensitive values."""

        return {
            "investigation_run_id": self.investigation_run_id,
            "source_id": self.source_id,
            "environment": self.environment.value,
            "status": self.status.value,
            "requested_metric": self.requested_metric,
            "data_version": self.data_version,
            "query_reference": self.query_reference,
            "requested_at": self.requested_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ApplicationStateRepository:
    """Parameterized persistence adapter for the ``app_state`` schema.

    ``connection`` must already be established by the caller.  The repository
    never opens a connection, stores a URL, commits, rolls back, or executes a
    migration.  DB-API errors from ``execute`` are intentionally allowed to
    propagate so the transaction owner can decide how to handle them.
    """

    def __init__(self, connection: object) -> None:
        if connection is None or not callable(getattr(connection, "cursor", None)):
            raise PersistenceValidationError(
                "ApplicationStateRepository requires an established DB-API connection."
            )
        self._connection = connection

    @staticmethod
    def _close_cursor(cursor: object) -> None:
        close = getattr(cursor, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # Cursor cleanup must not mask the execute/fetch exception that
                # the transaction owner needs to see.
                pass

    def _execute(self, sql: str, params: Sequence[object]) -> None:
        cursor = self._connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute(sql, tuple(params))  # type: ignore[attr-defined]
        finally:
            self._close_cursor(cursor)

    def upsert_data_source(
        self,
        source: DataSourceDescriptor | str | None = None,
        provider: SourceProvider | None = None,
        environment: SourceEnvironment | None = None,
        display_name: str | None = None,
        *,
        source_id: str | None = None,
        capabilities: DataSourceCapabilities | Mapping[str, object] | None = None,
        data_version: str | None = None,
        state: DataSourceState = DataSourceState.ACTIVE,
    ) -> DataSourceDescriptor:
        """Insert or update a non-sensitive data-source identity record.

        ``source`` may be an existing ``DataSourceDescriptor`` or a source ID.
        Keyword ``source_id`` is accepted as a readable API alias for callers
        that build records from primitive request fields.
        """

        descriptor: DataSourceDescriptor
        if isinstance(source, DataSourceDescriptor):
            if source_id is not None and _identifier(source_id, "source_id") != source.source_id:
                raise PersistenceValidationError(
                    "source_id does not match the supplied DataSourceDescriptor."
                )
            if provider is not None and provider is not source.provider:
                raise PersistenceValidationError("provider conflicts with descriptor.")
            if environment is not None and environment is not source.environment:
                raise PersistenceValidationError("environment conflicts with descriptor.")
            if display_name is not None and _identifier(display_name, "display_name") != source.display_name:
                raise PersistenceValidationError("display_name conflicts with descriptor.")
            descriptor = source
        else:
            resolved_source_id = source_id if source_id is not None else source
            if resolved_source_id is None:
                raise PersistenceValidationError("A source_id is required.")
            if source_id is not None and source is not None:
                if _identifier(source_id, "source_id") != _identifier(source, "source"):
                    raise PersistenceValidationError("source and source_id must match.")
            if provider is None or environment is None or display_name is None:
                raise PersistenceValidationError(
                    "provider, environment, and display_name are required for a new source."
                )
            descriptor = DataSourceDescriptor(
                source_id=_identifier(resolved_source_id, "source_id"),
                display_name=_identifier(display_name, "display_name"),
                provider=provider,
                environment=environment,
            )

        provider_value = _enum_value(descriptor.provider, SourceProvider, "provider")
        environment_value = _enum_value(
            descriptor.environment, SourceEnvironment, "environment"
        )
        state_value = _enum_value(state, DataSourceState, "state")
        data_version_value = _optional_text(data_version, "data_version")
        capabilities_json = _capabilities_payload(capabilities, descriptor)

        sql = """
            INSERT INTO app_state.data_sources (
                source_id, provider, environment, display_name, state,
                capabilities, data_version
            ) VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb), %s)
            ON CONFLICT (source_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                environment = EXCLUDED.environment,
                display_name = EXCLUDED.display_name,
                state = EXCLUDED.state,
                capabilities = EXCLUDED.capabilities,
                data_version = EXCLUDED.data_version,
                updated_at = now()
        """
        self._execute(
            sql,
            (
                descriptor.source_id,
                provider_value,
                environment_value,
                descriptor.display_name,
                state_value,
                capabilities_json,
                data_version_value,
            ),
        )
        return descriptor

    def create_investigation_run(
        self,
        investigation_run_id: str | None = None,
        source_id: str | None = None,
        environment: SourceEnvironment | None = None,
        *,
        run_id: str | None = None,
        requested_metric: str | None = None,
        data_version: str | None = None,
        query_reference: str | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> InvestigationRunSummary:
        """Create a queued investigation run and leave transaction ownership outside."""

        resolved_run_id = _run_id(investigation_run_id, run_id)
        source, environment_value = _required_source(source_id, environment)
        requested_metric_value = _optional_text(requested_metric, "requested_metric")
        data_version_value = _optional_text(data_version, "data_version")
        query_reference_value = _optional_text(query_reference, "query_reference")
        parameters_json = _json_object(parameters, "parameters")

        sql = """
            INSERT INTO app_state.investigation_runs (
                investigation_run_id, source_id, environment, status,
                requested_metric, data_version, query_reference, parameters
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
        """
        self._execute(
            sql,
            (
                resolved_run_id,
                source,
                environment_value,
                RunStatus.QUEUED.value,
                requested_metric_value,
                data_version_value,
                query_reference_value,
                parameters_json,
            ),
        )
        return InvestigationRunSummary(
            investigation_run_id=resolved_run_id,
            source_id=source,
            environment=SourceEnvironment(environment_value),
            status=RunStatus.QUEUED,
            requested_metric=requested_metric_value,
            data_version=data_version_value,
            query_reference=query_reference_value,
        )

    def transition_investigation_run(
        self,
        investigation_run_id: str | None = None,
        target_status: RunStatus | None = None,
        *,
        run_id: str | None = None,
        status: RunStatus | None = None,
    ) -> RunStatus:
        """Atomically perform one legal lifecycle transition.

        The current state is encoded in the conditional ``WHERE`` clause.  A
        zero-row update means the run is absent or was changed concurrently;
        in either case the caller must not claim the transition succeeded.
        """

        resolved_run_id = _run_id(investigation_run_id, run_id)
        if target_status is not None and status is not None and target_status is not status:
            raise PersistenceValidationError("target_status and status must match.")
        resolved_target = target_status if target_status is not None else status
        if not isinstance(resolved_target, RunStatus):
            raise PersistenceValidationError(
                "target_status must be a RunStatus enum member."
            )

        predecessors = tuple(
            source_state
            for source_state in RunStatus
            if RunState(source_state).can_transition_to(resolved_target)
        )
        if not predecessors:
            raise InvalidRunTransitionError(
                f"No legal run state can transition to '{resolved_target.value}'."
            )

        predecessor_placeholders = ", ".join("%s" for _ in predecessors)
        terminal_placeholders = ", ".join("%s" for _ in RunStatus if _.is_terminal)
        sql = f"""
            UPDATE app_state.investigation_runs
            SET status = %s,
                started_at = CASE WHEN %s = %s
                    THEN COALESCE(started_at, now()) ELSE started_at END,
                finished_at = CASE WHEN %s IN ({terminal_placeholders})
                    THEN COALESCE(finished_at, now()) ELSE finished_at END
            WHERE investigation_run_id = %s
              AND status IN ({predecessor_placeholders})
        """
        params: list[object] = [
            resolved_target.value,
            resolved_target.value,
            RunStatus.RUNNING.value,
            resolved_target.value,
            *(item.value for item in RunStatus if item.is_terminal),
            resolved_run_id,
            *(item.value for item in predecessors),
        ]
        cursor = self._connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute(sql, tuple(params))  # type: ignore[attr-defined]
            rowcount = getattr(cursor, "rowcount", None)
        finally:
            self._close_cursor(cursor)
        if rowcount == 0:
            raise PersistenceRepositoryError(
                f"Investigation run '{resolved_run_id}' was not in a state that can "
                f"transition to '{resolved_target.value}', or it does not exist."
            )
        return resolved_target

    # Short alias for callers that use the generic run vocabulary.
    transition_run = transition_investigation_run

    def fail_investigation_run(
        self,
        investigation_run_id: str | None = None,
        *,
        run_id: str | None = None,
        failure_code: str,
    ) -> RunStatus:
        """Atomically archive a controlled failure for a queued/running run.

        Only a bounded machine classification is accepted.  The conditional
        update is deliberately restricted to non-terminal predecessors so a
        late worker cannot overwrite a succeeded, failed, or cancelled run.
        This method executes no transaction boundary; the caller owns commit
        and rollback decisions.
        """

        resolved_run_id = _run_id(investigation_run_id, run_id)
        clean_failure_code = _failure_code(failure_code)
        failure_details = _json_object({"code": clean_failure_code}, "failure_details")

        sql = """
            UPDATE app_state.investigation_runs
            SET status = %s,
                failure_details = CAST(%s AS jsonb),
                finished_at = now()
            WHERE investigation_run_id = %s
              AND status IN (%s, %s)
        """
        cursor = self._connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute(  # type: ignore[attr-defined]
                sql,
                (
                    RunStatus.FAILED.value,
                    failure_details,
                    resolved_run_id,
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                ),
            )
            rowcount = getattr(cursor, "rowcount", None)
        finally:
            self._close_cursor(cursor)
        if rowcount == 0:
            raise PersistenceRepositoryError(
                f"Investigation run '{resolved_run_id}' was not queued/running, "
                "or it does not exist."
            )
        return RunStatus.FAILED

    # Explicit alias for callers that prefer state-oriented terminology.
    mark_investigation_run_failed = fail_investigation_run

    def record_tool_call(
        self,
        tool_call_id: str,
        investigation_run_id: str | None = None,
        source_id: str | None = None,
        environment: SourceEnvironment | None = None,
        tool_name: str | None = None,
        *,
        run_id: str | None = None,
        status: RunStatus = RunStatus.QUEUED,
        arguments: Mapping[str, object] | None = None,
        dimensions: Mapping[str, object] | None = None,
        filters: Mapping[str, object] | None = None,
        data_version: str | None = None,
        query_reference: str | None = None,
        result_reference: str | None = None,
    ) -> str:
        """Persist a tool invocation trace without persisting credentials."""

        clean_tool_call_id = _identifier(tool_call_id, "tool_call_id")
        resolved_run_id = _run_id(investigation_run_id, run_id)
        source, environment_value = _required_source(source_id, environment)
        clean_tool_name = _identifier(tool_name, "tool_name")
        status_value = _enum_value(status, RunStatus, "status")
        data_version_value = _optional_text(data_version, "data_version")
        query_reference_value = _optional_text(query_reference, "query_reference")
        result_reference_value = _optional_text(result_reference, "result_reference")
        arguments_json = _json_object(arguments, "arguments")
        dimensions_json = _json_object(dimensions, "dimensions")
        filters_json = _json_object(filters, "filters")

        sql = """
            INSERT INTO app_state.tool_calls (
                tool_call_id, investigation_run_id, source_id, environment,
                tool_name, status, arguments, dimensions, filters,
                data_version, query_reference, result_reference
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                CAST(%s AS jsonb), CAST(%s AS jsonb), CAST(%s AS jsonb),
                %s, %s, %s
            )
        """
        self._execute(
            sql,
            (
                clean_tool_call_id,
                resolved_run_id,
                source,
                environment_value,
                clean_tool_name,
                status_value,
                arguments_json,
                dimensions_json,
                filters_json,
                data_version_value,
                query_reference_value,
                result_reference_value,
            ),
        )
        return clean_tool_call_id

    def record_observation(
        self,
        observation: Observation,
        investigation_run_id: str | None = None,
        source_id: str | None = None,
        environment: SourceEnvironment | None = None,
        *,
        run_id: str | None = None,
        data_version: str | None = None,
    ) -> str:
        """Persist one Observation with its tool, source, and query reference."""

        if not isinstance(observation, Observation):
            raise PersistenceValidationError("observation must be an Observation instance.")
        resolved_run_id = _run_id(investigation_run_id, run_id)
        source, environment_value = _required_source(source_id, environment)
        data_version_value = _optional_text(data_version, "data_version")

        sql = """
            INSERT INTO app_state.observations (
                observation_id, investigation_run_id, tool_call_id,
                source_id, environment, metric, status, source_status,
                current_period_start, current_period_end,
                baseline_period_start, baseline_period_end,
                filters, group_by, dimensions,
                current_value, baseline_value, relative_change, unit,
                sample_size, data_version, query_reference,
                error_code, error_message, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                CAST(%s AS jsonb), CAST(%s AS jsonb), CAST(%s AS jsonb),
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """
        self._execute(
            sql,
            (
                observation.observation_id,
                resolved_run_id,
                observation.tool_call_id,
                source,
                environment_value,
                observation.metric,
                observation.status.value,
                observation.source_status,
                observation.current_period.start_date,
                observation.current_period.end_date,
                observation.baseline_period.start_date,
                observation.baseline_period.end_date,
                _json_object(observation.filters, "observation.filters"),
                _json_parameter(observation.group_by, "observation.group_by"),
                _json_object(observation.dimensions, "observation.dimensions"),
                observation.current_value,
                observation.baseline_value,
                observation.relative_change,
                observation.unit,
                observation.sample_size,
                data_version_value,
                observation.query_or_result_reference,
                observation.error_code,
                observation.error_message,
                observation.created_at,
            ),
        )
        return observation.observation_id

    def record_evidence(
        self,
        evidence: Evidence,
        investigation_run_id: str | None = None,
        source_id: str | None = None,
        environment: SourceEnvironment | None = None,
        *,
        run_id: str | None = None,
        data_version: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> str:
        """Persist Evidence promoted from an Observation."""

        if not isinstance(evidence, Evidence):
            raise PersistenceValidationError("evidence must be an Evidence instance.")
        resolved_run_id = _run_id(investigation_run_id, run_id)
        source, environment_value = _required_source(source_id, environment)
        data_version_value = _optional_text(data_version, "data_version")
        if payload is None:
            payload = {
                "tool_name": evidence.tool_name,
                "tool_call_id": evidence.tool_call_id,
                "group_by": evidence.group_by,
                "current_value": evidence.current_value,
                "baseline_value": evidence.baseline_value,
                "relative_change": evidence.relative_change,
                "unit": evidence.unit,
                "sample_size": evidence.sample_size,
                "source_status": evidence.source_status,
                "error_code": evidence.error_code,
                "error_message": evidence.error_message,
            }

        sql = """
            INSERT INTO app_state.evidence (
                evidence_id, investigation_run_id, observation_id,
                source_id, environment, role, observation_status, metric,
                dimensions, filters, query_reference, data_version, payload
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                CAST(%s AS jsonb), CAST(%s AS jsonb), %s, %s,
                CAST(%s AS jsonb)
            )
        """
        self._execute(
            sql,
            (
                evidence.evidence_id,
                resolved_run_id,
                evidence.observation_id,
                source,
                environment_value,
                evidence.role.value,
                evidence.observation_status.value,
                evidence.metric,
                _json_object(evidence.dimensions, "evidence.dimensions"),
                _json_object(evidence.filters, "evidence.filters"),
                evidence.query_or_result_reference,
                data_version_value,
                _json_object(payload, "evidence.payload"),
            ),
        )
        return evidence.evidence_id

    def record_diagnosis(
        self,
        diagnosis: Diagnosis,
        investigation_run_id: str | None = None,
        source_id: str | None = None,
        environment: SourceEnvironment | None = None,
        *,
        run_id: str | None = None,
        data_version: str | None = None,
        query_reference: str | None = None,
    ) -> str:
        """Persist a Diagnosis and its normalized Evidence links in order."""

        if not isinstance(diagnosis, Diagnosis):
            raise PersistenceValidationError("diagnosis must be a Diagnosis instance.")
        resolved_run_id = _run_id(investigation_run_id, run_id)
        source, environment_value = _required_source(source_id, environment)
        data_version_value = _optional_text(data_version, "data_version")
        query_reference_value = _optional_text(query_reference, "query_reference")

        if diagnosis.change is None:
            change_payload: Mapping[str, object] = {}
        else:
            change_payload = {
                "current_value": diagnosis.change.current_value,
                "baseline_value": diagnosis.change.baseline_value,
                "relative_change": diagnosis.change.relative_change,
                "unit": diagnosis.change.unit,
                "evidence_id": diagnosis.change.evidence_id,
            }

        insert_sql = """
            INSERT INTO app_state.diagnoses (
                diagnosis_id, investigation_run_id, source_id, environment,
                status, target_metric, primary_driver, affected_scope,
                change, evidence_ids, confidence, limitations,
                data_version, query_reference, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                CAST(%s AS jsonb), CAST(%s AS jsonb), CAST(%s AS jsonb),
                %s, CAST(%s AS jsonb), %s, %s, %s
            )
        """
        link_sql = """
            INSERT INTO app_state.diagnosis_evidence (
                diagnosis_id, investigation_run_id, evidence_id
            ) VALUES (%s, %s, %s)
        """
        cursor = self._connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute(  # type: ignore[attr-defined]
                insert_sql,
                (
                    diagnosis.diagnosis_id,
                    resolved_run_id,
                    source,
                    environment_value,
                    diagnosis.status.value,
                    diagnosis.target_metric,
                    diagnosis.primary_driver,
                    _json_object(diagnosis.affected_scope, "diagnosis.affected_scope"),
                    _json_object(change_payload, "diagnosis.change"),
                    _json_parameter(diagnosis.evidence_ids, "diagnosis.evidence_ids"),
                    diagnosis.confidence,
                    _json_parameter(diagnosis.limitations, "diagnosis.limitations"),
                    data_version_value,
                    query_reference_value,
                    diagnosis.created_at,
                ),
            )
            for evidence_id in diagnosis.evidence_ids:
                cursor.execute(  # type: ignore[attr-defined]
                    link_sql,
                    (diagnosis.diagnosis_id, resolved_run_id, evidence_id),
                )
        finally:
            self._close_cursor(cursor)
        return diagnosis.diagnosis_id

    def get_investigation_run(
        self,
        investigation_run_id: str | None = None,
        *,
        run_id: str | None = None,
    ) -> InvestigationRunSummary | None:
        """Read one run's status and source/version summary, if it exists."""

        resolved_run_id = _run_id(investigation_run_id, run_id)
        sql = """
            SELECT investigation_run_id, source_id, environment, status,
                   requested_metric, data_version, query_reference,
                   requested_at, started_at, finished_at
            FROM app_state.investigation_runs
            WHERE investigation_run_id = %s
        """
        cursor = self._connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute(sql, (resolved_run_id,))  # type: ignore[attr-defined]
            row = cursor.fetchone()  # type: ignore[attr-defined]
        finally:
            self._close_cursor(cursor)
        if row is None:
            return None

        def value_at(index: int, key: str) -> object:
            if isinstance(row, Mapping):
                try:
                    return row[key]
                except KeyError as exc:
                    raise PersistenceRepositoryError(
                        f"Stored run row is missing column '{key}'."
                    ) from exc
            try:
                return row[index]
            except (IndexError, KeyError, TypeError) as exc:
                raise PersistenceRepositoryError(
                    f"Stored run row is missing column '{key}'."
                ) from exc

        try:
            return InvestigationRunSummary(
                investigation_run_id=_identifier(
                    value_at(0, "investigation_run_id"), "investigation_run_id"
                ),
                source_id=_identifier(value_at(1, "source_id"), "source_id"),
                environment=_read_enum(
                    value_at(2, "environment"), SourceEnvironment, "environment"
                ),
                status=_read_enum(value_at(3, "status"), RunStatus, "status"),
                requested_metric=_optional_identifier(
                    value_at(4, "requested_metric"), "requested_metric"
                ),
                data_version=_optional_identifier(
                    value_at(5, "data_version"), "data_version"
                ),
                query_reference=_optional_identifier(
                    value_at(6, "query_reference"), "query_reference"
                ),
                requested_at=value_at(7, "requested_at"),  # type: ignore[arg-type]
                started_at=value_at(8, "started_at"),  # type: ignore[arg-type]
                finished_at=value_at(9, "finished_at"),  # type: ignore[arg-type]
            )
        except PersistenceRepositoryError:
            raise
        except PersistenceValidationError as exc:
            raise PersistenceRepositoryError("Stored run row violates its contract.") from exc

    # Alias for future history APIs that use the shorter summary vocabulary.
    get_run_summary = get_investigation_run


__all__ = [
    "ApplicationStateRepository",
    "InvestigationRunSummary",
]
