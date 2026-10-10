# Phase 9: Olist Real-world Validation Contract

## Purpose

This validation tests whether MetricSleuth's **data-investigation boundaries**
can be mapped to a real public e-commerce source. It is not an Amazon data
replacement, a new Domain Profile, or a claim about real-world business cause.

## Source and isolation

- Source: Olist Brazilian E-Commerce Public Dataset (local raw files live in
  `data/raw/olist/`, which is intentionally git-ignored).
- The source is read-only. It must not replace `warehouse` synthetic benchmark
  tables, alter Benchmark Ground Truth, or be imported by the Agent Runtime.
- The profiler is `backend/scripts/profile_olist_dataset.py`; it uses only the
  Python standard library and emits a reproducible source profile.

## Confirmed mapping candidates

| Metric / dimension | Olist source | Contract | Status |
| --- | --- | --- | --- |
| Merchandise GMV | `order_items.price` + delivered `orders` | `SUM(price)`; freight excluded | Candidate for a real-world Sales-like metric |
| Orders | delivered `orders.order_id` | `COUNT(DISTINCT order_id)` | Available |
| AOV | item price + delivered orders | aggregated GMV / aggregated orders | Available |
| Customer State | `customers.customer_state` | customer geography slice | Available |
| Seller State | `sellers.seller_state` | seller geography slice | Available after explicit join |
| Product Category | `products.product_category_name` | product hierarchy slice | Available |
| Payment Type | `payments.payment_type` | descriptive only until allocation is specified | Caveat |

## Explicit unsupported fields

Olist has no session/impression/click event stream and no acquisition-channel
field. Therefore `sessions`, `conversion_rate`, `marketplace`, `traffic_source`
and Amazon `asin` must remain **unavailable** for this validation. The project
must not synthesize them or reinterpret a proxy as a measured value.

## R1-003 capability contract

The existing registry is now expressed as a pure, isolated capability contract
by `backend/app/data_sources/olist_validation.py`:

- provider/environment are fixed to `OLIST + VALIDATION`;
- `merchandise_gmv`, `orders`, and `olist_aov` are adapted from the registry
  with `date × customer_state` grain and `customer_state` as their only
  query-safe dimension;
- `sessions` and `conversion_rate` are explicit `supported: false`
  declarations with reasons tied to the missing Olist event/denominator data;
- `marketplace`, `traffic_source`, and `asin` are not exposed as Olist
  dimensions.

`backend/scripts/verify_olist_tool_compatibility.py` passes this contract into
the existing `AnalyticsTools`, and
`backend/tests/test_olist_validation_capabilities.py` verifies the SQL-before-
validation boundary with a connection sentinel. This is a local Hermetic
contract check based on the existing Olist validation assets; it does not claim
that the current environment has an Olist database connection, synchronization,
continuous updates, or production ingestion.

## Run

```powershell
python backend/scripts/profile_olist_dataset.py `
  --input-dir data/raw/olist `
  --output-json docs/evaluation-artifacts/olist-source-profile.json
```

The isolated staging load is opt-in and never touches `warehouse`:

```powershell
# Source/join validation only; no database write.
python backend/scripts/load_olist_validation.py --input-dir data/raw/olist --dry-run

# Requires DATABASE_URL. First load creates only olist_validation.* tables.
python backend/scripts/load_olist_validation.py --input-dir data/raw/olist
python backend/scripts/verify_olist_validation.py `
  --output-json docs/evaluation-artifacts/olist-mapping-verification.json

# Reuse the existing controlled AnalyticsTools with the temporary Olist registry.
python backend/scripts/verify_olist_tool_compatibility.py `
  --output-json docs/evaluation-artifacts/olist-tool-compatibility.json
```

Re-loading an already populated validation schema is fail-closed. `--replace`
must be supplied explicitly and truncates only `olist_validation.fact_daily_order_value`,
`olist_validation.olist_order_items`, and `olist_validation.olist_orders`. No replacement
was performed in the 2026-10-10 acceptance run.

## Phase 9 validation boundary

The isolated staging adapter and compatibility command remain available for
an explicitly authorized local database validation run. Existing JSON
artifacts record an earlier validation of the raw joins and controlled tool
queries, but they are not evidence that the current environment has an active
Olist connection or continuous synchronization. The temporary registry
exposes only `merchandise_gmv`, `orders`, `olist_aov` and the order-safe
`customer_state` dimension. Its `sample_size_field: orders` is an explicit
real-data semantic choice; the Amazon registry continues to default to
`sessions`.

The original Phase 9 did not load this registry into the Agent Runtime or
product API. Since R2-005b2b (`c8ea746`), the explicitly configured local task
application supports an `olist_validation` profile; the default legacy API,
Benchmark cases, and Amazon Stage 1 config are unchanged. This still does not
establish continuous ingestion or real-model acceptance. Phase 9 demonstrates controlled tool
compatibility and local capability degradation, not a production multi-domain
implementation. R1-003 passed Hermetic regression; the 2026-10-10 isolated
database revalidation reuses these assets without claiming a continuous connector.

The 2026-10-10 actual SQL and persisted-progress results, input fingerprints,
and explicit isolated-database reproduction commands are recorded in
[`olist-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/olist-persistence-acceptance-2026-10-10.md).
That run deliberately fails after four completed steps and verifies that the
27 observations survive; it does not create a Diagnosis or call an LLM.
