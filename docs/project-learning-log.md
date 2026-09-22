# MetricSleuth 项目学习与开发日志

## 0. 文档说明与阅读规范

- **用途**：本项目学习日志用于团队交接、下班后复盘学习及技术面试回顾，系统记录 MetricSleuth 的架构演进、设计决策与真实踩坑经验。
- **事实来源**：本文档完全基于当前代码实现、`任务书.md`、实际测试日志及 Codex 技术负责人的验收结论进行编写，禁止记录臆测或未确认的技术方案。
- **权威性说明**：`任务书.md` 是本项目阶段划分、需求边界和架构演进的唯一权威来源。
- **状态维护规范**：任务执行工程师（Gemini）负责起草和更新日志内容，但**无权**自行将任务标记为 `Accepted`。所有任务必须由 Codex 技术负责人正式验收后方可生效。
- **安全规范**：严禁在本文档中记录真实生产密码、私钥、Token 或敏感业务数据；文中所有数据库连接串与凭据均为本地 Synthetic Benchmark 开发环境示例。

---

## 1. 知识标签体系

文档在各任务与知识点中统一采用以下标签：

- `[必须掌握]`：项目核心主链路所依赖的基础概念与实现机制，日常开发与调试必须精通。
- `[建议掌握]`：有助于提升工程质量、健壮性与可维护性的设计范式与最佳实践。
- `[面试高频]`：技术面试中针对后端架构、数据分析与 Agent 设计常考的核心原理与踩坑题。
- `[项目特有]`：MetricSleuth 专属的业务契约、指标口径与阶段约束。
- `[暂不深入]`：当前 Phase 不涉及或已明确延后至后续阶段的非核心技术。

---

## 2. 项目任务索引表

| Task ID | Phase | 任务名称 | 状态 | 核心产物 |
|---|---|---|---|---|
| `MS-SC-001` | Scaffold | Python 基础脚手架 | Accepted | `pyproject.toml`, `app/__init__.py`, `test_scaffold.py` |
| `MS-P0-001` | Phase 0 | 人工调查契约 | Accepted | `docs/phase-0-manual-investigation.md` |
| `MS-P1-001` | Phase 1 | Data Foundation | Accepted | `schema.sql`, `seed.py`, `anomaly_injector.py`, `ground_truth.json`, `verify_canonical.sql` |
| `MS-P2-001` | Phase 2 | Metric Semantic Layer | Accepted | `configs/metrics.yaml`, `backend/app/metrics/registry.py` |
| `MS-P2-002` | Phase 2 | 配置校验加固与学习文档补全 | Accepted | `registry.py` 增强校验, `test_metric_registry.py`, `project-learning-log.md` |
| `MS-P2-003` | Phase 2 | 学习日志事实与阶段边界纠偏 | Accepted | 学习日志事实与边界纠偏 |
| `MS-P2-004` | Phase 2 | 创建 Agent 接管文档并修正学习日志安全边界 | Accepted | `AGENTS.md`, `project-learning-log.md` |
| `MS-P2-005` | Phase 2 | 建立 Agent State 单一动态状态源 | Accepted | `docs/agent-state.md` |
| `MS-P3-001` | Phase 3 | 最小 Analytics Query 垂直切片 | Accepted | `backend/app/analytics/`, `test_analytics_tools.py`, `verify_phase3_query_metric.py` |
| `MS-P3-002` | Phase 3 | Related Metrics 与完整人工调查闭环 | Accepted | `query_related_metrics()`, `verify_phase3_complete_case.py` |
| `MS-P4-001` | Phase 4 | SQL AST Guard 静态安全基础 | Accepted | `backend/app/sql_safety/`, `test_sql_guard.py` |
| `MS-P4-002` | Phase 4 | PostgreSQL Readonly Role 与权限验证 | Accepted | `warehouse/setup_readonly_role.sql`, `warehouse/verify_readonly_role.py` |
| `MS-P4-003` | Phase 4 | ToolResult → Observation 可追溯转换基础 | Accepted | `backend/app/observations/`, `test_observations.py` |
| `MS-P4-004` | Phase 4 | Observation → Evidence 显式提升契约 | Accepted | `backend/app/evidence/`, `test_evidence.py` |
| `MS-P5-001` | Phase 5 | OpenAI Agents SDK Runtime Capability Spike | Live capability observed during MS-P6-004 attempt | `backend/app/agent_runtime/`, `test_runtime_spike.py`, `verify_phase5_runtime_spike.py` |
| `MS-P5-001-R1` | Phase 5 | Runtime budget/trace fail-closed hardening | Accepted | 固定单次 Tool 预算、SDK 实际异常穿透测试、严格 Trace 与结构化输出交叉校验 |
| `MS-P6-001` | Phase 6 | Runtime Analytics Tool Bridge | Accepted | `investigation_tools.py`, `test_investigation_tools.py` |
| `MS-P6-002` | Phase 6 | Investigation Run Contract 与多调用 Trace 验证 | Accepted | `investigation_runtime.py`, `test_investigation_runtime.py` |
| `MS-P6-003` | Phase 6 | Development Scenario Investigation Harness | Accepted | `verify_phase6_development_scenarios.py`, `test_development_scenarios.py` |
| `MS-P6-004` | Phase 6 | Live Development Set Agent Evaluation | Historical failure superseded | 早期兼容 Provider Canonical 输出不合格；后续显式 Gemini 三场景与受控 Benchmark Live 验收已完成，详见 3.39–3.43 |
| `MS-P7-001` | Phase 7 | Structured Diagnosis Domain Contract | Accepted | `backend/app/diagnosis/`, `test_diagnosis.py` |
| `MS-P7-002` | Phase 7 | Diagnosis Draft Resolution 与 Evidence Citation Verification | Accepted | `diagnosis/draft.py`, `test_diagnosis_draft.py` |
| `MS-P7-003` | Phase 7 | Evidence Selection Draft 与 Observation Citation Resolution | Accepted | `evidence/selection.py`, `test_evidence_selection.py` |
| `MS-P7-004` | Phase 7 | Observation-to-Diagnosis Composition Contract | Accepted | `diagnosis/composition.py`, `test_diagnosis_composition.py` |
| `MS-P7-005` | Phase 7 | SDK Trace Observation Catalog Extraction | Accepted | `observation_from_json`, `extract_observation_catalog`, 专项测试 |
| `MS-P7-006` | Phase 7 | Runtime Structured Diagnosis Intent Contract | Accepted | `diagnosis_intent.py`, strict AgentOutputSchema, 专项测试 |
| `MS-P7-007` | Phase 7 | Hermetic Evidence-driven Diagnosis Runtime Integration | Accepted — Hermetic only | `diagnosis_runtime.py`, `test_diagnosis_runtime.py` |
| `MS-P8-001` | Phase 8 | Evaluation Case Contract 与 Deterministic Core Scoring | Accepted | `app/evaluation/`, `test_evaluation_core.py` |
| `MS-P8-002` | Phase 8 | Core Evaluation Aggregate Report | Accepted | `evaluation/aggregate.py`, `test_evaluation_aggregate.py` |
| `MS-P8-003` | Phase 8 | Evidence Obligation Contract | Accepted | `evidence_obligations.py`, 专项测试 |
| `MS-P8-004` | Phase 8 | Evidence Citation Precision 与 Coverage Scoring | Accepted | `evidence_scorer.py`, `test_evidence_scoring.py` |
| `MS-P8-005` | Phase 8 | Unsupported Claim Contract 与 Scoring | Accepted | `unsupported_claims.py`, `test_unsupported_claims.py` |
| `MS-P8-006` | Phase 8 | Evaluation Run Outcome 与 Tool Operational Scoring | Accepted | `operational.py`, `test_evaluation_operational.py` |
| `MS-P8-007` | Phase 8 | Tool Operational Aggregate Report | Accepted | `operational_aggregate.py`, `test_evaluation_operational_aggregate.py` |
| `MS-P8-008` | Phase 8 | Unified Evaluation Aggregate Report | Accepted | `unified.py`, `test_evaluation_unified.py` |
| `MS-P8-009` | Phase 8 | Hermetic Evaluation Runner Contract | Accepted | `runner.py`, `test_evaluation_runner.py` |
| `MS-P8-010` | Phase 8 | Evaluation Manifest 与 Reproducibility Contract | Accepted | `manifest.py`, `test_evaluation_manifest.py` |
| `EVID-001` | MVP Hardening | Driver-at-Scope Evidence Integrity | Verified | 同一条异常支撑证据同时覆盖 driver 与完整 scope |
| `ENV-001` | MVP Hardening | Environment Reproducibility | Verified | `.env` 加载、依赖与隔离测试 |
| `LIVE-003` | MVP Hardening | Live Acceptance Contract Hardening | Verified hermetically | 三场景、Citation、Budget 与场景注入 fail-closed |
| `RUNTIME-SEM-001` | MVP Hardening | Runtime Semantic Discovery Tool | Verified hermetically | `get_metric_definition` 加入受控生产工具面 |
| `SEM-CORE-001` | MVP Hardening | Metric Registry Core/Profile Boundary | Verified | Registry 不再固定五个电商指标或单位白名单 |
| `TRACE-CORE-001` | MVP Hardening | SDK-native Investigation Trace | Verified hermetically | 只读、确定性 SDK Tool Trace 与 Run Summary 不变量 |
| `PRODUCT-TRUTH-001` | MVP Hardening | Product Truthfulness | Verified | Ground Truth 不出现在场景 API；Fixture 与 Live 明确分离 |
| `CONFIG-SEC-001` | MVP Hardening | Provider Configuration Hygiene | Verified | 示例凭据脱敏、官方默认端点、暴露凭据轮换规则 |
| `TRACE-API-001` | MVP Hardening | API Trusted Runtime Trace | Verified | API 直接消费 SDK Tool Trace，拒绝业务 wrapper 侧录伪装模型动作 |
| `LIVE-ARTIFACT-001` | MVP Hardening | Reproducible Live Acceptance Artifact | Verified hermetically | 原子脱敏 artifact、Traffic 完整 scope、可信动态分支断言 |
| `LIVE-CONTRACT-001` | MVP Hardening | Single-day Query Contract | Verified hermetically | Prompt 与 Tool 文档明确 Current Period 为同一自然日，Baseline 由比较策略生成 |
| `LIVE-REF-001` | MVP Hardening | Evidence Reference Normalization | Verified hermetically | 仅归一化可唯一映射的 Observation ID；未知或歧义引用继续拒绝 |
| `LIVE-DIAG-002` | MVP Hardening | Explicit Driver Evidence Contract | Verified hermetically | driver_evidence_id、Tool Output 协议与失败审计；未放宽联合支撑校验 |

---

## 3. 历史任务开发记录与技术复盘

### 3.1 MS-SC-001: 基础脚手架 (Repository Scaffold)

- **任务目标**：建立符合 Python 3.12+ 规范的最小工程骨架与标准库测试体系。
- **为什么要做**：避免在未建立基线的情况下引入复杂框架，确保后续所有代码均在严格的包管理与测试发现机制下运行。
- **核心产物与职责**：
  - `backend/pyproject.toml`：声明包元数据、Python 版本（`>=3.12`）与初始依赖。
  - `backend/app/__init__.py`：声明根包版本 `__version__ = "0.1.0"`。
  - `backend/tests/test_scaffold.py`：标准库 `unittest` 脚手架导入与版本测试。
- **关键设计** `[建议掌握]`：零第三方框架起步，使用 Python 标准库 `unittest` 与 `tomllib` 完成验证。
- **当前边界**：仅作为空骨架，不包含任何业务模块或网络服务。

---

### 3.2 MS-P0-001: 人工调查契约 (Manual Investigation Contract)

- **任务目标**：冻结业务分析师从全局 Sales 异常逐步下钻到主要异常贡献分群的人工排查数学规则与判定契约。
- **为什么要做**：在编写数据生成与 Agent 代码前，必须先有明确、可证伪的人工排查准则，否则后续 Agent 的评估与诊断将失去对照基准。
- **核心边界澄清** `[必须掌握]` `[项目特有]`：
  - **异常贡献定位 $\neq$ 最终业务根因**：Phase 0 仅定位数据层面的异常贡献范围（Data-level anomaly contribution scope），排查定位到 `US / ASIN-A / Ads` 的 Conversion Rate 异常，并不等于证明广告投放设置、Listing 页面改动、竞品降价或外部运营操作是最终业务根因（External business root cause）。
- **核心产物**：
  - `docs/phase-0-manual-investigation.md`：规范了 Current 与 Baseline 定义、四则指标聚合公式、缺口贡献（Shortfall Contribution）算法及负向对照要求。
- **关键设计与停止状态** `[必须掌握]` `[面试高频]`：
  1. **转化订单缺口公式**：
     $$\text{Shortfall} = \text{Sessions}_{\text{curr}} \times \text{CR}_{\text{base}} - \text{Orders}_{\text{curr}}$$
     按绝对订单损失量（而非单纯百分比）排序，避免小样本高比例波动的“小样本陷阱”。
  2. **下钻停止状态严格区分**：
     - **`insufficient_data`**：当基准期日均 Sessions $< 30$ 时触发，原因是样本规模不足，避免在小样本上做过度推断；
     - **`insufficient_evidence`**：当同层最大 Segment 缺口贡献率 $< 50\%$ 时触发，原因是异常贡献过于分散，无法定位单一主要范围。
- **需要掌握的知识**：指标树拆解（Sales → Orders/AOV → Sessions/CR）、下钻贡献度计算、停止条件状态区分。

---

### 3.3 MS-P1-001: Data Foundation (合成基准数据集与 SQL 验收)

- **任务目标**：构建可复现、可验证的 PostgreSQL Synthetic Benchmark 数据集，使分析师仅通过 SQL 即可完全复现 Canonical Case。
- **核心产物**：
  - `warehouse/schema.sql`：定义商品维表与每日表现事实表。
  - `warehouse/seed.py`：生成 2026-01-01 至 2026-01-31（558 行）确定性基准数据。
  - `warehouse/anomaly_injector.py`：注入 `canonical`、`traffic` 与 `no_anomaly` 三种场景。
  - `warehouse/ground_truth.json`：评测基准期望标签（严禁对 Agent 暴露）。
  - `warehouse/verify_canonical.sql`：原生 PL/pgSQL 自动化验收脚本。

#### 关键技术复盘与踩坑记录（真实问题已全部修复）

1. **为什么 `0.0.0.0/0 trust` 极其危险？** `[必须掌握]` `[面试高频]`
   - *问题*：配置 `listen_addresses='*'` 并开启 `0.0.0.0/0 trust` 意味着数据库监听在所有公网/局域网网卡上，任何网络可达的主机无需密码即可获得连接。
   - *修复*：将 `listen_addresses` 严格限制为 `'localhost'`（`127.0.0.1:5432`），并在 `pg_hba.conf` 仅保留 `scram-sha-256` 密码认证。
2. **为什么业务数据库账号绝不能是 `SUPERUSER`？** `[必须掌握]` `[面试高频]`
   - *问题*：PostgreSQL 的超级用户可绕过所有权限检查、调用 `COPY ... PROGRAM` 执行宿主机系统命令或修改系统级元数据。
   - *修复*：将 `metricsleuth` 用户权限降级为 `NOSUPERUSER NOCREATEDB NOCREATEROLE`，仅授予目标 schema/table 读写权限。
3. **为什么 PL/pgSQL 中的 `IF NULL THEN` 会导致伪 PASS？** `[必须掌握]` `[面试高频]`
   - *问题*：在 SQL 三值逻辑（True / False / NULL）中，`IF <condition> THEN` 只有在条件严格为 `TRUE` 时才进入分支。如果指标计算出 `NULL`，表达式 `NULL <= -0.10` 的结果是 `NULL`，不会进入异常抛出分支，导致空表或缺失数据时测试静默 PASS。
   - *修复*：增加前置记录数严格校验，对所有变量施加 `IS NULL` 显式校验，并使用 `IF NOT (rel_change <= -0.10) THEN RAISE EXCEPTION` 严密防护。
4. **为什么异常注入器必须校验更新行数（Rowcount）？** `[建议掌握]`
   - *问题*：SQL `UPDATE` 即使没有匹配到任何行（如目标日期不存在），也不会报错，导致注入器静默“成功”但数据库未被修改。
   - *修复*：在事务内检查 `cur.rowcount == 1`，并在注入结束时断言总更新行数恰好为 18。
