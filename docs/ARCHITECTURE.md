# MetricSleuth 架构说明

> **Status：Current + Planned boundary**
> 更新日期：2026-10-10
> 审查基线：`main`，R4-002 独立本地提交（用 git log 查询）；包含 R2-PG、R2-005b Worker/API 与 R4-001/002 受控验收
> 证据范围：仓库源码、测试、Schema、配置和版本化脱敏 artifact。本文没有连接生产数据库，也没有检查已部署服务。

本文是给后续开发者和接管 Agent 使用的**现状架构参考**。`Current` 只描述源码能够支持的行为；`Planned` 只描述已经确认的责任边界，不代表已经存在的表、接口或部署；`Unknown` 表示现有证据不足。历史任务书中的目标不能覆盖当前实现事实。

## 1. 架构结论

### Current

MetricSleuth 当前是一个以 Amazon/电商 Stage 1 Profile 为首个验证领域的 Python 单体应用：

```text
PostgreSQL Warehouse
        ↓
MetricRegistry（YAML 指标语义）
        ↓
AnalyticsTools（受控参数化查询）
        ↓
OpenAI Agents SDK Runner（模型决定下一工具动作）
        ↓
Observation → Evidence → Structured Diagnosis
        ↓
旧同步 FastAPI JSON（旧 Benchmark API 路径保留）
```

调查内核已具备可测试的“指标查询—动态调查—证据校验—结构化诊断”链路。旧同步 Benchmark API 仍保留；默认 React App 已切换到持久任务工作区，具体边界见第8节。另已完成并验收持久任务 API/Worker 路径：

```text
显式配置的任务 API → PostgreSQL app_state queued
                                  ↓
                            最小 Worker → 注入的 Runner
                                  ↓            ↓ 完整工具结果
                         终态/Diagnosis    checkpoint Trace/Observation
                                  └────────────┴→ app_state → GET 历史/详情
```

这条路径以受控 Runner 在真实数据库验收。另有显式本地任务应用入口可配置现有 SDK Runner，但真实模型待验收；默认旧 app 不自动启用服务，不是多数据源、认证或生产部署平台。

当前最重要的复用点是 `MetricRegistry`、`AnalyticsTools`、Agents SDK Runtime、Observation/Evidence/Diagnosis、Evaluation，以及已验收的持久化/Worker/API；主要缺口是实际来源与 Runner 配置、完整查询快照 provenance、持续外部接入、前端和部署边界。

### Planned

后续目标是在不重写调查内核的前提下，补齐以下边界：

- 外部数据源与 Synthetic/Sandbox 的身份和环境隔离；
- 原始数据到可调查 canonical 指标数据的责任分层；
- 已实现持久 Run/事实在默认应用和前端中的配置与使用；
- 可长期运行的安全部署、密钥注入、访问控制和运维边界。

`app_state` 表、migrations 001–004 和任务 API 已确定并验证，见后文 Current。外部 staging/canonical、用户权限与部署方案仍属规划。

### Unknown

- 当前个人服务器上是否已经存在可连接的 PostgreSQL 实例、其中实际有哪些表和数据，本次未连接验证。
- 已认可的独立 HTML 产品原型已由产品方提供，文件、哈希与页面/API 边界见 `PRODUCT.md` 第4节；R4-002 已按其导航和视觉基线接入 React，但静态原型及当前受控 UI 均不代表完整产品已实现。
- Shopify、外部用户 PostgreSQL、Webhook 和 Jev 尚未进入当前 Runtime/API。
- R1-004a已完成公开官方资料/源码比较，下一外部验证对象为Shopify开发店(sandbox)，产品级订单API接入和不可变版本发布仍是Planned，不是已有产品模块。见 [`data-source-selection.md`](data-source-selection.md)。不把Synthetic订单/会话比率套用为Shopify会话转化率。
- R1-004b新增独立 `backend/scripts/probe_shopify_orders.py`（只读固定query，离线守卫已验证）；不属于产品Runtime/同步连接器，不写数据库或发布版本。Shopify实际API、字段权限、持续更新及指标接线仍未验收，见 [`shopify-orders-probe.md`](shopify-orders-probe.md)。
- 生产反向代理、TLS、认证、密钥管理和进程监管方案尚未落地。

## 2. 证据边界与仓库地图

### Current：代码和配置的事实来源

当文档、测试和实现冲突时，当前行为以可执行源码和配置为准；测试说明验证边界，不能把 Mock 通过解释为生产运行。

| 区域 | 当前职责 | 主要证据 |
|---|---|---|
| 指标语义 | 读取并校验 YAML，建立只读内存 `MetricRegistry` | `configs/metrics.yaml`；`backend/app/metrics/registry.py:60-153` |
| 数据源能力契约 | 不可变身份/粒度合同；Registry 适配、AnalyticsTools 可选校验及新任务 API 服务器绑定；不是连接器 | `backend/app/data_sources/capabilities.py`；`backend/app/data_sources/semantic_adapter.py`；`backend/app/api/task_service.py` |
| Warehouse | Synthetic 数据 Schema、Seed 和异常注入 | `warehouse/schema.sql`；`warehouse/seed.py`；`warehouse/anomaly_injector.py` |
| 分析工具 | 根据 Registry 校验参数并执行 PostgreSQL 聚合；传入能力契约时在 SQL 前做来源能力校验 | `backend/app/analytics/tools.py:20-178` |
| SQL 安全 | 独立的 `sqlglot` AST 校验器和 LIMIT/allowlist 规则 | `backend/app/sql_safety/guard.py:49-251` |
| 可信中间事实 | `MetricQueryResult` 转不可变 `Observation` | `backend/app/analytics/models.py:18-71`；`backend/app/observations/mapper.py:45-187` |
| 证据和诊断 | Observation 显式提升为 Evidence，再组合为 Diagnosis | `backend/app/evidence/promoter.py:13-57`；`backend/app/diagnosis/composition.py:80-106` |
| Agent Runtime | Agents SDK 工具桥、Trace 审计、结构化诊断意图 | `backend/app/agent_runtime/investigation_runtime.py`；`backend/app/agent_runtime/diagnosis_runtime.py` |
| API 服务 | 旧同步调查 + 显式注入的持久任务/历史 API | `backend/app/api/routes.py`；`backend/app/api/task_routes.py`；`backend/app/api/task_service.py` |
| 应用状态 | 短事务事实保存、最小 Worker、作用域读取 | `backend/migrations/`；`backend/app/persistence/`；`backend/tests/test_postgres_persistence_integration.py`；`backend/tests/test_postgres_task_api_integration.py` |
| 前端 | React + TypeScript + Vite；默认调查区已消费持久任务 API，旧 Benchmark 工作台与其 API 客户端保留为历史路径 | `frontend/src/App.tsx`；`frontend/src/product/InvestigationWorkspace.tsx`；`frontend/src/tasks/client.ts`；`frontend/src/api.ts`；`frontend/vite.config.ts` |
| Evaluation | 纯评分、操作状态、Evidence/Unsupported Claim 评分和评测脚本 | `backend/app/evaluation/`；`backend/scripts/run_benchmark_evaluation.py` |

