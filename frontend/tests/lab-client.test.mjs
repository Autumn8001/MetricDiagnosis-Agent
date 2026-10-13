import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'
import test from 'node:test'
const { createLabClient } = await import(pathToFileURL(join(process.env.METRICSLEUTH_LAB_CLIENT_BUILD_DIR, 'lab/client.js')))
const source = '11111111-1111-4111-8111-111111111111'
const id = '22222222-2222-4222-8222-222222222222'
const key = '33333333-3333-4333-8333-333333333333'
const version = 'sandbox-' + 'a'.repeat(64)
const record = (overrides = {}) => ({ experiment_id: id, source_id: source, provider: 'synthetic', environment: 'sandbox',
  scenario_id: 'no_anomaly', target_date: '2026-01-31', status: 'published', created_at: '2026-10-13T12:00:00Z',
  updated_at: '2026-10-13T12:00:00Z', data_version: version, failure_code: null, requested_metric: null,
  investigation_run_id: null, data_version_kind: 'label', snapshot_consistent: false, ...overrides })
const catalog = () => ({ target_date: '2026-01-31', scenarios: ['no_anomaly','canonical','traffic'].map(scenario_id => ({ scenario_id, title: scenario_id, description: 'Controlled fixture' })),
  targets: [{ source_id: source, display_name: 'Fixture slot', provider: 'synthetic', environment: 'sandbox', state: 'available', experiment_id: null }] })
const response = (body, status = 200) => Response.json(body, { status })
const error = code => e => e.code === code

test('catalog accepts only isolated configured targets, no connection URLs', async () => {
  const client = createLabClient({ fetcher: async () => response(catalog()) })
  assert.equal((await client.catalog()).targets[0].state, 'available')
  for (const mutation of [value => { value.targets[0].environment = 'live' }, value => { value.targets[0].database_url = 'private-marker' }, value => { value.targets.push(value.targets[0]) }]) {
    const value = catalog(); mutation(value)
    const invalid = createLabClient({ fetcher: async () => response(value) })
    await assert.rejects(invalid.catalog(), error('invalid_response'))
  }
})

test('published detail requires matching identity and label, never a snapshot claim', async () => {
  for (const overrides of [{ snapshot_consistent: true }, { experiment_id: key }, { data_version: null }, { failure_code: 'private-marker' }, { target_date: '2026-02-31' }]) {
    const client = createLabClient({ fetcher: async () => response(record(overrides)) })
    await assert.rejects(client.detail(id), error('invalid_response'))
  }
})

test('pending and failed records preserve absence of values and outcomes', async () => {
  const failed = record({ status: 'failed', data_version: null, failure_code: 'publication_failed' })
  const client = createLabClient({ fetcher: async () => response(failed) })
  assert.equal((await client.detail(id)).investigation_run_id, null)
  const pending = record({ status: 'publishing', data_version: null })
  assert.equal((await createLabClient({ fetcher: async () => response(pending) }).detail(id)).status, 'publishing')
  const invalid = createLabClient({ fetcher: async () => response({ ...pending, requested_metric: 'sales' }) })
  await assert.rejects(invalid.detail(id), error('invalid_response'))
})

test('explicit retry preserves the same caller idempotency key without automatic requests', async () => {
  const calls = []
  const client = createLabClient({ fetcher: async (_, options) => { calls.push(JSON.parse(options.body)); return response(record()) } })
  const body = { source_id: source, scenario_id: 'no_anomaly', idempotency_key: key }
  await client.publish(body); await client.publish(body)
  assert.deepEqual(calls, [body, body])
  assert.equal(Object.keys(calls[0]).length, 3)
  const invalid = createLabClient({ fetcher: async () => response(record({ source_id: key })) })
  await assert.rejects(invalid.publish(body), error('invalid_response'))
})

test('safe errors do not disclose unknown response contents', async () => {
  for (const code of ['private-marker', 'lab_storage_unavailable']) {
    let count = 0
    const client = createLabClient({ fetcher: async () => { count++; return response({ detail: { code, message: 'private-marker' } }, 503) } })
    await assert.rejects(client.catalog(), e => !e.message.includes('private-marker') && e.code === (code === 'private-marker' ? 'request_failed' : code))
    assert.equal(count, 1)
  }
})

test('pagination validates the exact requested page and count', async () => {
  const client = createLabClient({ fetcher: async () => response({ items: [record()], limit: 20, offset: 0 }) })
  assert.equal((await client.list()).items.length, 1)
  await assert.rejects(client.list(20, 20), error('invalid_response'))
  await assert.rejects(client.list(101), error('invalid_lab_request'))
})

test('associated investigation uses the existing complete task contract and source version', async () => {
  const run = { investigation_run_id: key, source_id: source, environment: 'sandbox', provider: 'synthetic', status: 'queued',
    requested_metric: 'sales', requested_at: '2026-10-13T12:00:00Z', started_at: null, finished_at: null,
    data_version: version, query_reference: 'lab-task:' + id, failure_code: null, tool_call_count: 0, observation_count: 0, evidence_count: 0, diagnosis_count: 0 }
  let submitted
  const client = createLabClient({ fetcher: async (_, options) => { submitted = JSON.parse(options.body); return response(run) } })
  assert.equal((await client.investigate(record())).investigation_run_id, key)
  assert.deepEqual(submitted, { target_metric: 'sales' })
  const invalid = createLabClient({ fetcher: async () => response({ ...run, data_version: 'different' }) })
  await assert.rejects(invalid.investigate(record()), error('invalid_response'))
  await assert.rejects(client.investigate(record({ status: 'publishing', data_version: null })), error('lab_not_published'))
})