5. **为什么转化率（Conversion Rate）绝不能直接平均行级或每日比率？** `[必须掌握]` `[面试高频]`
   - *问题*：直接计算平均比率会引发“辛普森悖论”，忽略流量体量的权重差异（例如 10 访问 1 购买与 1000 访问 10 购买的平均转化率不应是 $(10\% + 1\%) / 2 = 5.5\%$，而应是 $11 / 1010 \approx 1.09\%$）。
   - *修复*：必须使用汇总分子除以汇总分母：$\text{CR} = \sum \text{Orders} / \sum \text{Sessions}$。

---

### 3.4 MS-P2-001 & MS-P2-002: Metric Semantic Layer (指标语义层)

- **任务目标**：构建轻量、确定性、无 LLM/数据库依赖的 Metric Semantic Layer，成为指标真理源（Single Source of Truth）。
- **核心产物**：
  - `configs/metrics.yaml`：5 个核心指标（`sales`, `orders`, `sessions`, `conversion_rate`, `aov`）的声明式元数据配置。
  - `backend/app/metrics/registry.py`：不可变指标模型 `MetricDefinition` 与注册表 `MetricRegistry`。
  - `backend/app/metrics/__init__.py`：导出 `MetricDefinition`, `MetricRegistry`, `MetricConfigError`, `MetricNotFoundError`。
  - `backend/tests/test_metric_registry.py`：完备的正反向单元测试套件。

#### 核心架构与加载流程 `[必须掌握]`

```text
configs/metrics.yaml
  → yaml.safe_load() (安全反序列化)
  → 结构与业务契约校验 (Fail-Fast 校验结构、字段、类型、自依赖与非法元素)
  → MetricDefinition (转换为不可变 frozen dataclass 与只读 tuple)
  → MetricRegistry (内存索引)
  → get() / get_dependencies() / get_related_metrics()
```

#### 配置驱动设计的优缺点 `[必须掌握]` `[面试高频]`

- **优点 (Pros)**：
  1. **Single Source of Truth**：指标定义、计算公式与支持维度集中管理，形成单一真理源；
  2. **解耦业务与执行**：公式不再散落并硬编码在各工具或 SQL 代码中，配置变更无需重构执行逻辑；
  3. **可维护性与可测试性**：声明式配置便于跨团队审查、版本管理和自动化 schema 验证。
- **缺点与代价 (Cons & Costs)**：
  1. **弱类型与延迟报错**：YAML 本身缺乏强静态类型检查，拼写错误、非法引用和类型嵌套必须在加载时通过自定义校验发现；
  2. **表达力失控风险**：过度追求配置灵活性容易导致自制出难以维护的“方言 DSL”或表达式解析器；
  3. **版本协同成本**：配置格式变更需要配套的迁移工具和严格的向后兼容测试。
- **MetricSleuth 的控制策略**：
  - 通过 `MetricRegistry` 内建严格的 fail-fast 校验守卫弥补 YAML 弱类型缺陷；
  - 坚持简单声明原则，仅支持固定 5 个核心指标，绝不实现通用表达式解释器、插件系统或复杂 DSL。

#### 关键概念与边界划分

1. **`metrics.yaml` 的职责**：声明指标类型（`additive`/`ratio`）、单位（`usd`/`count`/`ratio`）、聚合公式、计算依赖（`dependencies`）与排查关联指标（`related_metrics`）。
2. **`MetricRegistry` 的职责**：只读容器与查询入口，提供安全、确定的指标元数据查询，对外封装内部数据结构。
3. **`MetricDefinition` 的职责**：单个指标的元数据载体，使用 `@dataclass(frozen=True)` 且所有序列属性转换为 `tuple`，保证不可被外部调用方篡改。
4. **`dependencies` 与 `related_metrics` 的区别** `[必须掌握]` `[面试高频]`：
   - `dependencies`（计算依赖）：直接用于计算派生指标所需的原子指标（例如 `conversion_rate` 依赖 `orders` 和 `sessions`；`sales` 依赖为空 `[]`）。
   - `related_metrics`（调查关联指标）：在业务异常排查时，建议分析师或 Agent 联动查看的相关指标（例如 `sales` 的关联指标为 `orders`, `sessions`, `conversion_rate`, `aov`）。
5. **Fail-Fast 原则与领域异常 (`MetricConfigError` / `MetricNotFoundError`)** `[建议掌握]` `[面试高频]`：
   - 配置有误时立即在加载时抛出 `MetricConfigError` 终止，严禁泄漏原生 `TypeError`（如 `[[]]` 导致的 unhashable list）或 `KeyError`。
   - 查询不存在的指标时抛出明确的 `MetricNotFoundError`，不返回 `None` 或静默降级。
6. **PyYAML Loader 安全模型与当前实现边界** `[建议掌握]` `[面试高频]`：
   - `yaml.safe_load()` 仅构造标准 YAML 基础数据类型（字典、列表、标量）；
   - 使用 `UnsafeLoader` 等不安全 Loader 解析不可信 YAML 会反序列化任意 Python 对象并导致代码执行；现代 PyYAML 的 `yaml.load()` 已要求显式指定 Loader；
   - 当前实现使用 `yaml.safe_load()` 降低任意 Python 对象构造风险，并由 `MetricRegistry` 执行结构和业务契约校验。当前没有实现解析阶段的文件大小、嵌套深度或资源预算限制，因此该加载入口只用于仓库内受信任且经过代码审查的配置，不应直接暴露为任意不可信 YAML 上传接口。

---

### 3.5 MS-P2-003 ~ MS-P2-005: 学习日志纠偏、Agent 接管与状态源建立

- **MS-P2-003**：纠正业务根因与异常贡献边界、明确 `insufficient_data` 与 `insufficient_evidence` 停机状态语义。
- **MS-P2-004**：创建 `AGENTS.md`，纠正高估 YAML 解析安全能力的描述，如实界定受信任仓库配置边界。
- **MS-P2-005**：创建 `docs/agent-state.md`，实现稳定规则（`AGENTS.md`）与高频动态状态（`agent-state.md`）的彻底动静分离，消除状态漂移。
- **当前状态**：`Accepted`。

---

### 3.6 MS-P3-001: 最小 Analytics Query 垂直切片与深层不可变返工

- **任务目标**：实现由 `MetricRegistry` 驱动、受控参数化、计算结果深层不可变的最小指标查询工具 `query_metric()`。
- **核心产物**：
  - `backend/app/analytics/models.py`：定义不可变 `DateRange`、`MetricQueryRow`、`MetricQueryResult` 与 `MetricQueryError` 领域异常；
  - `backend/app/analytics/tools.py`：实现 `AnalyticsTools`，提供 `get_metric_definition()` 与 `query_metric()`；
  - `backend/app/analytics/__init__.py`：导出公开工具与数据结构；
  - `backend/tests/test_analytics_tools.py`：15 项 hermetic 单元测试；
  - `backend/scripts/verify_phase3_query_metric.py`：PostgreSQL Warehouse 端到端验证脚本。

#### 踩坑与技术复盘：`frozen dataclass` 与深层不可变的区别 `[必须掌握]` `[面试高频]`

- **问题现象**：虽然 `MetricQueryRow` 声明了 `@dataclass(frozen=True)`，但属性 `dimensions` 传入并持有了普通可变 `dict`，导致调用方执行 `row.dimensions["marketplace"] = "DE"` 成功原地篡改了查询结果，破坏了不可变契约。
- **核心原理**：`frozen=True` 仅重载了属性赋值行为（阻止 `row.dimensions = ...`），无法防御属性所引用可变对象内部的深层篡改操作（如字典的 `__setitem__`）。
- **彻底修复方案**：在 `MetricQueryRow.__post_init__` 中执行防御性浅拷贝并使用 Python 标准库 `types.MappingProxyType` 封装为只读映射视图：
  ```python
  def __post_init__(self) -> None:
      object.__setattr__(
          self,
          "dimensions",
          MappingProxyType(dict(self.dimensions)),
      )
  ```
  既切断了外部传入源字典的引用，又使任何原地修改抛出 `TypeError`，同时 100% 保持下标读取与字典等值比对接口不变。

---

### 3.7 MS-P3-002: Related Metrics 与完整人工调查闭环

- **任务目标**：实现 `query_related_metrics()`，并通过人工调用工具链在真实数据库中完整复现 Canonical Case 全链路定位。
- **核心产物**：
  - `backend/app/analytics/models.py`：新增 `RelatedMetricQueryResult`（不可变 `results: tuple[MetricQueryResult, ...]`）；
  - `backend/app/analytics/tools.py`：实现 `query_related_metrics()`，按 `MetricRegistry` 声明顺序循环调用受控 `query_metric()`；
  - `backend/scripts/verify_phase3_complete_case.py`：完整 Canonical Case 人工调查验收脚本。

#### 核心技术复盘与方法论 `[必须掌握]`

1. **Tool Composition（工具组合设计）** `[建议掌握]` `[面试高频]`：
   - `query_related_metrics()` 直接组合复用原子工具 `query_metric()`，不重复编写底层 SQL，所有参数（时间、filters、group_by）统一转发，子查询异常直接向上传播，保证了查询行为与安全边界的绝对一致。
2. **为什么下钻排查必须依据“转化订单缺口贡献（Shortfall Contribution）”而不是“相对变化率”？** `[必须掌握]` `[面试高频]`
   - **小样本高波动陷阱**：某小流量分群（例如 2 访问 1 购买 $\rightarrow$ 2 访问 0 购买）转化率下跌 100%，但实际仅损失 1 个订单；而核心主力分群（例如 1000 访问 100 购买 $\rightarrow$ 1000 访问 50 购买）转化率下跌 50%，实际损失 50 个订单；
   - **绝对缺口量衡量真实业务损失**：
     $$\text{Expected Orders} = \text{Sessions}_{\text{curr}} \times \text{CR}_{\text{base}}$$
     $$\text{Shortfall} = \text{Expected Orders} - \text{Orders}_{\text{curr}}$$
     $$\text{Positive Shortfall} = \max(\text{Shortfall}, 0)$$
     $$\text{Contribution Share} = \frac{\text{Positive Shortfall}}{\sum \text{Positive Shortfall}}$$
   - 只有依据缺口贡献占比（$\ge 50\%$）结合样本量（$\ge 30$）和转化率实质下跌（$\le -10\%$），才能准确锁定主要受损分群，避免被小样本边缘波动带偏。
3. **负向对照与贡献集中度** `[必须掌握]` `[项目特有]`：
   - 在每一层下钻中，不仅要验证主要分群的缺口贡献 $\ge 50\%$，还必须严格验证同层其余分群的转化率波动 $< 5\%$（稳定负向对照），排除全局性普遍衰退，确保异常聚焦在单一主要路径。
4. **数据异常贡献定位 $\neq$ 最终业务根因** `[必须掌握]` `[项目特有]`：
   - 调查最终定位到 `US / ASIN-A / Ads` 的转化率异常，证明的是该分群贡献了 100% 的订单缺口；但这属于**数据层面的异常贡献范围定位**，并不等同于证明广告出价设置、Listing 页面改动、评论差评或竞品降价是**外部物理业务根因**。

---

### 3.8 MS-P4-001: SQL AST Guard 静态安全基础

- **任务目标**：基于 `sqlglot` 构建确定性的 PostgreSQL 纯静态 SQL AST Guard 安全分析器，实现单语句校验、顶层 SELECT 约束、危险语法拒绝、表与安全函数白名单及强制 LIMIT 注入。
- **为什么要做**：建立纵深防御的前置静态防火墙，防止未来任意 SQL 查询入口依赖脆弱的正则表达式或字符串匹配导致 SQL 注入与资源耗尽。
- **核心产物**：
  - `backend/app/sql_safety/guard.py`：定义 `SqlGuard`、`SqlGuardError`、`ValidatedSql` 及安全函数/语法节点白名单；
  - `backend/app/sql_safety/__init__.py`：导出公开安全模型与验证器；
  - `backend/tests/test_sql_guard.py`：34 项针对 AST 安全特性的正反向单元测试。

#### 核心技术深度复盘 `[必须掌握]`

1. **为什么正则表达式不能可靠解析与防御 SQL？** `[必须掌握]` `[面试高频]`
   - **文法性质限制**：SQL 属于上下文无关文法（CFG），具备递归嵌套括号、字符串转义、注释（`--`、`/* */`）、大小写与别名混用等特性；
   - **正则的脆弱性**：正则无法维护递归状态机。例如 `(?i)SELECT.*FROM` 容易被多层括号 `SELECT (SELECT ...) FROM ...`、内联注释 `SELECT/*comment*/1` 或字符串 `'--'` 伪装绕过，产生大量假阳性（误拦截合法查询）或假阴性（漏放危险注入）。
2. **AST Guard 与 Readonly DB User 的职责区别与纵深防御** `[必须掌握]` `[面试高频]`
   - **只读 DB 账号 (Database Level Hard Boundary)**：主要安全防线。由数据库内核强制保证无法执行任何 `INSERT`/`UPDATE`/`DELETE`/`DROP` 等数据写入或修改；
   - **AST Guard (Application Level Static Boundary)**：前置纵深防御层。在 SQL 发往数据库前，静态拦截非预期表引用（如系统表 `pg_catalog.pg_user`、应用表 `app.evidence`）、阻断 `pg_sleep` 等慢查询 DoS 函数、强制注入 `LIMIT` 防止大内存 OOM；
   - **纵深防御 (Defense-in-Depth)**：只读账号无法防御合法表的大数据全表扫描或 DoS 慢函数；AST Guard 无法防御绕过应用直连数据库的攻击。两者互为补充，不可相互替代。
3. **为什么 Allowlist（白名单）显著优于 Denylist（黑名单）？** `[必须掌握]` `[面试高频]`
   - 黑名单模式（仅拦截已知的危险函数或表）容易因为未覆盖的新型方言函数、系统内部函数或编码变形而被轻易绕过；
   - 白名单模式采取“默认拒绝（Default Deny）”，仅允许明确审计过的安全分析函数（`SUM`, `COUNT`, `AVG`, `MIN`, `MAX`, `NULLIF`, `COALESCE`, `ABS`）和特定的 Warehouse 事实表/维表。
4. **为什么 `SELECT` 并不天然安全？** `[必须掌握]` `[面试高频]`
   - `SELECT * INTO table`：会在数据库中新建表（DDL/DML 副作用）；
   - `SELECT ... FOR UPDATE / FOR SHARE`：会在行上施加排他锁/共享锁，引发锁竞争甚至死锁；
   - `SELECT pg_sleep(10)` / `SELECT repeat('a', 1000000000)`：会导致 CPU 耗尽、连接池占满和内存溢出 DoS；
   - `SELECT * FROM pg_catalog.pg_user`：会泄露系统权限与数据库元数据；
   - 无 `LIMIT` 的 `SELECT *`：会因返回海量结果集导致应用层与网络 OOM。
5. **LIMIT 静态约束的作用与局限，为什么 Guard 不能替代 Statement Timeout？** `[必须掌握]` `[面试高频]`
   - **作用**：`LIMIT` 静态约束保证了最终返回给应用层的结果集行数受控（不超过 `max_rows`）；
   - **局限**：`LIMIT` 仅作用于**最终结果集的截断**。如果 SQL 内部包含复杂的全表笛卡尔积、未命中索引的大表扫描或重度 Hash Join，数据库在输出第一行前可能就已经消耗了数分钟的 CPU 和数十 GB 临时磁盘；
   - **结论**：必须在数据库执行层配合 `statement_timeout` 机制，两者分别在“行数预算”和“时耗预算”上进行双重兜底。

---

### 3.9 MS-P4-002: PostgreSQL Readonly Role 与权限验证

- **任务目标**：建立并验证独立的 PostgreSQL 只读登录角色 `metricsleuth_readonly`，实施最小表级授权与安全会话默认值，并通过端到端独立脚本严密验证。
- **为什么要做**：AST Guard 仅能在应用层做语法级预检，必须由数据库内核提供真正的物理权限隔离硬边界；同时必须建立独立的只读身份，杜绝业务分析/Agent 复用具备 DDL/DML 权限的开发管理员账号。
- **核心产物**：
  - `warehouse/setup_readonly_role.sql`：幂等创建/更新 `metricsleuth_readonly` 角色、收敛权限并设置数据库作用域默认参数；
  - `warehouse/verify_readonly_role.py`：独立权限与超时端到端验证测试套件。

