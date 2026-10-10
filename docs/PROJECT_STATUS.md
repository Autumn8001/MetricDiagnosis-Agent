# MetricSleuth Project Status

> 状态：动态接管摘要
> 快照日期：2026-10-10
> Git 基线：`main`（R0、R1-001 至 R1-003、R2-001 至 R2-005a 已提交）
> 最近完成：R0 认知与权威基线；R1 数据契约/语义适配/Olist 降级表达；R2-001 应用状态 Schema/状态机；R2-002 参数化 Repository；R2-003 审计结果持久化编排；R2-004a provenance 迁移合同；R2-004b 生命周期原语；R2-004c 短事务协调器；R2-005a 单任务执行服务
> 当前阶段：R2 持久化应用基础（进行中）
> 最近新增验收：R2-PG（`71e284f`）；R2-005b1 最小 Worker、步骤保存与中断恢复（本次提交）
> 当前任务：R2-005b2 持久任务/历史 API 与应用 Runner 配置接线；R1-004 仍需等待外部接入资源

## 当前结论

MetricSleuth 已具备较成熟的 Synthetic Benchmark 调查内核，但尚不是完整的真实数据产品。当前已完成最小数据源能力契约纯领域模型（R1-001）、当前 Semantic Layer 到能力契约的纯内存适配和 AnalyticsTools 可选的 SQL 前能力校验（R1-002），以及基于既有 Olist 资产的纯内存能力降级表达（R1-003，均已由主线程验收）。本项目明确**尚未接入**真实外部 PostgreSQL 或 Shopify（二者当前仅作为平台枚举定义，未实现连接器或网络调用）；Olist 也未宣称持续同步或产品级接入。R1-004 需等待受控接入资源；期间可按 Roadmap 推进不依赖外部授权的 R2 持久化应用基础设计与实现。

## 已完成且本轮有源码/测试证据

- 数据源能力契约（R1-001）：最小、领域无关、真正深层不可变契约模型，支持 `SourceProvider`、`SourceEnvironment`、`DataSourceDescriptor`、`MetricCapability`、`DataSourceCapabilities`（frozen dataclass，嵌套内部容器使用 MappingProxyType，防范 Sequence 字符串混淆），具备指标独立 grain/维度、跨 grain 组合保护与 fail-closed 校验（`backend/app/data_sources/capabilities.py`；单测 `backend/tests/test_data_source_capabilities.py` 6/6 PASS）。
- 指标能力矩阵与语义适配（R1-002）：当前 Synthetic Profile 的五个核心指标在 `configs/metrics.yaml` 显式声明 `date × asin × marketplace × traffic_source` atomic grain；`MetricRegistry` 严格校验显式 grain 并为旧配置提供明确 fallback；`build_capabilities_from_registry()` 保留 Registry 中的 metric dimensions/grain；`AnalyticsTools` 传入 capabilities 时在执行 SQL 前校验查询能力（主线程专项测试 51/51 PASS）。
- Olist 能力降级表达（R1-003）：`configs/olist_validation_metrics.yaml` 的三个支持指标显式使用 `date × customer_state` grain；`build_olist_validation_capabilities()` 复用 Registry grain/dimensions，显式拒绝 `sessions`、`conversion_rate` 及 `marketplace`/`traffic_source`/`asin`；Olist 工具兼容性脚本已绑定该合同。已验证绑定合同后，漏斗指标与非法维度都在 SQL 前失败。证据限于本地 Hermetic 测试，不代表数据库连接、同步或持续真实数据接入。
- PostgreSQL Synthetic Warehouse、10 个 Benchmark 场景和 Ground Truth 隔离。
- YAML Metric Semantic Layer 与指标依赖/driver 元数据。
- 受控 Analytics Tools、Observation、Evidence、Structured Diagnosis。
- OpenAI Agents SDK Runtime、Tool Trace、轮次和工具预算校验。
- Driver + Scope 同一 Evidence、negative control 等 fail-closed 约束。
- Evaluation 的 Driver、Scope、Evidence、Unsupported Claims 和 Tool/Budget 评分基础。
- FastAPI 六个端点与 React 单页 Diagnosis Workspace。
- Manual Daily Scan。
- Olist 隔离 Schema/Metric/Tool Compatibility 验证资产。

## 已实现但当前未真实复验

