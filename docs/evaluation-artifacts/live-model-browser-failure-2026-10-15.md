# 单次真实浏览器调查未通过（2026-10-15）

## 结论

本次用户重新授权的一笔隔离Synthetic调查实际启动了模型工具链，但最终持久化为 `failed / execution_failed`。已保存5次工具调用、8条Observation，Evidence和Diagnosis均为0。**完整同进程浏览器真实模型验收未通过**，没有以回读成功替代调查成功。

授权仅限本笔调查、最多8次工具调用/10轮、无自动重试或远程tracing；未访问生产或Shopify。一次性授权已经使用，没有追加第二笔调查。已存工具记录数不代表包括失败尝试在内的完整请求数；本次未留存可核验的总轮次、Token或费用，均不得填为0。

## 实际证据

| 字段 | 值 |
|---|---|
| 调查基线 | `0021320`；安全计数遥测为本次失败后的改进，未以新模型调用复验 |
| Run | `fce5859c-01f0-4a24-920b-06b7f03d5523` |
| Source | `38a95d82-85e9-45bc-be0c-6143e757c3ef` |
| Fixture asin | `68cbab34-bb38-4e40-a513-192fff918225` |
| 日期/指标 | 2026-10-10 / sales |
| 版本 | `synthetic-live-browser-acceptance-2026-10-15-v1`，标签而非快照 |
| API模式 | chat_completions |
| 模型身份 | 沿用本机现有配置；本笔没有保留独立可核验标识，不用历史Gemini别名冒充本次核验 |
| 状态/安全码 | failed / execution_failed |
| Tool/Observation/Evidence/Diagnosis | 5/8/0/0 |
| 持久任务执行时长 | 83.353655秒，finished_at减started_at，非纯模型耗时 |
| Token/费用/总轮次 | 未获取 |

已持久化的工具顺序：sales query_metric → sales query_related_metrics → conversion_rate按marketplace → 按traffic_source → 按marketplace和traffic_source联合查询。已有Observation包含sales80/100与orders8/10等实际SQL结果；任务未得到可持久化的最终Diagnosis。

观察期间曾确认两个运行句柄和 `running / 5工具 / 8观察`。后续工具等待被中断，重新检查时两个句柄均不存在，原API/数据库也已无监听。检查实际进程后只重启**原隔离测试PG**读取持久记录，没有重新运行Worker或模型。数据库证据确认终态failed，并非仅因观察超时推断任务失败。

额外的直接配置预检命令被自动审批以 `blocked by policy` 拒绝，未执行且未消费模型调用；后续使用原有显式harness入口获准执行。本笔失败的原始异常类型未保存，现有证据不足以判定是上游超时、结构化输出还是最终校验失败；不把任一猜测写成根因。

## 无新模型的桌面失败回读

独立 `task_application api` 绑定同一source/version，仅浏览器读取；没有启动Worker。真实Edge + production build + 只读代理显示失败前的工具/观察，刷新后重开通过：5/8/0/0。

首次只读脚本预检把“失败”硬绑定为Olist/validation，因此拒绝了本次Synthetic/sandbox；现已将允许的两个来源/环境组合与任务状态解耦，保留严格allow-list、指定source/run和禁止写请求。随后同一既有Run回读通过，没有重提任务。

```powershell
# 已有隔离PG和绑定本记录source的只读API运行时，从frontend执行：
node scripts/verify-postgres-workspace.mjs --api http://127.0.0.1:8015 --source 38a95d82-85e9-45bc-be0c-6143e757c3ef --run fce5859c-01f0-4a24-920b-06b7f03d5523 --expect failed --output D:/Rag/Agent/metricsleuth-live-browser-final-20261015
```

截图在仓库外 `D:/Rag/Agent/metricsleuth-live-browser-final-20261015/postgres-workspace-desktop.png`，已人工查看。最终应用表计数按Run/Tool/Observation/Evidence/Diagnosis为192/136/183/86/73，相比之前191/131/175/86/73只增加本次实际任务和完整步骤。没有删除、重置、替换历史记录或伪造结论。

## 后续改进与限制

验收harness已补安全遥测：配置模型仅对白名单别名输出；异常只记录类名、有效HTTP整数状态码和耗时，不记录原异常、响应、Prompt或凭据。成功时保留可核验轮次/工具次数；失败时不可获取值仍为null。Worker结束即输出安全事件，避免仅在成功确认后输出；后续启动应将安全stdout保存至仓库外验收日志，以免观察句柄丢失造成证据缺口。

浏览器收到failed终态后立即失败，不再等待成功超时；服务为失败回读保留15秒后退出。没有降低Diagnosis或证据校验，也没有开启默认重试。这些改进仅经过离线/受控回归，**没有用第二笔模型调用复验**。

改进后离线回归：后端全量712项，OK(skipped=6)，其中遥测守卫13项和语义回溯8项通过；前端读取断言3项、lint及生产构建通过。全量仍有既有event loop ResourceWarning及依赖弃用警告。跳过的数据库专项不算本次真实数据库测试通过；真实数据库证据是上文明确记录的既有Run读回。

临时只读API与测试PG均已停止，数据保留。真实外部源、重复评测、停止时机和生产部署依然未完成。
