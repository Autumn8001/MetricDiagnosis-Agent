// Read-only real PostgreSQL metric observation browser acceptance.
// Usage: node scripts/verify-metric-observation.mjs --api http://127.0.0.1:8001 --source UUID --profile synthetic|olist --output C:/absolute/evidence [--mode read|scan]
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const dist = resolve(frontend, 'dist')
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const MAX_PROXY_BYTES = 2 * 1024 * 1024
const REQUEST_TIMEOUT_MS = 10_000
const PROFILE_CASES = {
  synthetic: {
    metric: 'sales',
    date: '2026-10-10',
    current: '100.00',
    baseline: '100.00',
    status: 'normal',
    candidate: false,
    environment: 'sandbox',
    missingDate: '2000-01-01',
  },
  olist: {
    metric: 'merchandise_gmv',
    date: '2017-03-20',
    current: '16861.09',
    baseline: '13355.61',
    status: 'inconclusive',
    candidate: null,
    environment: 'validation',
    missingDate: '2000-01-01',
  },
}

function parseArguments(argv) {
  const values = Object.create(null)
  const accepted = new Set(['--api', '--source', '--profile', '--output', '--mode'])
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index]
    if (!accepted.has(name) || Object.hasOwn(values, name)) throw new Error('arguments')
    const value = argv[index + 1]
    if (!value || value.startsWith('--')) throw new Error('arguments')
    values[name] = value
    index += 1
  }
  if (['--api', '--source', '--profile', '--output'].some((key) => !Object.hasOwn(values, key))) throw new Error('arguments')
  const mode = values['--mode'] ?? 'read'
  if (mode !== 'read' && mode !== 'scan') throw new Error('arguments')

  let api
  try { api = new URL(values['--api']) } catch { throw new Error('api_url') }
  const host = api.hostname.toLowerCase()
  const loopback = host === 'localhost' || host === '[::1]' || /^127(?:\.\d{1,3}){3}$/.test(host)
  if (api.protocol !== 'http:' || !loopback || api.username || api.password || api.search || api.hash ||
      (api.pathname !== '/' && api.pathname !== '')) throw new Error('api_url')
  if (!UUID.test(values['--source'])) throw new Error('identifier')
  if (!Object.hasOwn(PROFILE_CASES, values['--profile'])) throw new Error('profile')
  if (!/^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(values['--output'])) throw new Error('output_path')
  return {
    apiOrigin: api.origin,
    sourceId: values['--source'],
    profile: values['--profile'],
    mode,
    fixture: PROFILE_CASES[values['--profile']],
    output: resolve(values['--output']),
  }
}

function check(condition, label) {
  if (!condition) throw new Error(label)
}

async function getJson(url, stage) {
  let response
  try {
    response = await fetch(url, {
      method: 'GET',
      redirect: 'error',
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    })
  } catch {
    throw new Error(stage)
  }
  if (!response.ok) throw new Error(stage)
  try { return await response.json() } catch { throw new Error(stage) }
}

function safeContentType(path) {
  return ({
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
  })[extname(path)] ?? 'application/octet-stream'
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
    if (size > MAX_PROXY_BYTES) {
      await reader.cancel().catch(() => {})
      throw new Error('proxy_size')
    }
    chunks.push(Buffer.from(value))
  }
  return Buffer.concat(chunks, size)
}

function hasOnlyUniqueParams(url, allowed) {
  const seen = new Set()
  for (const key of url.searchParams.keys()) {
    if (!allowed.has(key) || seen.has(key)) return false
    seen.add(key)
  }
  return true
}

function metricReadFact(body) {
  let payload
  try { payload = JSON.parse(body.toString('utf8')) } catch { throw new Error('metric_proxy_payload') }
  const observation = payload?.observation
  return {
    target_metric: payload?.target_metric,
    target_date: payload?.target_date,
    anomaly_candidate: payload?.anomaly_candidate,
    query_reference: payload?.query_reference,
    observation: observation === null ? null : {
      status: observation?.status,
      source_status: observation?.source_status,
      current_value: observation?.current_value,
      baseline_value: observation?.baseline_value,
      current_period_start: observation?.current_period_start,
      current_period_end: observation?.current_period_end,
      baseline_period_start: observation?.baseline_period_start,
      baseline_period_end: observation?.baseline_period_end,
    },
  }
}

function metricScanFact(body) {
  try { return JSON.parse(body.toString('utf8')) } catch { throw new Error('metric_scan_payload') }
}

