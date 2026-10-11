/** Wire contracts for source-bound metric reads and manual daily scans. */

export type MetricProvider = "postgresql" | "shopify" | "olist" | "synthetic";
export type MetricEnvironment = "live" | "sandbox" | "benchmark" | "validation";
export type MetricObservationStatus =
  | "normal"
  | "anomalous"
  | "inconclusive"
  | "insufficient_evidence"
  | "failed";

/** Decimal JSON values stay strings so large and precise values are not rounded. */
export type MetricDecimal = string | null;

export interface MetricObservationView {
  metric: string;
  status: MetricObservationStatus;
  source_status: string;
  current_period_start: string;
  current_period_end: string;
  baseline_period_start: string;
  baseline_period_end: string;
  current_value: MetricDecimal;
  baseline_value: MetricDecimal;
  relative_change: MetricDecimal;
  unit: string;
  sample_size: MetricDecimal;
}

export interface MetricReadResponse {
  source_id: string;
  provider: MetricProvider;
  environment: MetricEnvironment;
  data_version: string;
  data_version_kind: "label";
  persisted: false;
  scope: "source_global";
  target_metric: string;
  target_date: string;
  comparison: "previous_7_days";
  queried_at: string;
  query_reference: string;
  observation: MetricObservationView | null;
  anomaly_candidate: boolean | null;
}

export interface MetricScanResponse {
  source_id: string;
  provider: MetricProvider;
  environment: MetricEnvironment;
  data_version: string;
  data_version_kind: "label";
  persisted: false;
  scope: "source_global";
  target_date: string;
  comparison: "previous_7_days";
  snapshot_consistent: false;
  completed_at: string;
  items: MetricReadResponse[];
  anomaly_candidate_metrics: string[];
}
