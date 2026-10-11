# R4-006 单指标只读接口验收

## 结论与边界

已实现 GET `/api/metrics/observation`，由服务端绑定来源/Registry/连接工厂，只接受source_id、target_metric、规范target_date。经既有AnalyticsTools和Observation mapper读取实际PostgreSQL单日值及前七日基线。不运行模型/Worker、不创建调查、不执行迁移/种子写入、不调用Shopify、不读取`.env`。

HTTP使用FastAPI TestClient，不是独立HTTP进程或浏览器验收。数据是已有Synthetic稳定fixture及公开静态Olist，不是持续外部经营数据。页面本轮未改，指标页仍为能力目录。版本是label，不是snapshot；query_reference仅用于本次响应，不是已持久保存的Tool Call/Evidence。异常候选是现有下降阈值规则，不是Agent Diagnosis。

## 实际数据库结果（主线程执行）

隔离PostgreSQL，仅127.0.0.1:55440，测试role为metricsleuth_test；使用仓库外已有测试cluster。按专用端口启动，未连接生产。专项4/4 PASS：

| 检查 | 实际结果 |
| --- | --- |
| Synthetic，sales，2026-10-10 | 当前100.00、基线100.00，normal，candidate=false；第二个新应用实例读回一致 |
| Synthetic，2026-09-01无数据 | current/baseline均null，insufficient_evidence，candidate=null，不伪造0 |
| Olist，merchandise_gmv，2017-03-20 | 当前16861.09、基线13355.61；正向变化按既有mapper为inconclusive，candidate=null |
| Olist sessions / 异源ID | 400 metric_not_supported / 404 source_not_found |

每项测试前后都读取状态计数并比较一致。计数顺序Run/Tool Call/Observation/Evidence/Diagnosis：

- metricsleuth_r4_browser_acceptance：1/1/1/1/1。
- metricsleuth_r2_acceptance：179/117/155/70/70。

## 可复现命令

须保留既有fixture；此测试不会自动创建或重置它们。数据库身份、role、loopback、端口、无密码/额外URL参数均有测试守卫。不满足配置时拒绝；未配置时skip不等于验收通过。

在backend目录运行：

```powershell
$env:METRICSLEUTH_METRIC_SYNTHETIC_TEST_URL='postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r4_browser_acceptance'
$env:METRICSLEUTH_METRIC_OLIST_TEST_URL='postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_metric_read_api -v
```

源码入口：`backend/app/api/metric_read_service.py`、`metric_read_routes.py`、`metric_read_schemas.py`；实际数据库测试：`backend/tests/test_postgres_metric_read_api.py`。离线契约测试覆盖重复/未知/敏感输入的安全422、日期下溢、Decimal/null/空结果、来源与指标预检查、数据库/响应投影脱敏503；不能据此声称真实模型成功。

主线程最终验证：实际PG专项4/4 PASS；与离线API/Runner/应用专项合并31/31 PASS；不带专用数据库变量的全量离线回归 **Ran 649 tests / OK (skipped=4)**。四个跳过类是显式数据库环境未配置，不算数据库通过。离线输出中的模拟注入/Live失败守卫仅为patch测试，不发生本轮数据写入或模型调用。一次全量运行出现asyncio ResourceWarning，最终复跑未复现；未借此增加业务改动。

收尾：主线程已停止本次启动的隔离PG，pg_ctl status确认no server running，55440无监听；既有测试数据保留。没有启动浏览器/API后台服务，没有推送或部署。

## 下一步

将此接口接入既有指标页并做真实PG浏览器验收。模型成功仍受此前401鉴权阻碍，一次性授权已使用；未重试。开发店实际API gate仍待账号/权限资源，未改变MVP成功标准。
