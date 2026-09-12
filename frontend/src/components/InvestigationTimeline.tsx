import React, { useState } from 'react'
import type { InvestigationResponse, TraceStepItem } from '../types'

interface InvestigationTimelineProps {
  trace: TraceStepItem[]
  mode?: InvestigationResponse['mode']
}

export const InvestigationTimeline: React.FC<InvestigationTimelineProps> = ({ trace, mode }) => {
  const [expandedStep, setExpandedStep] = useState<number | null>(null)
  const isLive = mode === 'live'
  const title = isLive
    ? 'Investigation Trajectory (Agent Investigation 调查路径与动作轨迹)'
    : 'Fixture Preview Trace (固定夹具预览轨迹)'
  const emptyDescription = isLive
    ? 'Agent Investigation 路径将在排查执行后动态生成，呈现逐步工具调用与调查决策'
    : '固定夹具预览轨迹将在运行后展示（不调用模型）'
  const stepLabel = isLive ? 'Agent Trace Steps' : 'Fixture Trace Steps'

  if (trace.length === 0) {
    return (
      <div className="workspace-card">
        <div className="card-header">
          <div className="card-title-group">
            <span className="card-icon">🧭</span>
            <h2 className="card-title">{title}</h2>
          </div>
          <span className="card-badge">0 Steps</span>
        </div>
        <div className="empty-state">
          <div className="empty-icon">🛰️</div>
          <div>{emptyDescription}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="workspace-card">
      <div className="card-header">
        <div className="card-title-group">
          <span className="card-icon">🧭</span>
          <h2 className="card-title">{title}</h2>
        </div>
        <span className="card-badge">{trace.length} {stepLabel}</span>
      </div>

      <div className="timeline-container">
        {trace.map((step) => {
          const isExpanded = expandedStep === step.step_number
          const relChange = step.relative_change
          const hasDim = Object.keys(step.dimensions).length > 0

          return (
            <div key={step.step_number} className="timeline-step-card">
              <div className={`step-marker ${step.step_number === trace.length ? 'active' : ''}`}>
                {step.step_number}
              </div>

              <div className="step-content">
                <div className="step-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="step-tool-name">{step.tool_name}()</span>
                    {hasDim && (
                      <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        Drill-down: <strong style={{ color: 'var(--text-secondary)' }}>
                          {Object.entries(step.dimensions)
                            .map(([k, v]) => `${k}=${v}`)
                            .join(', ')}
                        </strong>
                      </span>
                    )}
                  </div>

                  {relChange !== null && relChange !== undefined && (
                    <span
                      className={`step-diff-pill ${
                        relChange < -0.05
                          ? 'diff-negative'
                          : 'diff-neutral'
                      }`}
                    >
                      {relChange > 0
                        ? `+${(relChange * 100).toFixed(1)}%`
                        : `${(relChange * 100).toFixed(1)}%`}
                    </span>
                  )}
                </div>

                <div className="step-summary">
                  {step.summary || `Executed ${step.tool_name} for ${step.metric || 'target'}`}
                </div>

                <div>
                  <span
                    className="step-details-toggle"
                    onClick={() => setExpandedStep(isExpanded ? null : step.step_number)}
                  >
                    {isExpanded ? 'Hide Raw Details ▲' : 'View Tool Call Details ▼'}
                  </span>

                  {isExpanded && (
                    <div className="step-raw-box">
                      <div>// Tool Call ID: {step.tool_call_id}</div>
                      <div>// Observation ID: {step.observation_id || 'N/A'}</div>
                      {step.arguments && (
                        <div style={{ marginTop: 4 }}>
                          Arguments: {JSON.stringify(step.arguments, null, 2)}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