#### 核心技术深度复盘 `[必须掌握]`

1. **为什么 Read-only Transaction 不能作为唯一的安全边界？** `[必须掌握]` `[面试高频]`
   - **原理机制**：`transaction_read_only` 和 `default_transaction_read_only` 属于 PostgreSQL 会话级（GUC）运行参数。任何普通客户端连接后，都可以随时通过 `SET default_transaction_read_only = off` 或 `BEGIN READ WRITE` 将只读事务模式重置为读写模式；
   - **安全隐患**：如果角色本身在底层物理表上拥有 `UPDATE`/`DELETE` 权限，攻击者或错误代码只需一行 `SET` 命令就能绕过只读事务限制，直接修改物理数据；
   - **结论**：**真正的权限主防线是数据库对象权限（Object Privileges）**，即角色必须在物理表上完全没有写权限。
2. **为什么要分别验证 SQLSTATE 25006 与 42501？** `[必须掌握]` `[面试高频]`
   - **SQLSTATE 25006 (`read_only_sql_transaction`)**：验证登录会话的**安全默认值**是否正常生效。在默认只读事务模式下尝试写入，由事务管理器直接阻断；
   - **SQLSTATE 42501 (`insufficient_privilege`)**：验证底层的**对象级权限硬边界**。当测试脚本显式执行 `SET default_transaction_read_only = off` 突破默认模式后，尝试写入依然被 PostgreSQL 权限子系统抛出 42501 强力拦截；
   - **双重断言意义**：分别验证这两个错误码，证明了“会话安全默认层”与“底层对象权限层”均真实生效且互为兜底，消除了单点配置失效风险。
3. **AST Guard、Readonly Role 与 Statement Timeout 的纵深防御（Defense-in-Depth）** `[必须掌握]` `[面试高频]`
   - **AST Guard（应用层前置静态防火墙）**：在网络 I/O 发生前，静态拦截非分析函数、未知表、多语句、`FOR UPDATE` 锁及自动注入 `LIMIT`；
   - **Readonly Role（数据库层硬边界）**：即使 SQL 绕过 Guard 或直连数据库，内核权限控制确保绝无可能发生物理写入或 DDL 修改；
   - **Statement Timeout（执行时耗预算兜底）**：即便合法只读 SQL 触发了耗时的大表 Cartesian Join 或 Hash Join，数据库在 1 秒超时到达时自动终止执行（SQLSTATE 57014），防止拖垮数据库连接池。
4. **`ALTER ROLE ... IN DATABASE ... SET ...` 为什么只是新会话默认值？** `[建议掌握]` `[面试高频]`
   - 该命令设置的参数存储在 `pg_db_role_setting` 中，仅在**客户端发起新连接并通过身份认证后**作为默认值加载；
   - 它无法改变已经建立的现有连接；且普通会话仍可尝试在运行时修改非受限参数；
   - **工程准则**：后续编写 SQL Executor 时，必须在每次连接建立或开启事务时显式声明 `READ ONLY` 和 `statement_timeout`，不能完全依赖角色默认值。
5. **为什么权限采用两张表的显式单表 GRANT？** `[建议掌握]`
   - 遵循最小特权原则（PoLP）。当前业务仅需要 `warehouse.dim_products` 和 `warehouse.fact_daily_performance`；
   - 坚决不使用 `GRANT SELECT ON ALL TABLES` 或设置 future-table default privileges，防止未来在 schema 中创建临时表或敏感数据时被只读角色自动访问导致权限扩散。
6. **为什么真实密码绝不能进入代码或 Git？** `[必须掌握]`
   - 生产与开发凭据进入代码仓库是严重的合规与安全漏洞。本方案在 SQL 脚本中使用 `\getenv`，在 Python 验证脚本中使用 `os.environ` 动态读取环境变量，保证仓库与版本历史零密码泄漏。

---

### 3.10 MS-P4-002-R1: Readonly Role Fail-Closed 与权限漂移检测

- **返工背景**：MS-P4-002 第一次实现通过了行为探针（读取成功、写入被拒、超时取消），但存在两个安全验收缺口：① 密码入口仅检查变量定义性（existence），未检查非空性（non-emptiness），空字符串密码可穿透并清除角色密码；② 验证脚本只确认"读取成功"，没有断言实际授权集合精确匹配允许列表，无法检测权限漂移。

#### 核心概念复盘 `[必须掌握]`

1. **psql 变量"已定义"与"非空"的区别** `[必须掌握]` `[面试高频]`
   - `\getenv readonly_pwd METRICSLEUTH_READONLY_PASSWORD` 在环境变量存在（包括值为空字符串）时定义 psql 变量 `readonly_pwd`；
   - `\if :{?readonly_pwd}` 仅判断变量**是否已被定义**（Defined / Not-defined），返回布尔值；空字符串 `""` 属于"已定义"，因此该检查对空字符串返回 `TRUE`；
   - 正确的非空检查需要进一步执行 SQL 层面的字符串长度校验：
     ```sql
     SELECT length(btrim(:'readonly_pwd')) > 0 AS readonly_pwd_valid \gset
     \if :readonly_pwd_valid
     \else
         \warn 'ERROR: password must be non-empty'
         SELECT 1/0;  -- 触发 ON_ERROR_STOP 非零退出
     \endif
     ```
   - `btrim()` 同时修剪首尾空白，保证纯空格字符串（如 `"   "`）也被正确拒绝。

2. **为什么 `\set ON_ERROR_STOP on` 应由脚本自身声明** `[必须掌握]`
   - 如果仅依赖调用方在命令行传递 `-v ON_ERROR_STOP=1`，则调用方传入裸 `psql -f` 时脚本将在遇到 SQL 错误后继续执行后续语句，例如空密码校验失败后仍可能执行 `ALTER ROLE ... PASSWORD ''`；
   - 在脚本文件开头声明 `\set ON_ERROR_STOP on`，确保无论调用方如何调用，脚本自身遇到任何 SQL 错误即立即非零终止（Fail Closed），校验代码的保护效果不依赖调用约定。

3. **为什么正向读取成功不能证明权限最小** `[必须掌握]` `[面试高频]`
   - "两张表 SELECT 成功"只证明角色**至少有**读取权限，不能证明**仅有**这两张表的 SELECT 权限；
   - 如果数据库在角色上额外积累了 `warehouse.other_table: SELECT`、`public.users: SELECT` 或 `warehouse.dim_products: INSERT`，行为探针不会感知，权限漂移（Privilege Drift）被静默漏过；
   - **最小权限原则（PoLP）**的验证必须通过查询权限系统元数据（Allowlist 精确断言）实现，而不能仅依赖"预期操作是否成功"的行为探针。

4. **精确授权集合断言与行为探针各自解决什么问题** `[必须掌握]` `[面试高频]`
   - **行为探针**：验证"预期操作可执行"与"非法操作被拒绝"（如写入抛 25006/42501），发现配置**功能性失效**；
   - **精确授权集合断言**：查询 `information_schema.role_table_grants`，严格断言实际直接表授权集合与期望集合完全等价（`==`），发现**权限漂移**（多余授权静默积累）；
   - 两者职责互补，缺一不可：探针覆盖功能正确性，断言覆盖边界精确性。

5. **为什么需要临时注入额外权限的反向测试** `[必须掌握]`
   - 正向验证脚本是否能正常 PASS 只证明"正常状态下不误报"；
   - 临时通过 `GRANT UPDATE ON warehouse.dim_products TO metricsleuth_readonly` 注入多余权限后，再次运行验证脚本，必须观察到精确断言**失败**，否则断言本身失效（假阴性漏报）；
   - 验证完后执行配置脚本（`REVOKE ALL` 后重新 `GRANT` 最小权限），确认验证器在恢复后正常 PASS（自我修复能力）。

6. **`pg_hba.conf` 为什么属于环境边界** `[建议掌握]`
   - `pg_hba.conf` 是 PostgreSQL 服务进程的客户端身份认证策略文件，属于宿主操作系统/PostgreSQL 安装层面的配置，由数据库管理员（DBA）负责维护；
   - 应用脚本追加 `pg_hba.conf` 规则会越出仓库的责任边界，跨越"应用配置 vs 系统配置"的边界，也会与"不修改系统/WSL/PostgreSQL 安全配置"的约定冲突；
   - 正确做法：在 README 和文档中明确声明所需的认证前置条件（`metricsleuth_readonly` 须能以 `scram-sha-256` 连接目标库），由环境管理员独立满足，仓库脚本对此保持只读态度。

7. **凭据进入执行日志也属于泄露** `[必须掌握]` `[面试高频]`
   - Git 仓库的代码与历史记录是最广为人知的泄漏渠道，但并非唯一渠道；
   - 当密码以明文出现在 shell 命令参数（`export VAR=mysecret; psql ...`）、任务执行日志、CI/CD 输出或与他人共享的终端录屏中时，凭据已泄露，即使未进入 Git；
   - MetricSleuth 在此次实施中，旧测试密码 `<redacted-old-test-password>` 出现在命令执行记录中，已被视为失效凭据，必须在同一内存会话中使用随机生成的临时值替换并在完成后立即清除。

8. **已暴露凭据为什么必须轮换** `[必须掌握]`
   - 即使泄漏渠道是本地日志而非公开网络，"已暴露"等同于"可能被知晓"；
   - 遵循最小假设原则：旧密码必须视为失效，立即通过内存中随机生成的新值（如 `openssl rand -hex 24`）覆盖，完成配置脚本幂等执行与完整验证后方可确认轮换完成；
   - 轮换过程中新密码绝不出现在命令文本、文件或报告中，仅存在于子进程的内存环境变量中。

#### R1 验收确认事实 `[项目特有]`

- **Fail-Closed 探针**：未设置、空字符串、纯空格密码全部非零退出（PASS）；探针执行前后角色密码哈希与授权集合不变（PASS）。
- **幂等配置**：连续两次执行 `setup_readonly_role.sql` 均成功，角色状态一致（PASS）。
- **精确授权集合**：`information_schema.role_table_grants` 返回集合精确等于 `{("warehouse", "dim_products", "SELECT"), ("warehouse", "fact_daily_performance", "SELECT")}`，无多余项（PASS）。
- **Schema 权限**：`USAGE` = `true`，`CREATE` = `false`（PASS）。
- **非 SELECT 权限**：两张表的 `INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER` 全部 `false`（PASS）。
- **Non-ownership**：数据库/schema/warehouse 表 owner 计数全为 `0`（PASS）。
- **权限漂移反向探针**：临时注入 `UPDATE` 权限后验证器断言失败；撤销后恢复成功（PASS）。
- **SQLSTATE 25006 / 42501 / 57014**：全部验证通过（PASS）。
- **数据完整性**：验证前后 `dim_products` 3 行、`fact_daily_performance` 558 行不变（PASS）。
- **密码轮换**：旧测试密码已在内存中以随机值覆盖，新密码未出现在任何文件或报告中（完成）。

#### 自测与面试问题

- **Q14**：`\if :{?readonly_pwd}` 在 `METRICSLEUTH_READONLY_PASSWORD=""` 时会返回 `TRUE` 还是 `FALSE`？正确的非空校验应如何实现？`[面试高频]`
- **Q15**：如果验证脚本只验证"读取成功"和"写入被拒"，能否检测到角色被额外 `GRANT SELECT ON warehouse.other_table` 的权限漂移？为什么？`[面试高频]`

---

### 3.11 MS-P4-003: ToolResult → Observation 可追溯转换基础

- **任务目标**：定义最小、不可变、可追溯的 `Observation` 领域模型与标准状态契约 `ObservationStatus`，将 `MetricQueryResult` 与 `RelatedMetricQueryResult` 确定性转换为规范化观察。
- **为什么要做**：Tool 返回值仅是原始数据行，没有统一的调查观察契约；无法在后续 Runtime 中表达状态（正常/异常/边界/证据不足/失败）、追踪调用源头、引用具体分群行、或保留稳定结果作为负向证据。
- **核心产物**：
  - `backend/app/observations/models.py`：定义不可变 `Observation`、`ObservationStatus` 状态枚举及领域异常；
  - `backend/app/observations/mapper.py`：实现确定性分类器 `classify_metric_row_status`、单指标转换 `observations_from_metric_query`、关联指标展平 `observations_from_related_metric_query`、统一调度入口 `observations_from_tool_result` 及失败工厂 `failed_observation`；
  - `backend/app/observations/__init__.py`：导出公开接口；
  - `backend/tests/test_observations.py`：20 项针对状态契约、数学阈值边界、不可变性、失败模型不变量及 Related 重复指标唯一性的 hermetic 单元测试。

#### 核心技术深度复盘 `[必须掌握]`

1. **ToolResult、Observation 与 Evidence 的职责区别与分层演进** `[必须掌握]` `[面试高频]`
   - **`ToolResult`（工具原始输出）**：纯数据载体（如 `MetricQueryResult`），仅表达“数据库/工具计算返回了什么数据”，不携带调查语义、状态判定与证据解释；
   - **`Observation`（单次调查观察）**：标准化、可追溯的观察事实。将原始数据转换为标准状态（`normal`/`anomalous`/`inconclusive`/`insufficient_evidence`/`failed`），携带完整的 Tool Call ID、时间戳、筛选条件、分组维度与来源行引用，具备绝对不可篡改性；
   - **`Evidence`（结构化归因证据）**：被最终诊断结论显式引用、具备解释力、可复现的关键观察集合（将在后续任务实现）；
   - **`Diagnosis`（最终诊断报告）**：基于一组正向与负向 Evidence 逻辑推导出的结构化异常归因结论；
   - **分层意义**：清晰切分数据生产、事实观察、证据沉淀与因果推断四个不同阶段，防止在底层查询中耦合上层诊断逻辑。

2. **为什么正常结果（Normal Results）也必须完整保留并转换为 Observation？** `[必须掌握]` `[面试高频]`
   - **负向控制证据（Negative Control Evidence）**：在指标异常归因中，“证明某些分支没有异常”与“证明某分支有异常”具有同等重要的证据价值；
   - **排查路径依赖**：例如在 Canonical Case 中，定位 `Conversion Rate` 为主要驱动时，必须以“`Sessions` 流量基本稳定（$|\text{relative\_change}| < 5\%$）”作为负向 Evidence 排除流量下滑驱动；在定位 `ASIN-A` 时，必须以“`ASIN-B` 与 `ASIN-C` 转化率稳定”作为负向 Evidence 证明异常集中在特定商品；
   - **设计准则**：工具转换层绝不丢弃任何正常或稳定结果，全部如实生成 `status=ObservationStatus.NORMAL` 的 Observation，供后续 Agent 沉淀为排除假设的负向证据。

3. **为什么 Observation 绝不等于最终诊断（Diagnosis）或业务根因？** `[必须掌握]`
   - `ObservationStatus.ANOMALOUS` 仅代表当前指标与分群在数据上满足材料性下降阈值（$\le -10\%$）；
   - 它**不代表**它是整体异常的主要贡献者（需要结合缺口贡献度与集中度分析），更**不代表**现实物理层面的外部业务根因（如广告出价误调、Listing 差评、竞品降价等）；
   - 严禁将 `anomalous` 命名为 `root_cause`，恪守数据异常定位与业务因果的清晰边界。

4. **不可变性、防御性拷贝与时间戳标准化** `[建议掌握]`
   - `Observation` 采用标准库 `@dataclass(frozen=True)`；
   - `filters` 和 `dimensions` 传入时执行 `dict()` 防御性浅拷贝并使用 `MappingProxyType` 封装为只读映射，彻底阻断源字典修改与直接原地修改（修改抛 `TypeError`）；
   - `group_by` 固化为独立 `tuple` 快照；
   - `created_at` 强制校验必须为时区感知（timezone-aware）的 `datetime`，并统一标准化为 UTC，消除跨时区环境下的时序歧义。

5. **失败状态的模型级不变量强制（MS-P4-003-R1 复盘）** `[必须掌握]` `[面试高频]`
   - 领域不变量必须在模型初始化入口（`Observation.__post_init__`）强制，不能仅依赖上层辅助工厂函数（`failed_observation`）；
   - 当 `status == ObservationStatus.FAILED` 时，强制要求 `current_value`、`baseline_value`、`relative_change`、`sample_size` 必须全部为 `None`，任一非空立即抛出 `ObservationValidationError`，杜绝调用方绕过工厂构造出携带虚假业务数值的非法失败观察；
   - 失败观察强制要求非空 `error_code` 和 `error_message`，成功观察强制禁止携带错误字段。

