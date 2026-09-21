"""Live autonomous investigation verification script for Phase 6 / LIVE-002.

Executes the official OpenAI Agents SDK runtime against real PostgreSQL warehouse
data across benchmark development scenarios (canonical, traffic, no_anomaly)
using a unified, domain-neutral investigation prompt. Validates autonomous dynamic
branching, strict budget containment, observation-to-diagnosis evidence traceability,
and expected diagnostic outcomes.

Supports both direct runtime execution and the in-process API service execution path.
"""

from __future__ import annotations

import argparse
import datetime
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import psycopg

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BACKEND_ROOT.parent if (BACKEND_ROOT / "backend").exists() else BACKEND_ROOT
if (BACKEND_ROOT / "configs").exists():
    REPOSITORY_ROOT = BACKEND_ROOT
elif (BACKEND_ROOT.parent / "configs").exists():
    REPOSITORY_ROOT = BACKEND_ROOT.parent

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent_runtime.diagnosis_runtime import (
    DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
    DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
    EvidenceDrivenRunSummary,
    run_evidence_driven_diagnosis,
)
from app.analytics.tools import AnalyticsTools
from app.api.service import resolve_live_model
from app.diagnosis.models import Diagnosis, DiagnosisStatus
from app.metrics.registry import MetricRegistry


AVAILABLE_SCENARIOS = ("canonical", "traffic", "no_anomaly")
DEFAULT_SCENARIOS = "canonical,traffic,no_anomaly"
LIVE_ARTIFACT_SCHEMA = "metricsleuth.live_investigation"
LIVE_ARTIFACT_VERSION = 1
NEUTRAL_PROMPT = (
    "Please investigate the sales anomaly for 2026-01-31 compared to the "
    "previous_7_days baseline. Available dimensions are marketplace, asin, "
    "and traffic_source. Use the controlled analytics tools to identify the "
    "primary data driver and affected segment if any, cite the resulting "
    "observations, and conclude with the structured diagnosis intent."
)


_SECRET_FIELD_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "base_url",
    "connection_string",
    "database_url",
    "password",
    "secret",
    "token",
)


def _is_secret_field(field_name: str) -> bool:
    normalized = field_name.strip().lower().replace("-", "_")
    return any(token in normalized for token in _SECRET_FIELD_TOKENS)


