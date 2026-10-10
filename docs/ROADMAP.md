# MetricSleuth MVP Roadmap

> 状态：当前长期实施计划
> 更新日期：2026-10-10
> 审查基线：`main` / `eba3d1846d08876df42c9730289009875dd73dc0`；R2-PG 在其后新增独立提交
> 目标来源：[`PRODUCT.md`](PRODUCT.md)
> 架构边界：[`ARCHITECTURE.md`](ARCHITECTURE.md)

## 1. 路线原则

> 先证明一个真实、可恢复、可追溯的数据调查闭环，再扩展自动触发、策略研究和更多行业。

- 保留并复用当前调查内核，不重写 OpenAI Agents SDK Runtime。
- 电商继续作为首个验证领域，但新基础设施使用来源身份和指标能力表达，不把 Amazon 字段写成平台永久定义。
- PostgreSQL 继续承担分析数据与应用状态的主要持久化基础；真实数据、Sandbox 和 Synthetic 必须隔离。
- Shopify 是首个持续外部数据源的优先候选，必须先通过真实权限和粒度验证；Olist 用于低风险验证映射与导入边界，不冒充持续数据源。
- 外部 PostgreSQL 作为重要接入方式保留，但在没有真实目标库前不先建设复杂通用映射平台。
- 不用微服务、Kafka、Kubernetes、Redis 或多 Agent 来弥补尚未完成的基本产品闭环。

## 2. 阶段总览

| 阶段 | 状态 | 目标 | 依赖 |
|---|---|---|---|
| R0 认知与权威基线 | 已完成 | 统一产品、架构、路线和动态状态文档 | 无 |
| R1 数据源契约与能力验证 | 进行中 | 确定来源隔离、指标粒度和首个真实连接器 | R0、数据源验证资源 |
| R2 持久化应用基础 | 进行中 | 保存数据源、同步、调查、证据和结果状态 | R1 契约 |
| R3 首个持续真实数据闭环 | 待开展 | 从真实外部源持续更新可调查数据 | R1、R2 |
| R4 产品 API 与冻结原型接线 | 进行中（R4-001 合同基础完成） | 五个产品页面由真实 API 和持久状态驱动 | R2；完整验收依赖 R3，映射/任务接线不必等待外部凭据 |
| R5 隔离实验室 | 待开展 | 在 Sandbox 中制造可控变化且不污染真实源 | R2、R3 |
| R6 真实评测与可靠性 | 待开展 | 可复算地验证模型、Driver/Scope/停止条件 | R3、R5 |
| R7 服务器部署与运营验收 | 待开展 | 安全、可恢复地长期运行完整产品 | R3、R4、R6 |
| R8 扩展研究 | 暂缓 | Jev、Webhook 自动触发、可替换 Harness | MVP 完成 |

## 3. R0 — 认知与权威基线

**状态：已完成（2026-10-09）**

### 目标

让未来的新对话无需重读全部历史即可准确接管，并停止沿旧任务书自动扩展 Benchmark Demo。

### 当前阻碍

- 历史文档把 `任务书.md` 设为唯一最高权威。
- “Portfolio MVP 已完成”与最新真实数据、持久化、完整 Web 和部署目标冲突。
- 测试数量和真实模型证据口径存在历史漂移。

### 技术方案与模块

- 精简 `AGENTS.md`。
- 建立 `PRODUCT.md`、`ARCHITECTURE.md`、`ROADMAP.md`、`PROJECT_STATUS.md`。
- 保留旧文档作为历史证据，不删除或静默改写历史结果。

### 验收标准

- 五份入口文档职责无重叠、互相引用一致。
- 明确 Current、Confirmed、Planned、Deferred 和 Unknown。
- 工作区只包含预期文档修改，Markdown diff 无格式错误。

## 4. R1 — 数据源契约与能力验证

**状态：进行中**

### 子任务进展

