import React, { useState } from 'react'
import type { EvidenceItem, InvestigationResponse } from '../types'

interface EvidencePortfolioProps {
  evidence: EvidenceItem[]
  mode?: InvestigationResponse['mode']
}

export const EvidencePortfolio: React.FC<EvidencePortfolioProps> = ({ evidence, mode }) => {
  const [activeTab, setActiveTab] = useState<'all' | 'supporting' | 'negative_control'>('all')
  const isLive = mode === 'live'
  const emptyDescription = isLive
    ? 'Agent Investigation 完成后将展示支撑、对照及上下文证据组合'
    : 'Fixture Preview 运行后将展示固定夹具提供的支撑与对照证据（不调用模型）'
  const evidenceLabel = isLive
    ? 'Evidence Items'
    : 'Fixture Preview Evidence'

  if (evidence.length === 0) {
    return (
      <div className="workspace-card">
        <div className="card-header">
          <div className="card-title-group">
            <span className="card-icon">🔬</span>
            <h2 className="card-title">Evidence Portfolio (证据链看板)</h2>
          </div>
          <span className="card-badge">0 Items</span>
        </div>
        <div className="empty-state">
          <div className="empty-icon">🗂️</div>
          <div>{emptyDescription}</div>
        </div>
      </div>
    )
  }

  const supportingItems = evidence.filter((e) => e.role === 'supporting')
  const negativeItems = evidence.filter((e) => e.role === 'negative_control')

  const filteredEvidence =
    activeTab === 'supporting'
      ? supportingItems
      : activeTab === 'negative_control'
      ? negativeItems
      : evidence

  return (
    <div className="workspace-card">
      <div className="card-header">
        <div className="card-title-group">
          <span className="card-icon">🔬</span>
          <h2 className="card-title">Evidence Portfolio (证据链看板)</h2>
        </div>
        <span className="card-badge">{evidence.length} {evidenceLabel}</span>
      </div>

      <div className="evidence-tabs">
        <button
          className={`evidence-tab-btn ${activeTab === 'all' ? 'active' : ''}`}
          onClick={() => setActiveTab('all')}
        >
          <span>全部证据</span>
          <span className="evidence-tab-count">{evidence.length}</span>
        </button>
        <button
          className={`evidence-tab-btn ${activeTab === 'supporting' ? 'active' : ''}`}
          onClick={() => setActiveTab('supporting')}
        >
          <span>🚨 支撑证据 (Supporting)</span>
          <span className="evidence-tab-count">{supportingItems.length}</span>
        </button>
        <button
          className={`evidence-tab-btn ${activeTab === 'negative_control' ? 'active' : ''}`}
          onClick={() => setActiveTab('negative_control')}
        >
          <span>🛡️ 排除对照 (Negative Controls)</span>
          <span className="evidence-tab-count">{negativeItems.length}</span>
        </button>
      </div>

      <div className="evidence-grid">
        {filteredEvidence.map((item) => {
          const isSupporting = item.role === 'supporting'
          const roleBadgeClass = isSupporting ? 'role-supporting' : 'role-negative'
          const cardClass = isSupporting ? 'supporting' : 'negative-control'

          const changePercent =
            item.relative_change !== null
              ? (item.relative_change * 100).toFixed(1)
              : null

          const filterEntries = Object.entries(item.filters)

          return (
            <div key={item.evidence_id} className={`evidence-card ${cardClass}`}>
              <div className="evidence-card-header">
                <div>
                  <div className="evidence-metric-name">{item.metric.toUpperCase()}</div>
                  <span className="evidence-id-tag">{item.evidence_id}</span>
                </div>
                <span className={`evidence-role-badge ${roleBadgeClass}`}>
                  {item.role.replace('_', ' ')}
                </span>
              </div>

              <div className="evidence-values-row">
                <div className="val-box">
                  <span className="val-label">Current</span>
                  <span className="val-num">
                    {item.current_value !== null ? item.current_value.toLocaleString() : 'N/A'}
                  </span>
                </div>

                <div className="val-box">
                  <span className="val-label">Baseline</span>
                  <span className="val-num">
                    {item.baseline_value !== null ? item.baseline_value.toLocaleString() : 'N/A'}
                  </span>
                </div>

                <div className="val-box">
                  <span className="val-label">Change</span>
                  <span
                    className="val-num"
                    style={{
                      color:
                        changePercent && Number(changePercent) < 0
                          ? 'var(--accent-crimson)'
                          : changePercent && Number(changePercent) > 0
                          ? 'var(--primary-green)'
                          : 'var(--text-secondary)',
                    }}
                  >
                    {changePercent !== null ? `${changePercent}%` : '0.0%'}
                  </span>
                </div>
              </div>

              {filterEntries.length > 0 && (
                <div className="evidence-filters">
                  {filterEntries.map(([dim, val]) => (
                    <span key={dim} className="filter-chip">
                      {dim}: <strong>{val}</strong>
                    </span>
                  ))}
                </div>
              )}

              {item.sample_size !== null && item.sample_size !== undefined && (
                <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)', marginTop: 'auto' }}>
                  Base sample size: {item.sample_size} sessions
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
