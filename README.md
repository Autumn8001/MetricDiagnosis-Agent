# MetricSleuth

MetricSleuth 是一个 Evidence-driven 业务指标异常调查 Agent。当前 Stage 1 Domain Profile 仅实现 Amazon / 电商运营；`Sales`、`Orders`、`Sessions`、`ASIN`、`Marketplace`、`Traffic Source` 是当前验证场景，不是永久产品定义。

## 当前状态

* **当前阶段**：Stage 1 Portfolio MVP 已完成实现，处于 Stabilization / Acceptance 收尾。FastAPI 与 React Diagnosis Workspace 已落地；Hermetic 测试和构建已通过。Gemini Chat Completions Provider 已通过真实 PostgreSQL 三场景验收：Canonical=Conversion Rate、Traffic=Sessions、No-anomaly 正确停止，且均形成可追溯 Tool/Observation/Evidence/Diagnosis 链路。校准后的 10 Case 单次 Live Evaluation 达到 100% Completion / Driver / Scope / Exact Match。
* **当前范围**：
  - 基础 Python 3.12+ 脚手架与元数据（当前验证解释器：Python 3.13.5）；
  - Phase 0 人工调查契约规格（[docs/phase-0-manual-investigation.md](docs/phase-0-manual-investigation.md)）；
  - Phase 1 PostgreSQL Warehouse 架构（`warehouse.dim_products`, `warehouse.fact_daily_performance`）；
  - 确定性数据 Seed 脚本与 10 种受控 Benchmark 场景异常注入器（`warehouse/anomaly_injector.py`）；
  - 评测基准标签（[warehouse/benchmark_cases.json](warehouse/benchmark_cases.json)）；
  - Canonical Case 人工 SQL 验收脚本（[warehouse/verify_canonical.sql](warehouse/verify_canonical.sql)）；
  - Phase 2 指标语义层定义（[configs/metrics.yaml](configs/metrics.yaml)）与只读注册表（`backend/app/metrics`）；
  - Phase 3 最小 Analytics Tools 垂直切片（`backend/app/analytics`：`get_metric_definition`, `query_metric`, `query_related_metrics`）；
  - Phase 4 纯静态 SQL AST Guard 安全分析器（`backend/app/sql_safety`：`SqlGuard`, `SqlGuardError`, `ValidatedSql`）；
  - Phase 4 PostgreSQL 独立只读角色与权限验证体系（`warehouse/setup_readonly_role.sql`, `warehouse/verify_readonly_role.py`）；
  - Phase 4 ToolResult $\rightarrow$ Observation 可追溯转换基础（`backend/app/observations`：`Observation`, `ObservationStatus` 等）；
  - Phase 4 Observation $\rightarrow$ Evidence 显式提升契约（`backend/app/evidence`：`Evidence`, `EvidenceRole`, `promote_observation_to_evidence`）；
  - Phase 5 OpenAI Agents SDK Runtime Spike（`backend/app/agent_runtime`）；
  - Phase 6 Runtime Tool Bridge、官方 SDK Runner 调查契约与三场景开发验收 Harness；
  - Phase 7 Evidence-driven Diagnosis 领域基础（`backend/app/diagnosis`：`Diagnosis`, `DiagnosisStatus`, `build_diagnosis`）；
  - Phase 8 Evaluation 完备体系（10 Case Benchmark Loader、Core/Aggregate Scoring、Evidence Obligations、Citation Precision/Coverage、Hermetic & Live Evaluation Runner 与 Repeated Aggregate Dashboard）；
  - Phase 10 最小 FastAPI 后端服务层（`backend/app/api`：健康检查、指标图谱、场景注入、模拟/真实调查接口）；
  - Phase 10 React Diagnosis Workspace 前端工程（`frontend/`：React + TS + Vite + 原生 Vanilla CSS，包含拓扑图、调查轨迹流、证据链看板、结构化诊断与追问交互）；
  - 项目学习与开发日志（[docs/project-learning-log.md](docs/project-learning-log.md)）；
  - Agent 运行状态与接管指南（[docs/agent-state.md](docs/agent-state.md), [AGENTS.md](AGENTS.md)）。
* **当前权威验证（2026-09-22）**：后端 449 项单元测试通过；前端 `npm run lint` 与 `npm run build` 通过；10 Case `--hermetic` 评测通过。Hermetic 结果是 Ground-Truth-backed 离线模拟，不证明真实模型 Agent 能力。
* **演示口径**：Fixture Preview 是确定性离线预览，用于展示 UI 与数据契约，不得称为真实 Agent Run；Live 模式才用于真实 Provider 调查。
* **当前 Live 稳定性事实**：此前未校准的替代 Case 在全局 Sales 上仅下降 -1.75% 至 -4.39%，与 `<5%` 正常阈值冲突；现已通过调整 Synthetic 数据权重和注入强度校准为约 -10% 的全局影响，未降低生产阈值、未更换模型、未把 Benchmark 路径硬编码到 Runtime。校准后的 10 Case 单次 Live 结果为 100%。随后 10 Case × 3 次、显式 `gemini-3.8-flash-high` 的真实评测完整结束：28/30 成功，Completion / Macro Driver / Scope / Exact 均为 93.33%；两次 `DiagnosisValidationError` 被如实保留。Runner 每 Run 原子写入脱敏 checkpoint，保留已完成审计结果而不保存 Tool 值、Provider 原文或凭据。API 服务层直接消费 SDK Runner 产出的可信 `InvestigationRunSummary.tool_trace`。
* **明确延后**：复杂多租户/用户系统、Go Gateway、大规模云端多 Agent 编排。
* **开发约束与文档**：
  - 后续所有开发工作必须严格遵守 [任务书.md](任务书.md)；
  - 面向展示的当前能力与边界参见 [docs/mvp-demo-brief.md](docs/mvp-demo-brief.md)，真实模型评测的脱敏验收摘要参见 [docs/evaluation-artifacts/live-evaluation-2026-09-22.md](docs/evaluation-artifacts/live-evaluation-2026-09-22.md)；
  - `warehouse/ground_truth.json` 仅供评测评估（Evaluation Runner）使用，**严禁**暴露给未来的 Agent Runtime 或查询工具；
  - 详细的设计决策、历史踩坑复盘与知识总结参见 [docs/project-learning-log.md](docs/project-learning-log.md)。

## 验证指南

