// Read-only real API/browser acceptance for an existing failure or Synthetic success.
// Usage: node scripts/verify-postgres-workspace.mjs --api http://127.0.0.1:8001 --source UUID --run UUID --output C:/absolute/evidence
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { extname, join, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const dist = resolve(frontend, 'dist')
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const MAX_PROXY_BYTES = 5 * 1024 * 1024
const REQUEST_TIMEOUT_MS = 10_000

function parseArguments(argv) {
  const values = Object.create(null)
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index]
    if (!['--api', '--source', '--run', '--output', '--expect'].includes(name) || values[name]) throw new Error('arguments')
    const value = argv[index + 1]
    if (!value || value.startsWith('--')) throw new Error('arguments')
    values[name] = value
    index += 1
  }
  if (!['--api', '--source', '--run', '--output'].every(key => values[key])) throw new Error('arguments')
  const expectedStatus = values['--expect'] ?? 'failed'
  if (!['failed', 'succeeded'].includes(expectedStatus)) throw new Error('arguments')

  const api = new URL(values['--api'])
  const host = api.hostname.toLowerCase()
  const loopback = host === 'localhost' || host === '::1' || host === '[::1]' ||
    /^127(?:\.\d{1,3}){3}$/.test(host)
  if (api.protocol !== 'http:' || !loopback || api.username || api.password || api.search || api.hash ||
      (api.pathname !== '/' && api.pathname !== '')) throw new Error('api_url')
  if (!UUID.test(values['--source']) || !UUID.test(values['--run'])) throw new Error('identifier')
  const output = resolve(values['--output'])
  if (!/^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(values['--output'])) throw new Error('output_path')
  return { apiOrigin: api.origin, sourceId: values['--source'], runId: values['--run'], output, expectedStatus }
}

function check(condition, label) {
  if (!condition) throw new Error(label)
}

async function getJson(url, stage) {
  let response
  try {
    response = await fetch(url, { method: 'GET', redirect: 'error', headers: { accept: 'application/json' }, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) })
  } catch {
    throw new Error(stage)
  }
  if (!response.ok) throw new Error(stage)
  try {
    return await response.json()
  } catch {
    throw new Error(stage)
  }
}

function sourceIn(catalog, sourceId) {
  return catalog?.items?.find((item) => item?.source_id === sourceId)
}

async function findRun(apiOrigin, sourceId, runId, stagePrefix) {
  for (let page = 0; page < 10; page += 1) {
    const offset = page * 20
    const url = new URL('/api/investigations', apiOrigin)
    url.searchParams.set('source_id', sourceId)
    url.searchParams.set('limit', '20')
    url.searchParams.set('offset', String(offset))
    const result = await getJson(url, `${stagePrefix}_list`)
    check(Array.isArray(result?.items) && result.limit === 20 && result.offset === offset, `${stagePrefix}_list_shape`)
    const match = result.items.find((item) => item?.investigation_run_id === runId)
    if (match) return { run: match, page }
    if (result.items.length < 20) break
  }
  throw new Error(`${stagePrefix}_run_missing`)
}

