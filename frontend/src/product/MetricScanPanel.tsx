import { useEffect, useRef, useState } from 'react'
import { createMetricClient, MetricClientError } from '../metrics/client'
import type { MetricReadResponse, MetricScanResponse } from '../metrics/contracts'
import type { InvestigationSourceView } from '../tasks/contracts'
import { formatDecimal } from './formatDecimal'

const metricClient = createMetricClient()

const SAFE_SCAN_ERRORS: Record<string, string> = {
  invalid_metric_request: '来源或日期不符合扫描要求，请重新选择。',
  metric_service_unavailable: '指标扫描服务暂不可用，请稍后手动重试。',
  source_not_found: '当前来源不可用，请检查顶部的数据来源。',
  metric_not_supported: '当前来源不支持全局扫描，请检查来源目录中的指标能力。',
  no_supported_metrics: '当前来源没有可扫描的指标。',
  metric_scan_over_budget: '当前来源可用指标超过单次扫描上限。',
  metric_query_unavailable: '暂时无法完成扫描，请稍后手动重试。',
  invalid_response: '服务返回的扫描数据无法识别，请检查来源配置后重试。',
  network_error: '无法连接指标扫描服务，请检查服务状态后手动重试。',
  request_failed: '扫描请求失败，请稍后手动重试。',
}

const STATUS_COPY: Record<NonNullable<MetricReadResponse['observation']>['status'], string> = {
  normal: '正常范围',
  anomalous: '异常候选',
  inconclusive: '结论不确定',
  insufficient_evidence: '证据不足',
  failed: '读取未成功',
}

function providerLabel(provider: MetricScanResponse['provider']): string {
  const labels: Record<MetricScanResponse['provider'], string> = {
    postgresql: 'PostgreSQL', shopify: 'Shopify', olist: 'Olist', synthetic: 'Synthetic',
  }
  return labels[provider]
}

function environmentLabel(environment: MetricScanResponse['environment']): string {
  const labels: Record<MetricScanResponse['environment'], string> = {
    live: '真实环境', sandbox: '隔离实验环境', benchmark: '基准数据环境', validation: '验证环境',
  }
  return labels[environment]
}

function displayTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? '时间不可用' : parsed.toLocaleString()
}

function safeError(error: unknown): string {
  if (error instanceof MetricClientError) return SAFE_SCAN_ERRORS[error.code] ?? SAFE_SCAN_ERRORS.request_failed
  return SAFE_SCAN_ERRORS.request_failed
}

function ScanDecimal({ label, value }: { label: string; value: string | null }) {
  const formatted = formatDecimal(value)
  return <div className="source-fact numeric-fact"><small>{label}</small><strong className="numeric-value">{formatted.approximate && <span aria-label="近似值">≈</span>}{formatted.display}</strong></div>
}

function RawScanDecimal({ label, value }: { label: string; value: string | null }) {
  return <div className="source-fact"><small>{label}</small><code className="decimal-raw">{formatDecimal(value).raw ?? '—'}</code></div>
}

