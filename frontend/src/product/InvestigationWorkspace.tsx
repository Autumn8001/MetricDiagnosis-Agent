import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createTaskClient, TaskClientError } from '../tasks/client'
import type { MetricReadResponse } from '../metrics/contracts'
import { MetricObservationPanel } from './MetricObservationPanel'
import { MetricScanPanel } from './MetricScanPanel'
import { LabPanel } from './LabPanel'
import type { LabExperiment } from '../lab/client'
import { formatDecimal } from './formatDecimal'
import type {
  InvestigationSourceView,
  TaskDetailResponse,
  TaskRunStatus,
  TaskRunView,
} from '../tasks/contracts'
import './workspace.css'

const taskClient = createTaskClient()
const PAGE_SIZE = 20

type Page = 'overview' | 'metrics' | 'investigation' | 'data' | 'lab'

const NAV_ITEMS: { id: Page; label: string; short: string; icon: 'home' | 'metrics' | 'investigation' | 'data' | 'lab' }[] = [
  { id: 'overview', label: '工作概览', short: '概览', icon: 'home' },
  { id: 'metrics', label: '经营指标', short: '指标', icon: 'metrics' },
  { id: 'investigation', label: 'AI 调查工作区', short: '调查', icon: 'investigation' },
  { id: 'data', label: '数据接入', short: '数据', icon: 'data' },
  { id: 'lab', label: '体验实验室', short: '实验室', icon: 'lab' },
]

