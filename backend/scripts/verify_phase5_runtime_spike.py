"""Verification script for Phase 5 OpenAI Agents SDK Runtime Spike."""

import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.agent_runtime.spike import RuntimeConfigError, run_runtime_spike


def main() -> int:
    print("=== MetricSleuth Phase 5 Runtime Spike Verification ===")

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("METRICSLEUTH_AGENT_MODEL", "").strip()

    if not api_key or not model:
        print("[NOTICE] Live runtime spike cannot run because required environment variables are not set.")
        print("  - OPENAI_API_KEY: " + ("[SET]" if api_key else "[MISSING]"))
        print("  - METRICSLEUTH_AGENT_MODEL: " + (model if model else "[MISSING]"))
        print("\nLive Status: BLOCKED")
        print("\nTo run the live spike against OpenAI Agents SDK, set:")
        print("  $env:OPENAI_API_KEY = '<local-only-secret>'")
        print("  $env:METRICSLEUTH_AGENT_MODEL = 'gpt-4o-mini'  # or preferred model")
        print("\nHermetic unit tests continue to validate tool adapter, trace parser, and budget rules.")
        return 2

    print(f"Running live spike with model: {model}...")
    try:
        summary = run_runtime_spike()

        print("\n--- Sanitized Execution Summary ---")
        print(f"Model: {summary.model}")
        print(f"Tool Calls Count: {summary.tool_calls_count} / max {summary.max_tool_calls}")
        print(f"Tools Used: {list(summary.tools_used)}")
        print(f"Tool Result Returned to Model: {summary.tool_result_returned}")
        print(f"Execution Trace Sequence: {' -> '.join(summary.trace_sequence)}")
        print(f"Turns Count: {summary.turns_count} / max {summary.max_turns}")
        print(f"Structured Output: {summary.final_output.model_dump_json(indent=2)}")

        # Keep all live-run assertions inside the failure boundary. A malformed
        # or inconsistent result is a runtime failure (exit code 1), never an
        # uncaught AssertionError that bypasses the script's status contract.
        assert summary.tool_calls_count == 1, f"Expected 1 tool call, got {summary.tool_calls_count}"
        assert summary.tools_used == ("get_metric_definition",), f"Unexpected tools: {summary.tools_used}"
        assert summary.tool_result_returned, "Tool result was not returned to model context"
        assert summary.final_output.metric_id == "sales", f"Expected metric_id 'sales', got {summary.final_output.metric_id}"
        assert summary.final_output.unit == "usd", f"Expected metric unit 'usd', got {summary.final_output.unit}"
        assert summary.final_output.tool_used == "get_metric_definition", f"Expected tool_used 'get_metric_definition', got {summary.final_output.tool_used}"
    except RuntimeConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        return 1
    except Exception as e:
        print(f"[RUNTIME SPIKE FAILED] {e}")
        return 1

    print("\nPhase 5 OpenAI Agents SDK Runtime Spike: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
