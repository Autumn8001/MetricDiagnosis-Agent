# R2-005b2a — 任务 API 真实 PostgreSQL 验收

日期：2026-10-10。状态：主线程实际执行通过。基线：`1b2b334` + 本切片提交（从 Git history 定位）。

## 实际交付

用户后续可通过这些接口启动调查、看进度和重新打开历史；本次实现后端合同，尚未接线前端或默认运行配置。

- POST `/api/investigations`：校验服务器注册来源和 metric/dimensions，持久排队，返回 202；不执行模型。
- GET `/api/investigations?source_id=...`：分页读取历史。
- GET `/api/investigations/{run_id}?source_id=...`：读取状态、Tool Call、Observation、Evidence 引用与 Diagnosis。
- `main.py:create_app(investigation_tasks_service=...)` 显式注入；默认 app 未配置时 503，不自动读取连接配置、迁移或启动 Worker。

源码：`backend/app/api/task_{schemas,service,routes}.py`、`backend/app/persistence/task_read_repository.py`、`backend/app/main.py`。

## 环境与复现

隔离本机 PostgreSQL **17.11**，端口 **55440**，专用数据库 `metricsleuth_r2_acceptance`、角色 `metricsleuth_test`。沿用前一阶段的仓库外 portable PostgreSQL 环境；准备与启动命令见 [Worker 验收记录](worker-checkpoint-acceptance-2026-10-10.md)。本地 trust 仅限隔离回环测试，不能复制到生产。

在 `backend` 运行：

```powershell
$env:METRICSLEUTH_TEST_DATABASE_URL = 'postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_persistence_integration tests.test_postgres_task_api_integration -v
```

测试只接受明确配置的本机专用测试库，不读取 `.env` 或应用 `DATABASE_URL`。会重复执行 app_state migrations 001–004，并新增 UUID 隔离测试记录；不清空数据库、不触碰生产或外部业务数据。未设置变量时跳过，不能视为验收通过。

本轮验收结束已停止端口 55440 的隔离测试实例；数据目录保留在仓库外，无删除操作。

HTTP 使用 FastAPI TestClient；真正 SQL/事务/新连接由 psycopg 执行。Worker 明确调用 `run_once()`，Runner 通过参数化 SELECT 生成 80/100 受控 Observation；没有调用模型，也没有读取外部真实订单。

## 本轮实际结果

| 检查 | 主线程结果 | 能证明什么 |
| --- | --- | --- |
| `tests.test_postgres_task_api_integration` | 4/4 PASS | HTTP 提交/查询与真实持久化组合 |
| 上述两个数据库模块合并 | Ran 19 tests / OK | 含原 15 项事务、身份、步骤与中断恢复回归 |
| `tests.test_task_api tests.test_task_read_repository tests.test_api` | Ran 40 tests / OK | 新合同、安全响应、SQL 作用域与旧 API 回归（Hermetic） |
| 全量 `unittest discover -s tests -p "test_*.py" -q` | Ran 568 tests / OK (skipped=2) | 未配置 DB 的独立离线回归；两项跳过为数据库测试类，不代表数据库通过 |

数据库 API 四项：

1. 提交后 queued，未调用 Runner；Worker 执行中读取 running 和已提交步骤；成功后四类事实与 evidence_ids 一致。全新应用/service/Worker 实例可读取同一结果，另一来源读取返回 404。
2. Runner 在保存一步后异常：状态 failed、受控 execution_failed、工具事实保留，Evidence/Diagnosis 为空；响应不含异常原文。
3. 非法指标/维度/来源、非日日期、客户端连接配置或环境字段被拒绝，不产生任务。输入错误只返回固定 code，不回显误传连接信息。
4. 读连接工厂异常只返回 503 固定 code，不暴露原始连接异常。

主线程接线时发现 router 导出名不匹配造成 ImportError，已修正 import 并重跑通过；未掩盖失败。

## 验证边界与下一步

- **真实运行**：本机 PostgreSQL、SQL、事务、持久步骤、HTTP 合同与全新实例读取。之前的进程重启/Worker 崩溃证据仍由对应专项记录支撑。
- **受控而非真实模型**：Runner 的 Observation/Diagnosis 是测试构造。未验证 LLM 决策、模型成本或外部真实数据效果。
- **尚未完成**：默认应用配置、真实 SDK Runner、后台进程启动、前端、外部同步、认证和生产部署。
- 服务器 source allowlist 不等于用户授权；旧端点仍有开发 CORS 和异常响应问题。新 API 不自动开放生产数据，不可直接公开部署。
- 公共详情使用显式字段投影，排除 error_message、failure_details、Evidence payload 和原始请求参数；工具参数/结构化文本仍由写入边界约束，不是任意秘密自动脱敏器。
- 同一 source_id 由服务器绑定唯一 provider/environment；provider 响应来自配置。接入配置须与数据库身份一致，不能随意重绑定已存在来源。
- 下一步 R2-005b2b：最小显式应用 Runner/启动配置，复用 AnalyticsTools 与 SDK progress callback，隔离旧 Synthetic Injection，随后在明确授权凭据和预算下进行一次真实模型验收。
