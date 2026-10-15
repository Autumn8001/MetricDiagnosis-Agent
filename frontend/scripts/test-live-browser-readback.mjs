// Offline regression for acceptance assertions; no browser, database or model.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { assertRenderedDiagnosis, assertFreshReadback } from './verify-live-model-browser-task.mjs'

const detail = {
  run: { investigation_run_id: 'run-1' },
  diagnoses: [{ status: 'diagnosed', evidence_ids: ['evidence-1'] }],
  evidence: [{ evidence_id: 'evidence-1', observation_id: 'observation-1', tool_call_id: 'call-1', query_reference: 'query-1', data_version: 'version-1' }],
}
const text = 'run-1 已定位主要变化 evidence-1 observation-1 call-1 query-1 version-1'

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
