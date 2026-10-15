// One explicitly authorized browser -> API -> Worker -> real SDK -> PostgreSQL acceptance.
// The companion Python server only permits the dedicated local Synthetic database.
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const dist = resolve(frontend, 'dist')
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const REQUEST_TIMEOUT_MS = 15_000
const TERMINAL_TIMEOUT_MS = 145_000
const MAX_BODY_BYTES = 1_048_576

function fail(code) { throw new Error(code) }
function check(value, code) { if (!value) fail(code) }

function parseArguments(argv) {
  const values = Object.create(null)
  let authorization = 0
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index]
    if (name === '--allow-live-model-browser-write') {
      authorization += 1
      continue
    }
    if (!['--api', '--output'].includes(name) || Object.hasOwn(values, name)) fail('arguments')
    const value = argv[index + 1]
    if (!value || value.startsWith('--')) fail('arguments')
    values[name] = value
    index += 1
  }
  if (authorization !== 1 || Object.keys(values).length !== 2) fail('authorization_required')
  let api
  try { api = new URL(values['--api']) } catch { fail('api_url') }
  const host = api.hostname.toLowerCase()
  check(api.protocol === 'http:' && (host === '::1' || host === '[::1]' || /^127(?:\.\d{1,3}){3}$/.test(host)) &&
    !api.username && !api.password && !api.search && !api.hash && (api.pathname === '/' || api.pathname === ''), 'api_url')
  const output = resolve(values['--output'])
  check(/^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(values['--output']), 'output_path')
  return { apiOrigin: api.origin, output }
}

async function limitedBody(response) {
  const reader = response.body?.getReader()
  if (!reader) return Buffer.alloc(0)
  const chunks = []
  let length = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    length += value.byteLength
    if (length > MAX_BODY_BYTES) {
      await reader.cancel().catch(() => {})
      fail('response_size')
    }
    chunks.push(Buffer.from(value))
  }
  return Buffer.concat(chunks, length)
}

async function jsonRequest(url, method, stage, body) {
  let response
  try {
    response = await fetch(url, { method, redirect: 'error', signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      headers: { accept: 'application/json', ...(body ? { 'content-type': 'application/json' } : {}) }, ...(body ? { body } : {}) })
  } catch { fail(stage) }
  const bytes = await limitedBody(response).catch(() => fail(stage))
  try { return { response, payload: JSON.parse(bytes.toString('utf8')) } } catch { fail(stage) }
}

function assertManifest(manifest) {
  const keys = ['acceptance_kind', 'api_mode', 'controlled_runner', 'data_profile', 'data_version', 'database', 'max_tool_calls', 'max_turns', 'real_model', 'request_filters', 'source_id', 'target_date', 'target_metric']
  check(manifest && typeof manifest === 'object' && !Array.isArray(manifest), 'manifest_shape')
  check(Object.keys(manifest).sort().join(',') === keys.sort().join(','), 'manifest_keys')
  check(manifest.acceptance_kind === 'live_model_browser_task' && manifest.database === 'metricsleuth_r2_acceptance', 'manifest_identity')
  check(manifest.real_model === true && manifest.controlled_runner === false && manifest.data_profile === 'synthetic', 'manifest_mode')
  check(UUID.test(manifest.source_id) && manifest.target_metric === 'sales' && manifest.target_date === '2026-10-10', 'manifest_task')
  check(manifest.request_filters && Object.keys(manifest.request_filters).length === 1 && UUID.test(manifest.request_filters.asin), 'manifest_filter')
  check(manifest.max_tool_calls === 8 && manifest.max_turns === 10 && typeof manifest.data_version === 'string' && manifest.data_version.length > 0, 'manifest_budget')
}

function assertCatalog(catalog, manifest) {
  check(catalog && Array.isArray(catalog.items) && catalog.items.length === 1, 'catalog_shape')
  const source = catalog.items[0]
  check(source?.source_id === manifest.source_id && source.provider === 'synthetic' && source.environment === 'sandbox' && source.data_version === manifest.data_version, 'catalog_source')
  const sales = source.metrics?.find((item) => item?.metric_id === 'sales')
  check(sales?.supported === true && Array.isArray(sales.dimensions) && sales.dimensions.includes('asin'), 'catalog_capability')
}

function contentType(path) {
  return ({ '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png' })[extname(path)] ?? 'application/octet-stream'
}

async function requestBody(request) {
  const chunks = []
  let length = 0
  for await (const chunk of request) {
    length += chunk.length
    if (length > MAX_BODY_BYTES) fail('request_size')
    chunks.push(chunk)
  }
  return Buffer.concat(chunks, length)
}

