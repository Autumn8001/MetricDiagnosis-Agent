// One explicitly authorized local controlled-runner task through the real UI/API/PG stack.
// Write mode: add --allow-test-task-write. Read-only recovery: add --resume-run UUID instead.
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const dist = resolve(frontend, 'dist')
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const API_TIMEOUT_MS = 10_000
const MAX_BODY_BYTES = 1024 * 1024
const EXPECTED_DATE = '2026-10-10'
const EXPECTED_DATABASE = 'metricsleuth_r4_browser_acceptance'
const EXPECTED_FIXTURE = 'synthetic-eight-days-v1'

function parseArguments(argv) {
  const values = Object.create(null)
  let writeFlagCount = 0
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index]
    if (name === '--allow-test-task-write') {
      writeFlagCount += 1
      if (writeFlagCount !== 1) throw new Error('arguments')
      continue
    }
    if (!['--api', '--source', '--output', '--resume-run'].includes(name) || Object.hasOwn(values, name)) throw new Error('arguments')
    const value = argv[index + 1]
    if (!value || value.startsWith('--')) throw new Error('arguments')
    values[name] = value
    index += 1
  }
  const resumeRunId = values['--resume-run'] ?? null
  if (resumeRunId) {
    if (writeFlagCount !== 0 || !UUID.test(resumeRunId)) throw new Error('resume_arguments')
  } else if (writeFlagCount !== 1) {
    throw new Error('allow_test_task_write_required')
  }
  if (Object.keys(values).length !== (resumeRunId ? 4 : 3)) throw new Error('arguments')

  let api
  try { api = new URL(values['--api']) } catch { throw new Error('api_url') }
  const host = api.hostname.toLowerCase()
  const loopback = host === '::1' || host === '[::1]' || /^127(?:\.\d{1,3}){3}$/.test(host)
  if (api.protocol !== 'http:' || !loopback || api.username || api.password || api.search || api.hash ||
      (api.pathname !== '/' && api.pathname !== '')) throw new Error('api_url')
  if (!UUID.test(values['--source'])) throw new Error('source_id')
  if (!/^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(values['--output'])) throw new Error('output_path')
  return {
    apiOrigin: api.origin,
    sourceId: values['--source'],
    output: resolve(values['--output']),
    resumeRunId,
    writeAuthorized: writeFlagCount === 1,
  }
}

function check(condition, label) {
  if (!condition) throw new Error(label)
}

async function readLimited(response) {
  const reader = response.body?.getReader()
  if (!reader) return Buffer.alloc(0)
  const chunks = []
  let size = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    size += value.byteLength
    if (size > MAX_BODY_BYTES) {
      await reader.cancel().catch(() => {})
      throw new Error('response_size')
    }
    chunks.push(Buffer.from(value))
  }
  return Buffer.concat(chunks, size)
}

async function fetchJson(url, method, stage, body) {
  let response
  try {
    response = await fetch(url, {
      method,
      redirect: 'error',
      headers: { accept: 'application/json', ...(body ? { 'content-type': 'application/json' } : {}) },
      ...(body ? { body } : {}),
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    })
  } catch {
    throw new Error(stage)
  }
  const bytes = await readLimited(response).catch(() => { throw new Error(stage) })
  let payload
  try { payload = JSON.parse(bytes.toString('utf8')) } catch { throw new Error(stage) }
  return { response, payload }
}

function assertManifest(manifest, sourceId) {
  const expectedKeys = ['acceptance_kind', 'database', 'source_id', 'target_date', 'controlled_runner', 'real_model', 'fixture']
  check(manifest && typeof manifest === 'object' && !Array.isArray(manifest) &&
    Object.keys(manifest).sort().join(',') === expectedKeys.sort().join(','), 'manifest_shape')
  check(manifest.acceptance_kind === 'controlled_browser_task', 'manifest_kind')
  check(manifest.database === EXPECTED_DATABASE, 'manifest_database')
  check(manifest.source_id === sourceId, 'manifest_source')
  check(manifest.target_date === EXPECTED_DATE, 'manifest_date')
  check(manifest.controlled_runner === true && manifest.real_model === false, 'manifest_execution_mode')
  check(manifest.fixture === EXPECTED_FIXTURE, 'manifest_fixture')
}

