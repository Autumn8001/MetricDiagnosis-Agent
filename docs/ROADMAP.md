# MetricSleuth MVP Roadmap

> 2026-10-15桌面增量验收：真实模型成功历史经实际PG/API/Edge显示与刷新重读通过，0写请求，数据库计数不变。复用只读浏览器脚本新增成功模式，无业务UI重构。证据：[成功记录回读](evaluation-artifacts/live-model-browser-readback-2026-10-15.md)。随后已出现浏览器新提交→真实Worker/SDK持久化证据，单进程终态轮询复跑仍待；R6少量重复评测、R3外部源及R7部署继续待完成。

> 2026-10-15新增：浏览器实际提交一笔带 `asin` 固定范围的 Synthetic 任务，真实 Worker/SDK/Analytics 持久化为 `succeeded`，安全SQL为5/8/6/1，后续独立只读API/Edge刷新重读同一记录通过。首次一体化服务在Worker返回后提前退出，浏览器无法在同一存活服务里轮询终态；harness已改为等待浏览器完成信号，但未为修复再消费第二笔模型调用。故R4真实模型链路已具备实际运行证据，单进程自动轮询的验收复跑仍待明确授权。见[专项记录](evaluation-artifacts/live-model-browser-submission-2026-10-15.md)。

> 2026-10-15最新验收：R2真实模型执行/持久化单次成功 gate 已通过（最终版3轮/2工具/5 Observation/5 Evidence/1 Diagnosis，新应用读回一致）。修复任务固定过滤器的模型可见Schema，保留后端拒绝越界与异常传播。691项离线回归通过，跳过6项。R6重复语义评测、持续外部来源和部署仍未完成。下一切片是桌面真实模型结果读取；不扩展任务调度。证据：[任务范围验收](evaluation-artifacts/live-model-task-scope-2026-10-15.md)。下文早期“真实模型待验收”为历史阶段状态。

> 状态：当前长期实施计划
> 更新日期：2026-10-15
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
| R2 持久化应用基础 | 基础切片验收通过 | 保存数据源、调查、证据和结果；持续同步的接入仍依赖R3 | R1 契约 |
| R3 首个持续真实数据闭环 | 待开展 | 从真实外部源持续更新可调查数据 | R1、R2 |
| R4 产品 API 与冻结原型接线 | 进行中（任务/指标/扫描/Lab已接线） | 五个产品页面由真实 API 和持久状态驱动；持续来源接线仍待R3 | R2；完整验收依赖 R3 |
| R5 隔离实验室 | 核心切片已验收（R5-004） | 隔离发布/API/桌面操作/调查关联已有真实PG与受控Runner证据；不等于模型验收 | R2；基础切片无需等待R3凭据 |
| R6 真实评测与可靠性 | 进行中（单次模型成功，重复评测待开展） | 可复算地验证模型、Driver/Scope/停止条件 | 基础依赖R2/R5；外部源评测依赖R3 |
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
- **R1-004b｜Shopify只读 capability spike**：离线准备完成，真实API验收待开展。新增独立 `backend/scripts/probe_shopify_orders.py`，固定HTTPS/query/API版本、read_orders先行、UTC日期窗口、最多5页/无重试/响应大小限制和脱敏汇总；不写DB/平台数据、不运行模型。主线程专项18/18 PASS，全部使用MockTransport/patch，不是外部API证据。运行与资源见 [`shopify-orders-probe.md`](shopify-orders-probe.md)。账号/专用开发店/应用只读权限尚待用户准备；实际分页/字段/覆盖未验收，Sales/AOV需口径确认，Sessions/Conversion默认不支持。通过实际API gate后才进入最小抓取→版本发布→SQL调查切片。
- **2026-10-11资源操作说明已补齐**：同组织Dev店/Dev Dashboard应用、read_orders版本发布与安装、client credentials短期Token及草稿转Orders的准备步骤，复用上述指南，不新增第二份认证文档。现有probe仅接收Access token，不实现交换/刷新；资源就绪后明确授权有限交换及读取。首轮少量订单权限/字段gate不等待8天，后续指标比较仍需真实历史覆盖，不伪造。离线守卫复验18/18，官方资料已核对；用户账号未实际演练，资源仍未提供。

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

