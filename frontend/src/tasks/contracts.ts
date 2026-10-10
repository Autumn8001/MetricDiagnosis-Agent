/** Public wire contracts for persisted investigation tasks. */

export type TaskRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export type DataSourceProvider = "postgresql" | "shopify" | "olist" | "synthetic";
export type DataSourceEnvironment = "live" | "sandbox" | "benchmark" | "validation";

/** JSON values carried by safe, structured tool arguments and dimensions. */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** Decimal values are serialized as strings by some JSON encoders and numbers by others. */
export type DecimalValue = number | string;

export interface InvestigationTaskCreate {
  source_id: string;
  target_metric: string;
  target_date: string;
  filters?: Record<string, string>;
  group_by?: string[];
}

export interface TaskRunView {
  investigation_run_id: string;
  source_id: string;
  environment: DataSourceEnvironment;
  provider: DataSourceProvider;
  status: TaskRunStatus;
  requested_metric: string;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  data_version: string | null;
  query_reference: string | null;
  failure_code: string | null;
  tool_call_count: number;
  observation_count: number;
  evidence_count: number;
  diagnosis_count: number;
}

export interface TaskListResponse {
  items: TaskRunView[];
  limit: number;
  offset: number;
}

export interface ToolCallView {
  tool_call_id: string;
  tool_name: string;
  status: string;
  arguments: Record<string, JsonValue>;
  data_version: string | null;
  query_reference: string | null;
  result_reference: string | null;
  requested_at: string;
}

export interface ObservationView {
  observation_id: string;
  tool_call_id: string | null;
  metric: string;
  status: string;
  source_status: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  baseline_period_start: string | null;
  baseline_period_end: string | null;
  filters: Record<string, JsonValue>;
  group_by: string[];
  dimensions: Record<string, JsonValue>;
  current_value: DecimalValue | null;
  baseline_value: DecimalValue | null;
  relative_change: DecimalValue | null;
  unit: string | null;
  sample_size: DecimalValue | null;
  query_reference: string | null;
  data_version: string | null;
  error_code: string | null;
  created_at: string;
}

export interface EvidenceView {
  evidence_id: string;
  observation_id: string;
  tool_call_id: string | null;
  role: string;
  data_version: string | null;
  query_reference: string | null;
  created_at: string;
}

export interface DiagnosisChangeView {
  current_value: DecimalValue | null;
  baseline_value: DecimalValue | null;
  relative_change: DecimalValue | null;
  unit: string;
  evidence_id: string;
}

export interface DiagnosisView {
  diagnosis_id: string;
  status: string;
  target_metric: string;
  primary_driver: string | null;
  affected_scope: Record<string, string>;
  change: DiagnosisChangeView | null;
  evidence_ids: string[];
  confidence: DecimalValue | null;
  limitations: string[];
  data_version: string | null;
  query_reference: string | null;
  created_at: string;
}

export interface TaskDetailResponse {
  run: TaskRunView;
  tool_calls: ToolCallView[];
  observations: ObservationView[];
  evidence: EvidenceView[];
  diagnoses: DiagnosisView[];
}

/** Server configuration only: not connectivity, freshness, or date coverage. */
export interface InvestigationSourceView {
  source_id: string;
  display_name: string;
  provider: DataSourceProvider;
  environment: DataSourceEnvironment;
  data_version: string;
  metrics: {
    metric_id: string;
    supported: boolean;
    grain: string[];
    dimensions: string[];
    unavailable_reason: string | null;
  }[];
}

export interface InvestigationSourcesResponse {
  items: InvestigationSourceView[];
}

/** The backend deliberately returns only stable, non-sensitive failure codes. */
export type TaskApiErrorCode =
  | "task_service_unavailable"
  | "source_catalog_unavailable"
  | "invalid_task_request"
  | "task_storage_unavailable"
  | "source_not_found"
  | "metric_or_dimensions_not_supported"
  | "invalid_pagination"
  | "investigation_not_found"
  | "invalid_response"
  | "network_error"
  | "request_failed";