function getSource(catalog, sourceId) {
  check(catalog && typeof catalog === 'object' && Array.isArray(catalog.items), 'catalog_shape')
  return catalog.items.find((item) => item?.source_id === sourceId)
}

function assertSource(source, sourceId) {
  check(source?.source_id === sourceId && source.provider === 'synthetic' && source.environment === 'sandbox', 'source_identity')
  check(source.data_version === EXPECTED_FIXTURE, 'source_fixture')
  check(Array.isArray(source.metrics) && source.metrics.some((item) => item?.metric_id === 'sales' && item.supported === true), 'source_sales')
}

async function assertEmptyHistory(apiOrigin, sourceId, stage) {
  const url = new URL('/api/investigations', apiOrigin)
  url.searchParams.set('source_id', sourceId)
  url.searchParams.set('limit', '1')
  url.searchParams.set('offset', '0')
  const { response, payload } = await fetchJson(url, 'GET', stage)
  check(response.status === 200 && payload?.limit === 1 && payload?.offset === 0 &&
    Array.isArray(payload.items) && payload.items.length === 0, `${stage}_not_empty`)
}

async function readRunList(apiOrigin, sourceId, stage) {
  const url = new URL('/api/investigations', apiOrigin)
  url.searchParams.set('source_id', sourceId)
  url.searchParams.set('limit', '100')
  url.searchParams.set('offset', '0')
  const { response, payload } = await fetchJson(url, 'GET', stage)
  check(response.status === 200 && payload?.limit === 100 && payload?.offset === 0 && Array.isArray(payload.items), `${stage}_shape`)
  return payload.items
}

function assertResumableRun(run, sourceId, runId) {
  check(run?.investigation_run_id === runId && run.source_id === sourceId && run.provider === 'synthetic' &&
    run.environment === 'sandbox' && run.status === 'succeeded' && run.requested_metric === 'sales' &&
    run.data_version === EXPECTED_FIXTURE && run.tool_call_count === 1 && run.observation_count === 1 &&
    run.evidence_count === 1 && run.diagnosis_count === 1, 'resume_run')
}

function safeContentType(path) {
  return ({
    '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
  })[extname(path)] ?? 'application/octet-stream'
}

async function readRequestBody(request) {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > MAX_BODY_BYTES) throw new Error('request_size')
    chunks.push(chunk)
  }
  return Buffer.concat(chunks, size)
}

function normalizeDecimal(value, stage) {
  check((typeof value === 'string' || typeof value === 'number') && String(value).length <= 128, stage)
  const raw = String(value)
  check(/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(raw), stage)
  const negative = raw.startsWith('-')
  const unsigned = negative ? raw.slice(1) : raw
  const [integer, fraction = ''] = unsigned.split('.')
  const normalized = `${integer.replace(/^0+(?=\d)/, '')}${fraction ? `.${fraction.replace(/0+$/, '')}` : ''}`.replace(/\.$/, '')
  return normalized === '0' ? '0' : `${negative ? '-' : ''}${normalized}`
}

