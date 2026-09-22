/**
 * Type definitions matching MetricSleuth FastAPI schemas.
 */

export interface MetricGraphNode {
  metric_id: string
  display_name: string
  description: string
  metric_type: string
  unit: string
  formula: string
  dependencies: string[]
  related_metrics: string[]
}

export interface MetricGraphEdge {
  source: string
  target: string
  relationship: string
}

export interface MetricGraphResponse {
  nodes: MetricGraphNode[]
  edges: MetricGraphEdge[]
}

export interface ScenarioItem {
  scenario_id: string
  title: string
  description: string
  target_metric: string
}

export interface ScenarioListResponse {
  scenarios: ScenarioItem[]
}

export interface InjectScenarioResponse {
  status: string
  scenario: string
  message: string
  mode: 'live' | 'dry_run'
}

export interface DiagnosisChangeItem {
  current_value: number | null
  baseline_value: number | null
  relative_change: number | null
  unit: string | null
  evidence_id: string | null
}

export interface DiagnosisItem {
  diagnosis_id: string
  status: 'diagnosed' | 'no_material_anomaly' | 'inconclusive' | 'budget_exhausted' | 'tool_failure'
  target_metric: string
  primary_driver: string | null
  affected_scope: Record<string, string>
  confidence: number | null
  change: DiagnosisChangeItem | null
  evidence_ids: string[]
  limitations: string[]
  created_at: string | null
}

export interface EvidenceItem {
  evidence_id: string
  observation_id: string
  metric: string
  role: 'supporting' | 'negative_control' | 'context' | 'limitation'
  observation_status: 'anomalous' | 'normal' | 'inconclusive' | 'insufficient_evidence' | 'failed'
  current_value: number | null
  baseline_value: number | null
  relative_change: number | null
  unit: string
  sample_size: number | null
  dimensions: Record<string, string>
  filters: Record<string, string>
}

export interface TraceStepItem {
  step_number: number
  tool_name: string
  tool_call_id: string
  arguments: Record<string, any>
  observation_id: string | null
  status: string
  metric: string | null
  current_value: number | null
  baseline_value: number | null
  relative_change: number | null
  dimensions: Record<string, string>
  summary: string | null
}

export interface BudgetUsage {
  tool_calls_count: number
  max_tool_calls: number
  turns_count: number
  max_turns: number
}

export interface InvestigationResponse {
  request_id: string
  mode: 'mock' | 'live'
  target_metric: string
  target_date: string
  scenario: string | null
  diagnosis: DiagnosisItem
  evidence: EvidenceItem[]
  investigation_trace: TraceStepItem[]
  budget: BudgetUsage
}

export interface InvestigationRequest {
  target_metric?: string
  target_date?: string
  baseline_strategy?: string
  prompt?: string
  scenario?: string
  mock_mode?: boolean
}

export interface HealthResponse {
  status: string
  service: string
  version: string
  timestamp: string
}

export interface DailyScanObservationItem {
  metric: string
  status: string
  current_value: number | null
  baseline_value: number | null
  relative_change: number | null
  unit: string
  sample_size: number | null
  observation_id: string
}

export interface DailyScanResponse {
  target_date: string
  comparison: string
  mode: 'manual_trigger_discovery'
  observations: DailyScanObservationItem[]
  anomaly_candidate_metrics: string[]
  next_step: string
}
