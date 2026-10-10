# MetricSleuth 产品定义

> 文档性质：稳定产品方向与 MVP 验收口径。
> 更新基线：2026-10-10（产品边界不变，仅更新持久化实现状态）。
> 状态词：**Confirmed** 表示已经确认的产品决策；**Current** 表示源码当前事实；**Deferred** 表示明确延后；**Unknown** 表示尚未通过仓库或运行证据确认。

## 1. 产品定位

MetricSleuth 是一个 **AI 自主数据调查与诊断系统**。

当业务指标出现异常时，系统读取受治理的真实业务数据，计算指标及其变化，向 Agent 提供查询工具。Agent 根据每次查询返回的 Observation 动态决定下一步调查动作，逐步缩小异常主要集中的指标和维度，最后输出带数据依据、可追溯的调查结论。

它的核心不是让模型自由生成 SQL，也不是把固定 SQL 流程包装成聊天窗口，而是让模型负责调查策略，让应用负责指标语义、查询边界、工具安全、证据引用和结论校验。

- **Confirmed：** 电商是第一个验证领域，不是产品的永久定义。
- **Confirmed：** 首个领域继续沿用仓库已有的 Amazon/电商指标、数据和评测资产，以尽快证明完整、真实、可运行的调查闭环。
- **Confirmed：** 产品最终应是可部署、可持续运行、可由浏览器操作的完整软件，而不只是预制结果 Demo。
- **Current：** 仓库当前主要实现的是受控 Synthetic Benchmark 上的 Amazon/电商调查内核与 Diagnosis Workspace；这不等同于最终产品已经完成。

## 2. 目标用户与主要场景

### 目标用户

- **业务分析人员或运营人员（Confirmed）：** 发现经营指标变化后，希望快速知道变化集中在哪些维度，并查看数据依据。
- **数据/产品负责人（Confirmed）：** 需要一个可追溯的异常调查结果，而不是只有一句模型生成的解释。
- **项目维护者与评审者（Confirmed）：** 通过真实模型调用、工具轨迹、评测记录和可复现结果，判断 AI 应用是否可靠。

### 首个使用场景

用户在工作概览或业务指标页面发现某指标异常，选择数据来源、指标和调查时间范围，启动一次调查。系统计算异常并运行 Agent；用户可以查看每次工具调用、Observation、当前进度、最终 Driver/Scope、证据和限制说明，并在历史记录中重新打开结果。

### 实验场景

用户在与真实数据隔离的实验室中制造可控数据变化，经正常的指标计算、异常发现和 Agent 调查流程运行，用于验证系统是否能定位预期 Driver 与 Scope。实验结果必须标记为实验数据，不得污染真实数据环境，也不得直接修改前端数字冒充业务事件。

## 3. MVP 功能边界

下表定义认可的 MVP 目标，不代表每项在当前源码中已经实现。

| 能力 | 状态 | MVP 要求与边界 |
| --- | --- | --- |
| 工作概览 | Confirmed | 展示数据源、指标状态、近期调查和任务状态；页面为体验基线，后端能力需补齐。 |
| 业务指标 | Confirmed | 展示有语义定义、计算口径、支持维度和异常状态的指标；不承诺所有指标共享同一粒度。 |
| AI 调查工作区 | Confirmed / Current | 保留现有调查工作区；最终需展示实时进度、工具调用、Observation、Evidence、Diagnosis 和失败原因。当前工作区主要连接现有调查 API。 |
| 数据接入 | Confirmed | 至少打通一个经过验证的真实外部数据源，并具备刷新状态、只读边界和来源标识。具体采用 Shopify、外部 PostgreSQL 或其他方案，在真实接口验证前为 **Unknown**。 |
| 数据实验室 | Confirmed | 提供隔离的 Sandbox 数据和可控变化；实验数据与真实外部数据、Synthetic Benchmark 分环境/来源存储。 |
| 异常发现 | Confirmed | 支持指标刷新后的异常检测，并能由用户启动调查；自动 Webhook 触发不是 MVP 必需条件。 |
| 动态 Agent 调查 | Confirmed / Current | Agent 必须根据 Observation 选择下一工具动作并可停止；当前 Agents SDK Runtime 和工具链已存在，但真实外部数据上的端到端验证尚未完成。 |
| 证据与可追溯性 | Confirmed / Current | 结论只能引用本次工具调用产生的 Observation，并能回到工具参数、数据来源和查询快照；当前 Observation/Evidence/Diagnosis 校验已存在，持久化 provenance 尚不完整。 |
| 任务与历史 | Confirmed / Current | Run、状态、失败、工具轨迹、证据和诊断结果必须持久保存，服务重启后可查看；持久化、Worker、步骤保存及显式配置的任务/历史 API 已在真实 PostgreSQL 验收。默认应用尚未配置服务，前端与真实模型 Runner 未接线。 |
| 评测 | Confirmed / Current | 保留 Synthetic Benchmark 和真实模型评测，区分 Hermetic、Mock、真实模型和真实数据；需要可重复保存每次 Run 的结果与停止条件。 |
| 部署 | Confirmed | 可在个人服务器上长期运行，包含最小安全配置、数据备份/恢复和健康检查；当前没有完整生产部署闭环。 |