**状态：基础切片已验收（真实PG/Worker/API/单次真实SDK成功）；重复语义评测归R6，持续来源与部署仍未完成。下列早期切片保留当时的验证范围。**

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

**状态：API/应用接线及单次真实模型持久化已验收；完整浏览器同进程复跑与重复语义评测仍待完成。**

- **R2-005b2a（已完成）**：POST `/api/investigations` 排队，GET 列表/详情读取状态、已保存步骤和结果；服务器绑定 source/provider/environment/capabilities/version，客户端不提供连接配置。FastAPI `create_app()` 显式注入服务；默认返回 503，不启动 Worker、不执行迁移、不注入 Scenario。
- 主线程真实 PostgreSQL 验收：API 专项 4/4、含既有 Worker/持久化回归 19/19 PASS；新应用实例读取历史、失败步骤留存、跨来源 404、安全错误和非法能力拒绝均通过。Runner 为受控 SELECT，非真实模型。记录见 [`task-api-acceptance-2026-10-10.md`](evaluation-artifacts/task-api-acceptance-2026-10-10.md)。
- **R2-005b2b（已实现，受控验收通过）**：`task_application.py` 提供仅本机的显式配置与 API/Worker 启动入口；`source_runner.py` 复用 AnalyticsTools、SDK Runtime 和进度回调，不注入场景、不新增调度框架。日期/固定 filters 硬约束与单查询只读短事务；任务专用 API 排除旧注入端点。真实数据库新专项 4/4 PASS，实际聚合 SQL/Observation、写入拒绝、元数据保留和独立 API 进程均验证。记录见 [`task-application-acceptance-2026-10-10.md`](evaluation-artifacts/task-application-acceptance-2026-10-10.md)。
- **下一验收**：明确非生产模型凭据/模型/调用预算和稳定数据版本后，经真实 SDK 完成一次 API 排队→Worker→SQL→步骤→Diagnosis→历史读取；保存脱敏逐 Run 证据。未通过前不标记 R2 全部完成。并检查真实来源的快照/只读角色与单源队列边界，避免继续增加无运行证据的基础模块。
- **2026-10-10 首次真实SDK尝试：未通过**。用户一次性授权后沿用现有模型/端点，SDK 返回 `InternalServerError`；无完成工具、Observation、Evidence 或 Diagnosis，失败任务和新应用重连读取正常。此次授权已使用，不自动重试；先确认端点可用性再经新授权复验。记录见 [`live-task-persistence-attempt-2026-10-10.md`](evaluation-artifacts/live-task-persistence-attempt-2026-10-10.md)。不因此改写 Runtime 或引入新的调度模块。
- **2026-10-15 真实SDK兼容性尝试：未通过**。更新后的配置已通过`/v1/models`、最小文本、工具声明和生成结构化Schema四项直接探测，但现有 Agents SDK 调查仍在首个工具调用前返回`UserError`；0工具/Observation/Evidence/Diagnosis，失败Run及新应用/SQL复核正常，测试库已停止。下一步先比对 SDK 实际请求/响应参数与兼容端点行为，再做最小适配；不引入第二套 Runtime。记录见 [`live-model-sdk-compatibility-2026-10-15.md`](evaluation-artifacts/live-model-sdk-compatibility-2026-10-15.md)。
- **2026-10-11新授权前置探测：未通过**。根目录.env读取与显式SDK配置匹配；一次无重试、256输出上限的工具协议请求返回401，未获得usage/工具结果，因此没有执行完整调查或创建Run，也没有修改CPA服务。需用户本机确认客户端访问密钥/授权，修复后另行确认有限探测/调查。验收工具增加独立持久引用链检查与明确semantic_evaluation=not_evaluated；旧受控成功及旧401失败记录实际PG只读复验符合预期，不把它们当新模型成功。见 [`live-model-preflight-and-provenance-2026-10-11.md`](evaluation-artifacts/live-model-preflight-and-provenance-2026-10-11.md)。Shopify资源明确尚未准备，持续源仍待实际gate。
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

**状态：进行中；任务/指标/扫描/Lab已接线，真实模型成功记录桌面回读已通过；同进程完整复跑、持续外部来源页面与最终产品验收仍待完成。**

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

