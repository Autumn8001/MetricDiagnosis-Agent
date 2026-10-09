# MetricSleuth 架构说明

> **Status：Current + Planned boundary**
> 审计日期：2026-10-09
> 审计代码版本：`main`（R1-001 已提交；R1-002 已由主线程验收，随本次提交落库）
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
FastAPI JSON → React Diagnosis Workspace
```

它已经具备一条可测试的“指标查询—动态调查—证据校验—结构化诊断”内核，但产品 API 仍围绕本地 Synthetic Benchmark 场景组织。它不是已经完成的多数据源、持久化、认证和生产部署平台。

当前最重要的复用点是 `MetricRegistry`、`AnalyticsTools`、Agents SDK Runtime、Observation/Evidence/Diagnosis 领域约束及 Evaluation 评分器；当前最重要的架构缺口是数据源身份、应用状态持久化、完整 provenance、外部数据接入和部署边界。

### Planned

后续目标是在不重写调查内核的前提下，补齐以下边界：

- 外部数据源与 Synthetic/Sandbox 的身份和环境隔离；
- 原始数据到可调查 canonical 指标数据的责任分层；
- Run、Tool Call、Observation、Evidence、Diagnosis 的持久化与恢复；
- 可长期运行的安全部署、密钥注入、访问控制和运维边界。

具体数据库表名、迁移方案和新增 API 尚未在当前架构中确定，不能从本节推导为已实现合同。

### Unknown

- 当前个人服务器上是否已经存在可连接的 PostgreSQL 实例、其中实际有哪些表和数据，本次未连接验证。
- 已认可的独立 HTML 产品原型不在本仓库中；仓库中可确认的是 `frontend/index.html` 这一 Vite 挂载壳，不足以代表完整原型。
- Shopify、外部用户 PostgreSQL、Webhook 和 Jev 尚未进入当前 Runtime/API。
- 生产反向代理、TLS、认证、密钥管理和进程监管方案尚未落地。

## 2. 证据边界与仓库地图

### Current：代码和配置的事实来源

当文档、测试和实现冲突时，当前行为以可执行源码和配置为准；测试说明验证边界，不能把 Mock 通过解释为生产运行。

| 区域 | 当前职责 | 主要证据 |
|---|---|---|
| 指标语义 | 读取并校验 YAML，建立只读内存 `MetricRegistry` | `configs/metrics.yaml`；`backend/app/metrics/registry.py:60-153` |
| 数据源能力契约 | 纯领域不可变来源身份、环境与指标 grain/维度能力模型；可由 Registry 适配，并由 AnalyticsTools 可选校验（尚未接入 API/DB） | `backend/app/data_sources/capabilities.py`；`backend/app/data_sources/semantic_adapter.py`；`backend/tests/test_semantic_adapter.py` |
| Warehouse | Synthetic 数据 Schema、Seed 和异常注入 | `warehouse/schema.sql`；`warehouse/seed.py`；`warehouse/anomaly_injector.py` |
| 分析工具 | 根据 Registry 校验参数并执行 PostgreSQL 聚合；传入能力契约时在 SQL 前做来源能力校验 | `backend/app/analytics/tools.py:20-178` |
| SQL 安全 | 独立的 `sqlglot` AST 校验器和 LIMIT/allowlist 规则 | `backend/app/sql_safety/guard.py:49-251` |
| 可信中间事实 | `MetricQueryResult` 转不可变 `Observation` | `backend/app/analytics/models.py:18-71`；`backend/app/observations/mapper.py:45-187` |
| 证据和诊断 | Observation 显式提升为 Evidence，再组合为 Diagnosis | `backend/app/evidence/promoter.py:13-57`；`backend/app/diagnosis/composition.py:80-106` |
| Agent Runtime | Agents SDK 工具桥、Trace 审计、结构化诊断意图 | `backend/app/agent_runtime/investigation_runtime.py`；`backend/app/agent_runtime/diagnosis_runtime.py` |
| API 服务 | FastAPI 路由和进程内业务编排 | `backend/app/api/routes.py:30-116`；`backend/app/api/service.py` |
| 前端 | React + TypeScript + Vite 单页工作台 | `frontend/src/App.tsx`；`frontend/src/api.ts`；`frontend/vite.config.ts` |
| Evaluation | 纯评分、操作状态、Evidence/Unsupported Claim 评分和评测脚本 | `backend/app/evaluation/`；`backend/scripts/run_benchmark_evaluation.py` |

### Current：实际技术栈

- 后端：Python `>=3.12`、FastAPI、Uvicorn、Pydantic 2、`psycopg`、PyYAML、`sqlglot`，以及 `openai-agents==0.22.0`（`backend/pyproject.toml:1-17`）。
- 数据库：PostgreSQL 连接实现。仓库声明的 Synthetic Schema 不是外部用户数据库接入机制。
- 前端：React 19、TypeScript 6、Vite 8，原生 CSS；依赖和脚本见 `frontend/package.json:1-23`。
- 应用形态：当前没有可确认的 Dockerfile、Compose、迁移目录、应用 ORM 或生产静态资源托管配置。

### Unknown：验证口径

本次文档整理没有执行真实模型调用、没有连接数据库、没有启动线上服务。`README.md`、`任务书.md` 和 `docs/agent-state.md` 对测试数量及 Live Evaluation 的描述存在时间/版本差异（例如 453 与 455 的测试数）；这些历史记录会在 Evaluation 小节标明边界，不作为本次新鲜运行证据。

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

`warehouse/olist_validation_schema.sql` 和 `backend/scripts/load_olist_validation.py` 使用独立的 `olist_validation` Schema，包含订单、订单明细和按日订单价值的验证对象。`configs/olist_validation_metrics.yaml` 只用于 Olist 工具兼容性验证；该 Profile 不被 `backend/app/api/service.py` 的默认 Runtime/API 加载，也不替换 Synthetic Profile。

Olist 证据只说明部分真实公开订单数据可以映射到受控指标工具。它不能证明当前系统已经支持任意外部 PostgreSQL，也不能提供当前 Amazon Profile 缺失的 `sessions`、`traffic_source` 或 `asin` 语义。

R1-003 新增的 `build_olist_validation_capabilities()`（`backend/app/data_sources/olist_validation.py`）把该 Profile 表达为 `OLIST + VALIDATION` 的纯内存能力合同：三个指标的 grain/dimensions 由 Olist Registry 适配而来，`sessions` 与 `conversion_rate` 被显式声明为 unavailable。`backend/scripts/verify_olist_tool_compatibility.py` 将这份合同传给 `AnalyticsTools`，因此支持指标的非法维度会在 SQL 前失败；这项能力只由本地 Hermetic 测试证明，不代表已完成 Olist 数据库连接、同步或持续外部接入。

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

**当前边界明确：** 能力契约与语义 Registry/AnalyticsTools 已完成纯内存适配；Olist 当前仅完成基于既有验证资产的合同表达和本地 Hermetic 验证，仍未接入 API、数据库来源发现、外部连接器、同步水位或持续真实外部数据验证。适配器也不证明传入 descriptor 对应的物理来源已经连接或同步。

### Planned：数据模型责任边界

未来数据接入需要由数据源层负责**源身份、权限、刷新状态和能力声明**；由数据处理层负责**原始/中间数据与 canonical 指标数据的隔离、映射和质量校验**；由调查层只消费通过契约的数据能力。具体表名、列名和迁移方式待真实数据验证后确定。

### Unknown：当前模型不能表达的内容

- 当前 Registry/source table 已可通过纯内存适配器生成 capability contract，但默认 API 尚未注入 source descriptor/capabilities，运行时查询仍受限于旧版单表假设。
- 当前数据库和 API 仍未持久化 `source_id`、快照、水位或同步版本字段。
- 当前没有应用层 Analysis Session、Run、Observation、Evidence、Diagnosis 的数据库 Schema 或迁移。

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
React App 内存状态与工作台组件
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

当前没有可供 API/前端查询的持久 Run 记录，因此无法在服务重启后恢复一次调查。以下信息也没有被统一持久化：

- SQL 文本、SQL hash 或查询执行计划；
- source identity、数据库快照/同步水位、数据版本；
- Prompt、模型配置和 Runtime 版本；
- 完整 Observation 原始结果和失败重试关系；
- 用户、权限、租户或审计主体。

`query_or_result_reference` 目前只是 `tool-result:{tool_call_id}` 形式的运行内引用，不等同于可复算的数据快照。

### Planned：持久化责任边界

持久化层应成为 Run 生命周期、状态转换、调查事实和审计引用的权威来源；Runtime 负责产生可信的运行摘要，数据访问层负责提供查询/快照 provenance，API 负责状态读取和恢复。具体存储对象、索引、迁移和历史保留策略需在实现前单独确认。

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

请求/响应结构定义在 `backend/app/api/schemas.py:80-221`。没有数据源 CRUD、连接测试、Schema 探索、Run 列表/详情、历史结果恢复或异步任务接口。

`backend/app/main.py:16-29` 配置了开发端口的 CORS，并包含 `allow_origins=[..., "*"]`、全方法和全请求头；当前没有认证/授权中间件，也没有证据表明它托管 Vite 生产静态文件。

### Current：前端

`frontend/src/App.tsx:144-379` 是无 Router 的单页 Diagnosis Workspace，包含：

- 指标关系图 `MetricGraph`；
- 诊断卡片 `StructuredDiagnosisCard`；
- 调查轨迹 `InvestigationTimeline`；
- Evidence 看板 `EvidencePortfolio`；
- 追问组件 `ContinueInquiry`；
- Manual Daily Scan 和 Synthetic 场景控制栏。

前端仅通过 `frontend/src/api.ts:33-75` 调用上述 6 个端点，状态使用 React 内存 state；没有历史导航、持久化缓存、来源管理、实验室页面或独立工作概览页面。应用启动时会自动请求一个 `mock_mode: true` 的 Fixture Preview（`frontend/src/App.tsx:203-220`），该结果是静态展示契约，不代表真实 Agent Run。

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

### Unknown：测试数量和部署级验收

README/任务书中的历史测试计数与 `docs/agent-state.md` 的较新计数不同。当前工作区实际运行后端全量测试为 490/490 PASS（包含 R2-001/R2-002 专项），前端 lint 与 TypeScript `--noEmit` 的历史结果仍需单独复核；这些仍是离线/Hermetic 与静态验证，不是当前生产数据库、真实外部数据持续刷新、浏览器部署或重启恢复的验收证据。

## 10. 规划架构的责任边界

以下仅记录已经确认的方向和应由哪个边界负责，不预先发明具体表或 endpoint。

### Planned：数据源身份与能力

- Source boundary 负责标识数据来源类型、连接/授权状态、可用时间范围、粒度、维度和指标能力。
- 纯领域能力契约已在 `backend/app/data_sources/capabilities.py`（单测：`backend/tests/test_data_source_capabilities.py`）中实现（Current），支持来源身份、环境隔离、独立指标 grain/维度及跨 grain 组合保护。
- Registry → capability 的纯内存适配和 AnalyticsTools 可选前置校验已实现（`backend/app/data_sources/semantic_adapter.py`、`backend/app/analytics/tools.py`；单测：`backend/tests/test_semantic_adapter.py`、`backend/tests/test_analytics_tools.py`）。API、实际数据库来源发现和连接器集成仍为 Planned。
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
  `environment`，并由复合外键验证每条记录引用的是一个有效来源环境。当前尚未
  用跨记录约束保证该来源环境一定等同于所属 Investigation Run；R2-003 的应用
  服务边界必须先执行该一致性检查，后续真实迁移再评估是否追加数据库约束。
- `backend/app/persistence/models.py` 提供不可变 `RunState`、`RunStatus`、
  合法生命周期迁移和 `SourceReference`；`SourceEnvironment` 复用数据源能力
  合同中的 `live`、`sandbox`、`benchmark`、`validation` 枚举。
- `backend/app/persistence/migrations.py` 只读取版本化 SQL 文本；
  `backend/app/persistence/repository.py` 提供只接受现成 connection 的
  参数化 `ApplicationStateRepository`，负责应用状态写入和最小 run 摘要读取。
  Repository 不建立连接、不保存 `DATABASE_URL`、不自动提交事务，也不执行
  migration。`tests/test_persistence_repository.py` 的 Fake connection 只证明
  repository 合同，不代表 PostgreSQL 迁移、真实写入或重启恢复已成功。
- `EvidenceDrivenRunSummary` 在 Runtime 结果上保留经过验证的完整
  `observation_catalog`。`backend/app/persistence/investigation_writer.py` 以单一
  `DataSourceDescriptor` 把该 Runtime Trace、Observation、Evidence 和 Diagnosis
  映射到 Repository，避免每条事实从独立调用参数取得来源身份。写入顺序和所有
  交叉引用先由 Hermetic Spy 测试验证；该 Writer 尚未连接 FastAPI/worker，不能
  当作运行中任务进度、实际事务提交或重启恢复的证据。
- `backend/migrations/002_enforce_investigation_provenance.sql` 是尚未执行的后续
  migration：它把 Tool Call、Observation、Evidence、Diagnosis 的三元来源身份
  外键绑定到 Investigation Run，而不是只验证其单独指向一个存在的 Data Source。
  `pg_constraint` guards 让同一 schema 重复运行时避免重复加约束。文本测试和有限
  SQL parser 读取不能证明 PostgreSQL 已执行此 migration 或其中约束已经生效。
- Repository 还提供条件化 `fail_investigation_run()`，只将受控 failure code 写入
  `failure_details`；Writer 的 `start()`、`complete()` 和 `fail()` 可分别由未来的
  短事务调用。它们不拥有 connection/commit/rollback，也未被 FastAPI 或 worker
  调用，因此当前没有任务领取、重试、运行中进度或真实事务边界。
- `backend/app/persistence/transaction_coordinator.py` 是当前唯一的 transaction
  owner：它通过注入的 factory 对 start/complete/fail 分别创建短连接事务，并返回绑定
  来源身份的 immutable handle。它不读取 `DATABASE_URL`、不保留 connection，也不
  直接执行模型；API/worker 尚未注入这个协调器。

### Planned：应用状态与运行时接线（R2-005）

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
3. 应用 Run 只在请求生命周期内存在，服务重启后没有历史恢复能力。
4. SQL 安全组件与 Analytics 主链脱节，数据库只读角色也没有由 API 自动保证。
5. CORS、认证、错误暴露和生产部署配置仍是开发环境状态。
6. 前端是单页调查工作台，不是已接线的五页面完整产品。

### Planned

下一次实现工作应先围绕数据源隔离、持久化 provenance 和真实纵向闭环推进；除非这些边界完成并有评测依据，不扩展多 Agent、第二 Runtime、Jev、Webhook 或第二行业 Profile。

### Unknown

以下问题在开始相应开发前必须用实现或真实接口验证，而不是在文档中猜测：

- 首个真实数据源及其可支持的 metric × dimension × grain 矩阵；
- canonical 数据口径和刷新/延迟承诺；
- Run/Observation/Evidence/Diagnosis 的保留、脱敏和查询需求；
- 个人服务器的数据库、反向代理、TLS、备份和认证条件；
- 产品原型文件的实际页面和交互合同。

维护本文件时，新增能力必须同时补充：源码入口、数据/状态边界、测试层次和“能证明/不能证明”说明。任何规划中的表、接口、第三方连接器或部署组件，只有实现并通过相应验收后才能从 `Planned` 移到 `Current`。