function assertDetail(detail, source, runId, sourceId, listedRun, stage, expectedStatus) {
  check(detail?.run?.investigation_run_id === runId, `${stage}_run_identity`)
  check(detail.run.source_id === sourceId && listedRun.source_id === sourceId, `${stage}_source_identity`)
  check(detail.run.provider === source.provider && detail.run.environment === source.environment &&
    listedRun.provider === source.provider && listedRun.environment === source.environment, `${stage}_source_metadata`)
  check(detail.run.status === expectedStatus && listedRun.status === expectedStatus, `${stage}_status`)
  check(Array.isArray(detail.tool_calls) && detail.tool_calls.length >= 1, `${stage}_tool_calls`)
  check(Array.isArray(detail.observations) && detail.observations.length >= 1, `${stage}_observations`)
  check(Array.isArray(detail.evidence) && Array.isArray(detail.diagnoses), `${stage}_facts`)
  if (expectedStatus === 'failed') {
    check(detail.evidence.length === 0 && detail.diagnoses.length === 0, `${stage}_failed_no_diagnosis`)
  } else {
    check(detail.evidence.length > 0 && detail.diagnoses.length === 1, `${stage}_success_facts`)
    const diagnosis = detail.diagnoses[0]
    check(diagnosis.status === 'diagnosed' && diagnosis.primary_driver === 'conversion_rate' &&
      diagnosis.affected_scope?.marketplace === 'US', `${stage}_driver_scope`)
    check(diagnosis.evidence_ids.length > 0 && diagnosis.evidence_ids.every(id =>
      detail.evidence.some(evidence => evidence.evidence_id === id)), `${stage}_diagnosis_links`)
    check(detail.evidence.every(evidence => detail.observations.some(observation =>
      observation.observation_id === evidence.observation_id && observation.tool_call_id === evidence.tool_call_id &&
      detail.tool_calls.some(tool => tool.tool_call_id === observation.tool_call_id))), `${stage}_evidence_links`)
    check(detail.evidence.some(evidence => diagnosis.evidence_ids.includes(evidence.evidence_id) && evidence.role === 'supporting' &&
      detail.observations.some(observation => observation.observation_id === evidence.observation_id &&
        observation.metric === diagnosis.primary_driver && observation.status === 'anomalous' &&
        observation.dimensions?.marketplace === 'US')), `${stage}_joint_support`)
  }
  const observation = detail.observations[0]
  const toolCall = detail.tool_calls.find((item) => item.tool_call_id === observation.tool_call_id)
  const queryReference = observation.query_reference
  check(toolCall?.tool_call_id === observation.tool_call_id, `${stage}_trace_link`)
  check(typeof observation.observation_id === 'string' && observation.observation_id.length > 0, `${stage}_observation_id`)
  check(typeof observation.tool_call_id === 'string' && observation.tool_call_id.length > 0, `${stage}_tool_id`)
  check(typeof queryReference === 'string' && queryReference.length > 0, `${stage}_query_reference`)
  check(observation.current_value !== null && observation.current_value !== undefined, `${stage}_current_value`)
  check(observation.baseline_value !== null && observation.baseline_value !== undefined, `${stage}_baseline_value`)
  check(listedRun.tool_call_count === detail.tool_calls.length && listedRun.observation_count === detail.observations.length &&
    listedRun.evidence_count === detail.evidence.length && listedRun.diagnosis_count === detail.diagnoses.length, `${stage}_persisted_counts`)
  return {
    observationId: observation.observation_id,
    toolCallId: observation.tool_call_id,
    queryReference,
    currentValue: String(observation.current_value),
    baselineValue: String(observation.baseline_value),
    toolCount: detail.tool_calls.length,
    observationCount: detail.observations.length,
  }
}