### MVP 明确不要求

- 一开始支持多个行业或通用多 Domain 框架。
- 让用户在产品内自由编写任意 SQL。
- 让所有指标、数据源和维度强行共用一个事实表或粒度。
- 复杂后台管理、微服务、消息队列或 Kubernetes。
- 在没有数据粒度证据时推导商品级转化率、流量归因等指标。

## 4. 认可的产品原型与界面边界

- **Confirmed：** 已认可的产品体验包含五个页面/区域：工作概览、业务指标、AI 调查工作区、数据接入、实验室。它是 MVP 的用户体验基线，后续实现应优先补齐数据和状态，不重新发起大幅 UI 改版。
- **Unknown：** 该独立 HTML 交互原型当前未出现在仓库中；仓库目前可见的是 `frontend/index.html` 和 React 前端代码。原型文件需要产品方提供后再纳入对照验收，不能依据记忆自行重建。
- **Current：** `frontend/src/` 与 `backend/app/api/routes.py` 已提供部分调查工作区、指标图、场景和调查接口，但不代表五个页面都已实现。

产品最终体验应形成以下闭环：

```text
工作概览/指标异常
        ↓
选择来源与调查范围
        ↓
启动调查并查看进度
        ↓
Agent 调用受治理工具，按 Observation 动态下钻
        ↓
查看 Tool Trace → Observation → Evidence → Diagnosis
        ↓
保存、复查和分享可追溯结果
```

## 5. 数据来源与隔离原则

### 数据类别

| 类别 | 状态 | 规则 |
| --- | --- | --- |
| Synthetic Benchmark | Current / Confirmed 保留 | 用于回归、已知异常案例和离线评测；不得冒充真实外部业务数据。仓库相关资产位于 `warehouse/`。 |
| Sandbox Data | Confirmed | 用于隔离实验和可控异常注入；必须有独立来源/环境标识，不写入真实数据环境。 |
| 真实外部数据 | Confirmed 目标 / Unknown 来源 | 至少选择一个可持续刷新且权限明确的来源完成纵向闭环。外部 PostgreSQL、Shopify 和 Olist 都不能在未完成运行验证前宣称为已接入产品。 |
| Olist 公开数据 | Current | `docs/phase-9-olist-real-world-validation.md` 与 `configs/olist_validation_metrics.yaml` 记录的是隔离映射/工具兼容性验证，不是当前产品 Runtime 的数据源。 |

所有调查结果至少需要知道 `source_id`、来源类型、环境、数据时间范围和数据快照/刷新信息。指标是否支持某个维度，必须由来源能力和粒度验证决定；不能仅凭字段名称拼接跨粒度指标。

### 数据源取舍

