import type {
  MetricEnvironment,
  MetricObservationStatus,
  MetricObservationView,
  MetricProvider,
  MetricReadResponse,
  MetricScanResponse,
} from "./contracts";

export type MetricReadErrorCode =
  | "metric_service_unavailable"
  | "metric_query_unavailable"
  | "invalid_metric_request"
  | "source_not_found"
  | "metric_not_supported"
  | "no_supported_metrics"
  | "metric_scan_over_budget"
  | "network_error"
  | "invalid_response"
  | "request_failed";

const SAFE_SERVER_CODES = new Set<MetricReadErrorCode>([
  "metric_service_unavailable",
  "metric_query_unavailable",
  "invalid_metric_request",
  "source_not_found",
  "metric_not_supported",
  "no_supported_metrics",
  "metric_scan_over_budget",
]);
const PROVIDERS = new Set<MetricProvider>(["postgresql", "shopify", "olist", "synthetic"]);
const ENVIRONMENTS = new Set<MetricEnvironment>(["live", "sandbox", "benchmark", "validation"]);
const OBSERVATION_STATUSES = new Set<MetricObservationStatus>([
  "normal", "anomalous", "inconclusive", "insufficient_evidence", "failed",
]);
const DECIMAL = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;
const DATE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const UTC_TIMESTAMP = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?(?:Z|\+00:00)$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DAY_MS = 24 * 60 * 60 * 1000;

export class MetricClientError extends Error {
  readonly status: number | null;
  readonly code: MetricReadErrorCode;

  constructor(status: number | null, code: MetricReadErrorCode) {
    super(code);
    this.name = "MetricClientError";
    this.status = status;
    this.code = code;
  }
}

export interface MetricReadInput {
  source_id: string;
  target_metric: string;
  target_date: string;
}

export interface MetricScanInput {
  source_id: string;
  target_date: string;
}

export interface MetricReadRequestOptions {
  signal?: AbortSignal;
}

export interface MetricClientOptions {
  baseUrl?: string;
  fetcher?: typeof fetch;
}

function invalidResponse(): never {
  throw new MetricClientError(null, "invalid_response");
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return invalidResponse();
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): void {
  const expected = new Set(keys);
  if (Object.keys(value).length !== expected.size || Object.keys(value).some((key) => !expected.has(key))) {
    invalidResponse();
  }
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isDate(value: unknown): value is string {
  if (typeof value !== "string" || !DATE.test(value)) return false;
  const instant = Date.parse(`${value}T00:00:00.000Z`);
  return Number.isFinite(instant) && new Date(instant).toISOString().slice(0, 10) === value;
}

function isUtcTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !UTC_TIMESTAMP.test(value) || !isDate(value.slice(0, 10))) return false;
  return Number.isFinite(Date.parse(value));
}

function dateMinusDays(value: string, days: number): string {
  const instant = Date.parse(`${value}T00:00:00.000Z`) - days * DAY_MS;
  return new Date(instant).toISOString().slice(0, 10);
}

function validRequestDate(value: unknown): value is string {
  if (!isDate(value)) return false;
  return dateMinusDays(value, 7) >= "0001-01-01";
}

function identifier(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && Array.from(value).length <= 128;
}

function validateInput(value: MetricReadInput): MetricReadInput {
  if (value === null || typeof value !== "object"
    || !identifier(value.source_id)
    || !identifier(value.target_metric)
    || !validRequestDate(value.target_date)) {
    throw new TypeError("Invalid metric read request");
  }
  return {
    source_id: value.source_id,
    target_metric: value.target_metric,
    target_date: value.target_date,
  };
}

function validateScanInput(value: MetricScanInput): MetricScanInput {
  if (value === null || typeof value !== "object"
    || !identifier(value.source_id)
    || !validRequestDate(value.target_date)) {
    throw new TypeError("Invalid metric scan request");
  }
  return { source_id: value.source_id, target_date: value.target_date };
}

function validDecimal(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && DECIMAL.test(value));
}

function validateObservation(value: unknown, metric: string, targetDate: string): MetricObservationView {
  const row = record(value);
  exactKeys(row, [
    "metric", "status", "source_status", "current_period_start", "current_period_end",
    "baseline_period_start", "baseline_period_end", "current_value", "baseline_value",
    "relative_change", "unit", "sample_size",
  ]);
  if (row.metric !== metric || typeof row.status !== "string" || !OBSERVATION_STATUSES.has(row.status as MetricObservationStatus)
    || !nonEmptyString(row.source_status) || !nonEmptyString(row.unit)
    || row.current_period_start !== targetDate || row.current_period_end !== targetDate
    || row.baseline_period_end !== dateMinusDays(targetDate, 1)
    || row.baseline_period_start !== dateMinusDays(targetDate, 7)
    || !validDecimal(row.current_value) || !validDecimal(row.baseline_value)
    || !validDecimal(row.relative_change) || !validDecimal(row.sample_size)) {
    return invalidResponse();
  }
  if ((row.status === "normal" || row.status === "anomalous")
    && (row.current_value === null || row.baseline_value === null || row.relative_change === null)) {
    return invalidResponse();
  }
  return row as unknown as MetricObservationView;
}