6. **Related Metrics 展平时的确定性作用域与 ID 唯一性（MS-P4-003-R1 复盘）** `[必须掌握]`
   - 当 `RelatedMetricQueryResult` 包含多个相同 `metric_id` 的子结果时，若 ID 仅包含 `tool_call_id + metric_id + row_idx` 会产生 ID 碰撞；
   - 必须通过确定性的作用域前缀 `f"{tool_call_id}_rel{sub_idx}"` 将子结果索引纳入 ID 命名空间，生成如 `call_001_rel0_orders_0`、`call_001_rel1_orders_0`；
   - 既保证了在同一次 Tool Call 内所有 Observation ID 的全局唯一性与确定性，又保持了单指标独立查询 ID 的简洁与兼容性，且不引入任何随机 UUID。

7. **状态分类的精确边界与 Fail-Fast 契约** `[必须掌握]`
   - $\text{relative\_change} \le -0.10$：`ObservationStatus.ANOMALOUS`（材料性下降）；
   - $|\text{relative\_change}| < 0.05$：`ObservationStatus.NORMAL`（稳定波动）；
   - $-0.10 < \text{relative\_change} \le -0.05$ 或正向增长：`ObservationStatus.INCONCLUSIVE`（边界/未判定）；
   - 小样本（`insufficient_data`）或不可用（`unavailable`）：`ObservationStatus.INSUFFICIENT_EVIDENCE`（证据不足，绝不强行推断）。

---

### 3.12 MS-P4-004: Observation → Evidence 显式提升契约

- **任务目标**：定义最小、不可变、可追溯的 `Evidence` 领域模型与 `EvidenceRole` 角色枚举，实现将特定 `Observation` 显式提升为 `Evidence` 的受控提升函数 `promote_observation_to_evidence`。
- **为什么要做**：Observation 是所有工具调用的客观全貌记录，但并非所有观察都应当作为后续结构化诊断（Diagnosis）的引用论据。必须通过显式提升将 Observation 赋予明确的证据角色（支持性证据、负向控制、证据局限），并在提升过程中严格保证指标数值原样继承、禁止业务因果主观臆断。
- **核心产物**：
  - `backend/app/evidence/models.py`：定义不可变 `Evidence`、`EvidenceRole` 角色枚举、`_derive_evidence_id` 私有 helper、冻结的 `_ALLOWED_ROLE_MAP` 策略及领域异常，严格校验角色兼容性与 ID 推导自洽性；
  - `backend/app/evidence/promoter.py`：实现 `promote_observation_to_evidence(observation, *, role)`，确定性生成 `evidence:{observation_id}:{role.value}`；
  - `backend/app/evidence/__init__.py`：导出 Evidence 模块公开接口；
  - `backend/tests/test_evidence.py`：18 项针对角色兼容矩阵、二元组确定性 ID、模型级 ID 派生校验、策略表不可变、失败证据数值保护与因果字段禁用的 hermetic 单元测试。

#### 核心技术深度复盘 `[必须掌握]`

1. **Observation 与 Evidence 的本质区别与显式提升必要性** `[必须掌握]` `[面试高频]`
   - **`Observation`（观察全貌）**：纯粹描述单次 Tool Call 的输出事实（“查了什么、返回了什么、在数据基准下状态是什么”），不带任何主观归因意图；
   - **`Evidence`（归因证据）**：被分析决策链路显式挑选、具备归因解释力、准备在最终 Diagnosis 中被引用的论据；
   - **为什么严禁自动批量转换**：若将所有 Observation 自动转为 Evidence，会导致证据链被大量无关或冗余信息淹没，破坏证据链的紧凑性与可解释性；显式提升确保了每一条进入诊断的证据都经过了 Agent 或排查逻辑的明确角色分配。

2. **三种证据角色（`EvidenceRole`）的严密语义** `[必须掌握]` `[面试高频]`
   - **`supporting`（支持性证据）**：直接支持某个数据异常判断（如 `conversion_rate` 下降 50% 支持转化率是本次 Sales 下跌的核心驱动）；
   - **`negative_control`（负向控制证据）**：证明某分支未发生异常，用于逻辑上排除其他候选假设（如 `sessions` 波动仅 -0.99% 排除流量规模问题；`ASIN-B` 转化率稳定排除全局系统性崩塌）；
   - **`limitation`（边界与限制证据）**：工具调用失败、样本量不足（`insufficient_data`）或处于边界模糊区间的观察，用于在诊断报告中如实声明证据链的不确定性边界。

3. **为什么 Normal Observation 既可作为 `negative_control` 也可作为 `supporting`？** `[必须掌握]`
   - **作为 `negative_control`**：在多维拆解异常时，用于排除未发生异常的候选指标或分群（如排查 Sales 下跌时，AOV 正常用于排除客单价驱动）；
   - **作为 `supporting`**：当调查起点是“排查某指标是否有异常”时，如果该指标自身处于 Normal 稳定波动范围，该 Observation 直接作为支持性证据证明“该指标无材料性异常”的业务结论。

4. **为什么失败、样本不足和边界结果只能作为 `limitation`？** `[必须掌握]`
   - 失败（`failed`）代表执行失败，样本不足（`insufficient_evidence`）代表统计效力不足，边界（`inconclusive`）代表信号微弱；
   - 严禁将此类不确定或无效结果包装为 `supporting` 或 `negative_control`，否则会引发严重的假阳性（误判）或假阴性（漏判）；系统在领域模型层通过状态-角色兼容矩阵 Fail Fast 强制拦截非法提升。

5. **数值不篡改原则与可追溯性保证** `[必须掌握]`
   - Evidence 提升过程**绝不重新计算指标、绝不查询数据库、绝不允许调用方覆写指标数值**，所有业务数值与查询上下文严格 1:1 复制自 Observation；
   - 领域模型内严禁包含 `root_cause` 属性或主观业务推断，严格恪守数据异常事实定位的架构边界。

6. **证据 ID 的 `(observation_id, role)` 二元组确定性契约与模型级自洽校验 (MS-P4-004-R1)** `[必须掌握]` `[面试高频]`
   - 同一个 Normal Observation 可以合法提升为 `supporting` 或 `negative_control` 两种不同角色；
   - 若 ID 仅依赖 `observation_id`，两次提升将生成相同的 ID，引发实体唯一性碰撞与诊断引用歧义；
   - 因此 Evidence ID 必须由 `(observation_id, role)` 联合确定，格式为 `evidence:{observation_id}:{role.value}`；
   - `Evidence.__post_init__` 强制校验传入的 `evidence_id` 必须严格等于根据 `(observation_id, role)` 推导出的期望 ID，防止调用方直接构造不自洽或伪造的 Evidence。

7. **领域策略不可变冻结原则 (MS-P4-004-R1)** `[必须掌握]`
   - 模块级策略表（如 `_ALLOWED_ROLE_MAP`）若为普通 `dict`，外部代码可在运行时动态修改键值对绕过安全规则；
   - 必须使用 `MappingProxyType` 将策略表封装为只读映射，内层集合使用不可变 `frozenset`，确保领域规则在整个运行时生命周期中具有不可篡改的防御性。

---

### 3.13 MS-P5-001 / MS-P5-001-R1: OpenAI Agents SDK Runtime Capability Spike

- **任务目标**：验证官方 Python OpenAI Agents SDK (`openai-agents==0.22.0`) 作为 MetricSleuth 核心 Agent Runtime 的可行性，设计并验证 `User Prompt → SDK Runner → 本地 Analytics Tool → Tool Result 回传模型 → Runtime 继续推理 → Structured Output (Pydantic)` 的端到端链路。
- **当前状态与环境事实**：
  - 本地环境当前未配置 `OPENAI_API_KEY` 与 `METRICSLEUTH_AGENT_MODEL` 凭据，Live Spike 处于 `Blocked` 状态（验证脚本返回退出码 2）；
  - 当前测试环境实际解释器为 `Python 3.13.5`（满足项目 `>=3.12` 要求）；
  - Phase 5 验收当时，24 项 Hermetic 单元测试已覆盖全部伪 PASS 反例，彼时全量 128 项测试全部通过；当前加入 Phase 6 Bridge 后的全量数为 139；
  - 严禁在未注入真实凭据前声称 Live Spike 已通过。
- **统一演进路线图**：
  - Current：`Phase 5 — Agent Runtime Spike + 最小接入`
  - Next：`Phase 6 — Autonomous Investigation`（自主多维下钻调查）
  - Phase 7：`Evidence-driven Diagnosis`（证据驱动归因模型）
  - Phase 10：`FastAPI / React Productization`（产品化交付）
- **核心产物**：
  - `backend/pyproject.toml`：精确固定 `openai-agents==0.22.0` 依赖与 `pydantic>=2.12,<3`；
  - `backend/app/agent_runtime/spike.py`：实现 `RuntimeSpikeOutput`（Pydantic 结构化输出）、`ToolCallBudgetGuard`（执行前线程安全原子预算守卫）、`create_get_metric_definition_tool`（配置 `failure_error_function=None` 保证 Fail-Closed）、`verify_runtime_trace_and_budget`（严格 Trace 时序与 Call ID 校验）、`cross_validate_structured_output` 与 `run_runtime_spike`；
  - `backend/app/agent_runtime/__init__.py`：导出模块公开接口；
  - `backend/tests/test_runtime_spike.py`：24 项 hermetic 单元测试（针对性覆盖每次 Run 独立预算、并发原子拦截、SDK FunctionTool 第二次调用的 Fail-Closed 异常穿透、公开入口拒绝放宽固定预算、Trace 恰好一次与时序颠倒、Call ID 不匹配、工具名错误、Message 位置异常、结构化输出不一致、非法工具 output 与缺凭据状态码等反例）；
  - `backend/scripts/verify_phase5_runtime_spike.py`：支持凭据注入时的真机 Live Spike 验证与脱敏摘要输出，凭据缺失时返回退出码 2（`Live Status: BLOCKED`）。

#### 核心技术深度复盘 `[必须掌握]`

1. **执行前原子预算拦截（Pre-execution Budget Guard） vs 事后检测（Post-hoc Check）** `[必须掌握]` `[面试高频]`
   - **事后检测的缺陷**：在 `Runner.run_sync()` 运行完毕后再统计 `ToolCallItem` 数量，如果模型发起了超额工具调用，此时底层业务函数（`AnalyticsTools.get_metric_definition` 或未来的数据库查询）已经在底层**完成了实际执行**并消耗了计算与连接资源；
   - **执行前原子拦截机制**：通过 `ToolCallBudgetGuard` 封装 `threading.Lock`，在进入 `AnalyticsTools.get_metric_definition()` 之前执行原子的 `check_and_consume` 判定。若已达到上限立即抛出 `RuntimeBudgetExceededError`，确保底层业务工具的实际调用次数严格为 1，杜绝超额执行。

2. **Fail-Closed 异常配置 `failure_error_function=None`** `[必须掌握]`
   - OpenAI Agents SDK 的 `@function_tool` 默认启用了错误捕获（`_use_default_failure_error_function = True`），工具抛出的异常会被捕获并转化为普通文本 Tool Result 返回给模型，模型可能忽略错误继续编造结果造成伪 PASS；
   - 必须显式配置 `function_tool(get_metric_definition, failure_error_function=None)`，使预算异常与系统错误以 Fail-Closed 机制直接穿透 Runner 向上抛出，使整个运行明确失败。

3. **严格 Trace 时序与 Call ID 身份绑定验证 (MS-P5-001-R1)** `[必须掌握]` `[面试高频]`
   - **名称与 Call ID 匹配**：检查 `ToolCallItem.tool_name == expected_tool_name`，且 `ToolCallOutputItem.call_id == ToolCallItem.call_id`；
   - **恰好一次调用**：Runtime Spike 契约只接受一个预期工具调用和一个匹配的 Tool Output；即使调用方配置了更大的上限，也不能把多次调用伪装成单次成功；
   - **严格偏序关系**：在 `new_items` 中验证：`call_idx < output_idx < last_msg_idx`（Tool Output 必须在 Tool Call 之后，最终 Message 必须在 Tool Output 之后）；
   - **反例防御**：严密拦截无 Tool Call、多 Tool Call、工具名错误、Call ID 不匹配、Tool Output 逆序出现在 Tool Call 前、以及所有 Message 都位于 Output 之前的非法 Trace。

4. **结构化输出（Structured Output）与真实 Tool Output 的交叉验证** `[必须掌握]`
   - 从匹配成功的 `ToolCallOutputItem` 中解析出真实的工具返回值字典，提取底层的 `metric_id` 和 `unit`；
   - 与模型最终输出的 `RuntimeSpikeOutput` 进行强类型字段级交叉比对（`metric_id`、`unit`、`tool_used`），若模型篡改了单位或工具名，立即抛出 `RuntimeValidationError`，杜绝自由文本幻觉。

5. **公开轮次统计与 SDK 兼容性** `[必须掌握]`
   - 严禁依赖 `_current_turn` 等私有字段；
   - 固定使用公开字段 `len(result.raw_responses)` 统计实际模型交互轮数，并校验 `1 <= turns_count <= max_turns`。

---

### 3.14 MS-P6-001: Runtime Analytics Tool Bridge

- **任务目标**：把已经验收的 AnalyticsTools 查询能力接入官方 SDK Tool，并将 ToolResult 转换为模型可继续推理的可追溯 Observation，而不实现自己的 Agent Loop。`[必须掌握]` `[项目特有]`
- **核心链路**：`ToolContext.call_id → AnalyticsTools → MetricQueryResult → Observation → JSON-safe Tool Output`。真实 SDK Call ID 进入 Observation 后，后续 Trace、Evidence 才能引用同一个调用身份。`[必须掌握]` `[面试高频]`
- **共享预算**：`query_metric` 与 `query_related_metrics` 使用同一个每次 Run 的 `ToolCallBudgetGuard(max_calls=8)`；预算在参数解析和底层查询前扣减，因此非法参数、数据库错误和正常调用都同样消耗预算。线程锁保证并发下最多只有 8 次进入 AnalyticsTools。`[必须掌握]`
- **显式 JSON 边界**：领域层保留 `Decimal`、`date`、`MappingProxyType`、tuple 和 Enum，SDK 输出边界才将其转换为无损字符串、ISO 日期、普通对象/数组和枚举值，避免在领域模型内部为了 JSON 传输丢失类型语义。`[必须掌握]` `[面试高频]`
- **Strict Schema 踩坑**：SDK strict schema 不接受 `dict[str, str]` 这种任意键对象。项目没有关闭 strict mode，而是将模型侧 filters 定义为 `DimensionFilter[]`，再在适配器内转换为底层 Mapping。这是“外部严格协议适配内部领域接口”的典型做法。`[面试高频]`
- **边界**：本任务没有读取 Ground Truth，没有提升 Evidence，没有选择主驱动或下一维度，也没有实现 Planner/while loop。它只提供 Phase 6 自主调查的最小工具面，Autonomous Investigation 尚未完成。
- **验证事实**：11 项专项 Hermetic 测试通过；该任务验收时全量为 139 项，加入 MS-P6-002 时为 148 项，当前为 215 项。测试包含真实 `FunctionTool.on_invoke_tool`、跨 Tool 共享预算、第 9 次调用拦截、并发上限、严格日期、错误穿透、空结果和 Ground Truth 隔离。

**自测题**：为什么不直接关闭 SDK strict mode 来支持任意键 filters？为什么工具预算必须在参数解析前扣减？

### 3.15 MS-P6-002: Investigation Run Contract 与多调用 Trace

