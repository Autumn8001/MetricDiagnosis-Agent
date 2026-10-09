# MetricSleuth Project Status

> 状态：动态接管摘要
> 快照日期：2026-10-09
> Git 基线：`main` / `a0a912a29addaddf02c14486f85c0a7392f32aa4`
> 最近完成：R0 认知与权威基线
> 下一阶段：R1 数据源契约与能力验证
> 当前任务：R0 已获产品方认可，等待下一轮开始 R1 实施

## 当前结论

MetricSleuth 已具备较成熟的 Synthetic Benchmark 调查内核，但尚不是完整的真实数据产品。下一阶段不重写 Agent，而是先确定数据源契约和首个持续真实数据源，再建设持久化、产品接线和部署闭环。

## 已完成且本轮有源码/测试证据

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

- Shopify 或用户外部 PostgreSQL 的产品级接入、同步和水位。
- `source_id`、真实/Sandbox/Synthetic 环境隔离和多 grain 指标能力契约。
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

进入 Roadmap R1：

1. 定义最小 Data Source Capability Contract 和来源/环境隔离规则。
2. 建立电商核心指标的 metric × dimension × grain 矩阵。
3. 用 Olist 现有资产验证缺失能力可显式降级。
4. 在用户提供 Shopify Development Store 后执行只读 capability spike，并决定首个持续连接器。

## 最新验证结果

| 检查 | 结果 | 边界 |
|---|---|---|
| 后端全量 unittest | 455/455 PASS | Hermetic；未访问真实模型或数据库 |
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