### Current：实际技术栈

- 后端：Python `>=3.12`、FastAPI、Uvicorn、Pydantic 2、`psycopg`、PyYAML、`sqlglot`，以及 `openai-agents==0.22.0`（`backend/pyproject.toml:1-17`）。
- 数据库：PostgreSQL 连接实现。仓库声明的 Synthetic Schema 不是外部用户数据库接入机制。
- 前端：React 19、TypeScript 6、Vite 8，原生 CSS；依赖和脚本见 `frontend/package.json:1-23`。
- 应用形态：已有 `backend/migrations/` 和显式参数化 Repository；无应用 ORM、Dockerfile/Compose 或生产静态资源托管配置。

### Unknown：验证口径

当前阶段实际运行过隔离本机 PostgreSQL 验收；2026-10-10 授权的一次真实 SDK 模型请求返回 `InternalServerError`，没有完成工具或 Diagnosis，模型成功验收仍未通过。未操作线上服务。`README.md`、`任务书.md` 和 `docs/agent-state.md` 的测试数量/Live 描述来自不同时间；最新结果见 `PROJECT_STATUS.md` 与验收 artifact，不能混算历史和本轮证据。

## 3. 当前数据模型

### Current：Synthetic Warehouse

`warehouse/schema.sql` 定义两个对象：

```text
warehouse.dim_products
  asin (PK), product_name, category

warehouse.fact_daily_performance
  date, asin, marketplace, traffic_source,
  impressions, clicks, sessions, orders,
  sales, ad_spend, refunds
  PK = (date, asin, marketplace, traffic_source)
```

事实表的已实现 grain 是：

```text
date × asin × marketplace × traffic_source
```

`warehouse/seed.py` 生成确定性的 Synthetic 记录，`warehouse/anomaly_injector.py` 修改当前日期的受控异常场景。异常注入是 Benchmark/Sandbox 行为，不是外部业务数据同步。

### Current：隔离的 Olist 验证 Schema

`warehouse/olist_validation_schema.sql` 和 `backend/scripts/load_olist_validation.py` 使用独立的 `olist_validation` Schema，包含订单、订单明细和按日订单价值的验证对象。`configs/olist_validation_metrics.yaml` 用于 Olist 受控指标验证，并可由显式 `task_application.py` 的 `olist_validation` Profile 加载；它不被 `backend/app/api/service.py` 的默认 Runtime/API 加载，也不替换 Synthetic Profile。

Olist 证据只说明部分真实公开订单数据可以映射到受控指标工具。它不能证明当前系统已经支持任意外部 PostgreSQL，也不能提供当前 Amazon Profile 缺失的 `sessions`、`traffic_source` 或 `asin` 语义。

R1-003 新增的 `build_olist_validation_capabilities()`（`backend/app/data_sources/olist_validation.py`）把该 Profile 表达为 `OLIST + VALIDATION` 的纯内存能力合同：三个指标的 grain/dimensions 由 Olist Registry 适配而来，`sessions` 与 `conversion_rate` 被显式声明为 unavailable。`backend/scripts/verify_olist_tool_compatibility.py` 将这份合同传给 `AnalyticsTools`，因此支持指标的非法维度会在 SQL 前失败；这项能力只由本地 Hermetic 测试证明，不代表已完成 Olist 数据库连接、同步或持续外部接入。