function validateResponse(value: unknown, input: MetricReadInput): MetricReadResponse {
  const row = record(value);
  exactKeys(row, [
    "source_id", "provider", "environment", "data_version", "data_version_kind", "persisted",
    "scope", "target_metric", "target_date", "comparison", "queried_at", "query_reference",
    "observation", "anomaly_candidate",
  ]);
  if (row.source_id !== input.source_id || row.target_metric !== input.target_metric
    || row.target_date !== input.target_date
    || typeof row.provider !== "string" || !PROVIDERS.has(row.provider as MetricProvider)
    || typeof row.environment !== "string" || !ENVIRONMENTS.has(row.environment as MetricEnvironment)
    || !nonEmptyString(row.data_version) || row.data_version_kind !== "label"
    || row.persisted !== false || row.scope !== "source_global"
    || row.comparison !== "previous_7_days"
    || !isUtcTimestamp(row.queried_at)
    || !nonEmptyString(row.query_reference)
    || !row.query_reference.startsWith("metric-read:")
    || !UUID.test(row.query_reference.slice("metric-read:".length))) {
    return invalidResponse();
  }

  const observation = row.observation === null
    ? null
    : validateObservation(row.observation, input.target_metric, input.target_date);
  const expectedCandidate = observation?.status === "anomalous"
    ? true
    : observation?.status === "normal"
      ? false
      : null;
  if (row.anomaly_candidate !== expectedCandidate) return invalidResponse();

  return row as unknown as MetricReadResponse;
}

function validateScanResponse(value: unknown, input: MetricScanInput): MetricScanResponse {
  const row = record(value);
  exactKeys(row, [
    "source_id", "provider", "environment", "data_version", "data_version_kind", "persisted",
    "scope", "target_date", "comparison", "snapshot_consistent", "completed_at", "items",
    "anomaly_candidate_metrics",
  ]);
  if (row.source_id !== input.source_id || row.target_date !== input.target_date
    || typeof row.provider !== "string" || !PROVIDERS.has(row.provider as MetricProvider)
    || typeof row.environment !== "string" || !ENVIRONMENTS.has(row.environment as MetricEnvironment)
    || !nonEmptyString(row.data_version) || row.data_version_kind !== "label"
    || row.persisted !== false || row.scope !== "source_global"
    || row.comparison !== "previous_7_days" || row.snapshot_consistent !== false
    || !isUtcTimestamp(row.completed_at)
    || !Array.isArray(row.items) || row.items.length < 1 || row.items.length > 5
    || !Array.isArray(row.anomaly_candidate_metrics)) {
    return invalidResponse();
  }

  const seenMetrics = new Set<string>();
  const seenReferences = new Set<string>();
  const items = row.items.map((value): MetricReadResponse => {
    const candidate = record(value);
    if (!identifier(candidate.target_metric)) return invalidResponse();
    const item = validateResponse(value, {
      source_id: input.source_id,
      target_metric: candidate.target_metric,
      target_date: input.target_date,
    });
    if (item.provider !== row.provider || item.environment !== row.environment
      || item.data_version !== row.data_version
      || seenMetrics.has(item.target_metric) || seenReferences.has(item.query_reference)) {
      return invalidResponse();
    }
    seenMetrics.add(item.target_metric);
    seenReferences.add(item.query_reference);
    return item;
  });

  const expectedCandidates = items
    .filter((item) => item.anomaly_candidate === true)
    .map((item) => item.target_metric);
  if (row.anomaly_candidate_metrics.length !== expectedCandidates.length
    || row.anomaly_candidate_metrics.some((metric, index) => metric !== expectedCandidates[index])) {
    return invalidResponse();
  }

  return row as unknown as MetricScanResponse;
}

function serverErrorCode(payload: unknown): MetricReadErrorCode {
  try {
    const body = record(payload);
    const detail = record(body.detail);
    const code = detail.code;
    return typeof code === "string" && SAFE_SERVER_CODES.has(code as MetricReadErrorCode)
      ? code as MetricReadErrorCode
      : "request_failed";
  } catch {
    return "request_failed";
  }
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError");
}

async function requestJson(
  url: string,
  fetcher: typeof fetch,
  signal?: AbortSignal,
): Promise<{ payload: unknown }> {
  let response: Response;
  try {
    response = await fetcher(url, {
      method: "GET",
      headers: { accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted || isAbortError(error)) throw abortError();
    throw new MetricClientError(null, "network_error");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (signal?.aborted || isAbortError(error)) throw abortError();
    if (response.ok) throw new MetricClientError(response.status, "invalid_response");
    throw new MetricClientError(response.status, "request_failed");
  }
  if (response.ok && signal?.aborted) throw abortError();
  if (!response.ok) throw new MetricClientError(response.status, serverErrorCode(payload));
  if (response.status !== 200) throw new MetricClientError(response.status, "invalid_response");
  return { payload };
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function createMetricClient(options: MetricClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const fetcher = options.fetcher ?? globalThis.fetch;
  if (typeof fetcher !== "function") throw new TypeError("A Fetch implementation is required");

  return {
    async read(input: MetricReadInput, requestOptions: MetricReadRequestOptions = {}): Promise<MetricReadResponse> {
      const cleanInput = validateInput(input);
      const query = new URLSearchParams({
        source_id: cleanInput.source_id,
        target_metric: cleanInput.target_metric,
        target_date: cleanInput.target_date,
      });
      const { payload } = await requestJson(
        `${baseUrl}/api/metrics/observation?${query.toString()}`,
        fetcher,
        requestOptions.signal,
      );
      return validateResponse(payload, cleanInput);
    },

    async scan(input: MetricScanInput, requestOptions: MetricReadRequestOptions = {}): Promise<MetricScanResponse> {
      const cleanInput = validateScanInput(input);
      const query = new URLSearchParams({
        source_id: cleanInput.source_id,
        target_date: cleanInput.target_date,
      });
      const { payload } = await requestJson(
        `${baseUrl}/api/metrics/scan?${query.toString()}`,
        fetcher,
        requestOptions.signal,
      );
      return validateScanResponse(payload, cleanInput);
    },
  };
}
