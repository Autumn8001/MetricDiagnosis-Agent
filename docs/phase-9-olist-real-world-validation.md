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
must be supplied explicitly and truncates only `olist_validation.olist_orders`
and `olist_validation.olist_order_items`.

## Phase 9 exit criterion

The isolated staging adapter now validates the raw joins, materializes the
source in `olist_validation.*`, and has been queried through the existing
`AnalyticsTools` using `configs/olist_validation_metrics.yaml`. The temporary
registry exposes only `merchandise_gmv`, `orders`, `olist_aov` and the
order-safe `customer_state` dimension. Its `sample_size_field: orders` is an
explicit real-data semantic choice; the Amazon registry continues to default
to `sessions`.

No Agent Runtime, product API, Benchmark case, or Amazon Stage 1 metric config
loads this temporary registry. Phase 9 therefore demonstrates controlled tool
compatibility, not a production multi-domain implementation.
