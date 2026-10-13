import { parseTaskRun } from '../tasks/client.js'
import type { TaskRunView } from '../tasks/contracts.js'

export type LabStatus = 'queued' | 'publishing' | 'published' | 'failed'
export type ScenarioId = 'no_anomaly' | 'canonical' | 'traffic'
export interface LabExperiment {
  experiment_id: string; source_id: string; environment: 'sandbox'; provider: 'synthetic'
  scenario_id: ScenarioId; target_date: string; status: LabStatus
  created_at: string; updated_at: string; data_version: string | null; failure_code: string | null
  requested_metric: string | null; investigation_run_id: string | null
  data_version_kind: 'label'; snapshot_consistent: false
}
export interface LabCatalog {
  target_date: string
  scenarios: { scenario_id: ScenarioId; title: string; description: string }[]
  targets: { source_id: string; display_name: string; provider: 'synthetic'; environment: 'sandbox';
    state: LabStatus | 'available'; experiment_id: string | null }[]
}
export interface LabList { items: LabExperiment[]; limit: number; offset: number }
export class LabClientError extends Error {
  readonly code: string
  constructor(code: string) { super(code); this.code = code; this.name = 'LabClientError' }
}
const CODES = new Set(['lab_service_unavailable', 'lab_storage_unavailable', 'invalid_lab_request',
  'lab_target_not_found', 'lab_experiment_not_found', 'lab_target_unavailable', 'lab_idempotency_conflict',
  'lab_not_published', 'lab_investigation_conflict', 'lab_metric_not_supported'])
const STATUSES = new Set(['queued', 'publishing', 'published', 'failed'])
const SCENARIOS = new Set(['no_anomaly', 'canonical', 'traffic'])
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const VERSION = /^sandbox-[0-9a-f]{64}$/
function invalid(): never { throw new LabClientError('invalid_response') }
function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid()
}
function text(value: unknown): string { return typeof value === 'string' && value.length ? value : invalid() }
function uuid(value: unknown): string { const result = text(value); return UUID.test(result) ? result : invalid() }
function day(value: unknown): string {
  const result = text(value)
  const parsed = new Date(result + 'T00:00:00Z')
  return /^\d{4}-\d{2}-\d{2}$/.test(result) && Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === result ? result : invalid()
}
function stamp(value: unknown): string {
  const result = text(value)
  return /^\d{4}-\d{2}-\d{2}T/.test(result) && Number.isFinite(Date.parse(result)) ? result : invalid()
}
function keys(row: Record<string, unknown>, expected: string[]): void {
  if (Object.keys(row).length !== expected.length || Object.keys(row).some(key => !expected.includes(key))) invalid()
}
function experiment(value: unknown): LabExperiment {
  const row = object(value)
  keys(row, ['experiment_id','source_id','environment','provider','scenario_id','target_date','status','created_at',
    'updated_at','data_version','failure_code','requested_metric','investigation_run_id','data_version_kind','snapshot_consistent'])
  uuid(row.experiment_id); uuid(row.source_id); day(row.target_date); stamp(row.created_at); stamp(row.updated_at)
  if (row.environment !== 'sandbox' || row.provider !== 'synthetic' || row.data_version_kind !== 'label' || row.snapshot_consistent !== false) invalid()
  if (!STATUSES.has(text(row.status)) || !SCENARIOS.has(text(row.scenario_id))) invalid()
  if (row.status === 'published') {
    if (!VERSION.test(text(row.data_version)) || row.failure_code !== null) invalid()
  } else {
    if (row.data_version !== null || row.investigation_run_id !== null || row.requested_metric !== null) invalid()
    if (row.status === 'failed') {
      if (!['publication_failed','publication_interrupted','publication_recovery_unavailable'].includes(text(row.failure_code))) invalid()
    } else if (row.failure_code !== null) invalid()
  }
  if (row.requested_metric !== null && !['sales','orders','sessions','conversion_rate','aov'].includes(text(row.requested_metric))) invalid()
  if (row.investigation_run_id !== null) { uuid(row.investigation_run_id); if (row.requested_metric === null) invalid() }
  return row as unknown as LabExperiment
}
function catalog(value: unknown): LabCatalog {
  const row = object(value); keys(row, ['target_date','scenarios','targets']); day(row.target_date)
  if (!Array.isArray(row.scenarios) || !Array.isArray(row.targets) || row.targets.length > 20) invalid()
  const sourceIds = new Set<string>(); const scenes = new Set<string>()
  for (const item of row.scenarios) {
    const scene = object(item); keys(scene, ['scenario_id','title','description'])
    const id = text(scene.scenario_id); if (!SCENARIOS.has(id) || scenes.has(id)) invalid()
    scenes.add(id); text(scene.title); text(scene.description)
  }
  if (scenes.size !== 3) invalid()
  for (const item of row.targets) {
    const target = object(item); keys(target, ['source_id','display_name','provider','environment','state','experiment_id'])
    const id = uuid(target.source_id); if (sourceIds.has(id)) invalid(); sourceIds.add(id); text(target.display_name)
    if (target.provider !== 'synthetic' || target.environment !== 'sandbox') invalid()
    if (target.state === 'available') { if (target.experiment_id !== null) invalid() }
    else { if (!STATUSES.has(text(target.state))) invalid(); uuid(target.experiment_id) }
  }
  return row as unknown as LabCatalog
}

