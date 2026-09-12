import React from 'react'
import type { InvestigationResponse } from '../types'

interface StructuredDiagnosisCardProps {
  investigation: InvestigationResponse | null
  mode?: InvestigationResponse['mode']
}

export const StructuredDiagnosisCard: React.FC<StructuredDiagnosisCardProps> = ({
  investigation,
  mode,
}) => {
  const isLive = (investigation?.mode ?? mode) === 'live'
  const runActionLabel = isLive ? '发起 Agent Investigation' : '运行固定夹具预览'

  if (!investigation) {
    return (
      <div className="workspace-card">
        <div className="card-header">
          <div className="card-title-group">
            <span className="card-icon">📋</span>
            <h2 className="card-title">Structured Diagnosis (结构化诊断报告)</h2>
          </div>
          <span className="card-badge">Standby</span>
        </div>
        <div className="empty-state">
          <div className="empty-icon">📊</div>
          <div>
            请点击上方<strong>「{runActionLabel}」</strong>
            {isLive
              ? '以触发真实 Agent Investigation 并生成诊断结论'
              : '以查看固定夹具诊断结果（不调用模型）'}
          </div>
        </div>
      </div>
    )
  }

  const { diagnosis, budget } = investigation
  const isAnomalous = diagnosis.status === 'diagnosed'
  const isNormal = diagnosis.status === 'no_material_anomaly'

  const statusClass = isAnomalous
    ? 'status-diagnosed'
    : isNormal
    ? 'status-normal'
    : 'status-inconclusive'

  const statusLabel = isAnomalous
    ? '🚨 Anomalous: Diagnosed'
    : isNormal
    ? '✅ Normal: No Material Anomaly'
    : `⚠️ Status: ${diagnosis.status}`

  const targetChangePercent =
    diagnosis.change?.relative_change !== null && diagnosis.change?.relative_change !== undefined
      ? (diagnosis.change.relative_change * 100).toFixed(2)
      : null

  const confidencePercent =
    diagnosis.confidence !== null && diagnosis.confidence !== undefined
      ? (diagnosis.confidence * 100).toFixed(0)
      : null

  const scopeEntries = Object.entries(diagnosis.affected_scope)
  const modeLabel = isLive
    ? 'Agent Investigation'
    : 'Fixture Preview（固定夹具预览·不调用模型）'
  const runLabel = isLive ? 'Agent Investigation Run' : 'Fixture Preview Run'
  const budgetLabel = isLive ? 'Investigation Budget Usage' : 'Fixture Run Budget Usage'

  return (
    <div className="workspace-card">
      <div className="card-header">
        <div className="card-title-group">
          <span className="card-icon">📋</span>
          <h2 className="card-title">Structured Diagnosis (结构化诊断报告)</h2>
        </div>
        <span className="card-badge">{diagnosis.diagnosis_id}</span>
      </div>

      {/* Hero Badge */}
      <div className="diagnosis-hero">
          <div>
            <span className={`diagnosis-status-badge ${statusClass}`}>
              {statusLabel}
            </span>
            <div style={{ marginTop: 6, fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            {runLabel}: <code style={{ fontFamily: 'var(--font-mono)' }}>{investigation.request_id}</code> ({modeLabel})
            </div>
          </div>

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.72rem', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
            {budgetLabel}
            </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.92rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
            {budget.tool_calls_count}/{budget.max_tool_calls} Tools · {budget.turns_count}/{budget.max_turns} Turns
          </div>
        </div>
      </div>

      {/* Key Stats Grid */}
      <div className="diagnosis-metrics-grid">
        {/* Box 1: Target Metric Change */}
        <div className="summary-stat-box">
          <span className="stat-label">Target Metric Change</span>
          <span
            className="stat-value"
            style={{
              color:
                targetChangePercent && Number(targetChangePercent) < 0
                  ? 'var(--accent-crimson)'
                  : 'var(--primary-green)',
            }}
          >
            {targetChangePercent !== null ? `${targetChangePercent}%` : 'N/A'}
          </span>
          <span className="stat-sub">
            {diagnosis.change?.current_value !== null && diagnosis.change?.baseline_value !== null
              ? `$${diagnosis.change?.current_value?.toLocaleString()} vs $${diagnosis.change?.baseline_value?.toLocaleString()} base`
              : 'Target within baseline bounds'}
          </span>
        </div>

        {/* Box 2: Primary Data Driver */}
        <div className="summary-stat-box">
          <span className="stat-label">Primary Driver (驱动因子)</span>
          <span className="stat-value" style={{ color: isAnomalous ? '#f87171' : 'var(--text-primary)' }}>
            {diagnosis.primary_driver ? diagnosis.primary_driver : 'None (No Driver)'}
          </span>
          <span className="stat-sub">
            {isAnomalous ? 'Isolated data driver contributor' : 'All related metrics within tolerance'}
          </span>
        </div>

        {/* Box 3: Affected Scope */}
        <div className="summary-stat-box">
          <span className="stat-label">Affected Scope (受影响细分)</span>
          {scopeEntries.length > 0 ? (
            <div className="scope-chips-container">
              {scopeEntries.map(([dim, val]) => (
                <span key={dim} className="scope-chip">
                  {dim}: <strong>{val}</strong>
                </span>
              ))}
            </div>
          ) : (
            <span className="stat-sub" style={{ marginTop: 6 }}>
              Global / Unsegmented
            </span>
          )}
        </div>

        {/* Box 4: Confidence Score */}
        <div className="summary-stat-box">
          <span className="stat-label">Confidence Score (置信度)</span>
          <span className="stat-value" style={{ color: 'var(--primary-green)' }}>
            {confidencePercent ? `${confidencePercent}%` : 'High'}
          </span>
          <span className="stat-sub">Evidence-backed consistency score</span>
        </div>
      </div>

      {/* Limitations Banner */}
      <div className="limitations-banner">
        <span style={{ fontSize: '1.2rem' }}>⚠️</span>
        <div>
          <strong>Causal Boundary (因果隔离与局限性边界说明): </strong>
          {diagnosis.limitations.length > 0
            ? diagnosis.limitations.join('; ')
            : 'Locates data-level anomaly contribution; does not prove external business root cause.'}
        </div>
      </div>
    </div>
  )
}