- Analytics Tools 的真实 PostgreSQL 执行路径：本轮自动测试使用 Fake/Mock connection。
- 真实模型动态调查：仓库保存了 2026-09-22 的 Synthetic Live 聚合记录；当前没有模型凭据，未复现逐 Run 结果。
- 前端 production build：历史文档记录通过；R0 运行过 lint 和无输出类型检查，本次后端验收未重新运行前端检查。

## R2-PG：真实 PostgreSQL 持久化验收已通过

- PostgreSQL 17.11 隔离本机测试库已执行 `001`、`002`、`003` migrations，并重复执行成功；没有连接生产库或读取应用连接配置。
- `upsert_data_source()` 拒绝同 ID 不同 provider/environment；`003_immutable_data_source_identity.sql` 触发器进一步禁止直接 SQL 修改 source_id/provider/environment。相同身份的元数据更新仍允许。
- 领域模型与 Repository 均允许 `queued → failed`；已验证实际 SQL 状态写入。
- 受控 Runner 执行参数化 `SELECT 80/100`，成功保存 Trace、Observation、Evidence、Diagnosis 与来源版本/查询引用；失败只落受控 code，不生成 Diagnosis。
- 实际数据库验证来源组合外键、Diagnosis 冲突后的整批回滚、Observation 原始错误文本不落库，以及全新连接读取。数据库进程重启后再次读回同一成功调查和 Diagnosis。
- 主线程终验：真实 PostgreSQL **7/7 PASS**；离线回归原始输出 **Ran 535 tests / OK (skipped=1)**，数据库测试类因未配置专用变量跳过。二者分别运行，不混算模型效果。
- 记录与复现命令：[`postgres-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/postgres-persistence-acceptance-2026-10-10.md)。测试实例已停止，测试数据保留在仓库外。
- R2-PG 验收时尚未完成 Worker/API 接线、失败前工具事实增量保存、任务恢复；其中 Worker 与步骤保存现已由下述 R2-005b1 补齐。外部业务同步与真实模型仍未验收。

## R2-005b1：最小 Worker 与失败前步骤保存已验收

- `InvestigationWorker.submit()/run_once()` 在 PostgreSQL 排队、原子领取一个调查；session advisory lock 保证只有一个 Worker 执行，Runner 期间不持有数据库事务。
- `004_worker_execution_mode.sql` 将 Worker 任务与旧 inline 调查隔开。中断恢复仅处理 Worker 的 running 任务，写 `worker_interrupted`，不自动重放模型、不影响 inline。
- 每个完整工具结果通过 `Coordinator.checkpoint()` 独立提交 Trace/Observation；失败前事实保留，不生成缺失的 Evidence/Diagnosis。
- 幂等重放只接受完全相同的事实；不同内容、不同来源/版本、终态写入均拒绝。成功完成不能遗漏已保存步骤。
- Agents SDK 三个现有工具和 Diagnosis Runtime 提供可选 `progress_callback`；沿用原始 SDK 调用参数、原 Observation 和最终校验。未改 Prompt、策略、预算或模型。
- 主线程实际 PostgreSQL **15/15 PASS**（含原 7 项回归），新库 migrations 001–004 和已有库升级/重放均验证；子 Worker 突然退出后事实保留，新 Worker 安全终结，未再次调用 Runner。
- 全量离线回归 **Ran 552 tests / OK (skipped=1)**；SDK 回调专项 5 项为 Fake Analytics/真实 FunctionTool invocation，无真实模型。
- 记录：[`worker-checkpoint-acceptance-2026-10-10.md`](evaluation-artifacts/worker-checkpoint-acceptance-2026-10-10.md)。没有 HTTP/前端或后台进程启动接线，不代表可部署产品已完成。

以下 R2-001 至 R2-005a 条目保留各切片当时的历史验证边界；其中“未执行迁移/未验证数据库”已由上述 R2-PG 验收更新，不代表当前仍未执行。

## R2-001：已完成并由主线程验收

- `backend/migrations/001_app_state.sql` 提供独立、幂等目标为 `app_state` 的
  应用状态 Schema，覆盖数据源、同步 Run、调查 Run、Tool Call、Observation、
  Evidence、Diagnosis 和多 Evidence 链接；未执行迁移。
- `backend/app/persistence/models.py` 提供不可变 `RunState`/`RunStatus` 状态机和
  `SourceReference`；非法创建、非法迁移和终态转换均 fail-closed。
- `backend/app/persistence/migrations.py` 只读取 SQL 文本；`tests/test_persistence.py`
  检查状态机、环境枚举、Schema/FK/约束形状和敏感列名排除。
- 本切片尚未接入 repository、FastAPI、Agent Runtime、worker 或真实 PostgreSQL；
  测试不代表迁移执行、重启恢复或真实持久化验收。

## R2-002：已完成并由主线程验收

- `backend/app/persistence/repository.py` 新增 `ApplicationStateRepository` 和
  `InvestigationRunSummary`，仅接受已建立的 DB-API connection；调用者负责
  transaction，不保存 `DATABASE_URL`，不自动 commit/rollback，不执行 migration。
- repository 使用参数绑定 SQL 保存 data source、queued investigation run、受
  `RunState` 规则约束的条件状态迁移、Tool Call、Observation、Evidence、
  Diagnosis 及 `diagnosis_evidence` 链接，并支持按 run id 读取最小摘要。
- 写入前统一校验 source/environment、状态枚举、空 ID、递归敏感 key 和 JSON
  可序列化性；认证字段不会写入 arguments、parameters、capabilities 或 payload。
- `backend/tests/test_persistence_repository.py` 提供 FakeConnection/FakeCursor
  合同测试；专项 9/9 PASS，全量 Hermetic unittest 490/490 PASS。
- 这是 repository 合同层证据；未执行 `001_app_state.sql`，未接线 FastAPI、
  Agent Runtime 或 worker，未证明真实 PostgreSQL、事务提交和重启恢复。
- Schema 目前只保证各事实所引用的来源/环境有效；尚未在数据库层保证它们一定
  等同于所属 Investigation Run 的来源/环境。R2-003 必须在应用接线与最终迁移
  设计中落实这项 provenance 一致性，当前不得宣称完整持久化隔离。

## R2-003：已完成并由主线程验收

- `EvidenceDrivenRunSummary` 新增完整、不可变 `observation_catalog`，并将每个
  Observation 的顺序、ID、Tool Call ID 和 Tool Name 与已验证 Trace 重新核对。
  这让持久化边界拥有完整事实目录，而非仅有最终 Evidence/Diagnosis。
- `backend/app/persistence/investigation_writer.py` 的
  `EvidenceDrivenRunPersistenceWriter` 只接受一个 `DataSourceDescriptor`；所有
  Tool Call、Observation、Evidence、Diagnosis 的 source/environment 均从此派生。
  它在任何写入前检查 Trace、catalog、Evidence 和 Diagnosis 的引用关系，按
  source → queued → running → facts → diagnosis → succeeded 顺序调用 Repository。
- Writer 不建立连接、不执行 migration、不 commit/rollback，Repository 异常原样
  传播且不会错误标记 succeeded。专项 29/29 PASS，后端全量 Hermetic unittest
  496/496 PASS。
- 未接线 FastAPI/worker；没有真实 PostgreSQL、运行中进度、失败持久化或重启恢复
  验收，不能把该合同测试表述为产品持久化已完成。

## R2-004a：已完成并由主线程验收，迁移尚未执行

- `backend/migrations/002_enforce_investigation_provenance.sql` 只为 `app_state`
  增加约束：Tool Call、Observation、Evidence、Diagnosis 的
  `(investigation_run_id, source_id, environment)` 将分别外键引用同一
  Investigation Run；这补齐了此前只验证“来源存在”、未验证“来源属于该 Run”的
  Schema 缺口。
- 每个约束增加前都会检查 `pg_constraint`，并且没有 DROP/TRUNCATE/DELETE、warehouse、
  Olist 或认证字段。`tests/test_persistence.py` 的专项 12/12 PASS，后端全量
  Hermetic unittest 498/498 PASS。
- 迁移未执行；SQLGlot 只能把 PostgreSQL `DO $$` 块降级为通用 Command，故这仅是
  SQL 文本/合同验证，不是 PostgreSQL 解析、约束生效或真实数据完整性证据。

## R2-004b：已完成并由主线程验收，未接线事务 owner

- Repository 的 `fail_investigation_run()` 只允许 queued/running → failed，并以
  参数化 SQL 把严格受控的 1–64 位小写 failure code 保存为 `{"code": ...}`；没有
  原始异常、stack trace、凭据或连接配置的参数入口。
- Writer 已拆分 `start()`（source→queued→running）、`complete()`（facts→succeeded）
  与 `fail()`；`write()` 仍为向后兼容组合，但对完整 Summary 先验证，避免坏数据
  产生孤立 running 记录。专项 23/23 PASS，后端全量 Hermetic unittest 506/506 PASS。
- 没有 API/worker、connection factory、commit/rollback owner、重试、领取或真实数据库
  验收；这些接口是下一步短事务服务的基础，不能当作已部署任务队列。

## R2-004c：已完成并由主线程验收，未接线 API/worker

- `InvestigationTransactionCoordinator` 对 start、complete、fail 分别从注入的
  factory 获取一个连接，成功才 commit，执行/commit 失败则 best-effort rollback，最后
  close；它不会跨模型调用持有连接，也不会读取环境变量、保存 URL 或创建网络连接。
- `InvestigationRunHandle` 是不可变的 run/source/data-version 绑定，complete/fail
  只能从 handle 获取来源身份。commit 已成功后的 cleanup 错误被隔离，避免调用方把
  已落库操作当作可安全重试的失败。
- 专项 11/11 PASS，后端全量 Hermetic unittest 517/517 PASS。仍未接 FastAPI、worker、
  实际 connection factory、PostgreSQL 或 migration；没有真实任务状态持久化证据。

## R2-005a：已完成并由主线程验收，未接线 HTTP/worker

- `InvestigationTaskExecutionService` 按 `start → injected runner → complete/fail`
  编排单个调查，Runner 在两个 coordinator 短事务之间执行；服务没有连接、线程、网络
  或环境配置责任。
- `InvestigationTaskRequest` 是不可变且来源绑定的请求合同，递归拒绝敏感 key 和非
  JSON 参数。Runner 异常仅落受控 code 后原样抛出；start 失败不执行 runner，complete
  失败不二次 fail 覆盖可能已发生的持久化事实。
- 专项 11/11 PASS，后端全量 Hermetic unittest 528/528 PASS。未运行真实 Agent、API、
  worker、PostgreSQL 或 migration，不能据此宣称已具备后台持久任务。

## 尚未实现

- 能力契约与 API、Agent Runtime、数据库来源发现及外部连接器的产品级接入（当前仅完成 Registry/AnalyticsTools 的纯内存适配，以及 Olist 验证合同表达）。
- Shopify 或用户外部 PostgreSQL 的产品级接入、连接器实现、数据同步和水位（当前绝对未接入真实外部库或 Shopify API）。
- repository/API 接线、用户取消/显式重试、生产进程恢复和持久化
  后的多 grain 查询支持。
- 面向用户的调查历史/步骤读取 API，以及应用配置的真实 Runner（步骤保存和最小 Worker 中断恢复已验收）。
- 数据接入、工作概览、独立指标页和实验室的真实 API。
- 用户认证、生产安全、后台进程生命周期与服务器部署资产。
- 独立 Holdout、真实外部数据评测、Next Action/Stop Condition 评分。

## 当前阻碍与待提供资源

1. 认可的 HTML 交互原型文件不在仓库中，已记录为待补产品资产；需要用户提供后才能按冻结设计接线，但不阻塞 R1 数据契约与数据层开发。
2. 已有可复用隔离本机 PostgreSQL 验收环境；产品数据源与模型凭据仍未配置，不能做真实 Agent/业务端到端复验。
3. Shopify Development Store/应用权限尚未提供；外部 PostgreSQL 目标库也未确定。
4. 首个真实源最终选择需经过 R1 capability gate，不能仅按候选名称决定。

## 下一步具体工作

继续推进 Roadmap R2：

1. R2-005b2：将任务提交、状态、步骤和历史结果读取接到 FastAPI；明确配置归属与安全错误响应，复用 Worker 和现有 SDK Runner。增加真实 PostgreSQL API 验收，不新增调度框架。真实模型验收需要明确配置的受控凭据/预算；不操作生产。
2. R1-004：在用户提供 Shopify Development Store 或明确的只读外部 PostgreSQL 目标后，执行只读 capability spike，并决定首个持续连接器。

## 最新验证结果

| 检查 | 结果 | 边界 |
|---|---|---|
| 数据源能力契约专项 | 6/6 PASS | 纯领域单元测试，覆盖基础合同、Olist、独立维度、跨 grain 保护、fail-closed 和深层不可变 |
| R2-001 持久化专项 | 10/10 PASS | 纯 Python 状态机、环境值、只读 migration loader、Schema/FK/约束形状和敏感列名排除；未执行 SQL |
| R2-002 repository 专项 | 9/9 PASS | Fake connection；参数化/事务边界/证据链/来源环境；未执行 SQL |
| R2-003 Runtime/Writer 专项 | 29/29 PASS | Fake/Spy repository；完整 catalog、来源派生、写入顺序、失败闭合；未执行 SQL |
| R2-004a provenance 专项 | 12/12 PASS | SQL 文本/合同；未执行 migration，`DO $$` 未获完整 parser 验证 |
| R2-004b lifecycle 专项 | 23/23 PASS | Fake/Spy repository；失败代码、start/complete/fail、无成功漂移；未执行 SQL |
| R2-004c transaction 专项 | 11/11 PASS | Fake connection；短事务、回滚、关闭与来源句柄；未执行 SQL |
| R2-005a task-service 专项 | 11/11 PASS | Fake/Spy coordinator；事务外 Runner、失败分类与输入隔离；未执行 SQL |
| 后端全量 unittest（2026-10-10） | Ran 552 tests / OK (skipped=1) | 未配置专用 DB 变量；数据库测试类跳过；无真实模型调用 |
| R2-005b1 数据库/Worker 专项 | 15/15 PASS | PostgreSQL 17.11；全新库、升级库、事实重放、失败留存、实际子进程退出与安全终结 |
| SDK 进度回调专项 | 5/5 PASS | Fake Analytics + 真实 FunctionTool invocation；无真实模型 |
| R2-PG 真实数据库专项（2026-10-10） | 7/7 PASS | PostgreSQL 17.11；迁移、约束、受控 Runner、成功/失败、回滚、重连、安全错误文本 |
| PostgreSQL 进程重启读取（2026-10-10） | PASS | 同一成功 Run、Diagnosis、data_version/query_reference；不是 Worker 恢复 |
| Olist 验证能力专项 | 5/5 PASS | Registry grain/dimensions、漏斗指标 unavailable、非法维度与错误来源身份；Fake connection 未执行 SQL |
| FastAPI 专项 | 24/24 PASS | Live 分支使用 patch，只证明契约/wiring |
| 前端 lint | PASS | 静态检查 |
| TypeScript `--noEmit` | PASS | 不生成构建产物 |
| Git 审查快照 | `eba3d1846d08876df42c9730289009875dd73dc0` | 原 11 个提交与审查分支保留；R2-PG 在本地 main 新增提交，不推送/合并 |

## 当前关键技术决策

- 产品方已于 2026-10-09 认可 R0 认知固化成果和当前 MVP Roadmap；后续按仓库长期文档自主推进。
- 保留 OpenAI Agents SDK 作为主 Runtime；没有独立 ADR 不建立第二套 Harness。
- PostgreSQL 继续作为 canonical analytics 与应用状态的主要基础，但不同责任需要隔离。
- Shopify 是首个持续真实源的优先候选，不是未经验证的既定实现。
- Olist 用作真实数据映射/契约验证，不宣称持续外部数据接入。
- Live Investigation 必须与 Synthetic Scenario Injection 解耦。
- 当前 R1-002 只为 Synthetic Semantic Layer 建立纯内存 metric × dimension × grain 适配，不把能力映射误认为真实来源连接或 Shopify 支持。
- 当前 R1-003 只为既有 Olist validation registry 建立 `OLIST + VALIDATION` 能力合同和本地 Hermetic 降级验证，不把 Olist 验证资产误认为持续真实连接器。
- 首版持久任务优先使用 PostgreSQL 状态机和简单 worker，不提前引入 Redis/Kafka/微服务。
- Jev、Webhook 自动触发和可替换 Harness 延后到真实闭环稳定后。

## 快速接管入口

- 产品目标：[`PRODUCT.md`](PRODUCT.md)
- 当前/规划架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 长期实施计划：[`ROADMAP.md`](ROADMAP.md)
- 历史 Live 记录：[`evaluation-artifacts/live-evaluation-2026-09-22.md`](evaluation-artifacts/live-evaluation-2026-09-22.md)
- Olist 验证：[`phase-9-olist-real-world-validation.md`](phase-9-olist-real-world-validation.md)
- 历史设计基线：[`../任务书.md`](../任务书.md)
