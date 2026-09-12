# MetricSleuth Agent 实时运行状态 (Agent Operational State)

## 0. 状态元数据

- **Document Role**: Dynamic operational state
- **Snapshot Date**: 2026-09-12
- **Current Phase**: Stage 1 MVP Stabilization / Acceptance
- **Current Task**: Final factual reconciliation and live acceptance gate
- **Current Task Status**: Real Provider run executed; Live Agent acceptance failed closed on an invalid Observation reference
- **Last Verified Batch**: 2026-09-12 final hardening and reconciliation
- **Current Blocker**: configured compatible model did not conform to the evidence-reference contract during the Canonical Run
- **Current Phase Status**: Portfolio MVP implementation complete; final Live acceptance not passed
- **Later Work**: only after the Live gate; no new feature task is active

---

## 1. 状态文档权威边界

- **`docs/agent-state.md`**：当前执行状态、任务进展、验证结果与阻塞项的**唯一动态权威来源**。
- **`任务书.md`**：架构设计、产品目标与 Phase 演进边界的最高权威来源。
- **实际代码与测试**：证明当前已经真实实现并验证的行为事实。
- **`AGENTS.md`**：长期稳定的接管规则、仓库地图、不变量与维护协议。
- **`docs/project-learning-log.md`**：历史演进复盘、深度技术剖析与面试复习资料。
- **冲突处理原则**：发生状态或设计冲突时，严禁静默修改，必须报告冲突并以代码、测试与 `任务书.md` 进行核对。

---

## 2. 任务状态矩阵

| Task ID | Phase | 任务名称 | 状态 |
|---|---|---|---|
| `MS-SC-001` | Scaffold | Python 基础脚手架 | Accepted |
| `MS-P0-001` | Phase 0 | 人工调查契约 | Accepted |
| `MS-P1-001` | Phase 1 | Data Foundation | Accepted |
| `MS-P2-001` | Phase 2 | Metric Semantic Layer | Accepted |
| `MS-P2-002` | Phase 2 | 配置校验加固与学习文档补全 | Accepted |
| `MS-P2-003` | Phase 2 | 学习日志事实与阶段边界纠偏 | Accepted |
| `MS-P2-004` | Phase 2 | 创建 Agent 接管文档并修正学习日志安全边界 | Accepted |
| `MS-P2-005` | Phase 2 | 建立 Agent State 单一动态状态源 | Accepted |
| `MS-P3-001` | Phase 3 | 最小 Analytics Query 垂直切片 | Accepted |
| `MS-P3-002` | Phase 3 | Related Metrics 与完整人工调查闭环 | Accepted |
| `MS-P4-001` | Phase 4 | SQL AST Guard 静态安全基础 | Accepted |
| `MS-P4-002` | Phase 4 | PostgreSQL Readonly Role 与权限验证 | Accepted |
| `MS-P4-003` | Phase 4 | ToolResult → Observation 可追溯转换基础 | Accepted |
| `MS-P4-004` | Phase 4 | Observation → Evidence 显式提升契约 | Accepted |
| `MS-P5-001` | Phase 5 | OpenAI Agents SDK Runtime Capability Spike | Live capability observed during MS-P6-004 attempt |
| `MS-P5-001-R1` | Phase 5 | Runtime budget/trace fail-closed hardening | Accepted |
| `MS-P6-001` | Phase 6 | Runtime Analytics Tool Bridge | Accepted |
| `MS-P6-002` | Phase 6 | Investigation Run Contract 与多调用 Trace 验证 | Accepted |
| `MS-P6-003` | Phase 6 | Development Scenario Investigation Harness | Accepted |
| `MS-P6-004` | Phase 6 | Live Development Set Agent Evaluation | Executed — FAIL (unknown Observation reference) |
| `MS-P7-001` | Phase 7 | Structured Diagnosis Domain Contract | Accepted |
| `MS-P7-002` | Phase 7 | Diagnosis Draft Resolution 与 Evidence Citation Verification | Accepted |
| `MS-P7-003` | Phase 7 | Evidence Selection Draft 与 Observation Citation Resolution | Accepted |
| `MS-P7-004` | Phase 7 | Observation-to-Diagnosis Composition Contract | Accepted |
| `MS-P7-005` | Phase 7 | SDK Trace Observation Catalog Extraction | Accepted |
| `MS-P7-006` | Phase 7 | Runtime Structured Diagnosis Intent Contract | Accepted |
| `MS-P7-007` | Phase 7 | Hermetic Evidence-driven Diagnosis Runtime Integration | Accepted — Hermetic only |
| `MS-P8-001` | Phase 8 | Evaluation Case Contract 与 Deterministic Scoring Foundation | Accepted |
| `MS-P8-002` | Phase 8 | Core Evaluation Aggregate Report | Accepted |
| `MS-P8-003` | Phase 8 | Evidence Obligation Contract | Accepted |
| `MS-P8-004` | Phase 8 | Evidence Citation Precision 与 Coverage Scoring | Accepted |
| `MS-P8-005` | Phase 8 | Unsupported Claim Contract 与 Scoring | Accepted |
| `MS-P8-006` | Phase 8 | Evaluation Run Outcome 与 Tool Operational Scoring | Accepted |
| `MS-P8-007` | Phase 8 | Tool Operational Aggregate Report | Accepted |
| `MS-P8-008` | Phase 8 | Unified Evaluation Aggregate Report | Accepted |
| `MS-P8-009` | Phase 8 | Hermetic Evaluation Runner Contract | Accepted |
| `MS-P8-010` | Phase 8 | Evaluation Manifest 与 Reproducibility Contract | Accepted |
| `MS-P8-011` | Phase 8 | Evaluation Run Identity 与 Manifest Reconciliation Contract | Implemented — current regression PASS |
| `MS-P8-012` | Phase 8 | Repeated-Run Evaluation Report 与多运行聚合计算器 | Implemented — current regression PASS |
| `MS-P8-013` | Phase 8 | Benchmark 场景扩展 (10 受控场景与标准评测集) | Implemented — current regression PASS |
| `MS-P8-014` | Phase 8 | Benchmark 评测管道与自动化报告生成脚本 | Implemented — Hermetic run verified |
| `MS-P10-001` | Phase 10 | FastAPI 最小后端服务与 RESTful 接口 | Accepted |
| `MS-P10-002` | Phase 10 | React Diagnosis Workspace 前端工作台 | Implemented — lint/build verified |

