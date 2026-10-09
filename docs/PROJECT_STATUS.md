# MetricSleuth Project Status

> 状态：动态接管摘要
> 快照日期：2026-10-09
> Git 基线：`main` / `a0a912a29addaddf02c14486f85c0a7392f32aa4`
> 最近完成：R0 认知与权威基线；R1-001 数据源能力契约（纯领域模型完成深层不可变与 fail-closed 修复并通过回归）
> 当前阶段：R1 数据源契约与能力验证（进行中）
> 当前任务：R1-001 已由主线程验收并提交；准备推进 R1-002 指标能力矩阵与现有语义层适配

## 当前结论

MetricSleuth 已具备较成熟的 Synthetic Benchmark 调查内核，但尚不是完整的真实数据产品。当前已完成最小数据源能力契约纯领域模型（R1-001），并在主线程复验反馈下完成了对象级/嵌套容器级深层不可变与 fail-closed 强化。本项目明确**尚未接入**真实外部 PostgreSQL 或 Shopify（二者当前仅作为平台枚举定义，未实现连接器或网络调用）。下一阶段需推进核心指标能力矩阵与契约适配，在确认首个持续真实数据源后，再建设持久化、产品接线和部署闭环。

## 已完成且本轮有源码/测试证据

- 数据源能力契约（R1-001）：最小、领域无关、真正深层不可变契约模型，支持 `SourceProvider`、`SourceEnvironment`、`DataSourceDescriptor`、`MetricCapability`、`DataSourceCapabilities`（frozen dataclass，嵌套内部容器使用 MappingProxyType，防范 Sequence 字符串混淆），具备指标独立 grain/维度、跨 grain 组合保护与 fail-closed 校验（`backend/app/data_sources/capabilities.py`；单测 `backend/tests/test_data_source_capabilities.py` 6/6 PASS）。
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
- 真实模型动态调查：仓库保存了 2026-09-22 的 Synthetic Live 聚合记录，本轮无凭据和数据库，未复现逐 Run 结果。
- 前端 production build：历史文档记录通过；本轮因文档任务不生成 `dist`，仅运行 lint 和无输出类型检查。

## 尚未实现

- 能力契约与 `MetricRegistry`、`AnalyticsTools`、API 及 Agent Runtime 的运行时接入集成（当前契约仅为纯领域模型）。
- Shopify 或用户外部 PostgreSQL 的产品级接入、连接器实现、数据同步和水位（当前绝对未接入真实外部库或 Shopify API）。
- 数据库持久化中的 `source_id`、数据环境隔离和多 grain 查询支持。
- Investigation/Tool Call/Observation/Evidence/Diagnosis 持久化与历史恢复。
- 数据接入、工作概览、独立指标页和实验室的真实 API。
- 用户认证、生产安全、后台任务恢复和服务器部署资产。
- 独立 Holdout、真实外部数据评测、Next Action/Stop Condition 评分。

## 当前阻碍与待提供资源

1. 认可的 HTML 交互原型文件不在仓库中，已记录为待补产品资产；需要用户提供后才能按冻结设计接线，但不阻塞 R1 数据契约与数据层开发。
2. 当前环境未配置 `DATABASE_URL` 或模型凭据，不能做真实端到端复验。
3. Shopify Development Store/应用权限尚未提供；外部 PostgreSQL 目标库也未确定。
4. 首个真实源最终选择需经过 R1 capability gate，不能仅按候选名称决定。

## 下一步具体工作

继续推进 Roadmap R1：

1. R1-002：建立电商核心指标的 metric × dimension × grain 矩阵并与现有语义层/校验适配。
2. R1-003：用 Olist 现有资产验证缺失能力可显式降级。
3. R1-004：在用户提供 Shopify Development Store 后执行只读 capability spike，并决定首个持续连接器。

## 最新验证结果

| 检查 | 结果 | 边界 |
|---|---|---|
| 数据源能力契约专项 | 6/6 PASS | 纯领域单元测试，覆盖基础合同、Olist、独立维度、跨 grain 保护、fail-closed 和深层不可变 |
| 后端全量 unittest | 461/461 PASS | Hermetic；455 既有基线 + 6 新增专项测试；未访问真实模型或数据库 |
| FastAPI 专项 | 24/24 PASS | Live 分支使用 patch，只证明契约/wiring |
| 前端 lint | PASS | 静态检查 |
| TypeScript `--noEmit` | PASS | 不生成构建产物 |
| Git 工作树（任务开始） | clean | 文档修改完成后的状态以本轮交接报告为准 |

## 当前关键技术决策

- 产品方已于 2026-10-09 认可 R0 认知固化成果和当前 MVP Roadmap；后续按仓库长期文档自主推进。
- 保留 OpenAI Agents SDK 作为主 Runtime；没有独立 ADR 不建立第二套 Harness。
- PostgreSQL 继续作为 canonical analytics 与应用状态的主要基础，但不同责任需要隔离。
- Shopify 是首个持续真实源的优先候选，不是未经验证的既定实现。
- Olist 用作真实数据映射/契约验证，不宣称持续外部数据接入。
- Live Investigation 必须与 Synthetic Scenario Injection 解耦。
- 首版持久任务优先使用 PostgreSQL 状态机和简单 worker，不提前引入 Redis/Kafka/微服务。
- Jev、Webhook 自动触发和可替换 Harness 延后到真实闭环稳定后。

## 快速接管入口

- 产品目标：[`PRODUCT.md`](PRODUCT.md)
- 当前/规划架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 长期实施计划：[`ROADMAP.md`](ROADMAP.md)
- 历史 Live 记录：[`evaluation-artifacts/live-evaluation-2026-09-22.md`](evaluation-artifacts/live-evaluation-2026-09-22.md)
- Olist 验证：[`phase-9-olist-real-world-validation.md`](phase-9-olist-real-world-validation.md)
- 历史设计基线：[`../任务书.md`](../任务书.md)