- **R1-001｜Data Source Capability Contract**：已完成并由主线程验收。实现了最小纯领域契约 `SourceProvider`、`SourceEnvironment`、`DataSourceDescriptor`、`MetricCapability`、`DataSourceCapabilities`（对象级与嵌套容器级不可变，支持指标独立 grain/维度快照、跨 grain 组合保护和严格 fail-closed 校验；源码：`backend/app/data_sources/capabilities.py`，单测 `backend/tests/test_data_source_capabilities.py` 6/6 PASS；全量回归 461/461 PASS）。明确尚未接入真实外部 PostgreSQL 或 Shopify，尚未接入现有 Runtime/API/DB。
- **R1-002｜电商核心指标 metric × dimension × grain 矩阵定义与适配**：已完成并由主线程验收。`configs/metrics.yaml` 的五个 Synthetic 核心指标显式声明 `date × asin × marketplace × traffic_source` atomic grain；`MetricRegistry` 严格校验显式 grain 并为旧配置提供明确 fallback；`backend/app/data_sources/semantic_adapter.py` 保留 Registry 中的 dimensions/grain；`AnalyticsTools` 可选接收能力契约并在 SQL 前 fail-closed 校验。主线程专项测试 51/51、全量回归 466/466 PASS；未接入真实数据库、Shopify 或 API。
- **R1-003｜Olist 隔离资产能力契约验证与降级表达**：已完成并由主线程验收。`configs/olist_validation_metrics.yaml` 的三个指标显式声明 `date × customer_state` grain；`build_olist_validation_capabilities()` 复用 Registry 适配器，并将 `sessions`/`conversion_rate` 显式标为 unavailable；Olist 工具兼容性脚本绑定该合同。主线程确认绑定合同后，漏斗指标和非法维度均在 SQL 前 fail-closed；新增 5 个本地 Hermetic 测试。未验证 Olist 数据库连接、同步或持续外部接入。
- **R1-003 后续数据库验收（2026-10-10）**：现有公共 CSV 在隔离 PostgreSQL 导入、映射及 Analytics 查询已实际通过；四步受控调查保存 27 Observation，失败后新应用读回，未伪造 Diagnosis。证据见 [`olist-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/olist-persistence-acceptance-2026-10-10.md)。这更新了 R1-003 当时未验证数据库的边界，不代表持续同步或 Olist 模型验收。
- **R1-004a｜来源资料比较与选择门**：已完成（2026-10-10）。官方资料/源码和资源条件核对后，用户确认暂无业务PostgreSQL、可准备Shopify开发店；下一外部验证对象为 `shopify / sandbox`，不是生产经营数据。指标/权限/版本发布方案与资源清单见 [`data-source-selection.md`](data-source-selection.md)。没有外部API、模型或连接器验收。
- **R1-004b｜Shopify只读 capability spike**：待开展。账号/专用开发店/应用只读权限尚待用户准备；先核对Orders分页/字段/覆盖和错误脱敏，Sales/AOV需口径确认，Sessions/Conversion默认不支持。通过实际API gate后才进入最小抓取→版本发布→SQL调查切片。

### 目标

在写连接器前确认什么数据能被可靠调查，并决定首个持续真实数据源。

### 当前阻碍

- 当前默认 Registry 仍绑定单一 Synthetic 宽表；R1-002 已为该表显式表达 atomic grain，但 Shopify 的订单、销售和会话数据可能具有不同 grain，尚未据此声明支持。
- 来源身份/环境/版本标签和持久任务边界已实现并在隔离数据库验证；仍缺真实持续源和可复算数据快照。
- 用户可准备Shopify开发店，但账号/店/应用权限尚未实际提供；暂无业务PostgreSQL。开发店不能等同live生产来源，最终经营数据验收仍需授权真实源。

### 技术方案

1. 定义来源能力契约：来源身份、环境、时间范围、刷新方式、指标、维度、grain、延迟、币种和时区。
2. 为当前 Synthetic Profile 的 Sales、Orders、AOV、Sessions、Conversion Rate 建立 metric × dimension × grain 矩阵；Country、Product、Traffic Source 等外部来源能力仍待真实接口验证。
3. 用现有 Olist 资产验证契约可以表达“支持、缺失、不可推导”。
4. R1-004a资料比较已完成；据用户资源选择Shopify开发店先验证平台接口，保留PostgreSQL作为未来获授权业务来源。真实调用前明确账号/只读权限/测试订单覆盖，不假设具备。
5. 先完成真实订单API gate，再建设一个最小版本发布与现有调查内核接线；不先做通用映射平台、漏斗拼接、重型同步调度或Webhook。

### 涉及模块

`backend/app/metrics/`、`backend/app/analytics/`、`configs/`、Olist 验证脚本，以及后续数据源领域模块。

### 验收标准

- 形成版本化能力矩阵和来源契约。
- 每个指标只暴露真实来源支持的维度。
- 明确首个持续数据源及失败降级方案。
- 不需要把凭据提交到仓库。

## 5. R2 — 持久化应用基础

**状态：进行中（R2-001 至 R2-005a、R2-PG、R2-005b1、R2-005b2a 已验收；R2-005b2b 应用 Runner 与启动配置已受控验收，真实模型待验收）**

### 目标

让调查任务、证据和同步状态在服务重启后仍可恢复，并为真实数据与 Sandbox 隔离提供单一事实源。

### 当前阻碍

- 旧同步 API 和旧 React Benchmark 状态仍为进程/页面内存态；新任务 API 在显式配置下可读写持久状态，R4-002 默认 React 页面已使用新 API。
- 默认旧 `app` 没有自动注入持久服务；显式 task application 本地 Runner 已配置可用，但真实模型成功 gate 未通过。
- 单 Worker 领取与中断终结已验收；用户取消/显式重试及服务器进程生命周期未实现。

### 技术方案

- 继续使用 PostgreSQL，不另引入 Redis 或消息中间件。
- 分离应用状态、来源 staging、canonical analytics、synthetic/sandbox 的数据库责任边界。
- 持久化最小生命周期：Data Source、Sync Run、Investigation Run、Tool Call、Observation、Evidence、Diagnosis。
- 每次查询保存脱敏参数、来源/数据版本、query hash、耗时和结果引用；敏感凭据只保存安全引用，不进入业务表或日志。
- 首版采用简单、可恢复的数据库状态机和单 worker 领取任务；并发扩展留到有实际负载证据之后。

### R2-001：应用状态 Schema 与领域状态机

**状态：已完成并由主线程验收**

- 新增只读可定位的 `backend/migrations/001_app_state.sql`，以独立的
  `app_state` Schema 保存 `data_sources`、`sync_runs`、`investigation_runs`、
  `tool_calls`、`observations`、`evidence` 和 `diagnoses`，并用
  `diagnosis_evidence` 表表达多 Evidence 引用。
- 新增 `backend/app/persistence/` 纯 Python 状态合同：`RunStatus`、合法
  生命周期迁移、终态封闭、`SourceReference` 和既有
  `SourceEnvironment` 枚举复用。
- 新增 Hermetic migration shape/unit tests。此切片只证明 SQL 文本结构和
  领域状态机；未执行迁移，没有 repository、API、worker、重启恢复或真实
  PostgreSQL 持久化验收。

### R2-002：应用状态 Repository

**状态：已完成并由主线程验收**

- 新增 `backend/app/persistence/repository.py`，只接受调用方已经建立的
  DB-API connection；不读取或保存 `DATABASE_URL`，不自动 commit、rollback
  或执行迁移。
- repository 使用参数化 SQL 支持 data source upsert、queued investigation
  run、条件状态迁移、Tool Call、Observation、Evidence、Diagnosis 及
  `diagnosis_evidence` 链接，并提供 run 摘要读取。
- 所有 JSON payload 在 SQL 前递归检查 JSON 可序列化性和敏感 key；来源环境、
  数据版本和 query reference 随事实保存。`tests/test_persistence_repository.py`
  使用 Fake connection 验证参数化、事务边界、状态条件、来源传递和证据链顺序。
- 本切片仅为 Hermetic repository 合同测试；未执行实际 migration、未接线
  FastAPI/Agent Runtime、未证明真实 PostgreSQL 持久化或重启恢复。
- 当前 Schema 会验证每条事实所引用的来源与环境有效，但尚未在数据库层强制其
  与所属 Investigation Run 的来源完全一致；这项跨记录 provenance 一致性约束
  是 R2-003 的明确责任，不能将现有合同测试表述为完整的持久化保证。

### R2-003：审计结果持久化编排边界

**状态：已完成并由主线程验收**

- `EvidenceDrivenRunSummary` 现在保留完整、不可变的 `observation_catalog`；它会
  在 Runtime 边界验证 catalog 的 ID 顺序、每条 Observation 的 Tool Call/Tool Name
  与已验证 Trace 完全对应，避免在后续持久化时只剩 Evidence 或 Diagnosis。
- `backend/app/persistence/investigation_writer.py` 新增
  `EvidenceDrivenRunPersistenceWriter`。它只接收一个 `DataSourceDescriptor`，从该
  单一上下文派生所有事实的 source/environment；写入顺序为 source、queued run、
  running、Tool Call/Observation、Evidence、Diagnosis、succeeded。
- Writer 在首次 repository 写入前重新验证 Trace、Observation、Evidence、Diagnosis
  的交叉引用；repository 抛错会原样上抛且不会标记 succeeded。它不连接数据库、
  不执行 migration、不会 commit/rollback，事务仍由未来 API/worker 调用方拥有。
- 单元测试为 Fake/Spy repository 合同测试。它证明来源派生、调用顺序与 fail-closed
  边界，不代表运行中进度保存、失败持久化、真实 PostgreSQL 或 API 产品接线。

### 验收标准

- 调查从 queued/running 进入明确终态，重复请求不会产生不可控重复副作用。
- 服务重启后可查询任务、历史和结果。
- 失败保存已经发生的 Tool Call 与 Observation，不伪造成功结果。
- Synthetic/Sandbox/真实来源不能交叉引用。

### R2-004a：数据库层 provenance 约束

**状态：已完成并由主线程验收；迁移未执行**

- `backend/migrations/002_enforce_investigation_provenance.sql` 为
  `investigation_runs` 与 `tool_calls` 增加可引用的复合唯一键，并让 Tool Call、
  Observation、Evidence、Diagnosis 的 `(investigation_run_id, source_id, environment)`
  分别外键指向同一个 Investigation Run。
- 每个 `ADD CONSTRAINT` 都通过 `pg_constraint` catalog 检查保护；迁移只触及
  `app_state`，不删除数据、不改 warehouse/Olist、也不包含凭据列。
- 测试验证 SQL 文本、约束命名、目标三元键和可发现性。未实际执行 PostgreSQL
  migration；SQL 解析器对 `DO $$` 只作为通用 Command 接受，不能替代真实数据库
  语法/约束验收。

### R2-004b：运行生命周期原语

**状态：已完成并由主线程验收；未接线事务 owner**

- `ApplicationStateRepository.fail_investigation_run()` 使用参数化、条件化 SQL，仅
  允许 queued/running → failed，并只写入受控 `failure_code` 的
  `{"code": "..."}` JSON；自由异常信息、stack trace、连接串和凭据没有 API。
- `EvidenceDrivenRunPersistenceWriter` 拆为 `start()`、`complete()`、`fail()`：前者
  只写 source→queued→running，后者只写完整 facts→succeeded，失败则只委托受控
  分类。`write()` 保持兼容，并在已有完整 Summary 时先验证再开始 Run。
- 这为未来短事务调用提供原语，但每次调用如何建立、commit/rollback、重试和领取
  工作仍未实现；所有证据仍是 Fake/Spy repository 合同测试。

### R2-004c：显式短事务协调器

**状态：已完成并由主线程验收；未接线 API/worker**

- `InvestigationTransactionCoordinator` 仅持有一个可注入 connection factory；每次
  `start`、`complete`、`fail` 都新建 Repository/Writer、成功后 commit 一次、异常时
  best-effort rollback，并在 finally 释放连接。连接不会跨模型调用或跨公开方法保存。
- 不可变 `InvestigationRunHandle` 把 run ID、DataSourceDescriptor、data version
  绑定在一起；complete/fail 没有独立 source/environment 参数。commit 后的 close
  清理异常不会被误报为可安全重试的持久化失败。
- 测试全部使用 Fake Connection；验证连接独立性、commit/rollback/close、commit 与
  cleanup 异常以及真实 Repository/Writer 的参数化组合。没有真实 connection factory、
  PostgreSQL、API 或 worker 运行证据。

### R2-005a：单任务执行服务

**状态：已完成并由主线程验收；未接线 HTTP/worker**

- `InvestigationTaskExecutionService` 将每个任务编排为
  `coordinator.start → injected runner → coordinator.complete/fail`；Runner 始终位于
  两个短事务之间，服务自身不保存连接、不读环境变量、不创建线程或网络连接。
- `InvestigationTaskRequest` 是 immutable 的来源绑定输入，并递归拒绝敏感 key 与
  非 JSON 参数；普通 Runner 异常使用固定安全分类，显式 `TaskExecutionFailure` 只可
  带受控 code，原始异常/stack trace 不会进入持久化事实。
- start 失败不调用 Runner，complete 失败不覆盖为 failed。Fake/Spy 测试只证明服务
  调度边界，不能证明真实 Agent、Worker、PostgreSQL 或 API 的任务执行。

### R2-PG：审查修复与真实 PostgreSQL 持久化验收

**状态：已完成并由主线程真实数据库验收（2026-10-10）**

- 目标：在继续 Worker 前证明现有持久化代码能够执行，而非继续依赖 Fake/Spy。
- 修复：数据源身份不可变（Repository 条件 upsert + `003` 触发器），统一 `queued → failed`，Observation/Evidence 错误文本保护。
- 依赖与模块：既有 migrations/Repository/Writer/Coordinator/Task Service；新增 opt-in PostgreSQL 集成测试，不更换 Runtime。
- 验收：隔离 PostgreSQL 17.11 上 migrations 001–003 重复执行；真实 SQL 七项测试通过，包含完整受控调查、来源隔离、状态、回滚、重连和错误文本；进程重启后结果读取成功。
- 边界：不是外部业务数据同步、真实模型或 Worker 验收。此前切片中的“未执行 migration”是其历史完成时状态。
- 记录：[`postgres-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/postgres-persistence-acceptance-2026-10-10.md)。

