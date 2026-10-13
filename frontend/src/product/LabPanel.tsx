import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createLabClient, LabClientError } from '../lab/client'
import type { LabCatalog, LabExperiment, ScenarioId } from '../lab/client'
import { createMetricClient, MetricClientError } from '../metrics/client'
import type { MetricScanResponse } from '../metrics/contracts'
import { formatDecimal } from './formatDecimal'

const lab = createLabClient()
const metrics = createMetricClient()
const PAGE_SIZE = 20
const labels = { queued: '等待发布', publishing: '正在发布', published: '数据已发布', failed: '发布失败' }
const errorCopy: Record<string, string> = {
  lab_service_unavailable: '当前环境尚未配置实验服务。请联系维护者，或稍后重新读取。',
  lab_storage_unavailable: '实验记录暂时无法读取或保存，请手动刷新确认状态。',
  lab_target_unavailable: '这个实验空间已使用。请读取已有记录，或选择空闲空间。',
  lab_target_not_found: '所选实验空间已不可用，请重新读取列表。',
  lab_experiment_not_found: '未找到这条实验记录，请重新读取历史。',
  lab_idempotency_conflict: '这次提交与已有实验不一致，请重新选择实验空间。',
  lab_investigation_conflict: '这个实验已有另一项调查，请查看已关联的任务。',
  lab_not_published: '请等待实验数据发布完成后再启动调查。',
  invalid_lab_request: '请求不符合当前实验范围，请检查所选空间和场景。',
  invalid_response: '服务返回的实验信息无法验证，请重新读取。',
  network_error: '连接中断。实验可能已经保存，请先刷新历史确认状态。',
  metric_query_unavailable: '指标暂时无法读取，请稍后重试。',
}
function message(error: unknown): string {
  const code = error instanceof LabClientError || error instanceof MetricClientError ? error.code : ''
  return errorCopy[code] ?? '操作未完成，请重新读取记录后再试。'
}
function number(value: string | number | null | undefined) {
  const formatted = formatDecimal(value ?? null)
  return (formatted.approximate ? '≈' : '') + formatted.display
}
function time(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }

interface Props {
  onOpen: (record: LabExperiment, runId: string, signal?: AbortSignal) => Promise<void>
}
export function LabPanel({ onOpen }: Props) {
  const [catalog, setCatalog] = useState<LabCatalog | null>(null)
  const [items, setItems] = useState<LabExperiment[]>([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [selectedSource, setSelectedSource] = useState('')
  const [scenario, setScenario] = useState<ScenarioId>('no_anomaly')
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<LabExperiment | null>(null)
  const [detailError, setDetailError] = useState('')
  const [detailReload, setDetailReload] = useState(0)
  const [retryableSource, setRetryableSource] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [starting, setStarting] = useState(false)
  const [reading, setReading] = useState(false)
  const [scan, setScan] = useState<MetricScanResponse | null>(null)
  const [notice, setNotice] = useState('')
  const loadAbort = useRef<AbortController | null>(null)
  const actionAbort = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const attempt = useRef<{ source_id: string; scenario_id: ScenarioId; idempotency_key: string } | null>(null)
  const available = useMemo(() => catalog?.targets.filter(target => target.state === 'available') ?? [], [catalog])

  const reload = useCallback(async () => {
    loadAbort.current?.abort()
    const controller = new AbortController(); loadAbort.current = controller
    const requestId = ++generation.current
    try {
      const [nextCatalog, history] = await Promise.all([lab.catalog(controller.signal), lab.list(PAGE_SIZE, offset, controller.signal)])
      if (controller.signal.aborted || requestId !== generation.current) return
      setLoadError(''); setCatalog(nextCatalog); setItems(history.items)
      setSelectedSource(current => nextCatalog.targets.some(target => target.source_id === current)
        ? current : nextCatalog.targets.find(target => target.state === 'available')?.source_id ?? '')
      setSelectedId(current => current || history.items[0]?.experiment_id || '')
      setDetailReload(value => value + 1)
    } catch (error) {
      if (!controller.signal.aborted && requestId === generation.current) setLoadError(message(error))
    } finally {
      if (!controller.signal.aborted && requestId === generation.current) setLoading(false)
    }
  }, [offset])
  useEffect(() => {
    const timer = setTimeout(() => { void reload() }, 0)
    return () => { clearTimeout(timer); loadAbort.current?.abort() }
  }, [reload])
  useEffect(() => () => actionAbort.current?.abort(), [])

  useEffect(() => {
    if (!selectedId) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const read = async () => {
      try {
        const record = await lab.detail(selectedId, controller.signal)
        if (controller.signal.aborted) return
        setDetailError(''); setDetail(record)
        if (record.status === 'queued' || record.status === 'publishing') timer = setTimeout(() => { void read() }, 2000)
      } catch (error) { if (!controller.signal.aborted) setDetailError(message(error)) }
    }
    void read()
    return () => { controller.abort(); if (timer) clearTimeout(timer) }
  }, [selectedId, detailReload])

  useEffect(() => {
    if (loadError || !items.some(item => item.status === 'queued' || item.status === 'publishing')) return
    const timer = setTimeout(() => { void reload() }, 2000)
    return () => clearTimeout(timer)
  }, [items, loadError, reload])

  const publish = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedSource || publishing || starting || reading) return
    if (!attempt.current || attempt.current.source_id !== selectedSource || attempt.current.scenario_id !== scenario) {
      attempt.current = { source_id: selectedSource, scenario_id: scenario, idempotency_key: crypto.randomUUID() }
    }
    const controller = new AbortController(); actionAbort.current?.abort(); actionAbort.current = controller
    setPublishing(true); setActionError(''); setNotice('')
    try {
      const record = await lab.publish(attempt.current, controller.signal)
      if (controller.signal.aborted) return
      attempt.current = null; setRetryableSource('')
      setSelectedId(record.experiment_id); setDetail(record); setScan(null)
      setNotice('实验已保存。下面展示服务端发布状态，完成后可读取指标。')
      void reload()
    } catch (error) {
      if (!controller.signal.aborted) {
        setActionError(message(error))
        setRetryableSource(error instanceof LabClientError && ['network_error','lab_storage_unavailable','request_failed'].includes(error.code) ? selectedSource : '')
      }
    } finally { if (!controller.signal.aborted) setPublishing(false) }
  }
  const readMetrics = async () => {
    if (!detail || detail.status !== 'published') return
    const record = detail
    const controller = new AbortController(); actionAbort.current?.abort(); actionAbort.current = controller
    setReading(true); setActionError(''); setScan(null)
    try {
      const result = await metrics.scan({ source_id: record.source_id, target_date: record.target_date }, { signal: controller.signal })
      if (result.provider !== 'synthetic' || result.environment !== 'sandbox' || result.data_version !== record.data_version) throw new LabClientError('invalid_response')
      if (!controller.signal.aborted) setScan(result)
    } catch (error) { if (!controller.signal.aborted) setActionError(message(error)) }
    finally { if (!controller.signal.aborted) setReading(false) }
  }
  const investigate = async () => {
    if (!detail || starting || reading || publishing) return
    const record = detail
    const controller = new AbortController(); actionAbort.current?.abort(); actionAbort.current = controller
    setStarting(true); setActionError('')
    try {
      const runId = record.investigation_run_id ?? (await lab.investigate(record, controller.signal)).investigation_run_id
      if (controller.signal.aborted) return
      await onOpen(record, runId, controller.signal)
    } catch (error) { if (!controller.signal.aborted) setActionError(message(error)) }
    finally { if (!controller.signal.aborted) { setStarting(false); setDetailReload(value => value + 1) } }
  }
  const selectedTarget = catalog?.targets.find(target => target.source_id === selectedSource)
  const mayPublish = selectedTarget?.state === 'available' || (retryableSource === selectedSource && !!actionError)
  const busy = publishing || starting || reading

  return <div className="lab-page">
    <div className="page-heading"><div><h1>隔离数据实验室</h1><p>选择场景发布实验数据，再读取指标并启动调查。实验数据与真实来源分开，记录由服务端保存。</p></div></div>
    {loadError && <div className="system-state state-error" role="alert"><strong>实验信息读取失败</strong><span>{loadError}</span><button className="button button-secondary" onClick={() => { setLoading(true); setLoadError(''); void reload() }}>重新读取</button></div>}
    {!catalog && loading && <div className="lab-loading" role="status"><span /><span /><span />正在读取实验空间和历史…</div>}
    {catalog && <>
      <section className="surface-card lab-publish" aria-labelledby="lab-publish-heading">
        <div className="section-heading"><div><h2 id="lab-publish-heading">发布一次实验</h2><p>每个空间保留一次发布，已有实验数据不会被覆盖。</p></div><span className="config-tag">Synthetic / Sandbox</span></div>
        {!available.length && !mayPublish && <p className="lab-capacity-note">当前没有空闲实验空间。已有实验仍可读取和调查；请联系维护者添加新空间。</p>}
        <form onSubmit={publish}>
          <div className="form-grid">
            <label className="field"><span>实验空间</span><select data-testid="lab-target" value={selectedSource} onChange={event => { setSelectedSource(event.target.value); attempt.current = null; setRetryableSource(''); setActionError('') }} disabled={busy} required>
              {!selectedSource && <option value="">选择空闲空间</option>}{catalog.targets.map(target => <option key={target.source_id} value={target.source_id} disabled={target.state !== 'available'}>{target.display_name}{target.state !== 'available' ? ' · 已使用' : ''}</option>)}
            </select></label>
            <label className="field"><span>实验场景</span><select data-testid="lab-scenario" value={scenario} onChange={event => { setScenario(event.target.value as ScenarioId); attempt.current = null; setRetryableSource(''); setActionError('') }} disabled={busy}>
              {catalog.scenarios.map(scene => <option key={scene.scenario_id} value={scene.scenario_id}>{scene.title}</option>)}
            </select></label>
            <label className="field"><span>数据日期</span><input type="date" value={catalog.target_date} readOnly /><small>来自当前实验数据配置。</small></label>
          </div>
          <div className="lab-form-actions"><p>{catalog.scenarios.find(scene => scene.scenario_id === scenario)?.description}</p><button data-testid="lab-publish" className="button button-primary" type="submit" disabled={!mayPublish || busy}>{publishing ? '正在提交…' : retryableSource && actionError ? '用原请求重试' : '发布实验数据'}</button></div>
        </form>
      </section>
      {actionError && <p className="inline-error" role="alert">{actionError}</p>}
      {notice && <p className="lab-notice" role="status">{notice}</p>}
      <section className="surface-card lab-history" aria-labelledby="lab-history-heading">
        <div className="section-heading"><div><h2 id="lab-history-heading">实验历史</h2><p>发布状态、数据版本与关联调查。</p></div><button className="button button-secondary" disabled={loading} onClick={() => { setLoading(true); setLoadError(''); void reload(); setDetailReload(value => value + 1) }}>{loading ? '读取中…' : '刷新记录'}</button></div>
        {items.length ? <div className="table-scroll"><table className="lab-history-table"><thead><tr><th>场景</th><th>状态</th><th>日期</th><th>创建时间</th><th><span className="visually-hidden">操作</span></th></tr></thead><tbody>{items.map(record => <tr key={record.experiment_id} className={selectedId === record.experiment_id ? 'is-selected' : ''}>
          <td>{catalog.scenarios.find(scene => scene.scenario_id === record.scenario_id)?.title ?? record.scenario_id}</td><td><span className={`status-pill status-${record.status === 'published' ? 'succeeded' : record.status === 'publishing' ? 'running' : record.status}`}>{labels[record.status]}</span></td><td>{record.target_date}</td><td>{time(record.created_at)}</td><td><button data-testid={`lab-open-${record.experiment_id}`} className="text-button" disabled={busy} onClick={() => { actionAbort.current?.abort(); setReading(false); setActionError(''); setDetailError(''); setSelectedId(record.experiment_id); setDetail(null); setScan(null); setDetailReload(value => value + 1) }}>查看实验</button></td>
        </tr>)}</tbody></table></div> : <div className="empty-state"><strong>还没有实验记录</strong><span>选择上面的空闲空间和场景，发布第一组隔离数据。</span></div>}
        <div className="lab-pagination"><span>每页最多 {PAGE_SIZE} 条，按创建时间倒序</span><div><button className="button button-secondary" disabled={!offset || loading} onClick={() => { setLoading(true); setLoadError(''); setOffset(value => Math.max(0, value - PAGE_SIZE)) }}>上一页</button><button className="button button-secondary" disabled={items.length < PAGE_SIZE || loading} onClick={() => { setLoading(true); setLoadError(''); setOffset(value => value + PAGE_SIZE) }}>下一页</button></div></div>
      </section>
      {detailError && <p className="inline-error" role="alert">{detailError}</p>}
      {selectedId && !detailError && !detail && <div className="system-state" role="status">正在读取实验详情…</div>}
      {detail && <section className="surface-card lab-detail" aria-labelledby="lab-detail-heading" data-testid="lab-detail">
        <div className="section-heading"><div><h2 id="lab-detail-heading">{catalog.scenarios.find(scene => scene.scenario_id === detail.scenario_id)?.title ?? '实验详情'}</h2><p>{labels[detail.status]} · {detail.target_date} · Synthetic / Sandbox</p></div><span className={`status-pill status-${detail.status === 'published' ? 'succeeded' : detail.status === 'publishing' ? 'running' : detail.status}`}>{labels[detail.status]}</span></div>
        {detail.status === 'failed' && <div className="failure-note"><strong>发布未完成</strong><span>安全错误代码：{detail.failure_code}。原有数据不会被覆盖；可选择新的空闲实验空间。</span></div>}
        {(detail.status === 'queued' || detail.status === 'publishing') && <p role="status">正在等候服务端发布结果。这里会自动读取状态，完成后再开启指标和调查操作。</p>}
        <div className="lab-record-meta"><div><small>实验编号</small><code>{detail.experiment_id}</code></div><div><small>来源编号</small><code>{detail.source_id}</code></div><div><small>关联调查</small><code>{detail.investigation_run_id ?? '尚未提交'}</code></div></div>
        {detail.status === 'published' && <>
          <div className="lab-detail-actions"><button data-testid="lab-read-metrics" className="button button-secondary" disabled={busy} onClick={() => void readMetrics()}>{reading ? '正在读取指标…' : '读取实验指标'}</button><button data-testid="lab-investigate" className="button button-primary" disabled={busy} onClick={() => void investigate()}>{starting ? '正在打开…' : detail.investigation_run_id ? '查看关联调查' : '启动 Sales 调查'}</button></div>
          <p className="lab-limits">版本是发布标签，指标读取不是一致快照。调查执行状态和工具证据在调查工作区查看。</p>
          <details className="lab-version"><summary>查看数据版本标签</summary><code>{detail.data_version}</code></details>
        </>}
        {scan && <div className="lab-metric-result"><h3>实际指标读取</h3><p className="lab-limits">本次读取：{time(scan.completed_at)}</p><div className="table-scroll"><table><thead><tr><th>指标</th><th>当前值</th><th>前 7 日基线</th><th>单位</th><th>候选状态</th></tr></thead><tbody>{scan.items.map(item => <tr key={item.target_metric}><th scope="row">{item.target_metric}</th><td>{number(item.observation?.current_value)}</td><td>{number(item.observation?.baseline_value)}</td><td>{item.observation?.unit ?? "—"}</td><td>{item.anomaly_candidate === true ? '异常候选' : item.anomaly_candidate === false ? '未发现材料性异常' : '尚不能判断'}</td></tr>)}</tbody></table></div><details><summary>查看原始数值与查询引用</summary><pre>{JSON.stringify(scan, null, 2)}</pre></details></div>}
      </section>}
    </>}
  </div>
}