> **注意**：执行 Agent（Gemini）无权自行将任何任务或 Phase 标记为 `Accepted`。

---

## 3. 当前实现状态

### 3.1 已实现能力
- Python 3.12+ 基础脚手架与包元数据声明（当前测试环境解释器为 Python 3.13.5，满足 `>=3.12`）；
- Phase 0 人工调查契约与缺口贡献计算规范；
- Phase 1 PostgreSQL Benchmark 数据集（`dim_products`, `fact_daily_performance`）；
- 确定性 Seed 生成器（558 行基准记录）；
- `canonical`、`traffic`、`no_anomaly` 三种确定性场景注入器；
- Canonical Case 原生 PL/pgSQL 自动化验收脚本（PASS）；
- Phase 2 五个核心指标语义配置（`configs/metrics.yaml`）；
- 不可变 `MetricRegistry` 与 `MetricDefinition`；
- Fail-Fast 配置校验守卫与领域异常；
- 学习日志（`docs/project-learning-log.md`）；
- Agent 接管规则（`AGENTS.md`）；
- 单一动态状态源（`docs/agent-state.md`）；
- Phase 3 最小 Analytics Tools 完整 API 表面：`get_metric_definition()`、`query_metric()`、`query_related_metrics()`；
- `MetricQueryRow.dimensions` 与 `RelatedMetricQueryResult.results` 深层不可变封装；
- 支持单日 Current 与前 7 日 Baseline 对比；
- 支持 additive 7 日日均、ratio 汇总分子除以汇总分母、relative_change 与 sample_size（Baseline 日均 Sessions）计算；
- 支持白名单 filters 与 group_by 维度聚合；
- 真实 PostgreSQL Warehouse 查询验证与 Canonical Case 完整人工调查验证脚本通过；
- Phase 4 纯静态 SQL AST Guard 安全分析器（`backend/app/sql_safety/`）；
- Phase 4 PostgreSQL 独立只读角色与权限体系（`warehouse/setup_readonly_role.sql` 与 `warehouse/verify_readonly_role.py`）：
  - 角色属性：`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 5`；
  - 无任何外部角色成员关系；
  - 权限严格收敛：仅授予 `USAGE ON SCHEMA warehouse` 与 `SELECT ON warehouse.dim_products`, `SELECT ON warehouse.fact_daily_performance`，无写权限、无 DDL 权限、无表 ownership、无 App/System catalog 特权；
  - 数据库作用域安全默认值（`metricsleuth` 库）：`default_transaction_read_only = on`, `statement_timeout = '1000ms'`, `search_path = pg_catalog`；
  - 环境变量安全注入：密码通过 `METRICSLEUTH_READONLY_PASSWORD` 动态传入，验证连接通过 `READONLY_DATABASE_URL` 动态传入，零密码硬编码；
  - 独立集成验证测试（`verify_readonly_role.py`）全量 PASS；
- Phase 4 ToolResult $\rightarrow$ Observation 可追溯转换基础（`backend/app/observations/`）：
  - 不可变 `Observation` 领域模型（`@dataclass(frozen=True)`，`filters` 和 `dimensions` 运行时只读 `MappingProxyType` 封装，`group_by` 独立快照 tuple，`created_at` 强制带时区并标准化为 UTC）；
  - 失败状态模型级不变量强制校验；
  - 标准化 `ObservationStatus` 状态契约（`normal`, `anomalous`, `inconclusive`, `insufficient_evidence`, `failed`）；
  - 确定性状态分类转换器与作用域 ID 生成（Related Metrics 展平转换时显式注入 `rel{sub_idx}` 前缀保证 100% 唯一）；
