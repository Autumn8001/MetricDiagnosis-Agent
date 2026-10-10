# Olist 静态公开数据：真实 SQL 与调查步骤持久化验收

日期：2026-10-10。源码基线：`c8ea7467475adc4c24d5db3d7895efe780afe960`，加本次验收脚本。

## 已运行的能力与边界

主线程在仓库外 PostgreSQL 17.11、loopback 55440、专用 `metricsleuth_r2_acceptance` 上运行现有 Olist loader、映射验证、AnalyticsTools 和新步骤验收。没有访问生产数据库、执行替换导入或调用模型；原始 CSV 与订单/客户 ID 不进入本记录。

这是**真实公开历史订单数据 + 真实 PostgreSQL + 受控 Runner**，不是 Synthetic，也不是持续外部连接器或真实模型验收。任务 HTTP 使用 TestClient；新应用实例重新建立数据库连接读取，不是浏览器或服务器部署验收。

## 输入与实际查询结果

本机 `data/raw/olist` 的五个输入已存在；未下载或提交原始数据。SHA-256：

| 文件 | SHA-256 |
|---|---|
| olist_orders_dataset.csv | 8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf |
| olist_order_items_dataset.csv | 0bc4d068c4fe38cbb01bd90e8746e3c613fe7b4baef75fab7b0e329701c3e279 |
| olist_customers_dataset.csv | 983a422239e1712ded753b3bf9ecf47dc73f144d306029dcfa99e70a226883d2 |
| olist_products_dataset.csv | 3e6569628a17fbc75fd206ee357b59e20364b9afa90f5b6cd5b4d624c58aa9cc |
| olist_sellers_dataset.csv | 1f643d2b950373b85735e7794b20986f528d7a000432e7c6f9bcbb44d0846a0e |

首次导入前确认 `olist_validation.olist_orders` 不存在。dry-run 与真实导入均为 99,441 orders / 112,650 order items。映射验证：

- delivered orders：96,478；delivered merchandise GMV：13,221,498.11；AOV：137.0415857501192。
- 原始可用 customer state 27、seller state 23、category 73；**当前 canonical 指标只声明 customer_state**，不把原始字段数量等同于可调查维度。
- 未构造 sessions/conversion_rate/asin/marketplace/traffic_source。
- 重复导入未提供 `--replace`，被拒绝；随后实际 SQL 确认订单 99,441、明细 112,650、日订单事实 96,478、总 GMV 13,221,498.11、总 orders 96,478，未覆盖数据。

2017-03-20 工具兼容性查询：GMV 16,861.09，前七日均值 13,355.61，相对变化 +0.26247247411387425；AOV 149.21318584070795，对比 158.18827411167513。GMV 按 customer_state 返回 24 行，baseline sample_size 为 84.42857142857143 orders/day。

## 持久任务验收

脚本：`backend/scripts/verify_olist_task_progress.py`；离线守卫测试：`backend/tests/test_olist_task_progress_acceptance.py`。

最终主线程执行 run：`102bea3f-cc93-400a-a871-6ef90238972f`；source：`bbaf0fe3-c61a-4d03-acca-4e10b69d24b7`；version：`olist-public-raw-files-20261010`。版本是审计标签，**不是数据库快照**；以上输入指纹帮助重建数据，但不冻结未来查询。

实际链路：

```text
POST 202 queued → Worker running
→ GMV overall SQL → checkpoint → HTTP 读回 running
→ orders overall SQL → checkpoint → HTTP 读回 running
→ AOV overall SQL → checkpoint → HTTP 读回 running
→ GMV by customer_state SQL → checkpoint → HTTP 读回 running
→ 受控 Runner 主动中止 → failed/execution_failed
→ 新应用实例/新连接读取同一结果
```

四个完整步骤、27 Observation 均保存；Evidence 0、Diagnosis 0。脚本退出 0 表示**预期失败留存验收通过**，不表示调查成功。工具值来自实际 SQL，行动顺序和中止由脚本控制，未由 LLM 选择。

`sessions` 及 GMV 按 `marketplace` 的无效请求返回 400，未创建任务。测试不声称验证所有不支持字段。失败状态只有固定 code；没有原始异常或外部响应写入数据库。

## 复现

仓库根目录，先按 [PostgreSQL 环境记录](postgres-persistence-acceptance-2026-10-10.md) 配置专用库并执行 migrations 001–004；脚本不迁移。导入只在该 schema 为空时执行；已有数据时仅复核，不添加 `--replace`。

```powershell
python -B backend/scripts/load_olist_validation.py --input-dir data/raw/olist --dry-run
python -B backend/scripts/load_olist_validation.py --input-dir data/raw/olist --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance
python -B backend/scripts/verify_olist_validation.py --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance
python -B backend/scripts/verify_olist_tool_compatibility.py --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance --target-date 2017-03-20
python -B backend/scripts/verify_olist_task_progress.py --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance --data-version olist-public-raw-files-20261010
```

脚本固定本验收日期，新 source/run ID 随机生成；不自动重放调查。不使用 `.env`、生产 DSN、模型或 `--output-json`。日期、币种/退款边界沿用 [Olist 映射说明](../phase-9-olist-real-world-validation.md)，并不建立多币种或时区转换支持。

主线程离线回归：`Ran 591 tests / OK (skipped=3)`。三个 PostgreSQL 类因未设置专用测试变量跳过；上述实际数据库脚本另行执行，两类证据不混算。