### R4-004 — 数值与调查明细阅读（已验收）

- 目标/依赖：改善R4-003真实记录暴露的长Decimal/大量维度阅读问题；只改前端，不改指标计算、Runtime或持久化。
- 实现：字符串精确数值格式化（最多4位小数、千分位、非零舍入标明≈），原始数值/区间/筛选/维度/Observation与Tool Call引用保留在原生details；第一条默认展开，其他按需展开，全部Observation仍呈现。相对变化保留原始比率，不添加推测币种/百分比。
- 主线程验收：格式10/10、客户端18/18、lint/类型/build通过；真实Edge受控HTTP验证键盘展开/长小数/大整数/null与既有任务行为PASS。既有Olist实际PG→API→Edge重新读取27Observation通过，数据库计数未变、0写请求，测试进程已停止。见 [`investigation-readability-acceptance-2026-10-10.md`](evaluation-artifacts/investigation-readability-acceptance-2026-10-10.md)。没有新模型、商店调用或成功Diagnosis验收。

### R4-005 — 浏览器新提交与成功持久结果（受控验收完成）

- 目标/依赖：R4-004后，验证浏览器提交→实际任务API→现有Worker→Analytics SQL→成功Diagnosis回读及刷新；独立专用PG库，受控Runner只在验收工具注入，不作为产品模型替身，不建立新执行机制。
- 实现/验收：既有迁移001–004与warehouse schema；稳定Synthetic八天sales100，浏览器实际POST一次成功，1/1/1/1事实与no_material_anomaly保存。API进程重启、新连接及浏览器刷新复读通过；桌面/移动端无横向溢出。首次脚本断言两处错误记录并修正，只读resume完成，无重复提交或删除数据。见 [`browser-task-roundtrip-acceptance-2026-10-10.md`](evaluation-artifacts/browser-task-roundtrip-acceptance-2026-10-10.md)。
- 边界：不验证真实模型动态选择、异常Driver/Scope、持续来源或不可变快照。实际商店Orders gate等待用户资源；真实模型成功gate需新的授权。R4仍进行中，不借受控验收宣布MVP完成。
- 下一阶段：按用户要求本切片收尾供查看；下一轮优先模型成功gate与开发店Orders实际能力验证，有资源后才设计最小数据版本发布/更新，不扩展调度框架。

### R4-006 — 单源单指标读取（后端与页面已验收）

- 目标/依赖：复用R1能力合同、现有Analytics SQL/Observation与R2连接边界，让业务指标页获得可查询的实际值；不依赖模型/开发店凭据，不扩展任务编排。
- 技术方案/模块：metric_read service/schema/routes、显式task_application API接线；原只读连接助手提取复用。GET仅source_id/target_metric/target_date，全来源单日对前7日；固定安全错误、Decimal/null与未持久化查询引用。
- 已验收：主线程实际隔离PG4/4，Synthetic和Olist静态数据、无数据/异源/不支持指标与状态表计数不变；记录 [`metric-observation-api-acceptance-2026-10-11.md`](evaluation-artifacts/metric-observation-api-acceptance-2026-10-11.md)。不是模型、持续来源、趋势或Diagnosis验收。
- 页面已验收：沿用原型，显式选指标日期，值/基线/缺数据/安全失败展示；来源key、请求epoch/Abort清过期响应，响应与目录身份/版本不一致时拒绝。带入调查仅填写，不自动POST。主线程Synthetic/Olist实际PG→独立API→build→Edge两profile均PASS，各4真实读取、1受控503、1延迟旧响应、0写尝试；客户端31/31、任务18/18、格式10/10、lint/类型/build、后端专项31/31。独立视觉复核ship（仅修正旧产品文档）；见 [`metric-observation-ui-acceptance-2026-10-11.md`](evaluation-artifacts/metric-observation-ui-acceptance-2026-10-11.md)。不是持续源、真实模型或趋势验收，整个R4仍进行中。
- 外部依赖仍在：模型401鉴权与新的调用授权；Shopify开发店/read_orders实际gate。资源具备后优先验证，不继续增加同步底座。