- Phase 4 Observation $\rightarrow$ Evidence 显式提升契约（`backend/app/evidence/`）：
  - **二元组确定性 ID 契约与模型级校验（MS-P4-004-R1）**：ID 规则为 `evidence:{observation_id}:{role.value}`，私有 `_derive_evidence_id` 单一真理源，`Evidence.__post_init__` 强制校验实际 `evidence_id` 严格等于根据 `(observation_id, role)` 派生出的期望 ID，保证同一 Normal 观察的不同角色 ID 严格隔离且防伪造；
  - 显式提升函数 `promote_observation_to_evidence(observation, *, role)`（不重新计算指标、不查询数据库、确定性生成 `evidence:{observation_id}:{role.value}`，重复提升幂等）；
  - 失败 Evidence 严格保留错误上下文且四个数值字段强制为 `None`；
- Phase 5 OpenAI Agents SDK Runtime Spike（`backend/app/agent_runtime/`）：
  - 采用官方 `openai-agents==0.22.0` Python SDK；
  - **执行前线程安全原子预算拦截（MS-P5-001-R1）**：`ToolCallBudgetGuard` 使用 `threading.Lock` 在进入 `AnalyticsTools.get_metric_definition()` 之前原子校验并扣减预算，超出预算立即抛出 `RuntimeBudgetExceededError`，底层业务工具调用次数严格为 1；
  - **Fail-Closed 异常配置（MS-P5-001-R1）**：生产代码明确配置 `function_tool(get_metric_definition, failure_error_function=None)`，确保预算异常直接穿透 Runner 造成执行失败，坚决阻止异常转化为错误文本回传给模型伪造输出；
  - **严格 Trace 时序与 Call ID 配对校验（MS-P5-001-R1）**：`verify_runtime_trace_and_budget` 强制检验 `expected_tool_name`、`ToolCallItem.call_id == ToolCallOutputItem.call_id` 以及偏序关系 `ToolCall → ToolCallOutput → last MessageOutput`；
  - **结构化输出交叉验证（MS-P5-001-R1）**：`cross_validate_structured_output` 强制要求 `final_output.metric_id`、`final_output.unit`、`final_output.tool_used` 严格与真实 Tool Output 及预期工具一致；
  - **公开轮次统计（MS-P5-001-R1）**：固定使用 `len(result.raw_responses)` 统计实际模型调用轮次，校验 `1 <= turns_count <= max_turns`，杜绝使用私有字段；
  - 24 项覆盖全部反例的 Hermetic 单元测试全部通过。
- Phase 6 Runtime Analytics Tool Bridge（`backend/app/agent_runtime/investigation_tools.py`）：
  - 将 `get_metric_definition()`、`query_metric()` 与 `query_related_metrics()` 封装为三个官方 SDK `FunctionTool`，共享同一预算边界；未实现自制 Loop 或固定下钻路径；
  - 使用 SDK 公共 `ToolContext.tool_call_id` 生成可追溯 Observation，并通过显式 JSON 边界保留 Decimal、日期、状态和查询上下文；
  - 两个 Tool 共享每次调查默认 8 次的线程安全预算，失败调用计入预算，第 9 次在底层查询前 Fail Closed；
  - Tool 输入保持 strict schema；过滤条件使用 `DimensionFilter` 结构化数组，再转换为 AnalyticsTools 的 Mapping 契约；
  - 11 项 Hermetic Bridge 测试覆盖参数转发、严格日期、真实 SDK 调用、共享/并发预算、错误传播、空结果与 Ground Truth 隔离。
- Phase 6 Investigation Run Contract（`backend/app/agent_runtime/investigation_runtime.py`）：
  - `create_investigation_agent()` 只装配官方 SDK Agent 与两个受控 Tool，不编码固定调查路径；
  - `run_investigation()` 为每次 Run 创建独立预算并调用 `Runner.run_sync()`，业务代码没有自制 Agent Loop；
  - `verify_investigation_trace()` 使用 SDK 公共 RunItem 字段审计多 Tool Call/Output 身份、顺序、Observation ID、最终 Message、工具预算与模型轮次；
  - SDK `ScriptedModel` 已跑通两种不同 Tool 顺序的真实 Runner 编排，明确只证明 Hermetic orchestration contract，不声称真实模型自主性；
  - 9 项专项测试覆盖成功路径和错误工具、重复/孤儿 Call ID、逆序 Output、身份串线、重复 Observation、非法 Output、预算和轮次等反例。
- Phase 6 Development Scenario Harness（`backend/scripts/verify_phase6_development_scenarios.py`）：
  - Canonical、Traffic、No-anomaly 共用同一套测试侧探针矩阵；不把 Ground Truth 用于选择查询；
  - Canonical 使用转化订单缺口定位 Conversion Rate 贡献，Traffic 使用 Sessions 缺口定位流量贡献，No-anomaly 全局稳定时返回无实质异常；
  - 三场真实 PostgreSQL 记录的 status、driver、scope、stable metrics 和负向对照集合均与 Ground Truth 精确匹配；
  - Ground Truth 在所有实际记录生成后才由脚本加载评分，`backend/app` 全量扫描确认零引用；
  - Harness 完成后恢复 canonical 场景；该固定探针仅为 Benchmark Oracle，不是生产 Agent Workflow。
