import React from 'react'

interface HeaderProps {
  isBackendOnline: boolean | null
  apiVersion: string
}

export const Header: React.FC<HeaderProps> = ({ isBackendOnline, apiVersion }) => {
  return (
    <header className="top-header">
      <div className="brand-section">
        <div className="brand-icon">🔍</div>
        <div>
          <div className="brand-title">
            <span>MetricSleuth</span>
            <span className="brand-badge">Stage 1 MVP</span>
          </div>
          <div className="brand-subtitle">
            Evidence-driven Business Metric Investigation Workspace
          </div>
        </div>
      </div>

      <div className="header-status">
        <div className="status-indicator">
          <span
            className={`status-dot ${
              isBackendOnline === true
                ? 'online'
                : isBackendOnline === false
                ? 'offline'
                : ''
            }`}
          />
          <span>
            {isBackendOnline === true
              ? `FastAPI ${apiVersion} (Connected)`
              : isBackendOnline === false
              ? 'Backend Offline'
              : 'Connecting...'}
          </span>
        </div>
      </div>
    </header>
  )
}
