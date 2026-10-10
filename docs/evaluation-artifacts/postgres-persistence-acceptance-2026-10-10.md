# R2-PG：真实 PostgreSQL 持久化验收

日期：2026-10-10。审查基线：`eba3d1846d08876df42c9730289009875dd73dc0`，加本次 R2-PG 修复提交。主线程审查 diff 并亲自执行以下测试。

本记录是 `71e284f` 阶段的历史快照。后续代码增加 Worker 与测试，当前复现命令将执行更多案例；最新结果见 [`worker-checkpoint-acceptance-2026-10-10.md`](worker-checkpoint-acceptance-2026-10-10.md)，不要改写下面原始七项结果。

## 结论与边界

**真实 PostgreSQL 持久化验收通过；不是外部真实业务数据或真实模型验收。**

受控 Runner 从实际参数化 `SELECT 80/100` 构造合法的 Trace、Observation、Evidence 和 Diagnosis，经过现有 Task Service → Coordinator → Writer → Repository 保存。没有调用 OpenAI/Shopify，没有修改生产环境。查询不是完整 AnalyticsTools/Warehouse 调查，模型动态决策质量不在本次证据范围。

产品对应能力：未来调查历史、证据详情及失败状态有了经真实数据库验证的保存基础。当前 API/前端尚未接线；用户还不能通过网页体验这些新增能力。

## 环境与操作范围