- Phase 7 Structured Diagnosis Domain Contract（`backend/app/diagnosis/`）：
  - 不可变 `Diagnosis` / `DiagnosisChange` 与五状态终止契约；Mapping、tuple 和 UTC 时间均在模型入口防御性规范化；
  - `build_diagnosis()` 只从实际 Evidence 派生引用与目标变化值，拒绝缺少目标、Driver、Scope 支撑或 negative control 的 diagnosed 结论；
  - `no_material_anomaly` 拒绝异常的非 limitation Evidence；`tool_failure` 与 `budget_exhausted` 允许零 Evidence，避免在工具尚未产出 Observation 时伪造证据；
  - 模型刻意不提供 `root_cause` 字段，结论边界保持在数据异常贡献定位；
  - 12 项专项测试覆盖全部状态、证据缺失/冲突、深层不可变、UTC、确定性引用和字符串伪序列反例。
- Phase 7 Diagnosis Draft Resolution（`backend/app/diagnosis/draft.py`）：
  - `DiagnosisDraft` 只包含诊断意图和 Evidence ID，结构上不允许 Runtime 自填指标数值、change 或 root cause；
  - Resolver 对应用持有的 Evidence Catalog 做完整类型与唯一性检查，所有 Draft 引用必须精确命中；
  - 只选择 Draft 显式引用的 Evidence并保持其顺序，再复用 `build_diagnosis()` 执行跨 Evidence 领域校验；
  - Draft 的 Scope/ID/limitations 深层不可变，字符串伪序列、NaN/Infinity confidence、未知引用和重复 ID 均 Fail Closed；
  - 14 项专项测试通过；主线程同时加固直接 Diagnosis 对非有限 confidence 的领域异常封装。
- Phase 7 Evidence Selection Resolution（`backend/app/evidence/selection.py`）：
  - `EvidenceSelection` 仅包含 Observation ID 与 EvidenceRole，不允许输入任何指标事实字段；
  - Observation Catalog 先执行完整类型与唯一性校验，Draft 的每个引用必须精确命中；
  - 只提升显式选择的 Observation并保持顺序，统一复用既有 promoter 复制事实和校验 Status/Role；
  - 同一 Normal Observation 可承担 supporting 与 negative control 两个合法角色，并生成不同确定性 Evidence ID；
  - 14 项专项测试覆盖空选择、未知/重复引用、非法角色、深层不可变和事实字段隔离。
- Phase 7 Observation-to-Diagnosis Composition（`backend/app/diagnosis/composition.py`）：
  - 最小组合服务只编排两个已验收 Resolver，不复制 Evidence 或 Diagnosis 规则；
  - 不可变 `DiagnosisComposition` 同时保留完整 Evidence Portfolio 与最终 Diagnosis；
  - Diagnosis 引用必须是 Portfolio 子集，Portfolio 可保留未引用 Evidence 供 Coverage 审计；
  - 目标数值从源 Observation 经 Evidence 原样进入 Diagnosis，任何未知引用或领域冲突 Fail Closed；
  - 11 项专项测试覆盖 diagnosed、no-anomaly、budget exhausted、引用子集和跨层错误传播。
- Phase 7 SDK Trace Observation Catalog Extraction：
  - `observation_from_json()` 是 Tool Output JSON 到 Observation 的严格、Fail-Closed 对偶边界；
  - `extract_observation_catalog()` 先复用完整 Trace 审计，只读取 `ToolCallOutputItem`，不信任模型 Message/final output 中的事实；
  - 日期、Decimal、timezone、Enum、Mapping、list 与完整键集合均严格解析，领域异常统一为 RuntimeTraceError；
  - 并发 Output 可逆序完成，Catalog 按已验证 Tool Call 顺序规范化，保持确定性；
  - 12 项专项测试覆盖 roundtrip、伪造消息、畸形类型、失败状态与并发逆序 Output。
- Phase 7 Runtime Structured Diagnosis Intent（`backend/app/agent_runtime/diagnosis_intent.py`）：
  - 冻结、extra-forbid 的 Pydantic Schema 只表达引用与诊断意图，不包含指标事实或 root cause；
  - 官方 `AgentOutputSchema` 验证为 strict JSON Schema，所有对象节点关闭 additionalProperties；
  - JSON arrays 在模型内快照为 tuple，confidence 使用有限 Decimal 字符串边界；
  - 确定性转换为现有 EvidenceSelectionDraft 与 DiagnosisDraft，重复引用和状态语义仍由领域层校验；
  - 9 项专项测试覆盖 strict Schema、缺失/额外字段、深层不可变、Decimal 边界和事实字段隔离。