function createReadonlyServer(apiOrigin, args, activity) {
  return createServer(async (request, response) => {
    const send = (status, body, contentType = 'text/plain; charset=utf-8') => {
      response.writeHead(status, {
        'content-type': contentType,
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff',
      })
      response.end(body)
    }
    try {
      const local = new URL(request.url, 'http://127.0.0.1')
      let delayMetricResponse = false
      if (request.method !== 'GET') {
        activity.blockedWrites += 1
        return send(405, 'method_not_allowed')
      }
      if (local.pathname.startsWith('/api/')) {
        let allowed = false
        if (local.pathname === '/api/investigation-sources') {
          allowed = local.search === ''
        } else if (local.pathname === '/api/investigations') {
          allowed = hasOnlyUniqueParams(local, new Set(['source_id', 'limit', 'offset'])) &&
            (local.searchParams.get('source_id') === args.sourceId ||
              (args.mode === 'scan' && activity.alternateSourceId && local.searchParams.get('source_id') === activity.alternateSourceId))
        } else {
          const detailMatch = local.pathname.match(/^\/api\/investigations\/([0-9a-f-]+)$/i)
          allowed = Boolean(detailMatch && UUID.test(detailMatch[1]) &&
            hasOnlyUniqueParams(local, new Set(['source_id'])) && local.searchParams.get('source_id') === args.sourceId)
        }

        if (local.pathname === '/api/metrics/observation') {
          const expectedDates = new Set([args.fixture.date, args.fixture.missingDate])
          allowed = hasOnlyUniqueParams(local, new Set(['source_id', 'target_metric', 'target_date'])) &&
            [...local.searchParams.keys()].length === 3 &&
            local.searchParams.get('source_id') === args.sourceId &&
            local.searchParams.get('target_metric') === args.fixture.metric &&
            expectedDates.has(local.searchParams.get('target_date'))
          if (allowed) {
            const date = local.searchParams.get('target_date')
            if (activity.failNextMetric && date === args.fixture.date) {
              activity.failNextMetric = false
              activity.controlled503 += 1
              return send(503, JSON.stringify({ detail: {
                code: 'metric_query_unavailable', message: 'METRICSLEUTH_PRIVATE_PROXY_MARKER_8f31c6',
              } }), 'application/json; charset=utf-8')
            }
            if (activity.delayNextFixture && date === args.fixture.date) {
              activity.delayNextFixture = false
              delayMetricResponse = true
            }
          }
        }
        if (args.mode === 'scan' && local.pathname === '/api/metrics/scan') {
          const expectedDates = new Set([args.fixture.date, args.fixture.missingDate])
          allowed = hasOnlyUniqueParams(local, new Set(['source_id', 'target_date'])) &&
            [...local.searchParams.keys()].length === 2 &&
            local.searchParams.get('source_id') === args.sourceId &&
            expectedDates.has(local.searchParams.get('target_date'))
          if (allowed) {
            const date = local.searchParams.get('target_date')
            if (activity.failNextScan && date === args.fixture.date) {
              activity.failNextScan = false
              activity.controlled503 += 1
              return send(503, JSON.stringify({ detail: {
                code: 'metric_query_unavailable', message: 'METRICSLEUTH_PRIVATE_PROXY_MARKER_8f31c6',
              } }), 'application/json; charset=utf-8')
            }
            if (activity.delayNextScan && date === args.fixture.date) {
              activity.delayNextScan = false
              delayMetricResponse = true
            }
          }
        }
        if (!allowed) return send(404, 'not_found')

        if (args.mode === 'scan' && local.pathname === '/api/investigations' &&
            local.searchParams.get('source_id') === activity.alternateSourceId) {
          activity.controlledCatalogSourceSwitch += 1
          const limit = Number(local.searchParams.get('limit') ?? 20)
          const offset = Number(local.searchParams.get('offset') ?? 0)
          return send(200, JSON.stringify({ items: [], limit, offset }), 'application/json; charset=utf-8')
        }

        let upstreamResponse
        try {
          const upstream = new URL(local.pathname + local.search, apiOrigin)
          if (local.pathname === '/api/metrics/observation') activity.metricReads += 1
          upstreamResponse = await fetch(upstream, {
            method: 'GET',
            redirect: 'error',
            headers: { accept: 'application/json' },
            signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
          })
          const body = await readLimited(upstreamResponse)
          if (local.pathname === '/api/metrics/observation' && upstreamResponse.ok) {
            const date = local.searchParams.get('target_date')
            if (date === args.fixture.date) activity.fixtureReads += 1
            else activity.missingReads += 1
            activity.metricFacts.push(metricReadFact(body))
          }
          if (args.mode === 'scan' && local.pathname === '/api/metrics/scan' && upstreamResponse.ok) {
            const date = local.searchParams.get('target_date')
            const fact = metricScanFact(body)
            activity.scanReads += 1
            if (date === args.fixture.date) activity.fixtureScans += 1
            else activity.missingScans += 1
            activity.scanFacts.push(fact)
            if (activity.conflictNextScan && date === args.fixture.date) {
              activity.conflictNextScan = false
              activity.controlledMetadataConflict += 1
              const controlled = structuredClone(fact)
              const alteredVersion = `${controlled.data_version}-controlled-conflict`
              controlled.data_version = alteredVersion
              controlled.items = controlled.items.map((item) => ({ ...item, data_version: alteredVersion }))
              return send(upstreamResponse.status, JSON.stringify(controlled), upstreamResponse.headers.get('content-type') ?? 'application/json')
            }
          }
          if (delayMetricResponse) {
            if (args.mode === 'scan' && local.pathname === '/api/metrics/scan') activity.delayedScans += 1
            else activity.delayedReads += 1
            await new Promise((done) => setTimeout(done, 1200))
          }
          if (local.pathname === '/api/metrics/observation') activity.metricResponses += 1
          if (args.mode === 'scan' && local.pathname === '/api/metrics/scan') activity.scanResponses += 1
          if (args.mode === 'scan' && local.pathname === '/api/investigation-sources' && upstreamResponse.ok) {
            let catalog
            try { catalog = JSON.parse(body.toString('utf8')) } catch { throw new Error('catalog_payload') }
            const controlled = structuredClone(catalog)
            const original = controlled?.items?.find((item) => item?.source_id === args.sourceId)
            if (original) {
              activity.alternateSourceId ??= randomUUID()
              controlled.items.push({ ...original, source_id: activity.alternateSourceId, display_name: '受控来源切换检查' })
              return send(upstreamResponse.status, JSON.stringify(controlled), upstreamResponse.headers.get('content-type') ?? 'application/json')
            }
          }
          return send(upstreamResponse.status, body, upstreamResponse.headers.get('content-type') ?? 'application/json')
        } catch {
          return send(502, 'upstream_unavailable')
        }
      }

      let pathname
      try { pathname = decodeURIComponent(local.pathname === '/' ? '/index.html' : local.pathname) } catch { return send(404, 'not_found') }
      const target = resolve(dist, `.${pathname}`)
      if (!target.startsWith(`${dist}${sep}`) && target !== dist) return send(404, 'not_found')
      const info = await stat(target).catch(() => null)
      if (!info?.isFile()) return send(404, 'not_found')
      const content = await readFile(target)
      return send(200, content, safeContentType(target))
    } catch {
      if (!response.headersSent) send(500, 'server_error')
      else response.destroy()
    }
  })
}