function safeContentType(path) {
  return ({ '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8', '.svg': 'image/svg+xml' })[extname(path)] ?? 'application/octet-stream'
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

function createReadonlyServer(apiOrigin, sourceId, runId, activity) {
  return createServer(async (request, response) => {
    const send = (status, body, contentType = 'text/plain; charset=utf-8') => {
      response.writeHead(status, { 'content-type': contentType, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' })
      response.end(body)
    }
    try {
      const local = new URL(request.url, 'http://127.0.0.1')
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) activity.blockedWrites += 1
      if (local.pathname.startsWith('/api/')) {
        if (request.method !== 'GET') return send(405, 'method_not_allowed')
        let allowed = false
        if (local.pathname === '/api/investigation-sources') {
          allowed = local.search === ''
        } else if (local.pathname === '/api/investigations') {
          allowed = [...local.searchParams.keys()].every((key) => ['source_id', 'limit', 'offset'].includes(key)) &&
            local.searchParams.get('source_id') === sourceId
        } else {
          const detailMatch = local.pathname.match(/^\/api\/investigations\/([0-9a-f-]+)$/i)
          allowed = Boolean(detailMatch && UUID.test(detailMatch[1]) && detailMatch[1] === runId &&
            [...local.searchParams.keys()].every((key) => key === 'source_id') && local.searchParams.get('source_id') === sourceId)
        }
        if (!allowed) return send(404, 'not_found')
        const upstream = new URL(local.pathname + local.search, apiOrigin)
        let upstreamResponse
        try {
          upstreamResponse = await fetch(upstream, { method: 'GET', redirect: 'error', headers: { accept: 'application/json' }, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) })
          const body = await readLimited(upstreamResponse)
          if (local.pathname === '/api/investigations') activity.targetListReads += 1
          return send(upstreamResponse.status, body, upstreamResponse.headers.get('content-type') ?? 'application/json')
        } catch {
          return send(502, 'upstream_unavailable')
        }
      }
      if (request.method !== 'GET' && request.method !== 'HEAD') return send(405, 'method_not_allowed')
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
  const args = parseArguments(process.argv.slice(2))
  await stat(dist).catch(() => { throw new Error('dist_missing') })
  await mkdir(args.output, { recursive: true })
  const outputInfo = await stat(args.output).catch(() => null)
  check(outputInfo?.isDirectory(), 'output_directory')

  const catalog = await getJson(new URL('/api/investigation-sources', args.apiOrigin), 'preflight_source_catalog')
  const source = sourceIn(catalog, args.sourceId)
  check(source && ((source.provider === 'synthetic' && source.environment === 'sandbox') ||
    (source.provider === 'olist' && source.environment === 'validation')), 'preflight_source')
  const listed = await findRun(args.apiOrigin, args.sourceId, args.runId, 'preflight')
  const detail = await getJson(new URL(`/api/investigations/${encodeURIComponent(args.runId)}?source_id=${encodeURIComponent(args.sourceId)}`, args.apiOrigin), 'preflight_detail')
  const facts = assertDetail(detail, source, args.runId, args.sourceId, listed.run, 'preflight', args.expectedStatus)

  const profile = await mkdtemp(join(tmpdir(), 'metricsleuth-postgres-browser-profile-'))
  const profileResolved = resolve(profile)
  const tempResolved = resolve(tmpdir())
  check(profileResolved.startsWith(`${tempResolved}${sep}`), 'profile_path')
  const outputResolved = resolve(args.output)
  const browserExecutable = process.env.METRICSLEUTH_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
  const activity = { targetListReads: 0, blockedWrites: 0 }
  const server = createReadonlyServer(args.apiOrigin, args.sourceId, args.runId, activity)
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
    browser = spawn(browserExecutable, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profileResolved}`,
      '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', 'about:blank'],
    { windowsHide: true, stdio: 'ignore' })
    let browserSpawnFailed = false
    browser.once('error', () => { browserSpawnFailed = true })
    const delay = (ms) => new Promise((done) => setTimeout(done, ms))
    async function until(operation, label) {
      const deadline = Date.now() + REQUEST_TIMEOUT_MS
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
    const targetsResponse = await fetch(`http://127.0.0.1:${debugPort}/json/list`, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) })
    const targets = await targetsResponse.json()
    const page = targets.find((target) => target.type === 'page')
    check(page?.webSocketDebuggerUrl, 'browser_page')
    socket = new WebSocket(page.webSocketDebuggerUrl)
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
    const evaluate = async (expression) => {
      const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
      if (result.exceptionDetails) throw new Error('browser_assertion')
      return result.result.value
    }
    const click = (selector) => evaluate(`{const el=Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(item=>item.getClientRects().length); if(!el) throw new Error('missing'); el.click(); true}`)
    const bodyText = () => evaluate('document.body.innerText')

    stage = 'browser_initial_load'
    await cdp('Page.navigate', { url: origin })
    await until(async () => evaluate(`!!document.querySelector('[data-testid="source-select"] option[value="${args.sourceId}"]')`), 'browser_catalog')
    const chosenSource = await evaluate(`{const select=document.querySelector('[data-testid="source-select"]'); const id=${JSON.stringify(args.sourceId)}; const option=Array.from(select.options).find(item=>item.value===id); if(!option) throw new Error('missing source'); const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set; setter.call(select,id); select.dispatchEvent(new Event('change',{bubbles:true})); select.value===id}`)
    check(chosenSource, 'browser_source_select')
    await click('[data-testid="nav-investigation"]')

    async function openTargetAndCheck(checkStage, minimumListReads) {
      stage = `${checkStage}_history_load`
      await until(async () => activity.targetListReads >= minimumListReads && !(await bodyText()).includes('正在读取已保存的调查…'), 'browser_history_load')
      for (let pageNumber = 0; pageNumber < 10; pageNumber += 1) {
        stage = `${checkStage}_history_page`
        await until(async () => !(await bodyText()).includes('正在读取已保存的调查…'), 'browser_history')
        const exists = await evaluate(`!!document.querySelector('[data-testid="history-run"][data-run-id="${args.runId}"]')`)
        if (exists) {
          stage = `${checkStage}_open_run`
          await click(`[data-testid="history-run"][data-run-id="${args.runId}"]`)
          await until(async () => (await bodyText()).includes(facts.observationId), 'browser_detail')
          const rendered = await bodyText()
          for (const expected of [args.runId, source.provider, source.environment, facts.observationId, facts.toolCallId,
            facts.queryReference, facts.currentValue, facts.baselineValue,
            ...(args.expectedStatus === 'succeeded' ? ['已定位主要变化', 'conversion_rate', ...detail.diagnoses[0].evidence_ids] : ['本次任务失败，未保存诊断结论。'])]) {
            check(rendered.includes(expected), `${checkStage}_rendered_fact`)
          }
          check(!rendered.includes('预设') && !rendered.includes('fixture-'), `${checkStage}_fixture_copy`)
          return true
        }
        const firstId = await evaluate(`document.querySelector('[data-testid="history-run"]')?.dataset.runId ?? ''`)
        const hasNext = await evaluate(`Array.from(document.querySelectorAll('button')).some(button=>button.textContent.includes('下一页') && !button.disabled)`)
        if (!hasNext) return false
        stage = `${checkStage}_pagination`
        await evaluate(`{const button=Array.from(document.querySelectorAll('button')).find(item=>item.textContent.includes('下一页') && !item.disabled); button.click(); true}`)
        await until(async () => (await evaluate(`document.querySelector('[data-testid="history-run"]')?.dataset.runId ?? ''`)) !== firstId, 'browser_next_page')
      }
      return false
    }

    check(await openTargetAndCheck('browser_first', 1), 'browser_run_not_found')
    stage = 'browser_desktop_capture'
    await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
    let capture = await cdp('Page.captureScreenshot', { format: 'png' })
    await writeFile(join(outputResolved, 'postgres-workspace-desktop.png'), Buffer.from(capture.data, 'base64'))
    if (args.expectedStatus === 'succeeded') {
      stage = 'browser_diagnosis_capture'
      await evaluate("document.querySelector('.diagnosis-card').scrollIntoView({block:'center'}); true")
      capture = await cdp('Page.captureScreenshot', { format: 'png' })
      await writeFile(join(outputResolved, 'postgres-workspace-diagnosis.png'), Buffer.from(capture.data, 'base64'))
    }

    stage = 'browser_reload'
    const readsBeforeReload = activity.targetListReads
    await cdp('Page.reload', { ignoreCache: true })
    await until(async () => evaluate(`!!document.querySelector('[data-testid="source-select"] option[value="${args.sourceId}"]')`), 'browser_reload_catalog')
    const selectedAfterReload = await evaluate(`{const select=document.querySelector('[data-testid="source-select"]'); const id=${JSON.stringify(args.sourceId)}; if(select.value!==id){const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set; setter.call(select,id); select.dispatchEvent(new Event('change',{bubbles:true}));} select.value===id}`)
    check(selectedAfterReload, 'browser_reload_source')
    await click('[data-testid="nav-investigation"]')
    check(await openTargetAndCheck('browser_after_reload', readsBeforeReload + 1), 'browser_reload_run_not_found')
    check(activity.blockedWrites === 0, 'browser_blocked_write_attempt')

    await cdp('Browser.close').catch(() => {})
    console.log(JSON.stringify({
      status: 'PASS',
      evidence: 'real Edge + production build + read-only local API proxy',
      run: `${args.runId.slice(0, 8)}…`,
      provider: source.provider,
      environment: source.environment,
      tool_calls: facts.toolCount,
      observations: facts.observationCount,
      evidence_count: detail.evidence.length,
      diagnosis_count: detail.diagnoses.length,
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
