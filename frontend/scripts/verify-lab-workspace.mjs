// Desktop UI acceptance using controlled HTTP data, never a database/model gate.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFile, mkdir, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { randomUUID } from 'node:crypto'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const tools = process.env.METRICSLEUTH_BROWSER_TOOLS
const pack = process.env.METRICSLEUTH_CHROMIUM_PACK
if (!tools || !pack) throw new Error('explicit_browser_tools_and_pack_required')
const output = resolve(frontend, '..', '.impeccable/review')
await mkdir(output, { recursive: true })
const runtime = await mkdtemp(join(tmpdir(), 'metricsleuth-lab-browser-'))
process.env.TMPDIR = runtime
process.env.AWS_EXECUTION_ENV = 'AWS_Lambda_nodejs22.x'
const fonts = join(runtime, 'fonts'); await mkdir(fonts)
const fontConfig = join(fonts, 'fonts.conf')
await writeFile(fontConfig, `<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/usr/share/fonts</dir><cachedir>${runtime}/font-cache</cachedir></fontconfig>`)
process.env.FONTCONFIG_PATH = fonts; process.env.FONTCONFIG_FILE = fontConfig
const { default: chromium } = await import(pathToFileURL(join(tools, '@sparticuz/chromium-min/build/index.js')).href)
const { chromium: playwright } = await import(pathToFileURL(join(tools, 'playwright-core/index.mjs')).href)

const source = randomUUID(), experimentId = randomUUID(), runId = randomUUID()
const version = 'sandbox-' + 'a'.repeat(64), stamp = '2026-10-13T12:00:00Z'
let record = null, investigation = null, posts = 0, catalogFailure = false
const requests = []
const catalog = () => ({ target_date: '2026-01-31', scenarios: [
  { scenario_id: 'no_anomaly', title: '正常业务基线', description: '受控 HTTP 验证数据；无数据库或模型调用。' },
  { scenario_id: 'canonical', title: '受控异常 A', description: '另一组受控 HTTP 验证场景。' },
  { scenario_id: 'traffic', title: '受控异常 B', description: '另一组受控 HTTP 验证场景。' },
], targets: [{ source_id: source, display_name: '桌面 HTTP 验证空间', provider: 'synthetic', environment: 'sandbox',
  state: record ? 'published' : 'available', experiment_id: record?.experiment_id ?? null }] })
