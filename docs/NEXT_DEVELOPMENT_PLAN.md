# MetricSleuth 后续开发方案

> 2026-10-15进展覆盖：下文阶段A/B已完成相应真实PG/受控验收，真实模型最终版执行/持久化首次成功（3轮2工具）。最近结果见 PROJECT_STATUS 和 [记录](evaluation-artifacts/live-model-task-scope-2026-10-15.md)。下一步先以桌面现有详情页读取成功结果，再做少量真实重复评测；Shopify仍需资源。下文是制定时的规划基线，不是最新进度。

> 状态：执行基线（规划文档）
> 更新时间：2026-10-13
> 依据提交：`da06d8c8109c472ebe348635cc51f8772eac6c50`
> 适用范围：桌面浏览器 Web MVP；不包含手机专项、生产部署授权或新 Runtime

## 1. 目标与结论

MetricSleuth 的下一目标不是继续增加底层框架，而是完成一条可演示、可追溯的真实闭环：

```text
受控/真实来源更新
  → 指标读取与异常候选
  → 用户在 Web 中启动调查
  → Agent 根据 Observation 选择工具
  → Tool Trace / Observation / Evidence / Diagnosis 持久化
  → 浏览器查看依据、来源版本和历史结果
```

当前最重要的判断是：持久化、最小 Worker、指标读取/扫描和桌面调查工作区已有源码及部分真实 PostgreSQL 证据；真实模型成功调查、持续外部数据同步、可操作 Sandbox Lab 和服务器部署仍未完成。因此后续按“先打通一个真实来源，再完成产品闭环，最后部署”的顺序推进，不继续扩展通用调度系统。

## 2. 证据边界

| 分类 | 当前结论 |
| --- | --- |
| 当前事实 | `docs/PROJECT_STATUS.md`、`docs/ARCHITECTURE.md`、R4/R5 验收记录及当前源码支持 Synthetic/Olist 调查内核、PostgreSQL 持久化、Worker、指标读取/扫描和 React 工作区。 |
| 已确认决策 | 首个验证领域仍是电商；MVP 只验收桌面 Web；保留 OpenAI Agents SDK Runtime；Sandbox 与真实来源隔离；不引入 Kafka/Redis/微服务/Jev/Webhook 作为当前主线。 |
| 后续提案 | 优先验证 Shopify Development Store 的只读 Orders 能力；若资源或权限未就绪，继续完善不依赖外部凭据的 Sandbox→Lab 最小闭环，但不把 Sandbox 称为真实业务数据。 |
| 未知 | CPA Gemini 端点的可用性、Shopify 实际字段/权限覆盖、生产服务器规格、认证/TLS/备份策略和真实模型的 Driver/Scope/停止准确率。 |

历史任务书中的“已完成”不覆盖上述未知项；Mock、Hermetic、Synthetic 和受控 Runner 结果必须与真实模型、真实外部数据结果分开报告。

## 3. 阶段顺序与验收门

### 阶段 A：R5-003，Sandbox 到应用来源绑定（下一阶段）

目标：让已发布的 Sandbox manifest 能被现有任务应用明确读取和绑定，而不是由测试代码手工传入 source/version。

最小范围：

- 增加只读 manifest/source binding 查询，复用现有 `DataSourceDescriptor`、`TaskSourceBinding`、`MetricReadService` 和安全来源校验。
- 明确 `data_version` 是发布标签还是数据库快照；在快照能力未实现前，API 必须继续暴露 `snapshot_consistent=false`。
- 不在本阶段实现实验编排、自动清理、并发发布或外部同步。

验收条件：新连接可从 manifest 得到来源身份和版本；错误来源、跨环境绑定和不存在版本 fail-closed；旧 R2/R4 数据库指纹不变；真实 PostgreSQL 读回与离线合同测试同时通过。

### 阶段 B：R5-004，最小实验记录与桌面 Lab API

目标：用户可以选择 Sandbox 场景、发布一次隔离数据、查看发布状态，并把结果送入现有调查任务 API。

最小范围：

- 设计一个与调查 Run 分离的实验记录，保存 source、scenario、data_version、目标日期、状态和关联 run；不保存 Ground Truth 到 Agent Prompt 或工具。
- 提供提交、详情和历史读取接口；重复提交必须有明确幂等语义，失败只能写安全错误分类。
- React Lab 只接入已认可 HTML 原型的交互结构，显示真实状态、来源环境和限制；不重画导航或制造前端数字。

验收条件：桌面浏览器完成“选择场景→发布→读取指标→提交调查→刷新后查看历史”；实验数据和真实来源不可混写；断电/请求失败不产生伪造 Diagnosis；真实 PostgreSQL 重连后记录和调查事实仍可读。

### 阶段 C：R3-001，Shopify Orders 真实只读验证

目标：在用户提供 Development Store、应用和 `read_orders` 权限后，确认字段、时间范围、分页和订单粒度，再决定是否进入连接器实现。

顺序：

1. 低成本连通性和少量分页读取，记录 API 版本、权限、响应字段和 UTC 时间范围。
2. 将 Orders 转为 source-specific staging 或受控 canonical 表；Agent 不直接查询第三方原始响应。
3. 先支持真实验证过的 sales、orders、product、marketplace/country 等指标；Sessions、Conversion Rate、AOV 若缺乏可靠粒度，保持 unavailable。
4. 以水位和幂等键实现最小增量同步，至少验证两次同步和一次重复同步。

