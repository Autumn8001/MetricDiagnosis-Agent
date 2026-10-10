// Browser integration with controlled HTTP fixtures, NOT a model/database acceptance.
// Usage: node scripts/verify-task-workspace.mjs [absolute-output-directory]
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const profile = await mkdtemp(join(tmpdir(), 'metricsleuth-browser-profile-'))
const output = process.argv[2] ? resolve(process.argv[2]) : await mkdtemp(join(tmpdir(), 'metricsleuth-browser-evidence-'))
await mkdir(output, { recursive: true })
const stamp = '2026-10-10T08:00:00Z'
const source = (id, provider, metric) => ({ source_id: id, display_name: `${provider} controlled fixture`, provider,
  environment: provider === 'olist' ? 'validation' : 'sandbox', data_version: 'fixture-label-not-snapshot',
  metrics: [{ metric_id: metric, supported: true, grain: ['date'], dimensions: [], unavailable_reason: null }] })
const sources = [source('synthetic-fixture', 'synthetic', 'sales'), source('olist-fixture', 'olist', 'orders')]
const run = (id, status = 'failed', sourceId = sources[0].source_id) => ({ investigation_run_id: id, source_id: sourceId,
  provider: sourceId === sources[0].source_id ? 'synthetic' : 'olist', environment: sourceId === sources[0].source_id ? 'sandbox' : 'validation',
  status, requested_metric: sourceId === sources[0].source_id ? 'sales' : 'orders', requested_at: stamp, started_at: stamp,
  finished_at: ['failed', 'succeeded'].includes(status) ? stamp : null, data_version: 'fixture-label-not-snapshot',
  query_reference: 'fixture-query', failure_code: status === 'failed' ? 'execution_failed' : null,
  tool_call_count: status === 'queued' ? 0 : 1, observation_count: status === 'queued' ? 0 : 1, evidence_count: 0, diagnosis_count: 0 })
const observation = { observation_id: 'fixture-observation', tool_call_id: 'fixture-tool', metric: 'sales', status: 'success',
  source_status: 'available', current_period_start: '2026-10-10', current_period_end: '2026-10-10',
  baseline_period_start: '2026-10-03', baseline_period_end: '2026-10-09', filters: {}, group_by: [], dimensions: {},
  current_value: '80', baseline_value: '100', relative_change: '-0.2', unit: 'USD', sample_size: '8',
  query_reference: 'fixture-query', data_version: 'fixture-label-not-snapshot', error_code: null, created_at: stamp }