### 1. 单元测试套件全量验证 (无需启动数据库)

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

### 2. Phase 2 Metric Semantic Layer 验证

无需数据库连接即可验证指标语义注册表：

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path

python -c "
from pathlib import Path
from app.metrics import MetricRegistry

registry = MetricRegistry.from_yaml(Path('configs/metrics.yaml'))

assert [m.metric_id for m in registry.list_metrics()] == [
    'sales',
    'orders',
    'sessions',
    'conversion_rate',
    'aov',
]

sales = registry.get('sales')
assert sales.unit == 'usd'
assert [m.metric_id for m in registry.get_related_metrics('sales')] == [
    'orders',
    'sessions',
    'conversion_rate',
    'aov',
]

cr = registry.get('conversion_rate')
assert [m.metric_id for m in registry.get_dependencies('conversion_rate')] == [
    'orders',
    'sessions',
]

aov = registry.get('aov')
assert [m.metric_id for m in registry.get_dependencies('aov')] == [
    'sales',
    'orders',
]

print('Metric Semantic Layer verification: PASS')
"
```

### 3. Phase 1 数据底座验证

当前已验证的本地运行环境为 **WSL Ubuntu 24.04** 中的 **PostgreSQL 16**（监听 WSL 本地 `127.0.0.1:5432`）。

> **说明**：以下连接串 `postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth` 仅为本地 Synthetic Benchmark 开发环境示例，不得用于生产环境。

#### 3.1 完整数据初始化与 Canonical Case 验收流程

在 Windows PowerShell 终端中，可直接从仓库根目录复制执行以下命令进行完整初始化与 SQL 验收：

```powershell
wsl -d Ubuntu --cd "$((Get-Location).Path)" -- bash -c "
export DATABASE_URL='postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'
python3 warehouse/seed.py --reset
python3 warehouse/anomaly_injector.py --scenario canonical
psql 'postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth' -v ON_ERROR_STOP=1 -f warehouse/verify_canonical.sql
"
```

#### 3.2 场景切换与验证

可以通过以下命令在三种基准场景间无污染切换：

```powershell
# 1. 注入 Canonical 场景（US / ASIN-A / Ads 转化率异常）并验证
wsl -d Ubuntu --cd "$((Get-Location).Path)" -- bash -c "
export DATABASE_URL='postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'
python3 warehouse/anomaly_injector.py --scenario canonical
psql 'postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth' -v ON_ERROR_STOP=1 -f warehouse/verify_canonical.sql
"

# 2. 注入 Traffic 场景（流量下降驱动）
wsl -d Ubuntu --cd "$((Get-Location).Path)" -- bash -c "
export DATABASE_URL='postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'
python3 warehouse/anomaly_injector.py --scenario traffic
"

# 3. 恢复为正常无异常状态（No Anomaly）
wsl -d Ubuntu --cd "$((Get-Location).Path)" -- bash -c "
export DATABASE_URL='postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'
python3 warehouse/anomaly_injector.py --scenario no_anomaly
"
```

### 4. Phase 3 Analytics Tools 真实数据库查询与完整 Case 验证

#### 4.1 单指标受控查询验证
在 Canonical 场景注入完毕后，执行以下命令验证受控 `query_metric()` 查询工具在真实 PostgreSQL 中的表现：

```powershell
wsl -d Ubuntu --cd "$((Get-Location).Path)" -- bash -c "
export DATABASE_URL='postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'
python3 backend/scripts/verify_phase3_query_metric.py
"
```

#### 4.2 完整 Canonical Case 人工调查闭环验证
执行以下命令，使用 `AnalyticsTools` 完整执行从全局 Sales 到关联拆解及三层分群下钻（Marketplace $\rightarrow$ ASIN $\rightarrow$ Traffic Source）的人工调查闭环：

```powershell
wsl -d Ubuntu --cd "$((Get-Location).Path)" -- bash -c "
export DATABASE_URL='postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth'
python3 backend/scripts/verify_phase3_complete_case.py
"
```

### 5. Phase 4 SQL AST Guard 纯静态安全验证

无需数据库连接即可验证纯 Python 的 AST 静态安全解析与防御：

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path

python -c "
from app.sql_safety import SqlGuard, SqlGuardError

guard = SqlGuard(
    allowed_tables=['warehouse.fact_daily_performance', 'warehouse.dim_products'],
    max_rows=1000
)

# 1. 验证合法查询（自动注入 LIMIT 1000）
valid_res = guard.validate('SELECT marketplace, SUM(sales) FROM warehouse.fact_daily_performance GROUP BY marketplace')
assert valid_res.effective_limit == 1000
assert valid_res.referenced_tables == ('warehouse.fact_daily_performance',)
assert 'LIMIT 1000' in valid_res.sql

# 2. 验证高危操作拦截（pg_sleep DoS 拦截）
try:
    guard.validate('SELECT pg_sleep(5) FROM warehouse.dim_products')
except SqlGuardError as e:
    assert 'not in allowed safe functions' in str(e)

print('SQL AST Guard static verification: PASS')
"
```

### 6. Phase 4 PostgreSQL 独立只读角色配置与权限验证

> **注意**：
> 1. 创建和配置角色需要 PostgreSQL 管理员权限（`postgres` 超级用户或具备 `CREATEROLE` 的管理员账号）；
> 2. 密码必须通过环境变量传入，严禁将真实密码硬编码到脚本或命令行参数中；
> 3. 角色上的 `default_transaction_read_only` 和 `statement_timeout` 仅作为新会话的**安全默认值**，未来实现的 SQL Executor 仍须在每次执行时显式强制事务模式与超时预算。
> 4. **`pg_hba.conf` 环境前置条件**：`pg_hba.conf` 是宿主 PostgreSQL 服务器的环境级客户端认证配置文件，**不属于本仓库脚本的管理范围**。仓库脚本不创建、不追加、不删除、不重排其中任何规则。宿主环境须由环境管理员独立确保 `metricsleuth_readonly` 角色能够通过 `scram-sha-256` 认证连接目标数据库；若认证规则缺失，应由环境管理员单独配置，不应由应用脚本静默修改系统级配置。
> 5. **Fail-Closed 密码校验**：`setup_readonly_role.sql` 内建 `\set ON_ERROR_STOP on`，并使用 `\gset` 在 SQL 层面校验密码非空。当 `METRICSLEUTH_READONLY_PASSWORD` 未设置、为空字符串或纯空格时，脚本将在任何角色创建、权限修改或密码变更发生前即非零退出（Fail Closed），已有角色状态不受影响。
> 6. 以下示例中的 `<local-only-secret>` 仅为占位符，**绝不填入真实密码**，真实凭据必须通过宿主环境的安全方式传入并在完成后立即清除。