export function createLabClient(options: { fetcher?: typeof fetch; baseUrl?: string } = {}) {
  const fetcher = options.fetcher ?? fetch
  const base = options.baseUrl ?? ''
  async function request(path: string, init: RequestInit = {}): Promise<unknown> {
    let response: Response
    try { response = await fetcher(base + path, init) } catch { throw new LabClientError('network_error') }
    let value: unknown
    try { value = await response.json() } catch { throw new LabClientError(response.ok ? 'invalid_response' : 'request_failed') }
    if (!response.ok) {
      const row = value && typeof value === 'object' ? value as Record<string, unknown> : null
      const detail = row?.detail && typeof row.detail === 'object' ? row.detail as Record<string, unknown> : null
      throw new LabClientError(typeof detail?.code === 'string' && CODES.has(detail.code) ? detail.code : 'request_failed')
    }
    return value
  }
  return {
    async catalog(signal?: AbortSignal) { return catalog(await request('/api/lab/catalog', { signal })) },
    async list(limit = 20, offset = 0, signal?: AbortSignal): Promise<LabList> {
      if (!Number.isInteger(limit) || limit < 1 || limit > 100 || !Number.isInteger(offset) || offset < 0) throw new LabClientError('invalid_lab_request')
      const row = object(await request(`/api/lab/experiments?limit=${limit}&offset=${offset}`, { signal }))
      keys(row, ['items','limit','offset'])
      if (!Array.isArray(row.items) || row.items.length > limit || row.limit !== limit || row.offset !== offset) invalid()
      return { items: row.items.map(experiment), limit, offset }
    },
    async detail(id: string, signal?: AbortSignal) { uuid(id); const result = experiment(await request(`/api/lab/experiments/${id}`, { signal })); if (result.experiment_id !== id) invalid(); return result },
    async publish(body: { source_id: string; scenario_id: ScenarioId; idempotency_key: string }, signal?: AbortSignal) {
      uuid(body.source_id); uuid(body.idempotency_key); if (!SCENARIOS.has(body.scenario_id)) throw new LabClientError('invalid_lab_request')
      const result = experiment(await request('/api/lab/experiments', { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }))
      if (result.source_id !== body.source_id || result.scenario_id !== body.scenario_id) invalid()
      return result
    },
    async investigate(record: LabExperiment, signal?: AbortSignal): Promise<TaskRunView> {
      if (record.status !== 'published') throw new LabClientError('lab_not_published')
      const value = await request(`/api/lab/experiments/${uuid(record.experiment_id)}/investigations`, {
        method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_metric: 'sales' }),
      })
      try {
        const run = parseTaskRun(value, record.source_id)
        if (run.provider !== 'synthetic' || run.environment !== 'sandbox' || run.data_version !== record.data_version || run.requested_metric !== 'sales') invalid()
        return run
      } catch { throw new LabClientError('invalid_response') }
    },
  }
}
