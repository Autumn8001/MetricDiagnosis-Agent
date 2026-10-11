import { useEffect, useRef, useState } from 'react'
import { createMetricClient, MetricClientError } from '../metrics/client'
import type { MetricReadResponse } from '../metrics/contracts'
import type { InvestigationSourceView } from '../tasks/contracts'
import { formatDecimal } from './formatDecimal'

const metricClient = createMetricClient()

const SAFE_READ_ERRORS: Record<string, string> = {
  invalid_metric_request: '指标或日期不符合读取要求，请重新选择。',
  metric_service_unavailable: '指标读取服务暂不可用，请稍后手动重试。',
  source_not_found: '当前来源不可用，请检查顶部的数据来源。',
  metric_not_supported: '当前来源不支持所选指标。',
  metric_query_unavailable: '暂时无法读取该指标，请稍后手动重试。',
  invalid_response: '服务返回的数据格式无法识别。',
  network_error: '无法连接指标读取服务，请检查服务状态。',
  request_failed: '指标读取失败，请稍后手动重试。',
}

const STATUS_COPY: Record<NonNullable<MetricReadResponse['observation']>['status'], { label: string; detail: string }> = {
  normal: { label: '当前变化在正常范围', detail: '此次读取未标记出明显变化。' },
  anomalous: { label: '发现异常候选', detail: '变化达到当前指标规则的异常阈值，可继续调查。' },
  inconclusive: { label: '变化结论不确定', detail: '当前结果不足以判定正常或异常。' },
  insufficient_evidence: { label: '数据证据不足', detail: '当前期间或基线缺少可用于比较的数据。' },
  failed: { label: '指标读取未成功', detail: '查询没有得到可用的指标观察结果。' },
}

function providerLabel(provider: MetricReadResponse['provider']): string {
  const labels: Record<MetricReadResponse['provider'], string> = {
    postgresql: 'PostgreSQL', shopify: 'Shopify', olist: 'Olist', synthetic: 'Synthetic',
  }
  return labels[provider]
}

function environmentLabel(environment: MetricReadResponse['environment']): string {
  const labels: Record<MetricReadResponse['environment'], string> = {
    live: '真实环境', sandbox: '隔离实验环境', benchmark: '基准数据环境', validation: '验证环境',
  }
  return labels[environment]
}

function formatTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? '时间不可用' : parsed.toLocaleString()
}

function safeReadError(error: unknown): string {
  if (error instanceof MetricClientError) return SAFE_READ_ERRORS[error.code] ?? SAFE_READ_ERRORS.request_failed
  return SAFE_READ_ERRORS.request_failed
}

function ReadDecimal({ label, value }: { label: string; value: string | number | null }) {
  const formatted = formatDecimal(value)
  return <div className="source-fact numeric-fact"><small>{label}</small><strong className="numeric-value">{formatted.approximate && <span aria-label="近似值">≈</span>}{formatted.display}</strong></div>
}

function RawReadDecimal({ label, value }: { label: string; value: string | null }) {
  return <div className="source-fact"><small>{label}</small><code className="decimal-raw">{formatDecimal(value).raw ?? '—'}</code></div>
}