#### 6.1 幂等配置只读角色

在 WSL 终端中执行以下命令配置 `metricsleuth_readonly` 角色（支持安全重复执行）：

```bash
export METRICSLEUTH_READONLY_PASSWORD='<local-only-secret>'
sudo --preserve-env=METRICSLEUTH_READONLY_PASSWORD \
  -u postgres psql -d metricsleuth \
  -v ON_ERROR_STOP=1 \
  -f warehouse/setup_readonly_role.sql
```

#### 6.2 独立只读权限验证

使用生成的只读连接串运行独立验证套件：

```bash
export READONLY_DATABASE_URL='postgresql://metricsleuth_readonly:<local-only-secret>@127.0.0.1:5432/metricsleuth'
python3 warehouse/verify_readonly_role.py
```

### 7. Phase 4 Observation 转换与状态契约验证

无需数据库连接即可验证纯 Python 的 Observation 模型与转换契约：

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path

python -c "
import datetime
from decimal import Decimal
from app.analytics.models import DateRange, MetricQueryRow, MetricQueryResult
from app.observations import observations_from_metric_query, ObservationStatus

cur_period = DateRange(datetime.date(2026, 1, 15), datetime.date(2026, 1, 15))
base_period = DateRange(datetime.date(2026, 1, 8), datetime.date(2026, 1, 14))

# 1. 模拟材料性下降结果转换（<= -10%）
result = MetricQueryResult(
    metric_id='sales',
    unit='usd',
    current_period=cur_period,
    baseline_period=base_period,
    group_by=(),
    rows=(MetricQueryRow({}, Decimal('800'), Decimal('1000'), Decimal('-0.2000'), 'ok', Decimal('500')),)
)

obs_tuple = observations_from_metric_query(
    result,
    tool_name='query_metric',
    tool_call_id='call_demo_01',
    query_or_result_reference='ref_demo',
    created_at=datetime.datetime.now(datetime.timezone.utc)
)

assert len(obs_tuple) == 1
assert obs_tuple[0].status == ObservationStatus.ANOMALOUS
assert obs_tuple[0].observation_id == 'call_demo_01_sales_0'
print('Observation Domain & Mapper verification: PASS')
"
```

### 8. Phase 4 Evidence 显式提升验证

无需数据库连接即可验证纯 Python 的 Evidence 显式提升契约：

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path

python -c "
import datetime
from decimal import Decimal
from app.analytics.models import DateRange, MetricQueryRow, MetricQueryResult
from app.observations import observations_from_metric_query
from app.evidence import promote_observation_to_evidence, EvidenceRole

cur_period = DateRange(datetime.date(2026, 1, 15), datetime.date(2026, 1, 15))
base_period = DateRange(datetime.date(2026, 1, 8), datetime.date(2026, 1, 14))

result = MetricQueryResult(
    metric_id='conversion_rate',
    unit='ratio',
    current_period=cur_period,
    baseline_period=base_period,
    group_by=('marketplace',),
    rows=(
        MetricQueryRow({'marketplace': 'US'}, Decimal('0.10'), Decimal('0.20'), Decimal('-0.5000'), 'ok', Decimal('500')),
        MetricQueryRow({'marketplace': 'UK'}, Decimal('0.20'), Decimal('0.20'), Decimal('0.0000'), 'ok', Decimal('200')),
    )
)

obs_tuple = observations_from_metric_query(
    result,
    tool_name='query_metric',
    tool_call_id='call_demo_02',
    query_or_result_reference='ref_demo_cr',
    created_at=datetime.datetime.now(datetime.timezone.utc)
)

# 1. 将 US 异常观察显式提升为 supporting 证据
ev_us = promote_observation_to_evidence(obs_tuple[0], role=EvidenceRole.SUPPORTING)
assert ev_us.evidence_id == 'evidence:call_demo_02_conversion_rate_0:supporting'
assert ev_us.role == EvidenceRole.SUPPORTING

# 2. 将 UK 正常观察显式提升为 negative_control 证据（排除 UK 异常）
ev_uk = promote_observation_to_evidence(obs_tuple[1], role=EvidenceRole.NEGATIVE_CONTROL)
assert ev_uk.evidence_id == 'evidence:call_demo_02_conversion_rate_1:negative_control'
assert ev_uk.role == EvidenceRole.NEGATIVE_CONTROL

print('Evidence Domain & Promotion verification: PASS')
"
```

### 9. Phase 5 OpenAI Agents SDK Runtime Spike 验证

本阶段采用官方 Python OpenAI Agents SDK (`openai-agents==0.22.0`) 作为 Agent 核心运行时，验证 `User Prompt → SDK Runner → 本地 Function Tool → Tool Result 回传模型 → Runtime 继续推理 → Structured Output (Pydantic)` 的端到端真实闭环。

#### 9.1 Hermetic 离线单元测试（无需网络与凭据，Runtime Spike 24 项；当前全量 321 项 PASS）

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_runtime_spike.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

#### 9.2 Live 真机 Spike 运行 (需要本地配置环境变量)

```powershell
# 1. 注入本地临时凭据 (严禁硬编码或提交至版本库)
$env:OPENAI_API_KEY = "<local-only-secret>"
$env:METRICSLEUTH_AGENT_MODEL = "gpt-4o-mini"

# 2. 执行端到端验证脚本
# 退出码语义：成功通过退出 0，缺少凭据退出 2 (BLOCKED)，运行失败退出 1
python backend/scripts/verify_phase5_runtime_spike.py
```

### 10. Phase 6 Runtime Analytics Tool Bridge

生产 Runtime 已将 `get_metric_definition()`、`query_metric()` 与 `query_related_metrics()` 封装为官方 Agents SDK `FunctionTool`。三个 Tool 由 `create_investigation_tools()` 一次创建并共享同一个每次调查预算（默认 8 次）；失败调用同样计入预算，超限会在进入 AnalyticsTools 前 Fail Closed。

