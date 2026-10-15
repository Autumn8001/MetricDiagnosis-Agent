# Live model SDK compatibility acceptance — 2026-10-15

> 后续定位纠正：本记录的“SDK协议不兼容”只是当时推测，并未成立。继续定位发现工具参数遗漏任务绑定过滤器，后端在执行 SQL 前拒绝；SDK 将该错误包装为 UserError。单看持久表的 0 条已完成工具记录不能推断“模型没有发起工具调用”。最新调查结果见 [任务过滤器验收](live-model-task-scope-2026-10-15.md)。

## Scope

This was a bounded acceptance attempt on the isolated Synthetic PostgreSQL database
`metricsleuth_r2_acceptance` (loopback port 55440). It did not access production,
Shopify, or any external business database. The temporary PostgreSQL instance was
stopped after the run and port 55440 had no listener.

The model environment was read from the local, ignored `.env`; no credential or raw
provider response is recorded here. The configured API mode was Chat Completions and
the configured model was `gemini-3.8-flash-high`. Automatic retries and remote tracing
were disabled. The investigation gate allowed at most 8 tool calls and 10 turns.

## Preflight evidence

The same endpoint returned successful responses for:

1. `GET /v1/models` (HTTP 200), with the configured model present;
2. a minimal Chat Completions text request (HTTP 200);
3. a Chat Completions request with a function tool (HTTP 200, tool call present);
4. a request using the generated `RuntimeDiagnosisIntent` JSON Schema (HTTP 200).

These checks show that the current endpoint accepts basic text, tool declarations, and
the generated structured-output schema when called directly.

## Agents SDK result

The existing `backend/scripts/verify_live_task_persistence.py` then ran the normal
Agents SDK Runtime and persistence path once. The run was persisted as `failed` with
`failure_code=execution_failed` and `exception_type=UserError`.

| Result | Value |
|---|---:|
| SDK tool calls | 0 |
| turns | not reported |
| Observations | 0 |
| Evidence | 0 |
| Diagnosis | 0 |
| persisted run | failed |

No successful diagnosis was produced. The failure occurs after endpoint
authentication and before the first analytics tool call, so this is now classified as
an Agents SDK request/response compatibility issue rather than an invalid-key issue.

## Decision

Do not claim real-model investigation success and do not add a second Agent Runtime.
The next focused task is to capture and compare the exact SDK-generated Chat
Completions request/response shape (including tool and structured-output parameters)
against the provider's accepted direct requests, then make the smallest compatible
adapter change. A new live investigation should only run after that change and a
fresh bounded authorization.
