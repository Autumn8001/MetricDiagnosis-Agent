# 真实浏览器调查：已捕获超时（2026-10-15）

## 结论

用户新授权的1次调查已执行，浏览器实际提交后，Worker/SDK完成5次工具查询并保存8条Observation，随后 `APITimeoutError`，任务为 `failed / execution_failed`。没有Evidence/Diagnosis。完整同进程真实模型浏览器成功gate仍未通过；不把工具查询成功或失败读取当作完整调查成功。

本次比[上一笔失败](live-model-browser-failure-2026-10-15.md)增加了可核查的异常类型和仓库外持久日志。不能反推上一笔也是同一原因。没有自动重试、新调查、外部业务数据访问或生产操作。

## 实际证据

| 字段 | 实际值 |
|---|---|
| 代码基线 | `1e78ddf`，分支 `codex/r5-004-validation` |
| 来源 | synthetic / sandbox，隔离本机 `metricsleuth_r2_acceptance` |
| Source | `fa2a9715-efae-4ae9-8e66-dc56179cf7c0` |
| Run | `46a51b06-ae7f-4f5d-8f19-0bd0a031d544` |
| 数据版本 | `synthetic-live-browser-acceptance-2026-10-15-v1`，输入标签非快照 |
| 日期/目标 | 2026-10-10 / sales；asin由本次fixture唯一绑定 |
| 配置模型标识 | `gemini-3.8-flash-high`；这是客户端配置，非独立核验上游实际模型身份 |
| 接口模式 | 沿用现有配置；本笔安全日志未单独保存该字段 |
| 客户端限制 | `AsyncOpenAI(max_retries=0, timeout=60)`；8工具/10轮；远程tracing关闭 |
| SDK异常 | `APITimeoutError`，未取得HTTP状态码 |
| Runner实测耗时 | 84167ms，多轮整体耗时，不是单请求耗时 |
| 数据库任务起止 | `2026-10-15T20:15:29.524532+08:00` → `2026-10-15T20:16:53.815457+08:00` |
| 已持久工具/观察/证据/诊断 | 5 / 8 / 0 / 0 |
| Token/费用/总轮次 | 未获得，保持null；工具持久数量不是全部模型请求数量 |

安全日志：仓库外 `D:/Rag/Agent/metricsleuth-browser-20261015-next-safe.jsonl`，本次确认实际包含 `acceptance_started`、`server_ready`、`worker_finished`、`acceptance_failed`。`worker_finished.telemetry.exception_type=APITimeoutError`；没有原始异常消息、鉴权配置、Prompt或服务响应。日志独占创建，未覆盖旧证据。

真实浏览器脚本终态为 `browser_task_failed`，exit1；服务保存失败事件后exit1。没有同进程成功回读确认事件。随后使用新只读PostgreSQL连接核对终态和步骤，5个工具均为succeeded：query_metric、query_related_metrics、query_metric、query_metric、query_metric。不是独立浏览器刷新重开验收，本次未生成成功截图。

只读数据库全表计数按Run/Tool/Observation/Evidence/Diagnosis为193/141/191/86/73，相比前一记录192/136/183/86/73只增加本笔任务及步骤。未迁移、重置或删除历史数据。

## 可复算检查与边界

从backend可只读复算本笔失败（先显式启动原隔离测试PG；不启动Worker、不调用模型）：

```powershell
python -B scripts/score_persisted_task.py --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance --source-id fa2a9715-efae-4ae9-8e66-dc56179cf7c0 --run-id 46a51b06-ae7f-4f5d-8f19-0bd0a031d544 --data-version synthetic-live-browser-acceptance-2026-10-15-v1 --expected-metric sales --expected-status diagnosed --expected-driver conversion_rate
```

实际exit1，`sample_count=1`、`execution_succeeded=false`、`semantic_evaluated=false`；没有伪造Driver/Scope得分或Diagnosis。缺少完整诊断引用链时 `provenance_passed=false` 不等于已保存的工具记录丢失。此次没执行三场景重复实验，也不是holdout。

前端生产构建实际通过。业务源码没有修改，没有为本次运行增加测试；此前17项日志守卫是离线证据，本次实际日志落盘补充了真实执行证据。验收API/浏览器脚本均已退出，隔离PG已正常停止、数据保留。

## 判断与下一步

已确认这笔调查在客户端等待模型响应期间超时。单请求60秒与整体84秒不能证明是服务故障、连接中断、慢推理或输出过长；没有原始网络阶段或CPA服务日志，不进一步推断。也不据此宣称端点不可用——本次此前已经完成多轮实际工具交互。

先向用户报告这一具体限制。下一次需要新预算，并明确是否接受较长的有限单请求/整体验收时限，或检查CPA服务端的对应超时记录；不擅自变更模型、CPA服务或其他账号。不通过提高重试次数掩盖失败。真实外部源仍依赖开发店/应用/read_orders，部署与稳定重复评测仍未通过。