SDK Tool 使用公开的 `ToolContext.tool_call_id` 生成 Observation，输出经过显式 JSON 边界转换：`Decimal` 保留为字符串、日期使用 ISO-8601、Mapping/tuple 转为普通对象/数组。由于 strict JSON Schema 不允许任意键对象，模型侧过滤条件采用结构化数组：

```json
{
  "filters": [
    {"dimension": "marketplace", "value": "US"}
  ]
}
```

离线验证不需要 API Key 或网络：

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_investigation_tools.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

当前能力只证明 `SDK Tool → AnalyticsTools → Observation → JSON Tool Output` 桥接成立，尚未实现或声称 Autonomous Investigation 已完成；Phase 5 Live Spike 仍按用户批准的例外暂缓。

### 11. Phase 6 Investigation Run Contract

`MS-P6-002` 使用官方 SDK `Agent + Runner` 执行调查 Tool，并通过 `verify_investigation_trace()` 审计多调用 Trace。生产代码没有 `while`、Planner 或固定下钻顺序；Runner 负责把每次 Tool Output 交回模型并继续下一轮。

Trace 验证至少保证：

- Tool 名称必须属于 `get_metric_definition` / `query_metric` / `query_related_metrics`；
- Call ID 在一次 Run 内唯一，且每个调用恰好匹配一个后置 Tool Output；
- Tool Output、Observation 与 SDK Call ID/Tool Name 身份一致；
- Observation ID 在整次 Run 内唯一；
- 最后一项必须是 Tool Output 之后的最终 Message；
- Tool Call 与模型轮次均不超过预算。

Hermetic 测试使用 SDK `ScriptedModel`，会真实经过 Runner 和 FunctionTool，但不会访问网络：

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_investigation_runtime.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

ScriptedModel 只证明应用与 SDK 的编排契约正确，不证明真实模型已经能够自主找出 Canonical、Traffic 或 No-anomaly Case；真实模型能力仍需后续 Live/Evaluation 验证。

### 12. Phase 6 Development Scenario Harness

`MS-P6-003` 提供测试侧三场景数据库验收脚本。三个场景都运行完全相同的探针矩阵；实际调查记录全部生成后，Harness 才加载 Ground Truth 评分，因此标签不会指导查询路径，也不会进入生产 Agent、Prompt 或 Tool Output。

```powershell
wsl -d Ubuntu --cd "$((Get-Location).Path)" -- bash -lc '
export DATABASE_URL="postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth"
python3 backend/scripts/verify_phase6_development_scenarios.py --restore-scenario canonical
'
```

验证覆盖：

- `canonical`：Conversion Rate 驱动，范围为 US / ASIN-A / Ads；
- `traffic`：Sessions 驱动，范围为 US / ASIN-A / Ads；
- `no_anomaly`：全部核心指标保持 `<5%` 正常波动，无主驱动、无异常范围；
- 每层负向对照成员集合精确匹配，缺失成员不能静默跳过；
- 结束后恢复 canonical 场景，保持现有演示基线。

这是 Benchmark/Data/Analytics 契约验收，不是生产调查 Workflow，也不证明真实模型已经自主选择正确查询。

### 12.1 Phase 6 Live Autonomous Investigation 验证

`MS-P6-004` 提供真实模型在真实 PostgreSQL 仓库上的全自动三场景 Live 调查验证脚本 `backend/scripts/verify_phase6_live_investigation.py`。
使用统一、领域中立的 Prompt，验证真实模型（默认 `gpt-4o-mini`）是否依据 Observation 事实动态分支，并在 `canonical`、`traffic`、`no_anomaly` 场景下输出符合 `DiagnosisComposition` 严格契约的诊断结果。

```powershell
# 1. 注入本地临时凭据 (严禁硬编码或提交至版本库)
$env:OPENAI_API_KEY = "<local-only-secret>"
$env:DATABASE_URL = "postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth"
$env:METRICSLEUTH_AGENT_MODEL = "gpt-4o-mini"  # 可选，默认 gpt-4o-mini

# 2. 执行三场景 Live 自动调查脚本
# 退出码语义：成功通过退出 0，缺少凭据/数据库连接退出 2 (BLOCKED)，运行断言失败退出 1
python backend/scripts/verify_phase6_live_investigation.py
```

验证契约与断言：
1. **自主动态分支**：Canonical 与 Traffic 场景的工具调用记录具有客观差异，证明非硬编码流程；
2. **Canonical 诊断**：`status=diagnosed`, `primary_driver="conversion_rate"`, scope 覆盖 `US / ASIN-A / Ads`；
3. **Traffic 诊断**：`status=diagnosed`, `primary_driver="sessions"`；
4. **No-anomaly 诊断**：`status=no_material_anomaly`, `primary_driver=None`, `affected_scope={}`；
5. **严格预算与轮次**：各场景均在 8 次工具调用与 10 轮模型交互内顺利终止；
6. **证据溯源**：所有引用的 Evidence 100% 对应本场 Run 产生的真实数据库 Observation；
7. **环境恢复**：执行完毕后自动恢复数据库至 `canonical` 演示场景。

> **Historical, superseded run:** An earlier compatible-provider Canonical run produced `primary_driver=orders` and a Scope without ASIN, so it correctly failed the Canonical contract and did not produce a PASS artifact. This is not the current acceptance status: later explicit Gemini runs passed the three-case gate and are recorded in [docs/evaluation-artifacts/live-evaluation-2026-09-22.md](docs/evaluation-artifacts/live-evaluation-2026-09-22.md).

### 13. Phase 7 Structured Diagnosis Domain Contract

`MS-P7-001` 建立了 Evidence-driven Diagnosis 的离线领域边界。`Diagnosis` 只表达数据异常贡献定位，不包含或暗示外部业务 `root_cause`；所有成功结论必须引用实际 `Evidence`，目标指标变化值由指定 Evidence 原样复制，不能由调用方另行填数。

当前支持五种互斥状态：

- `diagnosed`：必须具备异常目标 Evidence、异常 Driver Evidence、受 Evidence 上下文覆盖的 affected scope，以及至少一个 negative control；
- `no_material_anomaly`：目标必须由 normal supporting Evidence 支持，且不得同时引用异常的非 limitation Evidence；
- `insufficient_evidence`：表达证据不足，不伪造 Driver、Scope 或置信度；
- `budget_exhausted`：允许在尚未形成 Evidence 时安全结束；
- `tool_failure`：允许零 Evidence；若存在 Evidence，则必须是 FAILED limitation Evidence。

