import React from 'react'
import type { InvestigationResponse, MetricGraphNode } from '../types'

interface MetricGraphProps {
  nodes: MetricGraphNode[]
  investigation: InvestigationResponse | null
  onSelectNode: (node: MetricGraphNode) => void
}

export const MetricGraph: React.FC<MetricGraphProps> = ({
  nodes,
  investigation,
  onSelectNode,
}) => {
  const nodeMap = new Map(nodes.map((n) => [n.metric_id, n]))

  // Helper to extract node change from investigation evidence or diagnosis
  const getNodeChange = (metricId: string): number | null => {
    if (!investigation) return null
    if (investigation.target_metric === metricId && investigation.diagnosis.change) {
      return investigation.diagnosis.change.relative_change
    }
    const ev = investigation.evidence.find((e) => e.metric === metricId)
    return ev?.relative_change ?? null
  }

  const getNodeClass = (metricId: string): string => {
    if (!investigation) return ''
    if (metricId === investigation.diagnosis.primary_driver) {
      return 'driver'
    }
    if (metricId === investigation.target_metric) {
      return 'target'
    }
    return 'stable'
  }

  const renderNode = (metricId: string) => {
    const node = nodeMap.get(metricId)
    if (!node) return null

    const change = getNodeChange(metricId)
    const nodeClass = getNodeClass(metricId)
    const isDriver = investigation?.diagnosis.primary_driver === metricId
    const isTarget = investigation?.target_metric === metricId

    return (
      <div
        className={`metric-node ${nodeClass}`}
        onClick={() => onSelectNode(node)}
        title="点击查看指标详细公式与语义定义"
      >
        <div className="metric-node-header">
          <span className="metric-node-name">{node.display_name}</span>
          <span className="metric-node-tag">{node.unit}</span>
        </div>

        <div className="metric-node-formula">{node.formula}</div>

        {change !== null ? (
          <div
            className="metric-node-change"
            style={{
              color:
                change < -0.05
                  ? 'var(--accent-crimson)'
                  : change > 0.05
                  ? 'var(--primary-green)'
                  : 'var(--text-secondary)',
            }}
          >
            {isDriver && <span style={{ marginRight: 4 }}>🚨 Driver:</span>}
            {isTarget && !isDriver && <span style={{ marginRight: 4 }}>🎯 Target:</span>}
            {change > 0 ? `+${(change * 100).toFixed(1)}%` : `${(change * 100).toFixed(1)}%`}
          </div>
        ) : (
          <div className="metric-node-change" style={{ color: 'var(--text-dim)', fontSize: '0.75rem' }}>
            {investigation ? 'Normal / Stable' : 'Ready'}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="workspace-card">
      <div className="card-header">
        <div className="card-title-group">
          <span className="card-icon">🌲</span>
          <h2 className="card-title">Metric Dependency Graph (指标拓扑与因果拆解)</h2>
        </div>
        <span className="card-badge">
          {nodes.length > 0 ? `${nodes.length} Core Metrics` : 'Loading...'}
        </span>
      </div>

      <div className="metric-graph-container">
        {/* Level 1: Sales */}
        <div className="graph-level">{renderNode('sales')}</div>

        <div className="graph-connector-line">
          <span>Decomposes to: Orders × AOV</span>
        </div>

        {/* Level 2: Orders and AOV */}
        <div className="graph-level">
          {renderNode('orders')}
          {renderNode('aov')}
        </div>

        <div className="graph-connector-line">
          <span>Orders decomposes to: Sessions × Conversion Rate</span>
        </div>

        {/* Level 3: Sessions and Conversion Rate */}
        <div className="graph-level">
          {renderNode('sessions')}
          {renderNode('conversion_rate')}
        </div>
      </div>
    </div>
  )
}