- **任务目标**：让官方 SDK `Runner` 真正管理多轮 Tool 执行，并在业务层验证 Trace 的领域完整性，而不是自己编写 `while` 循环。`[必须掌握]` `[面试高频]`
- **Runner 与业务层分工**：SDK 负责把模型 Tool Call 路由到 FunctionTool、把 Tool Output 送回下一模型轮次并判断最终结束；MetricSleuth 只提供工具、预算和 Trace/Evidence 所需的不变量。`[必须掌握]`
- **Call ID 是 Trace 主键**：每个 Tool Call ID 必须唯一且恰好对应一个后置 Output；Output envelope 和其中每条 Observation 还必须重复声明相同 Call ID 与 Tool Name。三层身份交叉验证可防止结果串线或伪造引用。`[必须掌握]` `[面试高频]`
- **Trace 完整性不是只数调用次数**：还必须拒绝错误工具、重复/孤儿 Output、Output 出现在 Call 之前、Observation ID 跨调用重复、最终 Message 缺失或不在最后等伪 PASS 情形。`[建议掌握]`
- **Hermetic SDK 测试边界**：`ScriptedModel` 会真实驱动 Runner 和本地 FunctionTool，但模型响应顺序由测试预先写定。因此它证明 SDK 编排、参数验证和 Trace 审计正确，不证明真实 LLM 会自主选择正确路径。`[必须掌握]`
- **为什么使用直接 Tool Call**：当前每次 Observation 都可能改变下一步调查判断，中间输出又足够小，适合让模型逐轮观察后决定下一步；当前没有引入程序化批处理 Tool Calling。`[项目特有]`
- **验证事实**：两种不同的脚本 Tool 顺序均通过真实 Runner；9 项专项测试通过，该任务验收时全量为 148 项，当前为 215 项；生产模块未出现 Ground Truth、固定维度顺序或 SDK 私有字段依赖。

**面试自测题**：ScriptedModel 测试通过为什么不能证明 Agent 已具备真实自主调查能力？Tool Call、Tool Output 与 Observation 为什么要做三层 Call ID 校验？

### 3.16 MS-P6-003: Development Scenario Investigation Harness

- **任务目标**：为 Canonical、Traffic、No-anomaly 三个开发场景建立真实 PostgreSQL 的确定性验收 Oracle，确认数据生成、AnalyticsTools、指标口径和场景标签彼此一致。`[必须掌握]` `[项目特有]`
- **避免标签泄漏**：Harness 对三个场景运行同一套全局、Marketplace、ASIN、Traffic Source 探针，先生成所有实际记录，之后才读取 `ground_truth.json` 评分。Ground Truth 不进入生产模块、Prompt、Tool 参数或 Tool Output。`[必须掌握]` `[面试高频]`
- **驱动需要不同缺口口径**：Canonical 的 Driver 是 Conversion Rate，因此使用 `current_sessions × baseline_cr - current_orders`；Traffic 的 Driver 是 Sessions，因此使用 `baseline_sessions - current_sessions`。复用同一种缺口会在 Alternate Driver 场景中得出错误归因。`[必须掌握]`
- **No-anomaly 停止语义**：五个核心指标变化绝对值都小于 5% 时返回 `no_material_anomaly`、无 primary driver、空 affected scope，不能为了“完成下钻”而制造异常。`[项目特有]`
- **严格成员集合**：每层 Metric Result 的维度成员集合必须一致，负向对照与 Ground Truth 做精确集合比较；预期成员缺失会立即失败，不能用条件循环静默跳过。`[建议掌握]`
- **测试边界**：固定探针矩阵属于测试 Harness，而非生产 Agent Workflow。三场全部 PASS 证明 Benchmark/Data/Analytics 契约可复现，仍不证明真实 LLM 会自主选择同样的调查路径。`[必须掌握]`
- **验证事实**：三场真实 PostgreSQL Harness 全部通过并恢复 canonical；4 项 Hermetic Harness 测试通过；加入 MS-P7-005 后为 215 项后端全量测试；生产 `backend/app` 零 Ground Truth 引用。

**面试自测题**：为什么 Ground Truth 必须在实际调查记录生成后才加载？为什么 Sessions 驱动不能使用 Conversion Order Shortfall 评分？

### 3.17 MS-P7-001: Structured Diagnosis Domain Contract

- **任务目标**：把 Investigation 结束后的结论收敛为可校验、可引用、不可变的结构化 Diagnosis，同时严格停留在数据异常贡献定位，不宣称现实业务根因。`[必须掌握]` `[项目特有]`
- **模型与 Builder 分工**：`Diagnosis.__post_init__` 保护任何构造入口都必须满足状态不变量；`build_diagnosis()` 负责跨 Evidence 的语义校验和事实派生。只在工厂函数校验会允许直接构造绕过，只在模型内塞入全部查找逻辑又会让领域实体承担不必要的仓储职责。`[必须掌握]` `[面试高频]`
- **五种终止状态**：成功状态为 `diagnosed` 与 `no_material_anomaly`；非成功状态为 `insufficient_evidence`、`budget_exhausted`、`tool_failure`。非成功状态禁止携带 Driver、Scope 和置信度，防止失败结果伪装成已诊断结论。`[必须掌握]`
- **Evidence 是事实单一来源**：成功 Diagnosis 的目标变化值直接从指定 Evidence 复制，`evidence_ids` 按输入快照派生；目标异常、Driver、Scope 和 negative control 都必须由传入 Evidence 支持。调用方不能另传一套数值制造“引用了证据但数字不同”的结论。`[必须掌握]` `[面试高频]`
- **Fail-Closed 不等于强制伪造 Evidence**：预算可能在下一次 Tool 执行前耗尽，数据库错误也可能在 Observation 建立前中断，所以 `budget_exhausted` 和 `tool_failure` 合法允许零 Evidence。若 tool failure 已有 Evidence，则必须是 FAILED + LIMITATION。`[建议掌握]`
- **深层不可变与类型陷阱**：Mapping 做防御性复制后使用 `MappingProxyType`，序列转为 tuple，时间标准化为 UTC；同时显式拒绝把单个字符串当作 `Sequence[str]`，避免它被逐字符拆分后意外通过校验。`[面试高频]`
- **因果边界**：模型刻意没有 `root_cause` 字段；`primary_driver` 只表示数据指标的主要贡献 Driver。没有广告竞价、Listing 变更等外部事实输入时，系统不能把相关性升级为现实因果。`[必须掌握]`
- **验证事实**：12 项专项测试通过；加入 MS-P7-005 后为 215 项后端全量测试；无需网络、API Key 或数据库。Phase 6 Live Evaluation 仍为 Blocked，MS-P7-001 的 Accepted 只表示 Hermetic 领域契约成立。

**面试自测题**：为什么 Diagnosis 的数值必须从 Evidence 派生而不是由 LLM 同时填写？为什么 tool failure 不能一律要求至少一个 Evidence？

### 3.18 MS-P7-002: Diagnosis Draft Resolution 与 Evidence Citation Verification

- **任务目标**：在不可信 Runtime 输出和可信 Diagnosis 领域对象之间增加引用解析边界，防止模型伪造 Evidence 或填写一套与证据不一致的数字。`[必须掌握]` `[项目特有]`
- **Fact-free Draft**：`DiagnosisDraft` 只允许状态、目标指标、目标 Evidence ID、Driver、Scope、引用 ID、confidence 和 limitations；没有 current、baseline、relative change、unit、change 或 root cause 字段。事实字段从类型层面就无法由 Draft 输入。`[必须掌握]` `[面试高频]`
- **引用解析而不是信任字符串**：Resolver 对 Evidence Catalog 做快照、类型校验和 ID 唯一性断言，再将 Draft 的每个 ID 精确解析为对象。未知 ID、Catalog 重复 ID、target 未包含在选择集合中都会立即失败。`[必须掌握]`
- **最小披露原则**：最终 Diagnosis 只包含 Draft 明确选择的 Evidence，且顺序与 Draft 一致；Catalog 中即使存在其他证据也不会自动进入结论。这让引用集合可以审计，也避免无关证据污染结论。`[建议掌握]`
- **复用领域单一真理源**：Resolver 不复制 diagnosed/no-anomaly/tool-failure 的语义规则，而是把解析后的真实 Evidence 交给 `build_diagnosis()`。因此缺少 Driver、Scope 或 negative control 仍由既有领域规则拒绝。`[必须掌握]`
- **非有限 Decimal 边界**：`Decimal("NaN")` 和 `Decimal("Infinity")` 也是 Decimal 实例，但不是合法置信度。Draft 与 Diagnosis 都显式要求 finite 且位于 `[0,1]`，并统一转为 `DiagnosisValidationError`。`[面试高频]`
- **验证事实**：Draft Resolver 14 项专项、Diagnosis 合计 26 项通过；加入 MS-P7-005 后后端全量为 215 项；生产 Draft 模块无 Ground Truth、SDK Runtime、数据库或指标事实字段依赖。

**面试自测题**：为什么只验证 Evidence ID 非空远远不够？为什么 Resolver 应当按 Draft 顺序选证据，而不是直接使用整个 Catalog？

### 3.19 MS-P7-003: Evidence Selection Draft 与 Observation Citation Resolution

- **任务目标**：把未来 Runtime 的 Evidence 选择限制为 `(observation_id, role)` 引用意图，再由应用从可信 Observation Catalog 中解析事实并显式提升。`[必须掌握]` `[项目特有]`
- **引用与事实分离**：`EvidenceSelection` 只有 Observation ID 和 EvidenceRole，不能携带 metric、数值、日期、filters、dimensions 或错误字段。这样模型可以表达“引用哪条观察、用于什么论据”，却不能重写观察事实。`[必须掌握]` `[面试高频]`
- **完整 Catalog 校验**：Resolver 不仅校验被引用条目，还拒绝 Catalog 中任何重复 Observation ID 或非 Observation 对象，即使坏条目当前未被选择。应用持有的事实集合本身必须先保持无歧义。`[建议掌握]`
- **多角色不等于重复**：同一 Normal Observation 既可作为 supporting，也可作为 negative control；二者 Evidence ID 因 role 后缀不同而保持唯一。真正禁止的是完全重复的 `(observation_id, role)`。`[必须掌握]`
- **复用 Promoter**：Resolver 不手工复制 Observation 字段，也不重复 Status/Role 兼容表，而是调用 `promote_observation_to_evidence()`。这保证 Evidence 构造与角色规则仍有单一真理源。`[必须掌握]`
- **空选择语义**：预算在首次有效 Observation 前耗尽或工具提前失败时，可以合法生成空 Evidence tuple；上层 Diagnosis 的非成功状态会继续约束这种结果，不能因此伪造成功诊断。`[建议掌握]`
- **验证事实**：Evidence Selection 14 项专项通过；加入 MS-P7-005 后后端全量为 215 项；生产模块没有 Runtime、数据库、Ground Truth 或 Diagnosis 依赖。

**面试自测题**：为什么同一 Observation 的两种角色不应被当作重复？为什么 Catalog 中未被引用的重复 ID 也必须导致失败？

### 3.20 MS-P7-004: Observation-to-Diagnosis Composition Contract

- **任务目标**：把两个已经独立验收的引用解析边界组合成一条端到端领域链，同时保留完整 Evidence Portfolio 供审计。`[必须掌握]` `[项目特有]`
- **组合优于复制**：`compose_diagnosis_from_observations()` 先调用 Evidence Selection Resolver，再把结果作为 Catalog 传给 Diagnosis Draft Resolver。组合层不重新判断角色、状态、Driver、Scope 或 negative control，避免同一业务规则出现多个实现。`[必须掌握]` `[面试高频]`
- **Portfolio 与 Citation 的区别**：Portfolio 表示调查中被显式提升的全部 Evidence；Diagnosis Citation 只是最终结论实际引用的子集。保留二者可以分别评估 Evidence Coverage、Citation Precision 和未使用证据，而不是为了让集合相等丢弃调查记录。`[必须掌握]`
- **端到端事实链**：目标数值从 Observation 经 Promoter 复制到 Evidence，再由 Diagnosis Builder 从目标 Evidence 复制到 DiagnosisChange。任何一层都不能让 Draft 重填数值，因此可以沿 ID 和对象关系回溯。`[必须掌握]`
- **失败原样传播**：未知 Observation 属 EvidenceValidationError，未知 Evidence 或缺少 negative control 属 DiagnosisValidationError；组合层不吞异常、不转成部分成功，也不把错误文本当诊断。`[建议掌握]`
- **空链路合法性**：`budget_exhausted` 可以使用空 Evidence Portfolio 生成非成功 Diagnosis，符合预算在首次有效 Observation 前耗尽的真实情况。`[项目特有]`
- **验证事实**：Composition 11 项专项通过；加入 MS-P7-005 后后端全量为 215 项；模块无 SDK、网络、数据库或 Ground Truth 依赖。

**面试自测题**：为什么 Evidence Portfolio 可以大于 Diagnosis 引用集合？为什么组合层不应再次实现 negative control 检查？

### 3.21 MS-P7-005: SDK Trace Observation Catalog Extraction

- **任务目标**：把 SDK Trace 中本地 FunctionTool 的 JSON Output 严格恢复为可信 Observation Catalog，为 Evidence/Diagnosis 组合链提供事实对象。`[必须掌握]` `[项目特有]`
- **事实只能来自 Tool Output**：提取器先执行现有 Trace 审计，之后只遍历 `ToolCallOutputItem`。模型 Message 或 final output 即使包含格式正确的 Observation JSON，也不会成为事实来源。`[必须掌握]` `[面试高频]`
- **严格反序列化边界**：`observation_from_json()` 要求顶层键集合精确匹配，Decimal 只接受有限字符串，日期和时区严格解析，Mapping、list 和 Enum 不做宽松强制转换。这样 Schema 漂移与类型污染会在进入领域对象前失败。`[必须掌握]`
- **领域异常归一化**：日期、Decimal、Enum 解析错误以及 Observation 不变量错误统一包装成 `RuntimeTraceError`，上层只需处理稳定的 Runtime 边界异常，不会泄漏多种底层异常类型。`[建议掌握]`
- **并发顺序确定性**：并发 Tool Output 可能逆序完成。Catalog 不采用完成先后，而按已经验证的 Tool Call 顺序规范化，并与 Summary Observation IDs 交叉校验。`[面试高频]`
- **Roundtrip 验证**：normal、anomalous 和 failed Observation 都满足 `from_json(to_json(obs)) == obs`；失败状态的空数值和错误字段不变量仍由 Observation 模型最终保护。`[建议掌握]`
- **验证事实**：专项 12 项、后端全量 215 项通过；不需要网络、API Key 或数据库，Ground Truth 零引用。

**面试自测题**：为什么不能从模型 final output 重建 Observation？并发 Tool Output 逆序完成时为什么应按 Tool Call 顺序建立 Catalog？

### 3.22 MS-P7-006: Runtime Structured Diagnosis Intent Contract

- **任务目标**：为未来 Runtime 最终输出建立 SDK 可约束解码、但不携带指标事实的严格 Schema，并确定性转换为现有领域 Draft。`[必须掌握]` `[项目特有]`
- **Structured Output 不是普通 JSON Mode**：官方 SDK 的 `Agent(output_type=RuntimeDiagnosisIntent)` 会使用 JSON Schema 结构化输出；项目还验证 `AgentOutputSchema` 为 strict，所有对象节点都设置 `additionalProperties=false`。`[必须掌握]` `[面试高频]`
- **Schema 层消除事实伪造面**：Runtime 只能输出 Observation ID、Evidence Role、Evidence ID、Driver、Scope、confidence 和 limitations。current/baseline/change/unit/root cause 根本不在 Schema 中，模型无法通过合法输出覆盖工具事实。`[必须掌握]`
- **JSON 与领域类型分层**：Confidence 在 JSON 中是字符串，进入应用后才严格转成有限 Decimal；Scope 使用 item array 避免 arbitrary-key object 的 strict Schema 问题，之后再转成只读 Mapping。`[面试高频]`
- **深层不可变**：Pydantic frozen 只能阻止字段重新赋值，因此集合字段使用 tuple；before validator 又强制原始 Structured Output 必须是 JSON array，防止 Python tuple/字符串宽松输入。`[建议掌握]`
- **不重复领域规则**：转换器不判断 diagnosed 是否具备 Driver/negative control，只构造两个现有 Draft；真正的引用和状态语义继续由 Evidence/Diagnosis Resolver 负责。`[必须掌握]`
- **验证事实**：Runtime Intent 专项 9 项、后端全量 224 项通过；不运行 Agent、网络或数据库。OpenAI 官方文档确认设置 Agent `output_type` 会启用 Structured Outputs。

**面试自测题**：为什么 confidence 在模型 Schema 中使用字符串而不是 float？为什么 Pydantic frozen 模型仍要把 list 快照为 tuple？

### 3.23 MS-P7-007: Hermetic Evidence-driven Diagnosis Runtime Integration

