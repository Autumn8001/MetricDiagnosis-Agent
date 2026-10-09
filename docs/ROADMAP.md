# MetricSleuth MVP Roadmap

> 状态：当前长期实施计划
> 更新日期：2026-10-09
> 基线：`main` / `a0a912a29addaddf02c14486f85c0a7392f32aa4`
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
| R2 持久化应用基础 | 待开展 | 保存数据源、同步、调查、证据和结果状态 | R1 契约 |
| R3 首个持续真实数据闭环 | 待开展 | 从真实外部源持续更新可调查数据 | R1、R2 |
| R4 产品 API 与冻结原型接线 | 待开展 | 五个产品页面由真实 API 和持久状态驱动 | 原型文件、R2、R3 |
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
- **R1-003｜Olist 隔离资产能力契约验证与降级表达**：待开展。
- **R1-004｜Shopify Development Store 只读 capability spike 与连接器选择门**：待开展。

### 目标

在写连接器前确认什么数据能被可靠调查，并决定首个持续真实数据源。

### 当前阻碍

- 当前默认 Registry 仍绑定单一 Synthetic 宽表；R1-002 已为该表显式表达 atomic grain，但 Shopify 的订单、销售和会话数据可能具有不同 grain，尚未据此声明支持。
- 当前产品没有 `source_id`、来源类型、环境或数据版本边界。
- Shopify 原型店、权限和访问凭据尚未提供；外部 PostgreSQL 目标也未确认。

### 技术方案

1. 定义来源能力契约：来源身份、环境、时间范围、刷新方式、指标、维度、grain、延迟、币种和时区。
2. 为当前 Synthetic Profile 的 Sales、Orders、AOV、Sessions、Conversion Rate 建立 metric × dimension × grain 矩阵；Country、Product、Traffic Source 等外部来源能力仍待真实接口验证。
3. 用现有 Olist 资产验证契约可以表达“支持、缺失、不可推导”。
4. 在获得 Shopify Development Store 后执行只读 capability spike；不能获取可靠维度时显式降级。
5. 做连接器选择门：默认优先 Shopify；若权限/数据能力不满足，则以用户提供的只读 PostgreSQL 为首个持续源。

### 涉及模块

`backend/app/metrics/`、`backend/app/analytics/`、`configs/`、Olist 验证脚本，以及后续数据源领域模块。

### 验收标准

- 形成版本化能力矩阵和来源契约。
- 每个指标只暴露真实来源支持的维度。
- 明确首个持续数据源及失败降级方案。
- 不需要把凭据提交到仓库。

## 5. R2 — 持久化应用基础

**状态：待开展**

### 目标

让调查任务、证据和同步状态在服务重启后仍可恢复，并为真实数据与 Sandbox 隔离提供单一事实源。

### 当前阻碍

- 现有 API 和 React 状态均为进程/页面内存态。
- Observation/Evidence 只保存内存引用，不能独立复算查询。
- 没有任务并发、幂等、重启恢复或失败重试语义。

### 技术方案

- 继续使用 PostgreSQL，不另引入 Redis 或消息中间件。
- 分离应用状态、来源 staging、canonical analytics、synthetic/sandbox 的数据库责任边界。
- 持久化最小生命周期：Data Source、Sync Run、Investigation Run、Tool Call、Observation、Evidence、Diagnosis。
- 每次查询保存脱敏参数、来源/数据版本、query hash、耗时和结果引用；敏感凭据只保存安全引用，不进入业务表或日志。
- 首版采用简单、可恢复的数据库状态机和单 worker 领取任务；并发扩展留到有实际负载证据之后。

### 验收标准

- 调查从 queued/running 进入明确终态，重复请求不会产生不可控重复副作用。
- 服务重启后可查询任务、历史和结果。
- 失败保存已经发生的 Tool Call 与 Observation，不伪造成功结果。
- Synthetic/Sandbox/真实来源不能交叉引用。

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

**状态：待开展；等待原型文件**

### 目标

在不重新设计产品的前提下，让工作概览、业务指标、AI 调查工作区、数据接入和实验室成为可操作页面。

### 当前阻碍

- 认可的独立 HTML 原型不在仓库中。
- 当前只有无 Router 的单页 Benchmark Workspace。
- 缺少数据源、同步、历史、任务状态等 API。

### 技术方案

- 用户提供原型文件后，先做页面/组件/API 映射，不凭描述重画 UI。
- 复用现有 Metric Graph、Timeline、Evidence Portfolio、Diagnosis Card 和 Manual Scan 组件。
- 调查改为持久任务 API；前端显示进度、错误、重试边界和历史结果。
- Fixture Preview 只保留为清楚标记的产品预览；Sandbox 行为由实验室承载。

### 验收标准

- 五个页面都有真实或明确标记的 Sandbox 数据来源。
- 刷新浏览器或重启服务后历史调查仍存在。
- UI 不把 fallback/mock 内容表现为真实业务结果。
- 真实调查不再暴露 Benchmark 场景选择器或注入动作。

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