领域对象使用 `Decimal`、UTC 时间、tuple 防御性快照与只读 Mapping；Evidence ID 必须来自实际传入的 Evidence 集合。验证命令：

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_diagnosis.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

该任务只证明结构化 Diagnosis 的模型与证据约束成立，不证明真实模型已经自主生成正确 Diagnosis，也没有实现持久化、API 或 UI。

### 14. Phase 7 Diagnosis Draft Resolution

`MS-P7-002` 增加了一个刻意不携带指标事实的 `DiagnosisDraft`。未来 Runtime 只能在 Draft 中表达状态、目标指标、Driver、Scope、Evidence ID、置信度和限制；它不能提交 current value、baseline、relative change、unit、change 或 root cause。

`resolve_diagnosis_draft()` 会先把每个引用 ID 在应用持有的 Evidence Catalog 中精确解析，再按 Draft 声明顺序把实际 Evidence 交给现有 `build_diagnosis()`。未知引用、重复 Catalog ID、未被选中的 target Evidence 和任何跨 Evidence 领域冲突都会 Fail Closed。Catalog 中未被 Draft 引用的 Evidence 不会被悄悄加入结论。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_diagnosis_draft.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

Draft Resolver 专项 14 项、Diagnosis 合计 26 项持续通过；该任务链加入 Evidence Selection 时的全量基线为 192 项，当前全量见后续章节。该边界仍是 Hermetic 领域能力，不代表真实 LLM 输出已经接入。

### 15. Phase 7 Evidence Selection Resolution

`MS-P7-003` 建立了无事实字段的 `EvidenceSelection(observation_id, role)` 和不可变 `EvidenceSelectionDraft`。选择输入不能携带指标、数值、时间、过滤条件或错误信息；这些事实只能来自应用持有的真实 Observation。

`resolve_evidence_selections()` 会完整校验 Observation Catalog 的类型与 ID 唯一性，只解析 Draft 显式引用的 Observation，并按选择顺序调用现有 `promote_observation_to_evidence()`。未知引用、重复 Catalog ID、重复 `(observation_id, role)` 和不兼容的 Status/Role 都会 Fail Closed。

同一个 Normal Observation 可以合法同时成为 supporting Evidence 和 negative control Evidence；两者具有不同、确定性的 Evidence ID。未被选择的 Observation 不会进入 Evidence 结果。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evidence_selection.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

Evidence Selection 专项 14 项持续通过；加入组合契约后，后端全量为 203 项 PASS。该能力仍不负责自动决定 Evidence 角色，也不代表真实模型已经接入。

### 16. Phase 7 Observation-to-Diagnosis Composition

`MS-P7-004` 提供 `compose_diagnosis_from_observations()`，严格按以下顺序复用已验收能力：

```text
Observation Catalog
→ resolve_evidence_selections()
→ Evidence Portfolio
→ resolve_diagnosis_draft()
→ Diagnosis
```

返回的不可变 `DiagnosisComposition` 同时保留完整 Evidence Portfolio 和最终 Diagnosis。Portfolio 可以保留调查过程中形成但最终未被引用的 Evidence，便于后续评估 Evidence Coverage；Diagnosis 的每一个 Evidence ID 则必须存在于该 Portfolio。

组合服务不复制 Evidence 角色、Diagnosis 状态、Driver、Scope 或 negative control 规则，也不手动重建指标数值。任何下游领域错误都会原样向上传播，不会降级为部分成功。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_diagnosis_composition.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

Composition 专项 11 项持续通过；加入 Trace Catalog 提取后，后端全量为 215 项 PASS。

### 17. Phase 7 SDK Trace Observation Catalog Extraction

`MS-P7-005` 为现有 `observation_to_json()` 增加严格对偶 `observation_from_json()`，并通过 `extract_observation_catalog()` 只从已经通过审计的 `ToolCallOutputItem` 重建可信 Observation Catalog。

解析器要求 JSON 键集合精确匹配，Decimal 只能是有限数字字符串或 `null`，时间必须携带时区，日期、状态、Mapping 与 `group_by` 类型都必须严格合法。任何格式错误或 Observation 领域冲突统一转为 `RuntimeTraceError`。

模型 Message 和 `final_output` 即使包含看似合法的 Observation JSON，也不会进入 Catalog。并发 Tool Output 可以逆序完成；Catalog 始终按照已验证的 Tool Call 顺序规范化，确保后续 Evidence ID 与审计结果稳定。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_investigation_observation_catalog.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

当前验证为 Trace Catalog 专项 12 项、后端全量 215 项 PASS。该能力仍未让真实模型决定 Evidence 或 Diagnosis。

### 18. Phase 7 Runtime Structured Diagnosis Intent

`MS-P7-006` 使用冻结、`extra="forbid"` 的 Pydantic 模型定义 `RuntimeDiagnosisIntent`，供官方 SDK `Agent(output_type=...)` 生成 strict Structured Output。模型输出只能包含 Observation/Evidence 引用、角色、状态、Driver、Scope、confidence 和 limitations；Schema 中没有任何指标事实或 root cause 字段。

所有 JSON 数组在进入模型后转成 tuple，Python tuple 或字符串不能伪装成输入数组。Confidence 通过字符串传输后严格转换为有限 `Decimal`，重复 Scope、重复选择与重复 Evidence ID 继续由现有领域 Draft 拒绝。

`runtime_intent_to_drafts()` 只负责把受 Schema 约束的意图转换为 `EvidenceSelectionDraft + DiagnosisDraft`，不构造 Evidence、Diagnosis 或自动归因。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_runtime_diagnosis_intent.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

当前验证为 Runtime Intent 专项 9 项、后端全量 224 项 PASS。官方 SDK Output Schema 已验证为 strict，所有对象节点均关闭 `additionalProperties`。

### 19. Phase 7 Hermetic Evidence-driven Diagnosis Runtime

`MS-P7-007` 使用官方 SDK `Agent + Runner + ScriptedModel` 真正执行本地 FunctionTool，并依次完成：

```text
Runner Trace → Tool Output → Observation Catalog
→ RuntimeDiagnosisIntent → Evidence Selection
→ Evidence Portfolio → Structured Diagnosis
```

