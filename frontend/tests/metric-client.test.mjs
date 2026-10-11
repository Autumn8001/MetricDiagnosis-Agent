import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { join, resolve } from "node:path";
import test from "node:test";

const buildDirectory = process.env.METRICSLEUTH_METRIC_CLIENT_BUILD_DIR;
if (!buildDirectory) throw new Error("METRICSLEUTH_METRIC_CLIENT_BUILD_DIR is required");
const { createMetricClient, MetricClientError } = await import(
  pathToFileURL(join(resolve(buildDirectory), "metrics", "client.js")).href
);

const request = { source_id: "synthetic/store α", target_metric: "sales", target_date: "2026-10-10" };
const scanRequest = { source_id: request.source_id, target_date: request.target_date };
const id = "4a8b2cb3-9080-4e84-a96a-10a7f9115c70";
const ids = [
  id,
  "5b9c3cd4-a191-4f95-8ab7-b20b8a022d81",
  "6cad4de5-b2a2-40a6-9bc8-c31c9b133e92",
  "7dbe5ef6-c3b3-41b7-8cd9-d42dac244fa3",
  "8ecf6a07-d4c4-42c8-9dea-e53ebd3550b4",
  "9fd07b18-e5d5-43d9-8efb-f64fce4661c5",
];

function observation(overrides = {}) {
  return {
    metric: "sales",
    status: "normal",
    source_status: "ok",
    current_period_start: "2026-10-10",
    current_period_end: "2026-10-10",
    baseline_period_start: "2026-10-03",
    baseline_period_end: "2026-10-09",
    current_value: "100.00000000000000000000000001",
    baseline_value: "100.00000000000000000000000000",
    relative_change: "0.0000000000000000000000000001",
    unit: "USD",
    sample_size: "90071992547409931234567890",
    ...overrides,
  };
}

function result(overrides = {}) {
  return {
    source_id: request.source_id,
    provider: "synthetic",
    environment: "benchmark",
    data_version: "fixture-label-v1",
    data_version_kind: "label",
    persisted: false,
    scope: "source_global",
    target_metric: request.target_metric,
    target_date: request.target_date,
    comparison: "previous_7_days",
    queried_at: "2026-10-11T03:04:05.123456Z",
    query_reference: `metric-read:${id}`,
    observation: observation(),
    anomaly_candidate: false,
    ...overrides,
  };
}

function scanItem(metric, index, overrides = {}) {
  return result({
    target_metric: metric,
    query_reference: `metric-read:${ids[index]}`,
    observation: observation({ metric }),
    anomaly_candidate: false,
    ...overrides,
  });
}

function scanResult(items, overrides = {}) {
  return {
    source_id: scanRequest.source_id,
    provider: "synthetic",
    environment: "benchmark",
    data_version: "fixture-label-v1",
    data_version_kind: "label",
    persisted: false,
    scope: "source_global",
    target_date: scanRequest.target_date,
    comparison: "previous_7_days",
    snapshot_consistent: false,
    completed_at: "2026-10-11T03:04:05.123456Z",
    items,
    anomaly_candidate_metrics: [],
    ...overrides,
  };
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("GET returns exact decimal strings, sends only approved query values, and preserves nulls", async () => {
  const calls = [];
  const client = createMetricClient({
    baseUrl: "/root/",
    fetcher: async (url, init) => {
      calls.push({ url: new URL(url, "http://localhost"), init });
      return jsonResponse(result({
        observation: observation({ status: "inconclusive", baseline_value: null, relative_change: null }),
        anomaly_candidate: null,
      }));
    },
  });
  const value = await client.read(request);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.pathname, "/root/api/metrics/observation");
  assert.deepEqual([...calls[0].url.searchParams.keys()].sort(), ["source_id", "target_date", "target_metric"]);
  assert.equal(calls[0].url.searchParams.get("source_id"), request.source_id);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(Object.hasOwn(calls[0].init, "body"), false);
  assert.equal(value.observation.current_value, "100.00000000000000000000000001");
  assert.equal(value.observation.sample_size, "90071992547409931234567890");
  assert.equal(value.observation.baseline_value, null);
  assert.equal(value.observation.relative_change, null);
});

test("empty data and insufficient evidence remain null, never a fabricated normal result", async () => {
  const empty = createMetricClient({ fetcher: async () => jsonResponse(result({ observation: null, anomaly_candidate: null })) });
  assert.equal((await empty.read(request)).observation, null);
  const insufficient = createMetricClient({ fetcher: async () => jsonResponse(result({
    observation: observation({
      status: "insufficient_evidence", source_status: "insufficient_data", current_value: null,
      baseline_value: null, relative_change: null, sample_size: null,
    }),
    anomaly_candidate: null,
  })) });
  const value = await insufficient.read(request);
  assert.equal(value.observation.status, "insufficient_evidence");
  assert.equal(value.anomaly_candidate, null);
});

