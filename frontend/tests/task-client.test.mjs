// The repo script compiles src/tasks to METRICSLEUTH_TASK_CLIENT_BUILD_DIR first.
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { join, resolve } from "node:path";
import test from "node:test";

const buildDirectory = process.env.METRICSLEUTH_TASK_CLIENT_BUILD_DIR;
if (!buildDirectory) throw new Error("METRICSLEUTH_TASK_CLIENT_BUILD_DIR is required");
const { createTaskClient, TaskClientError } = await import(
  pathToFileURL(join(resolve(buildDirectory), "tasks", "client.js")).href
);

const runId = "11111111-1111-4111-8111-111111111111";
const sourceId = "shopify demo/α";

function run(overrides = {}) {
  return {
    investigation_run_id: runId,
    source_id: sourceId,
    environment: "sandbox",
    provider: "shopify",
    status: "queued",
    requested_metric: "sales",
    requested_at: "2026-10-10T12:00:00Z",
    started_at: null,
    finished_at: null,
    data_version: null,
    query_reference: "task:22222222-2222-4222-8222-222222222222",
    failure_code: null,
    tool_call_count: 0,
    observation_count: 0,
    evidence_count: 0,
    diagnosis_count: 0,
    ...overrides,
  };
}

function response(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("source catalog preserves configured capability limits without claiming connectivity", async () => {
  const source = { source_id: "static-olist", display_name: "Olist static validation", provider: "olist",
    environment: "validation", data_version: "label-only", metrics: [
      { metric_id: "orders", supported: true, grain: ["date", "customer_state"], dimensions: ["customer_state"], unavailable_reason: null },
      { metric_id: "sessions", supported: false, grain: [], dimensions: [], unavailable_reason: "not available" },
    ] };
  let requested;
  const client = createTaskClient({ fetcher: async (url) => { requested = url; return response({ items: [source] }); } });
  assert.deepEqual(await client.sources(), { items: [source] });
  assert.equal(requested, "/api/investigation-sources");
  const invalid = createTaskClient({ fetcher: async () => response({ items: [{ ...source, connected: true }] }) });
  await assert.rejects(invalid.sources(), (error) => error.code === "invalid_response");
  const duplicate = createTaskClient({ fetcher: async () => response({ items: [source, source] }) });
  await assert.rejects(duplicate.sources(), (error) => error.code === "invalid_response");
});

test("source catalog handles empty configuration and safe catalog errors", async () => {
  const empty = createTaskClient({ fetcher: async () => response({ items: [] }) });
  assert.deepEqual(await empty.sources(), { items: [] });
  const unavailable = createTaskClient({ fetcher: async () => response({ detail: { code: "source_catalog_unavailable", secret: "hidden" } }, 503) });
  await assert.rejects(unavailable.sources(), (error) => error.status === 503 && error.code === "source_catalog_unavailable" && !error.message.includes("hidden"));
});

test("submit validates 202 response, whitelists request fields, and sends only once", async () => {
  const calls = [];
  const client = createTaskClient({
    fetcher: async (url, init) => {
      calls.push({ url, init });
      return response(run(), 202);
    },
  });
  const result = await client.submit({
    source_id: sourceId,
    target_metric: "sales",
    target_date: "2026-10-09",
    filters: { country: "US" },
    group_by: ["country"],
  });
  assert.equal(result.investigation_run_id, runId);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    source_id: sourceId,
    target_metric: "sales",
    target_date: "2026-10-09",
    filters: { country: "US" },
    group_by: ["country"],
  });
});

test("submit sends the same trimmed identifiers accepted by the backend", async () => {
  let posted;
  const client = createTaskClient({
    fetcher: async (_url, init) => {
      posted = JSON.parse(init.body);
      return response(run({ source_id: "store", requested_metric: "sales" }), 202);
    },
  });
  const result = await client.submit({
    source_id: " store ",
    target_metric: " sales ",
    target_date: "2026-10-09",
    filters: { " country ": " US " },
    group_by: [" country "],
  });
  assert.equal(result.source_id, "store");
  assert.deepEqual(posted, {
    source_id: "store",
    target_metric: "sales",
    target_date: "2026-10-09",
    filters: { country: "US" },
    group_by: ["country"],
  });
});