### R4-007 — 来源绑定手动指标扫描（后端、客户端与桌面页面已验收）

- 目标/依赖：复用R4-006单指标读取，让所选来源支持的指标一次比较单日与前7日；不依赖模型/Shopify凭据，不新增计算器或调度框架。
- 方案/模块：metric_read service/schema/routes与main安全校验。GET `/api/metrics/scan`只收source_id/target_date，最多5项、批次先验证能力，逐项使用既有只读短事务；失败返回安全错误而非部分结果。明确snapshot_consistent=false、persisted=false、版本为label；无扫描历史、自动调查或新迁移。
- 已验收：主线程隔离PG7项及离线27项组合34/34；后端全量Ran668 / OK(skipped=4)。Synthetic5指标、Olist3指标，缺数为证据不足/null，异源拒绝，状态表计数未变；PG停止且数据保留。首次实际测试缺数断言错误已记录并修正，未改变产品语义。详见 [`source-metric-scan-acceptance-2026-10-11.md`](evaluation-artifacts/source-metric-scan-acceptance-2026-10-11.md)。不是持续数据或模型验收。
- 页面已验收（2026-10-12）：沿用冻结原型，显式日期/扫描、逐项原值与状态、来源明细、候选/未知计数及仅填表handoff；来源/版本/能力key与epoch/Abort清过期结果。Synthetic/Olist实际PG→独立API→build→Edge两profile均PASS，各7次真实scan GET批次、1受控503、1受控版本冲突、2延迟响应、1受控目录切换、0写请求；默认单指标浏览器回归通过。真实PG7/7，客户端58/58、任务18/18、lint/类型/build；独立桌面复核ship，原型hash不变，测试API/PG已停。首次键盘测试缺字符事件已修并保留记录；见 [`source-metric-scan-ui-acceptance-2026-10-12.md`](evaluation-artifacts/source-metric-scan-ui-acceptance-2026-10-12.md)。不是模型/持续更新/新Diagnosis验收。
- 客户端准备已验收（此前独立切片）：createMetricClient.scan复用read的传输/单项验证，增加整批身份/版本/唯一性/候选精确校验与两个安全错误码。该切片离线58/58，不替代本次实际页面验收；记录仍保留原验证边界。
- 后续优先级：模型鉴权修复与新的调用授权、开发店Orders实际gate仍优先于扩大底座。资源未就绪时复用既有Synthetic隔离资产推进R5的最小数据实验闭环；不得伪造持续真实数据。桌面Web为当前MVP验收范围，暂不做手机端专项；用户提供5h额度百分比，接近75%先收尾，不以测试数量维持进度。

### 目标

在不重新设计产品的前提下，让工作概览、业务指标、AI 调查工作区、数据接入和实验室成为可操作页面。

### 当前阻碍

- 原型已提供并冻结；原型的固定进度、追问、取消及实验注入不等于已有后端能力。
- 默认 React 调查工作区已接入 task API，R4-003已验证既有失败历史读取、R4-005已验证新提交与成功Diagnosis页面的受控实际SQL闭环；新的完整模型调查仍未验收。
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

**状态：R5-001至R5-004已完成相应真实PG/受控验收；Lab端到端真实模型评测、外部来源和部署仍待开展。**

### R5-002 — 专用空库首次发布与真实SQL回读（已验收）

- 目标/方案：复用既有内存生成器和warehouse schema，显式Synthetic/Sandbox身份、loopback库名/端口与实际连接校验、空目标守卫和事务锁；产品数据与manifest同事务发布，非空拒绝而非重置。
- 模块：`backend/app/sandbox/dataset_writer.py`及两份专项测试；现有MetricReadService/scan不改，由验收显式绑定来源与版本。无新Runtime、队列、Lab API/UI或迁移框架。
- 主线程验收：7项Fake+4项真实PG组合11/11；正常/变化各558行，sales52000.00/45760.00、共同基线52034.28571428571428571428571；原库指纹不变、误连与非空拒绝、真实CHECK触发DDL/DML回滚、新连接读取通过。全量675项、5跳过；PG停止，三个新库保留。首次CIDR地址守卫失败及修正见[记录](evaluation-artifacts/sandbox-dataset-postgres-acceptance-2026-10-12.md)。
- 限制/下一步：仅受保护Python发布，不是可操作Lab；manifest尚未自动绑定应用，版本只是输入内容标签。恢复后先核查绑定/回读再接最小实验记录/API、桌面页面；并发实际验收、权限、版本保留/清理仍待开展，不宣称完整实验室。模型与开发店资源gate保留优先级。