const detail = (currentRun) => ({ run: currentRun, tool_calls: currentRun.tool_call_count ? [{
  tool_call_id: 'fixture-tool', tool_name: 'query_metric', status: 'succeeded', arguments: { metric: 'sales' },
  data_version: currentRun.data_version, query_reference: 'fixture-query', result_reference: 'fixture-result', requested_at: stamp,
}] : [], observations: currentRun.observation_count ? [observation] : [], evidence: [], diagnoses: [] })
function successfulDetail() {
  const value = detail(run('historical-success', 'succeeded'))
  value.run.evidence_count = 1
  value.run.diagnosis_count = 1
  value.observations = [{ ...observation, status: 'normal', current_value: '100', relative_change: '0' }]
  value.evidence = [{ evidence_id: 'fixture-evidence', observation_id: observation.observation_id,
    tool_call_id: observation.tool_call_id, role: 'supporting', data_version: value.run.data_version,
    query_reference: 'fixture-query', created_at: stamp }]
  value.diagnoses = [{ diagnosis_id: 'fixture-diagnosis', status: 'no_material_anomaly', target_metric: 'sales',
    primary_driver: null, affected_scope: {}, change: null, evidence_ids: ['fixture-evidence'], confidence: null,
    limitations: ['Controlled browser fixture, not an actual model result'], data_version: value.run.data_version,
    query_reference: 'fixture-query', created_at: stamp }]
  return value
}
let catalogUnavailable = false
let detailReads = 0
let submitted = null
let postCount = 0
const requests = []
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost')
  requests.push(`${req.method} ${url.pathname}`)
  const json = (data, status = 200) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)) }
  try {
    if (url.pathname === '/_approved-prototype') {
      const prototype = await readFile(resolve(frontend, '..', 'MetricSleuth_%E4%BA%A4%E4%BA%92%E4%BA%A7%E5%93%81%E5%8E%9F%E5%9E%8B.html'))
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); res.end(prototype); return
    }
    if (url.pathname === '/api/investigation-sources') {
      return json(catalogUnavailable ? { detail: { code: 'task_service_unavailable', private: 'must-not-render' } } : { items: sources }, catalogUnavailable ? 503 : 200)
    }
    if (url.pathname === '/api/investigations' && req.method === 'POST') {
      const chunks = []
      for await (const chunk of req) chunks.push(chunk)
      submitted = JSON.parse(Buffer.concat(chunks).toString())
      postCount++
      assert.equal(submitted.source_id, sources[0].source_id)
      assert.equal(submitted.target_date, '2026-10-10')
      assert.deepEqual(submitted.filters, {})
      return json(run('submitted-fixture', 'queued'), 202)
    }
    if (url.pathname === '/api/investigations') {
      const sourceId = url.searchParams.get('source_id')
      const items = sourceId === sources[0].source_id ? [
        ...(postCount ? [run('submitted-fixture', detailReads >= 2 ? 'failed' : detailReads ? 'running' : 'queued')] : []),
        run('historical-failure'),
        successfulDetail().run,
      ] : []
      const limit = Number(url.searchParams.get('limit'))
      const offset = Number(url.searchParams.get('offset'))
      const paged = sourceId === sources[0].source_id
        ? [...items, ...Array.from({ length: 20 }, (_, index) => run(`page-fixture-${index}`))].slice(offset, offset + limit)
        : items
      return json({ items: paged, limit, offset })
    }
    if (url.pathname.startsWith('/api/investigations/')) {
      const id = decodeURIComponent(url.pathname.split('/').at(-1))
      if (id === 'historical-success') return json(successfulDetail())
      return json(detail(run(id, id === 'submitted-fixture' && ++detailReads === 1 ? 'running' : 'failed')))
    }
    if (url.pathname.startsWith('/api/')) return json({ detail: { code: 'unexpected_legacy_call' } }, 404)
    const relative = decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname)
    const target = resolve(frontend, 'dist', `.${relative}`)
    assert.ok(target.startsWith(resolve(frontend, 'dist') + (process.platform === 'win32' ? '\\' : '/')))
    const content = await readFile(target)
    res.writeHead(200, { 'content-type': ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml' })[extname(target)] || 'application/octet-stream' })
    res.end(content)
  } catch { res.writeHead(500); res.end('controlled_fixture_error') }
})
await new Promise((done) => server.listen(0, '127.0.0.1', done))
const origin = `http://127.0.0.1:${server.address().port}`
const executable = process.env.METRICSLEUTH_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const browser = spawn(executable, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', 'about:blank'],
{ windowsHide: true, stdio: 'ignore' })
let socket
const delay = (ms) => new Promise((done) => setTimeout(done, ms))
async function until(operation, label, timeout = 10000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    try { const value = await operation(); if (value) return value } catch { /* bounded startup/render wait */ }
    await delay(100)
  }
  throw new Error(`Timed out: ${label}`)
}
try {
  const port = await until(async () => Number((await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]), 'isolated browser startup')
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
  const page = targets.find((target) => target.type === 'page')
  assert.ok(page)
  socket = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((done, reject) => { socket.onopen = done; socket.onerror = reject })
  let counter = 0
  const pending = new Map()
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data)
    const handler = pending.get(message.id)
    if (handler) {
      pending.delete(message.id)
      if (message.error) handler.reject(new Error('CDP command failed'))
      else handler.resolve(message.result)
    }
  }
  const cdp = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++counter
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)) }, 10000)
    pending.set(id, { resolve: (value) => { clearTimeout(timeout); resolve(value) }, reject: (error) => { clearTimeout(timeout); reject(error) } })
    socket.send(JSON.stringify({ id, method, params }))
  })
  const evaluate = async (expression) => {
    const result = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error('Browser assertion expression failed')
    return result.result.value
  }
  const click = (testId) => evaluate(`Array.from(document.querySelectorAll('[data-testid="${testId}"]')).find(el=>el.getClientRects().length).click()`)
  const text = () => evaluate('document.body.innerText')
  const screenshot = async (name, width, height) => {
    await cdp('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 600 })
    await delay(150)
    assert.equal(await evaluate('document.documentElement.scrollWidth > window.innerWidth'), false, `${name}: horizontal overflow`)
    const capture = await cdp('Page.captureScreenshot', { format: 'png' })
    await writeFile(join(output, `${name}.png`), Buffer.from(capture.data, 'base64'))
  }
  await cdp('Page.navigate', { url: `${origin}/_approved-prototype` })
  await until(() => evaluate('!!document.querySelector(\'[data-go="investigation"]\')'), 'approved prototype')
  await evaluate('document.querySelector(\'[data-go="investigation"]\').click()')
  await screenshot('approved-investigation-desktop', 1440, 1000)
  await screenshot('approved-investigation-mobile', 390, 844)
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  await cdp('Page.navigate', { url: origin })
  await until(async () => (await text()).includes('synthetic controlled fixture'), 'source catalog render')
  await click('nav-investigation')
  await until(() => evaluate('!!document.querySelector(\'[data-testid="history-run"]\')'), 'history list')
  await evaluate(`Array.from(document.querySelectorAll('button')).find(el=>el.textContent==='下一页').click()`)
  await until(() => evaluate(`document.querySelector('[data-testid="history-run"]')?.dataset.runId==='page-fixture-18'`), 'second history page')
  await evaluate(`Array.from(document.querySelectorAll('button')).find(el=>el.textContent==='上一页').click()`)
  await until(() => evaluate(`document.querySelector('[data-testid="history-run"]')?.dataset.runId==='historical-failure'`), 'first history page restored')
  await screenshot('investigation-new-mobile', 390, 844)
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  await evaluate('document.querySelector(\'[data-testid="history-run"]\').click()')
  await until(async () => (await text()).includes('fixture-observation'), 'saved failed observation')
  assert.ok((await text()).includes('execution_failed'))
  assert.ok((await text()).includes('未保存诊断结论'), 'failed task must not fabricate a diagnosis')
  await screenshot('investigation-desktop', 1440, 1000)
  await screenshot('investigation-mobile', 390, 844)
  await evaluate('document.querySelector(\'[data-testid="run-detail"]\').scrollIntoView()')
  await screenshot('investigation-detail-mobile', 390, 844)
  await evaluate(`Array.from(document.querySelectorAll('summary')).find(el=>el.textContent.includes('调查历史')).scrollIntoView()`)
  await screenshot('investigation-history-mobile', 390, 844)
  await evaluate('window.scrollTo(0,0)')
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  await evaluate(`{const button=Array.from(document.querySelectorAll('[data-testid="history-run"]')).find(el=>el.dataset.runId==='historical-success'); if(button.closest('details')) button.closest('details').open=true; button.click();}`)
  await until(async () => (await text()).includes('无需归因') && (await text()).includes('fixture-evidence'), 'saved successful evidence and diagnosis')
  await screenshot('investigation-success-desktop', 1440, 1000)
  await evaluate(`{const input=document.querySelector('[data-testid="target-date"]'); if(input.closest('details')) input.closest('details').open=true; const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; setter.call(input,'2026-10-10'); input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true}));}`)
  await until(() => evaluate('!document.querySelector(\'[data-testid="submit-investigation"]\').disabled'), 'valid explicit date')
  await click('submit-investigation')
  await until(async () => detailReads >= 2 && (await text()).includes('submitted-fixture') && (await text()).includes('execution_failed'), 'queued task polling to failure')
  assert.equal(postCount, 1)
  const terminalReads = detailReads
  await delay(2300)
  assert.equal(detailReads, terminalReads, 'terminal task must stop polling')
  assert.ok(!requests.some((item) => /\/api\/(investigate$|scenarios|scans)/.test(item)), 'no legacy fixture/injection requests')
  await evaluate(`{const select=document.querySelector('[data-testid="source-select"]'); select.value='olist-fixture'; select.dispatchEvent(new Event('change',{bubbles:true}));}`)
  await until(() => evaluate('document.querySelector(\'[data-testid="metric-select"]\')?.value === "orders"'), 'source-specific metric')
  assert.equal(await evaluate('!!document.querySelector(\'[data-testid="run-detail"]\')'), false, 'source change clears old details')
  assert.equal(await evaluate('document.querySelector(\'[data-testid="target-date"]\').value'), '', 'source change requires explicit date')
  catalogUnavailable = true
  await cdp('Page.navigate', { url: origin })
  await until(async () => (await text()).includes('task_service_unavailable'), 'unconfigured service error')
  assert.ok(!(await text()).includes('must-not-render'), 'raw error response must not render')
  await screenshot('service-unavailable-mobile', 390, 844)
  console.log(JSON.stringify({ status: 'passed', boundary: 'controlled HTTP fixtures; real browser; no database or model', postCount, detailReads, output }))
  await cdp('Browser.close').catch(() => {})
} finally {
  socket?.close()
  browser.kill()
  await new Promise((done) => server.close(done))
  // Exact mkdtemp-owned profile only; screenshot evidence is retained separately.
  if (resolve(profile).startsWith(resolve(tmpdir()) + (process.platform === 'win32' ? '\\' : '/'))) {
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }).catch(() => {})
  }
}