上述是 R1-003 切片当时的验证边界。2026-10-10 主线程补验：真实公共 CSV → 隔离 PostgreSQL → Analytics SQL → 四步受控 Runner → 27 Observation/checkpoint → 预期失败 → 新应用读回已通过。`verify_olist_task_progress.py` 不调用 LLM、不制造 Evidence/Diagnosis；数据版本标签不是快照，未完成持续外部同步。可复现证据见 [`olist-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/olist-persistence-acceptance-2026-10-10.md)。

### Current：指标语义层

`configs/metrics.yaml` 是当前默认 Registry 的唯一配置来源：

- source table：`warehouse.fact_daily_performance`；
- time dimension：`date`；
- dimensions：`marketplace`、`asin`、`traffic_source`；
- metrics：`sales`、`orders`、`sessions`、`conversion_rate`、`aov`；
- 每个 MetricDefinition 同时包含 `metric_type`、`unit`、`formula`、`source_fields`、`dimensions`、`grain`、`dependencies`、`driver_metrics`、`related_metrics`。

`MetricRegistry.from_yaml()` 会严格校验引用、配置结构和显式 grain（`backend/app/metrics/registry.py`）。显式 grain 必须非空、包含 `source.time_dimension`，且只能使用 source 声明的时间维度或业务维度；缺少 grain 的旧配置使用明确的兼容回退 `time_dimension + metric dimensions`。当前 `formula` 是语义元数据；`AnalyticsTools._execute_metric_query()` 根据 `metric_type` 和 `source_fields` 生成计算 SQL，而不是执行任意 YAML 字符串。

需要区分三类关系：

| 关系 | 当前用途 | 证据 |
|---|---|---|
| `dependencies` | 公式依赖，例如 Conversion Rate 依赖 Orders/Sessions | `configs/metrics.yaml:75-96` |
| `related_metrics` | `query_related_metrics()` 按声明顺序批量查询的关联指标 | `backend/app/analytics/tools.py:125-167` |
| `driver_metrics` | 诊断闭环要求先观察的直接解释指标，不规定固定下钻路径 | `configs/metrics.yaml:25-27,47-49`；`backend/app/agent_runtime/diagnosis_runtime.py:167-210` |

### Current：查询结果模型

`MetricQueryResult` 由 `DateRange`、`group_by` 和不可变 `MetricQueryRow` 组成；每行包含维度、当前值、基线值、相对变化、源状态和样本量（`backend/app/analytics/models.py:18-71`）。当前工具约束：

- 当前期必须是单日，即 `start_date == end_date`；
- 基线固定为前 7 个完整日期，参数为 `compare_to="previous_7_days"`；
- Additive 指标使用求和，基线返回每日平均；
- Ratio 指标使用聚合分子 / 聚合分母；分母为零时返回不可用语义；
- filters 和 group_by 必须来自该指标声明的 dimensions。

### Current：数据源能力契约与语义适配

在 `backend/app/data_sources/capabilities.py`（单测：`backend/tests/test_data_source_capabilities.py`）中已实现最小、领域无关、不可变的能力合同：

- `SourceProvider`：来源平台枚举（`postgresql`、`shopify`、`olist`、`synthetic`）；
- `SourceEnvironment`：环境枚举（`live`、`sandbox`、`benchmark`、`validation`）；
- `DataSourceDescriptor`：不可变来源身份描述符（`source_id`、`display_name`、`provider`、`environment`）；
- `MetricCapability`：单指标能力声明（`metric_id`、`supported`、`grain`、`dimensions`、`unavailable_reason`），包含指标独立的 grain 与维度快照，支持 fail-closed 校验；
- `DataSourceCapabilities`：数据源实例能力集合，支持查询能力校验 `validate_query()`、跨 grain 组合保护 `validate_metric_combination()` 与 `can_combine_metrics()`。
- `build_capabilities_from_registry()`：只把当前 `MetricRegistry` 中已声明的指标映射为支持能力，保留各指标 dimensions/grain，不创建 Registry 外的指标；源码：`backend/app/data_sources/semantic_adapter.py`。
- `build_olist_validation_capabilities()`：在共享 Registry 适配器基础上，创建固定为 `SourceProvider.OLIST + SourceEnvironment.VALIDATION` 的 Olist 验证合同，并对缺失的漏斗指标显式 fail-closed；源码：`backend/app/data_sources/olist_validation.py`，测试：`backend/tests/test_olist_validation_capabilities.py`。
- `AnalyticsTools(..., capabilities=...)`：能力契约为可选参数。传入时，`query_metric()` 在实际 SQL 前执行 `validate_query()`，并将能力合同错误转换为 `MetricQueryError`；不传时保持历史查询路径。

**当前边界明确：** 能力契约与语义 Registry/AnalyticsTools 已完成适配；Olist 显式本地 Profile 的数据库查询和任务 API 步骤保存已受控验收，仍未实现数据库来源发现、外部连接器、同步水位或持续真实外部数据验证。适配器本身不证明任意传入 descriptor 对应的物理来源已经连接或同步。

### Planned：数据模型责任边界

未来数据接入需要由数据源层负责**源身份、权限、刷新状态和能力声明**；由数据处理层负责**原始/中间数据与 canonical 指标数据的隔离、映射和质量校验**；由调查层只消费通过契约的数据能力。具体表名、列名和迁移方式待真实数据验证后确定。

### Unknown：当前模型不能表达的内容

- 当前 Registry/source table 已可通过纯内存适配器生成 capability contract；持久任务 API 的服务器绑定会注入来源身份与能力。旧同步 API/Analytics 主链仍受限于旧版单表假设，不能由新任务 API 的能力合同推导为多来源分析支持。
- 当前 `app_state` 与新任务 API 已持久化 source_id/environment、Run与事实、data_version标签及query reference，真实数据库验收见第8节；尚无可靠数据快照和持续同步水位。
- 应用 Run/Observation/Evidence/Diagnosis 的 Schema 和 migrations 001–004 已实现并在隔离 PostgreSQL 执行；尚无产品级 Analysis Session 或持续连接器。

## 4. 当前数据流

下面是源码实际支持的数据流；它不是未来产品架构图。

```text
Synthetic seed / anomaly_injector.py
              │
              ▼
PostgreSQL warehouse.dim_products
PostgreSQL warehouse.fact_daily_performance
              │  DATABASE_URL（API 服务在调用时建立连接）
              ▼
MetricRegistry.from_yaml(configs/metrics.yaml)
              │
              ├─ build_capabilities_from_registry (可选纯内存适配)
              │
              ▼
AnalyticsTools(registry, psycopg connection[, capabilities])
              │  query_metric / query_related_metrics
              │  capabilities.validate_query（传入时，SQL 前）
              ▼
MetricQueryResult / RelatedMetricQueryResult
              │
              ▼
Observation mapper
              │  Observation = Tool + call_id + filters + values + status
              ▼
Agents SDK local FunctionTool output
              │
              ▼
模型继续选择工具或提交 RuntimeDiagnosisIntent
              │
              ▼
Trace verifier → Observation catalog
              │
              ▼
Evidence selection → Diagnosis builder/composition
              │
              ▼
FastAPI InvestigationResponse
              │
              ▼
旧 React Benchmark App 内存状态与工作台组件
```

当前 API 还有两条旁路：

```text
POST /api/scans/daily
  → execute_manual_daily_scan()
  → AnalyticsTools
  → 候选 Observation
  → 不调用模型、不生成 Diagnosis

POST /api/investigate {mock_mode: true}
  → _run_mock_investigation()
  → 静态 Fixture Response
  → 不调用数据库、不调用模型
```

Live 调查目前还有一个重要的历史耦合：`_run_live_investigation()` 先调用 `inject_scenario_data()`，然后才打开 `DATABASE_URL` 并启动 Agent（`backend/app/api/service.py:554-588`）。因此“Live”在当前 API 中仍然是 Synthetic 场景演示路径，而不是可供用户选择外部业务数据源的通用路径。

## 5. 当前组件职责

### Current：Analytics Tools 与 SQL 安全

`AnalyticsTools` 接受一个已建立的连接对象、一个 `MetricRegistry`，以及可选的 `DataSourceCapabilities`（`backend/app/analytics/tools.py`）。传入能力契约时，`query_metric()` 在进入 `_execute_metric_query()` 前校验指标、filters 和 group_by；能力错误统一转换为 `MetricQueryError`。它使用 `psycopg.sql.Identifier` 与参数占位符生成 SQL，因此 SQL 不是模型直接提供的自由文本。模型只能通过 SDK 暴露的三个工具操作：

1. `get_metric_definition`：获取语义定义；
2. `query_metric`：查询单个指标；
3. `query_related_metrics`：按 Registry 的 related metrics 查询多个指标。

`SqlGuard` 能够限制单个 SELECT、Schema-qualified table allowlist、安全函数和 LIMIT（`backend/app/sql_safety/guard.py:90-251`），但当前主查询链没有导入或调用 `SqlGuard`；测试只证明 Guard 自己的规则。数据库只读角色配置位于 `warehouse/setup_readonly_role.sql`，也不是应用启动时自动配置的安全边界。

### Current：Observation

`observations_from_tool_result()` 将工具结果的每一行转换为不可变 `Observation`（`backend/app/observations/mapper.py:157-187`）。`Observation` 保存：

- `tool_name`、`tool_call_id`、确定性 `observation_id`；
- 当前/基线期间、filters、group_by、dimensions；
- current/baseline/relative change、unit、sample size；
- source status、标准化 `ObservationStatus`、创建时间和失败信息；
- `query_or_result_reference`，当前工具桥接器填入 `tool-result:{tool_call_id}`。

状态分类在 `classify_metric_row_status()` 中执行：材料性下降为 `anomalous`，小幅变化为 `normal`，其他变化为 `inconclusive`，缺失/不可用为 `insufficient_evidence`（`backend/app/observations/mapper.py:16-42`）。

### Current：Evidence 与 Diagnosis

模型只提交 Observation 引用和角色，不携带事实数值。`resolve_evidence_selections()` 只允许从本次运行的 Observation catalog 中按 ID 提升 Evidence，并在未知 ID 时 fail-closed（`backend/app/evidence/selection.py:101-140`）。`promote_observation_to_evidence()` 复制 Observation 的查询上下文和数值，并生成确定性 ID `evidence:{observation_id}:{role}`（`backend/app/evidence/promoter.py:13-57`）。

`build_diagnosis()` 进一步强制：

- `diagnosed` 的目标 Evidence 必须是目标指标的 anomalous supporting Evidence；
- 一个同一的 anomalous supporting Evidence 必须同时支持 `primary_driver` 和完整 `affected_scope`；
- `diagnosed` 必须包含 negative-control Evidence；
- `no_material_anomaly` 不能引用异常的非 limitation Evidence；
- 非成功状态不能携带未经支持的 driver、scope 或 confidence。

证据组合顺序是：

```text
Observation catalog
  → resolve_evidence_selections()
  → Evidence portfolio
  → resolve_diagnosis_draft()/build_diagnosis()
  → DiagnosisComposition
```

见 `backend/app/diagnosis/composition.py:80-106`、`backend/app/diagnosis/builder.py:57-163`。

## 6. 当前 Agent Runtime 与调查流程

### Current：动态调查

正式调查路径使用 OpenAI Agents SDK。`run_evidence_driven_diagnosis()` 创建 Agent、调用 `Runner.run_sync()`，然后执行 Trace 验证、Observation catalog 提取和领域组合；该函数明确没有自建 Agent Loop（`backend/app/agent_runtime/diagnosis_runtime.py:213-325`）。

实际流程如下：

```text
API request / investigation prompt
        │
        ▼
create_evidence_driven_agent()
        │  SDK Agent + 3 个 local FunctionTool
        ▼
Runner.run_sync()
        │
        ├─ 模型选择工具及参数
        ├─ 工具执行 AnalyticsTools
        ├─ 工具结果作为 Observation JSON 返回上下文
        └─ 模型继续查询，或输出 RuntimeDiagnosisIntent
        │
        ▼
verify_investigation_trace()
        │  工具白名单、call_id 配对、时序、轮次和调用预算
        ▼
extract_observation_catalog()
        │  只接受本次已验证的工具输出
        ▼
runtime_intent_to_drafts()
        │
        ▼
compose_diagnosis_from_observations()
```

Agent 指令明确要求根据 Observation 决定下一步，不规定 Marketplace → ASIN → Traffic Source 的固定顺序（`backend/app/agent_runtime/investigation_runtime.py:346-367`）。当前默认限制为最多 8 次工具调用、10 轮模型响应（`backend/app/agent_runtime/diagnosis_runtime.py:47-49`）。`ToolCallBudgetGuard` 在工具执行前消耗调用额度（`backend/app/agent_runtime/spike.py:82-111`）。

### Current：语义闭包和停止条件

`diagnosis_runtime._verify_primary_driver_semantic_closure()` 要求：如果模型选择的 primary driver 仍声明有直接 driver metrics，则这些直接 driver 必须被观察；如果其中已有异常，也不能提前把中间指标当成最终 driver（`backend/app/agent_runtime/diagnosis_runtime.py:167-210`）。最终 Diagnosis 的成功、无异常、证据不足、预算耗尽和工具失败状态由领域模型和 builder 校验，而不是只信任 Prompt。

### Current：Trace 与动态性证据边界

`verify_investigation_trace()` 检查工具名、ToolCall/ToolCallOutput 的 call ID、先后顺序、每个输出是否属于对应工具以及最终消息输出；`InvestigationRunSummary.tool_trace` 保存本次运行的工具参数和 Observation ID（`backend/app/agent_runtime/investigation_runtime.py:371-585`）。这足以证明 Runtime 设计支持动态多轮调查。

但 `backend/tests/test_investigation_runtime.py` 和 `backend/tests/test_diagnosis_runtime.py` 主要使用 `agents.testing.ScriptedModel` 与 `MagicMock` AnalyticsTools。因此它们验证的是 Runtime 合同和 fail-closed 规则，不是任意真实模型在真实数据上的稳定决策能力。

### Planned：Runtime 边界

保留 OpenAI Agents SDK 作为当前主 Runtime；Jev、Webhook 和可替换 Harness 属于后续独立实验/接入边界，不能在当前架构中冒充已存在的 Runtime。任何替换都必须先有独立决策记录、兼容性验证和对 Driver/Scope/停止条件的比较证据。

## 7. Provenance 与持久化边界

### Current：本次运行内可追溯性

当前可以在内存中沿以下链路回溯：

```text
API request
  → SDK tool_call_id + tool arguments
  → Observation.observation_id / tool_call_id
  → Evidence.observation_id / evidence_id
  → Diagnosis.evidence_ids / change.evidence_id
```

API 的 `_build_live_trace_items()` 只使用 `InvestigationRunSummary.tool_trace` 生成调用身份、顺序、参数和 Observation 归属（`backend/app/api/service.py:379-551`）。这避免把组合工具内部查询误报为模型动作。

### Current：评测 artifact 的有限持久化

`backend/scripts/run_benchmark_evaluation.py` 可以在评测脚本层原子写入脱敏 checkpoint；其内容是 Run 身份、操作计数、结构化 Diagnosis 字段和 Evidence ID，不包含凭据、Provider 原文或原始业务数值（函数 `write_checkpoint_json()`）。仓库中版本化的 `docs/evaluation-artifacts/live-evaluation-2026-09-22.md` 是聚合接受记录，不是产品运行历史或完整 Tool Trace。

### Unknown：尚未具备的产品 provenance

旧同步 API 不持久保存 Run；新任务 API 已可在显式配置下读取持久 Run、工具事实和结果（见 R2-005b2a）。来源身份、环境、data_version/query_reference 已保存，但它们仍不是可重建的完整数据库快照。以下信息没有被统一持久化：

- SQL 文本、SQL hash 或查询执行计划；
- 数据库快照/同步水位及与 data_version 的可重建映射；
- Prompt、模型配置和 Runtime 版本；
- 完整 Observation 原始结果和失败重试关系；
- 用户、权限、租户或审计主体。

`query_or_result_reference` 目前只是 `tool-result:{tool_call_id}` 形式的运行内引用，不等同于可复算的数据快照。

### Planned：持久化责任边界

持久化层已承担 Run 生命周期、状态转换、调查事实和审计引用；Runtime 产生可信摘要，新 API 读取已保存状态。查询快照映射、保留策略、用户权限与部署责任仍需补齐。

## 8. FastAPI 与 React 当前边界

### Current：API

`backend/app/api/routes.py` 当前注册 6 个端点：

| 方法 | 路径 | 当前行为 |
|---|---|---|
| `GET` | `/health` | 返回进程健康和版本信息 |
| `GET` | `/api/metrics/graph` | 从 Registry 生成指标节点和部分依赖/分解边 |
| `GET` | `/api/scenarios` | 返回不含 Ground Truth 答案的 Benchmark 场景目录 |
| `POST` | `/api/scenarios/inject` | 触发 Synthetic 场景注入；无 DB 时可 dry-run |
| `POST` | `/api/scans/daily` | 运行手动全局扫描，只返回候选指标 |
| `POST` | `/api/investigate` | 返回 Fixture Preview 或一次同步 Live 调查结果 |

旧请求/响应结构在 `backend/app/api/schemas.py`。新 `task_routes.py` 提供 POST `/api/investigations`（202）以及 GET 列表/详情；契约在 `task_schemas.py`。默认 `app` 未注入任务服务时返回 503。尚无数据源 CRUD、连接测试、Schema 探索或用户取消/显式重试接口。

R4-001 新增 GET `/api/investigation-sources`：`InvestigationTasksService.list_sources()` 只投影配置的来源身份、版本标签和每项metric/grain/dimensions/supported能力，不开连接或提交任务；不是数据源CRUD、连接健康、刷新状态或日期覆盖接口。默认旧 `app` 未配置任务服务仍503。

`backend/app/main.py:16-29` 配置了开发端口的 CORS，并包含 `allow_origins=[..., "*"]`、全方法和全请求头；当前没有认证/授权中间件，也没有证据表明它托管 Vite 生产静态文件。

### Current：默认 React 产品工作区（R4-002）

`frontend/src/App.tsx` 默认只渲染 `product/InvestigationWorkspace.tsx`。该工作区保留认可原型的五导航区域，调用 `tasks/client.ts::createTaskClient` 的来源目录、任务提交、列表与详情接口。列表分页大小为20；概览状态计数只基于当前来源已加载的本页记录。指标页保留metric/grain/dimensions声明，R4-006新增显式单日/基线读取；数据页仅配置元数据，不探测连接健康/刷新。实验室未接入。

新提交的 queued 任务及所选 queued/running 历史详情每2秒读取详情，终态不继续轮询；API读取错误显示安全错误代码并停止该轮轮询。详情按服务端记录展示 Tool Call、Observation、Evidence、Diagnosis 与失败状态；空 Diagnosis 不会被前端合成。来源切换清理所选详情和显式日期。该 UI 没有取消/重试/追问、固定进度条或 Synthetic 注入操作。

R4-002 主线程最终真实 Edge + 受控 HTTP fixture 验收 PASS，记录见 `evaluation-artifacts/task-workspace-acceptance-2026-10-10.md`。随后R4-003用真实隔离PostgreSQL、独立任务API进程与Edge读回既有Olist失败调查并刷新复读，4工具/27Observation，无写请求/模型/Worker；见 `evaluation-artifacts/postgres-browser-history-acceptance-2026-10-10.md`。R4-005进一步验证浏览器实际POST一次经现有Worker执行Analytics SQL，保存成功的1/1/1/1事实及no_material_anomaly，在新API进程、浏览器刷新后读回；首次验收断言错误与只读resume修正均有记录，见 `evaluation-artifacts/browser-task-roundtrip-acceptance-2026-10-10.md`。Runner受控，不是模型动态调查、异常归因或持续外部数据验收；验收模式没有加入产品Runtime。

### Current：单源指标 Observation 读取（R4-006）

GET `/api/metrics/observation` 经 `metric_read_routes.py` 验证恰好三个参数 source_id/target_metric/target_date；`MetricReadService.read()` 绑定服务端 TaskSourceBinding/Registry/连接工厂，调用既有 AnalyticsTools.query_metric 和 Observation mapper。只读全来源聚合，单日对前七日，filters/group_by固定为空。异源/不支持指标在查询前拒绝；请求/数据库/映射错误返回固定代码，不回显原值。默认未注入服务时503，`task_application api` 显式注入，Worker不变。

原Runner的短事务助手提取为 `analytics/read_connection.py::ShortReadConnection`，Runner继续复用同实现；每次独立只读事务、10秒statement timeout、关闭连接与安全错误。响应保留Decimal字符串/null、UTC查询时间、来源身份和版本标签。`persisted=false`，read-query引用不是已存Tool Trace/Evidence；异常候选仅沿用现有mapper的下降阈值，不是Agent诊断。配置来源绑定不等于分析表物理行隔离，版本标签不等于快照，查询时间不等于上游更新时间。

实际隔离PG经TestClient→API→真实SQL专项4/4通过，状态记录计数未变；Synthetic及公开静态Olist均已验证，详见 `evaluation-artifacts/metric-observation-api-acceptance-2026-10-11.md`。随后前端 `metrics/client.ts` 严格验证GET响应身份、时期、Decimal字符串和状态/candidate一致性；`product/MetricObservationPanel.tsx` 提供显式查询、epoch/Abort清理与原生原始事实明细。目录provider/environment/版本标签冲突时拒绝展示；handoff只填写新调查目标，不POST。实际PG→独立API→生产build→Edge两profile均通过，受控503/延迟故障与实际查询分开记录于 `evaluation-artifacts/metric-observation-ui-acceptance-2026-10-11.md`。没有模型调用、持续连接器、趋势扫描或新迁移。

### Current：来源绑定手动指标扫描（R4-007，后端与桌面页面已验收）

GET `/api/metrics/scan`只接受source_id/target_date，复用同一MetricReadService的单指标读取；服务器从Registry和来源能力选择最多5项，在任何SQL前验证整批能力。每项独立只读短事务，响应snapshot_consistent=false、persisted=false，版本仍为label；不是实时快照、已存Evidence或扫描历史。任一查询失败返回安全503，不返回半份成功结果。只把明确anomalous项列为候选；候选为空不等于其他项正常，保留inconclusive/null/insufficient_evidence。没有自动调查、后台扫描或调度模块。实际Synthetic5项/Olist3项读取及验证边界见 [`source-metric-scan-acceptance-2026-10-11.md`](evaluation-artifacts/source-metric-scan-acceptance-2026-10-11.md)。旧Benchmark Daily Scan未改。

前端`metrics/client.ts`的`createMetricClient.scan()`复用read的安全请求/取消和单项响应验证；拒绝批次来源/日期/provider/environment/version冲突、重复指标/查询引用、伪造或遗漏候选以及非false快照声明。`MetricScanPanel.tsx`在既有业务指标页增加显式日期/扫描，核对目录身份与完整支持指标集合；来源身份/版本/能力key变化时卸载清理，日期变化使用epoch/Abort丢弃旧响应。逐项状态/精确原值/UTC时间及查询引用可展开，带入调查只填表、不POST。实际PG→独立API→build→Edge两profile功能通过，受控503/版本冲突/第二目录来源单独标明，不是模型或持续源验收；记录见 [`source-metric-scan-ui-acceptance-2026-10-12.md`](evaluation-artifacts/source-metric-scan-ui-acceptance-2026-10-12.md)。原单指标查询保留并实际浏览器回归通过。

### Historical：旧同步 Benchmark 工作台

旧工作台组件和 API 客户端仍保留在仓库，旧 App 编排可由 Git 历史读取，不再由默认 `App.tsx` 渲染。旧路径曾包含：

- 指标关系图 `MetricGraph`；
- 诊断卡片 `StructuredDiagnosisCard`；
- 调查轨迹 `InvestigationTimeline`；
- Evidence 看板 `EvidencePortfolio`；
- 追问组件 `ContinueInquiry`；
- Manual Daily Scan 和 Synthetic 场景控制栏。

旧实现通过 `frontend/src/api.ts` 调用同步 Benchmark 端点，使用 React 内存状态，并在启动时自动请求 Fixture Preview。R4-002 已将它从默认 React 路径移除；`api.ts`、旧工作台组件、场景注入与 Fixture Preview 代码仍是仓库历史资产，不是当前默认 UI 的能力。旧同步 Live 路径此前会注入 Synthetic 场景，不能当作外部数据调查。

R4-001 实现的 `frontend/src/tasks/contracts.ts` 与 `client.ts::createTaskClient` 已由 R4-002 默认页面消费，支持来源目录、任务创建/列表/详情；响应经字段/来源身份校验，Decimal保留字符串或数值，错误只暴露安全 code，POST不自动重试。`npm run test:tasks` 使用唯一OS临时编译目录和 Fake Fetch，无新增测试依赖；测试通过只证明客户端合同，不证明真实服务端连接。

### Planned：产品 API/前端的架构责任

未来 API 应负责把数据来源、扫描候选、调查 Run、实时状态、证据链和历史结果作为同一产品边界暴露；前端负责展示来源类型和环境、任务进度、工具调用、证据 provenance、诊断状态及失败原因。新增合同必须建立在已验证的数据能力和持久化模型上，不能先由 UI 数字反推后端事实。

## 9. 测试与评测分层

### Current：已有层次

| 层次 | 当前实现 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 领域单元测试 | `backend/tests/test_metric_registry.py`、`test_observations.py`、`test_evidence*.py`、`test_diagnosis*.py` | 配置校验、状态分类、引用和 Driver+Scope 联合约束 | 真实数据库、真实模型 |
| Analytics 工具测试 | `backend/tests/test_analytics_tools.py` 的 `FakeConnection` | 参数校验、SQL 结果映射、加总/比率计算 | 当前运行 PostgreSQL 的表、权限和数据 |
| SQL Guard 测试 | `backend/tests/test_sql_guard.py` | AST allowlist、只读语句和 LIMIT 规则 | Guard 已被主查询链实际调用（当前未接入） |
| SDK Runtime 测试 | `test_investigation_runtime.py`、`test_diagnosis_runtime.py` 的 `ScriptedModel`/Mock | 动态工具顺序可接受、Trace 配对、预算和结构化输出 fail-closed | 真实 Provider 的决策质量、成本、延迟和稳定性 |
| API 测试 | `backend/tests/test_api.py` 的 patched connection/runtime | 请求 schema、分支和响应映射 | 真实端到端服务、真实凭据和重启恢复 |
| Hermetic Evaluation | `backend/app/evaluation/runner.py` 与 `run_benchmark_evaluation.py --hermetic` | Ground Truth 对显式 Run Outcome 的 Driver、Scope、Exact、Evidence、Unsupported Claim、Tool/Budget 评分 | Agent 是否自己查对了数据；没有 SDK/DB/模型调用 |
| 真实本地集成脚本 | `backend/scripts/verify_phase3_*`、`verify_phase6_*`、Olist 脚本 | 在配置好 PostgreSQL/Provider 时验证真实链路 | 当前环境本次未重新执行；不等于部署可用 |

评测核心 `run_hermetic_evaluation()` 明确不读取文件、不访问数据库、不调用 SDK（`backend/app/evaluation/runner.py:331-361`）。因此通过 Hermetic 评测不能宣称真实模型运行成功。

### Current：真实模型证据口径

仓库包含一份 2026-09-22 的脱敏聚合 Live Evaluation 记录（`docs/evaluation-artifacts/live-evaluation-2026-09-22.md`），记录的是受控 Synthetic Benchmark 上一次兼容 Provider 的聚合结果；原始 Provider 文本、完整 Tool 值和凭据没有版本化。Runtime 代码具备真实 Provider 调用路径，但本次架构审计没有重新配置或执行它。

以上为初始审计时状态。2026-10-10 新任务应用已做一次授权实际SDK尝试，但 `InternalServerError` 导致无完成工具/Diagnosis；不能用历史聚合结果填补新持久调查成功证据，详见本次尝试 artifact。

### Unknown：测试数量和部署级验收

README/任务书与 `docs/agent-state.md` 的历史测试计数来自不同阶段。最新实际测试结果统一查看 `PROJECT_STATUS.md` 和对应 acceptance artifact；离线/Hermetic、真实数据库、真实模型必须分别报告，前端静态结果不能替代浏览器或部署验收。

## 10. 规划架构的责任边界

以下仅记录已经确认的方向和应由哪个边界负责，不预先发明具体表或 endpoint。

### Planned：数据源身份与能力

- Source boundary 负责标识数据来源类型、连接/授权状态、可用时间范围、粒度、维度和指标能力。
- 纯领域能力契约已在 `backend/app/data_sources/capabilities.py`（单测：`backend/tests/test_data_source_capabilities.py`）中实现（Current），支持来源身份、环境隔离、独立指标 grain/维度及跨 grain 组合保护。
- Registry → capability 的适配和 AnalyticsTools 可选前置校验已实现（`backend/app/data_sources/semantic_adapter.py`、`backend/app/analytics/tools.py`）。新任务 API/Source Runner 已绑定能力合同；实际数据库来源发现和外部连接器仍为 Planned。
- Synthetic、Sandbox 和真实外部来源必须可区分，调查 Run 必须引用明确的来源身份。
- 外部 PostgreSQL、Shopify 或其他来源只有在真实接口、权限和粒度验证后才可声明为支持；未验证的指标维度必须保持不可用。

### Planned：staging 与 canonical

- Ingestion boundary 负责接收外部数据并保留原始语义、时间和同步水位。
- Mapping/quality boundary 负责把已验证的数据转换成调查层可消费的 canonical 指标事实，并记录口径差异、缺失和不支持的维度。
- Agent/Analytics boundary 只读取通过验证的数据能力，不直接修改真实来源，也不把前端数字当作业务事件。

### Current：应用状态 Schema 与状态合同（R2-001，已由主线程验收）

- `backend/migrations/001_app_state.sql` 只创建独立的 `app_state` Schema，
  不修改 `warehouse` 或 `olist_validation`。当前包含数据源、同步 Run、调查
  Run、Tool Call、Observation、Evidence、Diagnosis 及其多 Evidence 链接表。
- Run→ToolCall→Observation→Evidence→Diagnosis 通过外键和复合唯一键保持同一
  `investigation_run_id` 的可追溯关系；来源对象和各事实保存 `source_id`、
  `environment`。`002` migration 进一步把事实三元来源外键绑定到所属 Run；
  已在隔离 PostgreSQL 17.11 验证不匹配来源/环境会被数据库拒绝。
- `backend/app/persistence/models.py` 提供不可变 `RunState`、`RunStatus`、
  合法生命周期迁移和 `SourceReference`；`SourceEnvironment` 复用数据源能力
  合同中的 `live`、`sandbox`、`benchmark`、`validation` 枚举。
- `backend/app/persistence/migrations.py` 只读取版本化 SQL 文本；
  `backend/app/persistence/repository.py` 提供只接受现成 connection 的
  参数化 `ApplicationStateRepository`，负责应用状态写入和最小 run 摘要读取。
  Repository 不建立连接、不保存 `DATABASE_URL`、不自动提交事务，也不执行
  migration。`tests/test_persistence_repository.py` 的 Fake connection 只证明
  repository 合同；真实数据库证据另见下述 R2-PG 记录。
- `EvidenceDrivenRunSummary` 在 Runtime 结果上保留经过验证的完整
  `observation_catalog`。`backend/app/persistence/investigation_writer.py` 以单一
  `DataSourceDescriptor` 把该 Runtime Trace、Observation、Evidence 和 Diagnosis
  映射到 Repository，避免每条事实从独立调用参数取得来源身份。写入顺序和所有
  交叉引用先由 Hermetic Spy 测试验证，后由 R2-PG/005b1 真实数据库验证。该 Writer
  已经由 Coordinator 在最小 Worker 中调用，新 FastAPI 任务服务通过 Worker 提交。
- `backend/migrations/002_enforce_investigation_provenance.sql` 是已在隔离测试库执行的
  migration：它把 Tool Call、Observation、Evidence、Diagnosis 的三元来源身份
  外键绑定到 Investigation Run，而不是只验证其单独指向一个存在的 Data Source。
  `pg_constraint` guards 让同一 schema 重复运行时避免重复加约束。文本测试和有限
  SQL parser 本身不能证明执行成功；独立 PostgreSQL 集成测试已验证约束生效与重复执行。
- Repository 还提供条件化 `fail_investigation_run()`，只将受控 failure code 写入
  `failure_details`；Writer 的 `start()`、`complete()` 和 `fail()` 可分别由未来的
  短事务调用。它们不拥有 connection/commit/rollback；现由 Coordinator 和最小
  Worker 调用，新 FastAPI 任务服务已接线；用户取消/显式重试未实现。
- `backend/app/persistence/transaction_coordinator.py` 是当前唯一的 transaction
  owner：它通过注入的 factory 对 start/complete/fail 分别创建短连接事务，并返回绑定
  来源身份的 immutable handle。它不读取 `DATABASE_URL`、不保留 connection，也不
  直接执行模型；最小 Worker 已注入该协调器，新任务 API 通过 Worker 提交。
- `backend/app/persistence/task_execution_service.py` 把一次已注入的 Agent runner
  放在 `start` 与 `complete/fail` 两个 coordinator 调用之间。其输入和 failure code
  都是深度校验、来源绑定和脱敏的；它不是后台 worker、HTTP endpoint 或模型实现，
  受控 Runner 与数据库持久化已验收；后台领取与中断恢复见 R2-005b1，真实模型与用户取消尚未验收。

### Current：R2-PG 验证与安全边界

- `003_immutable_data_source_identity.sql` 在数据库层禁止修改 source_id/provider/environment；Repository upsert 拒绝身份冲突，仅更新同身份元数据。
- `RunState` 和 Repository 一致允许 queued→failed。Coordinator factory 必须提供事务连接（psycopg `autocommit=False`），每次生命周期操作独立 commit/rollback，不跨 Runner 持有事务。
- Repository 不保存 Observation 原始 error_message；非格式合规 error_code 降级为 `tool_error`。Evidence 默认 payload 同样去除错误文本，自定义 payload 拒绝嵌套 error_message（含大小写/分隔符变体）。这不是任意文本通用脱敏器；API/日志和外部接入边界仍需单独保护。
- `tests/test_postgres_persistence_integration.py` 仅显式接入本机专用 `metricsleuth_r2_acceptance`，不会读取应用 `.env`/DATABASE_URL。迁移重复执行，受控 SELECT/Runner 完整持久化、失败、安全文本、身份与来源隔离、真实事务回滚和重新连接：7/7 PASS。
- PostgreSQL 进程重启后成功结果仍可读取；R2-PG 当时未实现的 Worker/checkpoint 已由下述 R2-005b1 补齐。历史验收记录：[`postgres-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/postgres-persistence-acceptance-2026-10-10.md)。