test("a failed POST is never retried", async () => {
  let calls = 0;
  const client = createTaskClient({ fetcher: async () => {
    calls += 1;
    return response({ detail: { code: "task_storage_unavailable" } }, 503);
  } });
  await assert.rejects(
    client.submit({ source_id: sourceId, target_metric: "sales", target_date: "2026-10-09" }),
    (error) => error instanceof TaskClientError && error.status === 503,
  );
  assert.equal(calls, 1);
});

test("filter names are data and cannot disappear through object prototype assignment", async () => {
  let posted;
  const client = createTaskClient({ fetcher: async (_url, init) => {
    posted = JSON.parse(init.body);
    return response(run(), 202);
  } });
  await client.submit({ source_id: sourceId, target_metric: "sales", target_date: "2026-10-09",
    filters: JSON.parse('{"__proto__":"bounded-scope"}') });
  assert.equal(Object.hasOwn(posted.filters, "__proto__"), true);
  assert.equal(posted.filters.__proto__, "bounded-scope");
});

test("list URL encodes source and pagination while validating every item identity", async () => {
  let requestedUrl;
  const client = createTaskClient({
    fetcher: async (url) => {
      requestedUrl = new URL(url, "http://localhost");
      return response({ items: [run()], limit: 5, offset: 2 });
    },
  });
  const result = await client.list(sourceId, { limit: 5, offset: 2 });
  assert.equal(requestedUrl.searchParams.get("source_id"), sourceId);
  assert.equal(requestedUrl.searchParams.get("limit"), "5");
  assert.equal(requestedUrl.searchParams.get("offset"), "2");
  assert.equal(result.items.length, 1);
  assert.equal(result.offset, 2);
});

test("detail encodes path and query identifiers and accepts Decimal strings, numbers, and nulls", async () => {
  const detailRunId = "run/a?b";
  const detail = {
    run: run({ investigation_run_id: detailRunId, status: "succeeded", observation_count: 1 }),
    tool_calls: [{
      tool_call_id: "tool-1", tool_name: "query_metric", status: "succeeded", arguments: { limit: 2 },
      data_version: null, query_reference: null, result_reference: "result-1", requested_at: "2026-10-10T12:00:00Z",
    }],
    observations: [{
      observation_id: "obs-1", tool_call_id: "tool-1", metric: "sales", status: "success", source_status: null,
      current_period_start: "2026-10-09", current_period_end: null, baseline_period_start: null,
      baseline_period_end: "2026-10-08", filters: {}, group_by: ["country"], dimensions: { country: "US" },
      current_value: "123.45", baseline_value: 100, relative_change: null, unit: "USD", sample_size: "1e2",
      query_reference: null, data_version: null, error_code: null, created_at: "2026-10-10T12:00:00Z",
    }],
    evidence: [{
      evidence_id: "ev-1", observation_id: "obs-1", tool_call_id: "tool-1", role: "driver",
      data_version: null, query_reference: null, created_at: "2026-10-10T12:00:00Z",
    }],
    diagnoses: [{
      diagnosis_id: "diag-1", status: "complete", target_metric: "sales", primary_driver: null,
      affected_scope: { country: "US" }, change: { current_value: null, baseline_value: 100, relative_change: "0.2345", unit: "USD", evidence_id: "ev-1" },
      evidence_ids: ["ev-1"], confidence: "0.8", limitations: [], data_version: null, query_reference: null,
      created_at: "2026-10-10T12:00:00Z",
    }],
  };
  let requestedUrl;
  const client = createTaskClient({
    baseUrl: "/root/",
    fetcher: async (url) => {
      requestedUrl = new URL(url, "http://localhost");
      return response(detail);
    },
  });
  const result = await client.detail(detailRunId, sourceId);
  assert.equal(requestedUrl.pathname, `/root/api/investigations/${encodeURIComponent(detailRunId)}`);
  assert.equal(requestedUrl.searchParams.get("source_id"), sourceId);
  assert.equal(result.observations[0].current_value, "123.45");
  assert.equal(result.observations[0].baseline_value, 100);
  assert.equal(result.observations[0].relative_change, null);
  assert.equal(result.diagnoses[0].change.current_value, null);
});