- Phase 7 Hermetic Evidence-driven Diagnosis Runtime（`backend/app/agent_runtime/diagnosis_runtime.py`）：
  - 官方 SDK Runner 与 FunctionTool、Trace Catalog、Structured Intent 和 DiagnosisComposition 端到端接通；
  - diagnosed 与 no-anomaly 使用不同 Tool 顺序通过真实 SDK ScriptedModel 编排；
  - 每次 Run 独立预算，未知 Observation、缺负向对照和非 Intent 输出均 Fail Closed；
  - 公开 Summary 保存实际 Structured Intent JSON，不暴露内部 Trace 审计 sentinel；
  - 7 项专项测试通过；只证明 Hermetic 编排，不证明真实模型自主性。
- Phase 8 Evaluation Case Contract 与 Core Scoring（`backend/app/evaluation/`）：
  - Ground Truth 仅由 Evaluation 层通过显式路径加载，Agent Runtime/查询面扫描保持零引用；
  - 当前三条开发 Case 使用严格键集合、状态不变量、深层不可变与唯一 ID/Scenario 契约；
  - 纯函数评分 status、target、driver、三层 scope、no-anomaly 和 exact match；
  - Ground Truth 合法公开命名，不使用动态 globals 绕过隔离扫描；
  - 12 项专项测试覆盖真实文件、畸形 JSON、重复标签、状态契约和评分反例。
- Phase 8 Core Evaluation Aggregate Report：
  - 多 Case 核心分数聚合为不可变报告，保留输入 Case 顺序；
  - status/target/driver/no-anomaly/exact-match 与三层 Scope 使用统一 Case 分母；
  - 所有率使用有限 Decimal，Macro Scope 必须等于三层均值；
  - 空输入、重复 Case ID、错误类型和报告字段不自洽均 Fail Fast；
  - 8 项专项测试通过。
- Phase 8 Evidence Obligation Contract：
  - Ground Truth 被展开为 target/driver/stable metric/negative-control member 四类义务；
  - 确定性 ID 与字段组合在模型入口自校验，组件分隔歧义 Fail Fast；
  - 固定维度及成员顺序保证可复现，Canonical 9 项、No-anomaly 13 项；
  - 5 项专项测试通过。
- Phase 8 Evidence Citation Precision 与 Coverage Scoring：
  - 只对 Diagnosis 实际引用的 Evidence 评分，未引用 Portfolio Evidence 不提升 Coverage；
  - Citation Precision 以已引用 Evidence 为分母，零引用时明确为 `None`，不伪装成 0%；
  - Evidence Coverage 以 Case 派生的 Obligations 为分母，一条 Evidence 可覆盖多个义务；
  - filter/dimension 同维度冲突时负向对照匹配 Fail Closed；
  - 10 项专项测试通过。
- Phase 8 Unsupported Claim Contract 与 Scoring：
  - 把成功 Diagnosis 拆为 target change、primary driver 与逐成员 scope claims；
  - 只允许 Diagnosis 实际引用的 Evidence 支撑 Claim，未引用 Portfolio Evidence 不计入；
  - 目标 Claim 校验 Evidence 身份、状态、角色和所有数值/单位完全一致；
  - Scope 上下文冲突 Fail Closed，非成功状态无成功事实 Claim 且比率为 `None`；
  - 11 项专项测试通过。
- Phase 8 Evaluation Run Outcome 与 Tool Operational Scoring：
  - 显式区分 completed、tool failure、budget exhausted 与 runtime failure；
  - 失败运行状态、调用计数和 failure code 必须由调用方提供，不从异常文本或缺失 Summary 猜测；
  - Tool Success 使用协议层配对合法输出/尝试调用口径，零调用时为 `None`；
  - Runtime 类型仅在适配成功 Summary 时延迟导入，Evaluation Core 不被迫加载 SDK；
  - 15 项专项测试通过。
- Phase 8 Tool Operational Aggregate Report：
  - 聚合多个逐 Run ToolOperationalScore，保留 Run 顺序并拒绝重复 case_id；
  - Tool Success 使用总成功调用/总尝试调用的 micro 分母，平均调用次数与预算耗尽率使用 Run 分母；
  - 空输入和零调用分母均明确为 None，不伪造 0%；
  - 7 项专项测试通过。
- Phase 8 Unified Evaluation Aggregate Report：
  - 组合 Core、Evidence Citation、Unsupported Claim 与 Tool Operational 四类已验收结果；
  - Evidence Precision 仅平均有定义的 Case，Coverage 按 Case 平均，Unsupported Claim 使用 Claim-micro 分母；
  - 保留 Case ID 与 diagnosis ID 的不同身份域，拒绝伪造对齐；
  - 3 项专项测试通过。
