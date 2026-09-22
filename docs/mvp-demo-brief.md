# MetricSleuth Stage 1 MVP Demo & Acceptance Brief

> Status: current implementation reference · Snapshot: 2026-09-22 · Code baseline: `main` at `3884600`

## 1. Purpose and scope

This brief is the short, factual guide for demonstrating the current MetricSleuth MVP to an interviewer, collaborator, or a future implementation agent. It describes the **Stage 1 Amazon / e-commerce profile only**. It does not claim production deployment, multi-domain support, real-world root-cause proof, or an Operations Action Plan.

The repository's product definition remains: an Evidence-driven business metric investigation Agent. Its Stage 1 profile uses `sales`, `orders`, `sessions`, `conversion_rate`, `aov`, `marketplace`, `asin`, and `traffic_source` as benchmark vocabulary ([任务书.md](../任务书.md)).

## 2. What is currently built

```text
PostgreSQL warehouse data
  → governed metric definitions
  → Agent Runtime chooses Analytics Tool calls
  → Observation catalog
  → selected Evidence
  → structured Diagnosis
  → FastAPI + React Diagnosis Workspace
```

| Capability | Current implementation evidence | What it proves | What it does not prove |
|---|---|---|---|
| Metric semantic control | `configs/metrics.yaml`, `backend/app/metrics/registry.py` | Metric formulas, dimensions, related metrics and `driver_metrics` are application-controlled. | A generic multi-industry metric platform. |
| Dynamic investigation runtime | `backend/app/agent_runtime/diagnosis_runtime.py:213` | The SDK Runtime performs the reasoning/tool-call loop; the application validates trace, Observation, Evidence and Diagnosis boundaries. | A self-built fixed workflow or an external business causal explanation. |
| Controlled data access | `backend/app/analytics/tools.py`, `backend/app/sql_safety/` | The Agent queries governed metrics through bounded tools rather than arbitrary database access. | Free-form Text-to-SQL access. |
| Evidence-grounded conclusion | `backend/app/evidence/`, `backend/app/diagnosis/` | Diagnosis references Evidence created from this run's Observations; invalid references are rejected. | Proof that an ad bid, listing change, or competitor caused the data anomaly. |
| Evaluation | `warehouse/benchmark_cases.json`, `backend/scripts/run_benchmark_evaluation.py:325` | Synthetic cases can be injected, evaluated against hidden-to-runtime Ground Truth, and audited. | Real-world generalization or guaranteed model reliability. |
| Product surface | `backend/app/api/routes.py:27`, `frontend/src/` | Health, metric graph, scenarios and investigation are exposed to a React workspace. | Production authentication, multi-tenant sessions or a Go gateway. |

## 3. Demonstration story

Use the canonical Stage 1 case:

```text
Sales decline
→ Agent identifies conversion_rate as primary data driver
→ narrows the affected scope to US / ASIN-A / Ads
→ cites Evidence produced from the same investigation
→ reports a data anomaly contribution localization
```

The conclusion is deliberately bounded:

> “The observed Sales decline is concentrated in the US marketplace, ASIN-A, Ads segment, with Conversion Rate as the primary data driver.”

It must not be presented as proof that an advertising strategy, a Listing change, or a competitor action caused the decline.

## 4. Verified acceptance evidence

| Check | Current factual result | Boundary |
|---|---|---|
| Backend regression | 449 unit tests pass | Hermetic correctness; not real-model performance. |
| Product build | React lint and production build pass; FastAPI `/health` returns `200` | Build and local API availability; not deployment. |
| Live three-case gate | Explicit Gemini provider completed Canonical Conversion, Traffic Sessions and No-anomaly stop cases | Proves the core chain can execute dynamically through the compatible provider. |
| Calibrated 10-case Live run | One run per Case achieved 100% completion / Driver / Scope / Exact Match | One controlled synthetic run, not a general accuracy claim. |
| Repeated Live sample | 10 Cases × 3 runs: 28/30 completed; aggregate completion, Driver, Scope and Exact Match = 93.33% | A bounded stability sample. Two invalid final diagnoses were rejected rather than silently accepted. |
| Failure auditability | Per-run atomic checkpoint and a reference-only failure note | Interruption and invalid final intents can be audited without storing provider text, Tool values, URLs or credentials. |

## 5. Local demo sequence

Prerequisites are a locally initialized synthetic PostgreSQL warehouse and locally configured provider variables. Do not commit `.env` or substitute real credentials into documentation.

```powershell
# Terminal 1: API
Set-Location backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2: workspace
Set-Location frontend
npm run dev
```

Then use the Workspace to inspect the metric graph, select the canonical scenario, run the investigation, and inspect:

1. the tool-call trajectory;
2. the resulting Observation cards;
3. selected Evidence and their roles;
4. the Structured Diagnosis and its scope;
5. the stated limitation that the result is data-level localization.

For offline wiring verification only:

```powershell
python backend/scripts/run_benchmark_evaluation.py --hermetic --runs-per-case 1
```

For a real-provider evaluation, explicitly set the model or configure `METRICSLEUTH_AGENT_MODEL`; the Runner records the resolved model in its Evaluation Manifest. Real runs require local credentials and are not represented by the hermetic output.

## 6. Known limitations and honest talking points

- **Current**: Amazon/e-commerce is the only implemented Stage 1 profile. The Core intentionally avoids treating its vocabulary as a permanent product definition, but no SaaS or other profile is implemented.
- **Current**: The 30-run real sample is 93.33%, not 100%. The two failures were domain validation rejections, which is safer than accepting an unsupported diagnosis. Their exact invalid intent has not reoccurred in a focused 6-run reproduction.
- **Deferred**: Real-world dataset mapping validation, persistent investigation sessions, authentication, deployment, Go gateway, monitoring, RAG and Operations Action Plans.
- **Out of scope**: Business root-cause proof and recommended Amazon operational actions. Those belong to a Human or upper Operations Agent using additional SOP, campaign, competitor and market evidence.

## 7. Meeting-ready summary

MetricSleuth is not a dashboard, unrestricted Text-to-SQL wrapper, or Amazon strategy assistant. It is a controlled investigation layer: a model decides which governed metric query to make next, while the application owns metric semantics, safety, Observation/Evidence provenance, structured diagnosis validation and benchmark scoring. The current MVP proves that loop on a controlled Amazon profile and makes both successful and rejected runs auditable.