const sourceView = () => ({ source_id: source, display_name: '桌面 HTTP 验证空间', provider: 'synthetic', environment: 'sandbox', data_version: version,
  metrics: ['sales','orders','sessions','conversion_rate','aov'].map(metric_id => ({ metric_id, supported: true, grain: ['date','asin','marketplace','traffic_source'], dimensions: ['asin','marketplace','traffic_source'], unavailable_reason: null })) })
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  const json = (body, status = 200) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(body)) }
  requests.push(`${req.method} ${url.pathname}`)
  try {
    if (url.pathname === '/api/lab/catalog') return catalogFailure
      ? json({ detail: { code: 'lab_service_unavailable', message: 'private-marker' } }, 503) : json(catalog())
    if (url.pathname === '/api/lab/experiments' && req.method === 'GET') return json({ items: record ? [record] : [], limit: 20, offset: 0 })
    if (url.pathname === '/api/lab/experiments' && req.method === 'POST') {
      let body = ''; for await (const chunk of req) body += chunk
      const input = JSON.parse(body); assert.equal(input.source_id, source); assert.equal(input.scenario_id, 'no_anomaly')
      posts++
      record = { experiment_id: experimentId, source_id: source, environment: 'sandbox', provider: 'synthetic', scenario_id: input.scenario_id,
        target_date: '2026-01-31', status: 'published', created_at: stamp, updated_at: stamp, data_version: version, failure_code: null,
        requested_metric: null, investigation_run_id: null, data_version_kind: 'label', snapshot_consistent: false }
      return json(record, 202)
    }
    if (url.pathname === `/api/lab/experiments/${experimentId}`) return json(record)
    if (url.pathname === `/api/lab/experiments/${experimentId}/investigations`) {
      let body = ''; for await (const chunk of req) body += chunk
      assert.deepEqual(JSON.parse(body), { target_metric: 'sales' })
      investigation = { investigation_run_id: runId, source_id: source, environment: 'sandbox', provider: 'synthetic', status: 'failed',
        requested_metric: 'sales', requested_at: stamp, started_at: stamp, finished_at: stamp, data_version: version,
        query_reference: 'lab-task:' + experimentId, failure_code: 'execution_failed', tool_call_count: 0, observation_count: 0, evidence_count: 0, diagnosis_count: 0 }
      record = { ...record, requested_metric: 'sales', investigation_run_id: runId }
      return json(investigation, 202)
    }
    if (url.pathname === '/api/investigation-sources') return json({ items: record ? [sourceView()] : [] })
    if (url.pathname === '/api/investigations') return json({ items: investigation ? [investigation] : [], limit: 20, offset: 0 })
    if (url.pathname === `/api/investigations/${runId}`) return json({ run: investigation, tool_calls: [], observations: [], evidence: [], diagnoses: [] })
    if (url.pathname === '/api/metrics/scan') {
      const query = 'metric-read:' + randomUUID()
      const item = { source_id: source, provider: 'synthetic', environment: 'sandbox', data_version: version, data_version_kind: 'label',
        persisted: false, scope: 'source_global', target_metric: 'sales', target_date: '2026-01-31', comparison: 'previous_7_days',
        queried_at: stamp, query_reference: query, anomaly_candidate: false, observation: { metric: 'sales', status: 'normal', source_status: 'ok',
          current_period_start: '2026-01-31', current_period_end: '2026-01-31', baseline_period_start: '2026-01-24', baseline_period_end: '2026-01-30',
          current_value: '52000.00', baseline_value: '52000.00', relative_change: '0', unit: 'usd', sample_size: '1000.00' } }
      return json({ source_id: source, provider: 'synthetic', environment: 'sandbox', data_version: version, data_version_kind: 'label',
        persisted: false, scope: 'source_global', target_date: '2026-01-31', comparison: 'previous_7_days', snapshot_consistent: false,
        completed_at: stamp, items: [item], anomaly_candidate_metrics: [] })
    }
    const relative = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname).slice(1)
    const file = resolve(frontend, 'dist', relative)
    if (!file.startsWith(resolve(frontend, 'dist') + '/')) return json({ detail: { code: 'not_found' } }, 404)
    const data = await readFile(file)
    res.writeHead(200, { 'content-type': relative.endsWith('.js') ? 'text/javascript' : relative.endsWith('.css') ? 'text/css' : relative.endsWith('.svg') ? 'image/svg+xml' : 'text/html' }); res.end(data)
  } catch { json({ detail: { code: 'fixture_request_failed' } }, 500) }
})
let context, stage = 'start'
try {
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve) })
  const base = `http://127.0.0.1:${server.address().port}`
  stage = 'launch'
  const executablePath = await chromium.executablePath(pack)
  const args = chromium.args.filter(arg => !['--disable-web-security','--allow-running-insecure-content'].includes(arg))
  context = await playwright.launchPersistentContext(join(runtime, 'profile'), { executablePath, args, headless: true,
    viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
  const page = await context.newPage()
  await page.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort())
  await page.goto(base)
  stage = 'empty_lab'
  await page.getByTestId('nav-lab').first().click()
  await page.getByTestId('lab-target').waitFor()
  await page.getByRole('heading', { name: '隔离数据实验室' }).waitFor()
  assert.equal(await page.getByTestId('lab-publish').isEnabled(), true)
  await page.screenshot({ path: join(output, 'lab-empty-desktop.png'), fullPage: true })
  stage = 'publish'
  await page.getByTestId('lab-publish').click()
  await page.getByTestId('lab-read-metrics').waitFor()
  assert.equal(posts, 1)
  stage = 'metrics'
  await page.getByTestId('lab-read-metrics').click()
  await page.getByRole('heading', { name: '实际指标读取' }).waitFor()
  await page.getByText('52,000', { exact: true }).first().waitFor()
  assert.equal(await page.locator('body').evaluate(el => el.scrollWidth > document.documentElement.clientWidth), false)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: join(output, 'lab-published-desktop.png'), fullPage: true })
  stage = 'investigation'
  await page.getByTestId('lab-investigate').click()
  stage = 'investigation_heading'
  await page.getByRole('heading', { name: '调查记录详情', exact: true }).waitFor()
  stage = 'investigation_disclosure'
  await page.locator('details.investigation-disclosure > summary').first().click()
  stage = 'investigation_notice'
  await page.getByText('已打开实验关联的持久调查。执行状态与证据来自服务端。').waitFor()
  assert.equal(await page.getByTestId('source-select').inputValue(), source)
  assert.equal(await page.getByTestId('target-date').inputValue(), '2026-01-31')
  stage = 'reload'
  await page.reload()
  await page.getByTestId('nav-lab').first().click()
  await page.getByTestId('lab-investigate').waitFor()
  assert.equal(await page.getByTestId('lab-investigate').textContent(), '查看关联调查')
  assert.equal(posts, 1)
  stage = 'error'
  catalogFailure = true
  await page.getByRole('button', { name: '刷新记录', exact: true }).click()
  await page.getByText('实验信息读取失败').waitFor()
  assert.equal((await page.locator('body').innerText()).includes('private-marker'), false)
  await page.screenshot({ path: join(output, 'lab-error-desktop.png'), fullPage: true })
  const report = { status: 'passed', desktop: '1440x1000', controlled_http_fixture: true, real_database: false, real_model: false,
    checks: ['empty_catalog_lab_access','one_publish_post','actual_response_metrics','source_bound_task_handoff','reload_history_without_replay','safe_error_copy','no_horizontal_overflow'], requests }
  await writeFile(join(output, 'lab-browser-report.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify({ status: 'passed', desktop: report.desktop, controlled_http_fixture: true, real_database: false, real_model: false, publish_posts: posts }))
} catch {
  if (context) {
    const pages = context.pages()
    if (pages.length) await pages.at(-1).screenshot({ path: join(output, 'lab-debug-desktop.png'), fullPage: true }).catch(() => {})
  }
  console.error('lab_browser_acceptance_failed:' + stage)
  process.exitCode = 1
} finally {
  if (context) await context.close()
  if (server.listening) await new Promise(resolve => server.close(resolve))
  await rm(runtime, { recursive: true, force: true })
}
