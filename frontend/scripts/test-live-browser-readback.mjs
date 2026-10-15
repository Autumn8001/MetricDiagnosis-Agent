// Offline regression for acceptance assertions; no browser, database or model.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { assertRenderedDiagnosis, assertFreshReadback, assertManifest } from './verify-live-model-browser-task.mjs'

const detail = {
  run: { investigation_run_id: 'run-1' },
  diagnoses: [{ status: 'diagnosed', evidence_ids: ['evidence-1'] }],
  evidence: [{ evidence_id: 'evidence-1', observation_id: 'observation-1', tool_call_id: 'call-1', query_reference: 'query-1', data_version: 'version-1' }],
}
const text = 'run-1 已定位主要变化 evidence-1 observation-1 call-1 query-1 version-1'

test('manifest accepts the bounded timeout contract and rejects absent or arbitrary values', () => {
  const manifest = {
    acceptance_kind: 'live_model_browser_task', api_mode: 'chat_completions',
    controlled_runner: false, data_profile: 'synthetic', data_version: 'test-v1',
    database: 'metricsleuth_r2_acceptance', max_tool_calls: 8, max_turns: 10,
    model_request_timeout_seconds: 120, real_model: true,
    request_filters: { asin: '11111111-1111-4111-8111-111111111111' },
    source_id: '22222222-2222-4222-8222-222222222222', target_date: '2026-10-10', target_metric: 'sales',
  }
  for (const timeout of [60, 120]) {
    assert.doesNotThrow(() => assertManifest({ ...manifest, model_request_timeout_seconds: timeout }))
  }
  for (const timeout of [0, 600, '120', null]) {
    assert.throws(() => assertManifest({ ...manifest, model_request_timeout_seconds: timeout }), /manifest_timeout/)
  }
  const missing = { ...manifest }
  delete missing.model_request_timeout_seconds
  assert.throws(() => assertManifest(missing), /manifest_keys/)
  assert.throws(() => assertManifest({ ...manifest, unexpected: true }), /manifest_keys/)
})

test('rendered result must include cited provenance, not only the success label', () => {
  assert.doesNotThrow(() => assertRenderedDiagnosis(detail, text))
  for (const value of ['run-1', '已定位主要变化', 'evidence-1', 'observation-1', 'call-1', 'query-1', 'version-1']) {
    assert.throws(() => assertRenderedDiagnosis(detail, text.replace(value, '')), /^Error: browser_/)
  }
})

test('no-anomaly diagnosis uses the actual UI label', () => {
  const normal = structuredClone(detail)
  normal.diagnoses[0].status = 'no_material_anomaly'
  assert.doesNotThrow(() => assertRenderedDiagnosis(normal, text.replace('已定位主要变化', '未发现明显异常')))
})

test('refresh must receive another terminal response with unchanged persisted facts', () => {
  assert.throws(() => assertFreshReadback(detail, detail, 5, 5), /browser_refresh_detail/)
  assert.throws(() => assertFreshReadback(detail, { ...detail, evidence: [] }, 5, 6), /browser_refresh_detail/)
  assert.doesNotThrow(() => assertFreshReadback(detail, structuredClone(detail), 5, 6))
})