Agent 使用 `output_type=RuntimeDiagnosisIntent`，最终 Structured Intent 经过领域 Resolver 校验后才能形成 Diagnosis。每次 Run 都有独立 Tool Budget；未知 Observation、伪造引用、缺少 negative control 或非 Intent 最终输出都会 Fail Closed。

Trace 审计所需的字符串 sentinel 只存在于内部适配视图；公开 `InvestigationRunSummary.final_output` 保存实际 Structured Intent 的规范 JSON，不泄漏内部占位值。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_diagnosis_runtime.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

当前验证为 Diagnosis Runtime 专项 7 项、后端全量 231 项 PASS。ScriptedModel 证明 SDK 编排与领域边界成立，不证明真实 LLM 已经能自主选择正确调查路径。

### 20. Phase 8 Evaluation Case Contract and Core Scoring

`MS-P8-001` 在独立 `app/evaluation` 边界中严格加载调用方显式指定的 Ground Truth 文件，并把每条 Case 冻结为不可变 `GroundTruthCase`。Loader 不提供默认路径，Agent Runtime 与查询工具仍然无法发现或读取评测标签。

当前纯确定性评分覆盖：status、target metric、primary driver、Marketplace/ASIN/Traffic Source 三层 Scope Accuracy、No-anomaly 二分类正确性与 Core Exact Match。Scope Accuracy 固定按三层分别比较，额外未知 Scope 会使 Exact Match 失败。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evaluation_core.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

`MS-P8-001` 验收时 Evaluation Core 专项 12 项、后端全量 243 项 PASS；当时 Evidence Citation、Coverage、Unsupported Claims 与 Tool Operational 指标尚未实现。

### 21. Phase 8 Core Evaluation Aggregate Report

`MS-P8-002` 将多个 `CoreCaseScore` 聚合为不可变 `CoreEvaluationReport`，输出 status、target metric、driver、no-anomaly、exact match、三个 Scope 维度准确率及 Macro Scope Accuracy。

所有比率均使用有限 `Decimal` 和统一 Case 分母；输入顺序保留在 `case_ids` 中，空输入、重复 Case ID、错误类型和不一致的报告字段都会被拒绝。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evaluation_aggregate.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

当前 Aggregate 专项 8 项、后端全量 251 项 PASS。报告仍只包含已经具备明确语义的核心指标。

### 22. Phase 8 Evidence Obligation Contract

`MS-P8-003` 把每个 Ground Truth Case 转换为有确定性 ID 的机器可执行 Evidence Obligations：目标异常支持、Driver 异常支持、稳定指标，以及每个 Marketplace/ASIN/Traffic Source 负向对照成员。

Canonical Case 生成 9 项义务，No-anomaly Case 生成 13 项。义务顺序稳定、ID 在模型入口自校验，含冒号的歧义组件和非法字段组合会被拒绝。

当前专项 5 项、后端全量 256 项 PASS。本任务只定义“应该证明什么”，尚未对实际 Evidence 计算 Precision/Coverage。

### 23. Phase 8 Evidence Citation Precision and Coverage Scoring

`MS-P8-004` 使用 `score_evidence_citations()` 将 Diagnosis 实际引用的 Evidence 与 Case 的 Evidence Obligations 做确定性匹配。Citation Precision 的分母是实际引用数，用来惩罚无关引用；Evidence Coverage 的分母是义务数，用来惩罚关键支持或负向对照遗漏。

只有 `Diagnosis.evidence_ids` 中的 Evidence 才参与评分，Portfolio 中未引用的 Evidence 不会抬高 Coverage。一条 Evidence 可以同时覆盖多个义务，例如带 Marketplace 维度的正常 Sessions 负向对照既可证明 Sessions 稳定，也可覆盖对应 Marketplace control。若同一维度在 filters 与 dimensions 中冲突，该 control 匹配会 Fail Closed。零引用时 Precision 明确为 `None`，避免把“无定义”误报为 0%。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evidence_scoring.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

`MS-P8-004` 验收时 Evidence Scoring 专项 10 项、后端全量 266 项 PASS；当时 Unsupported Claim 与 Tool Operational 指标仍未实现。

### 24. Phase 8 Unsupported Claim Scoring

`MS-P8-005` 将 Diagnosis 自身提出的成功事实拆成确定性 Claim：目标变化、Primary Driver，以及每一个 affected scope 成员。它不读取 Ground Truth，回答的是“这个结论是否由自己实际引用的 Evidence 支撑”，与 Citation Precision/Coverage 的评测问题明确分离。

目标 Claim 必须由 `DiagnosisChange.evidence_id` 指向的已引用 Evidence 支撑，并逐项核对 metric、role、status、current/baseline/relative change 和 unit；Driver 与 Scope Claim 也只能使用实际引用 Evidence。未引用 Portfolio Evidence 不生效，filters/dimensions 冲突时 Scope 支撑 Fail Closed。非成功 Diagnosis 不提出成功事实 Claim，因此 Unsupported Claim Rate 为 `None`。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_unsupported_claims.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

`MS-P8-005` 验收时 Unsupported Claims 专项 11 项、后端全量 277 项 PASS；当时 Tool Operational 指标与完整 Evaluation Runner 尚未实现。

### 25. Phase 8 Evaluation Run Outcome and Tool Operational Scoring

`MS-P8-006` 增加显式 `EvaluationRunOutcome`，使成功、Tool Failure、Budget Exhaustion 与 Runtime Failure 都能以同一不可变结构进入评测。失败运行的状态、调用计数和 `failure_code` 必须由调用方根据已观测事实提供；模块不会解析异常文本，也不会把缺失 Summary 猜成某种失败。

Tool Success Rate 采用协议层口径：有配对且通过 Trace 合法性检查的 Tool Output 数 / 已尝试 Tool Call 数。它不代表 Diagnosis Accuracy，也不代表业务查询答案正确。零次尝试时该比率为 `None`；Budget Exhaustion 作为独立终止状态记录，因此可以与此前 Tool Calls 全部成功同时成立。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evaluation_operational.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

当前 Evaluation Operational 专项 15 项、后端全量 292 项 PASS。多 Run 聚合与完整 Evaluation Runner 仍未实现。

### 26. Phase 8 Tool Operational Aggregate Report

