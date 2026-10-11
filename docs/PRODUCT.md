# MetricSleuth 产品定义

> 文档性质：稳定产品方向与 MVP 验收口径。
> 更新基线：2026-10-10（R4-002 React 接线与受控 HTTP 浏览器验收完成）。
> 状态词：**Confirmed** 表示已经确认的产品决策；**Current** 表示源码当前事实；**Deferred** 表示明确延后；**Unknown** 表示尚未通过仓库或运行证据确认。

## 1. 产品定位

MetricSleuth 是一个 **AI 自主数据调查与诊断系统**。

当业务指标出现异常时，系统读取受治理的真实业务数据，计算指标及其变化，向 Agent 提供查询工具。Agent 根据每次查询返回的 Observation 动态决定下一步调查动作，逐步缩小异常主要集中的指标和维度，最后输出带数据依据、可追溯的调查结论。

它的核心不是让模型自由生成 SQL，也不是把固定 SQL 流程包装成聊天窗口，而是让模型负责调查策略，让应用负责指标语义、查询边界、工具安全、证据引用和结论校验。

- **Confirmed：** 电商是第一个验证领域，不是产品的永久定义。
- **Confirmed：** 首个领域继续沿用仓库已有的 Amazon/电商指标、数据和评测资产，以尽快证明完整、真实、可运行的调查闭环。
- **Confirmed：** 产品最终应是可部署、可持续运行、可由浏览器操作的完整软件，而不只是预制结果 Demo。
- **Current：** 仓库已有受控 Synthetic/Olist PostgreSQL 调查内核、持久任务 API/Worker 和 React 工作区。R4-002通过受控HTTP交互验收，R4-003通过实际PostgreSQL/API/浏览器既有Olist失败历史读取及刷新重读；不等同于真实模型成功或最终产品闭环。

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
| 工作概览 | Confirmed / Current | 展示来源及当前来源最多 20 条任务的状态计数与历史；计数不是全库总量，指标数值/异常扫描尚未接入。 |
| 业务指标 | Confirmed / Current | 页面仍展示指标、粒度和维度能力目录。R4-006后端已有单源单日数值、前7日基线与异常候选读取接口并经实际PG验收，尚未接入页面；不是实时趋势或持续更新。 |
| AI 调查工作区 | Confirmed / Current | React 已提交调查并读取持久任务列表/详情，展示实际返回的状态和事实。受控HTTP交互、真实数据库既有失败历史读取、R4-005新提交与成功Diagnosis的受控真实SQL闭环已验收；新模型成功调查仍未验收。 |
| 数据接入 | Confirmed / Current | 页面读取服务器配置来源目录及能力声明；该目录不表示连接成功、健康、刷新或日期覆盖。外部源连接器尚未实现。 |
| 数据实验室 | Confirmed / Current | 五导航区域已保留；实验区明确显示未接入且不写数据。Sandbox 操作尚未实现。 |
| 异常发现 | Confirmed | 支持指标刷新后的异常检测，并能由用户启动调查；自动 Webhook 触发不是 MVP 必需条件。 |
| 动态 Agent 调查 | Confirmed / Current | Agent 必须根据 Observation 选择下一工具动作并可停止；当前 Agents SDK Runtime 和工具链已存在，但真实外部数据上的端到端验证尚未完成。 |
| 证据与可追溯性 | Confirmed / Current | 结论只能引用本次工具调用产生的 Observation，并能回到工具参数、数据来源和查询快照；当前 Observation/Evidence/Diagnosis 校验与持久化来源外键已通过受控数据库验收，数据版本仍是标签，可靠查询快照尚未实现。 |
| 任务与历史 | Confirmed / Current | Run、状态、失败、工具轨迹、证据和诊断结果必须持久保存，服务重启后可查看；持久化、Worker、步骤、任务 API 和显式本地启动入口已在真实 PostgreSQL 受控验收，默认 React 工作区已消费任务 API。默认旧 `app` 仍不自动注入任务服务；新 Runner 已实现，真实模型待验收。 |
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
- **Current / Confirmed：** 产品方于 2026-10-10 提供仓库根目录的 `MetricSleuth_%E4%BA%A4%E4%BA%92%E4%BA%A7%E5%93%81%E5%8E%9F%E5%9E%8B.html`，作为冻结的体验基线，保留原文件，不擅自重新设计。文件 SHA-256：`ae62216b9871c4cf2ee3651ea5e4d1c87a10d499beca2897db69dc80823fe76c`。
- **Current（R4-002）：** `frontend/src/App.tsx` 将默认 React App 接到 `InvestigationWorkspace`；五个原型导航区域保留。工作概览显示当前来源列表页（每页最多20条）的调查计数；业务指标页展示目录能力；数据页展示配置来源及限制；实验室明确未接入。只有调查任务/历史详情及来源/指标能力目录通过 task API 提供数据，其他页面不宣称实时指标或连接状态。
- **Current：** `frontend/src/tasks/client.ts` 的 `createTaskClient` 供 React 读取来源、提交任务、分页列举和读取详情。`InvestigationWorkspace` 对 queued/running 任务每2秒轮询，终态或读取错误时停止/展示安全错误；页面不实现取消、自动重试、追问、固定进度或实验数据注入。失败记录仅展示已保存事实，不构造缺失 Diagnosis。
- **Current（验证边界）：** R4-002 已由主线程在真实本机 Edge 配合受控 HTTP fixture 验收，覆盖翻页、提交/轮询停止、失败与成功历史事实、来源切换和未配置服务错误；它没有连接 PostgreSQL 或模型。记录见 [`task-workspace-acceptance-2026-10-10.md`](evaluation-artifacts/task-workspace-acceptance-2026-10-10.md)。视觉规则事实提取见根目录 `DESIGN.md`，原 HTML 仍为设计权威。
- **Current（R4-003）：** 真实PostgreSQL/独立任务API/Edge读取既有Olist失败调查4Tool Call/27Observation，刷新重读通过；没有新增任务或模型调用。见 [`postgres-browser-history-acceptance-2026-10-10.md`](evaluation-artifacts/postgres-browser-history-acceptance-2026-10-10.md)。