test("anomaly candidate matches only normal and anomalous observation states", async () => {
  for (const [status, candidate] of [["anomalous", true], ["normal", false], ["inconclusive", null], ["failed", null]]) {
    const client = createMetricClient({ fetcher: async () => jsonResponse(result({
      observation: observation({ status }), anomaly_candidate: candidate,
    })) });
    assert.equal((await client.read(request)).anomaly_candidate, candidate);
  }
});

test("normal and anomalous observations require current, baseline, and relative values", async (context) => {
  for (const status of ["normal", "anomalous"]) {
    for (const field of ["current_value", "baseline_value", "relative_change"]) {
      await context.test(`${status} with null ${field}`, async () => {
        const client = createMetricClient({ fetcher: async () => jsonResponse(result({
          observation: observation({ status, [field]: null }),
          anomaly_candidate: status === "anomalous",
        })) });
        await assert.rejects(client.read(request), (error) => error.code === "invalid_response");
      });
    }
  }
});

test("invalid local inputs fail before making a request", async () => {
  let calls = 0;
  const client = createMetricClient({ fetcher: async () => { calls += 1; return jsonResponse(result()); } });
  const invalid = [
    { ...request, source_id: "  " },
    { ...request, source_id: "x".repeat(129) },
    { ...request, target_metric: "\t" },
    { ...request, target_metric: "x".repeat(129) },
    { ...request, target_date: "2026-2-03" },
    { ...request, target_date: "2026-02-30" },
    { ...request, target_date: "0001-01-06" },
  ];
  for (const input of invalid) await assert.rejects(client.read(input), TypeError);
  assert.equal(calls, 0);
});

test("server failures expose only allowlisted codes, with no raw payload leakage", async () => {
  const client = createMetricClient({ fetcher: async () => jsonResponse({
    detail: { code: "metric_query_unavailable", error: "password=do-not-leak" },
    trace: "private response text",
  }, 503) });
  await assert.rejects(client.read(request), (error) => error instanceof MetricClientError
    && error.status === 503 && error.code === "metric_query_unavailable"
    && !error.message.includes("password") && !error.message.includes("private"));
  const unknown = createMetricClient({ fetcher: async () => jsonResponse({ detail: { code: "db-password-secret" } }, 500) });
  await assert.rejects(unknown.read(request), (error) => error.code === "request_failed" && !error.message.includes("secret"));
});

test("network errors and aborts are safe and requests are never retried", async () => {
  let calls = 0;
  const network = createMetricClient({ fetcher: async () => { calls += 1; throw new Error("secret endpoint"); } });
  await assert.rejects(network.read(request), (error) => error.code === "network_error" && !error.message.includes("secret"));
  assert.equal(calls, 1);

  const controller = new AbortController();
  const aborted = createMetricClient({ fetcher: async (_url, init) => {
    assert.equal(init.signal, controller.signal);
    throw new DOMException("private abort detail", "AbortError");
  } });
  await assert.rejects(aborted.read(request, { signal: controller.signal }),
    (error) => error instanceof DOMException && error.name === "AbortError" && !error.message.includes("private"));
});

test("an abort that races with a successful response is honored after parsing", async () => {
  const controller = new AbortController();
  let calls = 0;
  const client = createMetricClient({ fetcher: async () => {
    calls += 1;
    controller.abort();
    return jsonResponse(result());
  } });
  await assert.rejects(client.read(request, { signal: controller.signal }),
    (error) => error instanceof DOMException && error.name === "AbortError");
  assert.equal(calls, 1);
});

test("wrong request identity, periods, UTC timestamp, or query reference are rejected", async (context) => {
  const cases = [
    ["wrong source", { source_id: "other" }],
    ["wrong metric", { target_metric: "orders" }],
    ["wrong target date", { target_date: "2026-10-09" }],
    ["wrong current period", { observation: observation({ current_period_end: "2026-10-09" }) }],
    ["wrong baseline period", { observation: observation({ baseline_period_start: "2026-10-02" }) }],
    ["non-UTC timestamp", { queried_at: "2026-10-11T03:04:05+08:00" }],
    ["impossible UTC timestamp date", { queried_at: "2026-02-30T03:04:05Z" }],
    ["bad query reference", { query_reference: "metric-read:not-a-uuid" }],
  ];
  for (const [name, overrides] of cases) {
    await context.test(name, async () => {
      const client = createMetricClient({ fetcher: async () => jsonResponse(result(overrides)) });
      await assert.rejects(client.read(request), (error) => error.code === "invalid_response");
    });
  }
});