### R2-005b1 — 最小 Worker、失败前事实与恢复

**状态：已完成并由主线程验收（2026-10-10）**

- `InvestigationWorker` 只负责 submit/run_once；PostgreSQL session advisory lock 保证单 Worker，`FOR UPDATE SKIP LOCKED` 领取一个任务。不引入进程池、重试平台或消息中间件。
- 每个完整工具结果用独立短事务 checkpoint；同 ID 同事实可重放，不同事实拒绝。完成结果不能遗漏已保存步骤。
- 中断 Worker 任务安全终结，不自动重放模型；inline 任务隔离。真实子进程突然退出后前序步骤仍存在，无伪造 Diagnosis。
- 现有 SDK tools/Diagnosis Runtime 可选 progress_callback，保留原始参数和最终验证；真实模型运行仍待验。
- 验收：真实 PostgreSQL 15/15，离线回归 552 tests / OK (skipped=1)，SDK 回调 5/5（Fake Analytics，无模型）。记录见 [`worker-checkpoint-acceptance-2026-10-10.md`](evaluation-artifacts/worker-checkpoint-acceptance-2026-10-10.md)。

### R2-005b2 — 产品任务/历史 API 与应用 Runner 接线

**状态：进行中；R2-005b2a 已验收；R2-005b2b 已实现并受控数据库验收，真实模型待验收**