- **任务目标**：用官方 SDK Runner 把 Tool 调用、可信 Observation、Structured Intent、Evidence 和 Diagnosis 真正串成一次离线 Run。`[必须掌握]` `[项目特有]`
- **Runner 仍是唯一 Loop**：生产模块只创建 Agent、调用 `Runner.run_sync()` 并执行后置审计/解析，没有自建 while loop 或固定 next dimension。`[必须掌握]`
- **两类结构化输出边界**：Tool Output 是可信事实来源，最终 Runtime Intent 是不可信选择来源。前者重建 Observation，后者只能提交引用；两者在领域 Resolver 中交叉验证后才能形成 Diagnosis。`[必须掌握]` `[面试高频]`
- **兼容旧 Trace Verifier**：旧 verifier 要求 string final output，新链路使用结构化对象。实现创建只替换 audit-only final output 的浅视图，保留真实 new_items/raw_responses；审计后再强制验证原始 final output 类型。公开 Summary 保存真实 Intent JSON，不暴露 sentinel。`[建议掌握]`
- **独立预算**：每次 `run_evidence_driven_diagnosis()` 都创建新的 `ToolCallBudgetGuard`，连续两次 Run 不共享消耗额度。`[必须掌握]`
- **Hermetic 边界**：ScriptedModel 真正经过 Runner 和 FunctionTool，但选择步骤由测试预设。它证明架构闭环和 Fail-Closed，不证明真实模型自主调查准确率。`[必须掌握]`
- **验证事实**：diagnosed、no-anomaly、不同 Tool 顺序、未知引用、缺负向对照、非 Intent 输出和预算隔离共 7 项专项；后端全量 231 项通过。

**面试自测题**：为什么 Tool Output 和模型 Structured Intent 需要不同的信任等级？ScriptedModel 端到端通过为什么仍不能报告真实 Agent Accuracy？

### 3.24 MS-P8-001: Evaluation Case Contract 与 Deterministic Core Scoring

- **任务目标**：把开发集标签建模为严格、不可变、与 Runtime 隔离的评测 Case，并先实现无歧义的核心语义评分。`[必须掌握]` `[项目特有]`
- **Ground Truth 隔离的正确边界**：Ground Truth 可以在 Evaluation 包中明确出现，但不能进入 Agent Runtime、Prompt、Tool 或查询面。隔离测试应扫描受禁止模块，而不是禁止整个应用代码出现评测概念。`[必须掌握]` `[面试高频]`
- **显式路径所有权**：Loader 不内置默认文件位置，Evaluation Runner 必须显式提供路径，避免 Runtime 通过共享默认配置意外发现标签。`[建议掌握]`
- **严格配置契约**：顶层必须是 list，每个 Case 键集合精确，重复 JSON key、NaN 常量、重复 case/scenario、非法状态和非法 Scope/Control 都 Fail Fast。`[必须掌握]`
- **固定 Scope 指标**：Marketplace、ASIN、Traffic Source 三层分别比较，Scope Accuracy 为正确层数除以 3；额外 Scope 虽不改变三层分数，但会使 Exact Match 失败。`[项目特有]`
- **暂不伪造 Evidence 指标**：当前只评分 status、target、driver、scope、no-anomaly 与 exact match。Evidence Precision/Coverage 需要先定义每个 Case 的期望证据义务，不能拿“引用数量”冒充质量。`[必须掌握]`
- **验证事实**：Evaluation Core 专项 12 项、后端全量 243 项通过；真实三条 Ground Truth 均可严格加载。

**面试自测题**：为什么 Ground Truth 隔离不等于 Evaluation 代码不能读取它？为什么 Scope Accuracy 和 Exact Match 应同时存在？

### 3.25 MS-P8-002: Core Evaluation Aggregate Report

- **任务目标**：把逐 Case 的确定性核心分数聚合成可比较、不可变的评测报告。`[必须掌握]` `[项目特有]`
- **统一分母**：status、target、driver、no-anomaly、exact match 和每层 scope 都使用 Case Count 作为分母，避免不同指标暗中排除失败 Case 导致不可比。`[必须掌握]`
- **Decimal 而非 float**：评测报告需要可复现，所有比率使用 Decimal；模型还验证有限范围 `[0,1]`，拒绝 NaN/Infinity。`[建议掌握]`
- **Macro Scope Accuracy**：先分别计算 Marketplace/ASIN/Traffic Source Accuracy，再取三层算术平均，让每层维度拥有相同权重。`[项目特有]`
- **报告模型自校验**：case_count 必须与唯一 case_ids 数量一致，scope mapping 必须精确三键，macro 必须等于三层均值；即使绕过聚合器直接构造也不能伪造不自洽报告。`[面试高频]`
- **验证事实**：Aggregate 专项 8 项、后端全量 251 项通过；没有文件、Runtime、Evidence 或数据库依赖。

**面试自测题**：为什么聚合指标应使用统一分母？Macro Scope 与把所有 Scope 判断直接混在一起统计有什么关系？

### 3.26 MS-P8-003: Evidence Obligation Contract

- **任务目标**：先把“一个正确诊断应提供哪些证据”变成机器可执行义务，再讨论 Precision 与 Coverage。`[必须掌握]` `[项目特有]`
- **四类义务**：target supporting、driver supporting、stable metric、negative control member；每类字段组合不同且由模型强制。`[必须掌握]`
- **Precision 与 Coverage 的前提**：没有期望义务集合，只统计引用个数无法判断引用是否正确或遗漏关键对照。义务契约提供了明确分母和匹配目标。`[面试高频]`
- **确定性身份**：义务 ID 从 kind/metric 或 kind/dimension/value 唯一派生；组件禁止冒号以消除分隔歧义，直接伪造 ID 会失败。`[建议掌握]`
- **验证事实**：Canonical 9 项、No-anomaly 13 项；专项 5 项、全量 256 项通过。

**面试自测题**：为什么 Evidence Coverage 必须先定义期望义务？Citation Precision 与 Coverage 分别惩罚什么问题？

### 3.27 MS-P8-004: Evidence Citation Precision 与 Coverage Scoring

- **任务目标**：把 Diagnosis 的实际引用与 Case 的机器可执行 Evidence Obligations 对齐，分别度量引用相关性和证据义务完整性。`[必须掌握]` `[面试高频]`
- **Precision 与 Coverage 的分母不同**：Citation Precision = 匹配义务的已引用 Evidence 数 / 全部已引用 Evidence 数，惩罚无关引用；Evidence Coverage = 已覆盖义务数 / 全部义务数，惩罚关键证据遗漏。二者不能互相替代。`[必须掌握]`
- **Portfolio 不等于 Citation**：完整 Portfolio 用于审计，但只有 `Diagnosis.evidence_ids` 中真正引用的 Evidence 才能参与 Coverage。否则 Agent 可以先收集大量证据、最终不引用，却获得虚高覆盖率。`[项目特有]`
- **多对多匹配是合理语义**：一条正常指标 Evidence 既可能满足 stable metric，又可能因维度上下文满足 negative control；评分按义务覆盖去重，但该 Citation 本身只计一次。`[建议掌握]`
- **冲突上下文 Fail Closed**：当 filters 与 dimensions 对同一维度给出不同值时，不选择任一优先级，而是拒绝负向对照匹配，避免不一致查询上下文形成伪证据。`[必须掌握]`
- **零引用不是 0% Precision**：没有引用时 Precision 的数学分母为 0，应表示为 `None`；Coverage 仍可明确为 0。把 undefined 写成 0 会混淆“引用全部错误”和“根本没有引用”。`[面试高频]`
- **验证事实**：Evidence Scoring 专项 10 项、后端全量 266 项通过；评分为纯函数，不访问网络、数据库或 Agent Runtime，Runtime/query Ground Truth 扫描零命中。

**面试自测题**：为什么一份 Diagnosis 可能 Precision=100% 但 Coverage 很低？为什么未引用的 Portfolio Evidence 不能提升 Coverage？

### 3.28 MS-P8-005: Unsupported Claim Contract 与 Scoring

- **任务目标**：独立审计 Diagnosis 自己提出的可验证事实是否有实际引用 Evidence 支撑，而不是再次对 Ground Truth 做准确率判断。`[必须掌握]` `[面试高频]`
- **三个指标各问不同问题**：Citation Precision 问“引用是否相关”，Coverage 问“期望义务是否齐全”，Unsupported Claim Rate 问“实际结论是否有证据”。混用会导致看似完整、实则无法解释的评测结果。`[必须掌握]`
- **Claim 原子化**：diagnosed 结果展开为目标变化、Primary Driver 和每个 Scope member；逐成员 Scope 可以显示部分支持，而不是把整个范围压成一个布尔值。No-anomaly 只产生目标稳定 Claim，非成功状态不产生成功事实 Claim。`[项目特有]`
- **数值防伪造**：Target Claim 不只核对 Evidence ID，还逐项核对 current、baseline、relative change 与 unit。即使绕过 Builder 直接构造 Diagnosis，篡改任何目标数字也会被记为 unsupported。`[必须掌握]`
- **独立审计防线**：正常 Runtime 会复用 Diagnosis Builder，因此通常应得到 0% Unsupported Claims；独立 Scorer 的价值是检测绕过 Builder、序列化污染或未来边界回归，而不是重复生成 Diagnosis。`[面试高频]`
- **验证事实**：Unsupported Claims 专项 11 项、后端全量 277 项通过；模块不读取 Ground Truth、网络、数据库或 Runtime I/O。

**面试自测题**：为什么一个领域 Builder 已经强制证据支撑后，仍值得保留独立 Unsupported Claim Scorer？为什么非成功状态的比率应为 `None` 而不是 0？

### 3.29 MS-P8-006: Evaluation Run Outcome 与 Tool Operational Scoring

- **任务目标**：给成功和失败 Run 建立统一、不可变的事实信封，再计算协议层 Tool 指标。`[必须掌握]` `[项目特有]`
- **为什么 Summary 不够**：`EvidenceDrivenRunSummary` 只有在 Runner、Trace 审计和领域组合成功后才存在；Runner 或 Tool 抛错时没有 Summary。将“对象不存在”直接解释为 Tool Failure 会丢失 Runtime Failure、预算耗尽和调用计数。`[面试高频]`
- **显式事实优于异常猜测**：失败 Outcome 要求调用方提供 status、attempted/succeeded counts 和 failure code；评分器不解析异常 message，因为文本不稳定、可能含敏感信息，也无法可靠承担机器分类协议。`[必须掌握]`
- **Tool Success 的边界**：本指标只说明 Tool Call 是否获得配对、合法的协议输出，不说明指标查询是否命中 Ground Truth，更不说明最终 Diagnosis 是否正确。语义准确率由其他评测指标负责。`[必须掌握]`
- **分母为零语义**：零次 Tool Attempt 时 Success Rate 为 `None`，不是 0%；Budget Exhaustion 是 Run 级布尔状态，可与此前调用 100% 成功同时成立。`[面试高频]`
- **依赖延迟加载**：成功 Summary 适配器在调用时才导入 Runtime 类型，避免普通 `app.evaluation` import 被迫加载 Agents SDK。`[建议掌握]`
- **验证事实**：Evaluation Operational 专项 15 项、后端全量 292 项通过；Ground Truth/I/O 扫描零命中。

**面试自测题**：为什么 Tool Success Rate 不能替代 Diagnosis Accuracy？为什么失败分类不应该依赖 exception message 字符串？

### 3.30 MS-P8-007: Tool Operational Aggregate Report

- **任务目标**：将逐 Run ToolOperationalScore 聚合为可比较的操作报告，并固定三个指标各自的统计分母。`[必须掌握]` `[面试高频]`
- **调用级 micro vs Run-level mean**：Tool Success Rate = 总成功调用 / 总尝试调用，避免一个只调用 1 次的 Run 与一个调用 20 次的 Run 被等权平均；Average Tool Call Count 和 Budget Exhaustion Rate 则明确使用 Run 数分母。`[必须掌握]`
- **零调用语义**：零次调用 Run 仍是一次真实 Run，应进入平均调用次数和预算耗尽率分母，但不进入 Success Rate 分母；全体零调用时 Success Rate 为 `None`。`[面试高频]`
- **聚合器不猜测事实**：聚合器只接受已验证的 `ToolOperationalScore`，不读取 Trace、Ground Truth 或异常文本；失败事实必须先由 Outcome 边界显式记录。`[项目特有]`
- **验证事实**：Operational Aggregate 专项 7 项、后端全量 299 项通过；报告保留输入 Run 顺序并拒绝重复 Case ID 与伪造公式。

**面试自测题**：为什么 Tool Success 要用调用级 micro 分母？零调用 Run 为什么不能直接从所有统计中删除？

### 3.31 MS-P8-008: Unified Evaluation Aggregate Report

- **任务目标**：将四个已经独立验收的评测向量组合成一个可审计总报告，同时保留每个指标原本的分母和身份边界。`[必须掌握]` `[项目特有]`
- **不能强行合并身份**：Core/Evidence 使用 `case_id`，Unsupported Claims 使用 `diagnosis_id`；二者语义不同，报告保留独立序列而不假设字符串相等。`[面试高频]`
- **子指标分母不可偷换**：Evidence Precision 平均有定义 Case，Coverage 按 Case，Unsupported Claim 使用 Claim-micro，Tool Operational 直接复用调用级/Run 级聚合。统一报告只是组合，不应为了“一个分母”破坏指标含义。`[必须掌握]`
- **组合层仍需自校验**：Evidence Case 集合必须与 Core 严格对齐，Operational Run 顺序必须一致，重复 diagnosis ID、缺失 Case、伪造派生率都 Fail Closed。`[建议掌握]`
- **验证事实**：Unified Evaluation 专项 3 项、后端全量 302 项通过；无网络、数据库、Runtime 或 Ground Truth I/O。

**面试自测题**：为什么一个总评测报告不能简单把所有子指标平均成一个分数？为什么 Unsupported Claim 的身份不能直接复用 Case ID？

### 3.32 MS-P8-009: Hermetic Evaluation Runner Contract

- **任务目标**：把 Case、已观测 Run Outcome、可选 DiagnosisComposition 和四类既有评分器组合为一个确定性、可审计的 Hermetic Runner。`[必须掌握]` `[项目特有]`
- **失败 Run 不能从评测分母消失**：Runtime Failure、Budget Exhaustion 和 Tool Failure 即使没有 Diagnosis，也必须生成明确的零 Core/Coverage 结果并进入 Operational 聚合；否则只统计成功 Run 会产生幸存者偏差。`[面试高频]`
- **缺失 Diagnosis 不等于伪造失败 Diagnosis**：Runner 为失败 Run 生成评分占位结果，但不会构造不存在的 Diagnosis；Unsupported Claim Score 在无 Composition 时保持 `None`。`[建议掌握]`
- **状态必须跨对象一致**：Outcome 描述运行层结果，Diagnosis 描述领域终止状态。`completed` 不能携带 `budget_exhausted` 或 `tool_failure` Diagnosis；Budget/Tool Outcome 如携带 Composition，状态必须精确匹配。`[必须掌握]`
- **Hermetic 边界**：Runner 接收已经物化的对象，不加载 Ground Truth 文件、不调用 Agent SDK、不访问数据库、网络或文件系统，因此评分编排可以稳定、快速、可重复地测试。`[面试高频]`
- **验证事实**：Evaluation Runner 专项 9 项、后端全量 311 项通过；两个新增反例覆盖 `completed + budget_exhausted` 与 `completed + tool_failure`。

**面试自测题**：为什么失败 Run 仍必须进入准确率和调用统计分母？为什么 Outcome 与 Diagnosis 需要各自建模并做跨对象状态校验？

### 3.33 MS-P8-010: Evaluation Manifest 与 Reproducibility Contract

- **任务目标**：把模型、完整 Prompt、Metric Config Version、Dataset Version 和逐 Case 运行次数固定为不可变评测元数据，使报告结果具备最小可复现上下文。`[必须掌握]` `[项目特有]`
- **为什么记录完整 Prompt**：只记录“prompt-v1”无法独立确认实际指令内容；Manifest 保留完整 Prompt 且不做 `strip()`，避免无意改变可复现输入。`[面试高频]`
- **运行次数必须按 Case 记录**：只记录总运行次数无法判断不同 Case 是否获得相同采样机会，可能隐藏评测权重偏差；`run_counts_by_case` 保留逐 Case 次数，并派生总数。`[建议掌握]`
- **Manifest 不负责发现环境**：它不读取配置文件、环境变量、Git、网络或数据库，只保存调用方已确认的事实。这样避免元数据模型偷偷变成部署探测器。`[项目特有]`
- **当前边界**：Manifest 已能表达一个 Case 多次运行，但现有 Runner 仍以 Case ID 唯一；多 Run Identity 与聚合需要后续单独处理，不能用伪造 Case ID 绕过。`[必须掌握]`
- **验证事实**：Evaluation Manifest 专项 10 项、后端全量 321 项通过；API 探针确认构造字段精确、Prompt 原样保留、UTC 和总运行次数派生正确。

