# R4-007：来源绑定的手动指标扫描后端

> 日期：2026-10-11；基线：`e041cfe8fe3755c25ff5be5918a5a6f2786dd33e`，加本次后端接线。
> 范围：配置来源的只读API与隔离PostgreSQL；页面未接线，没有模型或外部平台调用。

## 产品意义与实现

`GET /api/metrics/scan?source_id=...&target_date=YYYY-MM-DD`一次读取当前来源支持的单日指标及前7日基线，提供异常候选，供后续概览/指标页显式手动扫描使用。不自动创建调查或判断Driver/Scope，不设置定时任务，不新增任务调度。

源码：`api/metric_read_routes.py`严格拒绝多余/重复/缺失参数与非规范日期；`MetricReadService.scan()`从Registry和capabilities选择最多5项，并在第一查询前验证全部能力。它复用`read()`、既有AnalyticsTools/Observation mapper和独立只读短事务，不另造计算器；旧Benchmark扫描接口未改。默认无服务503，配置异源404，空/超预算400；任何查询失败返回固定503，不返回半份成功结果。

`MetricScanResponse.items`保留每项Decimal字符串/null、状态、查询引用及时间。候选只包含`anomaly_candidate=true`的指标；候选为空不表示所有指标正常，必须查看各项null/inconclusive/insufficient_evidence。`persisted=false`，`snapshot_consistent=false`，data_version为label；没有新增已保存Evidence、扫描历史或一致性快照。

## 实际数据库证据

主线程显式启动仓库外既有PG17.11，仅127.0.0.1:55440，使用新应用/TestClient GET读取原有隔离fixture。不执行迁移、注入、Worker、模型或Shopify请求。

- Synthetic/sandbox：`metricsleuth_r4_browser_acceptance`，source `3989c537-a555-4828-80e5-28b45a9624fa`，version `synthetic-eight-days-v1`，2026-10-10。5项读取：sales100.00/100.00、orders10/10、sessions100/100、conversion_rate0.1/0.1、aov10.00/10.00；均normal，候选空。
- Olist/validation：`metricsleuth_r2_acceptance`，source `bbaf0fe3-c61a-4d03-acca-4e10b69d24b7`，version `olist-public-raw-files-20261010`，2017-03-20。只读3项，不读取sessions；GMV16861.09/13355.61、orders113/84.42857142857142857142857143、aov149.2131858407079646017699115/158.1882741116751269035532995。现有mapper均给inconclusive/candidate=null，未重定义阈值以制造异常。
- 缺数据日2026-09-01：Synthetic5项均insufficient_evidence，current/baseline/relative及candidate为null，不冒充正常零值。异源拒绝在实际数据库专项覆盖。
- 真实数据类型：Synthetic是受控模拟fixture，Olist是静态公开数据；均不是持续外部数据或真实模型验收。本轮实际SQL未制造新的异常，下降候选的判定另由离线受控结果测试覆盖。

## 失败与验收方法

首次实际数据库组合33项测试有1项失败：新测试误要求缺数据时Observation整体为null；实际聚合SQL返回一条数值为null的insufficient_evidence记录，与既有单指标合同一致。只修正测试，未修改计算器/Mapper/API以迎合断言。

专用环境复现（backend cwd，只读已有上述fixture）：

```powershell
$env:METRICSLEUTH_METRIC_SYNTHETIC_TEST_URL='postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r4_browser_acceptance'
$env:METRICSLEUTH_METRIC_OLIST_TEST_URL='postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_metric_read_api tests.test_metric_scan_api tests.test_metric_read_api tests.test_task_application -v
```

默认未配置时数据库类跳过，不计为数据库通过。离线测试用patch，不称为外部数据验收。前端、Runtime、持久化结构、生产配置和依赖未修改；本阶段后端通过不等于扫描按钮已可在浏览器操作。

## 最终验收与清理

- 主线程重新执行上述组合：34项全部通过，其中7项为实际PostgreSQL读取、27项为离线测试；没有跳过。
- 主线程后端全量离线回归：`python -B -m unittest discover -s tests -p 'test_*.py' -q`，Ran668，OK(skipped=4)，进程exit0。跳过的是需显式配置的数据库专项；输出中的Hermetic评测、受控Trace及负向守卫不是模型运行证据。既有SQL解析fallback与unclosed event loop ResourceWarning仍出现，本轮未扩展修复范围。
- 实际SQL独立核对前后Run/ToolCall/Observation/Evidence/Diagnosis计数：Synthetic库均为1/1/1/1/1，Olist库均为179/117/155/70/70；测试tearDown也逐项校验未变。未新增调查或保存扫描。
- 本轮启动的隔离PG已用准确data-worker-fresh目录停止，pg_ctl确认no server running，55440监听为0；保留数据库和日志，无生产操作。
- 此后端验收切片未改前端，也未重新运行浏览器/build；后续产品切片再按冻结原型接手动扫描入口，并单独验收真实API到页面行为。客户端准备的后续验证另见下节。

## 后续客户端合同切片（2026-10-11，离线验收）

基线`1c4d2914540ed17da1e08bb7e0a2ca720ad8989b`之后，仅增加`frontend/src/metrics/contracts.ts`的MetricScanResponse、`client.ts`的createMetricClient.scan以及`tests/metric-client.test.mjs`。没有改页面/CSS/后端/配置/依赖；上节数据库验收是前一提交的记录，本切片没有再次访问PG、模型或Shopify。

客户端发送GET且只含source_id/target_date，与read共用安全请求/JSON/Abort处理，无自动重试。整批响应先验证顶层字段与UTC完成时间、1–5项边界、每项来源/日期/provider/environment/version一致、指标及查询引用唯一，再复用单指标Observation/Decimal/null校验；候选列表必须按items顺序精确匹配所有true项，不能缺失、重复或伪造。snapshot_consistent/persisted只允许false；不猜测币种或重算异常阈值。

主线程审查完整diff，并在frontend cwd亲自执行：

```powershell
npm run test:metrics
npm run test:tasks
npm run lint
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json
npm run build
```

结果：指标客户端58/58（包含原31项）、任务客户端18/18，lint/类型/build均exit0；git diff --check通过。客户端测试使用注入fetcher与JSON响应，属于离线合同验证，不是浏览器、实际HTTP或真实数据运行。build生成忽略的dist产物，不部署。没有修改原有测试结论或将受控响应称为真实模型数据。

Current限制：没有扫描按钮、页面结果或新的浏览器验收；client仅保证响应内部一致，不证明来源目录中的provider/environment/version或能力集与响应一致。后续页面必须额外核对目录、处理取消/过期响应、显示每项不确定状态并显式带入调查，不能自动POST。真实模型401、Shopify资源及持续外部数据阻碍未解除。