- Windows 本机 PostgreSQL **17.11**，psycopg 驱动；专用数据库 `metricsleuth_r2_acceptance`。
- 监听仅 `127.0.0.1:55439`；临时角色 `metricsleuth_test`，本地 trust 认证仅用于隔离验收，不是生产安全方案。
- 测试只读取 `METRICSLEUTH_TEST_DATABASE_URL`，限制本机与专用库名；没有读取应用 `.env`、`DATABASE_URL` 或真实凭据。
- Docker Desktop 启动失败后采用官方 Windows 二进制 zip（[PostgreSQL 下载入口](https://www.postgresql.org/download/windows/)、[EDB binary archives](https://www.enterprisedb.com/download-postgresql-binaries)）。Unicode 临时路径导致初次 initdb 找不到资源，改为 ASCII 路径后成功；没有重置 Docker 或修改系统服务。
- 当前保留的测试实例目录：`D:\Rag\Agent\metricsleuth-test-pg-61dc9486`，位于 Git 仓库外。下载/解压缓存亦在仓库外；没有提交二进制、数据库数据或日志。验收后已停止实例，不删除数据。

## 实际结果

测试文件：`backend/tests/test_postgres_persistence_integration.py`。

| 场景 | 实际结果 |
|---|---|
| 001–003 migrations 新库执行并重复执行 | PASS，PL/pgSQL 与约束由实际数据库执行 |
| 完整受控调查保存与新连接读取 | PASS，Trace/Observation/Evidence/Diagnosis/引用关联各一条，来源版本和查询引用保留 |
| Runner 异常 | PASS，failed + 固定 code，原始异常文本不入库，Diagnosis 为零 |
| queued→failed | PASS，领域状态与实际 SQL 一致 |
| 数据源身份保护 | PASS，provider/environment 冲突 upsert 拒绝；无引用情况下直接修改 source_id/provider/environment 仍被触发器拒绝；同身份元数据更新允许 |
| 来源隔离 | PASS，不同 Run 的 source/environment 组合写入被外键拒绝 |
| 完成事务中途 Diagnosis 唯一键冲突 | PASS，先前插入的所有事实回滚为零，Run 仍 running；失败前序不会误标成功 |
| Observation 含原始错误文本 | PASS，数据库值为 `error_message=NULL`、`error_code=tool_error` |
| PostgreSQL 停止并重启，再读取同一成功 Run | PASS，succeeded、Diagnosis 一条、data_version/query_reference 保留 |

最终专项原始输出：`Ran 7 tests in 1.811s / OK`。此前首轮六项也通过；补充错误文本案例后运行最终七项。

离线回归独立运行：`Ran 535 tests in 18.054s / OK (skipped=1)`；文件冻结后的主线程最终复跑为 `Ran 535 tests in 22.036s / OK (skipped=1)`。未配置专用 DB 变量，数据库集成类跳过；没有真实模型执行。测试中出现的 Benchmark/Live verifier 文本属于 Mock/Hermetic 脚本输出，不能作为真实调查证据。

数据库重启复验输出：`RESTART_READ_PASS: same run succeeded, diagnosis_count=1, version/reference retained= True`。手动复验最初用了错误的列名 `run_id`/`created_at`，SQL 失败；按实际 Schema 改为 `investigation_run_id`/`requested_at` 后重新完成停止、启动和读取。没有因此修改 Schema。

两轮专项累计保留 15 个 Run：failed=4、running=6、succeeded=5；Tool Calls=6、Observations=6、Evidence=5、Diagnoses=5。running 是来源隔离/回滚测试的预期留存，不代表已实现 Worker 恢复。重复测试使用 UUID，不删除或覆盖前次数据，行数随重跑增长。

## 复现

前提：Python 后端依赖已安装。准备已解压的 PostgreSQL 17.11 Windows binaries，在仓库外选择一个**新的 ASCII 专用目录**。以下是本次环境参数，不要用于生产库；如目录已有数据，跳过 initdb/createdb，只启动既有实例。

```powershell
$acceptanceRoot = 'D:\Rag\Agent\metricsleuth-test-pg-61dc9486'
# 首次初始化（只能对新建的隔离目录执行）：
& "$acceptanceRoot\pgsql\bin\initdb.exe" -D "$acceptanceRoot\data" -U metricsleuth_test --auth=trust --encoding=UTF8 --locale=C
& "$acceptanceRoot\pgsql\bin\pg_ctl.exe" -D "$acceptanceRoot\data" -l "$acceptanceRoot\postgres.log" -o '-h 127.0.0.1 -p 55439' -w start
& "$acceptanceRoot\pgsql\bin\createdb.exe" -h 127.0.0.1 -p 55439 -U metricsleuth_test metricsleuth_r2_acceptance
```

在仓库 `backend` 执行，专项自行应用 migrations 001–003 两遍：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:METRICSLEUTH_TEST_DATABASE_URL = 'postgresql://metricsleuth_test@127.0.0.1:55439/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_persistence_integration -v
# 保存/检查 $LASTEXITCODE，必须为 0 且实际运行七项，不接受 Skip 作为数据库通过。
Remove-Item Env:METRICSLEUTH_TEST_DATABASE_URL
python -B -m unittest discover -s tests -p 'test_*.py' -q
```

进程重启复验（仍在 backend，只读回已有 Run，不生成新结果）：

```powershell
$selectedRun = & "$acceptanceRoot\pgsql\bin\psql.exe" -h 127.0.0.1 -p 55439 -U metricsleuth_test -d metricsleuth_r2_acceptance -At -c "SELECT investigation_run_id FROM app_state.investigation_runs WHERE status='succeeded' ORDER BY requested_at DESC LIMIT 1;"
if ($LASTEXITCODE -ne 0 -or -not $selectedRun) { throw 'No persisted successful run available.' }
$env:METRICSLEUTH_RESTART_RUN_ID = $selectedRun.Trim()
& "$acceptanceRoot\pgsql\bin\pg_ctl.exe" -D "$acceptanceRoot\data" -m fast -w stop
& "$acceptanceRoot\pgsql\bin\pg_ctl.exe" -D "$acceptanceRoot\data" -l "$acceptanceRoot\postgres.log" -o '-h 127.0.0.1 -p 55439' -w start
python -B -c "import os, psycopg; from app.persistence import ApplicationStateRepository, RunStatus; c=psycopg.connect('postgresql://metricsleuth_test@127.0.0.1:55439/metricsleuth_r2_acceptance'); rid=os.environ['METRICSLEUTH_RESTART_RUN_ID']; r=ApplicationStateRepository(c).get_investigation_run(run_id=rid); assert r and r.status == RunStatus.SUCCEEDED; n=c.execute('SELECT count(*) FROM app_state.diagnoses WHERE investigation_run_id=%s',(rid,)).fetchone()[0]; assert n==1; assert r.data_version and r.query_reference; print('RESTART_READ_PASS'); c.close()"
# 每步检查退出码；验收完成后停止专用实例，保留数据供复验：
& "$acceptanceRoot\pgsql\bin\pg_ctl.exe" -D "$acceptanceRoot\data" -m fast -w stop
```

## 剩余限制与下一门槛

- 无 Worker、失败前事实增量保存、任务领取/中断恢复；不以数据库重启读取代替 Worker 恢复验收。
- 未验证产品任务 API、真实模型、完整 AnalyticsTools 数据调查、外部接入及持续同步。
- 错误字段保护不是任意字符串通用脱敏；外部响应、API 与日志仍必须审查。
- 下一阶段 R2-005b 复用此环境，验收最小 Worker 与失败前 Trace/Observation 留存，不增加 Redis/Kafka 或通用调度系统。