`MS-P8-007` 将多个 `ToolOperationalScore` 聚合为不可变报告。Tool Success Rate 使用总成功调用数 / 总尝试调用数的调用级 micro 分母；Average Tool Call Count 使用 Run 数；Budget Exhaustion Rate 使用耗尽 Run 数 / Run 数。不会把每个 Run 的成功率简单平均来替代调用级统计。

空输入返回零计数与 `None` 比率；包含零调用 Run 时，该 Run 仍计入平均调用次数和预算分母，但不进入 Tool Success 的调用分母。输入顺序保留，重复 `case_id`、非法计数、非有限 Decimal 和伪造公式均 Fail Closed。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evaluation_operational_aggregate.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

`MS-P8-007` 验收时 Operational Aggregate 专项 7 项、后端全量 299 项 PASS；当时 Unified Evaluation Report 与完整 Evaluation Runner 尚未实现。

### 27. Phase 8 Unified Evaluation Aggregate Report

`MS-P8-008` 将 Core、Evidence Citation、Unsupported Claim 和 Tool Operational 四类结果组合为一个不可变报告。Evidence Precision 只平均有定义的 Case；Coverage 按 Case 平均；Unsupported Claim Rate 使用总 Claim 数作为 micro 分母；Operational 子报告沿用调用级/Run 级分母，不重新计算或篡改。

报告明确保留不同身份域：Evidence 分数按 `case_id` 与 Core 对齐，Unsupported Claim 分数按独立 `diagnosis_id` 保留，不伪造二者相等。输入顺序、重复身份、缺失 Case、伪造派生率和错误类型都会 Fail Closed。

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evaluation_unified.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

`MS-P8-008` 验收时 Unified Evaluation 专项 3 项、后端全量 302 项 PASS；当时 Hermetic Evaluation Runner、Holdout 和真实模型评测仍未验收。

### 28. Phase 8 Hermetic Evaluation Runner Contract

`MS-P8-009` 使用显式 `EvaluationRunRecord` 将 Ground Truth Case、已观测 Run Outcome 与可选 `DiagnosisComposition` 组合为确定性评测输入。Runner 只调用既有 Core、Evidence、Unsupported Claim 与 Tool Operational 评分器并构建 Unified Report；它不加载 Ground Truth 文件、不调用 Agent SDK、不访问数据库、网络或文件系统。

失败运行仍进入统一分母，但不会伪造 Diagnosis。`completed` Outcome 必须携带 Composition，且不能携带 `budget_exhausted` 或 `tool_failure` Diagnosis；Runtime Failure 禁止携带 Composition；Budget/Tool Failure 如携带 Composition，其 Diagnosis 状态必须精确匹配。

```powershell
Push-Location backend
python -B -m unittest discover -s tests -p "test_evaluation_runner.py" -v
python -B -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

验收结果：Evaluation Runner 专项 9 项、后端全量 311 项 PASS。该结果只证明 Hermetic 评测编排契约，不代表 10～15 Case Holdout 或真实模型评测已经完成。

### 29. Phase 8 Evaluation Manifest and Reproducibility Contract

`MS-P8-010` 新增不可变 `EvaluationManifest`，显式记录 `manifest_id`、`model_id`、完整 Prompt、Metric Config Version、Dataset Version、按 Case 的运行次数和 UTC 创建时间。`total_run_count` 由逐 Case 次数派生，调用方不能伪造。

完整 Prompt 被原样保留，其他标识符规范化首尾空白；运行次数必须是正整数并明确拒绝 `bool`。逐 Case Mapping 会创建防御性快照并在运行时只读。Manifest 是纯数据契约，不读取文件、环境变量、网络或数据库，也不导入 Agent Runtime、SDK 或 Ground Truth Loader。

```powershell
Push-Location backend
python -B -m unittest discover -s tests -p "test_evaluation_manifest.py" -v
python -B -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

验收结果：Evaluation Manifest 专项 10 项、后端全量 321 项 PASS。当前 Manifest 可以记录每个 Case 的运行次数，但现有 Runner 仍以 `case_id` 唯一，尚未实现同一 Case 的多 Run 身份与聚合。

### 30. Phase 8 Benchmark 评测管道与端到端运行指南 (MS-P8-014)

`MS-P8-014` 实现了端到端 Benchmark 评测管道运行器 [backend/scripts/run_benchmark_evaluation.py](backend/scripts/run_benchmark_evaluation.py)，将 `EvaluationManifest` 声明、逐 Case 多次运行收集、`ManifestEvaluationRunSet` 严格对账校验与 `RepeatedRunEvaluationReport` 宏指标聚合完整串联，并输出格式整齐的高可读性 CLI 看板。

#### 30.1 离线 Hermetic 模拟评测模式 (无需凭据与数据库连接)

使用 10 个真实 Benchmark Case 快速运行离线确定性模拟，验证整套对账与聚合管道：

```powershell
# 1. 单次执行测试 (每个 Case 运行 1 次，共 10 次 Run)
python backend/scripts/run_benchmark_evaluation.py --hermetic --runs-per-case 1

# 2. 稳定性重复评测 (每个 Case 运行 3 次，共 30 次 Run 并输出 JSON 报告)
python backend/scripts/run_benchmark_evaluation.py --hermetic --runs-per-case 3 --output-json evaluation_report.json
```

#### 30.2 真实 Live Agent 评测模式 (需本地凭据与数据库)

在已配置 `OPENAI_API_KEY` 与 PostgreSQL `DATABASE_URL` 的环境下执行：

```powershell
# 1. 注入本地临时凭据 (严禁硬编码至仓库)
$env:OPENAI_API_KEY = "<local-only-secret>"
$env:DATABASE_URL = "postgresql://metricsleuth:metricsleuth@127.0.0.1:5432/metricsleuth"

# 2. 端到端执行全量 10 Case 真实模型评测
# 退出码语义：评测完成退出 0，缺少凭据退出 2 (BLOCKED)，管道异常退出 1
# --model-id 优先；未显式传入时会使用 METRICSLEUTH_AGENT_MODEL，并把实际值写入 Manifest。
python backend/scripts/run_benchmark_evaluation.py --runs-per-case 1 --output-json live_benchmark_report.json
```

#### 30.3 管道单元测试回归

```powershell
Push-Location backend
python -m unittest discover -s tests -p "test_evaluation_pipeline.py" -v
python -m unittest discover -s tests -p "test_*.py" -v
Pop-Location
```

