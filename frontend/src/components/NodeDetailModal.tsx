import React from 'react'
import type { MetricGraphNode } from '../types'

interface NodeDetailModalProps {
  node: MetricGraphNode | null
  onClose: () => void
}

export const NodeDetailModal: React.FC<NodeDetailModalProps> = ({ node, onClose }) => {
  if (!node) return null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '1.5rem' }}>📊</span>
            <div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                {node.display_name}
              </h3>
              <div style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                ID: {node.metric_id} · Unit: {node.unit} · Type: {node.metric_type}
              </div>
            </div>
          </div>
          <button className="modal-close" onClick={onClose} title="关闭">
            ✕
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: '0.88rem' }}>
          <div>
            <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
              业务描述
            </div>
            <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>{node.description}</div>
          </div>

          <div>
            <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
              计算公式 (Formula)
            </div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                background: 'var(--bg-canvas)',
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid var(--border-subtle)',
                color: 'var(--primary-green)',
                marginTop: 4,
              }}
            >
              {node.formula}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
              直接依赖指标 (Dependencies)
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
              {node.dependencies.length > 0 ? (
                node.dependencies.map((dep) => (
                  <span
                    key={dep}
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.75rem',
                      background: 'var(--bg-surface)',
                      padding: '2px 8px',
                      borderRadius: 4,
                      border: '1px solid var(--border-subtle)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {dep}
                  </span>
                ))
              ) : (
                <span style={{ color: 'var(--text-dim)', fontSize: '0.8rem' }}>无（根指标）</span>
              )}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
              关联指标 (Related Metrics)
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
              {node.related_metrics.map((rel) => (
                <span
                  key={rel}
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.75rem',
                    background: 'var(--bg-surface)',
                    padding: '2px 8px',
                    borderRadius: 4,
                    border: '1px solid var(--border-subtle)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  {rel}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="btn btn-secondary" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