- **R2-005b2a（已完成）**：POST `/api/investigations` 排队，GET 列表/详情读取状态、已保存步骤和结果；服务器绑定 source/provider/environment/capabilities/version，客户端不提供连接配置。FastAPI `create_app()` 显式注入服务；默认返回 503，不启动 Worker、不执行迁移、不注入 Scenario。
- 主线程真实 PostgreSQL 验收：API 专项 4/4、含既有 Worker/持久化回归 19/19 PASS；新应用实例读取历史、失败步骤留存、跨来源 404、安全错误和非法能力拒绝均通过。Runner 为受控 SELECT，非真实模型。记录见 [`task-api-acceptance-2026-10-10.md`](evaluation-artifacts/task-api-acceptance-2026-10-10.md)。
- **R2-005b2b（已实现，受控验收通过）**：`task_application.py` 提供仅本机的显式配置与 API/Worker 启动入口；`source_runner.py` 复用 AnalyticsTools、SDK Runtime 和进度回调，不注入场景、不新增调度框架。日期/固定 filters 硬约束与单查询只读短事务；任务专用 API 排除旧注入端点。真实数据库新专项 4/4 PASS，实际聚合 SQL/Observation、写入拒绝、元数据保留和独立 API 进程均验证。记录见 [`task-application-acceptance-2026-10-10.md`](evaluation-artifacts/task-application-acceptance-2026-10-10.md)。
- **下一验收**：明确非生产模型凭据/模型/调用预算和稳定数据版本后，经真实 SDK 完成一次 API 排队→Worker→SQL→步骤→Diagnosis→历史读取；保存脱敏逐 Run 证据。未通过前不标记 R2 全部完成。并检查真实来源的快照/只读角色与单源队列边界，避免继续增加无运行证据的基础模块。
- **2026-10-10 首次真实SDK尝试：未通过**。用户一次性授权后沿用现有模型/端点，SDK 返回 `InternalServerError`；无完成工具、Observation、Evidence 或 Diagnosis，失败任务和新应用重连读取正常。此次授权已使用，不自动重试；先确认端点可用性再经新授权复验。记录见 [`live-task-persistence-attempt-2026-10-10.md`](evaluation-artifacts/live-task-persistence-attempt-2026-10-10.md)。不因此改写 Runtime 或引入新的调度模块。
- **单源队列边界补验（2026-10-10，已通过）**：应用Worker绑定Runner来源，只领取/恢复自己的任务；共享状态库的Synthetic/Olist交叉排队、running恢复及错误provider绑定在实际PG验证。保持原全局锁和短事务，无新调度机制。数据库回归26/26、离线605 tests / OK (skipped=3)；见 [`worker-source-isolation-acceptance-2026-10-10.md`](evaluation-artifacts/worker-source-isolation-acceptance-2026-10-10.md)。不是多租户授权、分析快照或模型成功。
- 服务 allowlist 不是用户授权；公开部署前仍需认证、收紧 CORS、隔离旧开发端点、日志/响应脱敏。用户取消与显式重试按真实展示需求确定，不先扩展通用任务框架。

