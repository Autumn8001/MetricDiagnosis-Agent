import type {
  DiagnosisChangeView,
  DiagnosisView,
  DataSourceEnvironment,
  DataSourceProvider,
  DecimalValue,
  EvidenceView,
  InvestigationTaskCreate,
  InvestigationSourcesResponse,
  InvestigationSourceView,
  JsonValue,
  ObservationView,
  TaskApiErrorCode,
  TaskDetailResponse,
  TaskListResponse,
  TaskRunStatus,
  TaskRunView,
  ToolCallView,
} from "./contracts.js";

export type TaskClientErrorCode = TaskApiErrorCode;

export class TaskClientError extends Error {
  readonly status: number | null;
  readonly code: TaskClientErrorCode;

  constructor(status: number | null, code: TaskClientErrorCode) {
    super(`Investigation request failed (${status ?? "network"}: ${code})`);
    this.name = "TaskClientError";
    this.status = status;
    this.code = code;
  }
}

export interface TaskClientOptions {
  /** API root, for example "" or "/api-root". Defaults to the current origin. */
  baseUrl?: string;
  /** Injectable transport for offline tests and alternate same-origin setups. */
  fetcher?: typeof fetch;
}

export interface TaskListOptions {
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

export interface TaskRequestOptions {
  signal?: AbortSignal;
}

const RUN_STATUSES = new Set<TaskRunStatus>([
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
]);
const SOURCE_PROVIDERS = new Set<DataSourceProvider>(["postgresql", "shopify", "olist", "synthetic"]);
const SOURCE_ENVIRONMENTS = new Set<DataSourceEnvironment>(["live", "sandbox", "benchmark", "validation"]);

const API_ERROR_CODES = new Set<TaskApiErrorCode>([
  "task_service_unavailable",
  "source_catalog_unavailable",
  "invalid_task_request",
  "task_storage_unavailable",
  "source_not_found",
  "metric_or_dimensions_not_supported",
  "invalid_pagination",
  "investigation_not_found",
]);

const DECIMAL_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function expectRecord(value: unknown, path: string): UnknownRecord {
  if (!isRecord(value)) invalid(path);
  return value;
}

function exactKeys(value: UnknownRecord, keys: readonly string[], path: string): void {
  const expected = new Set(keys);
  if (Object.keys(value).length !== keys.length || Object.keys(value).some((key) => !expected.has(key))) {
    invalid(path);
  }
}

function invalid(_path: string): never {
  // Keep diagnostics local and structural; never include payload values.
  throw new TaskClientError(null, "invalid_response");
}

function stringValue(value: unknown, path: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) invalid(path);
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  return value === null ? null : stringValue(value, path, true);
}

function integerValue(value: unknown, path: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) invalid(path);
  return value as number;
}

function decimalValue(value: unknown, path: string): DecimalValue {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) invalid(path);
    return value;
  }
  if (typeof value === "string" && DECIMAL_PATTERN.test(value)) return value;
  return invalid(path);
}

function nullableDecimal(value: unknown, path: string): DecimalValue | null {
  return value === null ? null : decimalValue(value, path);
}