async function main() {
  const args = parseArguments(process.argv.slice(2))
  await stat(dist).catch(() => { throw new Error('dist_missing') })
  await mkdir(args.output, { recursive: true })
  const outputInfo = await stat(args.output).catch(() => null)
  check(outputInfo?.isDirectory(), 'output_directory')

  const profile = await mkdtemp(join(tmpdir(), 'metricsleuth-metric-browser-'))
  const profileResolved = resolve(profile)
  const tempResolved = resolve(tmpdir())
  check(profileResolved.startsWith(`${tempResolved}${sep}`), 'profile_path')
  const outputResolved = resolve(args.output)
  const browserExecutable = process.env.METRICSLEUTH_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
  const activity = {
    metricReads: 0, fixtureReads: 0, missingReads: 0, controlled503: 0,
    delayedReads: 0, metricResponses: 0, blockedWrites: 0, metricFacts: [],
    scanReads: 0, fixtureScans: 0, missingScans: 0, scanResponses: 0, delayedScans: 0,
    controlledMetadataConflict: 0, controlledCatalogSourceSwitch: 0, scanFacts: [],
  }
  const server = createReadonlyServer(args.apiOrigin, args, activity)
  let browser
  let socket
  let closeBrowser
  let serverListening = false
  let stage = 'browser_start'
  let resultSummary
  let failureCode

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
      '--disable-component-update', '--disable-sync', 'about:blank',
    ], { windowsHide: true, stdio: 'ignore' })
    let browserSpawnFailed = false
    browser.once('error', () => { browserSpawnFailed = true })
    const delay = (ms) => new Promise((done) => setTimeout(done, ms))
    async function until(operation, label) {
      const deadline = Date.now() + REQUEST_TIMEOUT_MS
      while (Date.now() < deadline) {
        if (browserSpawnFailed) throw new Error('browser_spawn')
        if (browser.exitCode !== null && browser.exitCode !== 0) throw new Error('browser_exit')
        try {
          const value = await operation()
          if (value) return value
        } catch { /* bounded startup/render wait */ }
        await delay(100)
      }
      throw new Error(label)
    }

    stage = 'browser_debug_endpoint'
    const browserEndpoint = await until(async () => {
      const contents = await readFile(join(profileResolved, 'DevToolsActivePort'), 'utf8')
      const candidate = Number(contents.split('\n')[0])
      if (!Number.isInteger(candidate) || candidate <= 0) return null
      const endpoint = `http://127.0.0.1:${candidate}`
      const versionResponse = await fetch(`${endpoint}/json/version`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) })
      if (!versionResponse.ok) return null
      const targetsResponse = await fetch(`${endpoint}/json/list`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) })
      if (!targetsResponse.ok) return null
      const targets = await targetsResponse.json()
      const page = targets.find((target) => target.type === 'page')
      return page?.webSocketDebuggerUrl ? { port: candidate, webSocketDebuggerUrl: page.webSocketDebuggerUrl } : null
    }, 'browser_debug_endpoint')
    socket = new WebSocket(browserEndpoint.webSocketDebuggerUrl)
    await new Promise((resolveOpen, rejectOpen) => {
      const timer = setTimeout(() => rejectOpen(new Error('browser_socket_timeout')), REQUEST_TIMEOUT_MS)
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
      const timer = setTimeout(() => { pending.delete(id); rejectCommand(new Error('browser_command_timeout')) }, REQUEST_TIMEOUT_MS)
      pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolveCommand(value) },
        reject: (error) => { clearTimeout(timer); rejectCommand(error) },
      })
      socket.send(JSON.stringify({ id, method, params }))
    })
    closeBrowser = () => cdp('Browser.close')
    const evaluate = async (expression) => {
      const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
      if (result.exceptionDetails) throw new Error('browser_assertion')
      return result.result.value
    }
    const click = (selector) => evaluate(`{const el=document.querySelector(${JSON.stringify(selector)}); if(!el||el.disabled) throw new Error('missing'); el.click(); true}`)
    const bodyText = () => evaluate('document.body.innerText')
    const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`)
    const valueOf = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.value ?? null`)
    const setReactValue = async (selector, value, elementType) => evaluate(`{
      const el=document.querySelector(${JSON.stringify(selector)}); const value=${JSON.stringify(value)};
      if(!el) throw new Error('missing');
      const setter=Object.getOwnPropertyDescriptor(${elementType}.prototype,'value').set;
      setter.call(el,value); el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true})); el.value===value
    }`)
    const metricQueryCount = () => activity.metricReads

    stage = 'browser_initial_load'
    await cdp('Page.navigate', { url: origin })
    await until(async () => exists(`[data-testid="source-select"] option[value="${args.sourceId}"]`), 'browser_source_catalog')
    const source = await getJson(new URL('/api/investigation-sources', origin), 'source_catalog')
    const sourceItem = source?.items?.find((item) => item?.source_id === args.sourceId)
    check(sourceItem, 'source_catalog_shape')
    check(sourceItem.provider === (args.profile === 'synthetic' ? 'synthetic' : 'olist') &&
      sourceItem.environment === args.fixture.environment, 'source_profile')
    check(await setReactValue('[data-testid="source-select"]', args.sourceId, 'HTMLSelectElement'), 'browser_source_select')
    check(await valueOf('[data-testid="source-select"]') === args.sourceId, 'browser_source_selected')

    if (args.mode === 'scan') {
      stage = 'browser_open_scan'
      await click('[data-testid="nav-metrics"]')
      await until(async () => exists('[data-testid="metric-scan-date"]'), 'browser_scan_controls')
      check((await valueOf('[data-testid="metric-scan-date"]')) === '' &&
        await evaluate('document.querySelector("[data-testid=metric-scan-submit]")?.disabled === true') && activity.scanReads === 0,
      'browser_scan_initial_empty')
      const expectedMetrics = sourceItem.metrics.filter((item) => item.supported).map((item) => item.metric_id).sort()
      check(await setReactValue('[data-testid="metric-scan-date"]', args.fixture.date, 'HTMLInputElement'), 'browser_scan_date')
      const readScan = async (date, label) => {
        stage = label
        const before = activity.scanReads
        await click('[data-testid="metric-scan-submit"]')
        await until(async () => activity.scanReads > before && exists('[data-testid="metric-scan-result"]'), `${label}_result`)
        check(activity.scanReads === before + 1, `${label}_count`)
        return activity.scanFacts.findLast((item) => item.target_date === date)
      }
      const scan = await readScan(args.fixture.date, 'browser_actual_scan')
      const expectedCount = args.profile === 'synthetic' ? 5 : 3
      const primaryMetric = args.profile === 'synthetic' ? 'sales' : 'merchandise_gmv'
      check(scan?.source_id === args.sourceId && scan.provider === sourceItem.provider && scan.environment === sourceItem.environment &&
        scan.data_version === sourceItem.data_version && scan.data_version_kind === 'label' && scan.persisted === false &&
        scan.scope === 'source_global' && scan.target_date === args.fixture.date && scan.comparison === 'previous_7_days' &&
        scan.snapshot_consistent === false, 'browser_scan_api_identity')
      check(scan.items.length === expectedCount && expectedMetrics.length === expectedCount &&
        scan.items.map((item) => item.target_metric).sort().join('|') === expectedMetrics.join('|'), 'browser_scan_api_items')
      const primary = scan.items.find((item) => item.target_metric === primaryMetric)
      check(primary?.observation?.status === args.fixture.status && primary.observation.current_value === args.fixture.current &&
        primary.observation.baseline_value === args.fixture.baseline, 'browser_scan_primary_fact')
      check(scan.items.every((item) => item.source_id === scan.source_id && item.provider === scan.provider &&
        item.environment === scan.environment && item.data_version === scan.data_version && item.data_version_kind === 'label' &&
        item.persisted === false && item.scope === 'source_global' && item.target_date === scan.target_date &&
        item.comparison === scan.comparison && typeof item.queried_at === 'string' && typeof item.query_reference === 'string'),
      'browser_scan_item_identity')
      check(scan.anomaly_candidate_metrics.length === scan.items.filter((item) => item.anomaly_candidate === true).length,
        'browser_scan_candidate_identity')
      const expectedUnknown = args.profile === 'olist' ? 3 : 0
      check(scan.anomaly_candidate_metrics.length === 0 && scan.items.filter((item) => item.anomaly_candidate === null).length === expectedUnknown,
        'browser_scan_candidate_and_unknown_counts')
      const providerLabels = { postgresql: 'PostgreSQL', shopify: 'Shopify', olist: 'Olist', synthetic: 'Synthetic' }
      const environmentLabels = { live: '真实环境', sandbox: '隔离实验环境', benchmark: '基准数据环境', validation: '验证环境' }
      check(await evaluate(`{
        const summary=document.querySelector('[data-testid="metric-scan-row"] details summary');
        if(!summary) throw new Error('missing'); summary.focus({preventScroll:true}); document.activeElement===summary
      }`), 'browser_scan_keyboard_focus')
      await cdp('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 })
      await cdp('Input.dispatchKeyEvent', { type: 'char', key: 'Enter', code: 'Enter', text: '\r', unmodifiedText: '\r', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 })
      await cdp('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 })
      check(await evaluate('document.querySelector("[data-testid=metric-scan-row] details")?.open === true'), 'browser_scan_keyboard_toggle')
      await evaluate(`document.querySelectorAll('[data-testid="metric-scan-result"] details').forEach(el=>{el.open=true})`)
      check(await evaluate(`{
        const rows=Array.from(document.querySelectorAll('[data-testid="metric-scan-row"]'));
        const providers=${JSON.stringify(providerLabels)}, environments=${JSON.stringify(environmentLabels)};
        rows.map(el=>el.getAttribute('data-metric-id')).sort().join('|')===${JSON.stringify(expectedMetrics.join('|'))} && rows.every(el=>{
          const fact=${JSON.stringify(scan.items)}.find(item=>item.target_metric===el.getAttribute('data-metric-id'));
          const text=el.innerText; const status=fact.observation?.status ?? 'insufficient_evidence';
          return el.querySelector('.metric-read-status')?.classList.contains('metric-read-'+status) && text.includes(fact.query_reference) &&
            text.includes(fact.source_id) && text.includes(providers[fact.provider]) && text.includes(environments[fact.environment]) &&
            text.includes(fact.data_version) && text.includes(fact.queried_at) && text.includes('data_version_kind=label') && text.includes('persisted=false') &&
            text.includes('snapshot_consistent=false') && text.includes(fact.observation?.source_status ?? '未返回') &&
            (fact.observation?.current_value == null || text.includes(fact.observation.current_value)) &&
            (fact.observation?.baseline_value == null || text.includes(fact.observation.baseline_value)) &&
            (fact.observation?.relative_change == null || text.includes(fact.observation.relative_change)) &&
            (fact.observation?.sample_size == null || text.includes(fact.observation.sample_size)) &&
            (fact.observation == null || [fact.observation.current_period_start, fact.observation.current_period_end,
              fact.observation.baseline_period_start, fact.observation.baseline_period_end].every(value=>text.includes(value)));
        })
      }`), 'browser_scan_rendered_identity')
      const unknownCount = scan.items.filter((item) => item.anomaly_candidate === null).length
      check(unknownCount === expectedUnknown, 'browser_scan_unknown_count')
      check(await exists('.metric-scan-summary') && await evaluate(`{
        const summary=document.querySelector('.metric-scan-summary')?.innerText ?? '';
        summary.includes('${expectedCount} 项') && summary.includes('${unknownCount} 项') &&
          summary.includes('异常候选 0 项') && summary.includes('没有异常候选不代表全部正常')
      }`), 'browser_scan_summary_matches_facts')
      stage = 'browser_scan_desktop_capture'
      await evaluate('window.scrollTo(0,0)')
      await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
      let capture = await cdp('Page.captureScreenshot', { format: 'png' })
      await writeFile(join(outputResolved, 'scan-desktop.png'), Buffer.from(capture.data, 'base64'))
      stage = 'browser_scan_mobile_capture'
      await cdp('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 1, mobile: true })
      await evaluate('window.scrollTo(0,0)')
      check(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'browser_scan_mobile_overflow')
      capture = await cdp('Page.captureScreenshot', { format: 'png' })
      await writeFile(join(outputResolved, 'scan-mobile.png'), Buffer.from(capture.data, 'base64'))
      await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
      stage = 'browser_scan_controlled_503'
      activity.failNextScan = true
      const failures = activity.controlled503
      await click('[data-testid="metric-scan-submit"]')
      await until(async () => activity.controlled503 === failures + 1 && exists('[role="alert"]'), 'browser_scan_safe_error')
      check(!(await exists('[data-testid="metric-scan-result"]')) && !(await bodyText()).includes('METRICSLEUTH_PRIVATE_PROXY_MARKER_8f31c6'),
        'browser_scan_failure_clears_safe')
      check(await evaluate('document.querySelector("[data-testid=metric-scan-submit]")?.disabled === false'), 'browser_scan_retry_enabled')
      await readScan(args.fixture.date, 'browser_scan_manual_retry')
      stage = 'browser_scan_metadata_conflict'
      activity.conflictNextScan = true
      const conflicts = activity.controlledMetadataConflict
      await click('[data-testid="metric-scan-submit"]')
      await until(async () => activity.controlledMetadataConflict === conflicts + 1 && exists('[role="alert"]'), 'browser_scan_conflict_rejected')
      check(!(await exists('[data-testid="metric-scan-result"]')), 'browser_scan_conflict_clears')
      stage = 'browser_scan_missing_date'
      await setReactValue('[data-testid="metric-scan-date"]', args.fixture.missingDate, 'HTMLInputElement')
      const missing = await readScan(args.fixture.missingDate, 'browser_scan_missing')
      check(missing?.items.length === expectedCount && missing.items.every((item) => item.anomaly_candidate === null &&
        (item.observation === null || (item.observation.status === 'insufficient_evidence' && item.observation.current_value === null &&
          item.observation.baseline_value === null && item.observation.relative_change === null))),
        'browser_scan_missing_api_null')
      check(await evaluate(`{
        const rows=Array.from(document.querySelectorAll('[data-testid="metric-scan-row"]'));
        rows.length===${expectedCount} && rows.every(el=>el.querySelector('.metric-read-status')?.classList.contains('metric-read-insufficient_evidence') &&
          Array.from(el.querySelectorAll('.numeric-value')).every(value=>value.innerText.includes('—')&&!value.innerText.includes('0')) &&
          !el.innerText.includes('0.00'))
      }`), 'browser_scan_missing_rendered_null')
      stage = 'browser_scan_handoff'
      await setReactValue('[data-testid="metric-scan-date"]', args.fixture.date, 'HTMLInputElement')
      await readScan(args.fixture.date, 'browser_scan_handoff_scan')
      await click(`[data-testid="metric-scan-handoff"][data-metric-id="${primaryMetric}"]`)
      await until(async () => exists('[data-testid="metric-select"]') && exists('[data-testid="target-date"]'), 'browser_scan_handoff_form')
      check(await valueOf('[data-testid="metric-select"]') === primaryMetric && await valueOf('[data-testid="target-date"]') === args.fixture.date &&
        activity.blockedWrites === 0, 'browser_scan_handoff_identity')
      stage = 'browser_scan_delayed_race'
      await click('[data-testid="nav-metrics"]')
      await until(async () => exists('[data-testid="metric-scan-date"]'), 'browser_scan_return')
      const readsBeforeReturn = activity.scanReads
      await new Promise((done) => setTimeout(done, 300))
      check(await valueOf('[data-testid="metric-scan-date"]') === '' && activity.scanReads === readsBeforeReturn,
        'browser_scan_return_no_auto_query')
      await setReactValue('[data-testid="metric-scan-date"]', args.fixture.date, 'HTMLInputElement')
      const delayed = activity.delayedScans, responses = activity.scanResponses
      activity.delayNextScan = true
      await click('[data-testid="metric-scan-submit"]')
      await until(async () => activity.delayedScans === delayed + 1, 'browser_scan_delay_started')
      await setReactValue('[data-testid="metric-scan-date"]', args.fixture.missingDate, 'HTMLInputElement')
      await until(async () => activity.scanResponses >= responses + 1, 'browser_scan_delay_completed')
      check(!(await exists('[data-testid="metric-scan-result"]')) && await valueOf('[data-testid="metric-scan-date"]') === args.fixture.missingDate,
        'browser_scan_delayed_result_discarded')
      stage = 'browser_scan_catalog_source_switch'
      check(typeof activity.alternateSourceId === 'string' && UUID.test(activity.alternateSourceId), 'browser_scan_alternate_source')
      const historyBefore = activity.controlledCatalogSourceSwitch
      const switchDelay = activity.delayedScans
      await setReactValue('[data-testid="metric-scan-date"]', args.fixture.date, 'HTMLInputElement')
      activity.delayNextScan = true
      await click('[data-testid="metric-scan-submit"]')
      await until(async () => activity.delayedScans === switchDelay + 1, 'browser_scan_switch_delay_started')
      await setReactValue('[data-testid="source-select"]', activity.alternateSourceId, 'HTMLSelectElement')
      await until(async () => activity.controlledCatalogSourceSwitch > historyBefore && exists('[data-testid="metric-scan-date"]'), 'browser_scan_source_switch')
      await until(async () => activity.scanResponses >= responses + 2, 'browser_scan_switch_delay_completed')
      check(!(await exists('[data-testid="metric-scan-result"]')) && await valueOf('[data-testid="metric-scan-date"]') === '' &&
        activity.blockedWrites === 0, 'browser_scan_source_switch_clears')
      stage = 'browser_scan_reload'
      const scansBeforeReload = activity.scanReads
      await cdp('Page.reload', { ignoreCache: true })
      await until(async () => exists(`[data-testid="source-select"] option[value="${args.sourceId}"]`), 'browser_scan_reload_catalog')
      await setReactValue('[data-testid="source-select"]', args.sourceId, 'HTMLSelectElement')
      await click('[data-testid="nav-metrics"]')
      await until(async () => exists('[data-testid="metric-scan-date"]'), 'browser_scan_reload_panel')
      await new Promise((done) => setTimeout(done, 300))
      check(await valueOf('[data-testid="metric-scan-date"]') === '' &&
        await evaluate('document.querySelector("[data-testid=metric-scan-submit]")?.disabled === true') && activity.scanReads === scansBeforeReload,
      'browser_scan_reload_no_auto_query')
      resultSummary = {
        status: 'PASS', evidence: 'real Edge + production build + read-only local API proxy', profile: args.profile,
        stage: 'complete', actualScanGET: activity.scanReads,
        actualScanGETMeaning: 'successful scan GET batches; not SQL statement count or Agent tool calls', controlled503: activity.controlled503,
        controlledMetadataConflict: activity.controlledMetadataConflict, delayedScans: activity.delayedScans,
        controlledCatalogSourceSwitch: activity.controlledCatalogSourceSwitch, writeBlocked: activity.blockedWrites,
        screenshots: ['scan-desktop.png', 'scan-mobile.png'],
      }
    } else {
    stage = 'browser_open_metrics'
    await click('[data-testid="nav-metrics"]')
    await until(async () => exists('[data-testid="metric-read-select"]') && exists('[data-testid="metric-read-date"]'), 'browser_metric_controls')
    check((await valueOf('[data-testid="metric-read-date"]')) === '', 'browser_date_initial_empty')
    check(await evaluate('document.querySelector("[data-testid=metric-read-submit]")?.disabled === true'), 'browser_read_initial_disabled')
    check(await setReactValue('[data-testid="metric-read-select"]', args.fixture.metric, 'HTMLSelectElement'), 'browser_metric_select')
    check(await setReactValue('[data-testid="metric-read-date"]', args.fixture.date, 'HTMLInputElement'), 'browser_metric_date')
    check(await evaluate('document.querySelector("[data-testid=metric-read-submit]")?.disabled === false'), 'browser_read_enabled')

    stage = 'browser_metric_read'
    const beforeFixtureRead = activity.fixtureReads
    await click('[data-testid="metric-read-submit"]')
    await until(async () => activity.fixtureReads > 0 && exists('[data-testid="metric-read-result"]'), 'browser_metric_result')
    check(activity.fixtureReads === beforeFixtureRead + 1, 'browser_metric_read_count')
    const baselineStart = new Date(Date.parse(`${args.fixture.date}T00:00:00.000Z`) - 7 * 86_400_000).toISOString().slice(0, 10)
    const baselineEnd = new Date(Date.parse(`${args.fixture.date}T00:00:00.000Z`) - 86_400_000).toISOString().slice(0, 10)
    const facts = activity.metricFacts.find((item) => item.target_date === args.fixture.date)
    check(facts?.target_metric === args.fixture.metric && facts.observation?.status === args.fixture.status, 'browser_metric_api_status')
    check(facts.observation.current_value === args.fixture.current && facts.observation.baseline_value === args.fixture.baseline, 'browser_metric_api_values')
    check(facts.observation.current_period_start === args.fixture.date && facts.observation.current_period_end === args.fixture.date &&
      facts.observation.baseline_period_start === baselineStart && facts.observation.baseline_period_end === baselineEnd, 'browser_metric_api_periods')
    check(typeof facts.query_reference === 'string' && /^metric-read:[0-9a-f-]{36}$/i.test(facts.query_reference), 'browser_metric_api_reference')
    check(typeof facts.observation.source_status === 'string' && facts.observation.source_status.length > 0, 'browser_metric_api_source_status')
    check(await evaluate(`{const el=document.querySelector('[data-testid="metric-read-result"] .metric-read-status'); el?.classList.contains(${JSON.stringify(`metric-read-${args.fixture.status}`)}) ?? false}`), 'browser_metric_rendered_status')
    await evaluate(`document.querySelectorAll('[data-testid="metric-read-result"] details').forEach(el=>{el.open=true})`)
    const expandedResultText = await bodyText()
    for (const expected of [args.fixture.current, args.fixture.baseline, args.fixture.date,
      baselineStart, baselineEnd, facts.query_reference, facts.observation.source_status]) {
      check(expandedResultText.includes(expected), 'browser_metric_rendered_fact')
    }
    check(expandedResultText.includes('来源状态原值：'), 'browser_metric_source_status')

    stage = 'browser_desktop_capture'
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
    let capture = await cdp('Page.captureScreenshot', { format: 'png' })
    await writeFile(join(outputResolved, 'metrics-desktop.png'), Buffer.from(capture.data, 'base64'))
    stage = 'browser_mobile_capture'
    await cdp('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 1, mobile: true })
    check(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'browser_mobile_overflow')
    capture = await cdp('Page.captureScreenshot', { format: 'png' })
    await writeFile(join(outputResolved, 'metrics-mobile.png'), Buffer.from(capture.data, 'base64'))
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

    stage = 'browser_controlled_503'
    activity.failNextMetric = true
    const controlledBase = activity.controlled503
    const sqlBaseBeforeFailure = activity.metricReads
    await click('[data-testid="metric-read-submit"]')
    await until(async () => activity.controlled503 === controlledBase + 1 && exists('[role="alert"]'), 'browser_controlled_error')
    const safeErrorText = await bodyText()
    check(safeErrorText.includes('暂时无法读取该指标'), 'browser_controlled_safe_error')
    check(!safeErrorText.includes('METRICSLEUTH_PRIVATE_PROXY_MARKER_8f31c6'), 'browser_controlled_marker_redacted')
    check(!(await exists('[data-testid="metric-read-result"]')), 'browser_controlled_old_result_cleared')
    check(activity.metricReads === sqlBaseBeforeFailure, 'browser_controlled_no_sql')

    stage = 'browser_manual_retry'
    check(await evaluate('document.querySelector("[data-testid=metric-read-submit]")?.disabled === false'), 'browser_manual_retry_enabled')
    const retryReadBase = activity.fixtureReads
    const retrySqlBase = activity.metricReads
    await click('[data-testid="metric-read-submit"]')
    await until(async () => activity.fixtureReads === retryReadBase + 1 && exists('[data-testid="metric-read-result"]'), 'browser_manual_retry_result')
    check(activity.metricReads === retrySqlBase + 1, 'browser_manual_retry_sql')
    const retryFacts = activity.metricFacts.find((item) => item.target_date === args.fixture.date &&
      item.query_reference !== facts.query_reference)
    check(retryFacts?.observation?.current_value === args.fixture.current, 'browser_manual_retry_value')

    stage = 'browser_handoff'
    await click('[data-testid="metric-read-handoff"]')
    await until(async () => exists('[data-testid="metric-select"]') && exists('[data-testid="target-date"]'), 'browser_handoff_form')
    check(await valueOf('[data-testid="metric-select"]') === args.fixture.metric, 'browser_handoff_metric')
    check(await valueOf('[data-testid="target-date"]') === args.fixture.date, 'browser_handoff_date')
    check(activity.blockedWrites === 0, 'browser_handoff_write')

    stage = 'browser_return_metrics'
    const readsBeforeReturn = metricQueryCount()
    await click('[data-testid="nav-metrics"]')
    await until(async () => exists('[data-testid="metric-read-select"]'), 'browser_metric_return')
    await new Promise((done) => setTimeout(done, 300))
    check(metricQueryCount() === readsBeforeReturn, 'browser_metric_no_auto_query')
    check((await valueOf('[data-testid="metric-read-date"]')) === '', 'browser_metric_return_date_empty')
    check(await evaluate('document.querySelector("[data-testid=metric-read-submit]")?.disabled === true'), 'browser_metric_return_disabled')
    check(await setReactValue('[data-testid="metric-read-select"]', args.fixture.metric, 'HTMLSelectElement'), 'browser_missing_metric_select')
    check(await setReactValue('[data-testid="metric-read-date"]', args.fixture.date, 'HTMLInputElement'), 'browser_delayed_date')

    stage = 'browser_delayed_request_race'
    const delayBase = activity.delayedReads
    const responseBase = activity.metricResponses
    const sqlBaseBeforeDelay = activity.metricReads
    activity.delayNextFixture = true
    await click('[data-testid="metric-read-submit"]')
    await until(async () => activity.delayedReads === delayBase + 1, 'browser_delayed_request_started')
    check(await setReactValue('[data-testid="metric-read-date"]', args.fixture.missingDate, 'HTMLInputElement'), 'browser_delayed_change_date')
    await until(async () => activity.metricResponses >= responseBase + 1, 'browser_delayed_query_completed')
    check(activity.metricReads === sqlBaseBeforeDelay + 1, 'browser_delayed_real_sql')
    check((await valueOf('[data-testid="metric-read-date"]')) === args.fixture.missingDate, 'browser_delayed_keeps_new_date')
    check(!(await exists('[data-testid="metric-read-result"]')), 'browser_delayed_result_not_stale')

    stage = 'browser_missing_read'
    check(await evaluate('document.querySelector("[data-testid=metric-read-submit]")?.disabled === false'), 'browser_missing_read_enabled')
    const beforeMissingRead = activity.missingReads
    await click('[data-testid="metric-read-submit"]')
    await until(async () => activity.missingReads === beforeMissingRead + 1 && exists('[data-testid="metric-read-result"]'), 'browser_missing_result')
    const missingFacts = activity.metricFacts.find((item) => item.target_date === args.fixture.missingDate)
    check(missingFacts?.target_metric === args.fixture.metric && missingFacts.anomaly_candidate === null, 'browser_missing_api_status')
    check(missingFacts.observation === null || (missingFacts.observation.status === 'insufficient_evidence' &&
      missingFacts.observation.current_value === null && missingFacts.observation.baseline_value === null), 'browser_missing_api_values')
    check(await evaluate(`{const el=document.querySelector('[data-testid="metric-read-result"] .metric-read-status'); el?.classList.contains(${JSON.stringify(missingFacts.observation === null ? 'metric-read-insufficient' : 'metric-read-insufficient_evidence')}) ?? false}`), 'browser_missing_status')
    if (missingFacts.observation !== null) {
      await evaluate(`document.querySelectorAll('[data-testid="metric-read-result"] details').forEach(el=>{el.open=true})`)
      const missingResult = await bodyText()
      check(missingResult.includes('—'), 'browser_missing_rendered_null')
      check(!missingResult.includes('0.00'), 'browser_missing_not_zero')
      check(await evaluate(`{const values=Array.from(document.querySelectorAll('[data-testid="metric-read-result"] .metric-read-values .numeric-value')); values.length>=2 && values.slice(0,2).every(el=>el.textContent.includes('—')&&!el.textContent.includes('0'))}`), 'browser_missing_numeric_null')
    } else {
      check(await bodyText().then((value) => value.includes('不能将缺失数据视为 0 或正常')), 'browser_missing_null_copy')
    }
    check(activity.fixtureReads >= 2 && activity.missingReads === 1 && activity.controlled503 === 1, 'browser_expected_read_count')

    stage = 'browser_reload'
    const readsBeforeReload = metricQueryCount()
    await cdp('Page.reload', { ignoreCache: true })
    await until(async () => exists(`[data-testid="source-select"] option[value="${args.sourceId}"]`), 'browser_reload_catalog')
    await setReactValue('[data-testid="source-select"]', args.sourceId, 'HTMLSelectElement')
    await click('[data-testid="nav-metrics"]')
    await until(async () => exists('[data-testid="metric-read-date"]'), 'browser_reload_metrics')
    await new Promise((done) => setTimeout(done, 300))
    check((await valueOf('[data-testid="metric-read-date"]')) === '', 'browser_reload_date_empty')
    check(await evaluate('document.querySelector("[data-testid=metric-read-submit]")?.disabled === true'), 'browser_reload_read_disabled')
    check(metricQueryCount() === readsBeforeReload, 'browser_reload_no_auto_query')
    check(activity.blockedWrites === 0, 'browser_blocked_write_attempt')

    resultSummary = {
      status: 'PASS',
      evidence: 'real Edge + production build + read-only local API proxy',
      profile: args.profile,
      stage: 'complete',
      metricGET: activity.metricReads,
      controlled503: activity.controlled503,
      delayedReads: activity.delayedReads,
      writeBlocked: activity.blockedWrites,
      screenshots: ['metrics-desktop.png', 'metrics-mobile.png'],
    }
    }
  } catch (error) {
    const safeStage = typeof error?.message === 'string' && /^[a-z0-9_]+$/.test(error.message) ? error.message : stage
    failureCode = safeStage
  } finally {
    let cleanupFailed = false
    let browserClosed = !browser
    if (closeBrowser) {
      try {
        await closeBrowser()
        browserClosed = true
      } catch {
        cleanupFailed = true
      }
    } else if (browser) {
      cleanupFailed = true
    }
    if (browser && browser.exitCode === null) {
      browser.kill()
      const exited = await Promise.race([
        new Promise((done) => browser.once('exit', () => done(true))),
        new Promise((done) => setTimeout(() => done(false), 3000)),
      ])
      if (!exited) cleanupFailed = true
    }
    socket?.close()
    if (serverListening) {
      try { await new Promise((done, reject) => server.close((error) => error ? reject(error) : done())) } catch { cleanupFailed = true }
    }
    if (browserClosed && profileResolved.startsWith(`${tempResolved}${sep}`)) {
      try {
        await rm(profileResolved, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
        if (await stat(profileResolved).then(() => true, () => false)) cleanupFailed = true
      } catch {
        cleanupFailed = true
      }
    } else if (browser) {
      cleanupFailed = true
    }
    if (cleanupFailed) {
      resultSummary = undefined
      failureCode = 'cleanup_failed'
    }
    if (failureCode) {
      process.exitCode = 1
      console.error(`FAIL ${failureCode}`)
    } else if (resultSummary) console.log(JSON.stringify(resultSummary))
  }
}

main().catch((error) => {
  const code = typeof error?.message === 'string' && /^[a-z0-9_]+$/.test(error.message) ? error.message : 'setup_failed'
  console.error(`FAIL ${code}`)
  process.exitCode = 1
})