- 将执行服务接到明确的单 worker/任务入口，而不是直接把长模型调用塞入同步 HTTP
  处理器；先定义任务创建、查询、失败和取消边界，再选择可恢复的最小进程模型。
- 接线前必须明确迁移执行的受控环境与 connection factory 的配置归属。失败必须保留
  已发生的状态与安全的失败分类，但不得保存凭据、完整连接串或模型原始敏感输出。
- 显式本地API/Worker入口已由R2-005b2b实现；尚无生产进程托管或默认应用/前端配置。不连接部署数据库，迁移仍只在明确的隔离测试环境执行。
- 依赖：R2-PG 已通过；后续开发继续使用隔离数据库，不扩展通用调度平台。
- 复用已验收的领取/恢复/checkpoint；先提供提交、状态、历史与事实详情接口，明确 source/metric/time-range 的授权和能力校验。
- API 的真实数据库验收必须包含排队、成功/失败、已保存步骤读取与服务重新连接；Mock 测试不替代这些场景。
- 再用明确配置的受控模型与数据验证应用 Runner，不把可选 callback 接线当作真实模型成功。

## 6. R3 — 首个持续真实数据闭环

**状态：待开展**

### 目标

完成“外部数据更新 → 指标变化 → 手动启动调查 → Evidence → 保存结果”的真实纵向闭环。