def _json_safe(value: Any, *, field_path: str = "artifact") -> Any:
    """Convert explicitly supported values without stringifying arbitrary objects.

    Live artifacts are an audit boundary, not a general-purpose object dump.  The
    allowlist below supports the values produced by the runtime while rejecting
    unknown objects and secret-looking fields before they can reach disk.
    """
    if isinstance(value, Mapping):
        safe_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field_path} mapping keys must be strings.")
            if _is_secret_field(key):
                raise ValueError(f"Secret-looking field is not allowed in artifact: {field_path}.{key}")
            safe_mapping[key] = _json_safe(item, field_path=f"{field_path}.{key}")
        return safe_mapping
    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item, field_path=f"{field_path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"Non-finite Decimal is not allowed in artifact: {field_path}")
        return str(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite float is not allowed in artifact: {field_path}")
        return value
    raise TypeError(
        f"Unsupported artifact value at {field_path}: {type(value).__name__}. "
        "Refusing implicit stringification."
    )


def _value_from(source: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(field_name, default)
    return getattr(source, field_name, default)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _observation_ids_from_trace_entry(entry: Any) -> list[str]:
    raw_ids = _value_from(entry, "observation_ids")
    if raw_ids is None:
        raw_id = _value_from(entry, "observation_id")
        if raw_id is None:
            return []
        if not isinstance(raw_id, str):
            raise TypeError("Trace observation_id must be a string.")
        raw_ids = raw_id.split(",")
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    observation_ids: list[str] = []
    for item in raw_ids:
        if not isinstance(item, str):
            raise TypeError("Trace observation_ids must contain only strings.")
        if item.strip():
            observation_ids.append(item.strip())
    return observation_ids


def _trace_payload(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize direct SDK or API trace records into a public artifact shape."""
    summary = result.get("summary")
    if summary is not None:
        investigation = _value_from(summary, "investigation")
        entries = _value_from(investigation, "tool_trace", ())
    else:
        entries = result.get("call_log", ())

    payload: list[dict[str, Any]] = []
    for step_number, entry in enumerate(entries, 1):
        arguments = _value_from(entry, "arguments")
        if arguments is None:
            arguments = _value_from(entry, "kwargs", {})
        tool_name = _value_from(entry, "tool_name")
        if tool_name is None:
            tool_name = _value_from(entry, "operation")
        call_id = _value_from(entry, "tool_call_id")
        if call_id is None:
            call_id = f"unavailable-step-{step_number}"
        payload.append(
            {
                "step_number": step_number,
                "tool_call_id": call_id,
                "tool_name": tool_name,
                "arguments": arguments or {},
                "observation_ids": _observation_ids_from_trace_entry(entry),
            }
        )
    return payload


def _evidence_payload(evidence: Any) -> dict[str, Any]:
    """Select the Evidence contract fields; never dump arbitrary model fields."""
    return {
        "evidence_id": _value_from(evidence, "evidence_id"),
        "observation_id": _value_from(evidence, "observation_id"),
        "metric": _value_from(evidence, "metric"),
        "role": _enum_value(_value_from(evidence, "role")),
        "observation_status": _enum_value(_value_from(evidence, "observation_status")),
        "current_value": _value_from(evidence, "current_value"),
        "baseline_value": _value_from(evidence, "baseline_value"),
        "relative_change": _value_from(evidence, "relative_change"),
        "unit": _value_from(evidence, "unit"),
        "sample_size": _value_from(evidence, "sample_size"),
        "dimensions": _value_from(evidence, "dimensions", {}),
        "filters": _value_from(evidence, "filters", {}),
    }


def _diagnosis_payload(diagnosis: Any) -> dict[str, Any]:
    """Select the structured Diagnosis contract fields for the artifact."""
    change = _value_from(diagnosis, "change")
    change_payload = None
    if change is not None:
        change_payload = {
            "current_value": _value_from(change, "current_value"),
            "baseline_value": _value_from(change, "baseline_value"),
            "relative_change": _value_from(change, "relative_change"),
            "unit": _value_from(change, "unit"),
            "evidence_id": _value_from(change, "evidence_id"),
        }
    return {
        "diagnosis_id": _value_from(diagnosis, "diagnosis_id"),
        "status": _enum_value(_value_from(diagnosis, "status")),
        "target_metric": _value_from(diagnosis, "target_metric"),
        "primary_driver": _value_from(diagnosis, "primary_driver"),
        "affected_scope": _value_from(diagnosis, "affected_scope", {}),
        "confidence": _value_from(diagnosis, "confidence"),
        "change": change_payload,
        "evidence_ids": list(_value_from(diagnosis, "evidence_ids", ())),
        "limitations": list(_value_from(diagnosis, "limitations", ())),
        "created_at": _value_from(diagnosis, "created_at"),
    }


def _build_live_artifact(
    *,
    mode: str,
    model: str,
    scenarios: Sequence[str],
    results: Mapping[str, Mapping[str, Any]],
    generated_at: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted, JSON-safe artifact from already-verified run results."""
    expected = tuple(scenarios)
    if not _is_complete_suite(expected):
        raise ValueError("A successful live artifact requires the complete three-scenario suite.")
    if set(results) != set(expected):
        raise ValueError("Cannot build a live artifact from an incomplete scenario result set.")

    scenario_payload: dict[str, Any] = {}
    for scenario in expected:
        result = results[scenario]
        summary = result.get("summary")
        if summary is not None:
            investigation = _value_from(summary, "investigation")
            composition = _value_from(summary, "composition")
            diagnosis = _value_from(composition, "diagnosis")
            evidence = _value_from(composition, "evidence", ())
            budget = {
                "tool_calls_count": _value_from(investigation, "tool_calls_count"),
                "max_tool_calls": _value_from(investigation, "max_tool_calls"),
                "turns_count": _value_from(investigation, "turns_count"),
                "max_turns": _value_from(investigation, "max_turns"),
            }
        else:
            response = result.get("response")
            diagnosis = _value_from(response, "diagnosis", result)
            evidence = _value_from(response, "evidence", result.get("evidence_list", ()))
            budget_source = _value_from(response, "budget")
            budget = {
                "tool_calls_count": _value_from(budget_source, "tool_calls_count", result.get("tool_calls_count")),
                "max_tool_calls": _value_from(budget_source, "max_tool_calls", DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS),
                "turns_count": _value_from(budget_source, "turns_count", result.get("turns_count")),
                "max_turns": _value_from(budget_source, "max_turns", DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS),
            }

        scenario_payload[scenario] = {
            "result": {
                "scenario": scenario,
                "status": "PASS",
                "tools_used": result.get("tools_used", ()),
                "observation_ids": result.get("observation_ids", ()),
                "evidence_ids": result.get("evidence_ids", ()),
                "diagnosis_status": result.get("diagnosis_status", _value_from(diagnosis, "status")),
                "primary_driver": result.get("primary_driver", _value_from(diagnosis, "primary_driver")),
                "affected_scope": result.get("affected_scope", _value_from(diagnosis, "affected_scope", {})),
            },
            "trace": _trace_payload(result),
            "evidence": [_evidence_payload(item) for item in evidence],
            "diagnosis": _diagnosis_payload(diagnosis),
            "budget": budget,
        }

    timestamp = generated_at or datetime.datetime.now(datetime.timezone.utc)
    artifact = {
        "schema": LIVE_ARTIFACT_SCHEMA,
        "version": LIVE_ARTIFACT_VERSION,
        "generated_at": timestamp.astimezone(datetime.timezone.utc).isoformat(),
        "mode": mode,
        "model": model,
        **_provider_metadata(),
        "scenario_set": list(expected),
        "scenarios": scenario_payload,
        "overall_status": "PASS",
    }
    safe_artifact = _json_safe(artifact)
    if not isinstance(safe_artifact, dict):
        raise TypeError("Live artifact must be a JSON object.")
    return safe_artifact


def _write_live_artifact(path: str | Path, artifact: Mapping[str, Any]) -> None:
    """Atomically write one UTF-8 artifact, leaving any old target untouched on error."""
    target = Path(path)
    if target.exists() and target.is_dir():
        raise IsADirectoryError(f"Artifact target is a directory: {target}")
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    safe_artifact = _json_safe(artifact)
    temporary_path: str | None = None
    try:
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(parent),
            text=True,
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                safe_artifact,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                Path(temporary_path).unlink()
            except FileNotFoundError:
                pass


def _is_complete_suite(scenarios: Sequence[str]) -> bool:
    return set(scenarios) == set(AVAILABLE_SCENARIOS) and len(scenarios) == len(AVAILABLE_SCENARIOS)


def _provider_metadata() -> dict[str, Any]:
    """Return only the provider host, never the configured URL or credentials."""
    configured_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if not configured_url:
        host = "api.openai.com"
    else:
        parsed = urlsplit(configured_url if "://" in configured_url else f"//{configured_url}")
        host = (parsed.hostname or "unknown").lower()
    return {
        "provider_host": host,
        "is_official_openai": host == "api.openai.com",
    }


class LoggingAnalyticsTools(AnalyticsTools):
    """AnalyticsTools proxy that records invoked queries for audit verification."""

    def __init__(
        self,
        registry: MetricRegistry,
        connection: Any,
        call_log: list[dict[str, Any]],
    ) -> None:
        super().__init__(registry=registry, connection=connection)
        self._call_log = call_log

    def query_metric(self, *args: Any, **kwargs: Any) -> Any:
        result = super().query_metric(*args, **kwargs)
        self._call_log.append(
            {
                "operation": "query_metric",
                "kwargs": {
                    k: str(v) if isinstance(v, (datetime.date, tuple)) else v
                    for k, v in kwargs.items()
                },
                "result_metric": result.metric_id,
                "rows_count": len(result.rows),
            }
        )
        return result

    def query_related_metrics(self, *args: Any, **kwargs: Any) -> Any:
        result = super().query_related_metrics(*args, **kwargs)
        self._call_log.append(
            {
                "operation": "query_related_metrics",
                "kwargs": {
                    k: str(v) if isinstance(v, (datetime.date, tuple)) else v
                    for k, v in kwargs.items()
                },
                "metrics_returned": [r.metric_id for r in result.results],
            }
        )
        return result


def _inject_scenario(scenario: str, database_url: str) -> None:
    """Inject one synthetic anomaly scenario using the benchmark injector."""
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "warehouse" / "anomaly_injector.py"),
            "--scenario",
            scenario,
            "--database-url",
            database_url,
        ],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Scenario injector failed for '{scenario}' with exit {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )


def _print_formatted_trace(
    scenario: str,
    turns_count: int,
    max_turns: int,
    tool_calls_count: int,
    max_tool_calls: int,
    tools_used: list[str],
    call_log: list[dict[str, Any]],
    observation_ids: list[str],
    evidence_items: list[dict[str, Any]],
    diagnosis: dict[str, Any],
) -> None:
    """Format and print an auditable timeline for one live investigation run.

    Follows the strict sequence:
    Scenario -> Tool Call Sequence -> Observations Captured -> Cited Evidence -> Final Structured Diagnosis
    """
    print(f"\n======================================================================")
    print(f"[TRACE] Scenario: {scenario.upper()}")
    print(f"======================================================================")

    # 1. Tool Call Sequence
    print(f"1. Tool Call Sequence (Turns: {turns_count}/{max_turns}, Tool Calls: {tool_calls_count}/{max_tool_calls}):")
    if call_log:
        for i, call in enumerate(call_log, 1):
            op = call.get("operation") or call.get("tool_name", "query")
            call_id = call.get("tool_call_id", f"call_{i}")
            kwargs = call.get("kwargs") or call.get("arguments", {})
            summary = call.get("summary", "")
            print(f"   [{i}] {op} (ID: {call_id})")
            print(f"       Arguments: {json.dumps(kwargs, ensure_ascii=False)}")
            if summary:
                print(f"       Summary:   {summary}")
    else:
        print(f"   Tools used: {tools_used}")

    # 2. Observations Captured
    print(f"\n2. Observations Captured (Count: {len(observation_ids)}):")
    for obs_id in observation_ids:
        print(f"   - {obs_id}")

    # 3. Diagnosis-cited Evidence (the portfolio may contain additional items)
    cited_ids = set(diagnosis.get("evidence_ids", []))
    cited_evidence = [ev for ev in evidence_items if ev.get("evidence_id") in cited_ids]
    print(f"\n3. Diagnosis-Cited Evidence (Count: {len(cited_evidence)}):")
    for ev in cited_evidence:
        ev_id = ev.get("evidence_id", "unknown")
        metric = ev.get("metric", "")
        role = ev.get("role", "")
        status = ev.get("observation_status", "")
        change = ev.get("relative_change")
        change_str = f"{change:+.2%}" if change is not None else "N/A"
        dims = ev.get("dimensions", {})
        filters = ev.get("filters", {})
        print(f"   * [{role}] {ev_id} | Metric: {metric} | Status: {status} | Change: {change_str}")
        if dims or filters:
            print(f"     Scope/Filters: dims={dims}, filters={filters}")

    # 4. Final Structured Diagnosis
    print(f"\n4. Final Structured Diagnosis:")
    print(f"   - Diagnosis ID:   {diagnosis.get('diagnosis_id')}")
    print(f"   - Status:         {diagnosis.get('status')}")
    print(f"   - Target Metric:  {diagnosis.get('target_metric')}")
    print(f"   - Primary Driver: {diagnosis.get('primary_driver')}")
    print(f"   - Affected Scope: {diagnosis.get('affected_scope')}")
    print(f"   - Confidence:     {diagnosis.get('confidence')}")
    print(f"   - Limitations:    {diagnosis.get('limitations', [])}")
    print(f"======================================================================\n")


def _freeze_call_value(value: Any) -> Any:
    """Return a deterministic, hashable representation of a call argument."""
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_call_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_call_value(item) for item in value)
    return value


