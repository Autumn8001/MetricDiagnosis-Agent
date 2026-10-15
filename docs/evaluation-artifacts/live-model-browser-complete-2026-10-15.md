# 同进程真实浏览器调查闭环通过（2026-10-15）

## 结论

用户新授权的唯一一次模型调查通过：真实Edge在React生产构建中提交，经同一FastAPI进程、PostgreSQL Worker、OpenAI Agents SDK与实际Analytics SQL生成持久Diagnosis；浏览器轮询到成功，刷新后取得新的终态详情，展示相同证据引用，再向仍存活API确认完成。服务与浏览器脚本均exit0，安全日志有 `browser_readback_accepted`。这关闭的是完整同进程浏览器Synthetic执行gate，不是整个MVP或重复语义评测gate。

## 实际证据

| 字段 | 实际值 |
|---|---|
| 基线 | `3f8c1b5`，加本轮浏览器manifest契约修复 |
| Source | `b5c8845f-e138-4927-9121-bf09e68b419f` |
| Run | `607bb0f8-7016-4214-be2d-a965c906876f` |
| 数据 | 本机隔离PostgreSQL，synthetic/sandbox |
| 数据版本 | `synthetic-live-browser-acceptance-2026-10-15-v1`，标签不是不可变快照 |
| 模型配置标识/接口 | `gemini-3.8-flash-high` / chat_completions；未独立核验上游实际模型身份 |
| 限制 | 单请求120秒，最多8工具/10轮，零自动重试、远程tracing关闭 |
| 实测轮次/工具 | 6轮 / 5次工具调用 |
| Runner实测耗时 | 115843ms，多轮整体时间 |
| 持久Tool/Observation/Evidence/Diagnosis | 5 / 8 / 6 / 1 |
| 诊断 | sales / diagnosed / conversion_rate |
| 当前值/前7日基线/相对变化 | 80.00 / 100.00 / -0.2 |
| Scope | marketplace=US、traffic_source=test；asin由提交固定过滤器限定 |
| Token/费用 | 未取得，null，不能填0 |

此fixture只含指定asin的受控变化，并非三场景评测集；缺少独立负对照总体，Scope正确率未评测。数据层贡献不证明外部业务原因。

## 预算与预检修复

最初浏览器在提交前报 `manifest_keys`：后端新增超时字段，而严格前端allow-list未同步。这是验收脚本契约遗漏，本轮修复并增加反例测试；未放开未知字段。首次服务随后达到存活时限，第二次浏览器前置读取报 `browser_catalog`。原服务句柄确认exit1，安全日志无Worker事件；实际数据库确认原source `2c0ee235-6f5a-49ee-9830-edd59805b49d` 下Run数为0。

确认没有任务/模型执行后，才启动新服务并立即衔接浏览器。授权仅消耗成功Run一次，没有因观察超时重启已有任务，没有删除首轮fixture/失败日志。修复不涉及产品Runtime、提示词、业务功能、CPA或模型切换。

## 持久化与语义回算

服务退出后，新PostgreSQL连接以repeatable-read/read-only事务复核Diagnosis及计数，并复用现有评分器：

```powershell
# 原隔离PG显式启动后，从backend执行；只读、没有模型调用：
python -B scripts/score_persisted_task.py --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance --source-id b5c8845f-e138-4927-9121-bf09e68b419f --run-id 607bb0f8-7016-4214-be2d-a965c906876f --data-version synthetic-live-browser-acceptance-2026-10-15-v1 --expected-metric sales --expected-status diagnosed --expected-driver conversion_rate
```

实际exit0，provenance/目标/状态/Driver通过；4/4声明支持，unsupported_claim_rate=0。Scope准确率、停止时机、Token/费用明确为未评测/未知。一个已知样本的4条声明不是4次独立实验或整体模型准确率。

Run/Tool/Observation/Evidence/Diagnosis最终计数194/146/199/92/74，前一笔193/141/191/86/73；仅增加1/5/8/6/1。未改写历史失败记录。[之前60秒超时](live-model-browser-timeout-2026-10-15.md)仍保留；本次成功不证明延长超时是唯一原因，也不保证未来不会超时。

## 记录、检查及下一步

仓库外安全日志：`D:/Rag/Agent/metricsleuth-browser-20261015-timeout120-safe-2.jsonl`，含启动限制、来源、Worker成功遥测及浏览器确认。未提交的首轮日志为同目录 `metricsleuth-browser-20261015-timeout120-safe.jsonl`，两份均保留。

截图：`D:/Rag/Agent/metricsleuth-live-browser-timeout120-20261015/live-model-browser-task-desktop.png`，已人工检查，显示完成状态、来源、指标原值及步骤；刷新与屏幕外引用由脚本读取DOM验证，不仅依赖截图。

本轮前端build、manifest/引用/刷新读取共4项离线断言及lint通过。后端源码未改，本轮未重跑后端全量；此前18项harness守卫是历史离线证据。临时API/浏览器已退出，隔离PG已正常停止、数据保留，端口55440/8014无监听。未改main、merge、部署或操作生产。

下一步优先[三场景小样本评测](sandbox-evaluation-plan-2026-10-15.md)，拟议6次调用未获预算，不能复用本次授权；Shopify开发店/应用/read_orders仍待准备，按[资源指南](../shopify-orders-probe.md)先做实际字段gate，再最小同步。MVP仍缺持续外部数据、重复语义/停止评测、usage及生产安全部署验收。