function assertSuccessfulDetail(detail, sourceId, runId) {
  check(detail?.run?.investigation_run_id === runId && detail.run.source_id === sourceId, 'detail_identity')
  check(detail.run.provider === 'synthetic' && detail.run.environment === 'sandbox', 'detail_source')
  check(detail.run.status === 'succeeded' && detail.run.requested_metric === 'sales' && detail.run.data_version === EXPECTED_FIXTURE, 'detail_run')
  check(Array.isArray(detail.tool_calls) && detail.tool_calls.length === 1, 'detail_tool_calls')
  check(Array.isArray(detail.observations) && detail.observations.length === 1, 'detail_observations')
  check(Array.isArray(detail.evidence) && detail.evidence.length === 1, 'detail_evidence')
  check(Array.isArray(detail.diagnoses) && detail.diagnoses.length === 1, 'detail_diagnoses')

  const tool = detail.tool_calls[0]
  const observation = detail.observations[0]
  const evidence = detail.evidence[0]
  const diagnosis = detail.diagnoses[0]
  check(typeof tool.tool_call_id === 'string' && tool.tool_call_id.length > 0 && tool.tool_call_id.length <= 256 && tool.status === 'succeeded', 'detail_tool_identity')
  check(observation.metric === 'sales' && observation.status === 'normal' && observation.tool_call_id === tool.tool_call_id &&
    observation.data_version === EXPECTED_FIXTURE, 'detail_observation_link')
  if (tool.query_reference !== null) check(observation.query_reference === tool.query_reference, 'detail_tool_query_reference')
  check(normalizeDecimal(observation.current_value, 'detail_current_value') === '100' &&
    normalizeDecimal(observation.baseline_value, 'detail_baseline_value') === '100' &&
    normalizeDecimal(observation.relative_change, 'detail_relative_change') === '0', 'detail_observation_values')
  check(JSON.stringify(observation.filters) === '{}' && Array.isArray(observation.group_by) && observation.group_by.length === 0 &&
    observation.dimensions && Object.keys(observation.dimensions).length === 0, 'detail_observation_scope')
  check(evidence.observation_id === observation.observation_id && evidence.tool_call_id === tool.tool_call_id &&
    evidence.query_reference === observation.query_reference && evidence.data_version === observation.data_version &&
    evidence.role === 'supporting' && typeof evidence.evidence_id === 'string' && evidence.evidence_id.length > 0, 'detail_evidence_links')
  check(diagnosis.status === 'no_material_anomaly' && diagnosis.target_metric === 'sales' &&
    diagnosis.primary_driver === null && diagnosis.affected_scope && Object.keys(diagnosis.affected_scope).length === 0, 'detail_diagnosis')
  check(typeof diagnosis.diagnosis_id === 'string' && diagnosis.diagnosis_id.length > 0 && diagnosis.diagnosis_id.length <= 256 &&
    diagnosis.data_version === EXPECTED_FIXTURE, 'detail_diagnosis_identity')
  check(Array.isArray(diagnosis.evidence_ids) && diagnosis.evidence_ids.length === 1 &&
    diagnosis.evidence_ids[0] === evidence.evidence_id && diagnosis.change?.evidence_id === evidence.evidence_id, 'detail_diagnosis_evidence')
  check(normalizeDecimal(diagnosis.change.current_value, 'detail_diagnosis_current') === '100' &&
    normalizeDecimal(diagnosis.change.baseline_value, 'detail_diagnosis_baseline') === '100' &&
    normalizeDecimal(diagnosis.change.relative_change, 'detail_diagnosis_relative') === '0', 'detail_diagnosis_values')
  check(Array.isArray(diagnosis.limitations) && diagnosis.limitations.some((item) =>
    typeof item === 'string' && item.includes('Controlled Runner acceptance; not a model diagnosis')), 'detail_controlled_limitation')
  check(detail.run.tool_call_count === 1 && detail.run.observation_count === 1 &&
    detail.run.evidence_count === 1 && detail.run.diagnosis_count === 1, 'detail_persisted_counts')

  return {
    toolCallId: tool.tool_call_id,
    observationId: observation.observation_id,
    evidenceId: evidence.evidence_id,
    diagnosisId: diagnosis.diagnosis_id,
    currentValue: String(observation.current_value),
    baselineValue: String(observation.baseline_value),
    relativeChange: String(observation.relative_change),
    limitation: diagnosis.limitations.find((item) => item.includes('Controlled Runner acceptance; not a model diagnosis')),
  }
}