### Current：最小 Worker 与增量工具事实（R2-005b1）

- `persistence/worker.py:InvestigationWorker` 接受显式 connection factory 和 Runner，提供 submit/run_once，不发现配置、启动线程、轮询或调用模型。
- `004_worker_execution_mode.sql` 增加 inline/worker 区分；既有 Run 默认 inline。单 Worker session advisory lock 跨 Runner 存活，但所有事务在模型调用前提交；需要专用物理连接，不可把持锁连接归还普通连接池。
- queued Worker 任务使用行锁原子领取；新 Worker 获锁后将遗留 running Worker 任务标记 `worker_interrupted`，不重放收费调用。inline 不参与该恢复。
- `Coordinator.checkpoint()` 锁定 running Run 的来源/版本，将完整 Trace+Observation 短事务保存。Repository 幂等 INSERT 比较所有显式事实列，拒绝同 ID 不同事实；原错误文本仍不落库。
- `Writer.complete(checkpointed=True)` 验证最终 Summary 包含已保存事实，再严格幂等重放完整目录，写 Evidence/Diagnosis 和 succeeded。事务失败不能抹去之前已提交的步骤；未产生 Diagnosis 时不保存假结果。
- 三个 SDK FunctionTool 与 `run_evidence_driven_diagnosis()` 支持可选同步 progress_callback；回调使用 ToolContext 原始参数和 Observation payload，失败传播，最终 Trace/Diagnosis 校验不变。符合应用拥有持久化、SDK 保持调查循环的边界（[OpenAI SDK 文档](https://developers.openai.com/api/docs/guides/agents/sdk)）。
- 已有库和全新隔离 PostgreSQL 17.11 验证 15/15；SDK callback 专项为 Fake Analytics，无真实模型。记录：[`worker-checkpoint-acceptance-2026-10-10.md`](evaluation-artifacts/worker-checkpoint-acceptance-2026-10-10.md)。新 API 可显式注入该 Worker；默认应用、前端与后台进程尚未配置。

### Current：持久任务/历史 API（R2-005b2a）

- `main.py:create_app()` 显式注入 `InvestigationTasksService`；无配置时任务端点 fail closed（503），不发现凭据、不迁移、不启动线程。旧六端点行为保持不变。
- `api/task_service.py:TaskSourceBinding` 在服务器绑定 descriptor、capabilities 和版本。客户端只提交 source_id、metric、单日日期、filters、group_by；不接受环境、provider、DSN、模型或自由 Prompt。能力校验不等于连接器已验证，也不是用户认证。
- POST 只调用 Worker.submit，不在 HTTP 中运行调查；GET 经 `task_read_repository.py` 的显式投影和 source/environment/worker 条件查询。读事务使用 REPEATABLE READ READ ONLY，独立关闭连接。
- 详情返回 Tool Call、Observation、Evidence 引用与结构化 Diagnosis；不返回 request parameters、failure_details、Evidence payload、原始 error_message。工具参数与结构化业务字段仍需要写入边界验证，不能视为任意文本通用脱敏。
- task 路径输入验证和服务错误只返回固定 code，不回显误传凭据或连接异常。旧端点的错误响应与 wildcard CORS 未在本切片改变，公开部署前必须收紧。
- 真实 PostgreSQL API 专项 4/4、含持久化/Worker 回归 19/19 PASS；HTTP 使用 TestClient，Runner 为受控 SQL，无真实模型/外部源/浏览器/生产部署。证据：[`task-api-acceptance-2026-10-10.md`](evaluation-artifacts/task-api-acceptance-2026-10-10.md)。

### Current：显式应用 Runner/本地启动配置（R2-005b2b，模型待验收）

- `task_application.py` 提供显式环境配置和 `api/worker [--once]` 本地入口；不读 `.env`/旧 DATABASE_URL，不迁移、不准备业务数据。仅允许 loopback 库和 Synthetic Sandbox/Olist静态Validation，不宣称外部PG/Shopify产品接入。
- `source_runner.py:SourceInvestigationRunner` 校验 descriptor/version/metric/date/filters，调用既有诊断 SDK Runtime，传入 model、8次以内工具预算、10轮以内预算和 checkpoint callback。继承原SDK环境bootstrap；每次 RunConfig 禁止tracing导出，不等于业务数据不发送给模型。
- Analytics connection facade 每查询打开独立 READ ONLY 短事务，10秒SQL超时，查询后关闭；不跨模型调用持分析事务。固定filter必须出现在原始工具参数中，不隐式加过滤造成Observation范围失真。
- 本地任务专用API不包含旧注入/同步端点，无wildcard CORS，监听127.0.0.1。默认旧app兼容行为不变，认证/生产部署未完成。
- 数据源upsert省略capabilities保留已有值，显式{}可清空；真实数据库验证。当前能力权威仍是服务器绑定，而不是元数据自动发现。
- 新专项4/4、数据库全回归23/23 PASS：实际Analytics聚合→Observation→checkpoint→受控Diagnosis→API读取，以及只读拒写和独立API进程。模型与外部同步未运行；证据/启动合同：[`task-application-acceptance-2026-10-10.md`](evaluation-artifacts/task-application-acceptance-2026-10-10.md)。
- 版本标签不是数据库snapshot，不同短事务可能看见并发更新。应用Worker现绑定Runner的来源身份，仅领取/恢复自己的任务；不自动路由混合来源，也不提供用户授权或共用宽表的物理分析隔离。队列隔离实际PG验收见 [`worker-source-isolation-acceptance-2026-10-10.md`](evaluation-artifacts/worker-source-isolation-acceptance-2026-10-10.md)。快照和分析只读角色仍待落实。

### Planned：真实 SDK/模型与数据版本验收

一次实际授权尝试已执行但未通过：`InternalServerError`，0工具/0Observation/0Diagnosis，失败状态及新应用重读正常；详见 [`live-task-persistence-attempt-2026-10-10.md`](evaluation-artifacts/live-task-persistence-attempt-2026-10-10.md)。不应把 SDK 接线已实现或错误请求已发出解释为真实模型成功。

- Run boundary 负责任务状态、并发/重试/取消和重启恢复。
- 写入服务必须从 Investigation Run 的已持久化来源身份派生 Tool Call、Observation、
  Evidence 与 Diagnosis 的 `source_id/environment`，不得相信调用者重复提交的
  独立来源字段。
- 运行中状态需要明确的短事务与 worker 领取策略；不得为一次可能耗时的模型调用
  持有数据库事务，也不得以成功响应代替数据库确认。
- Evidence boundary 负责把每条 Observation 绑定到工具调用、来源版本和可复算查询上下文。
- Diagnosis boundary 继续保留当前 fail-closed 的 Driver、Scope、Negative Control 和因果边界；持久化不能绕过这些校验。

### Planned：部署和安全

- Deployment boundary 负责进程生命周期、数据库连接池/超时、密钥注入、日志脱敏、TLS/反向代理和备份恢复。
- Read-only 数据库权限必须由数据库/部署边界落实，不能只依赖静态 SQL Guard。
- API 访问控制、来源隔离和错误信息脱敏在产品化前必须有明确责任归属。

### Planned：实验环境

- Sandbox boundary 负责隔离可控数据变化、实验元数据、重置和清理。
- Sandbox 不能写入真实外部来源，也不能污染生产/Live 数据；实验结果必须带来源类型标记。

## 11. 可直接复用与不可混淆的部分

### Current：可以直接复用

- `MetricRegistry` 的严格配置校验和指标依赖/驱动关系模型；
- `build_capabilities_from_registry()` 的指标 dimensions/grain 能力映射及 AnalyticsTools 可选契约校验；
- `AnalyticsTools` 的参数化查询、单日/七日基线和聚合比率语义；
- SDK Runtime 的 Tool Budget、Trace 验证、Observation catalog 和 Structured Output；
- Evidence promotion、Diagnosis builder/composition 的 fail-closed 规则；
- Evaluation 的分层评分、运行失败/预算耗尽区分及 Olist 隔离验证脚本；
- React 工作台中的 Trace、Evidence 和 Diagnosis 展示组件。

### Current：不能直接当作产品能力

- `warehouse/anomaly_injector.py`：只属于 Synthetic Benchmark/Sandbox，不能代表真实数据更新；
- `_run_mock_investigation()`：只提供 Fixture Preview，不是模型或数据库调用；
- `docs/evaluation-artifacts/live-evaluation-2026-09-22.md`：是历史聚合记录，不是可查询的产品 Run 历史；
- `SqlGuard`：已实现并测试，但未接入 `AnalyticsTools` 主路径；
- Olist `olist_validation` Schema：隔离验证资产，不是默认产品数据源；
- `docs/agent-state.md`、`README.md` 中的“已完成/MVP”措辞：必须结合源码和证据边界阅读，不能替代部署事实。

## 12. 当前限制、开放问题和维护规则

### Current

1. 默认 Registry 仍绑定一个宽表和一套 Synthetic/Amazon 维度；虽已有可选 capability contract 适配，不同真实数据源/粒度仍未完成来源验证和连接器接入。
2. Live API 会先注入 Synthetic 场景，真实外部数据闭环尚不存在。
3. 新任务服务能重连读取历史，默认React已消费新任务API，真实PostgreSQL→HTTP→浏览器失败历史及受控新提交成功记录已验收；新模型成功调查闭环仍未通过。
4. SQL 安全组件与 Analytics 主链脱节，数据库只读角色也没有由 API 自动保证。
5. CORS、认证、错误暴露和生产部署配置仍是开发环境状态。
6. 前端保留五个原型导航区并接入持久任务，已分别验收受控HTTP交互和实际PostgreSQL历史读取；指标趋势、外部连接/刷新与实验操作未接线，真实长Decimal/大量维度结果需要可读性改进。

### Planned

下一次实现工作应先围绕数据源隔离、持久化 provenance 和真实纵向闭环推进；除非这些边界完成并有评测依据，不扩展多 Agent、第二 Runtime、Jev、Webhook 或第二行业 Profile。

### Unknown

以下问题在开始相应开发前必须用实现或真实接口验证，而不是在文档中猜测：

- 首个真实数据源及其可支持的 metric × dimension × grain 矩阵；
- canonical 数据口径和刷新/延迟承诺；
- Run/Observation/Evidence/Diagnosis 的保留、脱敏和查询需求；
- 个人服务器的数据库、反向代理、TLS、备份和认证条件；
- 原型交互接入真实 API 后的验收结果；当前静态示例不是运行证据。

维护本文件时，新增能力必须同时补充：源码入口、数据/状态边界、测试层次和“能证明/不能证明”说明。任何规划中的表、接口、第三方连接器或部署组件，只有实现并通过相应验收后才能从 `Planned` 移到 `Current`。