### R5-001 — 现有Synthetic资产与隔离首验边界（核对完成）

- 目标/阻碍：复用既有数据生成器，但禁止旧seed reset或全日注入器污染现有数据；当前固定warehouse表没有source_id物理隔离，现有单源应用绑定也不能代替数据隔离。
- 已验证：主线程内存生成558行、126行基线、18行目标日，seed与injector正常日一致、可重复；既有离线21/21。发现旧main的全表删除/全日重写和原始异常输出边界；记录见 [`sandbox-asset-review-2026-10-12.md`](evaluation-artifacts/sandbox-asset-review-2026-10-12.md)。未连接/写入数据库，不是Lab实现或真实模型验收。
- 下一切片/依赖：在新建空的专用Sandbox库复用生成函数和schema，显式身份/空目标守卫，不回退默认DATABASE_URL；同事务写入并从现有只读MetricReadService重新读取。GroundTruth/预期答案不进入Runtime，不增加调度平台。
- 验收标准：真实PG写入、错误目标/非空拒绝、事务回滚、重连查询、原Benchmark/Olist库数据未变；正常/变化结果来自实际SQL。通过后再接最小产品实验记录与桌面Lab；版本保留/并发/清理未完成前不宣称完整实验室。

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

**状态：进行中；单次真实SDK成功已有证据，重复评测和停止语义评分尚未完成。**

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


## 2026-10-13 R5-003 Witt 实现记录（Pending Review）

增加只读 `sandbox_manifest` 启动 Profile，解析发布标签并复用现有 TaskSourceBinding、Worker、任务 API 与指标读取。限定本机命名 Sandbox、Synthetic/Sandbox 身份、唯一 manifest 和服务器配置的 source_id；可选择固定预期版本。未知版本/错误身份/错误物理库 fail-closed；同一 API 启动解析一次并共享上下文。不新增 Runtime、实验编排或快照机制。

已完成独立 PostgreSQL 16.4 临时集群重连/来源目录/真实指标扫描验收，未访问既有R2/R4库；这些历史库的本轮指纹尚未复验，不以新建控制库替代该证据。新建控制库指纹前后相同。完整证据见 evaluation-artifacts/sandbox-manifest-binding-acceptance-2026-10-13.md。下一步 R5-004 独立实验记录和 Lab 接线；未调用模型。

## 2026-10-13 R5-004（实现与真实临时PostgreSQL验收已完成）

新增独立实验记录、幂等发布/状态/历史API、来源绑定调查关联和React Lab；复用现有内核，不覆盖空库发布后的数据、不重放模型。当前每个预配置目标仅一次发布，最多20个。

离线690项/OK(skipped=6，Windows跳过POSIX文件模式位测试)、Lab客户端7项、lint/类型/构建、桌面受控HTTP流程通过。主线程随后在本机临时PG集群执行专项，005迁移、发布幂等、正常/失败调查步骤、非空保护、发布中断恢复和断链修复六项检查全部通过；受控Runner不代表真实模型。模型请求0。见 [验证记录](evaluation-artifacts/lab-application-acceptance-2026-10-13.md) 与 [启动说明](lab-application.md)。

## 2026-10-15 验收脚本保活与事实复核

一次性harness在后端独立限制任务范围和提交次数，未知写结果禁止重试；完成信号需同Run Worker结束和新读取的完整provenance通过。浏览器刷新必须取得新终态响应并展示实际证据引用。实际loopback HTTP+受控Worker的保活回归通过；真实PG只读复核既有模型成功Run，5/8/6/1及全表计数不变。后端702项/OK(skipped=6)、前端断言3项通过；没有新模型调用。此处不关闭完整真实模型浏览器复跑或R6重复语义评测gate。下一步保持有限真实验收→少量重复评测→Shopify权限gate/最小更新→部署的顺序，不增加调度模块。