- Phase 8 Hermetic Evaluation Runner Contract：
  - `EvaluationRunRecord` 显式组合 Case、已观测 Outcome 与可选 DiagnosisComposition，不从异常文本猜测失败类型；
  - 无 Composition 的失败 Run 仍进入 Core、Evidence 与 Operational 分母，但不伪造 Diagnosis；
  - Runner 只编排既有纯评分器，不加载 Ground Truth 文件，不调用 SDK、数据库、网络或文件系统；
  - Outcome/Diagnosis 状态组合 Fail Closed：`completed` 禁止终止型失败 Diagnosis，Runtime Failure 禁止 Composition，Budget/Tool Failure 的可选 Composition 必须精确匹配；
  - 9 项专项测试通过。
- Phase 8 Evaluation Manifest 与 Reproducibility Contract：
  - 不可变 `EvaluationManifest` 记录模型、完整 Prompt、Metric Config Version、Dataset Version、逐 Case 运行次数与 UTC 创建时间；
  - Prompt 原样保留，标识符规范化；运行次数只接受正整数并拒绝 `bool`；Mapping 防御性快照且运行时只读；
  - `total_run_count` 为派生属性，不允许调用方伪造；
  - 模块不读取文件、环境变量、网络或数据库，不依赖 Runtime、SDK 或 Ground Truth Loader；
  - 10 项专项测试通过。
- Phase 8 Evaluation Run Identity 与 Manifest Reconciliation Contract：
  - `EvaluationRunRecord` 拥有显式提供的、规范化后的 `run_id`，保留 `case.case_id == outcome.case_id` 校验，明确区分 Case Identity（评测场景）与 Run Identity（具体单次执行）；
  - `ManifestEvaluationRunSet` 不可变集合模型建立 Manifest 声明与实际 Run 集合的对账边界：
    - 强制 `manifest` 为 `EvaluationManifest`，`records` 为非空 `EvaluationRunRecord` 序列快照（`tuple`）；
    - 强制所有规范化后的 `run_id` 在集合内唯一；
    - 精确对账：实际 Case 集合必须与 Manifest 完全相等，每个 Case 的实际执行次数必须与 `manifest.run_counts_by_case` 严格一致；任何缺失、额外或次数不符均 Fail Closed；
    - `actual_run_counts_by_case` 由 `records` 自动推导，保持 Manifest 声明顺序并封装为只读 `MappingProxyType`，调用方无法传入或篡改；
  - 现有 `run_hermetic_evaluation()` 保持单次 Pass（最多 1 个 Case）边界，新增单次 Pass 内 `run_id` 唯一性校验；
  - 16 项 Run Set 专项测试 + 11 项 Runner 专项测试通过。
- Phase 8 Benchmark 10 场景与 Anomaly Injector 扩展：
  - `warehouse/anomaly_injector.py` 扩展支持全量 10 个受控场景（覆盖 Conversion / Traffic / AOV 三大主驱动、US / UK / DE 三大站点、ASIN-A / B / C 三大商品、Ads / Organic 两类渠道、正常波动与轻微局部干扰项 Distractor）；
  - 支持 `--dry-run` 离线校验；动态验证特定场景的 target segment 存在性；
  - 建立标准评测集 `warehouse/benchmark_cases.json`，严格遵循 `GroundTruthCase` 契约并提供 10 个场景的完整标准答案标签与因果隔离边界；既有 `warehouse/ground_truth.json` 保持不变；
  - 17 项专项测试覆盖用例加载、ID/场景唯一性、驱动分布、义务展开与数据变异确定性。
- Phase 8 Benchmark 评测管道与自动化看板生成：
  - 实现端到端评测管道脚本 `backend/scripts/run_benchmark_evaluation.py`，支持离线 `--hermetic` 模拟与 Live Agent 运行双模式；
  - 完整串联 `EvaluationManifest` 声明 $\rightarrow$ 逐 Case 运行收集 $\rightarrow$ `ManifestEvaluationRunSet` 严格对账 $\rightarrow$ `aggregate_manifest_evaluation_run_set()` 跨运行聚合；
  - 生成高可读性 CLI 看板（展示总 Cases、总 Runs、宏 Driver/Scope/Exact 指标与逐 Case 明细），并支持 `--output-json` 报告导出；
  - 8 项专项测试覆盖 Manifest 对账、单次/多次运行管道、看板格式化与 JSON 导出。
- Phase 10 FastAPI 最小后端服务与 RESTful 接口体系（`backend/app/api/` 与 `backend/app/main.py`）：
  - `backend/app/api/schemas.py`: Pydantic V2 请求与响应数据交换模型，包括 `MetricGraphNode`/`Edge`、`ScenarioItem`、`InvestigationRequest`、`InvestigationResponse`（包含完整的 `DiagnosisItem`、`EvidenceItem` 列表、`TraceStepItem` 轨迹及 `BudgetUsage`）；
  - `backend/app/api/service.py`: 纯业务服务层，提供依赖图拓扑提取、10 场景清单加载、安全变异注入（无数据库时自动降级 Dry-run，非法场景阻断）、确定性离线 Mock 演示调查与真实 Live 调查编排；
  - `backend/app/api/routes.py`: 路由注册，暴露 `GET /health`、`GET /api/metrics/graph`、`GET /api/scenarios`、`POST /api/scenarios/inject`、`POST /api/investigate`；
  - `backend/app/main.py`: FastAPI 应用工厂，挂载 CORS 中间件（允许 Vite 前端 `http://localhost:5173` 等跨域访问）与 API 路由；
  - 15 项 API 专项单元测试全部通过。