验收条件：真实 API 读取通过；重复同步不重复计数；数据版本/水位可追溯；指标扫描读取已同步数据；没有把 Development Store 数据描述为生产经营数据。

### 阶段 D：R3-002，真实模型调查 Gate（当前阻塞）

目标：在明确端点、模型和预算并重新获得一次性授权后，执行一次隔离 Synthetic 或 Shopify 测试调查。

限制：最多 8 次工具调用、10 轮、禁用自动重试和远程 tracing；失败立即停止并记录安全错误；不反复消耗额度。

当前结果：2026-10-14 一次有限调查返回 `AuthenticationError / 401`，0 工具调用；失败 Run 已保存，未生成伪造 Diagnosis。验收条件仍是保存真实 Tool Trace、Observation、Evidence 和 Diagnosis；每个 Driver/Scope 可回到同一轮 Evidence 与查询引用；能证明 Agent 根据 Observation 选择下一步并在证据充分时停止。401、模型不兼容或工具协议失败只能记为失败，不得记作模型通过。鉴权修复前不重复调用。

### 阶段 E：R6，真实评测与可靠性

目标：把模型、数据、Sandbox 和 Mock 结果分开，形成可复算评测。

- 保留现有 Synthetic Regression，并增加不参与调参的 holdout。
- 报告 Driver、Scope、Unsupported Claim、过早停止、冗余调用、工具次数、耗时和成本（可获取时）。
- 失败 Run 进入分母并保存脱敏输入版本、模型标识、Prompt/工具合同版本和 Trace 引用。

验收条件：另一台环境可依据版本化输入重算；报告明确标注 Mock/Hermetic、受控 Runner、真实模型和真实外部数据。

### 阶段 F：R7，个人服务器部署

目标：将已通过真实数据和模型 Gate 的最小闭环部署为少进程 Web 系统。

只在前述 Gate 通过后实施：Web/API、Worker、PostgreSQL 和反向代理；加入最小认证、TLS、Secret 注入、健康检查、结构化日志、备份/恢复、迁移和安全停机说明。

验收条件：服务器重启后历史和任务状态可恢复；浏览器能完成来源读取、调查和历史查看；密钥不进仓库、日志、响应或前端包；备份恢复和失败任务恢复有实际演练记录。

## 4. 依赖与取舍

| 决策 | 选择 | 原因 |
| --- | --- | --- |
| 首个外部源 | Shopify Development Store 优先；外部 PostgreSQL 等待真实目标库 | 已有 Orders probe 和产品方向，先验证最小权限/字段；避免先做通用映射平台。 |
| Sandbox | 保留并接入 Lab，但严格标记 `synthetic/sandbox` | 可在没有外部凭据时验证产品闭环，不能冒充持续真实数据。 |
| Runtime | 继续复用 OpenAI Agents SDK | 当前已有工具、Observation、Evidence、Diagnosis 和 callback 接线；暂无切换收益。 |
| 持久化 | PostgreSQL + 现有短事务/Worker | 已有真实迁移和恢复证据；不为简单领取任务引入 Kafka、Redis 或微服务。 |
| UI | 以冻结 HTML 原型和现有 React 工作区为基线 | 主要缺口是数据和状态接线，不是重新设计视觉层。 |
| 研究扩展 | Jev、Webhook、替换 Harness、第二行业全部后置 | 不阻塞第一个可运行真实闭环。 |

## 5. 不做事项与停止条件

当前不做：手机端专项、第二套 Agent Runtime、通用连接器平台、自动 Webhook 触发、复杂队列、前端模拟业务事件、为增加测试数量而继续扩展 Fake 持久化代码。

出现以下任一情况应暂停并报告，而不是继续堆功能：

- 外部来源粒度无法支持某指标；该指标应标记 unavailable。
- 模型端点连续返回鉴权或协议错误；不重复调用，等待用户确认资源。
- 真实数据库验收与文档证据不一致；先修复证据边界。
- 需要生产权限、不可逆迁移、密钥变更或公开部署；必须单独获得确认。

## 6. 每阶段交付格式

每个阶段必须产生一个独立提交，并更新 `docs/ROADMAP.md`、`docs/PROJECT_STATUS.md` 及必要的 `docs/evaluation-artifacts/` 记录，至少包含：

1. 普通中文的实际产品能力说明；
2. 代码路径和接口/表的实际证据；
3. 真实数据库、受控 Runner、Mock 和真实模型的分别结果；
4. 失败、回滚、重连、权限和敏感信息边界；
5. 未完成事项、下一门槛和是否需要用户资源。

## 7. 当前下一步

恢复开发后，先进行 R5-003 的只读范围审查和最小实现设计：确认 manifest 如何映射到现有来源目录与任务绑定，再写一个可从真实 PostgreSQL 重连复现的读取验收。若该边界稳定，再进入 R5-004 Lab API/UI。Shopify 和真实模型只在资源、权限及新授权可用时插入对应 Gate，不将等待外部资源作为停工理由，也不假设它们已经成功。