原型为自包含静态交互文件，不是已接入后端的产品。其硬编码指标、固定步骤/定时进度、预设追问回答、示例历史与前端场景切换只说明体验，不能作为真实运行证据。

| 原型区域 | 可复用资产 | 真实接线边界 |
| --- | --- | --- |
| 工作概览 | 持久调查列表/状态 API | 当前计数只涵盖所选来源当前页最多20条；指标异常数值与刷新状态仍需真实查询。 |
| 经营指标 | `/api/investigation-sources` 来源能力目录 | 目前展示指标/粒度/维度声明，不是趋势图、数值计算或来源在线检查。 |
| AI 调查 | POST/GET `/api/investigations` 与来源目录 | React 已接入；显示服务端实际状态和持久化事实。取消、自动重试、追问尚无持久接口。示例 `analytics.compare_metric` 不是现有工具合同。 |
| 数据接入 | 来源能力合同、显式单源应用配置 | 目录不探测连接或数据新鲜度；持续外部连接器/刷新 API 未实现。 |
| 体验实验室 | Synthetic Benchmark 与隔离测试资产 | 当前页面是未接线说明；尚无可操作的隔离数据变化流程。 |

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
| Olist 公开数据 | Current | 显式本地任务应用已有 `olist_validation` Profile。隔离 PostgreSQL 上实际导入/查询公开静态订单数据，并验收失败前步骤留存和新应用读取；行动由受控 Runner 选择，无 Olist 模型验收。不是默认产品数据源或持续连接器；见 `docs/evaluation-artifacts/olist-persistence-acceptance-2026-10-10.md`。 |

所有调查结果至少需要知道 `source_id`、来源类型、环境、数据时间范围和数据快照/刷新信息。指标是否支持某个维度，必须由来源能力和粒度验证决定；不能仅凭字段名称拼接跨粒度指标。

### 数据源取舍

- **Current：** `warehouse/` 与 `configs/metrics.yaml` 支撑单一 Synthetic Amazon Profile；`AnalyticsTools` 可以执行传入的 PostgreSQL 查询，但这不等于已经支持用户接入任意外部 PostgreSQL。
- **Confirmed（2026-10-10资源选择）：** 用户暂无业务PostgreSQL、可准备Shopify开发店，下一外部接口验证优先Shopify订单域；开发店为sandbox，不称真实生产经营数据。实际权限、覆盖/粒度/币种/退款口径仍Unknown，未实现连接器。资料与准备清单见 [`data-source-selection.md`](data-source-selection.md)。最终MVP经营数据目标不因此降低。
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