function createLocalServer(apiOrigin, sourceId, writeAllowed, activity) {
  return createServer(async (request, response) => {
    const send = (status, body, contentType = 'text/plain; charset=utf-8') => {
      response.writeHead(status, { 'content-type': contentType, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' })
      response.end(body)
    }
    try {
      const local = new URL(request.url, 'http://127.0.0.1')
      if (local.pathname.startsWith('/api/')) {
        if (request.method === 'POST' && local.pathname === '/api/investigations' && local.search === '') {
          activity.postAttempts += 1
          if (!writeAllowed || activity.postAttempts !== 1 || activity.runId ||
              !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers['content-type'] ?? '')) {
            activity.blockedWrites += 1
            return send(405, 'write_not_allowed')
          }
          let bytes
          try { bytes = await readRequestBody(request) } catch {
            activity.blockedWrites += 1
            return send(413, 'request_too_large')
          }
          let payload
          try { payload = JSON.parse(bytes.toString('utf8')) } catch {
            activity.blockedWrites += 1
            return send(400, 'invalid_task')
          }
          const expected = {
            source_id: sourceId,
            target_metric: 'sales',
            target_date: EXPECTED_DATE,
            filters: {},
            group_by: [],
          }
          if (JSON.stringify(payload) !== JSON.stringify(expected) || bytes.toString('utf8') !== JSON.stringify(expected)) {
            activity.blockedWrites += 1
            return send(400, 'task_not_allowed')
          }

          let upstreamResponse
          try {
            upstreamResponse = await fetch(new URL('/api/investigations', apiOrigin), {
              method: 'POST',
              headers: { 'content-type': 'application/json', accept: 'application/json' },
              body: bytes,
              redirect: 'error',
              signal: AbortSignal.timeout(API_TIMEOUT_MS),
            })
          } catch {
            return send(502, 'upstream_unavailable')
          }
          const upstreamBody = await readLimited(upstreamResponse).catch(() => null)
          if (!upstreamBody) return send(502, 'upstream_unavailable')
          let created
          try { created = JSON.parse(upstreamBody.toString('utf8')) } catch { return send(502, 'upstream_unavailable') }
          if (upstreamResponse.status !== 202 || !UUID.test(created?.investigation_run_id ?? '') ||
              created.source_id !== sourceId || created.provider !== 'synthetic' || created.environment !== 'sandbox' ||
              created.status !== 'queued' || created.requested_metric !== 'sales' || created.data_version !== EXPECTED_FIXTURE ||
              created.tool_call_count !== 0 || created.observation_count !== 0 || created.evidence_count !== 0 || created.diagnosis_count !== 0) {
            return send(502, 'unexpected_task_response')
          }
          activity.runId = created.investigation_run_id
          activity.forwardedPosts += 1
          return send(upstreamResponse.status, upstreamBody, upstreamResponse.headers.get('content-type') ?? 'application/json')
        }

        if (request.method !== 'GET') {
          if (['PUT', 'PATCH', 'DELETE', 'POST'].includes(request.method)) activity.blockedWrites += 1
          return send(405, 'method_not_allowed')
        }
        let allowed = false
        if (local.pathname === '/api/investigation-sources') {
          allowed = local.search === ''
        } else if (local.pathname === '/api/investigations') {
          const keys = [...local.searchParams.keys()]
          const sourceValues = local.searchParams.getAll('source_id')
          const limitValues = local.searchParams.getAll('limit')
          const offsetValues = local.searchParams.getAll('offset')
          allowed = keys.every((key) => ['source_id', 'limit', 'offset'].includes(key)) &&
            sourceValues.length === 1 && sourceValues[0] === sourceId && limitValues.length === 1 &&
            /^(?:1|[1-9]\d?)$/.test(limitValues[0]) && Number(limitValues[0]) <= 100 && offsetValues.length === 1 &&
            /^(?:0|[1-9]\d*)$/.test(offsetValues[0])
          if (allowed) activity.listReads += 1
        } else {
          const detailMatch = local.pathname.match(/^\/api\/investigations\/([0-9a-f-]+)$/i)
          const sourceValues = local.searchParams.getAll('source_id')
          allowed = Boolean(detailMatch && UUID.test(detailMatch[1]) && activity.runId &&
            detailMatch[1] === activity.runId && [...local.searchParams.keys()].every((key) => key === 'source_id') &&
            sourceValues.length === 1 && sourceValues[0] === sourceId)
          if (allowed) activity.detailReads += 1
        }
        if (!allowed) {
          activity.rejectedApiRequests += 1
          return send(404, 'not_found')
        }
        const upstream = new URL(local.pathname + local.search, apiOrigin)
        let upstreamResponse
        try {
          upstreamResponse = await fetch(upstream, {
            method: 'GET', headers: { accept: 'application/json' }, redirect: 'error',
            signal: AbortSignal.timeout(API_TIMEOUT_MS),
          })
          const body = await readLimited(upstreamResponse)
          return send(upstreamResponse.status, body, upstreamResponse.headers.get('content-type') ?? 'application/json')
        } catch {
          return send(502, 'upstream_unavailable')
        }
      }

      if (request.method !== 'GET' && request.method !== 'HEAD') {
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) activity.blockedWrites += 1
        return send(405, 'method_not_allowed')
      }
      let pathname
      try { pathname = decodeURIComponent(local.pathname === '/' ? '/index.html' : local.pathname) } catch { return send(404, 'not_found') }
      const target = resolve(dist, `.${pathname}`)
      if (!target.startsWith(`${dist}${sep}`) && target !== dist) return send(404, 'not_found')
      const info = await stat(target).catch(() => null)
      if (!info?.isFile()) return send(404, 'not_found')
      const content = await readFile(target)
      response.writeHead(200, { 'content-type': safeContentType(target), 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' })
      response.end(request.method === 'HEAD' ? undefined : content)
    } catch {
      if (!response.headersSent) send(500, 'server_error')
      else response.destroy()
    }
  })
}

async function main() {
  // The selected write/resume mode is validated before any filesystem, browser, or API operation.
  const args = parseArguments(process.argv.slice(2))
  const { response: manifestResponse, payload: manifest } = await fetchJson(
    new URL('/__acceptance__/manifest', args.apiOrigin), 'GET', 'manifest_request',
  )
  check(manifestResponse.status === 200, 'manifest_status')
  assertManifest(manifest, args.sourceId)

  const { response: catalogResponse, payload: catalog } = await fetchJson(
    new URL('/api/investigation-sources', args.apiOrigin), 'GET', 'preflight_catalog',
  )
  check(catalogResponse.status === 200, 'preflight_catalog_status')
  const source = getSource(catalog, args.sourceId)
  assertSource(source, args.sourceId)
  let runId = args.resumeRunId
  let facts = null
  if (runId) {
    const runs = await readRunList(args.apiOrigin, args.sourceId, 'resume_history')
    check(runs.length === 1, 'resume_history_not_unique')
    assertResumableRun(runs[0], args.sourceId, runId)
    const detailUrl = new URL(`/api/investigations/${encodeURIComponent(runId)}`, args.apiOrigin)
    detailUrl.searchParams.set('source_id', args.sourceId)
    const { response: detailResponse, payload: detail } = await fetchJson(detailUrl, 'GET', 'resume_detail')
    check(detailResponse.status === 200, 'resume_detail_status')
    facts = assertSuccessfulDetail(detail, args.sourceId, runId)
  } else {
    await assertEmptyHistory(args.apiOrigin, args.sourceId, 'preflight_history')
  }

  await stat(dist).catch(() => { throw new Error('dist_missing') })
  await mkdir(args.output, { recursive: true })
  const outputInfo = await stat(args.output).catch(() => null)
  check(outputInfo?.isDirectory(), 'output_directory')

  const profile = await mkdtemp(join(tmpdir(), 'metricsleuth-postgres-task-roundtrip-'))
  const profileResolved = resolve(profile)
  const tempResolved = resolve(tmpdir())
  check(profileResolved.startsWith(`${tempResolved}${sep}`), 'profile_path')
  const outputResolved = resolve(args.output)
  const browserExecutable = process.env.METRICSLEUTH_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
  const activity = { postAttempts: 0, forwardedPosts: 0, blockedWrites: 0, rejectedApiRequests: 0, listReads: 0, detailReads: 0, runId }
  const server = createLocalServer(args.apiOrigin, args.sourceId, args.writeAuthorized, activity)
  let browser
  let socket
  let serverListening = false
  let stage = 'browser_start'

  try {
    await new Promise((resolveListen, rejectListen) => {
      server.once('error', rejectListen)
      server.listen(0, '127.0.0.1', resolveListen)
    })
    serverListening = true
    const origin = `http://127.0.0.1:${server.address().port}`
    browser = spawn(browserExecutable, [
      '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profileResolved}`,
      '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
      '--disable-component-update', '--disable-sync', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
      'about:blank',
    ], { windowsHide: true, stdio: 'ignore' })
    let browserSpawnFailed = false
    browser.once('error', () => { browserSpawnFailed = true })
    const delay = (ms) => new Promise((done) => setTimeout(done, ms))
    async function until(operation, label, timeout = API_TIMEOUT_MS) {
      const deadline = Date.now() + timeout
      while (Date.now() < deadline) {
        if (browserSpawnFailed) throw new Error('browser_spawn')
        if (browser.exitCode !== null) throw new Error('browser_exit')
        try { const value = await operation(); if (value) return value } catch { /* bounded startup/render wait */ }
        await delay(100)
      }
      throw new Error(label)
    }

    stage = 'browser_debug_endpoint'
    const debugPort = await until(async () => {
      const contents = await readFile(join(profileResolved, 'DevToolsActivePort'), 'utf8')
      const candidate = Number(contents.split('\n')[0])
      return Number.isInteger(candidate) && candidate > 0 ? candidate : null
    }, 'browser_debug_endpoint')
    const targetsResponse = await fetch(`http://127.0.0.1:${debugPort}/json/list`, { signal: AbortSignal.timeout(API_TIMEOUT_MS) })
    const targets = await targetsResponse.json()
    const page = targets.find((target) => target.type === 'page')
    check(page?.webSocketDebuggerUrl, 'browser_page')
    socket = new WebSocket(page.webSocketDebuggerUrl)
    await new Promise((resolveOpen, rejectOpen) => {
      const timer = setTimeout(() => rejectOpen(new Error('browser_socket_timeout')), API_TIMEOUT_MS)
      socket.onopen = () => { clearTimeout(timer); resolveOpen() }
      socket.onerror = () => { clearTimeout(timer); rejectOpen(new Error('browser_socket')) }
    })

    let counter = 0
    const pending = new Map()
    socket.onmessage = ({ data }) => {
      let message
      try { message = JSON.parse(data) } catch { return }
      const handler = pending.get(message.id)
      if (!handler) return
      pending.delete(message.id)
      if (message.error) handler.reject(new Error('browser_command'))
      else handler.resolve(message.result)
    }
    const cdp = (method, params = {}) => new Promise((resolveCommand, rejectCommand) => {
      const id = ++counter
      const timer = setTimeout(() => { pending.delete(id); rejectCommand(new Error('browser_command_timeout')) }, API_TIMEOUT_MS)
      pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolveCommand(value) },
        reject: (error) => { clearTimeout(timer); rejectCommand(error) },
      })
      socket.send(JSON.stringify({ id, method, params }))
    })
    const evaluate = async (expression) => {
      const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
      if (result.exceptionDetails) throw new Error('browser_assertion')
      return result.result.value
    }
    const click = (selector) => evaluate(`{const el=Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(item=>item.getClientRects().length); if(!el) throw new Error('missing'); el.click(); true}`)
    const bodyText = () => evaluate('document.body.innerText')
    const setSelect = (selector, value) => evaluate(`{const el=document.querySelector(${JSON.stringify(selector)}); if(!el) throw new Error('missing'); const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set; setter.call(el,${JSON.stringify(value)}); el.dispatchEvent(new Event('change',{bubbles:true})); el.value===${JSON.stringify(value)}}`)
    const setInput = (selector, value) => evaluate(`{const el=document.querySelector(${JSON.stringify(selector)}); if(!el) throw new Error('missing'); const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; setter.call(el,${JSON.stringify(value)}); el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); el.value===${JSON.stringify(value)}}`)

    stage = 'browser_initial_load'
    await cdp('Page.navigate', { url: origin })
    await until(async () => evaluate(`!!document.querySelector('[data-testid="source-select"] option[value="${args.sourceId}"]')`), 'browser_catalog')
    const selectedSource = await setSelect('[data-testid="source-select"]', args.sourceId)
    check(selectedSource, 'browser_source_select')
    await click('[data-testid="nav-investigation"]')
    const historyRunSelector = (id) => `[data-testid="history-run"][data-run-id="${id}"]`
    const assertRendered = async (prefix) => {
      const text = await bodyText()
      check(text.includes(runId), `${prefix}_rendered_run`)
      check(text.includes(args.sourceId), `${prefix}_rendered_source`)
      check(text.includes(facts.observationId), `${prefix}_rendered_observation`)
      check(text.includes(facts.evidenceId), `${prefix}_rendered_evidence`)
      check(text.includes(facts.currentValue), `${prefix}_rendered_current_raw`)
      check(text.includes(facts.baselineValue), `${prefix}_rendered_baseline_raw`)
      check(text.includes(facts.relativeChange), `${prefix}_rendered_relative_raw`)
      check(text.includes('未发现明显异常'), `${prefix}_rendered_diagnosis_status`)
      check(text.includes(facts.limitation), `${prefix}_rendered_controlled_limitation`)
      check(text.includes('无需归因（未发现明显异常）'), `${prefix}_rendered_no_driver`)
      check(text.includes('无需定位影响范围（未发现明显异常）'), `${prefix}_rendered_empty_scope`)
      const toolSummary = await evaluate(`Array.from(document.querySelectorAll('.trace-item summary')).some(el=>el.getClientRects().length)`)
      check(toolSummary, `${prefix}_tool_trace_visible`)
      await click('.trace-item summary')
      const expanded = await bodyText()
      check(expanded.includes(facts.toolCallId), `${prefix}_rendered_tool_call`)
      const displayedNumbers = await evaluate(`Array.from(document.querySelectorAll('[data-testid="decimal-value"]')).map(el=>el.innerText.replace('≈','').trim())`)
      check(displayedNumbers.length >= 3 && displayedNumbers.some((value) => value.includes('100')) &&
        displayedNumbers.some((value) => value === '0' || value === '0.0'), `${prefix}_rendered_summary_values`)
      return text
    }

    let beforeQuietPeriod
    if (args.resumeRunId) {
      stage = 'browser_resume_history'
      await until(async () => activity.listReads > 0 && evaluate(`!!document.querySelector(${JSON.stringify(historyRunSelector(runId))})`), 'browser_resume_run')
      await click(historyRunSelector(runId))
      await until(async () => {
        const text = await bodyText()
        return text.includes(runId) && text.includes('已完成') && text.includes(facts.observationId)
      }, 'browser_resume_detail')
      await assertRendered('browser_resume')
      beforeQuietPeriod = { details: activity.detailReads, lists: activity.listReads }
      check(beforeQuietPeriod.details >= 1, 'browser_resume_detail_reads')
      stage = 'browser_resume_polling_stop'
      await delay(2300)
      check(activity.detailReads === beforeQuietPeriod.details && activity.listReads === beforeQuietPeriod.lists, 'browser_resume_polling_continued')
    } else {
      stage = 'browser_empty_history'
      await until(async () => activity.listReads > 0 && (await bodyText()).includes('还没有调查记录'), 'browser_empty_history')
      check(!(await evaluate(`!!document.querySelector('[data-testid="history-run"]')`)), 'browser_history_not_empty')

      stage = 'browser_prepare_task'
      check(await setSelect('[data-testid="metric-select"]', 'sales'), 'browser_metric_select')
      check(await setInput('[data-testid="target-date"]', EXPECTED_DATE), 'browser_target_date')
      const formValues = await evaluate(`({metric:document.querySelector('[data-testid="metric-select"]')?.value,date:document.querySelector('[data-testid="target-date"]')?.value,disabled:document.querySelector('[data-testid="submit-investigation"]')?.disabled})`)
      check(formValues?.metric === 'sales' && formValues.date === EXPECTED_DATE && formValues.disabled === false, 'browser_task_form')

      stage = 'browser_submit'
      check(await click('[data-testid="submit-investigation"]'), 'browser_submit_click')
      await until(async () => activity.postAttempts === 1 && activity.forwardedPosts === 1 && activity.runId, 'browser_submit_post', API_TIMEOUT_MS + 2000)
      runId = activity.runId
      check(UUID.test(runId), 'browser_created_run_id')

      stage = 'browser_wait_terminal'
      await until(async () => {
        const text = await bodyText()
        return text.includes(runId) && text.includes('已完成') && text.includes('未发现明显异常') && text.includes('100')
      }, 'browser_terminal_result', 90_000)
      beforeQuietPeriod = { details: activity.detailReads, lists: activity.listReads }
      const detailUrl = new URL(`/api/investigations/${encodeURIComponent(runId)}`, args.apiOrigin)
      detailUrl.searchParams.set('source_id', args.sourceId)
      const { response: detailResponse, payload: detail } = await fetchJson(detailUrl, 'GET', 'result_detail')
      check(detailResponse.status === 200, 'result_detail_status')
      facts = assertSuccessfulDetail(detail, args.sourceId, runId)
      check(beforeQuietPeriod.details >= 1, 'browser_detail_reads')

      stage = 'browser_terminal_polling_stop'
      await delay(2300)
      check(activity.detailReads === beforeQuietPeriod.details && activity.listReads === beforeQuietPeriod.lists, 'browser_terminal_polling_continued')
    }

    stage = 'browser_fresh_list'
    const freshListUrl = new URL('/api/investigations', args.apiOrigin)
    freshListUrl.searchParams.set('source_id', args.sourceId)
    freshListUrl.searchParams.set('limit', '20')
    freshListUrl.searchParams.set('offset', '0')
    const { response: freshListResponse, payload: freshList } = await fetchJson(freshListUrl, 'GET', 'result_list')
    check(freshListResponse.status === 200 && freshList?.items?.length === 1 &&
      freshList.items[0]?.investigation_run_id === runId && freshList.items[0]?.status === 'succeeded' &&
      freshList.items[0]?.source_id === args.sourceId && freshList.items[0]?.provider === 'synthetic' &&
      freshList.items[0]?.environment === 'sandbox' && freshList.items[0]?.requested_metric === 'sales' &&
      freshList.items[0]?.tool_call_count === 1 && freshList.items[0]?.observation_count === 1 &&
      freshList.items[0]?.evidence_count === 1 && freshList.items[0]?.diagnosis_count === 1, 'result_list_run')

    stage = 'browser_reopen_detail'
    // Verify the task is present in the UI history from the newly persisted API list.
    await cdp('Page.reload', { ignoreCache: true })
    await until(async () => evaluate(`!!document.querySelector('[data-testid="source-select"] option[value="${args.sourceId}"]')`), 'browser_reload_catalog')
    check(await setSelect('[data-testid="source-select"]', args.sourceId), 'browser_reload_source')
    await click('[data-testid="nav-investigation"]')
    await until(async () => evaluate(`!!document.querySelector(${JSON.stringify(historyRunSelector(runId))})`), 'browser_history_run')
    await click(historyRunSelector(runId))
    await until(async () => (await bodyText()).includes(facts.observationId), 'browser_reopened_detail')
    await assertRendered('browser_reopen')

    stage = 'browser_desktop_capture'
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1200, deviceScaleFactor: 1, mobile: false })
    check(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'browser_desktop_overflow')
    let capture = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
    await writeFile(join(outputResolved, 'postgres-task-roundtrip-desktop.png'), Buffer.from(capture.data, 'base64'))

    stage = 'browser_mobile_capture'
    await cdp('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true })
    check(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'browser_mobile_overflow')
    capture = await cdp('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
    await writeFile(join(outputResolved, 'postgres-task-roundtrip-mobile.png'), Buffer.from(capture.data, 'base64'))

    check(activity.postAttempts === (args.resumeRunId ? 0 : 1) && activity.forwardedPosts === (args.resumeRunId ? 0 : 1) &&
      activity.blockedWrites === 0 && activity.rejectedApiRequests === 0, 'proxy_guard')
    await cdp('Browser.close').catch(() => {})
    console.log(JSON.stringify({
      status: 'PASS',
      acceptance_kind: 'controlled_browser_task',
      real_database: true,
      controlled_runner: true,
      real_model: false,
      resume_read_only: Boolean(args.resumeRunId),
      run_id: runId,
      source_id: args.sourceId,
      post_count: activity.forwardedPosts,
      tool_calls: 1,
      observations: 1,
      evidence: 1,
      diagnoses: 1,
      diagnosis_status: 'no_material_anomaly',
      attribution_claim: false,
      current_value: facts.currentValue,
      baseline_value: facts.baselineValue,
      relative_change: facts.relativeChange,
      limitation_visible: true,
      screenshots: ['postgres-task-roundtrip-desktop.png', 'postgres-task-roundtrip-mobile.png'],
    }))
  } catch (error) {
    const safeStage = typeof error?.message === 'string' && /^[a-z0-9_]+$/.test(error.message) ? error.message : stage
    console.error(`FAIL ${safeStage}`)
    process.exitCode = 1
  } finally {
    socket?.close()
    if (browser && browser.exitCode === null) {
      browser.kill()
      await Promise.race([new Promise((done) => browser.once('exit', done)), new Promise((done) => setTimeout(done, 3000))])
    }
    if (serverListening) await new Promise((done) => server.close(done))
    if (profileResolved.startsWith(`${tempResolved}${sep}`)) await rm(profileResolved, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }).catch(() => {})
  }
}

main().catch((error) => {
  const code = typeof error?.message === 'string' && /^[a-z0-9_]+$/.test(error.message) ? error.message : 'setup_failed'
  console.error(`FAIL ${code}`)
  process.exitCode = 1
})