test("extra fields, floats, non-finite numbers, and inconsistent candidates are rejected", async (context) => {
  const cases = [
    ["extra response field", { response: { ...result(), debug: "unexpected" } }],
    ["extra observation field", { response: result({ observation: observation({ persisted: true }) }) }],
    ["JSON float instead of decimal string", { response: result({ observation: observation({ current_value: 1.25 }) }) }],
    ["NaN text", { response: result({ observation: observation({ relative_change: "NaN" }) }) }],
    ["inconsistent candidate", { response: result({ anomaly_candidate: true }) }],
    ["unknown environment", { response: result({ environment: "production" }) }],
  ];
  for (const [name, item] of cases) {
    await context.test(name, async () => {
      const client = createMetricClient({ fetcher: async () => jsonResponse(item.response) });
      await assert.rejects(client.read(request), (error) => error.code === "invalid_response");
    });
  }
});

test("malformed JSON and wrong success status are classified safely", async () => {
  const malformed = createMetricClient({ fetcher: async () => new Response("token=private", { status: 200 }) });
  await assert.rejects(malformed.read(request), (error) => error.code === "invalid_response" && !error.message.includes("token"));
  const wrongStatus = createMetricClient({ fetcher: async () => jsonResponse(result(), 201) });
  await assert.rejects(wrongStatus.read(request), (error) => error.code === "invalid_response" && error.status === 201);
});

test("scan sends only source and date, and validates Synthetic values, candidates, and nulls", async () => {
  const payload = scanResult([
    scanItem("sales", 0, { observation: observation({ metric: "sales", status: "anomalous" }), anomaly_candidate: true }),
    scanItem("orders", 1, { observation: observation({ metric: "orders", status: "insufficient_evidence", current_value: null, baseline_value: null, relative_change: null }), anomaly_candidate: null }),
  ], { anomaly_candidate_metrics: ["sales"] });
  const calls = [];
  const client = createMetricClient({
    baseUrl: "/root/",
    fetcher: async (url, init) => {
      calls.push({ url: new URL(url, "http://localhost"), init });
      return jsonResponse(payload);
    },
  });
  const value = await client.scan(scanRequest);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.pathname, "/root/api/metrics/scan");
  assert.deepEqual([...calls[0].url.searchParams.keys()].sort(), ["source_id", "target_date"]);
  assert.equal(calls[0].url.searchParams.get("source_id"), scanRequest.source_id);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(Object.hasOwn(calls[0].init, "body"), false);
  assert.equal(value.items.length, 2);
  assert.deepEqual(value.anomaly_candidate_metrics, ["sales"]);
  assert.equal(value.items[1].observation.current_value, null);
  assert.equal(value.snapshot_consistent, false);
});

test("scan accepts Olist validation data with inconclusive metrics and no candidates", async () => {
  const items = ["merchandise_gmv", "orders", "olist_aov"].map((metric, index) => scanItem(metric, index, {
    provider: "olist",
    environment: "validation",
    data_version: "olist-static-validation-v1",
    observation: observation({ metric, status: "inconclusive" }),
    anomaly_candidate: null,
  }));
  const payload = scanResult(items, {
    provider: "olist",
    environment: "validation",
    data_version: "olist-static-validation-v1",
  });
  const client = createMetricClient({ fetcher: async () => jsonResponse(payload) });
  const value = await client.scan(scanRequest);
  assert.deepEqual(value.items.map((item) => item.target_metric), ["merchandise_gmv", "orders", "olist_aov"]);
  assert.deepEqual(value.anomaly_candidate_metrics, []);
  assert.ok(value.items.every((item) => item.anomaly_candidate === null));
});

