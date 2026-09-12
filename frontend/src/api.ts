/**
 * API client for communicating with the MetricSleuth FastAPI backend.
 */

import type {
  HealthResponse,
  InjectScenarioResponse,
  InvestigationRequest,
  InvestigationResponse,
  MetricGraphResponse,
  ScenarioListResponse,
} from './types'

const API_BASE = ''

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = res.statusText
    try {
      const errJson = await res.json()
      if (errJson && errJson.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail)
      }
    } catch {
      // ignore
    }
    throw new Error(`HTTP ${res.status}: ${errorDetail}`)
  }
  return res.json()
}

export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`)
  return handleResponse<HealthResponse>(res)
}

export async function getMetricGraph(): Promise<MetricGraphResponse> {
  const res = await fetch(`${API_BASE}/api/metrics/graph`)
  return handleResponse<MetricGraphResponse>(res)
}

export async function getScenarios(): Promise<ScenarioListResponse> {
  const res = await fetch(`${API_BASE}/api/scenarios`)
  return handleResponse<ScenarioListResponse>(res)
}

export async function injectScenario(scenario: string): Promise<InjectScenarioResponse> {
  const res = await fetch(`${API_BASE}/api/scenarios/inject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario }),
  })
  return handleResponse<InjectScenarioResponse>(res)
}

export async function runInvestigation(
  req: InvestigationRequest
): Promise<InvestigationResponse> {
  const res = await fetch(`${API_BASE}/api/investigate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  return handleResponse<InvestigationResponse>(res)
}