**面试自测题**：为什么评测报告必须记录 Prompt 和 Dataset Version？为什么不能只记录总运行次数？

### 3.34 MS-P8-011: Evaluation Run Identity 与 Manifest Reconciliation Contract

- **任务目标**：为每次 Evaluation Run 建立独立、确定的 `run_id` 身份契约，并建立不可变 `ManifestEvaluationRunSet` 模型，验证实际执行记录与 `EvaluationManifest.run_counts_by_case` 严格对账。`[必须掌握]` `[项目特有]`
- **Case Identity vs Run Identity**：
  - **Case Identity (`case_id`)**：描述评测场景本身、业务上下文与 Ground Truth 预期。
  - **Run Identity (`run_id`)**：描述对某个 Case 的一次具体、独立执行（一次采样）。
  - 一个 Case 可以多次执行（如 `case-001` 下有 `run-001`, `run-002`, `run-003`），以评估 LLM 随机性下的稳定性和方差。`[必须掌握]` `[面试高频]`
- **为什么不能伪造或隐式推导 Run ID**：
  - 不能将 `run_id` 塞进 `case_id`（如 `case-001#run-001`），否则会污染 Ground Truth 匹配逻辑；
  - 不能使用列表索引，因为重排序或过滤会导致身份错乱；
  - 不能在模型内自动生成随机 UUID 或时间戳，否则破坏 Hermetic 评测的确定性与可复现性；`run_id` 必须由调用方显式提供且非空规范化。`[必须掌握]`
- **Manifest 与 Run 集合严格对账**：
  - `ManifestEvaluationRunSet` 在初始化时执行 Fail-Closed 校验：
    1. 整个集合内所有规范化后的 `run_id` 必须全局唯一；
    2. 实际 Case 集合必须与 `manifest.run_counts_by_case` 声明集合完全一致（无多余、无遗漏）；
    3. 每个 Case 的实际运行次数必须与 Manifest 声明精确相等（多一次、少一次均失败）；
    4. `actual_run_counts_by_case` 自动推导并保存为只读 `MappingProxyType`，保持 Manifest 声明顺序。`[必须掌握]`
- **为什么本轮不直接修改全部评分聚合模型**：
  - 保持单一职责与 Minimal Diff 原则：先建立可靠的身份与计数对账边界，保持现有单次 Pass Runner（`run_hermetic_evaluation`）仅处理无重复 Case 的 Pass；
  - 避免一次性修改所有聚合器导致现有 Core、Evidence、Operational 评分公式发生非预期语义漂移。`[建议掌握]`
- **验证事实**：Run Set 专项 16 项、Runner 专项 11 项、全量 338 项测试通过；无外部 I/O。

**面试自测题**：在评估非确定性 LLM Agent 时，为什么要区分 Case Identity 与 Run Identity？为什么不能用随机 UUID 隐式生成 Run ID？

### 3.35 2026-09-11 MVP Acceptance Hardening Batch

- **实现完成不等于真实模型验收** `[必须掌握]` `[面试高频]`：438 项 Hermetic 测试、前端 lint/build 和 10 Case 离线评测证明代码契约与评测管道可靠；它们不能替代真实 Provider + PostgreSQL 的三场景运行。当前 `MS-P6-004` 已执行，但 Provider 模型未满足严格 Driver / Evidence / Scope 合同，准确状态是 Executed — FAIL。
- **Driver-at-Scope 必须由同一证据支撑** `[必须掌握]`：不能把全局 Driver Evidence 与另一个 Segment Evidence 拼接成“该 Driver 导致该 Scope”的结论。同一条 anomalous supporting Evidence 必须同时匹配 primary driver 并覆盖完整 affected scope。
- **模型自由度应位于调查动作选择** `[必须掌握]`：Agent 可调用 `get_metric_definition`、`query_metric`、`query_related_metrics`，由 Semantic Layer 提供事实；生产 Prompt 不写死 Canonical 下钻序列。
- **SDK Trace 与业务侧录不同** `[建议掌握]`：`InvestigationRunSummary.tool_trace` 从 SDK Tool Call 原始参数与时序派生，适合证明模型实际选择了什么。API 已完成接入，不再把 `query_related_metrics` 的内部 `query_metric` 复用记录成模型主动选择。
- **Fixture Preview 不是 Agent** `[必须掌握]`：Fixture 是不读取所选场景 Ground Truth 的通用确定性 UI 样例，只验证 UI 和数据契约；Live 模式才可用于证明 Agent Authenticity。场景列表也不得把 expected driver/scope/status 暴露给前端。
- **Core 中立不等于现在建设多行业框架** `[项目特有]`：Registry 已去掉固定五指标和单位白名单，但 Stage 1 YAML、Warehouse、Benchmark 仍只支持 Amazon Profile。没有引入 Domain Plugin、Factory 或 SaaS Adapter。
- **凭据进入聊天或日志即视为泄露** `[必须掌握]`：示例配置只能使用占位符；任何暴露过的 Key 必须撤销并轮换，真实 `.env` 永不提交。
- **历史快照说明**：本节记录当时的 438/438 测试与尚未完成的 Live Gate，已被后续 3.39–3.43 的真实验收结果取代。当前权威状态以 `docs/agent-state.md`、任务书及 `docs/evaluation-artifacts/` 为准。

**面试自测题**：为什么 438 项测试全部通过仍不能证明 Agent 会自主调查？为什么 API Tool Trace 应优先来自 SDK Runner，而不是业务工具 wrapper？

### 3.36 2026-09-12 Live Provider Reality Check

- **真实调用事实** `[必须掌握]`：兼容 Provider 已收到 Synthetic Benchmark 调查请求，模型实际完成多次 Tool 选择与 Analytics 查询；因此当前问题不再是“没有执行 Live Run”。
- **领域时间契约必须进入 Tool 可见接口** `[面试高频]`：模型曾把 Current Period 扩展成多日范围。Runtime Prompt 与 Tool 文档随后明确 `start_date == end_date`，Baseline 只由 `compare_to=previous_7_days` 生成，避免模型把比较窗口误当当前窗口。
- **表示归一化不能变成容错造证据** `[必须掌握]`：模型把已选择 Observation ID 填入 Evidence ID 字段时，系统只在它能唯一对应一条 Selection 时做确定性转换；未知或歧义引用仍由 Resolver 拒绝。这里修复的是等价表示，不是猜测模型意图。
- **最终失败证明 Fail-Closed 边界有效** `[面试高频]`：最新 Canonical Run 引用了本次 Tool Output 中不存在的 Observation ID。系统没有补造 Observation、没有降低校验、没有输出 Diagnosis PASS artifact，而是终止验收并恢复 canonical 数据库状态。
- **结论**：MVP 实现与测试基线成立，但选定模型尚未证明能稳定遵循 Evidence/Observation 引用契约。恢复时应优先改善结构化引用遵循度或评估更合适的模型，不应削弱 Evidence Integrity。

### 3.37 2026-09-21 Driver-at-Scope Live Hardening

- **当前事实** `[必须掌握]`：兼容 Provider 仅返回 grok-4.5 与 grok-4.6。两者都实际运行过 Canonical，数据库每次均恢复，且失败不会产生 PASS artifact。
- **模型输出不等于领域结论** `[面试高频]`：grok-4.6 曾把 marketplace 这样的维度写入 primary_driver；grok-4.5 能查到 Related Metrics，但会把 target metric 视为 Driver 或在没有 Scope 的情况下结束。JSON 形状有效不表示业务引用关系有效。
- **新增的可追溯性合同** `[必须掌握]`：Runtime Intent 增加 driver_evidence_id，使模型显式指出哪条 Evidence 同时支撑 Driver 与完整 Scope；查询 Tool Output 同时携带通用证据协议。未知引用、跨 Evidence 拼接、空 no-anomaly 仍由领域层 Fail-Closed。
- **未被采纳的错误修复**：没有把最近的 Observation 自动当 Driver Evidence，没有把多条 Evidence 合成为虚拟证据，也没有为通过 Demo 放宽 builder.py 的联合支撑规则。
- **结论**：下一步不是继续堆 Prompt，而是获取能稳定支持 Tool Calling 与 JSON Schema 的 Provider，或通过独立 ADR 决定把领域校验错误作为受控 final-submit Tool 的反馈，让 SDK Runtime 自己 replan。

---

### 3.38 2026-09-22 Driver Semantic Graph：中间指标不能替代最终解释

- **问题**：`dependencies` 描述公式输入，`related_metrics` 描述可比较候选；两者都不能表达“Orders 还应由 Sessions / Conversion Rate 继续解释”。因此真实 Agent 虽已查到 Conversion Rate 异常，仍可能合法地把 Orders 当作最终 Driver。
- **最小修正**：语义层新增 `driver_metrics`，并在成功 Diagnosis 前校验直接 Driver 已观察且没有异常。该校验只拒绝未闭环的最终声明，绝不决定下一次调用哪个 Tool，也不把 Canonical 的维度路径写进 Runtime。
- **工具信息密度**：受控 query 工具返回本次涉及指标的受控定义，避免模型为了获取已知语义额外浪费预算；这不读取 Ground Truth，也不放宽 SQL 或指标定义边界。
- **历史验证边界**：当时 445 项后端单测通过，真实 Provider 尚待完整三场景 artifact 验收；该待办已在后续 3.39–3.43 完成。

### 3.39 2026-09-22 Gemini Live Gate 与全量 Benchmark 事实

- Gemini `gemini-3.8-flash-high` 在兼容 Chat Completions Provider 上通过真实 PostgreSQL 三场景验收：Canonical 定位 Conversion Rate / US / ASIN-A / Ads，Traffic 定位 Sessions / US / ASIN-A / Ads，No-anomaly 正确停止；所有关键 Evidence 都能追溯到同一运行的 Tool Observation。
- 同一模型随后完成 10 Case、每 Case 1 次的 Live Evaluation；结果为完成率 80%，Macro Driver / Scope / Exact 各 40%。这说明三场景 Gate 证明核心链可工作，但绝不等价于模型在完整受控 Benchmark 上可靠。
- **数据有效性复核**：6 个被 Ground Truth 标为 `diagnosed` 的替代场景，其全局 Sales 实测仅下降 1.75%–4.39%，落在 Phase 0 `<5%` 的正常区间；固定 Prompt 却要求调查全局 Sales anomaly。此时模型给出 no-material-anomaly 不应自动计为模型错误。
- **工程原则**：下一步不能把 Case Ground Truth 或 Canonical 路径写入 Prompt，也不能悄悄降低生产异常阈值刷分。必须先让 Benchmark 的 Trigger、注入数据与 Ground Truth 一致：要么让目标分群具备足够的全局贡献，要么明确改为 segment-level Trigger，并在作出产品选择后重跑。

### 3.40 2026-09-22 Benchmark Trigger 校准与真实复验

- **选择**：保留产品入口“调查全局 Sales 异常”，不新增 segment-level Trigger。于是只校准 Synthetic Benchmark：提高被测目标分群的基线贡献，并将替代 Case 的异常幅度提高至足以让全局 Sales 下降约 10%；normal / distractor Case 保持 `<5%`。
- **证明链**：内存注入计算、真实 PostgreSQL 逐场景查询均验证 8 个诊断 Case 为材料性下降；校准后的 Gemini 10 Case × 1 次真实评测得到 100% Completion / Driver / Scope / Exact Match。该结果应描述为当前受控 Synthetic Benchmark 上的一次真实运行，不应扩大为现实世界准确率声明。
- **稳定性边界**：30 次重复评测在第 27 次后没有 stderr 即终止，也没有生成最终 artifact，不能选择性拿前 27 次宣称稳定性。Warehouse 已显式恢复至 canonical。后续应做 checkpoint，而不是重复扩大 Prompt 或评测作弊。

### 3.41 2026-09-22 Live Evaluation 逐 Run Checkpoint

- **问题**：重复 Live Evaluation 只有在全部完成时才导出聚合报告；一次外部 Provider 长运行在 27/30 后中断，已完成的真实运行没有独立 artifact。
- **最小修正**：Runner 在每个 Run 结束后以临时文件加原子替换写入 checkpoint。内容限定为 Run 身份、操作结果、结构化 Diagnosis 与 Evidence ID；不保存 Tool 原始值、Provider 文本、数据库 URL 或任何凭据。
- **边界**：checkpoint 只改善中断后的审计与恢复，不参与 Agent 决策、不改变 Prompt、阈值、Ground Truth 或评分公式，也不把未完成的重复评测包装为稳定性结论。
- **验证事实**：新增 2 项专项测试覆盖逐 Run 最新记录写入和脱敏字段边界；后端全量 447 项通过。

### 3.42 2026-09-22 模型选择对账与 30 Run 真实稳定性结果

- **配置事实**：Benchmark CLI 曾保留历史默认 `gpt-4o-mini`，没有继承 `METRICSLEUTH_AGENT_MODEL`；在 Gemini-only Provider 上会导致 `BadRequestError`，这不是模型推理质量结论。现改为显式 CLI 参数优先、环境变量其次、历史默认最后，并把解析后的模型写入 Manifest。
- **真实结果**：显式 `gemini-3.8-flash-high` 的 10 Case × 3 次评测全部运行结束，30 条 checkpoint record 与最终聚合报告均生成；28/30 成功，Completion / Macro Driver / Scope / Exact 均为 93.33%。
- **失败语义**：两个失败是 `DiagnosisValidationError`，并非 Provider、数据库、工具预算或 Trace 失败。它表示领域边界没有为了刷分放行不完整结论；同时也说明该模型在两个替代场景中尚未达到完全稳定。
- **验证事实**：模型优先级新增专项测试，后端全量 448 项通过。

### 3.43 2026-09-22 低频 Diagnosis 拒绝的可审计化

- **问题**：30 次真实评测中有两次 `DiagnosisValidationError`，原 artifact 只保存异常类型，无法区分模型最终 Intent 的引用缺口和任意其他运行时问题。
- **最小修正**：保留 Runtime 已附加的 reference-only intent note；它只含 status、primary driver、scope 与 Evidence/Observation ID，不接受任意异常正文，因此不会把 Provider 原文、Tool 值、数据库连接或凭据写进 checkpoint。
- **复现事实**：两个失败 Case 各运行 3 次均成功（6/6），所以失败暂时是低频波动而非 Case 或数据注入的确定性缺陷。正确措施是保留可审计失败边界、等待新的具体 artifact；不在无证据时加入自动重试或把校验退化为 Prompt 规则。
- **验证事实**：专项测试新增安全 note 白名单，后端全量 449 项通过。

### 3.44 2026-09-22 Product API 与 Evaluation Ground Truth 隔离

- **问题**：产品 API 曾直接加载 `benchmark_cases.json`，虽然场景列表不返回标签，但 Fixture Preview 会根据 Case 的 status、driver 和 scope 回放答案。这会让“演示模式”在内部持有评测答案，破坏 Ground Truth 仅用于 Evaluation 的边界。
- **最小修正**：新增只含 `scenario_id` 与 `target_metric` 的 `warehouse/scenario_catalog.json`。API 只从该目录校验场景和触发注入；Fixture Preview 改为明确标注的通用 UI 样例，所选场景只作为选择器回显，不能改变诊断、轨迹或证据内容。Live Runtime 的 Agent、Tool、Observation、Evidence、Diagnosis 链路不变。
- **为什么重要** `[必须掌握]`：不向前端返回标签还不够；只要产品服务能读取并使用 Ground Truth，就可能在 Mock、日志或未来代码中意外泄漏。评测真值应留在 Evaluation 边界，产品只拥有运行时所需的最小元数据。
- **验证事实**：API 专项与后端全量 448 项测试通过；回归测试同时检查 API 源码不导入 Ground Truth Loader/类型，且两个不同场景的 Fixture Preview 不会返回不同 Benchmark 答案。前端 lint/build 通过。

