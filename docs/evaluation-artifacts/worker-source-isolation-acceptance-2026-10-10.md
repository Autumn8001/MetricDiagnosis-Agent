# 单源 Worker：领取与中断恢复隔离验收

日期：2026-10-10；基线 `58d7c70fff735d3e85d22d193612b5c24b3bda55` 加本次局部修复。目的：防止绑定一个来源的应用误领或终结另一来源的调查。不是新任务调度系统、真实模型或外部连接器验收。

## 问题与最小修复

原 `task_application.py:build_task_application()` 的 Runner 绑定单一 descriptor，但 `InvestigationWorker` 全局领取 queued、恢复 running。共用 `app_state` 时，另一来源的任务可能先被领取，再因 Source Runner 身份不符而错误失败；全局恢复也可能提前终结另一来源的中断记录。

当前 `worker.py:InvestigationWorker` 新增 `expected_source`：

- `submit()` 在建立连接前检查 source_id/provider/environment，display_name 不作为身份。
- `_claim_one()` 使用固定、参数化来源/环境/provider 谓词；保留原 `FOR UPDATE SKIP LOCKED`。
- `_recover_interrupted()` 只处理绑定来源/环境/provider的 Worker running；查询同时核对不可变来源记录，避免启动时配置了错误provider仍误终结任务。
- `build_task_application()` 始终绑定与 Runner 一致的 descriptor。低层 `expected_source=None` 保留原受控测试兼容行为，不用于显式产品入口。

没有 migration、新表、第二套 Runner、重试平台或新锁机制。原全局 advisory lock 保留，仍是数据库内串行单 Worker；本修复不提供并行调度或混合来源自动路由。

## 主线程真实 PostgreSQL 验收

环境：仓库外 PostgreSQL 17.11，`127.0.0.1:55440/metricsleuth_r2_acceptance`；Synthetic fixture 与 Olist Validation 的独立来源身份。未读取 `.env`、调用模型或连接生产。

测试 `backend/tests/test_postgres_task_application.py`：

| 案例 | 实际结果 |
|---|---|
| `test_source_bound_application_leaves_other_queued_tasks_untouched` | 先排队 Olist，再排队 Synthetic；Synthetic Worker 只处理自己，实际 Analytics SQL 读到fixture sales80。再次领取为空，Olist仍queued、started_at为空、工具数0；Olist Worker随后只处理自己的记录。两次Runner均受控停止，不制造Diagnosis。 |
| `test_source_bound_recovery_does_not_fail_another_sources_running_task` | 两个来源的queued记录在隔离库模拟为running；Synthetic Worker仅终结自己的记录为failed/worker_interrupted，Olist仍running无failure code；Olist Worker随后恢复自己。Runner调用次数0、无伪造Diagnosis。 |
| `test_incorrect_provider_binding_neither_claims_nor_recovers_source_tasks` | 错误provider、相同source_id/environment的Worker既不领取queued，也不终结running，Runner调用0。正确绑定的Owner仍可恢复自己的中断记录。 |

测试只终结本测试生成且未终结的记录，不删除测试数据。受控停止用于隔离测试，不作为模型失败证据。

主线程结果：

- 原应用专项加两项先6/6 PASS，强化外层SQL值/Runner调用次数断言后再次6/6 PASS；主审再补错误provider场景，最终应用专项包含7项。
- 全部持久化/Worker/API/应用实际PostgreSQL回归：26/26 PASS，包含最终应用7项。
- 离线全回归：605 tests / OK (skipped=3)；三个数据库类因未配置专用变量跳过，数据库结果另行验证。
- 单元测试：`test_persistence_worker.py` 覆盖拒绝异源提交、参数化claim/recovery、身份不依赖显示名及低层兼容；`test_task_application.py` 证明产品入口传入同一descriptor。这些离线证据不是数据库隔离或模型运行的替代。

最终SQL确认活动Worker记录0，上次真实模型失败记录仍为原 `failed / execution_failed`。验收后已停止55440测试实例，数据保留在仓库外；没有操作线上服务。

## 复现命令

先按 [隔离测试环境说明](worker-checkpoint-acceptance-2026-10-10.md) 启动55440实例，backend目录执行；只配置专用测试变量，不使用生产连接。

```powershell
$env:METRICSLEUTH_TEST_DATABASE_URL = 'postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_persistence_integration tests.test_postgres_task_api_integration tests.test_postgres_task_application -v
Remove-Item Env:METRICSLEUTH_TEST_DATABASE_URL
python -B -m unittest discover -s tests -p 'test_*.py' -q
```

## 仍未完成的边界

来源队列隔离不等于用户认证、租户授权或任意来源的物理分析数据隔离。当前Profile仍选择固定warehouse/Olist表，不能让两个descriptor共用一张不含source_id的宽表就宣称数据已隔离。`data_version`仍是标签，未冻结数据库快照；分析角色最小权限也需另行验收。

真实SDK成功gate仍未通过，上次一次性授权已消耗，本次没有模型重试。持续外部源、原型接线和生产部署依旧待完成。
