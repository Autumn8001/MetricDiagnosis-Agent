import React, { useEffect, useState } from 'react'
import {
  checkHealth,
  getMetricGraph,
  getScenarios,
  injectScenario,
  runInvestigation,
} from './api'
import type {
  InvestigationResponse,
  MetricGraphNode,
  ScenarioItem,
} from './types'

import { Header } from './components/Header'
import { ControlBar } from './components/ControlBar'
import { MetricGraph } from './components/MetricGraph'
import { StructuredDiagnosisCard } from './components/StructuredDiagnosisCard'
import { InvestigationTimeline } from './components/InvestigationTimeline'
import { EvidencePortfolio } from './components/EvidencePortfolio'
import { ContinueInquiry } from './components/ContinueInquiry'
import { NodeDetailModal } from './components/NodeDetailModal'

// Safe local fallback definitions for metrics and scenarios
const DEFAULT_METRIC_NODES: MetricGraphNode[] = [
  {
    metric_id: 'sales',
    display_name: 'Sales (GMV)',
    description: 'Total revenue generated from order transactions',
    metric_type: 'additive',
    unit: 'usd',
    formula: 'SUM(sales)',
    dependencies: [],
    related_metrics: ['orders', 'sessions', 'conversion_rate', 'aov'],
  },
  {
    metric_id: 'orders',
    display_name: 'Orders',
    description: 'Total count of completed order transactions',
    metric_type: 'additive',
    unit: 'count',
    formula: 'SUM(orders)',
    dependencies: [],
    related_metrics: ['sales', 'sessions', 'conversion_rate', 'aov'],
  },
  {
    metric_id: 'sessions',
    display_name: 'Sessions (Traffic)',
    description: 'Total visitor browsing sessions',
    metric_type: 'additive',
    unit: 'count',
    formula: 'SUM(sessions)',
    dependencies: [],
    related_metrics: ['orders', 'conversion_rate'],
  },
  {
    metric_id: 'conversion_rate',
    display_name: 'Conversion Rate (CR)',
    description: 'Orders per browsing session ratio',
    metric_type: 'ratio',
    unit: 'ratio',
    formula: 'orders / sessions',
    dependencies: ['orders', 'sessions'],
    related_metrics: ['sales', 'aov'],
  },
  {
    metric_id: 'aov',
    display_name: 'Average Order Value (AOV)',
    description: 'Average revenue generated per order',
    metric_type: 'ratio',
    unit: 'usd',
    formula: 'sales / orders',
    dependencies: ['sales', 'orders'],
    related_metrics: ['conversion_rate'],
  },
]