### 3.45 2026-09-22 Olist 真实公开数据 Source Profiling

- **目标**：验证 MetricSleuth 的核心边界能否面对真实订单数据，而不是把 Olist 强行改造成 Amazon 漏斗数据。
- **事实**：本地 Olist 原始数据包含 99,441 笔订单、112,650 条订单明细，订单购买时间覆盖 2016-09-04 至 2018-10-17。订单→客户、明细→订单、明细→商品/卖家的关联缺失均为 0；但存在 775 笔无订单明细订单和 1 笔无支付订单，必须作为真实数据质量事实保留。
- **可用与不可用** `[必须掌握]`：`SUM(order_items.price)`（排除 freight）可作为明确命名的 Merchandise GMV 候选，Orders 和聚合 AOV 可计算；Customer/Seller State、Product Category 可切片。Sessions、Conversion Rate、Marketplace、Traffic Source、ASIN 没有来源字段，必须返回 unavailable/不支持，不能用代理字段冒充测量值。
- **边界**：这一阶段只添加标准库只读 Profiling 脚本与映射文档。原始下载目录 git-ignore；不导入现有 Warehouse，不改 Agent Runtime、Semantic Layer 或 Ground Truth。
- **验证事实**：两项专项测试覆盖完整最小源与缺失文件 fail-closed；真实 Olist 下载已生成脱敏聚合 profile。当前后端全量基线为 450 项测试。

## 4. 面试高频问题与项目化回答

### Q1: 什么是 Metric Semantic Layer（指标语义层）？它在 MetricSleuth 中起什么作用？ `[面试高频]`
> **回答要点**：
> 指标语义层是连接底层物理数据表与上层分析/Agent 应用的统一业务定义抽象。在 MetricSleuth 中，它通过 `configs/metrics.yaml` 和 `MetricRegistry` 将指标名称、聚合公式、依赖关系和维度约束标准化为不可变对象，确保后续 Phase 3 的 Analytics Tools 和 Agent Runtime 拥有唯一的指标计算口径真理源，彻底消除在 SQL 或工具代码中硬编码计算公式的混乱。

### Q2: 为什么转化率（Conversion Rate）等比率指标不能在 SQL 中直接做 `AVG(conversion_rate)`？ `[面试高频]`
> **回答要点**：
> 1. **数学非线性性**：比率指标的平均值不等于总量的比率，直接平均会导致“辛普森悖论”，小流量异常样本会过度拉偏整体结果。
> 2. **零分母风险**：当分母（Sessions）为 0 时，行级比率无法定义；而汇总后再除，可以通过 `NULLIF(SUM(sessions), 0)` 优雅处理并标记为 `unavailable`。
> 3. **正确做法**：必须坚持“先汇总再做除法”（$\sum \text{Orders} / \sum \text{Sessions}$）。

### Q3: 为什么在配置解析中必须坚持 Fail-Fast 原则并封装自定义领域异常？ `[面试高频]`
> **回答要点**：
> 1. **稳定性与可观测性**：如果非法配置（如嵌套列表 `[[]]`）导致内部泄漏 `TypeError: unhashable type`，外部调用者将无法判断是代码 Bug 还是配置文件错误。
> 2. **精确拦截**：在 `from_yaml` 构建期对类型、空值、自引用及非法依赖进行全面检查，统一转换为 `MetricConfigError`，确保系统启动即发现配置缺陷，防止错误蔓延到运行时工具调用中。

### Q4: 为什么在 Python 中使用 `dataclass(frozen=True)` 还需要显式将 `list` 转换为 `tuple`，将 `dict` 包装为 `MappingProxyType`？ `[面试高频]`
> **回答要点**：
> `dataclass(frozen=True)` 只重载了类的属性赋值行为（即 `instance.attr = ...` 会抛出 `FrozenInstanceError`），但并不会自动递归冻结属性所引用的对象。如果属性是普通 `list` 或 `dict`，调用方依然可以通过 `instance.attr.append()` 或 `instance.attr[k] = v` 原地修改其内部内容。因此，对于序列必须转换为不可变类型 `tuple`，对于字典必须在 `__post_init__` 中执行防御性拷贝并封装为 `types.MappingProxyType`，实现真正的运行时深层不可变。

### Q5: 为什么加载 YAML 时推荐使用 `yaml.safe_load()`？使用它有哪些安全考量？ `[面试高频]`
> **回答要点**：
> 1. **反序列化防护**：`yaml.safe_load()` 仅构造标准 YAML/JSON 基础标量与集合类型；如果使用 `UnsafeLoader` 等不安全 Loader 解析不可信 YAML，可能通过对象反序列化标签实例化恶意 Python 对象并导致任意代码执行。现代 PyYAML 已强制要求显式指定 Loader。
> 2. **当前实现边界**：当前实现使用 `yaml.safe_load()` 降低任意 Python 对象构造风险，并由 `MetricRegistry` 执行结构和业务契约校验。当前没有实现解析阶段的文件大小、嵌套深度或资源预算限制，因此该加载入口只用于仓库内受信任且经过代码审查的配置，不应直接暴露为任意不可信 YAML 上传接口。

### Q6: 配置驱动设计有哪些优点和代价？MetricSleuth 如何控制这些代价？ `[面试高频]`
> **回答要点**：
> 1. **优点**：形成单一真理源（Single Source of Truth），指标口径与公式集中管理，业务调整无需重构代码，便于跨端协作和版本审计。
> 2. **代价**：YAML 缺乏编译期静态类型，拼写与引用错误只能延后到运行时校验；若过度设计容易演化成难以维护的复杂 DSL。
> 3. **MetricSleuth 的控制策略**：在 `MetricRegistry` 中构建全面的 fail-fast 校验守卫直接拦截类型和引用错误；业务上严格固化 5 个核心指标，坚决不引入通用表达式引擎或动态插件，在享受解耦红利的同时保持架构极简。

### Q7: 为什么在构造动态 SQL 时，表名/列名必须使用 `psycopg.sql.Identifier`，而过滤值使用参数绑定？ `[面试高频]`
> **回答要点**：
> 1. **SQL 语法的不同部位限制**：SQL 协议中的参数化占位符（`$1` / `%s`）只允许替代**数据字面量**（Data Literals），不允许用于表名、列名等**模式标识符**（Schema Identifiers）。
> 2. **防御两类不同漏洞**：
>    - 数据值通过参数绑定传输，数据库驱动会严格将其当作常量处理，彻底避免 `' OR 1=1 --` 等字符串逃逸注入；
>    - 动态维度的列名和表名无法通过占位符传参，必须先经过白名单校验（如 `MetricRegistry.dimensions`），再通过 `psycopg.sql.Identifier` 进行安全引号包裹转义，双重防护杜绝标识符注入。

### Q8: 电商指标分析中，计算环比变化（Relative Change）时如何处理零分母与小样本问题？ `[面试高频]`
> **回答要点**：
> 1. **小样本防护（`insufficient_data`）**：当分群样本规模（如基准期日均 Sessions）低于安全统计阈值（$\ge 30$）时，指标波动往往受到极端随机性干扰。系统前置判定并标记为 `insufficient_data`，将 `relative_change` 设为 `None`，防止分析师或 Agent 陷入“1 个转化到 0 转化导致跌幅 100%”的虚假异常陷阱；
> 2. **零分母与不可比防护（`unavailable`）**：当基准值为 0 或比率分母为 0 时，数学除法无意义。系统显式将状态置为 `unavailable` 并将 `relative_change` 设为 `None`，严禁使用 `0` 代替不可计算状态，避免业务误判为“无波动”。

### Q9: 为什么在电商指标异常排查中，分群下钻必须依据“转化订单缺口贡献（Shortfall Contribution）”而不是直接按“转化率相对跌幅”排序？ `[面试高频]`
> **回答要点**：
> 1. **避免小样本高百分比波动的“小样本陷阱”**：小流量分群（例如 2 访问 1 订单跌到 0 订单）跌幅为 100%，但实际仅损失 1 单；主力分群（例如 1000 访问 100 订单跌到 50 订单）跌幅为 50%，实际损失 50 单。按百分比排序会错误将小流量分群识别为主因；
> 2. **业务价值对齐**：使用预期订单减去实际订单（$\text{Sessions}_{\text{curr}} \times \text{CR}_{\text{base}} - \text{Orders}_{\text{curr}}$）计算绝对订单损失量，并计算其在总正向缺口中的占比（$\ge 50\%$），能够精准定位对整体销售额损失负责的核心受损分群。

### Q10: 为什么不能仅依靠只读数据库账号（Readonly User）来保障 Agent 的 SQL 安全？为什么还需要 AST Guard？ `[面试高频]`
> **回答要点**：
> 只读账号仅能阻止写入和修改数据（DML/DDL），但无法阻止：
> 1. **大查询内存打爆 (OOM)**：无 `LIMIT` 的查询拉取千万行数据拖垮应用服务与网络；
> 2. **高危慢函数 DoS 攻击**：调用 `pg_sleep()`、复杂正则表达式或高消耗系统函数拖死数据库连接池；
> 3. **行锁竞争**：执行 `SELECT ... FOR UPDATE` 锁住核心业务行导致其他业务事务超时；
> 4. **元数据敏感泄露**：查询 `pg_catalog.pg_user` 或跨 schema 嗅探未经授权的应用数据表。
> AST Guard 在应用层进行前置静态语法审计与拦截，与只读账号结合构成纵深防御体系。

### Q11: 为什么 AST Guard 必须强制校验表名必须包含 Schema（如 `warehouse.dim_products`）且禁止 3-part 名称？ `[面试高频]`
> **回答要点**：
> 1. **消除 `search_path` 歧义与劫持**：未显式限定 schema 的表名（如 `dim_products`）完全依赖数据库 session 当前的 `search_path` 解析。攻击者或意外配置可能导致查询解析到未预期的 `public` 或临时 schema 中的同名表；
> 2. **约束数据边界**：强制限定 `schema.table` 并结合显式白名单，确保查询永远严格锁定在受控的分析数仓范围内；禁止 3-part 名称（`database.schema.table`）避免跨数据库未受控访问。

### Q12: 为什么在 PostgreSQL 中，只读事务模式（Read-Only Transaction）不能替代物理对象权限？ `[面试高频]`
> **回答要点**：
> 1. **会话级参数易被重置**：`default_transaction_read_only` / `transaction_read_only` 只是会话级配置变量（GUC），普通客户端连接后随时可以通过 `SET default_transaction_read_only = off` 覆盖；
> 2. **权限硬边界不可逾越**：真正的安全边界是物理对象权限（Object Privileges）。当该角色在表上没有 `INSERT`/`UPDATE`/`DELETE` 权限时，即使客户端显式关闭了只读事务模式，写操作仍会被 PostgreSQL 内核以 SQLSTATE 42501（`insufficient_privilege`）强力拒绝。

### Q13: MetricSleuth 的 SQL 执行纵深防御体系是如何构建的？ `[面试高频]`
> **回答要点**：
> 体系由三层独立防线构成：
> 1. **第一层：应用层静态 AST Guard**（拦截 DML/DDL、拒绝 schema-qualified 函数/自定义运算符/高危慢函数、强制注入 LIMIT 1000）；
> 2. **第二层：数据库层物理权限硬隔离**（只读角色 `metricsleuth_readonly` 仅有 2 张表的 SELECT 权限，关闭只读仍报 42501）；
> 3. **第三层：执行时耗与事务预算兜底**（数据库端配置 1000ms `statement_timeout` 自动取消慢查询，结合会话默认只读事务 25006）。

### Q14: 在构建生产级 LLM Agent 时，自建 Agent Loop (while loop) 与采用官方 SDK Runner（如 OpenAI Agents SDK）有哪些架构权衡？ `[面试高频]`
> **回答要点**：
> 1. **自建 Loop 的代价**：自建 `while` 循环看似轻量，但在生产环境下很快会面临会话状态机管理、并发工具调用调度、工具异常/超时结构化回传模型、上下文截断与压缩、以及跨轮中断恢复（Handoff/Approval）等复杂工程问题，极易出现死循环或上下文污染；
> 2. **官方 SDK Runner 的优势**：官方 `Runner` 将多轮调用（Reason $\rightarrow$ Tool Call $\rightarrow$ Tool Output $\rightarrow$ Final Output）标准化为健壮的状态机，原生支持 Pydantic 强类型结构化输出、Guardrails 熔断护栏与详细的 RunItem Trace 审计，让业务层能够专注于指标分析工具的设计与领域逻辑收敛。

### Q15: 为什么 Agent 系统的结构化输出（Structured Output）必须依赖框架级 Schema 约束与模型受控解码，而不能依赖 Prompt 要求模型输出 JSON 字符串并用正则解析？ `[面试高频]`
> **回答要点**：
> 1. **确定性与无幻觉保证**：通过 Prompt 要求 JSON 字符串存在非零概率的输出格式漂移（如 Markdown 代码块包裹、尾部多余文本、Key 缺失或类型错误），正则表达式解析脆弱且容易在下游引发运行时崩溃；
> 2. **受控解码（Constrained Decoding）**：OpenAI 官方 Structured Outputs 机制在底层将 Pydantic 生成的 JSON Schema 转换为模型采样时的状态约束（Grammar-based / Masked Sampling），确保模型生成的每一个 Token 100% 严格符合 Schema 定义，从源头杜绝非预期格式。

### Q16: 在评估非确定性 LLM Agent 时，为什么要区分 Case Identity 与 Run Identity？如何通过 Manifest Reconciliation 确保评测的科学性与可复现性？ `[面试高频]`
> **回答要点**：
> 1. **两类身份的本质区别**：Case Identity（`case_id`）定义静态评测场景、输入数据特征与预期 Ground Truth 答案；Run Identity（`run_id`）定义对该场景的一次具体执行采样。大模型的非确定性要求同一 Case 执行多次以统计方差与稳定性。
> 2. **身份隔离与防止污染**：禁止将 `run_id` 拼接进 `case_id`（如 `case-001#run-001`），避免污染 Ground Truth 的匹配与索引；禁止隐式使用随机 UUID 或时间戳，确保评测输入纯净且受调用方完全控制。
> 3. **Manifest 对账机制**：通过不可变的 `ManifestEvaluationRunSet` 对执行记录执行 Fail-Closed 校验，确保所有 `run_id` 唯一、实际 Case 集合与 Manifest 声明严格相等、每个 Case 的执行次数精确匹配，从源头杜绝漏跑、多跑或未声明 Case 导致的虚假指标评估。

---

## 5. 下班后复习清单

1. [ ] **概念复习（5 min）**：
   - 复述只读事务（25006）与对象权限（42501）的区别，以及三层纵深防御体系。
2. [ ] **代码走读（10 min）**：
   - 阅读 `warehouse/setup_readonly_role.sql` 与 `warehouse/verify_readonly_role.py`，理解幂等配置与端到端验证逻辑。
3. [ ] **测试验证（5 min）**：
   - 在 PowerShell 运行 `Push-Location backend; python -B -m unittest discover -s tests -p "test_*.py" -v; Pop-Location`，确认当前 338 项单元测试通过。
   - 在 WSL 执行 `python3 warehouse/verify_readonly_role.py`，确认只读角色集成测试通过。
4. [ ] **安全与架构复习（5 min）**：
   - 复述为什么必须显式单表 GRANT，以及为什么凭据必须通过环境变量安全注入。

---

## 6. 自测问题

1. **自测问题 1**：如果客户端连接后执行了 `SET default_transaction_read_only = off`，尝试 `UPDATE warehouse.dim_products` 会发生什么？返回什么 SQLSTATE？
2. **自测问题 2**：若在 `metricsleuth_readonly` 连接中执行耗时 5 秒的只读慢查询，数据库会如何处理？返回什么 SQLSTATE？
3. **自测问题 3**：为什么 `warehouse/setup_readonly_role.sql` 不给只读角色配置 `GRANT SELECT ON ALL TABLES IN SCHEMA warehouse`？
4. **自测问题 4**：为什么 `warehouse/setup_readonly_role.sql` 和 `warehouse/verify_readonly_role.py` 必须从环境变量读取密码和 URL？
5. **自测问题 5**：为什么 `ALTER ROLE ... IN DATABASE ... SET ...` 只是新会话默认值，未来 Executor 每次执行时仍需显式强制？
