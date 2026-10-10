# MetricSleuth Agent 接管指南

## 1. 项目定位

MetricSleuth 是一个 **AI 自主数据调查与诊断系统**。它读取受控指标和真实查询结果，由 Agent 动态选择下一步调查动作，最终输出带 Evidence 引用的 Structured Diagnosis。

电商是当前第一个验证领域，不是产品的永久定义。项目目标是形成可在个人服务器长期运行、可供求职展示和毕业设计验收的完整 Web 软件，而不只是 Synthetic Benchmark Demo。

## 2. 新对话阅读顺序与权威关系

1. `AGENTS.md`：稳定的接管规则与仓库入口。
2. `docs/PROJECT_STATUS.md`：当前任务、验证快照、阻碍和下一步。
3. `docs/PRODUCT.md`：稳定产品目标、MVP 边界和验收标准。
4. `docs/ARCHITECTURE.md`：源码确认的当前架构与规划架构。
5. `docs/ROADMAP.md`：长期阶段、依赖和完成条件。
6. 当前阶段关联源码、测试和专项文档。

`任务书.md`、`快速开发版项目基线.md`、`docs/agent-state.md` 和 `docs/project-learning-log.md` 是历史设计与演进记录，不再单独决定当前产品优先级。发生冲突时依次采用：**当前源码与运行证据 → `docs/PRODUCT.md` 中的已确认目标 → `docs/ARCHITECTURE.md` → `docs/ROADMAP.md` → 历史文档**。

## 3. 技术栈与关键目录

- `backend/app/metrics/`：指标语义注册表。
- `backend/app/analytics/`：受控 PostgreSQL Analytics Tools。
- `backend/app/agent_runtime/`：OpenAI Agents SDK Runtime 与 Tool Trace。
- `backend/app/observations/`、`evidence/`、`diagnosis/`：事实、证据和诊断领域边界。
- `backend/app/evaluation/`：确定性评分与聚合。
- `backend/app/api/`：FastAPI 产品接口。
- `backend/app/monitoring/`：手动异常扫描。
- `backend/app/persistence/`：短事务、调查步骤保存与最小 PostgreSQL Worker；部署接线仍需查当前状态。
- `frontend/`：React + TypeScript + Vite 单页工作区。
- `warehouse/`：Synthetic Benchmark、PostgreSQL Schema、Seed 与隔离验证脚本。
- `configs/`：指标定义。
- `docs/evaluation-artifacts/`：脱敏评测和数据验证记录。

## 4. 必须遵守的工程原则

1. 源码、测试和实际运行证据优先；Mock/Hermetic 通过不得表述为真实模型或真实数据库通过。
2. 复用现有 OpenAI Agents SDK Runtime、Semantic Layer、Analytics Tools、Observation、Evidence、Diagnosis 和 Evaluation；没有 ADR 不建立第二套 Runtime。
3. Ground Truth 只供 Evaluation 使用，不能进入产品 Runtime、Prompt、API 或工具查询。
4. Synthetic、Sandbox 和真实外部数据必须有明确来源与环境隔离，禁止用前端数字伪造业务事件。
5. Agent 不得发明指标公式或事实；Diagnosis 的 Driver 和 Scope 必须由本轮 Evidence 支撑。
6. 不把数据异常贡献定位描述为最终业务因果。
7. 优先完成最小真实闭环；Jev、Webhook、多 Runtime、多行业和重型基础设施按 Roadmap 延后。
8. 不读取、输出或提交真实密钥；不未经确认操作生产数据、线上配置或不可逆部署。
9. 每个实现任务结束后更新 `docs/ROADMAP.md` 和 `docs/PROJECT_STATUS.md`，并记录验证边界。

## 5. 常用验证命令

后端离线回归（不访问真实模型或数据库）：

```powershell
Push-Location backend
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m unittest discover -s tests -p "test_*.py" -v
$testExit = $LASTEXITCODE
Pop-Location
exit $testExit
```

前端静态验证：

```powershell
Push-Location frontend
npm run lint
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json
Pop-Location
```

生产构建会写入 `frontend/dist/`，仅在任务允许生成构建产物时执行：

```powershell
Push-Location frontend
npm run build
Pop-Location
```

真实 PostgreSQL、真实模型、外部数据同步和部署验收必须使用明确配置的非生产或受控环境，并在结果中单独标注。

R2 PostgreSQL 专项：在 `backend` 中配置专用 `METRICSLEUTH_TEST_DATABASE_URL` 后执行 `python -B -m unittest tests.test_postgres_persistence_integration -v`。仅允许本机 `metricsleuth_r2_acceptance`，会执行应用状态迁移；完整环境、启动/停止和验证边界见 [`docs/evaluation-artifacts/postgres-persistence-acceptance-2026-10-10.md`](docs/evaluation-artifacts/postgres-persistence-acceptance-2026-10-10.md)。未配置时跳过不是数据库验收通过。

## 6. 工作方式

R2 任务 API 数据库专项：在相同专用环境运行 `python -B -m unittest tests.test_postgres_persistence_integration tests.test_postgres_task_api_integration -v`。HTTP 使用 TestClient、Runner 为受控 SQL，不是模型验收；详见 `docs/evaluation-artifacts/task-api-acceptance-2026-10-10.md`。默认 FastAPI app 未配置任务服务时返回 503。

显式本地应用入口为 `python -B -m app.task_application api` / `worker --once`（backend cwd），必须先按 `docs/evaluation-artifacts/task-application-acceptance-2026-10-10.md` 配置；不会自动迁移或注入数据。新增真实 SQL/进程专项 `tests.test_postgres_task_application`；真实模型验收仍需明确凭据与预算。

Olist 静态公开数据的实际 SQL/步骤留存证据见 `docs/evaluation-artifacts/olist-persistence-acceptance-2026-10-10.md`。一次授权的真实SDK调查返回 `InternalServerError`，成功 gate 尚未通过；见 `docs/evaluation-artifacts/live-task-persistence-attempt-2026-10-10.md`。`verify_live_task_persistence.py` 是显式计费验收脚本，不是自动回归；本次一次性授权已使用，不得未经新的授权重跑。

- 开始任务前检查 `git status --short --branch`，保护用户现有修改。
- 先读取当前阶段代码和测试，再确定最小改动。
- 一般低风险实现可按 Roadmap 自主推进；重大产品方向、不可逆数据操作、生产部署、密钥和权限变更必须先获得用户确认。
- 子任务完成不等于项目验收；主线程必须审查最终 diff 并亲自执行适当测试。
- 失败必须保留并说明，不为展示效果降低领域校验或篡改评测口径。
