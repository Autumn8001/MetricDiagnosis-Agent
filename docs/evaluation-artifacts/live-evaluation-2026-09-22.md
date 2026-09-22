# Live Evaluation Acceptance Record — 2026-09-22

> Status: observed local acceptance evidence · Scope: controlled Stage 1 Synthetic Benchmark · Source revision: `3884600`

## Scope

This record preserves the aggregate, non-sensitive result of a completed real-provider evaluation. It is not a production reliability claim and it does not expose the local provider URL, database URL, API key, Tool result values, or model text.

The Agent Runtime did not receive `warehouse/ground_truth.json`; Ground Truth is consumed only by the evaluation layer after each run.

## Run identity

| Field | Observed value |
|---|---|
| Manifest ID | `manifest-benchmark-20260922-035143` |
| Model explicitly requested | `gemini-3.8-flash-high` |
| Dataset | Stage 1 controlled Synthetic Benchmark, 10 Cases |
| Runs per Case | 3 |
| Expected / recorded runs | 30 / 30 |
| Metric configuration / dataset version | `v1.0.0` / `v1.0.0` |
| Runtime limits | At most 8 Tool Calls and 10 turns per run |
| Restoration | Runner restored the local warehouse to `canonical` after completion |

## Aggregate outcome

| Metric | Result |
|---|---:|
| Run completion | 28 / 30 (93.33%) |
| Macro Driver accuracy | 93.33% |
| Macro Scope accuracy | 93.33% |
| Macro Exact Match | 93.33% |
| Provider / database / Tool Budget / trace failures | 0 |
| Rejected final Diagnosis intents | 2 (`DiagnosisValidationError`) |

The two rejected outcomes occurred in the following runs:

- `conversion_sales_de_asin_c_ads-live-run-2`
- `traffic_sales_us_asin_c_organic-live-run-3`

They remain in the denominator. The system did not downgrade the domain validation or report only the successful 28 runs.

## Interpretation

**Current fact:** the Agent completed the full controlled benchmark and produced the expected Driver and Scope in 28 cases. The two remaining outcomes were rejected at the structured Diagnosis boundary, rather than being accepted without supporting Evidence.

**Boundary:** this sample demonstrates a working Agent investigation chain under one compatible provider and a controlled Amazon Profile. It does not establish real-world accuracy, provider-independent performance, causal attribution, or 100% repeatability.

## Follow-up evidence

After this run, each failed Case was independently repeated three times with the same explicit model selection:

| Case | Runs | Completion / Driver / Scope / Exact Match |
|---|---:|---:|
| `conversion_sales_de_asin_c_ads` | 3 | 100% / 100% / 100% / 100% |
| `traffic_sales_us_asin_c_organic` | 3 | 100% / 100% / 100% / 100% |

This means the failure is not a deterministic anomaly-injection or Analytics Tool defect. It is insufficient evidence for adding a retry loop, a fixed investigation path, or a Benchmark-specific Prompt exception.

## Audit and recovery behavior

The Evaluation Runner now writes an atomic checkpoint after every completed run (`backend/scripts/run_benchmark_evaluation.py:301`). A checkpoint holds only run identity, operation counts, structured Diagnosis fields and Evidence IDs. It excludes credentials, provider output and raw business values. When a domain composition error includes the Runtime's existing reference-only intent note, the runner preserves that note for future diagnosis while discarding arbitrary exception text (`backend/scripts/run_benchmark_evaluation.py:284`).

## Reproduction boundary

The exact original provider output is intentionally not versioned. Reproduction requires a locally configured compatible provider and the local synthetic warehouse. Use the command documented in [README.md](../../README.md) and explicitly set the model to preserve run identity.
