# MetricSleuth Agent 接管与运行指南

## 1. 建议阅读顺序

接管或进入本项目的 Agent 必须按以下顺序查阅上下文：

1. `AGENTS.md`（当前文件：长期稳定接管规则、架构约定与维护协议）
2. `docs/agent-state.md`（**当前唯一动态操作状态**：Phase 状态、任务矩阵、验证结果与阻塞项）
3. `任务书.md`（产品目标、技术边界与 Phase 演进基线）
4. 当前 Phase 的规格文档与关联代码
5. `docs/project-learning-log.md`（历史技术复盘、踩坑记录与设计详解）
6. `README.md`（本地运行与端到端验证操作指南）

---

## 2. 文档权威关系与动态状态来源

- **`任务书.md`**：架构方案、阶段划分和产品边界的**唯一最高权威来源**。
- **`docs/agent-state.md`**：当前执行状态、任务进展、验证结果与阻塞项的**唯一动态权威来源**。当前 Phase、任务状态、测试快照、阻塞项和下一步统一查看该文档。
- **`AGENTS.md`**：长期稳定的接管规则、仓库地图、核心不变量与维护协议。
- **`docs/project-learning-log.md`**：技术原理沉淀、踩坑复盘与面试复习资料。
- **`README.md`**：开发者本地环境配置与运行验证指南。
- **冲突处理原则**：若文档与代码发生冲突，必须以实际代码和测试运行事实为准，并显式向用户报告冲突，严禁私自静默合并或修改既定边界。

---

## 3. 产品定位与核心链路

MetricSleuth 面向电商（Amazon）经营指标异常的第一轮多维自动化排查。

- **核心链路（永远不变）**：
  ```text
  Metric → Agent → Tool → Evidence → Diagnosis
  ```
- **定位边界**：Stage 1 仅定位数据层面的异常贡献范围，**不证明**现实业务最终根因，亦不直接给出业务调整决策。
- **框架约束**：严禁自行实现通用 Agent Loop，严禁引入未授权框架（LangGraph、Multi-Agent、MCP、RAG、Redis、Kafka、微服务等）。

---

## 4. 仓库地图

- `任务书.md`：产品目标、技术边界与 Phase 顺序的唯一权威来源。
- `README.md`：开发者运行与本地端到端验证操作指南。
- `AGENTS.md`：长期稳定接管规则、仓库地图与维护协议。
- `configs/metrics.yaml`：5 个核心指标的声明式元数据与公式配置。
- `docs/agent-state.md`：项目唯一动态操作状态、任务进展、验证结果与阻塞项。
- `docs/phase-0-manual-investigation.md`：业务分析师人工下钻排查与缺口贡献计算规范。
- `docs/project-learning-log.md`：架构设计复盘、真实踩坑分析与面试知识库。
- `warehouse/`：PostgreSQL Schema、确定性 Seed、异常注入器、Ground Truth、只读角色配置（`setup_readonly_role.sql`）与权限验证脚本（`verify_readonly_role.py`）。
- `backend/app/metrics/`：只读指标模型定义与 Fail-Fast 注册表实现。
- `backend/app/analytics/`：受控 Analytics Tools 查询实现与结构化查询数据模型。
- `backend/app/sql_safety/`：纯静态 SQL AST Guard 安全验证器。
- `backend/app/observations/`：不可变 Observation 领域模型与 ToolResult 确定性转换器。
- `backend/app/evidence/`：不可变 Evidence 领域模型与显式提升契约。
- `backend/app/agent_runtime/`：OpenAI Agents SDK 官方运行时适配、本地工具封装与结构化输出。
- `backend/tests/`：标准库脚手架、语义层、分析工具、SQL Guard、Observation、Evidence 与 Runtime Spike 单元测试套件。

---

## 5. 关键不变量

1. **Ground Truth 隔离**：`warehouse/ground_truth.json` 仅用于评测评估，严禁被语义层、工具或 Agent 读取。
2. **比率聚合口径**：Conversion Rate 和 AOV 必须使用汇总分子除以汇总分母，禁止平均行级比率。
3. **零分母语义**：分母为零时语义必须为 `unavailable`，严禁转换为 `0`。
4. **因果边界隔离**：异常贡献定位不等于现实业务最终根因。
5. **阶段不可跳跃**：当前 Phase 经 Codex 验收通过前，严禁提前开始下一 Phase。
6. **架构极简约束**：不自制 Agent Loop，不引入未授权框架，不修改系统/WSL/PostgreSQL 安全配置。
7. **验收权限约束**：Gemini 严禁自行标记任务为 `Accepted`。

---

## 6. 最小验证命令

执行以下命令验证当前语义层与测试完整性：

```powershell
python -m py_compile backend/app/metrics/registry.py backend/tests/test_metric_registry.py

Push-Location backend
python -m unittest discover -s tests -p "test_*.py" -v
$testExit = $LASTEXITCODE
Pop-Location

if ($testExit -ne 0) {
    exit $testExit
}
```

> **数据库验证**：PostgreSQL Warehouse 与异常注入验证流程详见 [README.md](README.md)。

---

## 7. Git 状态与工作区说明

- 当前仓库尚无干净的新项目提交基线，开发过程遵循 Minimal Diff 原则。
- `git status` 中旧占位文件 `1` 的删除由用户确认，无需恢复。
- 每次任务必须对比任务开始与结束时的实际文件状态，严禁创建或修改未授权文件。

---

## 8. 任务结束维护协议

每次任务执行完毕后，执行 Agent 必须完成以下维护：

1. **更新动态状态**：在 `docs/agent-state.md` 中更新快照日期、当前 Task 及其 `Pending Codex Review` 状态、验证结果、阻塞项与下一步；
2. **更新学习日志**：在 `docs/project-learning-log.md` 中同步更新任务索引与技术复盘；
3. **稳定文档维护**：仅在稳定工作规则、文档权威关系、仓库核心结构或长期不变量发生变化时，才允许修改 `AGENTS.md`；
4. **严禁自行将任务或阶段标记为 `Accepted`**。