test("scan rejects malformed batch identity, metadata, candidates, and bounded shape", async (context) => {
  const validItems = [
    scanItem("sales", 0, { observation: observation({ metric: "sales", status: "anomalous" }), anomaly_candidate: true }),
    scanItem("orders", 1, { observation: observation({ metric: "orders", status: "inconclusive" }), anomaly_candidate: null }),
  ];
  const base = scanResult(validItems, { anomaly_candidate_metrics: ["sales"] });
  const cases = [
    ["unknown top-level field", (body) => { body.debug = "secret"; }],
    ["non-UTC completion time", (body) => { body.completed_at = "2026-10-11T11:04:05+08:00"; }],
    ["snapshot claim", (body) => { body.snapshot_consistent = true; }],
    ["root source mismatch", (body) => { body.source_id = "other-source"; }],
    ["root version mismatch", (body) => { body.data_version = "other-version"; }],
    ["item source mismatch", (body) => { body.items[0].source_id = "other-source"; }],
    ["item date mismatch", (body) => { body.items[0].target_date = "2026-10-09"; }],
    ["item provider mismatch", (body) => { body.items[0].provider = "olist"; }],
    ["item environment mismatch", (body) => { body.items[0].environment = "validation"; }],
    ["item version mismatch", (body) => { body.items[0].data_version = "other-version"; }],
    ["blank nested metric id", (body) => { body.items[0].target_metric = " "; }],
    ["oversized nested metric id", (body) => { body.items[0].target_metric = "x".repeat(129); }],
    ["duplicate metric", (body) => { body.items[1].target_metric = "sales"; body.items[1].observation.metric = "sales"; }],
    ["duplicate query reference", (body) => { body.items[1].query_reference = body.items[0].query_reference; }],
    ["forged candidate", (body) => { body.anomaly_candidate_metrics = ["orders"]; }],
    ["missing candidate", (body) => { body.anomaly_candidate_metrics = []; }],
    ["duplicate candidate", (body) => { body.anomaly_candidate_metrics = ["sales", "sales"]; }],
    ["candidate ordering", (body) => { body.items.unshift(scanItem("sessions", 2, { observation: observation({ metric: "sessions", status: "anomalous" }), anomaly_candidate: true })); body.anomaly_candidate_metrics = ["sales", "sessions"]; }],
    ["empty item list", (body) => { body.items = []; }],
    ["more than five items", (body) => { body.items = Array.from({ length: 6 }, (_, index) => scanItem(`metric-${index}`, index)); }],
  ];
  for (const [name, mutate] of cases) {
    await context.test(name, async () => {
      const body = structuredClone(base);
      mutate(body);
      const client = createMetricClient({ fetcher: async () => jsonResponse(body) });
      await assert.rejects(client.scan(scanRequest), (error) => error.code === "invalid_response");
    });
  }
});

test("scan invalid inputs fail before fetch", async () => {
  let calls = 0;
  const client = createMetricClient({ fetcher: async () => { calls += 1; return jsonResponse(scanResult([scanItem("sales", 0)])); } });
  const invalid = [
    { ...scanRequest, source_id: " " },
    { ...scanRequest, source_id: "x".repeat(129) },
    { ...scanRequest, target_date: "2026-2-03" },
    { ...scanRequest, target_date: "2026-02-30" },
    { ...scanRequest, target_date: "0001-01-06" },
  ];
  for (const input of invalid) await assert.rejects(client.scan(input), TypeError);
  assert.equal(calls, 0);
});

test("scan safe errors, unknown server errors, aborts, and network failures do not leak or retry", async () => {
  for (const code of ["no_supported_metrics", "metric_scan_over_budget"]) {
    const safe = createMetricClient({ fetcher: async () => jsonResponse({ detail: { code, password: "secret" } }, 400) });
    await assert.rejects(safe.scan(scanRequest), (error) => error instanceof MetricClientError
      && error.code === code && !error.message.includes("secret"));
  }

  let calls = 0;
  const unknown = createMetricClient({ fetcher: async () => { calls += 1; return jsonResponse({ detail: { code: "db-password-secret" } }, 503); } });
  await assert.rejects(unknown.scan(scanRequest), (error) => error.code === "request_failed" && !error.message.includes("secret"));
  assert.equal(calls, 1);

  const network = createMetricClient({ fetcher: async () => { calls += 1; throw new Error("private endpoint"); } });
  await assert.rejects(network.scan(scanRequest), (error) => error.code === "network_error" && !error.message.includes("private"));
  assert.equal(calls, 2);

  const controller = new AbortController();
  const aborted = createMetricClient({ fetcher: async (_url, init) => {
    assert.equal(init.signal, controller.signal);
    throw new DOMException("private detail", "AbortError");
  } });
  await assert.rejects(aborted.scan(scanRequest, { signal: controller.signal }),
    (error) => error instanceof DOMException && error.name === "AbortError" && !error.message.includes("private"));
});

test("scan malformed JSON and non-200 success status are classified safely", async () => {
  const malformed = createMetricClient({ fetcher: async () => new Response("token=private", { status: 200 }) });
  await assert.rejects(malformed.scan(scanRequest),
    (error) => error.code === "invalid_response" && !error.message.includes("token"));
  const wrongStatus = createMetricClient({ fetcher: async () => jsonResponse(scanResult([scanItem("sales", 0)]), 201) });
  await assert.rejects(wrongStatus.scan(scanRequest),
    (error) => error.code === "invalid_response" && error.status === 201);
});

test("scan honors abort that races with a successful response", async () => {
  const controller = new AbortController();
  let calls = 0;
  const payload = scanResult([scanItem("sales", 0)]);
  const client = createMetricClient({ fetcher: async () => {
    calls += 1;
    controller.abort();
    return jsonResponse(payload);
  } });
  await assert.rejects(client.scan(scanRequest, { signal: controller.signal }),
    (error) => error instanceof DOMException && error.name === "AbortError");
  assert.equal(calls, 1);
});