### 当前阻碍

- 现有 Live API 在调查前注入 Synthetic Scenario。
- Olist 是静态验证数据；Shopify 和外部 PostgreSQL 尚无产品连接器。
- 当前 Semantic Layer 不能自然表达多个 fact grain。

### 技术方案

- 根据 R1 选择结果实现一个连接器，不同时建设多套连接器。
- 采用 source-specific staging，再转换为受控 canonical analytics 表或视图；Agent 不直接访问原始第三方响应。
- 增量同步使用明确 checkpoint、水位和幂等 upsert；提供安全重跑与对账。
- Live Investigation 只选择已接入来源和目标指标，不调用 Scenario Injector。
- 先支持被真实验证的指标；Sessions/Conversion Rate 等不能可靠对齐时保持 unavailable。

### 验收标准

- 两次或以上增量同步能正确推进水位且重复执行不重复计数。
- Daily Scan 和 Agent 查询的是外部源更新后的数据。
- 至少一次真实模型调查保存完整 Trace、Observation、Evidence 和 Diagnosis。
- 调查结果可从保存的来源版本和查询引用复核。

## 7. R4 — 产品 API 与冻结原型接线

**状态：进行中；R4-001/002已完成；R4-003真实PostgreSQL→API→浏览器既有失败历史读取通过，新模型调查与完整产品仍待验收**

### R4-001 — 任务客户端与配置来源目录（已完成）