test("503 and 422 errors expose only HTTP status and allowlisted code", async () => {
  const client = createTaskClient({
    fetcher: async (_url, init) => init.method === "POST"
      ? response({ detail: { code: "invalid_task_request", private: "do-not-show" } }, 422)
      : response({ detail: { code: "task_storage_unavailable", error: "password=hidden" } }, 503),
  });
  await assert.rejects(
    client.submit({ source_id: sourceId, target_metric: "sales", target_date: "2026-10-09" }),
    (error) => error instanceof TaskClientError && error.status === 422 && error.code === "invalid_task_request" && !error.message.includes("private"),
  );
  await assert.rejects(
    client.list(sourceId),
    (error) => error instanceof TaskClientError && error.status === 503 && error.code === "task_storage_unavailable" && !error.message.includes("password"),
  );
});

test("unknown server error codes are replaced with a safe fallback", async () => {
  const client = createTaskClient({ fetcher: async () => response({ detail: { code: "secret-db-error" } }, 500) });
  await assert.rejects(client.list(sourceId), (error) => error.code === "request_failed" && error.status === 500);
});

test("malformed JSON, malformed contracts, wrong source, and wrong run are rejected", async (context) => {
  const cases = [
    { name: "bad JSON", fetcher: async () => new Response("not-json", { status: 202 }) },
    { name: "missing field", fetcher: async () => response({ ...run(), tool_call_count: undefined }, 202) },
    { name: "unknown provider", fetcher: async () => response(run({ provider: "unregistered-provider" }), 202) },
    { name: "wrong source", fetcher: async () => response(run({ source_id: "other-source" }), 202) },
  ];
  for (const item of cases) {
    await context.test(item.name, async () => {
      const client = createTaskClient({ fetcher: item.fetcher });
      await assert.rejects(client.submit({ source_id: sourceId, target_metric: "sales", target_date: "2026-10-09" }),
        (error) => error instanceof TaskClientError && error.code === "invalid_response");
    });
  }
  const detailClient = createTaskClient({
    fetcher: async () => response({ run: run({ investigation_run_id: "different-run" }), tool_calls: [], observations: [], evidence: [], diagnoses: [] }),
  });
  await assert.rejects(detailClient.detail(runId, sourceId),
    (error) => error instanceof TaskClientError && error.code === "invalid_response");
  const listClient = createTaskClient({ fetcher: async () => response({ items: [run({ source_id: "other-source" })], limit: 20, offset: 0 }) });
  await assert.rejects(listClient.list(sourceId),
    (error) => error instanceof TaskClientError && error.code === "invalid_response");
});

test("AbortSignal is forwarded and an aborted request stays a safe AbortError", async () => {
  const controller = new AbortController();
  const client = createTaskClient({ fetcher: async (_url, init) => {
    assert.equal(init.signal, controller.signal);
    throw new DOMException("private endpoint details", "AbortError");
  } });
  controller.abort();
  await assert.rejects(client.list(sourceId, { signal: controller.signal }),
    (error) => error instanceof DOMException && error.name === "AbortError" && !error.message.includes("private"));
});

test("AbortSignal during response body parsing remains an AbortError", async () => {
  const controller = new AbortController();
  const client = createTaskClient({ fetcher: async () => ({
    ok: true,
    status: 202,
    json: async () => {
      controller.abort();
      throw new DOMException("private response body details", "AbortError");
    },
  }) });
  await assert.rejects(
    client.submit({ source_id: sourceId, target_metric: "sales", target_date: "2026-10-09" }, { signal: controller.signal }),
    (error) => error instanceof DOMException && error.name === "AbortError" && !error.message.includes("private"),
  );
});

test("invalid pagination and request extras fail before network access", async () => {
  let calls = 0;
  const client = createTaskClient({ fetcher: async () => { calls += 1; return response(run(), 202); } });
  await assert.rejects(client.list(sourceId, { limit: 101 }), TypeError);
  await assert.rejects(client.list(sourceId, { offset: Number.MAX_SAFE_INTEGER + 1 }), TypeError);
  await assert.rejects(client.submit({ source_id: sourceId, target_metric: "sales", target_date: "2026-10-09", dsn: "secret" }), TypeError);
  await assert.rejects(client.submit({
    source_id: sourceId,
    target_metric: "sales",
    target_date: "2026-10-09",
    filters: { country: "US\u0085" },
  }), TypeError);
  assert.equal(calls, 0);
});