def _call_signature(call: Mapping[str, Any]) -> tuple[Any, ...]:
    """Capture the complete arguments for one analytics-tool branch."""
    arguments = call.get("kwargs") or call.get("arguments") or {}
    return (
        call.get("operation") or call.get("tool_name"),
        _freeze_call_value(arguments),
    )


def _analytics_call_signatures(call_log: Sequence[Mapping[str, Any]]) -> list[tuple[Any, ...]]:
    """Compare only model-selected analytics queries, not semantic lookups."""
    return [
        _call_signature(call)
        for call in call_log
        if (call.get("operation") or call.get("tool_name"))
        in {"query_metric", "query_related_metrics"}
    ]


def _evidence_value(evidence: Any, field: str) -> Any:
    if isinstance(evidence, Mapping):
        return evidence.get(field)
    return getattr(evidence, field, None)


def assert_scenario_results(
    results: dict[str, dict[str, Any]],
    expected_scenarios: Sequence[str] = AVAILABLE_SCENARIOS,
) -> None:
    """Verify LIVE-002 invariants for exactly the requested scenario set."""
    expected = tuple(expected_scenarios)
    if len(set(expected)) != len(expected):
        raise AssertionError(f"Expected scenarios must be unique, got: {expected}.")
    actual_set = set(results)
    expected_set = set(expected)
    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        unexpected = sorted(actual_set - expected_set)
        raise AssertionError(
            "Scenario completeness FAILED: "
            f"missing={missing}, unexpected={unexpected}, expected={list(expected)}."
        )

    print("\n=======================================================")
    print(f"Verifying {len(expected)} Selected Scenario(s) & Assertions...")
    print("=======================================================")

    # Budget containment applies to every result, including explicit subsets.
    for scenario, result in results.items():
        tool_calls = result["tool_calls_count"]
        turns = result["turns_count"]
        if not (1 <= tool_calls <= DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS):
            raise AssertionError(f"Scenario '{scenario}' exceeded tool call budget (got {tool_calls}).")
        if not (1 <= turns <= DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS):
            raise AssertionError(f"Scenario '{scenario}' exceeded turn budget (got {turns}).")

    # 1. Autonomous Dynamic Branching assertion
    if "canonical" in results and "traffic" in results:
        canonical_calls = _analytics_call_signatures(results["canonical"]["call_log"])
        traffic_calls = _analytics_call_signatures(results["traffic"]["call_log"])
        if canonical_calls == traffic_calls:
            raise AssertionError(
                "Autonomous dynamic branching FAILED: Canonical and Traffic scenarios produced identical "
                "analytics query call sequences. The agent must dynamically adapt queries based on Observation facts."
            )
        print("  [PASS] Autonomous Dynamic Branching: Canonical vs Traffic analytics call sequences differ.")

    # 2. Canonical diagnosis assertion
    if "canonical" in results:
        res = results["canonical"]
        status = res["diagnosis_status"]
        driver = res["primary_driver"]
        scope = res["affected_scope"]

        if status != "diagnosed":
            raise AssertionError(f"Canonical scenario expected status 'diagnosed', got '{status}'.")
        if driver != "conversion_rate":
            raise AssertionError(f"Canonical scenario expected primary_driver 'conversion_rate', got '{driver}'.")
        if not (scope.get("marketplace") == "US" and scope.get("asin") == "ASIN-A" and scope.get("traffic_source") == "Ads"):
            raise AssertionError(f"Canonical scenario affected_scope must identify US / ASIN-A / Ads, got: {scope}.")
        print("  [PASS] Canonical Scenario: identified conversion_rate in US/ASIN-A/Ads within budget.")

    # 3. Traffic diagnosis assertion
    if "traffic" in results:
        res = results["traffic"]
        status = res["diagnosis_status"]
        driver = res["primary_driver"]
        scope = res["affected_scope"]

        if status != "diagnosed":
            raise AssertionError(f"Traffic scenario expected status 'diagnosed', got '{status}'.")
        if driver != "sessions":
            raise AssertionError(f"Traffic scenario expected primary_driver 'sessions', got '{driver}'.")
        expected_scope = {
            "marketplace": "US",
            "asin": "ASIN-A",
            "traffic_source": "Ads",
        }
        if scope != expected_scope:
            raise AssertionError(
                "Traffic scenario affected_scope must identify US / ASIN-A / Ads, "
                f"got {scope}."
            )
        print("  [PASS] Traffic Scenario: identified sessions in US/ASIN-A/Ads within budget.")

    # 4. No-anomaly diagnosis assertion
    if "no_anomaly" in results:
        res = results["no_anomaly"]
        status = res["diagnosis_status"]
        driver = res["primary_driver"]
        scope = res["affected_scope"]

        if status != "no_material_anomaly":
            raise AssertionError(
                f"No-anomaly scenario expected status 'no_material_anomaly', got '{status}'."
            )
        if driver is not None:
            raise AssertionError(f"No-anomaly scenario must have primary_driver None, got '{driver}'.")
        if len(scope) != 0:
            raise AssertionError(f"No-anomaly scenario must have empty affected_scope, got: {scope}.")
        print("  [PASS] No-anomaly Scenario: correctly diagnosed no_material_anomaly with primary_driver=None.")

    # 5. Evidence traceability assertion
    for sc, res in results.items():
        evidence_ids = res.get("evidence_ids", [])
        obs_ids = set(res.get("observation_ids", []))
        if not evidence_ids:
            raise AssertionError(f"Scenario '{sc}' diagnosis must cite at least one evidence item.")
        portfolio = {
            _evidence_value(evidence, "evidence_id"): evidence
            for evidence in res.get("evidence_list", [])
        }
        for evidence_id in evidence_ids:
            if evidence_id not in portfolio:
                raise AssertionError(
                    f"Scenario '{sc}' diagnosis cites evidence '{evidence_id}' absent from its portfolio."
                )
            observation_id = _evidence_value(portfolio[evidence_id], "observation_id")
            if not observation_id or observation_id not in obs_ids:
                raise AssertionError(
                    f"Scenario '{sc}' cited evidence '{evidence_id}' references observation "
                    f"'{observation_id}' not produced in this run."
                )
    print("  [PASS] Evidence Traceability: cited evidence traces back to real warehouse observations.")