- 目标：页面可消费持久调查合同，并从服务器允许列表获取来源/指标能力，不猜 source_id 或沿用原型的硬编码范围。
- 方案/模块：`frontend/src/tasks/` 提供 sources/submit/list/detail及响应校验；`GET /api/investigation-sources` 投影现有 TaskSourceBinding，纯读内存，不探测连接、不查询日期、不执行模型。
- 依赖：既有R2任务API、来源能力合同；不依赖外部凭据，不更改迁移/Worker/Runtime。
- 主线程验收：客户端18/18、后端目录/API/应用24/24、离线612 tests / OK(skipped=3)、前端lint/类型/build通过。记录见 [`task-frontend-contract-acceptance-2026-10-10.md`](evaluation-artifacts/task-frontend-contract-acceptance-2026-10-10.md)。不是浏览器、真实数据库或模型验收。

### R4-002 — 原型调查工作区接线（受控 HTTP 浏览器验收完成）

- 目标：保留原型五个导航区域，将默认 React 页面接入来源目录和持久调查任务 API。
- 实现：`frontend/src/App.tsx` 渲染 `InvestigationWorkspace`；页面读取来源、提交任务、分页读取列表及详情；queued/running 详情每2秒轮询，终态或详情读取错误后不继续轮询。结果来自服务端持久事实；无取消、自动重试、追问、固定进度或页面实验注入。
- 页面语义：概览计数只涵盖所选来源当前一页（最多20条）；指标页显示服务端配置能力目录而非趋势/计算值；数据页显示来源配置而非连通性、健康或同步状态；实验室已明确显示尚未接线。
- 验证边界：主线程最终真实 Edge + 受控 HTTP fixture PASS，覆盖来源/能力渲染、历史翻页、成功与失败历史事实、失败不伪造 Diagnosis、单次提交/轮询和终态停止、来源切换及服务不可用错误。客户端18/18、API/应用24/24、lint/类型/build通过。无 PostgreSQL、外部数据或模型参与。记录：[`task-workspace-acceptance-2026-10-10.md`](evaluation-artifacts/task-workspace-acceptance-2026-10-10.md)。
- 下一数据库读取切片已由 R4-003 完成，见下节。另行保留真实 SDK 成功持久化 gate，不能以受控 Runner 替代。

### R4-003 — 真实 PostgreSQL 历史浏览器读取（已验收）

- 目标/依赖：验证既有 R4-002 页面确实能从 R2 持久化和实际 API 读取历史；使用既有 Olist 静态验证记录，不新建业务能力。
- 方案/模块：`frontend/scripts/verify-postgres-workspace.mjs` 启动真实 Edge 与只允许GET的本机静态/代理服务，读取显式 `task_application api`；没有 fixture、Worker、模型、迁移或数据写入。
- 主线程验收：既有失败调查4个Tool Call / 27个Observation / 0Evidence / 0Diagnosis；页面事实与API一致，刷新复读通过；直接SQL与API首条GMV 16861.09/13355.61一致。浏览器写请求0、前后数据库计数相同，API和隔离PG验收后均停止。lint/脚本语法检查通过；见 [`postgres-browser-history-acceptance-2026-10-10.md`](evaluation-artifacts/postgres-browser-history-acceptance-2026-10-10.md)。不是新的模型成功调查、实时外部源或完整R4。
- 后续阻碍/顺序：R1-004a资料比较已完成，下一步R1-004b只读Orders probe，实际调用待专用开发店与应用权限；真实模型成功gate需新的授权。依据此次真实数据，后续UI切片改善Decimal显示和维度记录分层，同时保留原始值/引用；不扩展调度或重画原型。

### 目标

在不重新设计产品的前提下，让工作概览、业务指标、AI 调查工作区、数据接入和实验室成为可操作页面。

### 当前阻碍

- 原型已提供并冻结；原型的固定进度、追问、取消及实验注入不等于已有后端能力。
- 默认 React 调查工作区已接入 task API，R4-003已通过真实 PostgreSQL → HTTP → 浏览器的既有失败历史读取；新的完整模型调查与成功Diagnosis页面仍未验收。
- 概览异常指标/真实趋势、外部数据源连接与刷新 API、可执行 Sandbox Lab 尚未实现；任务应用仍需显式环境配置，默认旧 `app` 不自动注入任务服务。

### 技术方案

- 按已提供原型与 PRODUCT.md 第4节映射实施，保持设计风格和交互结构，不凭描述重画 UI。
- 调查使用持久任务 API；页面显示服务端实际状态、事实、错误与历史，不用进度动画代替执行记录。
- 保持未接线功能明确标注；来源目录能力不能解释为连接状态，实验行为不能通过前端数字模拟。
- 保留旧 Benchmark API/组件作为历史资产，但默认 UI 不依赖它们。