const DEFAULT_SCENARIOS: ScenarioItem[] = [
  {
    scenario_id: 'canonical',
    title: 'Controlled Case 01 / 受控基准场景 01',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'traffic',
    title: 'Controlled Case 02 / 受控基准场景 02',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'no_anomaly',
    title: 'Controlled Case 03 / 受控基准场景 03',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'aov_us_asin_b_organic',
    title: 'Controlled Case 04 / 受控基准场景 04',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'traffic_uk_asin_b_ads',
    title: 'Controlled Case 05 / 受控基准场景 05',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'conversion_de_asin_c_ads',
    title: 'Controlled Case 06 / 受控基准场景 06',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'traffic_us_asin_c_organic',
    title: 'Controlled Case 07 / 受控基准场景 07',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'aov_uk_asin_a_ads',
    title: 'Controlled Case 08 / 受控基准场景 08',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'conversion_us_asin_b_ads',
    title: 'Controlled Case 09 / 受控基准场景 09',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
  {
    scenario_id: 'distractor_minor_fluctuation',
    title: 'Controlled Case 10 / 受控基准场景 10',
    description: 'Controlled benchmark fixture for preview and data injection; expected diagnosis is intentionally hidden.',
    target_metric: 'sales',
  },
]

export const App: React.FC = () => {
  const [isBackendOnline, setIsBackendOnline] = useState<boolean | null>(null)
  const [apiVersion, setApiVersion] = useState<string>('1.0.0')

  const [scenarios, setScenarios] = useState<ScenarioItem[]>(DEFAULT_SCENARIOS)
  const [selectedScenario, setSelectedScenario] = useState<string>('canonical')
  const [metricNodes, setMetricNodes] = useState<MetricGraphNode[]>(DEFAULT_METRIC_NODES)

  const [investigation, setInvestigation] = useState<InvestigationResponse | null>(null)
  const [isInjecting, setIsInjecting] = useState<boolean>(false)
  const [isInvestigating, setIsInvestigating] = useState<boolean>(false)
  const [isMockMode, setIsMockMode] = useState<boolean>(true)

  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)
  const [selectedNode, setSelectedNode] = useState<MetricGraphNode | null>(null)

  const showToast = (message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type })
    setTimeout(() => {
      setToast(null)
    }, 4500)
  }

  // Initial Load: Health check, Graph, Scenarios
  useEffect(() => {
    const initApp = async () => {
      try {
        const health = await checkHealth()
        setIsBackendOnline(true)
        setApiVersion(health.version || '1.0.0')
      } catch {
        setIsBackendOnline(false)
      }

      try {
        const graphRes = await getMetricGraph()
        if (graphRes.nodes && graphRes.nodes.length > 0) {
          setMetricNodes(graphRes.nodes)
        }
      } catch {
        // Fall back to default
      }

      try {
        const scRes = await getScenarios()
        if (scRes.scenarios && scRes.scenarios.length > 0) {
          setScenarios(scRes.scenarios)
        }
      } catch {
        // Fall back to default
      }
    }

    initApp()
  }, [])

  // Auto-run the default Fixture Preview once loaded
  useEffect(() => {
    const autoRun = async () => {
      try {
        const res = await runInvestigation({
          target_metric: 'sales',
          target_date: '2026-01-31',
          baseline_strategy: 'previous_7_days',
          scenario: 'canonical',
          mock_mode: true,
        })
        setInvestigation(res)
      } catch {
        // Standby
      }
    }
    autoRun()
  }, [])

  // Inject Scenario
  const handleInjectScenario = async () => {
    setIsInjecting(true)
    try {
      const res = await injectScenario(selectedScenario)
      const injectionMode =
        res.mode === 'dry_run'
          ? 'Dry Run / 仅校验场景（未写入数据库）'
          : 'Live Warehouse'
      showToast(`场景注入成功 [${injectionMode}]: ${res.message}`, 'success')
    } catch (err: any) {
      showToast(`场景注入失败: ${err.message}`, 'error')
    } finally {
      setIsInjecting(false)
    }
  }

  // Run Investigation
  const handleRunInvestigation = async (customPrompt?: string) => {
    setIsInvestigating(true)
    try {
      const res = await runInvestigation({
        target_metric: 'sales',
        target_date: '2026-01-31',
        baseline_strategy: 'previous_7_days',
        scenario: selectedScenario,
        mock_mode: isMockMode,
        prompt: customPrompt,
      })
      setInvestigation(res)
      if (res.mode !== 'live') {
        showToast(
          'Fixture Preview 已加载：仅用于 UI 示意，不代表所选场景结果或 Agent 调查。',
          'success'
        )
        return
      }
      const isDiag = res.diagnosis.status === 'diagnosed'
      showToast(
        isDiag
          ? `Agent Investigation 完成：识别主驱动指标「${res.diagnosis.primary_driver}」，定位至受影响维度。`
          : 'Agent Investigation 完成：目标指标在公差范围内正常波动（无实质性异常）。',
        'success'
      )
    } catch (err: any) {
      showToast(`调查执行失败: ${err.message}`, 'error')
    } finally {
      setIsInvestigating(false)
    }
  }

  const handleScenarioChange = (scenarioId: string) => {
    setSelectedScenario(scenarioId)
    // Clear old investigation and trigger fresh investigation
    setInvestigation(null)
  }

  return (
    <div className="app-container">
      {/* 1. Header */}
      <Header isBackendOnline={isBackendOnline} apiVersion={apiVersion} />

      {/* Toast Notification */}
      {toast && (
        <div className={`toast-bar ${toast.type === 'success' ? 'toast-success' : 'toast-error'}`}>
          <span>{toast.message}</span>
          <button
            onClick={() => setToast(null)}
            style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}
          >
            ✕
          </button>
        </div>
      )}

      {/* 2. Control Bar */}
      <ControlBar
        scenarios={scenarios}
        selectedScenario={selectedScenario}
        onSelectScenario={handleScenarioChange}
        onInjectScenario={handleInjectScenario}
        onRunInvestigation={() => handleRunInvestigation()}
        isInjecting={isInjecting}
        isInvestigating={isInvestigating}
        isMockMode={isMockMode}
        onToggleMockMode={setIsMockMode}
      />

      {/* 3. Main Workspace Grid */}
      <div className="workspace-grid">
        {/* Top Left: Metric Dependency Graph */}
        <MetricGraph
          nodes={metricNodes}
          investigation={investigation}
          onSelectNode={(node) => setSelectedNode(node)}
        />

        {/* Top Right: Structured Diagnosis Report */}
        <StructuredDiagnosisCard
          investigation={investigation}
          mode={investigation?.mode ?? (isMockMode ? 'mock' : 'live')}
        />

        {/* Bottom Left: Investigation Steps / Trajectory */}
        <InvestigationTimeline
          trace={investigation?.investigation_trace || []}
          mode={investigation?.mode ?? (isMockMode ? 'mock' : 'live')}
        />

        {/* Bottom Right: Evidence Portfolio */}
        <EvidencePortfolio
          evidence={investigation?.evidence || []}
          mode={investigation?.mode ?? (isMockMode ? 'mock' : 'live')}
        />

        {/* Full Width: Continue Investigation Inquiry */}
        <ContinueInquiry
          onSendInquiry={(prompt) => handleRunInvestigation(prompt)}
          disabled={isInvestigating}
        />
      </div>

      {/* Metric Detail Modal */}
      <NodeDetailModal node={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  )
}

export default App