- Phase 10 React Diagnosis Workspace 前端单页应用（`frontend/`）：
  - 技术栈：React + TypeScript + Vite + 原生 Vanilla CSS（严格禁止 TailwindCSS，遵循 Claude 陶土深灰与 ChatGPT 极简绿设计系统）；
  - `ControlBar`: 10 个受控 Benchmark 场景下拉切换、目标基准摘要、Mock/Live 模式开关、一键注入与自主排查操作；
  - `MetricGraph`: 层次化指标依赖拓扑与业务拆解树（Sales $\rightarrow$ Orders $\times$ AOV $\rightarrow$ Sessions $\times$ CR），支持目标与驱动指标动态红/绿高亮与点击指标公式弹窗；
  - `StructuredDiagnosisCard`: 状态徽章（`DIAGNOSED` / `NO_MATERIAL_ANOMALY`）、Target 变动、Primary Driver、Affected Scope 细分标签、置信度、会话预算开销与醒目的因果隔离限制声明；
  - `InvestigationTimeline`: 5 步时序时钟轨迹流，展示逐步工具调用、下钻维度与 Observation 摘要；
  - `EvidencePortfolio`: 支撑证据（Supporting）与排除对照（Negative Controls）分组卡片看板；
  - `ContinueInquiry`: 底部 Human-in-the-Loop 自然语言继续追问与快捷下钻建议输入区；
  - `npm run build` 耗时 144ms 顺利产出构建包；并通过 Playwright Browser Subagent 8 步全流程浏览器交互验证。
- 当前权威回归为 427 项后端单元测试全部通过；此前各节的数量是对应任务完成时的历史快照。

### 3.2 2026-09-11 MVP hardening batch

| Task ID | 事实状态 | 核心结果 |
|---|---|---|
| `EVID-001` | Verified | Driver 与完整 affected scope 必须由同一条 anomalous supporting Evidence 支撑，禁止证据拼接伪归因 |
| `ENV-001` | Verified | 本地 `.env` 就近加载且不覆盖显式环境变量；补齐运行依赖与隔离测试 |
| `LIVE-003` | Verified hermetically | 三场景验收契约、Citation、Budget、No-anomaly 与场景注入改为 fail-closed |
| `RUNTIME-SEM-001` | Verified hermetically | Agent 可通过受控 `get_metric_definition` 获取语义，生产 Prompt 未写死固定调查顺序 |
| `SEM-CORE-001` | Verified | Registry 去除固定五指标和单位白名单；Stage 1 YAML 仍只实现 Amazon Profile |
| `TRACE-CORE-001` | Verified hermetically | SDK Tool Call 参数与调用顺序形成只读 `InvestigationRunSummary.tool_trace` |
| `PRODUCT-TRUTH-001` | Verified | 场景 API 不泄漏 Ground Truth；Fixture Preview 与 Live Agent 在 API/UI 文案和行为上分离 |
| `CONFIG-SEC-001` | Verified | 示例配置仅保留占位凭据与官方 Provider 默认地址；仓库扫描未发现已知明文测试凭据 |
| `TRACE-API-001` | Verified | API Live Trace 唯一来源改为 SDK `InvestigationRunSummary.tool_trace`，组合工具内部调用不再冒充模型动作 |
| `LIVE-ARTIFACT-001` | Verified hermetically | 三场景验收增加原子脱敏 artifact、Traffic 完整 scope 与可信动态分支断言 |
| `LIVE-CONTRACT-001` | Verified hermetically | Runtime Prompt 与 Tool 文档明确单日 Current Period；Baseline 只由 `previous_7_days` 计算 |
| `LIVE-REF-001` | Verified hermetically | 仅对可唯一映射的 Observation-ID-as-Evidence-ID 表达差异做确定性归一化；未知或歧义引用继续 Fail-Closed |

### 3.3 明确未实现或未验收能力
- 云端多租户与生产级用户账号系统（属于 Stage 2 规划）
- 真实模型在开发集上的自主调查与 Diagnosis 验收（MS-P6-004 已执行，但 Canonical 场景未通过 Evidence/Observation 引用完整性校验）
- 大规模 Holdout 盲测数据集与在线全量 Agent 评测运行
- Go Gateway（Stage 1 保持轻量单体，严格避免过度工程）
- 有状态的连续追问 Session；当前追问是新的独立调查请求

---

## 4. 当前验证状态