export function MetricScanPanel({
  source,
  supportedMetrics,
  handoffDisabled,
  onHandoff,
}: {
  source: InvestigationSourceView
  supportedMetrics: { metric_id: string }[]
  handoffDisabled: boolean
  onHandoff: (result: MetricReadResponse) => void
}) {
  const [targetDate, setTargetDate] = useState('')
  const [result, setResult] = useState<MetricScanResponse | null>(null)
  const [phase, setPhase] = useState<'idle' | 'loading' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState('')
  const requestController = useRef<AbortController | null>(null)
  const requestEpoch = useRef(0)

  useEffect(() => () => {
    requestEpoch.current += 1
    requestController.current?.abort()
  }, [])

  const clearCurrent = () => {
    requestEpoch.current += 1
    requestController.current?.abort()
    requestController.current = null
    setResult(null)
    setPhase('idle')
    setErrorMessage('')
  }

  const scan = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!targetDate || phase === 'loading') return
    if (supportedMetrics.length > 5) {
      setResult(null)
      setErrorMessage(SAFE_SCAN_ERRORS.metric_scan_over_budget)
      setPhase('error')
      return
    }
    if (supportedMetrics.length === 0) {
      setResult(null)
      setErrorMessage(SAFE_SCAN_ERRORS.no_supported_metrics)
      setPhase('error')
      return
    }

    requestController.current?.abort()
    const controller = new AbortController()
    const epoch = ++requestEpoch.current
    requestController.current = controller
    setResult(null)
    setErrorMessage('')
    setPhase('loading')

    try {
      const response = await metricClient.scan(
        { source_id: source.source_id, target_date: targetDate },
        { signal: controller.signal },
      )
      if (controller.signal.aborted || requestEpoch.current !== epoch) return
      const expectedMetrics = supportedMetrics.map((item) => item.metric_id).sort()
      const actualMetrics = response.items.map((item) => item.target_metric).sort()
      if (response.source_id !== source.source_id
        || response.provider !== source.provider
        || response.environment !== source.environment
        || response.data_version !== source.data_version
        || supportedMetrics.length > 5
        || actualMetrics.length !== expectedMetrics.length
        || actualMetrics.some((metric, index) => metric !== expectedMetrics[index])) {
        throw new MetricClientError(null, 'invalid_response')
      }
      setResult(response)
      setPhase('idle')
    } catch (error) {
      if (controller.signal.aborted || requestEpoch.current !== epoch) return
      setErrorMessage(safeError(error))
      setPhase('error')
    } finally {
      if (requestEpoch.current === epoch) requestController.current = null
    }
  }

  const candidates = result?.anomaly_candidate_metrics.length ?? 0
  const unknown = result?.items.filter((item) => item.anomaly_candidate === null).length ?? 0
  const overBudget = supportedMetrics.length > 5
  const noMetrics = supportedMetrics.length === 0

  return <section className="surface-card metric-scan-panel" aria-labelledby="metric-scan-heading">
    <div className="section-header"><div><h2 id="metric-scan-heading">手动扫描指标</h2><p>按所选日期读取当前来源支持的全局指标；不会自动运行 Agent。</p></div></div>
    <form className="metric-scan-form" onSubmit={(event) => { void scan(event) }}>
      <label className="field"><span>目标日期</span><input data-testid="metric-scan-date" type="date" value={targetDate} onChange={(event) => { clearCurrent(); setTargetDate(event.target.value) }} required /><small>明确选择日期后，点击扫描读取一次。</small></label>
      <button data-testid="metric-scan-submit" className="button button-primary metric-scan-submit" type="submit" disabled={!targetDate || phase === 'loading' || overBudget || noMetrics}>{phase === 'loading' ? <><span className="spinner spinner-light" /> 正在扫描…</> : '扫描指标'}</button>
    </form>
    <p className="quiet-note metric-scan-boundary">只读扫描：不运行 Agent、不保存调查证据；各指标分别查询，不保证同一数据库快照。版本仅标签，查询时间不是上游更新时间。</p>
    {overBudget && <p className="inline-error" role="alert">{SAFE_SCAN_ERRORS.metric_scan_over_budget}</p>}
    {noMetrics && <p className="metric-read-state" role="status">当前来源目录没有标记为支持的可扫描指标。</p>}
    {phase === 'loading' && <div className="metric-read-state" role="status" aria-live="polite"><span className="spinner" />正在读取指标结果…</div>}
    {phase === 'error' && <div className="inline-error" role="alert"><span className="error-mark" aria-hidden="true">!</span><span>{errorMessage}</span></div>}
    {result && <>
      <div className="metric-read-meta metric-scan-source-meta">
        <span>来源：{providerLabel(result.provider)} · {environmentLabel(result.environment)}</span>
        <span>来源 ID：{result.source_id}</span>
        <span>数据版本标签：{result.data_version}</span>
      </div>
      <p className="metric-scan-summary" aria-live="polite">已读取 {result.items.length} 项 · 异常候选 {candidates} 项 · 无法判断 {unknown} 项。{candidates === 0 ? '没有异常候选不代表全部正常，请同时查看不确定项。' : '候选不是原因诊断，需进一步调查。'}</p>
      <div data-testid="metric-scan-result" className="metric-scan-result">
        {result.items.map((item) => {
          const observation = item.observation
          const status = observation?.status ?? 'insufficient_evidence'
          return <article key={item.target_metric} data-testid="metric-scan-row" data-metric-id={item.target_metric} className="metric-scan-row">
            <div className="metric-scan-row-heading"><h3>{item.target_metric}</h3><span className={`metric-read-status metric-read-${status}`}>{observation ? STATUS_COPY[status] : '没有可展示的 Observation'}</span></div>
            {observation ? <>
              <div className="observation-values metric-read-values"><ScanDecimal label="当前值" value={observation.current_value} /><ScanDecimal label="前 7 天基线" value={observation.baseline_value} /><ScanDecimal label="相对变化原始比率" value={observation.relative_change} /></div>
              <p className="metric-read-unit">指标单位：{observation.unit || '来源未提供'}</p>
            </> : <p className="metric-scan-missing">未返回 Observation，不能将缺失数据视为 0 或正常。</p>}
            <p className="metric-scan-periods">当前区间：{observation?.current_period_start ?? result.target_date} 至 {observation?.current_period_end ?? result.target_date} · 基线：{observation?.baseline_period_start ?? '—'} 至 {observation?.baseline_period_end ?? '—'}</p>
            <button data-testid="metric-scan-handoff" data-metric-id={item.target_metric} className="button button-secondary metric-read-handoff" type="button" disabled={handoffDisabled} onClick={() => onHandoff(item)}>带入调查</button>
            {handoffDisabled && <small className="metric-read-handoff-note">当前有调查任务正在提交，提交完成后可带入本次结果。</small>}
            <details className="metric-read-details"><summary>来源、查询时间与原始数据</summary><div className="metric-read-meta">
              <span>来源：{providerLabel(item.provider)} · {environmentLabel(item.environment)}</span>
              <span>来源 ID：{item.source_id}</span>
              <span>数据版本标签：{item.data_version}</span>
              <span>来源状态原值：{observation?.source_status ?? '未返回'}</span>
              <span>查询完成时间：{displayTime(item.queried_at)}（本地时间，不是上游更新时间）</span>
              <span>结果未持久保存为调查证据</span>
            </div>
              <code className="metric-read-query-ref">queried_at UTC：{item.queried_at}</code>
              <code className="metric-read-query-ref">数据版本原值：{item.data_version}</code>
              <code className="metric-read-query-ref">data_version_kind={item.data_version_kind} · persisted={String(item.persisted)} · snapshot_consistent={String(result.snapshot_consistent)}</code>
              <div className="decimal-raw-list"><RawScanDecimal label="当前值原始值" value={observation?.current_value ?? null} /><RawScanDecimal label="基线原始值" value={observation?.baseline_value ?? null} /><RawScanDecimal label="相对变化原始比率" value={observation?.relative_change ?? null} /><RawScanDecimal label="样本量原始值" value={observation?.sample_size ?? null} /></div>
              <p className="metric-read-periods">当前区间：{observation?.current_period_start ?? '—'} 至 {observation?.current_period_end ?? '—'} · 基线：{observation?.baseline_period_start ?? '—'} 至 {observation?.baseline_period_end ?? '—'}</p>
              <code className="metric-read-query-ref">Query reference：{item.query_reference}</code>
            </details>
          </article>
        })}
      </div>
      <p className="metric-scan-completion">本次扫描完成于 {displayTime(result.completed_at)}。完成时间不代表上游数据更新时间。</p>
    </>}
  </section>
}