function Icon({ name, className }: { name: 'home' | 'spark' | 'overview' | 'metrics' | 'investigation' | 'data' | 'lab' | 'source' | 'runs' | 'active' | 'result' | 'plus' | 'refresh' | 'open'; className?: string }) {
  const paths: Record<typeof name, React.ReactNode> = {
    home: <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z" />,
    spark: <><path d="m12 2 1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2z" /><path d="m20 17 .7 2.3L23 20l-2.3.7L20 23l-.7-2.3L17 20l2.3-.7L20 17z" /></>,
    overview: <><circle cx="12" cy="12" r="8" /><path d="M4.5 12h15M12 4.5v15M7 7l10 10" /></>,
    metrics: <><path d="M4 19V5M4 19h16" /><path d="m7 15 3-4 3 2 5-7" /></>,
    investigation: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 4 4" /></>,
    data: <><ellipse cx="12" cy="5" rx="7.5" ry="3" /><path d="M4.5 5v7c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V5M4.5 12v7c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-7" /></>,
    lab: <><path d="M9 3h6M10 3v6l-5 9.2A2 2 0 0 0 6.8 21h10.4a2 2 0 0 0 1.8-2.8L14 9V3" /><path d="M7.3 16h9.4" /></>,
    source: <><ellipse cx="12" cy="5" rx="7.5" ry="3" /><path d="M4.5 5v7c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V5M4.5 12v7c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-7" /></>,
    runs: <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4.5v-1h6v1M8.5 10h7M8.5 14h7M8.5 18h4" /></>,
    active: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3.5 2" /></>,
    result: <><path d="m5 12 4.5 4.5L19 7" /><circle cx="12" cy="12" r="9" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.6 9A7 7 0 0 1 18 6.5L20 12M4 12l2 5.5A7 7 0 0 0 18.4 15" /></>,
    open: <><path d="M5 12h13M13 6l6 6-6 6" /></>,
  }
  return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

const SAFE_ERROR_COPY: Record<string, string> = {
  task_service_unavailable: '调查服务暂不可用，请稍后手动刷新。',
  source_catalog_unavailable: '数据来源目录暂不可用。',
  invalid_task_request: '请求不符合当前调查能力要求，请检查指标和日期。',
  task_storage_unavailable: '调查记录暂时无法保存，请稍后重试。',
  source_not_found: '所选数据来源当前不可用，请重新选择。',
  metric_or_dimensions_not_supported: '所选数据来源不支持该指标组合。',
  invalid_pagination: '无法读取此页调查记录。',
  investigation_not_found: '调查记录不存在或已不可见。',
  invalid_response: '服务返回的数据格式无法识别。',
  network_error: '无法连接调查服务，请检查服务状态后手动重试。',
  request_failed: '请求失败，请稍后手动重试。',
}

function safeErrorMessage(error: unknown): string {
  if (error instanceof TaskClientError) return `${SAFE_ERROR_COPY[error.code] ?? SAFE_ERROR_COPY.request_failed}（${error.code}）`
  if (error instanceof DOMException && error.name === 'AbortError') return ''
  return SAFE_ERROR_COPY.request_failed
}

function dateTime(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString()
}

function runStatus(status: TaskRunStatus): string {
  const labels: Record<TaskRunStatus, string> = {
    queued: '排队中', running: '调查中', succeeded: '已完成', failed: '失败', cancelled: '已取消',
  }
  return labels[status]
}

function diagnosisStatus(status: string): string {
  const labels: Record<string, string> = {
    diagnosed: '已定位主要变化',
    no_material_anomaly: '未发现明显异常',
    insufficient_evidence: '证据不足',
    budget_exhausted: '调查预算已用尽',
    tool_failure: '工具执行失败',
  }
  return labels[status] ?? status
}

function profileLabel(source: InvestigationSourceView): string {
  if (source.provider === 'olist') return 'Olist 静态公开数据'
  if (source.provider === 'synthetic') return source.environment === 'sandbox' ? 'Synthetic 隔离实验数据' : 'Synthetic 基准数据'
  if (source.provider === 'shopify') return 'Shopify 配置目录'
  return 'PostgreSQL 配置目录'
}

function jsonText(value: unknown): string {
  try { return JSON.stringify(value, null, 2) } catch { return '无法显示结构化内容' }
}

export function InvestigationWorkspace() {
  const [page, setPage] = useState<Page>('overview')
  const [sources, setSources] = useState<InvestigationSourceView[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [catalogError, setCatalogError] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [runs, setRuns] = useState<TaskRunView[]>([])
  const [offset, setOffset] = useState(0)
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState('')
  const [selectedRunId, setSelectedRunId] = useState('')
  const [detail, setDetail] = useState<TaskDetailResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailRefresh, setDetailRefresh] = useState(0)
  const [metric, setMetric] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [notice, setNotice] = useState('')

  const sourceEpoch = useRef(0)
  const submitAbort = useRef<AbortController | null>(null)
  const listAbort = useRef<AbortController | null>(null)
  const listRequest = useRef(0)
  const currentSource = useMemo(() => sources.find((item) => item.source_id === sourceId) ?? null, [sources, sourceId])

  useEffect(() => {
    const controller = new AbortController()
    taskClient.sources({ signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return
      setSources(result.items)
      const selected = result.items[0]
      setSourceId(selected?.source_id ?? '')
      setMetric(selected?.metrics.find((item) => item.supported)?.metric_id ?? '')
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setCatalogError(safeErrorMessage(error))
    }).finally(() => {
      if (!controller.signal.aborted) setCatalogLoading(false)
    })
    return () => controller.abort()
  }, [])

  useEffect(() => () => submitAbort.current?.abort(), [])

  const loadRuns = useCallback(async (requestedSource: string, requestedOffset: number) => {
    if (!requestedSource) return
    listAbort.current?.abort()
    const controller = new AbortController()
    listAbort.current = controller
    const requestId = ++listRequest.current
    setListLoading(true)
    setListError('')
    try {
      const result = await taskClient.list(requestedSource, { limit: PAGE_SIZE, offset: requestedOffset, signal: controller.signal })
      if (controller.signal.aborted || requestId !== listRequest.current || sourceId !== requestedSource) return
      setRuns(result.items)
    } catch (error) {
      if (!controller.signal.aborted && requestId === listRequest.current) setListError(safeErrorMessage(error))
    } finally {
      if (!controller.signal.aborted && requestId === listRequest.current) setListLoading(false)
    }
  }, [sourceId])

  useEffect(() => {
    if (!sourceId) return
    // Starting the external list request also exposes its loading state to the workspace.
    // eslint-disable-next-line react/set-state-in-effect -- loadRuns starts a real request and records its loading state.
    void loadRuns(sourceId, offset)
    return () => listAbort.current?.abort()
  }, [sourceId, offset, loadRuns])

  useEffect(() => {
    if (!selectedRunId || !sourceId) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false
    const requestedSource = sourceId
    const requestedRun = selectedRunId

    const fetchDetail = async () => {
      try {
        const response = await taskClient.detail(requestedRun, requestedSource, { signal: controller.signal })
        if (controller.signal.aborted || sourceId !== requestedSource || selectedRunId !== requestedRun) return
        setDetail(response)
        const listed = await taskClient.list(requestedSource, { limit: PAGE_SIZE, offset, signal: controller.signal })
        if (!controller.signal.aborted && sourceId === requestedSource && selectedRunId === requestedRun) setRuns(listed.items)
        if (response.run.status === 'queued' || response.run.status === 'running') {
          timer = setTimeout(() => { void fetchDetail() }, 2000)
        }
      } catch (error) {
        if (!controller.signal.aborted && !stopped) setDetailError(safeErrorMessage(error))
      } finally {
        if (!controller.signal.aborted && !stopped) setDetailLoading(false)
      }
    }

    void fetchDetail()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      controller.abort()
    }
  }, [selectedRunId, sourceId, detailRefresh, offset])

  const changeSource = (nextSourceId: string) => {
    if (nextSourceId === sourceId) return
    sourceEpoch.current += 1
    submitAbort.current?.abort()
    setSubmitting(false)
    setSubmitError('')
    setNotice('')
    setSelectedRunId('')
    setDetail(null)
    setDetailLoading(false)
    setDetailError('')
    setOffset(0)
    setRuns([])
    setMetric(sources.find((source) => source.source_id === nextSourceId)?.metrics.find((item) => item.supported)?.metric_id ?? '')
    setTargetDate('')
    setSourceId(nextSourceId)
  }

  const openRun = (runId: string) => {
    setPage('investigation')
    setDetail(null)
    setDetailError('')
    setDetailLoading(true)
    if (runId === selectedRunId) setDetailRefresh((value) => value + 1)
    setSelectedRunId(runId)
  }

  const submitInvestigation = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!currentSource || !metric || !targetDate || submitting) return
    const epoch = sourceEpoch.current
    const requestedSource = currentSource.source_id
    const controller = new AbortController()
    submitAbort.current?.abort()
    submitAbort.current = controller
    setSubmitting(true)
    setSubmitError('')
    setNotice('')
    try {
      const run = await taskClient.submit({
        source_id: requestedSource,
        target_metric: metric,
        target_date: targetDate,
        filters: {},
        group_by: [],
      }, { signal: controller.signal })
      if (controller.signal.aborted || sourceEpoch.current !== epoch) return
      setDetail(null)
      setDetailLoading(true)
      setDetailError('')
      setSelectedRunId(run.investigation_run_id)
      setOffset(0)
      setPage('investigation')
      setNotice('调查任务已提交，当前显示来自服务端的实际执行状态。')
      void loadRuns(requestedSource, 0)
    } catch (error) {
      if (!controller.signal.aborted && sourceEpoch.current === epoch) setSubmitError(safeErrorMessage(error))
    } finally {
      if (sourceEpoch.current === epoch) setSubmitting(false)
    }
  }

  const selectPage = (next: Page) => {
    setPage(next)
    setNotice('')
  }

  const refresh = () => {
    if (sourceId) void loadRuns(sourceId, offset)
    if (selectedRunId) {
      setDetailLoading(true)
      setDetailError('')
      setDetailRefresh((value) => value + 1)
    }
  }

  const openLabInvestigation = async (record: LabExperiment, runId: string, signal?: AbortSignal) => {
    const epoch = sourceEpoch.current
    const next = await taskClient.sources({ signal })
    if (signal?.aborted) return
    if (sourceEpoch.current !== epoch) throw new TaskClientError(null, "invalid_response")
    const source = next.items.find(item => item.source_id === record.source_id)
    if (!source || source.provider !== 'synthetic' || source.environment !== 'sandbox' || source.data_version !== record.data_version) {
      throw new TaskClientError(null, 'invalid_response')
    }
    sourceEpoch.current += 1
    submitAbort.current?.abort()
    listAbort.current?.abort()
    setSubmitting(false)
    setSources(next.items)
    setSourceId(source.source_id)
    setMetric(record.requested_metric ?? 'sales')
    setTargetDate(record.target_date)
    setOffset(0)
    setRuns([])
    setDetail(null)
    setDetailError('')
    setSubmitError('')
    setCatalogError('')
    setDetailLoading(true)
    setSelectedRunId(runId)
    setDetailRefresh(value => value + 1)
    setPage('investigation')
    setNotice('已打开实验关联的持久调查。执行状态与证据来自服务端。')
  }

  const supportedMetrics = currentSource?.metrics.filter((item) => item.supported) ?? []
  const allCounts = useMemo(() => runs.reduce<Record<TaskRunStatus, number>>((counts, run) => {
    counts[run.status] += 1
    return counts
  }, { queued: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0 }), [runs])

  return (
    <div className="product-shell">
      <aside className="product-sidebar" aria-label="主导航">
        <a className="product-brand" href="#overview" onClick={(event) => { event.preventDefault(); selectPage('overview') }}>
          <span className="brand-mark"><Icon name="spark" /></span>
          <span><strong>MetricSleuth</strong><small>AI INVESTIGATION</small></span>
        </a>
        <div className="sidebar-section-label">工作区</div>
        <nav className="primary-nav">
          {NAV_ITEMS.filter((item) => item.id !== 'lab').map((item) => (
            <button key={item.id} data-testid={`nav-${item.id}`} className={`nav-item ${page === item.id ? 'is-active' : ''}`} aria-current={page === item.id ? 'page' : undefined} onClick={() => selectPage(item.id)}>
              <Icon name={item.icon} className="nav-glyph" />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-section-label lab-nav-label">实验室</div>
        <nav className="primary-nav">
          <button data-testid="nav-lab" className={`nav-item ${page === 'lab' ? 'is-active' : ''}`} aria-current={page === 'lab' ? 'page' : undefined} onClick={() => selectPage('lab')}><Icon name="lab" className="nav-glyph" /><span>体验实验室</span></button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-footnote"><span className="footnote-dot" />任务记录由服务端保存</div>
      </aside>

      <main className="product-main">
        <header className="workspace-topbar">
          <div className="breadcrumb"><span>MetricSleuth</span><span className="breadcrumb-divider">/</span><strong>{NAV_ITEMS.find((item) => item.id === page)?.label}</strong></div>
          <label className="source-switcher">
            <span>当前数据来源</span>
            <select data-testid="source-select" aria-label="选择数据来源" value={sourceId} onChange={(event) => changeSource(event.target.value)} disabled={catalogLoading || sources.length === 0}>
              {sources.length === 0 && <option value="">暂无可用来源</option>}
              {sources.map((source) => <option key={source.source_id} value={source.source_id}>{source.display_name}</option>)}
            </select>
          </label>
        </header>

        <div className="page-content">
          {page !== 'lab' && (catalogLoading || catalogError || !currentSource) && (
            <section className={`system-state ${catalogError ? 'state-error' : ''}`} role={catalogError ? 'alert' : 'status'}>
              {catalogLoading ? <><span className="spinner" />正在读取数据来源目录…</> : catalogError ? <><strong>数据来源目录不可用</strong><span>{catalogError}</span><button className="button button-secondary" onClick={() => window.location.reload()}>重新加载页面</button></> : <><strong>暂无可用调查来源</strong><span>目前没有可以启动任务的数据来源配置。</span></>}
            </section>
          )}

          {page === 'lab' && <LabPanel onOpen={openLabInvestigation} />}
          {currentSource && <>
            {page === 'overview' && <OverviewPage source={currentSource} runs={runs} counts={allCounts} loading={listLoading} error={listError} onRefresh={refresh} onOpen={openRun} onNew={() => selectPage('investigation')} />}
            {page === 'metrics' && <MetricsPage key={currentSource.source_id} source={currentSource} handoffDisabled={submitting} onHandoff={(result) => {
              setMetric(result.target_metric)
              setTargetDate(result.target_date)
              setPage('investigation')
              setSelectedRunId('')
              setDetail(null)
              setDetailLoading(false)
              setDetailError('')
              setSubmitError('')
              setNotice('已带入指标与日期。请检查调查目标后手动开始调查。')
            }} />}
            {page === 'investigation' && <InvestigationPage
              source={currentSource}
              sources={sources}
              runs={runs}
              offset={offset}
              loading={listLoading}
              listError={listError}
              selectedRunId={selectedRunId}
              detail={detail}
              detailLoading={detailLoading}
              detailError={detailError}
              supportedMetrics={supportedMetrics}
              metric={metric}
              onMetric={setMetric}
              targetDate={targetDate}
              onDate={setTargetDate}
              submitting={submitting}
              submitError={submitError}
              notice={notice}
              onSubmit={submitInvestigation}
              onSelectRun={openRun}
              onRefresh={refresh}
              onPage={(nextOffset) => { setOffset(nextOffset); setSelectedRunId(''); setDetail(null); setDetailLoading(false); setDetailError('') }}
            />}
            {page === 'data' && <DataPage source={currentSource} />}
          </>}
        </div>
      </main>
      <nav className="mobile-nav" aria-label="底部导航">
        {NAV_ITEMS.map((item) => <button key={item.id} data-testid={`nav-${item.id}`} className={page === item.id ? 'is-active' : ''} aria-current={page === item.id ? 'page' : undefined} onClick={() => selectPage(item.id)}><Icon name={item.icon} className="nav-glyph" /><span>{item.short}</span></button>)}
      </nav>
    </div>
  )
}

function PageHeading({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

function OverviewPage({ source, runs, counts, loading, error, onRefresh, onOpen, onNew }: {
  source: InvestigationSourceView; runs: TaskRunView[]; counts: Record<TaskRunStatus, number>; loading: boolean; error: string; onRefresh: () => void; onOpen: (id: string) => void; onNew: () => void
}) {
  return <>
    <PageHeading title="业务运行概览" description="查看已保存的调查任务状态，并从真实配置的数据来源开始一次调查。" action={<button className="button button-primary" onClick={onNew}><Icon name="plus" /> 发起调查</button>} />
    <div className="summary-grid">
      <SummaryCard label="当前来源" value={source.display_name} detail={`${profileLabel(source)} · ${source.environment}`} icon="source" />
      <SummaryCard label="本页调查记录" value={String(runs.length)} detail="按创建时间倒序 · 每页最多 20 条" icon="runs" />
      <SummaryCard label="正在处理" value={String(counts.queued + counts.running)} detail={`排队 ${counts.queued} · 调查中 ${counts.running}`} icon="active" />
      <SummaryCard label="已完成 / 失败" value={`${counts.succeeded} / ${counts.failed}`} detail="仅统计当前来源的本页记录" icon="result" />
    </div>
    <section className="surface-card">
      <SectionHeader title="最近调查" subtitle="任务状态和时间来自持久化记录。" action={<button className="text-button" onClick={onRefresh} disabled={loading}>{loading ? '读取中…' : <><Icon name="refresh" /> 刷新记录</>}</button>} />
      {error ? <InlineError message={error} onRetry={onRefresh} /> : <RunTable runs={runs} loading={loading} onOpen={onOpen} />}
    </section>
  </>
}

function SummaryCard({ label, value, detail, icon }: { label: string; value: string; detail: string; icon: string }) {
  return <article className="summary-card"><div className={`summary-icon summary-${icon}`} aria-hidden="true"><Icon name={icon as 'source' | 'runs' | 'active' | 'result'} /></div><div className="summary-copy"><span>{label}</span><strong title={value}>{value}</strong><small>{detail}</small></div></article>
}

function SectionHeader({ title, subtitle, action }: { title: string; subtitle: string; action?: React.ReactNode }) {
  return <div className="section-header"><div><h2>{title}</h2><p>{subtitle}</p></div>{action}</div>
}

function RunTable({ runs, loading, onOpen }: { runs: TaskRunView[]; loading: boolean; onOpen: (id: string) => void }) {
  if (loading && runs.length === 0) return <div className="empty-state"><span className="spinner" />正在读取已保存的调查…</div>
  if (runs.length === 0) return <div className="empty-state"><Icon name="runs" className="empty-symbol" /><strong>还没有调查记录</strong><span>选择一个目标日期和指标后，可以启动第一次调查。</span></div>
  return <div className="table-scroll"><table className="runs-table"><thead><tr><th>目标指标</th><th>状态</th><th>创建时间</th><th>调查步骤</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{runs.map((run) => <tr key={run.investigation_run_id}><td><strong>{run.requested_metric}</strong><small className="table-id">{run.investigation_run_id}</small></td><td><StatusBadge status={run.status} /></td><td>{dateTime(run.requested_at)}</td><td>{run.tool_call_count} 次工具调用</td><td><button data-testid="history-run" data-run-id={run.investigation_run_id} className="row-link" onClick={() => onOpen(run.investigation_run_id)}>查看记录 <Icon name="open" /></button></td></tr>)}</tbody></table></div>
}

function StatusBadge({ status }: { status: TaskRunStatus }) {
  return <span className={`status-badge status-${status}`}><i aria-hidden="true" />{runStatus(status)}</span>
}

function MetricsPage({ source, handoffDisabled, onHandoff }: { source: InvestigationSourceView; handoffDisabled: boolean; onHandoff: (result: MetricReadResponse) => void }) {
  const supportedMetrics = source.metrics.filter((item) => item.supported)
  const scanIdentity = JSON.stringify([
    source.source_id,
    source.provider,
    source.environment,
    source.data_version,
    supportedMetrics.map((item) => item.metric_id).sort(),
  ])
  return <>
    <PageHeading title="指标与数据能力" description="可按日期扫描当前来源支持的指标，或单独读取一项；下方能力目录说明该来源支持的粒度与维度。" />
    <MetricScanPanel key={scanIdentity} source={source} supportedMetrics={supportedMetrics} handoffDisabled={handoffDisabled} onHandoff={onHandoff} />
    <MetricObservationPanel key={source.source_id} source={source} supportedMetrics={supportedMetrics} handoffDisabled={handoffDisabled} onHandoff={onHandoff} />
    <section className="surface-card">
      <SectionHeader title="可调查指标" subtitle={`${source.display_name} · ${profileLabel(source)}`} />
      {source.metrics.length === 0 ? <div className="empty-state"><strong>尚无指标能力信息</strong><span>来源目录没有返回指标配置。</span></div> : <div className="metric-list">{source.metrics.map((item) => <article className="metric-row" key={item.metric_id}><div className="metric-leading"><span className={`metric-state-dot ${item.supported ? 'available' : ''}`} /><div><h3>{item.metric_id}</h3><span>{item.supported ? '支持调查' : '当前不可用'}</span></div></div><div className="metric-properties"><div><small>数据粒度</small><span>{item.grain.length ? item.grain.join(' · ') : '目录未声明'}</span></div><div><small>可用维度</small><span>{item.dimensions.length ? item.dimensions.join(' · ') : '无可用维度'}</span></div></div>{item.unavailable_reason && <p className="metric-reason">{item.unavailable_reason}</p>}</article>)}</div>}
      <p className="quiet-note">指标定义表示系统已配置的语义能力，不代表来源当前在线、数据最新或覆盖目标日期。</p>
    </section>
  </>
}

function DataPage({ source }: { source: InvestigationSourceView }) {
  return <>
    <PageHeading title="数据来源与接入" description="查看系统登记的数据来源身份和能力配置。目录登记不表示外部服务已连接。" />
    <section className="source-detail-card">
      <div className="source-card-heading"><span className="source-emblem"><Icon name="source" /></span><div><h2>{source.display_name}</h2><p>{profileLabel(source)}</p></div><span className="config-tag">配置目录</span></div>
      <div className="source-facts"><Fact label="Provider" value={source.provider} /><Fact label="环境" value={source.environment} /><Fact label="Source ID" value={source.source_id} /><Fact label="数据版本标签" value={source.data_version} /></div>
      <div className="source-notice"><span aria-hidden="true">i</span><p><strong>这是服务端登记的来源配置。</strong>页面没有探测数据库或外部平台连接状态；数据版本是标识标签，不保证对应不可变快照或持续更新。</p></div>
      <div className="connection-checklist"><h3>接入状态</h3><div><span className="check-pending">—</span><span>凭据与只读权限状态未由此目录验证</span><span className="muted-value">未探测</span></div><div><span className="check-pending">—</span><span>最近同步时间未提供</span><span className="muted-value">未知</span></div></div>
    </section>
  </>
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="source-fact"><small>{label}</small><strong title={value}>{value}</strong></div>
}

function InvestigationPage({
  source, sources, runs, offset, loading, listError, selectedRunId, detail, detailLoading, detailError, supportedMetrics, metric, onMetric, targetDate, onDate, submitting, submitError, notice, onSubmit, onSelectRun, onRefresh, onPage,
}: {
  source: InvestigationSourceView; sources: InvestigationSourceView[]; runs: TaskRunView[]; offset: number; loading: boolean; listError: string; selectedRunId: string; detail: TaskDetailResponse | null; detailLoading: boolean; detailError: string; supportedMetrics: InvestigationSourceView['metrics']; metric: string; onMetric: (value: string) => void; targetDate: string; onDate: (value: string) => void; submitting: boolean; submitError: string; notice: string; onSubmit: (event: React.FormEvent<HTMLFormElement>) => void; onSelectRun: (runId: string) => void; onRefresh: () => void; onPage: (offset: number) => void;
}) {
  return <div className="investigation-page">
    <PageHeading title={selectedRunId ? '调查记录详情' : '发起数据调查'} description="提交后，Agent 在服务端按任务执行；这里读取已保存的真实状态、工具记录和证据。" />
    {selectedRunId && <TaskDetailPanel detail={detail} loading={detailLoading} error={detailError} runId={selectedRunId} onRefresh={onRefresh} onNew={() => onSelectRun('')} />}
    {sources.length > 0 && <details key={selectedRunId ? 'existing-run' : 'new-run'} className="investigation-disclosure" open={!selectedRunId}>
      <summary><span>新建调查</span><small>选择来源、指标与目标日期</small></summary>
      <form className="surface-card investigation-form" onSubmit={onSubmit}>
      <SectionHeader title="调查目标" subtitle="首版按单日与前 7 天基线比较，不附加隐式筛选或分组。" />
      <div className="form-grid"><label className="field"><span>数据来源</span><select value={source.source_id} disabled><option value={source.source_id}>{source.display_name} · {source.environment}</option></select><small>在顶部来源选择器切换。</small></label>
        <label className="field"><span>目标指标</span><select data-testid="metric-select" value={metric} onChange={(event) => onMetric(event.target.value)} required disabled={supportedMetrics.length === 0}><option value="" disabled>选择可调查指标</option>{supportedMetrics.map((item) => <option key={item.metric_id} value={item.metric_id}>{item.metric_id}</option>)}</select><small>仅列出该来源目录标记为支持的指标。</small></label>
        <label className="field"><span>目标日期</span><input data-testid="target-date" type="date" value={targetDate} onChange={(event) => onDate(event.target.value)} required /><small>请明确选择要调查的日期。</small></label></div>
      <div className="query-boundary"><span aria-hidden="true">i</span><p>本次请求使用空筛选与空分组。系统会按该指标定义执行；不同指标的数据粒度和可用维度以指标页及后端验证为准。</p></div>
      {submitError && <InlineError message={submitError} />}
      {submitError && <p className="submission-uncertain">提交结果可能不确定，请先刷新历史确认任务是否已入队，再决定下一步。系统不会自动重新提交。</p>}
      {notice && <p className="inline-notice" role="status">{notice}</p>}
      <div className="form-footer"><span>切换来源只会中断当前浏览请求，不代表取消已入队任务。</span><button data-testid="submit-investigation" className="button button-primary" type="submit" disabled={!metric || !targetDate || submitting || supportedMetrics.length === 0}>{submitting ? <><span className="spinner spinner-light" /> 正在提交…</> : '开始调查'}</button></div>
      </form>
    </details>}
    <details key={selectedRunId ? 'history-existing' : 'history-new'} className="investigation-disclosure" open={!selectedRunId}>
    <summary><span>调查历史</span><small>{source.display_name} · 当前页 {runs.length} 条</small></summary>
    <section className="surface-card history-card"><SectionHeader title="已保存任务" subtitle="按服务端记录时间倒序排列。" action={<button className="text-button" onClick={onRefresh} disabled={loading}>{loading ? '读取中…' : <><Icon name="refresh" /> 手动刷新</>}</button>} />
      {listError ? <InlineError message={listError} onRetry={onRefresh} /> : <RunTable runs={runs} loading={loading} onOpen={onSelectRun} />}
      <div className="pagination"><span>{runs.length ? `显示 ${offset + 1}–${offset + runs.length} 条` : `第 ${Math.floor(offset / PAGE_SIZE) + 1} 页`}</span><div><button className="button button-secondary button-small" onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0 || loading}>上一页</button><button className="button button-secondary button-small" onClick={() => onPage(offset + PAGE_SIZE)} disabled={runs.length < PAGE_SIZE || loading}>下一页</button></div></div>
    </section>
    </details>
  </div>
}

function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div data-testid="task-error" className="inline-error" role="alert"><span className="error-mark" aria-hidden="true">!</span><span>{message}</span>{onRetry && <button className="text-button" onClick={onRetry}>手动重试</button>}</div>
}

function TaskDetailPanel({ detail, loading, error, runId, onRefresh, onNew }: { detail: TaskDetailResponse | null; loading: boolean; error: string; runId: string; onRefresh: () => void; onNew: () => void }) {
  if (error) return <section className="surface-card"><SectionHeader title="调查详情" subtitle={runId} action={<><button className="text-button" onClick={onNew}>新建调查</button><button className="text-button" onClick={onRefresh}><Icon name="refresh" /> 重新读取</button></>} /><InlineError message={error} /></section>
  if (!detail) return <section className="surface-card detail-loading"><span className="spinner" />{loading ? '正在读取持久化详情…' : '暂无详情'}</section>
  const { run } = detail
  return <section data-testid="run-detail" className="surface-card task-detail" aria-live="polite">
    <SectionHeader title="调查详情" subtitle={`Run ${run.investigation_run_id}`} action={<div className="detail-heading-actions"><StatusBadge status={run.status} /><button className="text-button" onClick={onNew}>新建调查</button><button className="text-button" onClick={onRefresh} disabled={loading}><Icon name="refresh" /> 刷新详情</button></div>} />
    <div className="detail-columns">
      <div className="detail-results">
        <ObservationSection detail={detail} />
        <EvidenceSection detail={detail} />
        <DiagnosisSection detail={detail} />
      </div>
      <div className="detail-process">
        <section className="detail-section"><SectionHeader title="本次运行" subtitle="来源身份、版本和持久化状态。" /><div className="run-meta-grid"><Fact label="状态" value={runStatus(run.status)} /><Fact label="来源 / 环境" value={`${run.provider} · ${run.environment}`} /><Fact label="来源 ID" value={run.source_id} /><Fact label="请求指标" value={run.requested_metric} /><Fact label="数据版本标签" value={run.data_version ?? '未提供'} /><Fact label="查询引用" value={run.query_reference ?? '未提供'} /><Fact label="更新时间" value={dateTime(run.finished_at ?? run.started_at ?? run.requested_at)} /></div>{run.status === 'failed' && <div className="failure-note"><strong>任务失败</strong><span>安全错误代码：{run.failure_code ?? '未提供'}</span></div>}<div className="trace-summary"><strong>{detail.tool_calls.length}</strong><span>工具调用</span><strong>{detail.observations.length}</strong><span>观察结果</span><strong>{detail.evidence.length}</strong><span>证据</span><strong>{detail.diagnoses.length}</strong><span>诊断</span></div></section>
        <ToolCallsSection detail={detail} />
      </div>
    </div>
  </section>
}

function ToolCallsSection({ detail }: { detail: TaskDetailResponse }) {
  return <div className="detail-section"><SectionHeader title="调查过程" subtitle="参数和引用来自已保存的工具轨迹。" />{detail.tool_calls.length ? <div className="fact-list">{detail.tool_calls.map((call, index) => <details className="trace-item" key={call.tool_call_id}><summary><span className="trace-index">{String(index + 1).padStart(2, '0')}</span><strong>{call.tool_name}</strong><span className={`tool-result tool-${call.status}`}>{call.status}</span><time>{dateTime(call.requested_at)}</time></summary><div className="trace-body"><Fact label="Tool Call ID" value={call.tool_call_id} /><Fact label="数据版本" value={call.data_version ?? '未提供'} /><Fact label="Query reference" value={call.query_reference ?? '未提供'} /><Fact label="Result reference" value={call.result_reference ?? '未提供'} /><pre>{jsonText(call.arguments)}</pre></div></details>)}</div> : <DetailEmpty text="本次调查没有保存工具调用。" />}</div>
}

function ObservationSection({ detail }: { detail: TaskDetailResponse }) {
  return <div className="detail-section"><SectionHeader title="调查结果" subtitle="Observation 来自持久化记录；≈ 表示展示值经过舍入，原始值见明细，相对变化保留原始比率。" />{detail.observations.length ? <div className="observation-list">{detail.observations.map((observation, index) => <article className="observation-card" key={observation.observation_id}><div className="observation-title"><div><strong>{observation.metric}</strong><small>{observation.status}{observation.source_status ? ` · ${observation.source_status}` : ''}</small></div><span className="observation-unit">{observation.unit ?? '单位未提供'}</span></div><p className="observation-dimensions">{Object.keys(observation.dimensions).length ? `维度：${jsonText(observation.dimensions)}` : '当前查询总体'}</p><div className="observation-values"><DecimalFact label="当前值" value={observation.current_value} /><DecimalFact label="基线值" value={observation.baseline_value} /><DecimalFact label="相对变化" value={observation.relative_change} /></div><details className="observation-details" open={index === 0}><summary>数据明细与原始值</summary><div className="observation-meta"><span>Observation ID：{observation.observation_id}</span><span>Tool Call ID：{observation.tool_call_id ?? '未关联'}</span><span>当前区间：{observation.current_period_start ?? '—'} 至 {observation.current_period_end ?? '—'}</span><span>基线区间：{observation.baseline_period_start ?? '—'} 至 {observation.baseline_period_end ?? '—'}</span><span>筛选：{jsonText(observation.filters)}</span><span>分组：{observation.group_by.length ? observation.group_by.join(', ') : '无'}</span><span>维度值：{jsonText(observation.dimensions)}</span><span>Query reference：{observation.query_reference ?? '未提供'}</span>{observation.error_code && <span>安全错误代码：{observation.error_code}</span>}</div><div className="decimal-raw-list"><RawDecimal label="当前值原始值" value={observation.current_value} /><RawDecimal label="基线值原始值" value={observation.baseline_value} /><RawDecimal label="相对变化原始值" value={observation.relative_change} /></div></details></article>)}</div> : <DetailEmpty text="本次调查没有保存观察结果。" />}</div>
}

function EvidenceSection({ detail }: { detail: TaskDetailResponse }) {
  return <div className="detail-section"><SectionHeader title="证据" subtitle="每条证据关联到其 Observation 和 Tool Call。" />{detail.evidence.length ? <div className="evidence-list">{detail.evidence.map((evidence) => { const observation = detail.observations.find((item) => item.observation_id === evidence.observation_id); return <article className="evidence-row" key={evidence.evidence_id}><span className="evidence-marker">E</span><div><strong>{evidence.role} · {observation?.metric ?? '指标未找到'}</strong><small>Evidence {evidence.evidence_id}</small><small>Observation {evidence.observation_id} · Tool {evidence.tool_call_id ?? '未关联'}</small><small>Query {evidence.query_reference ?? '未提供'} · Version {evidence.data_version ?? '未提供'}</small></div></article> })}</div> : <DetailEmpty text="本次调查没有保存 Evidence。" />}</div>
}

function DiagnosisSection({ detail }: { detail: TaskDetailResponse }) {
  return <div className="detail-section"><SectionHeader title="诊断结论" subtitle="只显示已持久化的 Diagnosis。" />{detail.diagnoses.length ? <div className="diagnosis-list">{detail.diagnoses.map((diagnosis) => { const noMaterialAnomaly = diagnosis.status === 'no_material_anomaly'; const hasScope = Object.keys(diagnosis.affected_scope).length > 0; return <article className="diagnosis-card" key={diagnosis.diagnosis_id}><div className="diagnosis-heading"><strong>{diagnosisStatus(diagnosis.status)}</strong><span>置信度 {diagnosis.confidence ?? '未提供'}</span></div><Fact label="目标指标" value={diagnosis.target_metric} /><Fact label="主要驱动" value={diagnosis.primary_driver ?? (noMaterialAnomaly ? '无需归因（未发现明显异常）' : '不适用（未产生成功诊断）')} /><Fact label="影响范围" value={hasScope ? jsonText(diagnosis.affected_scope) : noMaterialAnomaly ? '无需定位影响范围（未发现明显异常）' : '不适用（未产生成功诊断）'} />{diagnosis.change && <><div className="observation-values"><DecimalFact label="当前值" value={diagnosis.change.current_value} /><DecimalFact label="基线值" value={diagnosis.change.baseline_value} /><DecimalFact label="相对变化" value={diagnosis.change.relative_change} /></div><details className="decimal-details"><summary>数据明细与原始值</summary><div className="decimal-raw-list"><RawDecimal label="当前值原始值" value={diagnosis.change.current_value} /><RawDecimal label="基线值原始值" value={diagnosis.change.baseline_value} /><RawDecimal label="相对变化原始值" value={diagnosis.change.relative_change} /><Fact label="关联证据" value={diagnosis.change.evidence_id} /></div></details></>}<Fact label="Evidence IDs" value={diagnosis.evidence_ids.join(', ') || '无'} /><div className="limitations"><strong>限制说明</strong>{diagnosis.limitations.length ? <ul>{diagnosis.limitations.map((item, index) => <li key={`${diagnosis.diagnosis_id}-limit-${index}`}>{item}</li>)}</ul> : <span>未提供</span>}</div></article> })}</div> : <DetailEmpty text={detail.run.status === 'failed' ? '本次任务失败，未保存诊断结论。' : '当前记录尚无已保存的诊断结论。'} />}</div>
}

function DecimalFact({ label, value }: { label: string; value: number | string | null }) {
  const formatted = formatDecimal(value)
  return <div className="source-fact numeric-fact"><small>{label}</small><strong className="numeric-value" data-testid="decimal-value">{formatted.approximate && <span aria-label="近似值">≈</span>}{formatted.display}</strong></div>
}

function RawDecimal({ label, value }: { label: string; value: number | string | null }) {
  const raw = formatDecimal(value).raw
  return <div className="source-fact"><small>{label}</small><code className="decimal-raw">{raw ?? '—'}</code></div>
}

function DetailEmpty({ text }: { text: string }) {
  return <p className="detail-empty">{text}</p>
}