function createProxy(apiOrigin, manifest, activity) {
  return createServer(async (request, response) => {
    const send = (status, body, type = 'text/plain; charset=utf-8') => {
      response.writeHead(status, { 'content-type': type, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' })
      response.end(body)
    }
    try {
      const local = new URL(request.url, 'http://127.0.0.1')
      if (local.pathname.startsWith('/api/')) {
        if (request.method === 'POST' && local.pathname === '/api/investigations' && local.search === '') {
          activity.postAttempts += 1
          if (activity.postAttempts !== 1 || activity.runId || !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers['content-type'] ?? '')) return send(405, 'write_not_allowed')
          const body = await requestBody(request)
          let payload
          try { payload = JSON.parse(body.toString('utf8')) } catch { return send(400, 'invalid_task') }
          const expected = { source_id: manifest.source_id, target_metric: manifest.target_metric, target_date: manifest.target_date, filters: manifest.request_filters, group_by: [] }
          if (JSON.stringify(payload) !== JSON.stringify(expected)) return send(400, 'task_not_allowed')
          const upstream = await fetch(new URL('/api/investigations', apiOrigin), { method: 'POST', redirect: 'error', signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), headers: { accept: 'application/json', 'content-type': 'application/json' }, body })
          const upstreamBody = await limitedBody(upstream)
          let created
          try { created = JSON.parse(upstreamBody.toString('utf8')) } catch { return send(502, 'upstream_invalid') }
          if (upstream.status !== 202 || !UUID.test(created?.investigation_run_id) || created.source_id !== manifest.source_id || created.status !== 'queued' || created.tool_call_count !== 0 || created.observation_count !== 0 || created.evidence_count !== 0 || created.diagnosis_count !== 0) return send(502, 'upstream_unexpected')
          activity.runId = created.investigation_run_id
          activity.forwardedPosts += 1
          return send(202, upstreamBody, upstream.headers.get('content-type') ?? 'application/json')
        }
        if (request.method !== 'GET') { activity.blockedWrites += 1; return send(405, 'method_not_allowed') }
        let allowed = false
        if (local.pathname === '/api/investigation-sources') {
          allowed = local.search === ''
          activity.catalogReads += 1
        } else if (local.pathname === '/api/investigations') {
          const keys = [...local.searchParams.keys()]
          allowed = keys.every((key) => ['source_id', 'limit', 'offset'].includes(key)) && local.searchParams.get('source_id') === manifest.source_id && local.searchParams.getAll('source_id').length === 1 && /^\d+$/.test(local.searchParams.get('limit') ?? '') && /^\d+$/.test(local.searchParams.get('offset') ?? '')
          if (allowed) activity.listReads += 1
        } else {
          const match = local.pathname.match(/^\/api\/investigations\/([0-9a-f-]+)$/i)
          allowed = Boolean(match && activity.runId && match[1] === activity.runId && local.searchParams.get('source_id') === manifest.source_id && local.searchParams.getAll('source_id').length === 1 && [...local.searchParams.keys()].every((key) => key === 'source_id'))
          if (allowed) activity.detailReads += 1
        }
        if (!allowed) { activity.rejectedApiRequests += 1; return send(404, 'not_found') }
        const upstream = await fetch(new URL(local.pathname + local.search, apiOrigin), { method: 'GET', redirect: 'error', signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), headers: { accept: 'application/json' } })
        const body = await limitedBody(upstream)
        if (local.pathname.startsWith('/api/investigations/') && upstream.status === 200) {
          try {
            const detail = JSON.parse(body.toString('utf8'))
            activity.latestStatus = detail?.run?.status ?? null
            if (activity.latestStatus === 'succeeded') {
              const counts = detail.run
              check(Array.isArray(detail.tool_calls) && detail.tool_calls.length > 0 && Array.isArray(detail.observations) && detail.observations.length > 0 && Array.isArray(detail.evidence) && detail.evidence.length > 0 && Array.isArray(detail.diagnoses) && detail.diagnoses.length === 1, 'persisted_facts')
              check(counts.tool_call_count === detail.tool_calls.length && counts.observation_count === detail.observations.length && counts.evidence_count === detail.evidence.length && counts.diagnosis_count === detail.diagnoses.length, 'persisted_counts')
              const diagnosis = detail.diagnoses[0]
              const evidenceIds = new Set(detail.evidence.map((item) => item.evidence_id))
              check(Array.isArray(diagnosis.evidence_ids) && diagnosis.evidence_ids.length > 0 && diagnosis.evidence_ids.every((id) => evidenceIds.has(id)), 'diagnosis_evidence')
              activity.factCounts = { tool_calls: detail.tool_calls.length, observations: detail.observations.length, evidence: detail.evidence.length, diagnoses: detail.diagnoses.length }
              activity.primaryDriver = typeof diagnosis.primary_driver === 'string' ? diagnosis.primary_driver : null
            }
          } catch { return send(502, 'upstream_invalid') }
        }
        return send(upstream.status, body, upstream.headers.get('content-type') ?? 'application/json')
      }
      if (!['GET', 'HEAD'].includes(request.method)) return send(405, 'method_not_allowed')
      let pathname
      try { pathname = decodeURIComponent(local.pathname === '/' ? '/index.html' : local.pathname) } catch { return send(404, 'not_found') }
      const target = resolve(dist, `.${pathname}`)
      if (!target.startsWith(`${dist}${sep}`) && target !== dist) return send(404, 'not_found')
      const info = await stat(target).catch(() => null)
      if (!info?.isFile()) return send(404, 'not_found')
      const content = await readFile(target)
      response.writeHead(200, { 'content-type': contentType(target), 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' })
      response.end(request.method === 'HEAD' ? undefined : content)
    } catch {
      if (!response.headersSent) send(500, 'proxy_error')
      else response.destroy()
    }
  })
}

async function main() {
  const args = parseArguments(process.argv.slice(2))
  const manifestResult = await jsonRequest(new URL('/__acceptance__/manifest', args.apiOrigin), 'GET', 'manifest_request')
  check(manifestResult.response.status === 200, 'manifest_status')
  const manifest = manifestResult.payload
  assertManifest(manifest)
  await mkdir(args.output, { recursive: true })
  const catalogResult = await jsonRequest(new URL('/api/investigation-sources', args.apiOrigin), 'GET', 'catalog_request')
  check(catalogResult.response.status === 200, 'catalog_status')
  assertCatalog(catalogResult.payload, manifest)
  const profile = await mkdtemp(join(tmpdir(), 'metricsleuth-live-browser-profile-'))
  const profileResolved = resolve(profile)
  check(profileResolved.startsWith(`${resolve(tmpdir())}${sep}`), 'profile_path')
  const activity = { postAttempts: 0, forwardedPosts: 0, blockedWrites: 0, rejectedApiRequests: 0, catalogReads: 0, listReads: 0, detailReads: 0, runId: null, latestStatus: null, factCounts: null, primaryDriver: null }
  const proxy = createProxy(args.apiOrigin, manifest, activity)
  const browserExecutable = process.env.METRICSLEUTH_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
  let browser
  let socket
  try {
    await new Promise((resolveListen, rejectListen) => { proxy.once('error', rejectListen); proxy.listen(0, '127.0.0.1', resolveListen) })
    const origin = `http://127.0.0.1:${proxy.address().port}`
    browser = spawn(browserExecutable, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profileResolved}`, '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', 'about:blank'], { windowsHide: true, stdio: 'ignore' })
    const wait = (ms) => new Promise((done) => setTimeout(done, ms))
    async function until(operation, code, timeout = REQUEST_TIMEOUT_MS) {
      const deadline = Date.now() + timeout
      while (Date.now() < deadline) {
        try { const result = await operation(); if (result) return result } catch { /* bounded browser startup / render wait */ }
        await wait(100)
      }
      fail(code)
    }
    const debugPort = await until(async () => {
      const candidate = Number((await readFile(join(profileResolved, 'DevToolsActivePort'), 'utf8')).split('\n')[0])
      return Number.isInteger(candidate) && candidate > 0 ? candidate : null
    }, 'browser_debug_endpoint')
    const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) })).json()
    const page = targets.find((target) => target.type === 'page')
    check(page?.webSocketDebuggerUrl, 'browser_page')
    socket = new WebSocket(page.webSocketDebuggerUrl)
    await new Promise((resolveOpen, rejectOpen) => { const timer = setTimeout(() => rejectOpen(new Error('browser_socket')), REQUEST_TIMEOUT_MS); socket.onopen = () => { clearTimeout(timer); resolveOpen() }; socket.onerror = () => { clearTimeout(timer); rejectOpen(new Error('browser_socket')) } })
    let command = 0
    const pending = new Map()
    socket.onmessage = ({ data }) => { let message; try { message = JSON.parse(data) } catch { return }; const handler = pending.get(message.id); if (!handler) return; pending.delete(message.id); if (message.error) handler.reject(new Error('browser_command')); else handler.resolve(message.result) }
    const cdp = (method, params = {}) => new Promise((resolveCommand, rejectCommand) => { const id = ++command; const timer = setTimeout(() => { pending.delete(id); rejectCommand(new Error('browser_command_timeout')) }, REQUEST_TIMEOUT_MS); pending.set(id, { resolve: (value) => { clearTimeout(timer); resolveCommand(value) }, reject: (error) => { clearTimeout(timer); rejectCommand(error) } }); socket.send(JSON.stringify({ id, method, params })) })
    const evaluate = async (expression) => { const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (result.exceptionDetails) fail('browser_assertion'); return result.result.value }
    const setValue = (selector, value, type) => evaluate(`{const element=document.querySelector(${JSON.stringify(selector)}); if(!element) throw new Error('missing'); const setter=Object.getOwnPropertyDescriptor(${type}.prototype,'value').set; setter.call(element,${JSON.stringify(value)}); element.dispatchEvent(new Event('input',{bubbles:true})); element.dispatchEvent(new Event('change',{bubbles:true})); element.value===${JSON.stringify(value)}}`)
    const click = (selector) => evaluate(`{const element=Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(item=>item.getClientRects().length); if(!element) throw new Error('missing'); element.click(); true}`)
    const bodyText = () => evaluate('document.body.innerText')
    await cdp('Page.navigate', { url: origin })
    await until(() => evaluate(`!!document.querySelector('[data-testid="source-select"] option[value="${manifest.source_id}"]')`), 'browser_catalog')
    await click('[data-testid="nav-investigation"]')
    await until(() => evaluate(`!!document.querySelector('[data-testid="metric-select"]')`), 'browser_investigation')
    check(await setValue('[data-testid="metric-select"]', 'sales', 'HTMLSelectElement'), 'browser_metric')
    check(await setValue('[data-testid="target-date"]', manifest.target_date, 'HTMLInputElement'), 'browser_date')
    check(await setValue('[data-testid="filter-dimension"]', 'asin', 'HTMLSelectElement'), 'browser_filter_dimension')
    await until(() => evaluate('document.querySelector(\'[data-testid="filter-value"]\')?.disabled === false'), 'browser_filter_enabled')
    check(await setValue('[data-testid="filter-value"]', manifest.request_filters.asin, 'HTMLInputElement'), 'browser_filter_value')
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
    check(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'browser_desktop_overflow')
    await click('[data-testid="submit-investigation"]')
    await until(() => activity.forwardedPosts === 1 && UUID.test(activity.runId ?? ''), 'browser_submit', REQUEST_TIMEOUT_MS + 3_000)
    await until(async () => activity.latestStatus === 'succeeded' && activity.factCounts !== null && (await bodyText()).includes(activity.runId), 'browser_terminal', TERMINAL_TIMEOUT_MS)
    const terminalText = await bodyText()
    check(terminalText.includes('已定位主要变化') || terminalText.includes('暂无显著异常') || terminalText.includes('需要更多证据'), 'browser_diagnosis_rendered')
    const screenshot = await cdp('Page.captureScreenshot', { format: 'png' })
    await writeFile(join(args.output, 'live-model-browser-task-desktop.png'), Buffer.from(screenshot.data, 'base64'))
    await cdp('Page.reload', { ignoreCache: true })
    await until(() => evaluate(`!!document.querySelector('[data-testid="history-run"][data-run-id="${activity.runId}"]')`), 'browser_refresh_history')
    await click(`[data-testid="history-run"][data-run-id="${activity.runId}"]`)
    await until(async () => (await bodyText()).includes(activity.runId) && activity.detailReads >= 2, 'browser_refresh_detail')
    check(activity.postAttempts === 1 && activity.forwardedPosts === 1 && activity.blockedWrites === 0 && activity.rejectedApiRequests === 0, 'browser_request_boundary')
    const completion = await jsonRequest(new URL('/__acceptance__/complete', args.apiOrigin), 'POST', 'acceptance_complete', JSON.stringify({}))
    check(completion.response.status === 200 && completion.payload?.status === 'accepted', 'acceptance_complete')
    console.log(JSON.stringify({ status: 'passed', boundary: 'one browser-submitted real SDK task; isolated Synthetic PostgreSQL; no external business data', run_id: activity.runId, tool_calls: activity.factCounts.tool_calls, observations: activity.factCounts.observations, evidence: activity.factCounts.evidence, diagnoses: activity.factCounts.diagnoses, primary_driver: activity.primaryDriver, api_mode: manifest.api_mode, output: args.output }))
  } finally {
    socket?.close()
    if (browser && browser.exitCode === null) { browser.kill(); await Promise.race([new Promise((done) => browser.once('exit', done)), new Promise((done) => setTimeout(done, 3_000))]) }
    await new Promise((done) => proxy.close(done)).catch(() => {})
    if (resolve(profile).startsWith(`${resolve(tmpdir())}${sep}`)) await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }).catch(() => {})
  }
}

main().catch((error) => { console.log(JSON.stringify({ status: 'failed', code: error instanceof Error && /^[a-z_]+$/.test(error.message) ? error.message : 'browser_acceptance_failed' })); process.exitCode = 1 })