def run_live_investigation_direct(
    database_url: str,
    api_key: str,
    model: str,
    scenarios: Sequence[str],
    restore_scenario: str = "canonical",
) -> dict[str, dict[str, Any]]:
    """Execute scenarios directly using in-process Agents SDK runtime."""
    config_path = REPOSITORY_ROOT / "configs" / "metrics.yaml"
    registry = MetricRegistry.from_yaml(config_path)

    run_results: dict[str, dict[str, Any]] = {}

    try:
        total_scenarios = len(scenarios)
        for idx, scenario in enumerate(scenarios, 1):
            print(f"\n>>> [{idx}/{total_scenarios}] Injecting scenario: {scenario} ...")
            _inject_scenario(scenario, database_url)

            call_log: list[dict[str, Any]] = []
            with psycopg.connect(database_url) as connection:
                tools = LoggingAnalyticsTools(
                    registry=registry,
                    connection=connection,
                    call_log=call_log,
                )
                diagnosis_id = f"live_diag_{scenario}_{int(time.time())}"

                print(f">>> Running autonomous investigation with {model} (direct mode) ...")
                summary: EvidenceDrivenRunSummary = run_evidence_driven_diagnosis(
                    prompt=NEUTRAL_PROMPT,
                    diagnosis_id=diagnosis_id,
                    analytics_tools=tools,
                    model=model,
                    max_tool_calls=DEFAULT_EVIDENCE_DRIVEN_MAX_TOOL_CALLS,
                    max_turns=DEFAULT_EVIDENCE_DRIVEN_MAX_TURNS,
                )

                diag = summary.composition.diagnosis
                diag_dict = {
                    "diagnosis_id": diag.diagnosis_id,
                    "status": diag.status.value,
                    "target_metric": diag.target_metric,
                    "primary_driver": diag.primary_driver,
                    "affected_scope": dict(diag.affected_scope),
                    "confidence": float(diag.confidence) if diag.confidence is not None else None,
                    "evidence_ids": list(diag.evidence_ids),
                    "limitations": list(diag.limitations),
                }
                evidence_items = [
                    {
                        "evidence_id": ev.evidence_id,
                        "observation_id": ev.observation_id,
                        "metric": ev.metric,
                        "role": ev.role.value,
                        "observation_status": ev.observation_status.value,
                        "relative_change": float(ev.relative_change) if ev.relative_change is not None else None,
                        "dimensions": dict(ev.dimensions),
                        "filters": dict(ev.filters),
                    }
                    for ev in summary.composition.evidence
                ]

                _print_formatted_trace(
                    scenario=scenario,
                    turns_count=summary.investigation.turns_count,
                    max_turns=summary.investigation.max_turns,
                    tool_calls_count=summary.investigation.tool_calls_count,
                    max_tool_calls=summary.investigation.max_tool_calls,
                    tools_used=list(summary.investigation.tools_used),
                    call_log=call_log,
                    observation_ids=list(summary.investigation.observation_ids),
                    evidence_items=evidence_items,
                    diagnosis=diag_dict,
                )

                run_results[scenario] = {
                    "summary": summary,
                    "tool_calls_count": summary.investigation.tool_calls_count,
                    "turns_count": summary.investigation.turns_count,
                    "tools_used": list(summary.investigation.tools_used),
                    "call_log": call_log,
                    "observation_ids": list(summary.investigation.observation_ids),
                    "evidence_ids": list(diag.evidence_ids),
                    "evidence_list": summary.composition.evidence,
                    "diagnosis_status": diag.status.value,
                    "primary_driver": diag.primary_driver,
                    "affected_scope": dict(diag.affected_scope),
                    "confidence": float(diag.confidence) if diag.confidence is not None else None,
                }

        assert_scenario_results(run_results, expected_scenarios=scenarios)
        return run_results
    finally:
        print(f"\n>>> Restoring database state to '{restore_scenario}' scenario ...")
        _inject_scenario(restore_scenario, database_url)
        print(f">>> Database restored to '{restore_scenario}'.")