### 31. Phase 10 FastAPI 服务与 RESTful 接口指南 (MS-P10-001)

`MS-P10-001` 构建了轻量、零侵入的 FastAPI 后端服务（`backend/app/api/` 与 `backend/app/main.py`），将核心指标依赖拓扑图、演示场景切换/注入、受控 Agent 异常排查会话执行以及结构化诊断输出封装为标准的 RESTful HTTP 接口，为前端 React Diagnosis Workspace 提供稳定、类型完备的 API 支持。

#### 31.1 本地启动服务

服务支持通过 `uvicorn` 热重载启动：

```powershell
# 方式一：从 backend 目录启动 (推荐)
Push-Location backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
Pop-Location

# 方式二：从仓库根目录启动
$env:PYTHONPATH = "backend"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 31.2 交互式 Swagger API 文档

服务启动后，可直接在浏览器中访问自动生成的 OpenAPI / Swagger 文档：
* Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
* ReDoc UI: [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### 31.3 核心 RESTful 端点一览

| 方法 | 路径 | 描述 | 适用场景 |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | 服务健康检查与存活探针 | 前端与网关连通性检测 |
| `GET` | `/api/metrics/graph` | 获取指标依赖拓扑图（节点元数据与有向依赖边） | 前端指标拓扑看板可视化渲染 |
| `GET` | `/api/scenarios` | 获取 10 个受控 Benchmark 场景的中性展示信息（不返回 Ground Truth 标签） | 演示场景下拉选择器 |
| `POST` | `/api/scenarios/inject` | 触发指定场景的数据注入（无数据库时自动降级 Dry-run） | 场景一键切换 |
| `POST` | `/api/investigate` | 执行指标异常调查（`mock_mode=True` 为 Fixture Preview；关闭后为 Live Agent 路径） | 核心诊断执行与调查轨迹回放 |

#### 31.4 API 单元测试与端点自检

单元测试基于 `fastapi.testclient.TestClient`，完全离线运行且不依赖外部网络与数据库：

```powershell
# 1. 执行 API 专项单元测试 (15 项)
Push-Location backend
python -m unittest discover -s tests -p "test_api.py" -v
Pop-Location

# 2. 快速健康检查一键自测
python -c "from app.main import app; from fastapi.testclient import TestClient; client = TestClient(app); res = client.get('/health'); assert res.status_code == 200; print('API Self-check: PASS')"
```

### 32. Phase 10 React Diagnosis Workspace 前端工作台指南 (MS-P10-002)

`MS-P10-002` 构建了基于 **React + TypeScript + Vite + 原生 Vanilla CSS** 的现代化 **Diagnosis Workspace（诊断工作台）** 单页应用，实现了指标拓扑可视化、10 个 Benchmark 场景一键切换注入、Agent 逐步调查轨迹回放、证据链卡片分类展示、结构化诊断卡以及底部自然语言继续追问交互。

#### 32.1 前端环境启动

在 `frontend/` 目录下启动 Vite 开发服务器：

```powershell
Push-Location frontend
npm install
npm run dev
Pop-Location
```

启动后在浏览器中打开：[http://localhost:5173](http://localhost:5173)

#### 32.2 全栈双端本地联调与演示流程

在两个终端中分别启动后端与前端：

```powershell
# 终端 1：启动 FastAPI 后端服务 (监听 8000 端口)
Push-Location backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
Pop-Location

# 终端 2：启动 React 前端服务 (监听 5173 端口，内建代理转发至 8000)
Push-Location frontend
npm run dev
Pop-Location
```

#### 32.3 核心功能模块交互说明

1. **顶部控制栏 (Header & Control Bar)**：
   - **连接状态指示灯**：展示 `FastAPI 1.0.0 (Connected)` 或离线保护状态；
   - **Benchmark 场景下拉菜单**：包含全部 10 个受控场景（Canonical / Traffic / No-anomaly / AOV / UK Ads / DE CR / Distractor 等）；
   - **Fixture Preview / Live 模式切换**：Fixture Preview 用于无数据库或无 OpenAI Key 时展示确定性 UI 数据，不代表 Agent 推理；在已配置环境时可切换 Live 真实排查；
   - **「💉 注入场景数据」**：调用受控异常注入器更新仓库数据（带 Toast 反馈）；
   - **「⚡ 发起自主排查」**：触发 Agent 多步调查并全量驱动页面各板块数据刷新。
2. **Metric Dependency Graph (指标拓扑与因果拆解)**：
   - 展示 `Sales` $\rightarrow$ `Orders` $\times$ `AOV`，`Orders` $\rightarrow$ `Sessions` $\times$ `Conversion Rate` 拓扑依赖树；
   - 异常驱动指标动态高亮（如 AOV 或 Conversion Rate 节点带有呼吸灯外发光与相对变化率 Badge）；
   - 点击任意节点弹出详情模态框，展示该指标的详细业务定义、公式与依赖列表。
3. **Structured Diagnosis (结构化诊断报告)**：
   - 展示状态徽章（`DIAGNOSED` 或 `NO_MATERIAL_ANOMALY`）、Target 相对跌幅、Primary Driver 驱动因子、Affected Scope 维度标签组（Marketplace/ASIN/Traffic Source）、置信度百分比与预算开销；
   - 醒目标注因果隔离声明：“数据异常贡献定位，不外推现实业务最终因果”。
4. **Investigation Trajectory (Agent 调查动作轨迹)**：
   - 阶梯式时序流展现调查轨迹；Fixture Preview 展示预置轨迹，Live 模式展示实际运行轨迹；
   - 支持展开查看每一步工具的入参与 Observation 原始回执。
5. **Evidence Portfolio (证据链看板)**：
   - 支持通过 Tab 自由切换“全部证据”、“支撑证据 (Supporting)”与“排除对照 (Negative Controls)”；
   - 卡片式展示指标、基准值对比、当前值、变化率与细分维度过滤器。
6. **Continue Investigation (继续追问与深入下钻)**：
   - 提供快捷追问建议按钮（如“分析近30天内促销优惠对客单价 AOV 的影响”等）以及自定义自然语言输入框，支持 Human-in-the-Loop 追加排查。

#### 32.4 生产构建与打包验证

```powershell
Push-Location frontend
npm run build
Pop-Location
```
- 结果：通过 TypeScript 严格编译与 Vite 生产打包，生成零错误生产静态资源（`dist/`）。