- **Current：** `warehouse/` 与 `configs/metrics.yaml` 支撑单一 Synthetic Amazon Profile；`AnalyticsTools` 可以执行传入的 PostgreSQL 查询，但这不等于已经支持用户接入任意外部 PostgreSQL。
- **Unknown：** Shopify 是否作为第一真实来源，需先验证权限、历史窗口、粒度、时区、退款/取消口径及各指标可用维度。
- **Deferred：** Webhook 自动触发、更多外部来源和第二行业，待一个真实来源闭环稳定后再做。

## 6. Agent、证据与运行约束

- **Confirmed：** 正式 Runtime 优先复用 OpenAI Agents SDK；运行时替换、Jev 策略和其他 Harness 不进入当前 MVP 主线。
- **Confirmed：** 应用控制 Metric Semantic Layer、工具白名单、查询预算、安全规则、Observation 结构和 Diagnosis 校验；模型不能伪造 Observation 或直接提交未经证据支持的结论。
- **Current：** `backend/app/agent_runtime/`、`backend/app/analytics/`、`backend/app/observations/`、`backend/app/evidence/` 和 `backend/app/diagnosis/` 已形成调查内核，但主要测试使用 Scripted/Mock 组件，不能把测试通过等同于真实模型和真实数据验证。
- **Confirmed：** 任何 Driver、Scope 或结论都必须能追溯到本次调查的实际工具调用和 Observation；无法支持的内容应明确标记不确定或拒绝。

## 7. 非目标与延后事项

以下内容不属于当前 MVP 的完成条件：

- **Deferred：** Jev 作为 Investigation State → Next Action 的替代策略及其与 LLM 的系统性成本/正确率比较。
- **Deferred：** Webhook 事件接收、自动触发调查和外部通知。
- **Deferred：** Codex、DeepSeek 或其他可替换 Harness；除非有独立决策记录，不新增第二套 Runtime。
- **Deferred：** 多 Agent 协作、RAG、知识图谱、微服务和复杂基础设施。
- **Deferred：** 第二行业 Profile；电商验证成功前不以扩展行业代替主线交付。
- **Not a goal：** 传统电商管理后台、普通 BI Dashboard、无治理 Text-to-SQL 聊天工具、固定 SQL 调查脚本或通用 Chatbot。

## 8. 成功验收标准

MVP 只有在以下条件全部满足后，才能对外称为“真实可运行的 MetricSleuth MVP”：

1. 用户可通过浏览器访问认可的五页面体验，并在不依赖开发者手工改数据库的情况下选择来源、查看指标和启动调查。
2. 至少一个真实外部数据源能够安全、只读、可持续刷新；系统明确标识真实、Synthetic 和 Sandbox 数据。
3. 用户可观察到 Agent 基于真实 Observation 动态选择至少两步调查动作，或在证据不足时正确停止；不是预先播放的固定结果。
4. 每个最终结论都能回到 Tool Call、查询参数/摘要、Observation、Evidence、来源和数据时间范围；不可支持的 Driver/Scope 不得被展示为事实。
5. Run 状态、进度、失败信息、Tool Trace、Evidence 和 Diagnosis 持久保存，服务重启后可恢复历史结果。
6. Sandbox 能制造可控变化并通过正常调查流程验证，且不会污染真实数据或 Benchmark。
7. 有脱敏、可重复的评测记录，分别说明 Mock/Hermetic、真实模型、Synthetic 数据和真实外部数据的验证范围；不以单元测试替代真实模型验收。
8. 系统具备个人服务器长期运行所需的最小部署、健康检查、日志、超时、密钥注入和备份/恢复能力。

## 9. 关联文档

以下路径用于核对当前实现，不改变本文件定义的产品目标：

- `README.md`：当前仓库运行方式与历史实现声明。
- `任务书.md`：历史阶段计划；与本文件冲突时，以本文件的最新产品边界为准。
- `docs/mvp-demo-brief.md`：当前 Stage 1 Demo 的能力和限制。
- `configs/metrics.yaml`：当前指标语义配置。
- `backend/app/api/routes.py`：当前 FastAPI 路由入口。
- `warehouse/`：当前 Synthetic Warehouse、场景和评测资产。
- `docs/phase-9-olist-real-world-validation.md`：Olist 隔离验证记录。
