import React, { useState } from 'react'

interface ContinueInquiryProps {
  onSendInquiry: (prompt: string) => void
  disabled: boolean
}

export const ContinueInquiry: React.FC<ContinueInquiryProps> = ({
  onSendInquiry,
  disabled,
}) => {
  const [inquiryText, setInquiryText] = useState('')

  const suggestions = [
    '比较 sales 与 orders 在 marketplace=US 下的变化',
    '下钻 sessions 到 asin=ASIN-A、traffic_source=Ads',
    '对比 conversion_rate 与 aov 在 marketplace=US / asin=ASIN-A 的表现',
    '按 marketplace、asin、traffic_source 检查 orders 的分布',
  ]

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!inquiryText.trim() || disabled) return
    onSendInquiry(inquiryText.trim())
    setInquiryText('')
  }

  return (
    <div className="workspace-card full-width-section">
      <div className="card-header">
        <div className="card-title-group">
          <span className="card-icon">💬</span>
          <h2 className="card-title">New Follow-up Investigation (发起新的追问调查)</h2>
        </div>
        <span className="card-badge">Human-in-the-Loop</span>
      </div>

      <div className="inquiry-section">
        <div className="inquiry-disclaimer">
          每次发送都会启动独立 run；不会继承上一轮会话或历史状态。
        </div>
        <div className="quick-prompts">
          <span className="quick-prompt-label">快捷建议:</span>
          {suggestions.map((s, idx) => (
            <button
              key={idx}
              className="quick-prompt-btn"
              onClick={() => onSendInquiry(s)}
              disabled={disabled}
            >
              {s}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="prompt-input-row">
          <input
            type="text"
            className="prompt-input"
            placeholder="输入新的自然语言调查，例如：比较 asin=ASIN-A 在不同 traffic_source 下的 conversion_rate..."
            value={inquiryText}
            onChange={(e) => setInquiryText(e.target.value)}
            disabled={disabled}
          />
          <button type="submit" className="btn btn-primary" disabled={disabled || !inquiryText.trim()}>
            <span>🚀</span>
            <span>发起新的追问调查</span>
          </button>
        </form>
      </div>
    </div>
  )
}