- **Last Verification Date**: 2026-09-12
- **Backend Unit Tests**: 436/436 PASS
- **Frontend Lint**: PASS
- **Frontend Production Build**: PASS
- **10 Case Hermetic Evaluation**: PASS (`--hermetic --runs-per-case 1`)，仅证明评测管道与受控离线输入，不证明真实模型能力
- **Credential Scan**: PASS（显式排除本地 `.env`、`.git`、`node_modules` 与构建产物）
- **Real Provider + PostgreSQL Three-case Run**: EXECUTED / FAIL-CLOSED during Canonical / no PASS artifact
- **Real Provider 10 Case Evaluation**: NOT EXECUTED
- **Historical Browser Verification**: 文档保留历史报告，但本轮未重新执行，不作为当前新增验收证据

---

## 5. 当前阻塞与下一步

- **实现状态**：Stage 1 Portfolio MVP 的 Core、Evaluation、API 与 UI 已形成可运行实现；API 已直接使用可信 SDK Tool Trace，三场景脚本可原子输出脱敏验收 artifact。
- **验证状态**：436 项后端测试通过；API 与 Live Validator 专项各 23 项通过。真实 Provider 已被调用，失败运行没有生成 PASS artifact。
- **验收阻塞**：用户已授权发送 Synthetic Benchmark 数据；本地 PostgreSQL 与隔离 Python 环境可用。真实运行先后暴露并修正了单日查询参数表达和可唯一解析的 Evidence ID 表达差异；最新 Canonical Run 仍引用了本次 Tool Output 中不存在的 `observation_id`，被严格解析器拒绝。
- **安全边界**：真实 `.env` 保持本地且不得提交；artifact 不记录 API Key、数据库连接串或完整 Provider URL。
- **恢复开发时的唯一优先级**：在不削弱 Evidence 完整性校验的前提下，提高模型对 Observation/Evidence 引用契约的遵循度，然后重新执行三场景 Live 验收；通过前不启动新 Phase。

---

## 6. 工作区状态说明

- 当前仓库已建立并推送 Stage 1 MVP Git 基线，后续继续遵循 Minimal Diff 原则。
- 旧占位文件 `1` 的删除已由用户确认，无需恢复。
- 新 Agent 必须首先运行 `git status --short --untracked-files=all` 查看工作区。
- 必须对比任务开始与结束时的实际文件状态，严禁修改或覆盖未授权文件。

---

## 7. 最近关键决定

1. **因果与异常边界**：数据异常贡献定位不等于现实业务最终根因。
2. **评测基准隔离**：Ground Truth 严格与 Agent 查询面隔离。
3. **比率聚合口径**：比率指标（Conversion Rate, AOV）必须使用汇总分子除以汇总分母，禁止平均行级比率。
4. **零分母语义**：分母为零时必须为 `unavailable`，严禁转换为 `0`。
5. **深层不可变性**：模型边界使用防御性拷贝与 `MappingProxyType`/`tuple` 封装保证运行时只读。
6. **Tool 组合模式**：`query_related_metrics()` 完全复用受控的 `query_metric()`，不重复拼装 SQL。
7. **缺口贡献优先**：分群下钻定位依据 `conversion_order_shortfall` 和贡献占比（$\ge 50\%$），防止小样本高百分比误判。
8. **纵深防御架构**：只读 DB 账号是数据库层面的硬防御边界；SQL AST Guard 是前置的静态语法分析层；两者结合 `statement_timeout` 构成多层纵深防御。
9. **对象权限 vs 会话默认值**：`default_transaction_read_only` 属于会话级安全默认值，不能替代对象级权限；真正的硬边界是角色在对象上无任何写权限（即使关闭 read-only 仍报 42501）。
10. **凭据安全规范**：真实密码与私有连接串绝不进入代码、脚本、配置或 Git，通过环境变量安全注入。
11. **产品与 Domain 边界**：MetricSleuth 的永久定位是 Evidence-driven 业务指标异常调查 Agent；Amazon / 电商运营是当前唯一 Stage 1 Domain Profile，电商指标与维度不得被解释为永久产品定义。
12. **已知 Stage 1 限定实现**：MetricRegistry 已移除固定电商指标与单位白名单；AnalyticsTools 的 Sessions 样本量语义和 Evaluation 的固定电商维度仍属于 Amazon Profile 限定。当前不阻塞 Stage 1，也不以多 Domain 框架或 Metric DSL 提前重构。
13. **Runtime 冻结**：当前继续使用 OpenAI Agents SDK 作为通用 Agent Loop 基础设施；Runtime 替换只允许通过未来独立 ADR 决策，不与 Domain 校准混合。

---

## 8. 新 Agent 接管检查表

接管本项目的 Agent 在开始任何任务前，请逐项核对：

- [ ] 阅读 `AGENTS.md`（了解稳定规则与接管协议）
- [ ] 阅读 `docs/agent-state.md`（确认当前唯一动态执行快照）
- [ ] 阅读 `任务书.md` 当前 Phase（确认架构设计与产品边界）
- [ ] 检查 `git status`（确认工作区文件基线）
- [ ] 检查当前任务 Allowed Changes（明确本次只允许修改哪些文件）
- [ ] 运行必要基线测试（`unittest discover` 确保基线绿灯）
- [ ] 确认未提前实现下一 Phase（严格遵守当前任务边界）