def run_live_investigation_api(
    database_url: str,
    api_key: str,
    model: str,
    scenarios: Sequence[str],
    restore_scenario: str = "canonical",
) -> dict[str, dict[str, Any]]:
    """Execute scenarios through the in-process API service path."""
    from app.api.schemas import InvestigationRequest
    from app.api.service import execute_investigation, inject_scenario_data

    os.environ["DATABASE_URL"] = database_url
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["METRICSLEUTH_AGENT_MODEL"] = model

    run_results: dict[str, dict[str, Any]] = {}

    try:
        total_scenarios = len(scenarios)
        for idx, scenario in enumerate(scenarios, 1):
            print(f"\n>>> [{idx}/{total_scenarios}] Injecting scenario: {scenario} ...")
            injection_mode, _ = inject_scenario_data(scenario)
            if injection_mode != "live":
                raise RuntimeError(
                    f"Scenario '{scenario}' was not injected into the live warehouse "
                    f"(mode={injection_mode})."
                )

            print(f">>> Running autonomous investigation via in-process API service for {scenario} (model={model}) ...")
            req = InvestigationRequest(
                mock_mode=False,
                target_metric="sales",
                target_date="2026-01-31",
                scenario=scenario,
                model=model,
                prompt=NEUTRAL_PROMPT,
            )
            resp = execute_investigation(req)

            call_log = [
                {
                    "operation": step.tool_name,
                    "tool_call_id": step.tool_call_id,
                    "kwargs": step.arguments,
                    "summary": step.summary,
                }
                for step in resp.investigation_trace
            ]
            observation_ids = []
            for step in resp.investigation_trace:
                if step.observation_id:
                    observation_ids.extend(
                        observation_id.strip()
                        for observation_id in step.observation_id.split(",")
                        if observation_id.strip()
                    )

            evidence_items = [ev.model_dump() for ev in resp.evidence]
            diag_dict = resp.diagnosis.model_dump()

            _print_formatted_trace(
                scenario=scenario,
                turns_count=resp.budget.turns_count,
                max_turns=resp.budget.max_turns,
                tool_calls_count=resp.budget.tool_calls_count,
                max_tool_calls=resp.budget.max_tool_calls,
                tools_used=[step.tool_name for step in resp.investigation_trace],
                call_log=call_log,
                observation_ids=observation_ids,
                evidence_items=evidence_items,
                diagnosis=diag_dict,
            )

            run_results[scenario] = {
                "tool_calls_count": resp.budget.tool_calls_count,
                "turns_count": resp.budget.turns_count,
                "tools_used": [step.tool_name for step in resp.investigation_trace],
                "call_log": call_log,
                "observation_ids": observation_ids,
                "evidence_ids": list(resp.diagnosis.evidence_ids),
                "evidence_list": resp.evidence,
                "diagnosis_status": resp.diagnosis.status,
                "primary_driver": resp.diagnosis.primary_driver,
                "affected_scope": resp.diagnosis.affected_scope,
                "confidence": resp.diagnosis.confidence,
                "response": resp,
            }

        assert_scenario_results(run_results, expected_scenarios=scenarios)
        return run_results
    finally:
        print(f"\n>>> Restoring database state to '{restore_scenario}' scenario ...")
        restore_mode, _ = inject_scenario_data(restore_scenario)
        if restore_mode != "live":
            raise RuntimeError(
                f"Restore scenario '{restore_scenario}' was not injected into the live warehouse "
                f"(mode={restore_mode})."
            )
        print(f">>> Database restored to '{restore_scenario}'.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Phase 6 / LIVE-002 Live Autonomous Investigation on benchmark development scenarios."
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model name (overrides METRICSLEUTH_AGENT_MODEL and default 'gpt-4o-mini')",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "").strip(),
        help="PostgreSQL connection string (or set DATABASE_URL env var)",
    )
    parser.add_argument(
        "--scenarios",
        default=DEFAULT_SCENARIOS,
        help=f"Comma-separated list of scenarios to verify (default: {DEFAULT_SCENARIOS})",
    )
    parser.add_argument(
        "--mode",
        choices=["direct", "service", "api"],
        default="direct",
        help="Execution mode: 'direct' (Agents SDK runtime) or 'service' (in-process service; 'api' is a compatibility alias)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Write a redacted JSON PASS artifact after the complete three-scenario suite succeeds",
    )
    parser.add_argument(
        "--dry-run-check",
        action="store_true",
        help="Perform pre-flight configuration and dependency check without invoking live LLM",
    )
    parser.add_argument(
        "--restore-scenario",
        default="canonical",
        help="Scenario to restore after tests (default: canonical)",
    )
    args = parser.parse_args()

    # Parse and validate scenarios
    raw_scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    scenarios = tuple(raw_scenarios) if raw_scenarios else AVAILABLE_SCENARIOS

    resolved_model = resolve_live_model(args.model)
    resolved_mode = "service" if args.mode == "api" else args.mode
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    database_url = args.database_url.strip()

    # Handle Pre-flight Check (--dry-run-check)
    if args.dry_run_check:
        print("=== MetricSleuth Live Autonomous Investigation Pre-flight Check ===")
        print(f"Target Scenarios: {', '.join(scenarios)}")
        print(f"Resolved Model:   {resolved_model}")
        print(f"Execution Mode:   {resolved_mode}")
        print(f"Dependency Status:")
        print(f"  - OPENAI_API_KEY: {'[CONFIGURED]' if api_key else '[MISSING]'}")
        print(f"  - DATABASE_URL:   {'[CONFIGURED]' if database_url else '[MISSING]'}")

        if not api_key or not database_url:
            print("\nPre-flight Status: BLOCKED (Fail-Closed)")
            print("Required live credentials or database configuration missing.")
            print("To run live investigation against real OpenAI models and PostgreSQL:")
            print("  $env:OPENAI_API_KEY = '<your-openai-api-key>'")
            print("  $env:DATABASE_URL   = 'postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'")
            return 2
        else:
            print("\nPre-flight Status: READY")
            print("All live investigation prerequisites are satisfied.")
            return 0

    print("=== MetricSleuth Live Autonomous Investigation Verification ===")

    if not api_key or not database_url:
        print("[NOTICE] Live investigation cannot run because required environment variables or credentials are not set.")
        print(f"  - OPENAI_API_KEY: {'[CONFIGURED]' if api_key else '[MISSING]'}")
        print(f"  - METRICSLEUTH_AGENT_MODEL: {resolved_model}")
        print(f"  - DATABASE_URL: {'[CONFIGURED]' if database_url else '[MISSING]'}")
        print("\nLive Status: BLOCKED (Fail-Closed)")
        print("\nTo run the live autonomous investigation against real OpenAI models and PostgreSQL, set:")
        print("  $env:OPENAI_API_KEY = '<local-only-secret>'")
        print("  $env:DATABASE_URL = 'postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'")
        print("  $env:METRICSLEUTH_AGENT_MODEL = 'gpt-4o-mini'  # optional, defaults to gpt-4o-mini")
        print("\nHermetic unit tests continue to validate offline investigation harness and diagnosis composition.")
        return 2

    if args.output_json is not None and not _is_complete_suite(scenarios):
        print(
            "[NOTICE] --output-json requires the complete three-scenario suite "
            "(canonical, traffic, no_anomaly); no artifact was written.",
            file=sys.stderr,
        )
        return 2

    print(f"Starting live investigation (mode={resolved_mode}, model={resolved_model}) ...")
    try:
        if resolved_mode == "service":
            run_results = run_live_investigation_api(
                database_url=database_url,
                api_key=api_key,
                model=resolved_model,
                scenarios=scenarios,
                restore_scenario=args.restore_scenario,
            )
        else:
            run_results = run_live_investigation_direct(
                database_url=database_url,
                api_key=api_key,
                model=resolved_model,
                scenarios=scenarios,
                restore_scenario=args.restore_scenario,
            )
        if args.output_json is not None:
            artifact = _build_live_artifact(
                mode=resolved_mode,
                model=resolved_model,
                scenarios=scenarios,
                results=run_results,
            )
            _write_live_artifact(args.output_json, artifact)
            print(f"Live artifact written atomically: {args.output_json}")
    except Exception as exc:
        for note in getattr(exc, "__notes__", ()):
            print(f"[LIVE DIAGNOSTIC] {note}", file=sys.stderr)
        print(f"\n[LIVE INVESTIGATION FAILED] {exc}", file=sys.stderr)
        return 1

    if _is_complete_suite(scenarios):
        print("\nLive Autonomous Investigation (complete 3-scenario suite): PASS")
    else:
        print(f"\nLive Autonomous Investigation (selected subset: {', '.join(scenarios)}): PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