### 验收标准

- 五个页面都有真实或明确标记的 Sandbox 数据来源。
- 刷新浏览器或重启服务后历史调查仍存在。
- UI 不把 fallback/mock 内容表现为真实业务结果。
- 真实调查不再暴露 Benchmark 场景选择器或注入动作。

R4-002受控UI与R4-003真实数据库历史读取不代表完整R4条件满足；真实模型调查、持续外部来源、指标异常数据和Lab仍未通过产品验收。

## 8. R5 — 隔离实验室

**状态：待开展**

### 目标

允许用户在隔离环境制造可控指标变化，并通过与真实数据相同的处理和调查链验证 Agent。

### 技术方案

- 复用 Synthetic Benchmark 生成器和异常注入器，但绑定专用 Sandbox source/environment。
- 实验记录保存输入、数据版本、期望范围和产生的调查 Run。
- 禁止修改真实来源或用前端覆盖数字模拟变化。

### 验收标准

- Sandbox 数据物理或强逻辑隔离。
- 实验可重复、可清理、可追溯。
- 同一调查 API 可面向真实来源或 Sandbox，结果明确显示来源。

## 9. R6 — 真实评测与可靠性

**状态：待开展**

### 目标

让真实模型表现可重复、可比较且能诚实呈现失败。

### 技术方案

- 保留现有 Synthetic Regression，并增加未用于调参的 Holdout 和真实数据验证集。
- 重复报告补齐 No-anomaly Accuracy、Unsupported Claim Rate 和失败 Run 实际调用数。
- 增加 Next Action 与 Stop Condition 指标：过早停止、冗余调用、证据充分后的停止及时性。
- 保存脱敏 per-run 评分输入、模型/Prompt/数据版本和 Trace 引用。

### 验收标准

- 报告可从版本化输入独立重算。
- Mock、Hermetic、Synthetic Live、真实外部数据结果分开展示。
- 失败仍进入分母，且不会被记成零调用来扭曲成本指标。

## 10. R7 — 服务器部署与运营验收

**状态：待开展**

### 目标

在个人服务器上安全、稳定地提供完整 Web 产品。

### 技术方案

- 单仓库、少进程部署：Web/API、后台 worker、PostgreSQL；容器化与反向代理在此阶段定稿。
- 提供最小认证、TLS、生产 CORS、Secret 注入、结构化日志、健康检查、备份和恢复。
- 明确数据库迁移、升级、回滚和安全停机流程。
- 以服务器重启、任务中断、第三方限流和数据库暂时不可用作为验收场景。

### 验收标准

- 通过公网浏览器完成数据接入、同步、扫描、调查和历史查看。
- 重启后状态恢复；备份恢复经过演练。
- 密钥不出现在仓库、响应、日志或前端包中。
- 有可重复部署说明和最终演示脚本。

## 11. R8 — 扩展研究

**状态：Deferred**

- Jev：作为 `Investigation State → Next Action` 的实验策略，与现有 LLM 策略按正确率、调用数、耗时和成本比较。
- Webhook：在同步与幂等边界稳定后，用于外部事件接收、自动触发和结果通知。
- 可替换 Harness：在当前 Runtime 接口和评测数据成熟后，再用 ADR 比较 Codex、DeepSeek 等执行机制。
- 第二行业：只有首个真实电商闭环完成后，才用真实需求验证通用边界。

这些方向不得阻塞 R1～R7。

## 12. MVP Definition of Done

只有同时满足以下条件，才能称为本轮认可的 MVP：

1. 至少一个真实外部业务源可重复接入并持续更新。
2. 用户可在浏览器发现指标变化并主动启动真实 Agent 调查。
3. Agent 根据真实 Observation 动态选择工具，并在预算内终止。
4. Tool Trace、Observation、Evidence、Diagnosis 与来源数据版本被持久保存。
5. Driver 和 Scope 能追溯到同一条支持 Evidence，因果边界明确。
6. Synthetic/Sandbox 与真实数据隔离，实验可重复且不污染真实环境。
7. Mock、Hermetic、真实模型和真实数据评测结果严格分开。
8. 五个原型页面形成连贯产品体验。
9. 系统可在个人服务器安全部署，重启后任务和历史不丢失。
10. 仓库提供可重复测试、部署、备份恢复和演示说明。
