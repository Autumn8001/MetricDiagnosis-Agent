# R2-005b1：最小 Worker 与调查步骤保存验收

日期：2026-10-10。代码基线：`71e284fefe46258e747f057f2ce29986b0931b88` 加本切片提交；本地 main，原审查快照不变。主线程复核所有 diff 并亲自执行测试。

## 本次实际能力

调查可排队并被一个 Worker 领取；每个已完整生成的工具步骤独立保存。后续 Runner 报错或 Worker 进程突然退出，已经提交的 Tool Trace/Observation 不丢失。新 Worker 将中断任务标记失败，不重复执行，不伪造 Diagnosis。

这是未来“调查进度、失败详情和历史”的后端基础，**不是已经可在网页使用的功能**。没有新增调度平台、Redis/Kafka、第二 Runtime、后台常驻进程或部署。

实际流程：

```text
submit → PostgreSQL queued(worker)
run_once → 单 Worker session lock → 恢复遗留 Worker running → 行锁领取
         → 事务已提交 → injected Runner
         → 每个完整工具结果：checkpoint 短事务 → Tool Trace + Observation
         → 成功：验证完整 Summary → Evidence + Diagnosis + succeeded
         → 异常：受控失败码 + failed，保留既有步骤
进程中断 → 锁随连接释放 → 新 Worker 安全终结，不自动重放
```

## 实现与约束

- `backend/app/persistence/worker.py:InvestigationWorker`：submit/run_once，显式 connection factory 与 Runner；session advisory lock 保证单 Worker，`FOR UPDATE SKIP LOCKED` 每次领取一个任务。持锁连接保持 session，但 Runner 期间没有未提交事务。该连接必须独占，不可归还共享池。
- `004_worker_execution_mode.sql`：仅新增 inline/worker 标识，现有任务默认 inline；Worker 恢复不修改 inline 调查。
- `Coordinator.checkpoint()` / `Writer.checkpoint()`：在独立事务中锁定 running Run，并验证 source/environment/data_version。只保存已有工具事实，不创建 Evidence/Diagnosis。
- Repository 的可选幂等写入：同 ID 所有显式列相等才可重放，不允许冲突静默忽略或更新事实。
- `Writer.complete(checkpointed=True)`：禁止遗漏已经提交的步骤，核对重放内容并保存最终结果；完成事务失败不删除此前步骤，也不盲目二次覆盖状态。
- SDK 三个原有 FunctionTool 支持可选同步 progress_callback，参数取 ToolContext 原始 JSON，Observation 来自同一返回 payload。回调失败向外传播；Prompt、预算、动态调查决策与最终验证不变。
- 尚未完成的工具调用（例如查询直接抛异常、尚未产生完整 payload）不被伪造为已完成步骤。未实现每个模型 token 或工具开始事件的持久化。

## 运行证据

环境：隔离 PostgreSQL **17.11**，psycopg。旧实例 `127.0.0.1:55439` 用于升级回归；另新建空集群 `127.0.0.1:55440`，专用库均为 `metricsleuth_r2_acceptance`。没有读取应用 `.env`/DATABASE_URL，没有生产连接或模型 API 调用。

| 验收 | 结果与证据 |
|---|---|
| 旧库 migrations 001–004 重复执行 | PASS，原数据保留 |
| 空集群首次迁移及重复执行 | PASS，14 项完整运行；随后扩展到最终 15 项重复运行 |
| 最终真实数据库专项 | `Ran 15 tests in 8.317s / OK` |
| 既有持久化回归 | 原七项包含在专项中：身份保护、状态、来源隔离、成功/失败、回滚、重连、安全错误文本 |
| checkpoint 重放/冲突 | PASS，同事实只留一条；内容/参数冲突、错误版本、终态写入拒绝；新 Tool 插入后 Observation 冲突，整个步骤回滚 |
| 最终 Summary 遗漏已存步骤 | PASS，拒绝完成，保留步骤和 running，无 Diagnosis |
| Worker 独占与短事务 | PASS，Runner 内启动竞争 Worker 未调用其 Runner；pg_stat_activity 无 idle in transaction |
| 队列行锁与重复提交 | PASS，被锁的 queued 行被跳过，解锁后领取；重复 run ID 提交拒绝，无重复执行 |
| Runner 在保存步骤后异常 | PASS，failed + execution_failed，Trace/Observation 保留，Evidence/Diagnosis 为零，原始异常不入库 |
| 真实子进程突然退出 | PASS，子 Worker checkpoint 后 `os._exit(23)`，不走正常 finally；父进程读回 running 与事实，新 Worker 改为 worker_interrupted，不再调用 Runner |
| inline 隔离 | PASS，Worker 恢复不会修改 inline running |
| autocommit 错误配置 | PASS，生命周期写入前拒绝，未创建 Run |
| 全量离线回归 | 初次 `Ran 552 tests in 16.661s / OK (skipped=1)`；最终复跑 `Ran 552 tests in 15.761s / OK (skipped=1)`；专用 DB 未配置，数据库测试类跳过 |
| SDK 进度回调专项 | 5/5，真实 FunctionTool invocation + Fake Analytics；原始参数、三类工具、失败传播、默认行为；无模型 |

主线程初次专项用了错误的测试模块简称，unittest 报 ImportError；随后旧 FakeWriter 未接收新增 checkpointed 参数出现两项 TypeError，更新测试替身合同后，Writer/Coordinator 与新增 Repository/Worker 专项 34/34 通过。没有通过删除断言或改业务规则规避失败。

## 复现命令

测试实例准备方法沿用 [R2-PG 记录](postgres-persistence-acceptance-2026-10-10.md)。本次新实例数据目录为仓库外 `D:\Rag\Agent\metricsleuth-test-pg-61dc9486\data-worker-fresh`；使用同目录的 pgsql binaries，启动端口改为 55440。已有实例直接启动，不再次 initdb。测试保留 UUID 记录，不执行 DELETE/TRUNCATE/DROP。

在仓库 backend：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:METRICSLEUTH_TEST_DATABASE_URL = 'postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_persistence_integration -v
# 必须实际运行15项且退出码0；未配置/Skip不是数据库通过。
Remove-Item Env:METRICSLEUTH_TEST_DATABASE_URL
python -B -m unittest discover -s tests -p 'test_*.py' -q
```

只使用隔离本机库；本地 trust 认证为验收便利配置，不得复制到部署环境。测试结束停止两个专用实例，保留数据与日志在仓库外，未提交二进制或数据。

## 未验收与下一阶段

- Controlled Runner 查询真实 SQL，但输入仍是受控数值，不是外部经营数据。
- SDK callback 已接线并离线测试，尚未完成真实模型→SDK→Worker→数据库的联合验收。
- 当前 Worker 是可调用的 submit/run_once 实现，没有常驻进程启动、轮询间隔、健康检查或部署接线。
- 无产品任务/历史 API、网页进度、用户取消/显式重试、外部持续同步；不能称为完整 MVP。
- 下一切片 R2-005b2 优先接最小任务/状态/步骤/历史 API，继续使用真实 PostgreSQL 验收，配置明确后再测真实模型。