export function MetricObservationPanel({
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
  const [metric, setMetric] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [result, setResult] = useState<MetricReadResponse | null>(null)
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

  const readObservation = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!metric || !targetDate || phase === 'loading') return

    requestController.current?.abort()
    const controller = new AbortController()
    const epoch = ++requestEpoch.current
    requestController.current = controller
    setResult(null)
    setErrorMessage('')
    setPhase('loading')

    try {
      const response = await metricClient.read(
        { source_id: source.source_id, target_metric: metric, target_date: targetDate },
        { signal: controller.signal },
      )
      if (controller.signal.aborted || requestEpoch.current !== epoch) return
      if (response.source_id !== source.source_id
        || response.provider !== source.provider
        || response.environment !== source.environment
        || response.data_version !== source.data_version) {
        throw new MetricClientError(null, 'invalid_response')
      }
      setResult(response)
      setPhase('idle')
    } catch (error) {
      if (controller.signal.aborted || requestEpoch.current !== epoch) return
      setErrorMessage(safeReadError(error))
      setPhase('error')
    } finally {
      if (requestEpoch.current === epoch) requestController.current = null
    }
  }

  const observationStatus = result?.observation?.status
  const statusCopy = observationStatus ? STATUS_COPY[observationStatus] : null

  return <section className="surface-card metric-observation-panel" aria-labelledby="metric-read-heading">
    <div className="section-header"><div><h2 id="metric-read-heading">读取指标变化</h2><p>读取所选来源单日值并与前 7 天基线比较；此操作不会启动调查。</p></div></div>
    <form className="metric-read-form" onSubmit={(event) => { void readObservation(event) }}>
      <label className="field"><span>目标指标</span><select data-testid="metric-read-select" value={metric} onChange={(event) => { clearCurrent(); setMetric(event.target.value) }} required disabled={supportedMetrics.length === 0}>
        <option value="" disabled>选择支持读取的指标</option>
        {supportedMetrics.map((item) => <option key={item.metric_id} value={item.metric_id}>{item.metric_id}</option>)}
      </select><small>仅显示当前来源标记为支持的指标。</small></label>
      <label className="field"><span>目标日期</span><input data-testid="metric-read-date" type="date" value={targetDate} onChange={(event) => { clearCurrent(); setTargetDate(event.target.value) }} required /><small>请明确选择要读取的日期。</small></label>
      <button data-testid="metric-read-submit" className="button button-primary metric-read-submit" type="submit" disabled={!metric || !targetDate || phase === 'loading'}>{phase === 'loading' ? <><span className="spinner spinner-light" /> 正在读取…</> : '读取指标'}</button>
    </form>
    <p className="quiet-note metric-read-boundary">这是只读查询，不运行 Agent、不保存调查证据。查询完成时间不代表上游数据更新时间；数据版本是标签，不是不可变快照。</p>

    {phase === 'loading' && <div className="metric-read-state" role="status" aria-live="polite"><span className="spinner" />正在读取所选指标…</div>}
    {phase === 'error' && <div className="inline-error" role="alert"><span className="error-mark" aria-hidden="true">!</span><span>{errorMessage}</span></div>}
    {!result && phase === 'idle' && <div className="metric-read-state" role="status">选择指标和日期后读取一次实际查询结果。</div>}
    {result && <div data-testid="metric-read-result" className="metric-read-result" aria-live="polite">
      {result.observation ? <>
        <div className={`metric-read-status metric-read-${result.observation.status}`}><strong>{statusCopy?.label ?? '指标状态不确定'}</strong><span>{statusCopy?.detail ?? '请结合数据明细谨慎判断。'}</span>{result.anomaly_candidate === true && <small>系统标记为异常候选，不代表已完成原因诊断。</small>}{result.anomaly_candidate === false && <small>当前数据未被标记为异常候选。</small>}{result.anomaly_candidate === null && <small>现有数据无法判断是否为异常候选。</small>}</div>
        <div className="observation-values metric-read-values">
          <ReadDecimal label="所选日期" value={result.observation.current_value} />
          <ReadDecimal label="前 7 天基线" value={result.observation.baseline_value} />
          <ReadDecimal label="相对变化原始比率" value={result.observation.relative_change} />
        </div>
        <p className="metric-read-unit">指标单位：{result.observation.unit || '来源未提供'}</p>
      </> : <div className="metric-read-status metric-read-insufficient"><strong>没有可展示的观察值</strong><span>查询未返回指标 Observation；不能将缺失数据视为 0 或正常。</span></div>}
      {result.observation && <div className="metric-read-periods">
        <span>当前区间：{result.observation.current_period_start} 至 {result.observation.current_period_end}</span>
        <span>基线区间：{result.observation.baseline_period_start} 至 {result.observation.baseline_period_end}</span>
      </div>}
      <button data-testid="metric-read-handoff" className="button button-secondary metric-read-handoff" type="button" disabled={handoffDisabled} onClick={() => onHandoff(result)}>带入调查</button>
      {handoffDisabled && <small className="metric-read-handoff-note">当前有调查任务正在提交，提交完成后可带入本次结果。</small>}
      <details className="metric-read-details"><summary>来源、查询时间与原始引用</summary><div className="metric-read-meta">
        <span>来源：{providerLabel(result.provider)} · {environmentLabel(result.environment)}</span>
        <span>来源 ID：{result.source_id}</span>
        <span>数据版本标签：{result.data_version}</span>
        <span>范围：当前来源总体 · 对比前 7 天</span>
        <span>查询完成时间：{formatTime(result.queried_at)}（不是上游更新时间）</span>
        <span>结果未持久保存为调查证据</span>
      </div><code className="metric-read-query-ref">Query reference：{result.query_reference}</code></details>
      {result.observation && <details className="metric-read-details"><summary>Observation 原始数据</summary><div className="metric-read-meta"><span>来源状态原值：{result.observation.source_status}</span><span>样本量与其余指标值保留原始十进制字符串。</span></div><div className="decimal-raw-list"><RawReadDecimal label="当前值原始值" value={result.observation.current_value} /><RawReadDecimal label="基线值原始值" value={result.observation.baseline_value} /><RawReadDecimal label="相对变化原始比率" value={result.observation.relative_change} /><RawReadDecimal label="样本量原始值" value={result.observation.sample_size} /></div></details>}
      {(result.observation?.status === 'insufficient_evidence' || result.observation?.status === 'inconclusive' || result.observation === null) && <p className="metric-read-uncertain">当前结果不确定。带入调查只会填写指标和日期，不会自动启动任务。</p>}
    </div>}
  </section>
}
