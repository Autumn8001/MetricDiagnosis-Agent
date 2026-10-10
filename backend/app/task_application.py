"""Explicit local task application wiring. No migrations or scenario injection."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

from app.api.task_service import InvestigationTasksService, TaskSourceBinding
from app.data_sources.capabilities import DataSourceDescriptor, SourceEnvironment, SourceProvider
from app.data_sources.semantic_adapter import build_capabilities_from_registry
from app.metrics.registry import MetricRegistry
from app.persistence.worker import InvestigationWorker


class TaskApplicationConfigError(ValueError):
    """Safe configuration classification, never containing submitted values."""


@dataclass(frozen=True)
class TaskApplicationConfig:
    state_database_url: str = field(repr=False)
    analytics_database_url: str = field(repr=False)
    profile: str
    source_id: str
    data_version: str
    model: str
    max_tool_calls: int = 8
    max_turns: int = 10

    def __post_init__(self):
        if self.profile not in {"synthetic", "olist_validation"}:
            raise TaskApplicationConfigError("unsupported_task_profile")
        for value in (self.source_id, self.data_version, self.model):
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise TaskApplicationConfigError("invalid_task_configuration")
        for value, maximum in ((self.max_tool_calls, 8), (self.max_turns, 10)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise TaskApplicationConfigError("invalid_task_budget")
        # This entry point is deliberately local-only until production controls
        # exist. Do not silently fall back to the legacy DATABASE_URL/.env.
        for value in (self.state_database_url, self.analytics_database_url):
            try:
                parsed = urlsplit(value)
                valid = (parsed.scheme in {"postgres", "postgresql"}
                         and parsed.hostname in {"localhost", "127.0.0.1"}
                         and parsed.path not in {"", "/"}
                         and not parsed.query and not parsed.fragment)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise TaskApplicationConfigError("local_database_configuration_required")

    @classmethod
    def from_environment(cls):
        names = (
            "METRICSLEUTH_STATE_DATABASE_URL", "METRICSLEUTH_ANALYTICS_DATABASE_URL",
            "METRICSLEUTH_TASK_PROFILE", "METRICSLEUTH_TASK_SOURCE_ID",
            "METRICSLEUTH_TASK_DATA_VERSION", "METRICSLEUTH_TASK_MODEL",
        )
        values = [os.environ.get(name, "").strip() for name in names]
        if not all(values):
            raise TaskApplicationConfigError("task_configuration_missing")
        try:
            calls = int(os.environ.get("METRICSLEUTH_TASK_MAX_TOOL_CALLS", "8"))
            turns = int(os.environ.get("METRICSLEUTH_TASK_MAX_TURNS", "10"))
        except ValueError:
            raise TaskApplicationConfigError("invalid_task_budget") from None
        return cls(*values, max_tool_calls=calls, max_turns=turns)


def _connection_factory(database_url):
    def connect():
        import psycopg
        try:
            return psycopg.connect(database_url, autocommit=False, connect_timeout=5)
        except Exception:
            raise RuntimeError("task_database_unavailable") from None
    return connect


def build_task_application(config: TaskApplicationConfig, *, diagnosis_runner=None):
    """Build service/worker without connecting or performing any SQL/model call."""
    from app.persistence.source_runner import SourceInvestigationRunner
    root = Path(__file__).resolve().parents[2]
    is_synthetic = config.profile == "synthetic"
    registry = MetricRegistry.from_yaml(root / "configs" / (
        "metrics.yaml" if is_synthetic else "olist_validation_metrics.yaml"
    ))
    descriptor = DataSourceDescriptor(
        source_id=config.source_id,
        display_name="Synthetic sandbox" if is_synthetic else "Olist static validation",
        provider=SourceProvider.SYNTHETIC if is_synthetic else SourceProvider.OLIST,
        environment=SourceEnvironment.SANDBOX if is_synthetic else SourceEnvironment.VALIDATION,
    )
    binding = TaskSourceBinding(descriptor, build_capabilities_from_registry(registry, descriptor), config.data_version)
    state_factory = _connection_factory(config.state_database_url)
    kwargs = {} if diagnosis_runner is None else {"diagnosis_runner": diagnosis_runner}
    runner = SourceInvestigationRunner(
        binding=binding, registry=registry,
        analytics_connection_factory=_connection_factory(config.analytics_database_url),
        model=config.model, max_tool_calls=config.max_tool_calls,
        max_turns=config.max_turns, **kwargs,
    )
    worker = InvestigationWorker(state_factory, runner, expected_source=descriptor)
    service = InvestigationTasksService(state_factory, worker, (binding,))
    return service, worker


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local persisted investigations; no automatic migrations")
    parser.add_argument("mode", choices=("api", "worker"))
    parser.add_argument("--once", action="store_true", help="Worker executes at most one task")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or (args.mode == "api" and args.once):
        parser.error("invalid local startup arguments")
    try:
        config = TaskApplicationConfig.from_environment()
        if args.mode == "worker" and not os.environ.get("OPENAI_API_KEY", "").strip():
            raise TaskApplicationConfigError("model_credentials_missing")
        service, worker = build_task_application(config)
        if args.mode == "api":
            import uvicorn
            from app.main import create_app
            app = create_app(investigation_tasks_service=service, include_legacy_routes=False)
            uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
        else:
            while True:
                run_id = worker.run_once()
                if args.once:
                    print("task_processed" if run_id is not None else "no_task_available")
                    return 0
                time.sleep(2)
    except KeyboardInterrupt:
        return 0
    except TaskApplicationConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("task_application_failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