function dateValue(value: unknown, path: string): string {
  const date = stringValue(value, path);
  if (!ISO_DATE_PATTERN.test(date)) invalid(path);
  const parsed = new Date(`${date}T00:00:00.000Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== date) invalid(path);
  return date;
}

function nullableDate(value: unknown, path: string): string | null {
  return value === null ? null : dateValue(value, path);
}

function dateTimeValue(value: unknown, path: string): string {
  const dateTime = stringValue(value, path);
  if (!/^\d{4}-\d{2}-\d{2}T/.test(dateTime) || Number.isNaN(Date.parse(dateTime))) invalid(path);
  return dateTime;
}

function stringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) invalid(path);
  return value.map((item, index) => stringValue(item, `${path}[${index}]`, true));
}

function jsonValue(value: unknown, path: string): JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map((item, index) => jsonValue(item, `${path}[${index}]`));
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, jsonValue(item, `${path}.${key}`)]),
    );
  }
  return invalid(path);
}

function jsonRecord(value: unknown, path: string): Record<string, JsonValue> {
  const record = expectRecord(value, path);
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, jsonValue(item, `${path}.${key}`)]));
}

function stringRecord(value: unknown, path: string): Record<string, string> {
  const record = expectRecord(value, path);
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, stringValue(item, `${path}.${key}`, true)]));
}

function hasControlCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0);
    return codePoint !== undefined && (codePoint <= 0x1f || (codePoint >= 0x7f && codePoint <= 0x9f));
  });
}

const RUN_KEYS = [
  "investigation_run_id", "source_id", "environment", "provider", "status", "requested_metric",
  "requested_at", "started_at", "finished_at", "data_version", "query_reference", "failure_code",
  "tool_call_count", "observation_count", "evidence_count", "diagnosis_count",
] as const;

function validateRun(value: unknown, expectedSourceId: string, expectedRunId?: string): TaskRunView {
  const row = expectRecord(value, "run");
  exactKeys(row, RUN_KEYS, "run");
  const sourceId = stringValue(row.source_id, "run.source_id");
  const runId = stringValue(row.investigation_run_id, "run.investigation_run_id");
  if (sourceId !== expectedSourceId || (expectedRunId !== undefined && runId !== expectedRunId)) invalid("run identity");
  const status = stringValue(row.status, "run.status");
  if (!RUN_STATUSES.has(status as TaskRunStatus)) invalid("run.status");
  const provider = stringValue(row.provider, "run.provider");
  if (!SOURCE_PROVIDERS.has(provider as DataSourceProvider)) invalid("run.provider");
  const environment = stringValue(row.environment, "run.environment");
  if (!SOURCE_ENVIRONMENTS.has(environment as DataSourceEnvironment)) invalid("run.environment");
  return {
    investigation_run_id: runId,
    source_id: sourceId,
    environment: environment as DataSourceEnvironment,
    provider: provider as DataSourceProvider,
    status: status as TaskRunStatus,
    requested_metric: stringValue(row.requested_metric, "run.requested_metric"),
    requested_at: dateTimeValue(row.requested_at, "run.requested_at"),
    started_at: row.started_at === null ? null : dateTimeValue(row.started_at, "run.started_at"),
    finished_at: row.finished_at === null ? null : dateTimeValue(row.finished_at, "run.finished_at"),
    data_version: nullableString(row.data_version, "run.data_version"),
    query_reference: nullableString(row.query_reference, "run.query_reference"),
    failure_code: nullableString(row.failure_code, "run.failure_code"),
    tool_call_count: integerValue(row.tool_call_count, "run.tool_call_count"),
    observation_count: integerValue(row.observation_count, "run.observation_count"),
    evidence_count: integerValue(row.evidence_count, "run.evidence_count"),
    diagnosis_count: integerValue(row.diagnosis_count, "run.diagnosis_count"),
  };
}
function validateToolCall(value: unknown): ToolCallView {
  const row = expectRecord(value, "tool call");
  exactKeys(row, ["tool_call_id", "tool_name", "status", "arguments", "data_version", "query_reference", "result_reference", "requested_at"], "tool call");
  return {
    tool_call_id: stringValue(row.tool_call_id, "tool_call_id"),
    tool_name: stringValue(row.tool_name, "tool_name"),
    status: stringValue(row.status, "tool_call.status"),
    arguments: jsonRecord(row.arguments, "tool_call.arguments"),
    data_version: nullableString(row.data_version, "tool_call.data_version"),
    query_reference: nullableString(row.query_reference, "tool_call.query_reference"),
    result_reference: nullableString(row.result_reference, "tool_call.result_reference"),
    requested_at: dateTimeValue(row.requested_at, "tool_call.requested_at"),
  };
}

function validateSource(value: unknown): InvestigationSourceView {
  const row = expectRecord(value, "source");
  exactKeys(row, ["source_id", "display_name", "provider", "environment", "data_version", "metrics"], "source");
  if (!SOURCE_PROVIDERS.has(row.provider as DataSourceProvider) ||
      !SOURCE_ENVIRONMENTS.has(row.environment as DataSourceEnvironment) || !Array.isArray(row.metrics)) {
    invalid("source");
  }
  const metrics = row.metrics.map((value) => {
    const metric = expectRecord(value, "metric capability");
    exactKeys(metric, ["metric_id", "supported", "grain", "dimensions", "unavailable_reason"], "metric capability");
    if (typeof metric.supported !== "boolean") invalid("metric capability");
    return {
      metric_id: stringValue(metric.metric_id, "metric_id"),
      supported: metric.supported,
      grain: stringArray(metric.grain, "grain"),
      dimensions: stringArray(metric.dimensions, "dimensions"),
      unavailable_reason: nullableString(metric.unavailable_reason, "unavailable_reason"),
    };
  });
  if (new Set(metrics.map((metric) => metric.metric_id)).size !== metrics.length) invalid("duplicate metric");
  return {
    source_id: stringValue(row.source_id, "source_id"),
    display_name: stringValue(row.display_name, "display_name"),
    provider: row.provider as DataSourceProvider,
    environment: row.environment as DataSourceEnvironment,
    data_version: stringValue(row.data_version, "data_version"),
    metrics,
  };
}

function validateObservation(value: unknown): ObservationView {
  const row = expectRecord(value, "observation");
  exactKeys(row, [
    "observation_id", "tool_call_id", "metric", "status", "source_status", "current_period_start",
    "current_period_end", "baseline_period_start", "baseline_period_end", "filters", "group_by",
    "dimensions", "current_value", "baseline_value", "relative_change", "unit", "sample_size",
    "query_reference", "data_version", "error_code", "created_at",
  ], "observation");
  return {
    observation_id: stringValue(row.observation_id, "observation_id"),
    tool_call_id: nullableString(row.tool_call_id, "observation.tool_call_id"),
    metric: stringValue(row.metric, "observation.metric"),
    status: stringValue(row.status, "observation.status"),
    source_status: nullableString(row.source_status, "observation.source_status"),
    current_period_start: nullableDate(row.current_period_start, "observation.current_period_start"),
    current_period_end: nullableDate(row.current_period_end, "observation.current_period_end"),
    baseline_period_start: nullableDate(row.baseline_period_start, "observation.baseline_period_start"),
    baseline_period_end: nullableDate(row.baseline_period_end, "observation.baseline_period_end"),
    filters: jsonRecord(row.filters, "observation.filters"),
    group_by: stringArray(row.group_by, "observation.group_by"),
    dimensions: jsonRecord(row.dimensions, "observation.dimensions"),
    current_value: nullableDecimal(row.current_value, "observation.current_value"),
    baseline_value: nullableDecimal(row.baseline_value, "observation.baseline_value"),
    relative_change: nullableDecimal(row.relative_change, "observation.relative_change"),
    unit: nullableString(row.unit, "observation.unit"),
    sample_size: nullableDecimal(row.sample_size, "observation.sample_size"),
    query_reference: nullableString(row.query_reference, "observation.query_reference"),
    data_version: nullableString(row.data_version, "observation.data_version"),
    error_code: nullableString(row.error_code, "observation.error_code"),
    created_at: dateTimeValue(row.created_at, "observation.created_at"),
  };
}

function validateEvidence(value: unknown): EvidenceView {
  const row = expectRecord(value, "evidence");
  exactKeys(row, ["evidence_id", "observation_id", "tool_call_id", "role", "data_version", "query_reference", "created_at"], "evidence");
  return {
    evidence_id: stringValue(row.evidence_id, "evidence_id"),
    observation_id: stringValue(row.observation_id, "evidence.observation_id"),
    tool_call_id: nullableString(row.tool_call_id, "evidence.tool_call_id"),
    role: stringValue(row.role, "evidence.role"),
    data_version: nullableString(row.data_version, "evidence.data_version"),
    query_reference: nullableString(row.query_reference, "evidence.query_reference"),
    created_at: dateTimeValue(row.created_at, "evidence.created_at"),
  };
}

function validateDiagnosisChange(value: unknown): DiagnosisChangeView | null {
  if (value === null) return null;
  const row = expectRecord(value, "diagnosis.change");
  exactKeys(row, ["current_value", "baseline_value", "relative_change", "unit", "evidence_id"], "diagnosis.change");
  return {
    current_value: nullableDecimal(row.current_value, "diagnosis.change.current_value"),
    baseline_value: nullableDecimal(row.baseline_value, "diagnosis.change.baseline_value"),
    relative_change: nullableDecimal(row.relative_change, "diagnosis.change.relative_change"),
    unit: stringValue(row.unit, "diagnosis.change.unit", true),
    evidence_id: stringValue(row.evidence_id, "diagnosis.change.evidence_id"),
  };
}

function validateDiagnosis(value: unknown): DiagnosisView {
  const row = expectRecord(value, "diagnosis");
  exactKeys(row, ["diagnosis_id", "status", "target_metric", "primary_driver", "affected_scope", "change", "evidence_ids", "confidence", "limitations", "data_version", "query_reference", "created_at"], "diagnosis");
  return {
    diagnosis_id: stringValue(row.diagnosis_id, "diagnosis_id"),
    status: stringValue(row.status, "diagnosis.status"),
    target_metric: stringValue(row.target_metric, "diagnosis.target_metric"),
    primary_driver: nullableString(row.primary_driver, "diagnosis.primary_driver"),
    affected_scope: stringRecord(row.affected_scope, "diagnosis.affected_scope"),
    change: validateDiagnosisChange(row.change),
    evidence_ids: stringArray(row.evidence_ids, "diagnosis.evidence_ids"),
    confidence: nullableDecimal(row.confidence, "diagnosis.confidence"),
    limitations: stringArray(row.limitations, "diagnosis.limitations"),
    data_version: nullableString(row.data_version, "diagnosis.data_version"),
    query_reference: nullableString(row.query_reference, "diagnosis.query_reference"),
    created_at: dateTimeValue(row.created_at, "diagnosis.created_at"),
  };
}

function safeApiCode(value: unknown): TaskApiErrorCode | null {
  return typeof value === "string" && API_ERROR_CODES.has(value as TaskApiErrorCode)
    ? value as TaskApiErrorCode
    : null;
}

function fallbackCodeForStatus(status: number): TaskApiErrorCode {
  if (status === 422) return "invalid_task_request";
  return "request_failed";
}

async function responseJson(response: Response): Promise<unknown> {
  try {
    return await response.json() as unknown;
  } catch {
    throw new TaskClientError(response.status, "invalid_response");
  }
}

function throwHttpError(response: Response, payload: unknown): never {
  const detail = isRecord(payload) ? payload.detail : undefined;
  const code = isRecord(detail) ? safeApiCode(detail.code) : null;
  throw new TaskClientError(response.status, code ?? fallbackCodeForStatus(response.status));
}

function validateTaskCreate(payload: InvestigationTaskCreate): InvestigationTaskCreate {
  if (!isRecord(payload)) throw new TypeError("Invalid investigation request");
  const allowed = new Set(["source_id", "target_metric", "target_date", "filters", "group_by"]);
  if (Object.keys(payload).some((key) => !allowed.has(key))) throw new TypeError("Invalid investigation request");
  const rawSourceId = payload.source_id;
  const rawMetric = payload.target_metric;
  if (typeof rawSourceId !== "string" || typeof rawMetric !== "string" ||
      typeof payload.target_date !== "string" || !ISO_DATE_PATTERN.test(payload.target_date)) {
    throw new TypeError("Invalid investigation request");
  }
  const sourceId = rawSourceId.trim();
  const metric = rawMetric.trim();
  if (sourceId.length === 0 || sourceId.length > 128 || metric.length === 0 || metric.length > 128) {
    throw new TypeError("Invalid investigation request");
  }
  dateValue(payload.target_date, "target_date");
  const rawFilters = payload.filters ?? {};
  const rawGroupBy = payload.group_by ?? [];
  if (!isRecord(rawFilters) || Object.keys(rawFilters).length > 32 || !Array.isArray(rawGroupBy) || rawGroupBy.length > 16) {
    throw new TypeError("Invalid investigation request");
  }
  // Dimension names are data, including names such as "__proto__".
  const normalizedFilters: Record<string, string> = Object.create(null);
  for (const [rawKey, rawValue] of Object.entries(rawFilters)) {
    if (typeof rawValue !== "string" || hasControlCharacter(rawValue)) {
      throw new TypeError("Invalid investigation request");
    }
    const key = rawKey.trim();
    const value = rawValue.trim();
    if (key.length === 0 || key.length > 64 || value.length > 256 || Object.hasOwn(normalizedFilters, key)) {
      throw new TypeError("Invalid investigation request");
    }
    normalizedFilters[key] = value;
  }
  const dimensions = rawGroupBy.map((item) => {
    if (typeof item !== "string") throw new TypeError("Invalid investigation request");
    const normalized = item.trim();
    if (normalized.length === 0 || normalized.length > 64) throw new TypeError("Invalid investigation request");
    return normalized;
  });
  if (new Set(dimensions).size !== dimensions.length) throw new TypeError("Invalid investigation request");
  return {
    source_id: sourceId,
    target_metric: metric,
    target_date: payload.target_date,
    filters: normalizedFilters,
    group_by: dimensions,
  };
}

function assertSourceId(value: string): void {
  if (typeof value !== "string" || value.length < 1 || value.length > 128) {
    throw new TypeError("Invalid source identifier");
  }
}

export function createTaskClient(options: TaskClientOptions = {}) {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const fetcher = options.fetcher ?? globalThis.fetch;
  if (typeof fetcher !== "function") throw new TypeError("A Fetch implementation is required");

  async function request(
    path: string,
    init: RequestInit,
    expectedStatus: number,
  ): Promise<unknown> {
    let response: Response;
    try {
      response = await fetcher(`${baseUrl}${path}`, init);
    } catch {
      if (init.signal?.aborted) throw new DOMException("The operation was aborted", "AbortError");
      throw new TaskClientError(null, "network_error");
    }
    let payload: unknown;
    try {
      payload = await responseJson(response);
    } catch (error) {
      if (init.signal?.aborted) throw new DOMException("The operation was aborted", "AbortError");
      throw error;
    }
    if (!response.ok) throwHttpError(response, payload);
    if (response.status !== expectedStatus) throw new TaskClientError(response.status, "invalid_response");
    return payload;
  }

  return {
    async sources(requestOptions: TaskRequestOptions = {}): Promise<InvestigationSourcesResponse> {
      const response = await request("/api/investigation-sources", {
        method: "GET", headers: { accept: "application/json" }, signal: requestOptions.signal,
      }, 200);
      const row = expectRecord(response, "source catalog");
      exactKeys(row, ["items"], "source catalog");
      if (!Array.isArray(row.items)) invalid("source catalog");
      const items = row.items.map(validateSource);
      if (new Set(items.map((source) => source.source_id)).size !== items.length) invalid("duplicate source");
      return { items };
    },
    async submit(
      payload: InvestigationTaskCreate,
      requestOptions: TaskRequestOptions = {},
    ): Promise<TaskRunView> {
      const body = validateTaskCreate(payload);
      const response = await request("/api/investigations", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify(body),
        signal: requestOptions.signal,
      }, 202);
      return validateRun(response, body.source_id);
    },

    async list(
      sourceId: string,
      listOptions: TaskListOptions = {},
    ): Promise<TaskListResponse> {
      assertSourceId(sourceId);
      const limit = listOptions.limit ?? 20;
      const offset = listOptions.offset ?? 0;
      if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100 || !Number.isSafeInteger(offset) || offset < 0) {
        throw new TypeError("Invalid investigation pagination");
      }
      const query = new URLSearchParams({ source_id: sourceId, limit: String(limit), offset: String(offset) });
      const response = await request(`/api/investigations?${query.toString()}`, {
        method: "GET",
        headers: { accept: "application/json" },
        signal: listOptions.signal,
      }, 200);
      const row = expectRecord(response, "task list");
      exactKeys(row, ["items", "limit", "offset"], "task list");
      if (!Array.isArray(row.items)) invalid("task list.items");
      const items = row.items.map((item) => validateRun(item, sourceId));
      const actualLimit = integerValue(row.limit, "task list.limit", 1);
      const actualOffset = integerValue(row.offset, "task list.offset");
      if (actualLimit !== limit || actualOffset !== offset) invalid("task list pagination");
      return { items, limit: actualLimit, offset: actualOffset };
    },

    async detail(
      runId: string,
      sourceId: string,
      requestOptions: TaskRequestOptions = {},
    ): Promise<TaskDetailResponse> {
      if (typeof runId !== "string" || runId.length < 1 || runId.length > 64) throw new TypeError("Invalid investigation identifier");
      assertSourceId(sourceId);
      const query = new URLSearchParams({ source_id: sourceId });
      const response = await request(`/api/investigations/${encodeURIComponent(runId)}?${query.toString()}`, {
        method: "GET",
        headers: { accept: "application/json" },
        signal: requestOptions.signal,
      }, 200);
      const row = expectRecord(response, "task detail");
      exactKeys(row, ["run", "tool_calls", "observations", "evidence", "diagnoses"], "task detail");
      if (!Array.isArray(row.tool_calls) || !Array.isArray(row.observations) || !Array.isArray(row.evidence) || !Array.isArray(row.diagnoses)) {
        invalid("task detail arrays");
      }
      return {
        run: validateRun(row.run, sourceId, runId),
        tool_calls: row.tool_calls.map(validateToolCall),
        observations: row.observations.map(validateObservation),
        evidence: row.evidence.map(validateEvidence),
        diagnoses: row.diagnoses.map(validateDiagnosis),
      };
    },
  };
}
