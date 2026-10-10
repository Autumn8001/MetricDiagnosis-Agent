# R2-005b2b — 显式应用接线与真实 SQL 验收

日期：2026-10-10；基线 `86ac086` + 本切片提交。已实现并受控验收，**真实模型待验收**，不代表 R2/MVP 全部完成。

## 产品意义与实现

此前任务 API 需要调用者手动拼接 service/Worker。现在提供一个可以单独启动的本地 API 和 Worker 入口，并把查询和保存接起来：

```text
显式配置 → 任务 API → app_state queued → Worker
                                         ↓
                    SourceInvestigationRunner → 现有 SDK Diagnosis Runtime
                                         ↓ 每次工具查询
                    AnalyticsTools → 独立 READ ONLY 短事务
                                         ↓
                    Observation / checkpoint → 持久结果 / GET 历史
```

- `backend/app/task_application.py`：`TaskApplicationConfig`、`build_task_application()`、本地 `api/worker` CLI；构造不连接数据库或模型，不自动迁移、不读取 `.env`/旧 `DATABASE_URL`。
- `backend/app/persistence/source_runner.py`：复用 `run_evidence_driven_diagnosis()`，没有第二 Agent loop。显式传 model、预算与 progress_callback；RunConfig 禁止本次 tracing 导出，防止业务内容自动进入默认 tracing。SDK 主线依据 [官方 Agents SDK 文档](https://developers.openai.com/api/docs/guides/agents/sdk)，具体兼容性以仓库固定 `openai-agents==0.22.0` 和实际测试为准。
- 工具硬性约束任务日期、previous_7_days 和固定 filters；固定过滤必须由每次工具参数明确带出，不能遗漏/覆盖。不能只在 SQL 中隐式补过滤，否则 Trace/Observation 会误报实际数据范围。
- 每次查询单独打开事务，`SET TRANSACTION READ ONLY` + 10 秒 statement_timeout，查询后提交并关闭；模型思考期间不持有该事务。固定失败分类不输出驱动原文。
- `main.py:create_app(include_legacy_routes=False)` 提供任务专用入口：不含旧 Scenario Injection/同步调查端点，CORS 仅本地开发来源，无 wildcard/credentials。默认旧 app 保持兼容。
- `repository.py:upsert_data_source()` 不传 capabilities 时保留已有元数据；新来源仍写 `{}`，显式 `{}` 可清空。身份不可变合同不变。

## 启动合同（实现，非生产部署方案）

必须显式提供以下环境变量；不写入仓库、不通过 HTTP 传入、不输出值：

| 变量 | 内容 |
| --- | --- |
| `METRICSLEUTH_STATE_DATABASE_URL` | 本机应用状态事务连接 |
| `METRICSLEUTH_ANALYTICS_DATABASE_URL` | 本机分析数据连接；应使用独立只读角色 |
| `METRICSLEUTH_TASK_PROFILE` | `synthetic` 或 `olist_validation`，自动标记 Sandbox/Validation |
| `METRICSLEUTH_TASK_SOURCE_ID` | 稳定且不可重绑定的数据源身份 |
| `METRICSLEUTH_TASK_DATA_VERSION` | 已准备数据版本标签；不是数据库快照 |
| `METRICSLEUTH_TASK_MODEL` | 运营者选择的模型，不接受客户端覆盖 |
| `METRICSLEUTH_TASK_MAX_TOOL_CALLS` / `...MAX_TURNS` | 可选，默认 8/10；最大 8/10，保持现有 Runtime 约束 |

只接受 loopback PostgreSQL URL，不允许 query 参数重定向；暂不支持远程生产 URL。状态与分析库可不同，Analytics 事务只读不替代数据库角色授权。管理员须事先在受控环境执行状态迁移 001–004 并准备 Profile 表；启动不会帮用户执行迁移或注入数据。

在 `backend`：

```powershell
python -B -m app.task_application api --port 8001
# 另一个终端；必须明确提供 OPENAI_API_KEY、模型和预算后才执行。
python -B -m app.task_application worker --once
# 持续本地 Worker，2 秒轮询；Ctrl+C 停止，不自动重试收费调查。
python -B -m app.task_application worker
```

API 固定监听 `127.0.0.1`，不输出 access log；`/health` 是进程健康，不是数据库 readiness。Worker 没有模型凭据时在领取前失败。没有运行过上述真实模型 Worker；仅运行了 CLI help、隔离 API 子进程和受控 Runner。

默认 SDK Runtime 沿用原有 `OPENAI_API_MODE`/`OPENAI_AGENTS_DISABLE_TRACING` bootstrap。显式每次 RunConfig 强制禁 tracing，但模型数据本身依然需要发送给选定 Provider，不能理解为离线/零外发。

## 可复现验收与结果

沿用仓库外 PostgreSQL 17.11 / 55440 / `metricsleuth_r2_acceptance`（环境准备见 [Worker 验收](worker-checkpoint-acceptance-2026-10-10.md)）。专用变量只用于隔离测试，缺省跳过不是通过。

```powershell
$env:METRICSLEUTH_TEST_DATABASE_URL = 'postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_persistence_integration tests.test_postgres_task_api_integration tests.test_postgres_task_application -v
```

新专项 `tests.test_postgres_task_application` **4/4 PASS**：

1. 在受保护的专用测试库准备 UUID 隔离的八天 Synthetic 行。`build_task_application()` → HTTP 排队 → Worker → Source Runner → **实际 AnalyticsTools 聚合 SQL** → 实际 Observation mapper → checkpoint → 受控 Diagnosis → GET 结果。真实计算 current=80、baseline=100；不是 SELECT 常量冒充指标仓库查询。
2. 在真实 Analytics 事务中尝试 UPDATE，PostgreSQL READ ONLY 实际拒绝，事务回滚、调查失败、没有假 Diagnosis，八天销售总额仍为 780。
3. 真实数据库验证 capabilities 省略保留、显式空清除，data_version 参数顺序正确。
4. 独立 Python API 子进程通过 loopback HTTP 返回 health 和真实数据库历史列表；旧注入端点 404。结束时仅停止本测试子进程。

工具调用选择与最终 Diagnosis 是注入的受控 Runner，不经过模型/SDK 推理循环；真实的是 SQL、Observation 映射、事务、进程 HTTP 和持久化，不是模型正确率。

主线程最终合并数据库回归 **Ran 23 tests / OK**；独立离线回归 **Ran 585 tests / OK (skipped=3)**，三个数据库测试类因未配置专用变量跳过。Reader/API/Worker 原验收仍保留原边界。审查时修复了 CASE 布尔 SQL 参数顺序与 Trace 固定过滤遗漏，不能把先前 Fake 通过视为已证明这些边界。

## 尚未验收 / 下一步

- 真实 SDK/模型执行、预算和结果需下一次明确配置后验证；不能根据 adapter 接线宣称通过。
- 当前只提供 Synthetic Sandbox / Olist 静态 Validation Profile。未新增 Shopify/用户外部 PostgreSQL 连接器或持续同步。
- `data_version` 是配置标签；不同短事务可能看见并发更新。真实来源接入前须选择稳定版本表/快照边界，不能声称已有可复算 snapshot。
- 单 Worker 读取该 app_state 的 Worker 队列；配置只绑定一个来源。不要让不同单源 Worker 共用一个混合来源队列并假设会自动路由；多来源需求确定后再最小扩展。
- 公开部署认证、生产只读角色、TLS、日志/敏感字段治理、模型配置元数据、备份、前端与原型仍未完成。测试启动不是服务器部署。
- 测试只新增专用 Synthetic 数据，保留在仓库外测试实例，不删除重要数据；验收结束停止隔离实例。
