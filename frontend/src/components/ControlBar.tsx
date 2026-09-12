import type { ScenarioItem } from '../types'

interface ControlBarProps {
  scenarios: ScenarioItem[]
  selectedScenario: string
  onSelectScenario: (scenarioId: string) => void
  onInjectScenario: () => void
  onRunInvestigation: () => void
  isInjecting: boolean
  isInvestigating: boolean
  isMockMode: boolean
  onToggleMockMode: (val: boolean) => void
}

export const ControlBar: React.FC<ControlBarProps> = ({
  scenarios,
  selectedScenario,
  onSelectScenario,
  onInjectScenario,
  onRunInvestigation,
  isInjecting,
  isInvestigating,
  isMockMode,
  onToggleMockMode,
}) => {
  const modeLabel = isMockMode
    ? 'Fixture Preview（固定夹具预览·不调用模型）'
    : 'Live Agent Investigation'
  const runActionLabel = isMockMode
    ? '运行固定夹具预览'
    : '发起 Agent Investigation'

  return (
    <div className="control-bar">
      <div className="controls-left">
        <div className="control-group">
          <label className="control-label">Benchmark 演示场景</label>
          <select
            className="scenario-select"
            value={selectedScenario}
            onChange={(e) => onSelectScenario(e.target.value)}
            disabled={isInjecting || isInvestigating}
          >
            {scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label className="control-label">分析目标与基准</label>
          <div className="meta-chip">
            <span>Target:</span>
            <span className="meta-highlight">sales</span>
            <span>|</span>
            <span>Date:</span>
            <span className="meta-highlight">2026-01-31</span>
            <span>vs</span>
            <span>7d Baseline</span>
          </div>
        </div>
      </div>

      <div className="controls-right">
        <label className="mode-toggle" title="Fixture Preview 使用固定夹具，不调用模型；Live Agent Investigation 执行真实模型调查">
          <input
            type="checkbox"
            checked={isMockMode}
            onChange={(e) => onToggleMockMode(e.target.checked)}
          />
          <span>{modeLabel}</span>
        </label>

        <button
          className="btn btn-secondary"
          onClick={onInjectScenario}
          disabled={isInjecting || isInvestigating}
        >
          {isInjecting ? (
            <>
              <div className="loading-spinner" />
              <span>注入中...</span>
            </>
          ) : (
            <>
              <span>💉</span>
              <span>注入场景数据</span>
            </>
          )}
        </button>

        <button
          className="btn btn-primary"
          onClick={onRunInvestigation}
          disabled={isInvestigating}
        >
          {isInvestigating ? (
            <>
              <div className="loading-spinner" />
              <span>{isMockMode ? '固定夹具预览运行中...' : 'Agent Investigation 运行中...'}</span>
            </>
          ) : (
            <>
              <span>⚡</span>
              <span>{runActionLabel}</span>
            </>
          )}
        </button>
      </div>
    </div>
  )
}
