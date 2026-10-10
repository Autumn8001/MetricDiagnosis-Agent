# R4-003：真实 PostgreSQL → API → 浏览器历史读取

日期：2026-10-10。源码起点：`423f8106880ecdbd6b162db0ed8998e0516cdd8f`。
范围：只读已有隔离调查记录，不运行 Worker、模型、迁移、数据导入或业务事件。

## 产品意义与验证边界

目标是证明 R4-002 页面显示的数据可以来自真实持久化数据库，而不只是前端受控 HTTP fixture。输入为上一轮已导入公开静态 Olist 数据并由受控 Runner 查询、保存的失败调查。它不是新的模型调查，也不是持续外部数据接入。

既有调查 `102bea3f-cc93-400a-a871-6ef90238972f`；来源 `bbaf0fe3-c61a-4d03-acca-4e10b69d24b7` / `olist` / `validation`；版本 `olist-public-raw-files-20261010`。该版本仍是标签而非快照。历史产生过程见 [Olist SQL/步骤验收](olist-persistence-acceptance-2026-10-10.md)。

## 实际环境和读取链路

- 仓库外已有 PostgreSQL 17.11，数据目录 `D:/Rag/Agent/metricsleuth-test-pg-61dc9486/data-worker-fresh`；仅 loopback 55440、专用 `metricsleuth_r2_acceptance`。
- 先用 `pg_ctl status` 确认停止，再启动既有测试实例；没有重新 initdb 或执行迁移。
- 使用 `app.task_application api --port 8012` 的实际 Python 子进程，显式 Olist 来源配置和占位 model `unused-read-only-browser-acceptance`。没有模型凭据读取、`.env` 加载或 Worker 启动。
- 浏览器验收服务只代理允许的 GET 来源/列表/详情请求，POST 与其他 API 拒绝。production React build 由本机 HTTP 服务托管，真正读取上述 API 的 PostgreSQL 结果，无 fixture 兜底。

```text
既有 Olist 调查事实（PostgreSQL app_state）
    → TaskReadRepository / InvestigationTasksService
    → task_application 的实际 HTTP GET
    → 验收服务的只读代理
    → React 持久调查工作区 / Edge 浏览器
```

## 主线程运行证据

初步真实 API 返回来源目录1项；指定调查为 `failed`，4个 Tool Call、27个 Observation、0 Evidence、0 Diagnosis。直接 PostgreSQL `BEGIN READ ONLY` 查询与 API 第一条 Observation 相同：`merchandise_gmv` current `16861.09`、baseline `13355.61`。数字为公开静态数据聚合，不提交原始订单或个人记录。

主线程最终结果：真实 Edge + production build + 只读真实 API 代理 **PASS**。页面显示指定来源/任务、首条真实 Observation 与关联 Tool Call/查询引用、上述 current/baseline 值及失败无 Diagnosis；刷新后再次从历史打开仍一致。桌面1440×1000和手机390×844截图已检查，手机无页面水平溢出。脚本断言浏览器 POST/PUT/PATCH/DELETE 尝试为0。

数据库验收前后全表计数一致：Run178、Tool Call117、Observation155、Evidence70、Diagnosis70；指定失败调查仍为4/27/0/0。本次没有新增调查、执行步骤或修改结果。未知配置来源读取该调查实际返回404，旧 `/api/scenarios` 实际返回404。

`node --check` 和前端 `npm run lint` 由主线程执行通过。非法非loopback API 地址在任何请求前失败，输出固定 `FAIL api_url`、退出码1，这是预期安全拒绝，不是成功浏览器验收。

截图目录：`C:/Users/星烛/.codex/visualizations/2026/10/09/01a11e69-2efd-7a23-8450-901add13d890/r4-003-postgres-browser/`。验收结束已核对并停止本次API PID50620，停止55440隔离PostgreSQL；`pg_ctl status` 确认 `no server running`（该检查的退出码1表示已停止）。数据库和截图保留。

真实记录呈现发现：长 Decimal 在手机上换行较多，27条维度 Observation 逐项展示较长。后续应改善显示格式/分层阅读，保留原始精度和引用，不为演示篡改值。本次未修改业务 UI。

## 复现方式

准备同一隔离数据库与既有记录，按 [显式本地应用说明](task-application-acceptance-2026-10-10.md) 启动 API，绑定上述来源/Profile。API 入口需要配置 model，但本次只启动 API；不要运行 `worker` 或收费验收脚本。

在 `frontend`：

```powershell
npm run build
node scripts/verify-postgres-workspace.mjs --api http://127.0.0.1:8012 --source bbaf0fe3-c61a-4d03-acca-4e10b69d24b7 --run 102bea3f-cc93-400a-a871-6ef90238972f --output D:/Rag/Agent/metricsleuth-postgres-browser-evidence
```

脚本不创建缺失来源或调查；没有上述历史记录时会失败。验证使用真实 Edge（可显式配置 `METRICSLEUTH_TEST_BROWSER`），有界翻页查找既有记录；输出目录只保存截图，临时 profile 在结束时清理。终验后停止本次启动的 API 子进程和隔离 PostgreSQL，保留数据库及截图，不部署。

## 仍未完成

成功 Diagnosis 的真实数据库页面验证、浏览器提交到受控 Worker 的端到端调查及真实 SDK 成功 gate 仍需独立验收。持续真实源、指标趋势/异常、可操作 Lab、最小权限/认证和服务器部署不由本次只读历史验收证明。
