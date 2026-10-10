# 真实模型持久调查：一次授权尝试未通过

日期：2026-10-10。基线：`15f2baebd5710a285f841a38b801617ae5d0aa5b`，加一次性验收脚本。

## 结论

**真实模型验收未通过。** 用户明确授权复用本机现有模型配置，执行一次隔离 Synthetic 调查，最多8次工具调用/10轮。主线程只运行一次，客户端禁用自动重试；未追加模型探测、重跑或更换模型。

SDK 返回 `InternalServerError`。没有已完成的模型轮次或工具结果，不能宣称模型成功执行、动态调查或 Evidence/Diagnosis 已通过真实模型持久化。SDK 异常类型不足以确定端点故障根因、服务商是否内部执行或实际费用；没有检查控制台账单。

真实数据库成功保存失败状态；新应用实例/新连接读取一致，未伪造缺失的 Trace、Observation、Evidence 或 Diagnosis。此前 [Olist SQL/步骤验收](olist-persistence-acceptance-2026-10-10.md) 是另一次受控 Runner 验证，不是本次模型结果。

## 配置与安全范围

- PostgreSQL 17.11，`127.0.0.1:55440` 的专用 `metricsleuth_r2_acceptance`；没有生产、外部业务库或 Shopify 调用。
- `openai-agents 0.22.0`、`openai 3.5.0`、`psycopg 3.3.4`。
- 显式读取被 Git 忽略的本机 `.env`，只采用现有 API key、端点、API模式与模型名；未打印或提交这些原始配置。实际模式 `chat_completions`，自定义端点，沿用原模型。模型配置字符串 SHA-256：`ab92b864a47dcb51ad091da3dc8e5b1e538edb2170789fa7a30edd21ad7f222a`；没有保存密钥指纹。
- 客户端 `max_retries=0`、单请求 timeout 60秒；SDK 工具预算8、轮次预算10。次数/超时不是费用硬上限或整个调查的 wall-clock 硬上限。
- 原有 Source Runner 使用 `RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)`；验收进程也关闭追踪，客户端不用于 tracing。保留本机步骤保存而不导出远程追踪，符合 [SDK observability 配置](https://developers.openai.com/api/docs/guides/agents/integrations-observability) 的控制方式。Synthetic 指标仍会在实际模型请求中发送，不能把禁用 tracing 解释为完全不发送数据。
- 原始异常、连接信息与外部响应均不打印、不落数据库。未改 Runtime/Prompt/领域校验来迎合本次失败。

## 实际链路与结果

脚本：`backend/scripts/verify_live_task_persistence.py`。执行前确认没有 queued/running Worker 任务，仅插入一个 UUID 产品和2026-10-03至10八行 Synthetic 数据，不迁移、不替换已有数据。

fixture：US/test，baseline每日 sessions100、orders10、sales100；target sessions100、orders8、sales80。这是人为受控指标变化，不是外部业务事实或 Benchmark Ground Truth 输入。

```text
POST /api/investigations 202 queued
→ Worker running → 既有 Agents SDK 请求
→ InternalServerError（无完成工具结果）
→ failed / execution_failed
→ 新应用实例/新连接读取同一失败记录
```

| 项目 | 本次实际结果 |
|---|---|
| Run | 3e3f7f94-d13c-4cb4-84cc-9c0b0e162cf7 |
| Source | adc12517-8bc8-44d9-9155-c458ed9cfd14 |
| Fixture product | 511c0c9b-8c49-40b7-9170-ced5dcd3466e（新生成的测试 ID） |
| Data version | synthetic-live-acceptance-2026-10-10-v1（标签，非数据库快照） |
| Script exit | 1，失败，不是验收通过 |
| Status / safe failure | failed / execution_failed |
| Completed model turns | 未获得可验证值；不是0轮成功执行 |
| Tool Call / Observation / Evidence / Diagnosis | 0 / 0 / 0 / 0 |
| Fresh application reread | PASS |

主线程随后实际 SQL 检查：`failure_details = {"code": "execution_failed"}`，无原始异常；fixture八行、总sales780.00、总orders78；活动 Worker 任务0。隔离数据保留，不自动删除。

本阶段验收结束后已停止本机55440测试实例，数据目录保留在仓库外；没有重启/部署线上服务。复验需要先启动同一专用测试实例。

## 复现方法与后续边界

命令在仓库根目录执行；**每次运行都可能产生外部计费并创建新任务，不能作为离线回归自动执行。此次一次性授权已经使用，重跑须获得新的明确授权。**

```powershell
python -B backend/scripts/verify_live_task_persistence.py --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance --model-env-file .env --allow-model-call
```

URL守卫只允许专用loopback库，缺授权flag/配置文件/既有表或有其他活动任务时拒绝；脚本不迁移、不发现生产配置，不会自动重试。

下一步先确认现有端点/模型可用性，再安排经授权的完整真实调查与 Evidence/Diagnosis 持久化验收。本次失败不构成重写 Runtime、引入第二套 Harness 或自动更换提供方的依据。R2 的真实模型成功 gate 仍未通过，R3持续外部数据、原型前端接线与安全部署也未完成。

## 最终离线验证

主线程：后端全回归 `Ran 598 tests / OK (skipped=3)`，两个验收脚本守卫专项13/13 PASS。三个 PostgreSQL 类在全回归中因未配置专用变量跳过，真实数据库23/23回归此前另行执行通过。

一次实际调用后仅整理验收脚本的重复输出投影/连接管理，并新增安全HTTP状态字段守卫；没有改业务核心或再次调用模型。本次错误记录没有采集HTTP状态整数，不能用后增字段补写历史响应。离线守卫不等同于真实模型验收。
