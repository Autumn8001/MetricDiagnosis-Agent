# MetricSleuth Project Status

> **浏览器提交真实模型任务（2026-10-15）**：桌面浏览器已经实际提交一笔带明确 `asin` 范围的 Synthetic 任务，经 FastAPI、真实 PostgreSQL Worker、既有 OpenAI Agents SDK 和 Analytics SQL 持久化为 `succeeded`。安全 SQL 与只读 Edge 页面分别核对为 5 Tool Call / 8 Observation / 6 Evidence / 1 Diagnosis；页面刷新重读同一记录通过。首次一体化浏览器 harness 因 Worker 后 API 提前退出而未在同一存活服务中完成终态轮询，已修正为浏览器显式完成信号，但为控制模型调用未重跑第二笔任务。此条更新优先于下方旧“模型成功未通过”的历史快照；完整边界见[验收记录](evaluation-artifacts/live-model-browser-submission-2026-10-15.md)。

> **桌面回读验收 2026-10-15**：基线c3360ff的真实模型成功Run现已通过实际PG→独立API→React build→Edge桌面读取与刷新重开；2工具/5观察/5证据/1诊断、Driver与证据引用核对通过，0写请求，DB前后190/126/167/80/72不变。任务客户端18/18、lint/build通过。API和PG已停止，无新模型调用。[记录](evaluation-artifacts/live-model-browser-readback-2026-10-15.md)。下一步是浏览器新提交→真实Worker/SDK完整闭环及少量重复评测，非继续扩展底座；Shopify资源与部署仍未完成。

> **最新状态 2026-10-15**：分支 `codex/r5-004-validation`。真实 SDK + 隔离 PostgreSQL Synthetic 调查已成功，任务固定过滤器 Schema 已向模型显式绑定，后端仍拒绝越界。新的浏览器提交成功记录补齐了产品提交入口与真实 Worker 的实际接线；但一体化服务保活复跑、重复模型评测、持续外部来源和部署仍待完成。Token 使用量未采集，隔离PG已停止；未部署。

> 2026-10-14 R5-004：独立实验迁移、Lab API、发布/恢复、关联既有Runtime和React Lab已实现。真实临时PostgreSQL脚本六项检查通过；离线Ran690 / OK(skipped=6，Windows跳过POSIX文件模式位测试)，桌面1440×1000受控HTTP流程通过。真实模型和外部业务数据仍未调用，未推送或部署。[验证记录](evaluation-artifacts/lab-application-acceptance-2026-10-13.md)。

> 2026-10-15 历史兼容性记录：更新后的端点已通过 `/v1/models`、最小文本、工具声明和生成结构化Schema四项直接探测；当时旧任务过滤器没有进入模型可见 Schema，首次 Agents SDK 调查在首个完整工具结果前返回 `UserError`。后续修复已通过真实模型成功验收，故此段只保留历史故障定位，不代表当前 gate 状态；见[旧记录](evaluation-artifacts/live-model-sdk-compatibility-2026-10-15.md)。

> 状态：动态接管摘要；更新时间：2026-10-15
> 分支：`codex/r5-004-validation`；本轮基线：`2546350e784d6e801e87c8996d5e2552482bdeaa`。当前提交请用 `git log -1` 核对；不以历史 main 快照代替当前分支。
> 最近验收：R5 Lab 的 PostgreSQL/受控流程、R2 真实 SDK 成功持久化、R4 浏览器提交及同一成功记录的独立桌面回读。完整单进程真实模型浏览器复跑仍待完成。
> 当前切片：R6持久结果语义回溯。2条历史真实模型成功Run符合预期指标/终态/Driver，引用声明支持分别3/3、4/4；另保留1条历史401失败为不可评分，无伪Diagnosis。这是已知样本回溯，不是新的重复实验或准确率结论。
> 最新验证：后端 Ran 710 / OK(skipped=6)，新增回溯专项8项通过；真实PG读回3条历史记录，应用表计数191/131/175/86/73前后一致。没有新模型或Shopify调用；隔离PG已停止。Scope准确率、停止时机与Token/成本仍未评测。全量回归仍有既有event loop ResourceWarning和依赖弃用警告。前端未改，本轮未重跑前端；上轮86项及lint通过。
> 下一步：完成有限真实模型浏览器复跑及小样本重复评测；Shopify资源就绪后先执行只读能力探测，再实现两次更新的幂等同步。不会因等待资源扩展通用框架。
> 用户约束：已恢复持续推进；仅桌面Web。用户提供5h额度百分比，接近75%准备收尾；不猜测额度。不操作生产环境。

## 当前结论

MetricSleuth 已具备 Synthetic/Olist 调查内核、持久 PostgreSQL 任务 API/Worker、默认React工作区及实际单项读取/来源全局手动扫描。浏览器已提交一次真实模型 Synthetic 调查并留下可追溯事实；R4-006/007指标页可读实际值及前7日基线并带入表单，不自动调查。Olist仍为公开静态数据，不是持续连接器；Shopify/外部PostgreSQL连接、重复真实评测、生产安全部署及一体化浏览器 harness 复跑仍未完成，不能称MVP已交付。

R6复现入口：[`持久语义回溯记录`](evaluation-artifacts/persisted-semantic-replay-2026-10-15.md)；只读脚本 `backend/scripts/score_persisted_task.py` 复用现有声明支持评分器，不调用模型、不读.env、不写数据库。`semantic_passed`只覆盖脚本明确检查的四项，不代表完整R6通过。历史失败仍保留，不能将本次2条通过记录当作无偏准确率样本。

## 历史阶段证据

以下条目保留各阶段发生时的范围与失败，不代表本轮重跑，也不覆盖上方当前摘要。尤其早期“模型未成功”“Lab未接线”已由2026-10-15和R5-004记录更新。

- R5-002（2026-10-12）：`app/sandbox/dataset_writer.py`以显式loopback专用空库、Synthetic/Sandbox UUID和实际连接身份守卫，单事务写入3商品、558日分段及manifest；不调用旧reset/main，不覆盖已有库。真实PG验证正常sales52000.00与变化45760.00、共同基线52034.28571428571428571428571，候选sales/orders/conversion_rate；重新创建应用/连接回读、非空拒绝、误连拒绝、CHECK失败DDL/DML回滚通过。原R2/R4状态计数和业务表指纹逐项保持不变。三个新库保留，隔离PG已停止且55440无监听；没有API服务器或Worker启动。版本是输入内容标签，不是不可变数据库快照；没有Lab路由、页面、实验记录或Diagnosis。[验收记录](evaluation-artifacts/sandbox-dataset-postgres-acceptance-2026-10-12.md)含复现及首次失败，重跑实际测试必须另建空库，不得重置保存的fixture。
- R5-001资产核对（2026-10-12）：已确认复用内存生成函数；旧seed reset全表DELETE、injector按日重写18分段，不能作为产品共享库写入口。主线程21/21及内存重复性/数据形状核对；[核对记录](evaluation-artifacts/sandbox-asset-review-2026-10-12.md)区分源码事实、已验证数据和待实现首验。下一步新建空的专用Sandbox库，原子写入并真实SQL回读；未实现写入口、实验版本记录、API或Lab，没有新增数据库/模型调用。
- R4-007桌面页面（2026-10-12）：MetricScanPanel复用冻结设计和scan客户端，来源目录身份/完整能力集合检查，key/epoch/Abort清过期，逐项原值与状态、未知计数及原生明细、handoff仅填表。两profile实际PG/API/build/Edge通过，原单指标回归通过；独立桌面复核ship，无实质修复，DESIGN/sidecar只读核对无须刷新。计数保持Synthetic1/1/1/1/1与Olist179/117/155/70/70；验收API/PG停止、数据保留。[记录](evaluation-artifacts/source-metric-scan-ui-acceptance-2026-10-12.md)区分真实SQL、受控故障/目录以及首次键盘驱动失败。手机端仅有用户明确桌面边界前的附带历史截图，后续不安排专项。本轮没有模型/平台请求，扫描不持久化且不是一致快照。
- R4-007客户端合同准备：frontend metrics/contracts/client与对应测试新增scan，严格验证整批来源/日期/版本/唯一指标/唯一查询引用及精确候选列表；read共用安全传输且原31项保留。主线程58/58、任务18/18、lint/类型/build通过；[同一验收记录后续客户端节](evaluation-artifacts/source-metric-scan-acceptance-2026-10-11.md)明确离线边界。页面未改、目录与响应一致性待页面验证，没有新PG/模型/平台请求。
- R4-007后端扫描（2026-10-11）：GET `/api/metrics/scan`复用MetricReadService.read/Analytics/Mapper，能力预校验、最多5项、安全参数和失败合同，无自动调查或数据写入。实际PG读取Synthetic5项、Olist3项；缺数null、异源拒绝，状态计数不变。组合34/34、全量668(skipped=4)，PG停止；[验收记录](evaluation-artifacts/source-metric-scan-acceptance-2026-10-11.md)保留首次错误与复现步骤。snapshot_consistent=false、版本仅label、扫描不持久化；页面未接线、实际SQL未制造异常，不是模型或持续外部源验证。
- Shopify资源准备（2026-10-11）：用户明确开发店/read_orders尚未就绪，已按官方Dev Dashboard/同组织client credentials流程整理[操作指南](shopify-orders-probe.md)，说明约24小时Token、脚本无交换/刷新、草稿不等于Orders、首轮少量样本gate与后续8天指标分开。主线程离线守卫18/18；未创建账号、应用、店铺、凭据或订单，未访问Shopify/模型/数据库，不把指南当接入验收。
- 2026-10-11新授权模型预检：正确读取根目录.env，显式SDK key/Base匹配、配置无重复/已知占位/内部空白；一次Chat Completions工具声明请求（配置标识gemini-3.8-flash-high、输出上限256、无重试/远程tracing）返回AuthenticationError/401。未获得usage/工具输出，未执行完整调查、不创建Run，未修改CPA；上游实际模型未确认。纯函数独立检查Diagnosis→Evidence→Observation→ToolCall、来源/版本/数量/引用，离线18/18；实际PG旧成功全项通过、旧401失败正确拒绝、内存断链拒绝。脚本明确SDK/持久化范围，不把passed作为Driver/Scope/停止准确率。详情见 [`live-model-preflight-and-provenance-2026-10-11.md`](evaluation-artifacts/live-model-preflight-and-provenance-2026-10-11.md)。
- R4-006页面：实际PG→独立API→生产build→真实Edge两profilePASS，Synthetic100/100、Olist16861.09/13355.61；缺数据null、受控503安全手动重读、延迟旧响应清除、handoff不POST和刷新不自动查询通过。前端客户端31/31、任务18/18、格式10/10、lint/类型/build；后端专项31/31。独立视觉复核ship，原型hash不变，配置/设计体系未改。状态计数1/1/1/1/1与179/117/155/70/70前后一致，API/PG与验收Edge已停。首次验证工具误判Edge launcher退出已修，两个旧临时profile可能残留但无运行进程；细节/截图目录见 [`metric-observation-ui-acceptance-2026-10-11.md`](evaluation-artifacts/metric-observation-ui-acceptance-2026-10-11.md)。没有模型调用或外部API，不宣称趋势、来源健康或持续更新。
- R4-006后端切片（此前验收）：GET `/api/metrics/observation` 绑定服务端单源，只接受source_id/target_metric/target_date，读取单日与前7日基线。主线程实际PG专项4/4 PASS，Synthetic100.00/100.00、Olist16861.09/13355.61；缺数据保留null，异源和不支持指标拒绝，状态表计数不变。复用原Analytics/mapper/10秒只读事务，无模型、任务写入、迁移、同步或UI改动。最终离线结果见专项记录 [`metric-observation-api-acceptance-2026-10-11.md`](evaluation-artifacts/metric-observation-api-acceptance-2026-10-11.md)。异常候选不是Diagnosis，query_reference未持久保存，版本仍为标签。
- 第二次真实SDK尝试：一次新授权下沿用现有配置，实际返回AuthenticationError/401，0/0/0/0工具与事实；失败Run保存、新应用回读与实际SQL核对通过。CLI参数错误脱敏修复，26项离线守卫与638 tests/OK(skipped=3)通过。测试PG已停止、失败数据保留，没有重试/换模型/商店调用。模型成功gate仍未通过。见 [`live-task-authentication-attempt-2026-10-10.md`](evaluation-artifacts/live-task-authentication-attempt-2026-10-10.md)。
- R4-005：新专用PG库迁移001–004、稳定Synthetic八天数据；浏览器POST一次→202 queued→既有Worker→实际Analytics SQL→succeeded，保存1/1/1/1 Tool/Observation/Evidence/Diagnosis；新API进程与浏览器刷新重开读回100.00/100.00/0及no_material_anomaly。首次两个脚本断言错误已记录并修正，仅只读resume复验PASS，未重提/清库。原库计数不变，测试API/PG已停止，原型哈希未变。受控规则不是模型、异常归因或持续来源验收。见 [`browser-task-roundtrip-acceptance-2026-10-10.md`](evaluation-artifacts/browser-task-roundtrip-acceptance-2026-10-10.md)。
- R4-004：字符串精确格式化与原始事实disclosure；格式10/10、客户端18/18、lint/类型/build、受控HTTP真实Edge通过。实际PG/API/Edge重读既有Olist失败记录4/27/0/0，前后数据库计数178/117/155/70/70不变、0浏览器写请求，测试API/PG已停止。原型哈希不变；不是新模型/连续来源/成功诊断验收。见 [`investigation-readability-acceptance-2026-10-10.md`](evaluation-artifacts/investigation-readability-acceptance-2026-10-10.md)。
- R1-004b离线准备：独立只读Orders probe与守卫18/18 PASS（主线程执行，MockTransport/patch）；请求固定query/域名/版本、最多5页、无重试、安全错误与聚合输出。没有商店API/DB/模型调用，没有连接器接入应用。运行说明 [`shopify-orders-probe.md`](shopify-orders-probe.md)，证据 [`shopify-probe-offline-acceptance-2026-10-10.md`](evaluation-artifacts/shopify-probe-offline-acceptance-2026-10-10.md)。真实gate未通过。
- R1-004a：[`data-source-selection.md`](data-source-selection.md)记录官方权限、订单/会话粒度、开发店限制及最小版本发布方案。已选择Shopify开发店为下一外部验证对象；只是资料和资源决策，不是连接器或实际API测试。官方sessions转化率与Synthetic orders/sessions不同，不直接复用公式；开发店始终sandbox。
- R4-003：真实PostgreSQL/API/Edge读取既有Olist失败调查4Tool Call/27Observation/0Evidence/0Diagnosis，SQL与API首条GMV16861.09/13355.61一致，页面与刷新重读PASS；0浏览器写请求、前后数据库计数一致。新只读脚本语法/lint通过；测试API和PG均已停止。见 [`postgres-browser-history-acceptance-2026-10-10.md`](evaluation-artifacts/postgres-browser-history-acceptance-2026-10-10.md)。非真实模型/持续外部源。
- R4-002：默认 React 页面消费来源目录及持久任务 submit/list/detail API，保留原型五导航。概览只统计当前来源当前页最多20条；指标页只展示能力目录，数据页不冒充连接健康/刷新，Lab 未接线。queued/running 每2秒轮询，终态/错误停止；失败不合成 Diagnosis。主线程最终真实 Edge + 受控 HTTP fixture PASS（含翻页、单次POST、来源切换、失败/成功详情、安全503），无真实数据库/模型。客户端18/18、API/应用24/24、lint/类型/build通过；记录：[`task-workspace-acceptance-2026-10-10.md`](evaluation-artifacts/task-workspace-acceptance-2026-10-10.md)。原型哈希未变；视觉实现事实见根目录 `DESIGN.md`。
- R4-001：`frontend/src/tasks/` 持久调查 sources/submit/list/detail 客户端和完整响应校验；后端 GET `/api/investigation-sources` 只投影配置来源能力，不连接数据库或运行任务。主线程客户端18/18、后端目录/API/应用24/24，证据见 [`task-frontend-contract-acceptance-2026-10-10.md`](evaluation-artifacts/task-frontend-contract-acceptance-2026-10-10.md)。
- 数据源能力契约（R1-001）：最小、领域无关、真正深层不可变契约模型，支持 `SourceProvider`、`SourceEnvironment`、`DataSourceDescriptor`、`MetricCapability`、`DataSourceCapabilities`（frozen dataclass，嵌套内部容器使用 MappingProxyType，防范 Sequence 字符串混淆），具备指标独立 grain/维度、跨 grain 组合保护与 fail-closed 校验（`backend/app/data_sources/capabilities.py`；单测 `backend/tests/test_data_source_capabilities.py` 6/6 PASS）。
- 指标能力矩阵与语义适配（R1-002）：当前 Synthetic Profile 的五个核心指标在 `configs/metrics.yaml` 显式声明 `date × asin × marketplace × traffic_source` atomic grain；`MetricRegistry` 严格校验显式 grain 并为旧配置提供明确 fallback；`build_capabilities_from_registry()` 保留 Registry 中的 metric dimensions/grain；`AnalyticsTools` 传入 capabilities 时在执行 SQL 前校验查询能力（主线程专项测试 51/51 PASS）。
- Olist 能力降级表达（R1-003）：`configs/olist_validation_metrics.yaml` 的三个支持指标显式使用 `date × customer_state` grain；`build_olist_validation_capabilities()` 复用 Registry grain/dimensions，显式拒绝 `sessions`、`conversion_rate` 及 `marketplace`/`traffic_source`/`asin`；Olist 工具兼容性脚本已绑定该合同。已验证绑定合同后，漏斗指标与非法维度都在 SQL 前失败。证据限于本地 Hermetic 测试，不代表数据库连接、同步或持续真实数据接入。
- Olist 后续真实数据库验收（2026-10-10）：本机已存在的公开 CSV 导入隔离 PostgreSQL，真实 Analytics 查询和四步受控调查保存/失败留存/新应用读取通过。这更新上述 R1-003 当时的数据库验证边界，但仍不是持续外部源或 Olist 真实模型验收；详见下节。
- PostgreSQL Synthetic Warehouse、10 个 Benchmark 场景和 Ground Truth 隔离。
- YAML Metric Semantic Layer 与指标依赖/driver 元数据。
- 受控 Analytics Tools、Observation、Evidence、Structured Diagnosis。
- OpenAI Agents SDK Runtime、Tool Trace、轮次和工具预算校验。
- Driver + Scope 同一 Evidence、negative control 等 fail-closed 约束。
- Evaluation 的 Driver、Scope、Evidence、Unsupported Claims 和 Tool/Budget 评分基础。
- FastAPI 旧同步 Benchmark API 与新显式持久任务 API；默认 React UI 已从旧同步工作台切换到 R4-002 持久任务工作区。
- Manual Daily Scan。
- Olist 隔离 Schema/Metric/Tool Compatibility 验证资产。

## 已实现但当前未真实复验

- 旧同步 Live API 的完整模型执行路径尚未复验；新应用 Runner 的 AnalyticsTools 聚合 SQL 已由 R2-005b2b 在真实 PostgreSQL 验证，不是外部数据同步。
- 真实模型动态调查：早期 401、InternalServerError 和一次过滤器遗漏导致的 `UserError` 均保留为历史失败；后续修复任务过滤器 Schema 后，真实 SDK 成功 gate 已通过，且本次浏览器提交记录已实际持久化。尚未完成少量重复情形、成本/Token采集或外部数据上的模型评测；详情见 [`live-model-task-scope-2026-10-15.md`](evaluation-artifacts/live-model-task-scope-2026-10-15.md) 与 [`live-model-browser-submission-2026-10-15.md`](evaluation-artifacts/live-model-browser-submission-2026-10-15.md)。
- 前端 production build、lint与类型检查已在R4-005重新通过；这不代表服务器部署或所有页面功能完成。

## R2-PG：真实 PostgreSQL 持久化验收已通过

- PostgreSQL 17.11 隔离本机测试库已执行 `001`、`002`、`003` migrations，并重复执行成功；没有连接生产库或读取应用连接配置。
- `upsert_data_source()` 拒绝同 ID 不同 provider/environment；`003_immutable_data_source_identity.sql` 触发器进一步禁止直接 SQL 修改 source_id/provider/environment。相同身份的元数据更新仍允许。
- 领域模型与 Repository 均允许 `queued → failed`；已验证实际 SQL 状态写入。
- 受控 Runner 执行参数化 `SELECT 80/100`，成功保存 Trace、Observation、Evidence、Diagnosis 与来源版本/查询引用；失败只落受控 code，不生成 Diagnosis。
- 实际数据库验证来源组合外键、Diagnosis 冲突后的整批回滚、Observation 原始错误文本不落库，以及全新连接读取。数据库进程重启后再次读回同一成功调查和 Diagnosis。
- 主线程终验：真实 PostgreSQL **7/7 PASS**；离线回归原始输出 **Ran 535 tests / OK (skipped=1)**，数据库测试类因未配置专用变量跳过。二者分别运行，不混算模型效果。
- 记录与复现命令：[`postgres-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/postgres-persistence-acceptance-2026-10-10.md)。测试实例已停止，测试数据保留在仓库外。
- R2-PG 验收时尚未完成 Worker/API 接线、失败前工具事实增量保存、任务恢复；其中 Worker 与步骤保存现已由下述 R2-005b1 补齐。外部业务同步与真实模型仍未验收。

## R2-005b1：最小 Worker 与失败前步骤保存已验收

- `InvestigationWorker.submit()/run_once()` 在 PostgreSQL 排队、原子领取一个调查；session advisory lock 保证只有一个 Worker 执行，Runner 期间不持有数据库事务。
- `004_worker_execution_mode.sql` 将 Worker 任务与旧 inline 调查隔开。中断恢复仅处理 Worker 的 running 任务，写 `worker_interrupted`，不自动重放模型、不影响 inline。
- 每个完整工具结果通过 `Coordinator.checkpoint()` 独立提交 Trace/Observation；失败前事实保留，不生成缺失的 Evidence/Diagnosis。
- 幂等重放只接受完全相同的事实；不同内容、不同来源/版本、终态写入均拒绝。成功完成不能遗漏已保存步骤。
- Agents SDK 三个现有工具和 Diagnosis Runtime 提供可选 `progress_callback`；沿用原始 SDK 调用参数、原 Observation 和最终校验。未改 Prompt、策略、预算或模型。
- 主线程实际 PostgreSQL **15/15 PASS**（含原 7 项回归），新库 migrations 001–004 和已有库升级/重放均验证；子 Worker 突然退出后事实保留，新 Worker 安全终结，未再次调用 Runner。
- 全量离线回归 **Ran 552 tests / OK (skipped=1)**；SDK 回调专项 5 项为 Fake Analytics/真实 FunctionTool invocation，无真实模型。
- 记录：[`worker-checkpoint-acceptance-2026-10-10.md`](evaluation-artifacts/worker-checkpoint-acceptance-2026-10-10.md)。没有 HTTP/前端或后台进程启动接线，不代表可部署产品已完成。

以下 R2-001 至 R2-005a 条目保留各切片当时的历史验证边界；其中“未执行迁移/未验证数据库”已由上述 R2-PG 验收更新，不代表当前仍未执行。

## R2-005b2b：显式应用接线已受控验收，模型待验证

- `task_application.py` 提供可单独启动的 loopback 任务 API/Worker；仅 Synthetic Sandbox / Olist 静态 Validation，必填显式配置，无自动迁移/.env/Scenario Injection。任务专用入口不含旧注入接口，默认旧 app 仍保持兼容。
- Source Runner 复用 SDK Runtime 和 callback；每次查询为独立只读短事务并限时10秒。日期和固定filters由工具强制校验；不隐式补过滤而造成Trace/Observation范围错误。
- capabilities 省略不会抹掉已有元数据；真实 SQL 已验证参数顺序、保留/显式清除语义。
- 新 PostgreSQL 专项4/4 PASS，含实际Analytics聚合与Observation mapper、UPDATE只读拒绝、元数据保留、独立API子进程HTTP读取。最终合并回归见下表。Runner为受控，真实模型未调用。
- `data_version`仍为标签，不是数据库snapshot；单源配置不提供混合来源自动路由。后续已补上Worker只领取/恢复绑定来源的边界，见下节；下一步先真实模型验收与真实源capability gate，不继续扩展编排。
- 证据/安全启动说明：[`task-application-acceptance-2026-10-10.md`](evaluation-artifacts/task-application-acceptance-2026-10-10.md)。

## 单源 Worker：领取与恢复来源隔离已验收

- 修复单源Runner配合全局Worker时误领/终结其他来源任务的边界：`InvestigationWorker(expected_source=...)` 在连接前拒绝异源提交，并以参数化SQL限定领取和恢复来源；显式应用始终传入同一descriptor。
- 保留原全局advisory lock/短事务，无新表、迁移或调度机制。低层未绑定Worker保留受控兼容用法，产品入口不使用全局领取。
- 主线程实际PG验证：先排队Olist再排队Synthetic，Synthetic仅执行自己且读到sales80；Olist保持queued直到自己的Worker执行。两个来源running恢复互不终结，无Runner重放、无伪造Diagnosis。
- 主审另补相同source_id/environment但错误provider的启动配置：既不领取queued，也不终结running。应用PG专项7/7，全持久化/Worker/API/应用回归26/26；离线605 tests / OK (skipped=3)。记录：[`worker-source-isolation-acceptance-2026-10-10.md`](evaluation-artifacts/worker-source-isolation-acceptance-2026-10-10.md)。不是多租户授权或分析宽表物理隔离。

## Olist 静态公开数据：真实 SQL 与失败步骤持久化已验收

- 本机原有公开 CSV 已实际导入专用测试库，不是 Synthetic：99,441 orders / 112,650 items；delivered 96,478，merchandise GMV 13,221,498.11。未下载、提交原始记录或使用 `--replace`。
- 原有 loader/映射/工具资产复用；显式任务 Profile 查询 GMV、orders、AOV 和按 customer_state 的 GMV，保存4个步骤/27 Observation。受控 Runner 主动中止后固定 code `execution_failed`，Evidence/Diagnosis 都为0，新应用实例重连读回一致。
- 不支持的 sessions/marketplace 请求在任务创建前拒绝。版本 `olist-public-raw-files-20261010` 是标签，不是快照；公开静态历史数据不等于持续业务接入，也未使用真实模型。
- 新脚本 `backend/scripts/verify_olist_task_progress.py` 与6个离线守卫测试；主线程验收 run `102bea3f-cc93-400a-a871-6ef90238972f`。记录：[`olist-persistence-acceptance-2026-10-10.md`](evaluation-artifacts/olist-persistence-acceptance-2026-10-10.md)。
- 既有 PostgreSQL 持久化/Worker/API/应用回归重新执行23/23 PASS；离线全回归591 tests / OK (skipped=3)，均不作为模型成功证据。

## 真实 SDK 持久调查：已尝试，未通过

- 用户授权一次隔离 Synthetic 模型调查、最多8工具/10轮；主线程沿用本机既有端点/模型与SDK，禁用重试/远程追踪。只插入一个新测试产品八行数据，不使用生产/Olist原始数据。
- 实际 `InternalServerError`，完成工具0/Observation0/Evidence0/Diagnosis0。任务持久化为 `failed / execution_failed`，新应用重连读取一致；脚本 exit1，不当作模型通过。
- 本次一次性授权已使用，不自动追加请求或换模型。需确认端点/模型可用性后另行授权验证完整成功链路，不扩展编排框架。
- 证据与复现边界：[`live-task-persistence-attempt-2026-10-10.md`](evaluation-artifacts/live-task-persistence-attempt-2026-10-10.md)。模型客户端返回错误不能证明动态调查、调用成本或通用模型可靠性。

## R2-005b2a：任务 API 与持久历史已验收

- 新 POST `/api/investigations` 排队；GET 列表/详情可读运行状态、步骤、证据和结果。服务显式注入，默认应用未配置时 503；没有 HTTP 长模型调用、自动迁移或场景注入。
- 服务器绑定来源/环境/provider、能力与版本；客户端仅提交受限指标查询意图。所有读取按 source/environment/worker 限定。来源 allowlist 不是用户授权。
- 新任务响应不暴露原始错误文本、failure_details、Evidence payload 或误传凭据；旧开发端点/CORS 不变，尚不能安全公开。
- 主线程真实 PostgreSQL API 专项 4/4 PASS；含既有持久化/Worker 回归 19/19 PASS。覆盖运行中读步骤、成功/失败、全新应用实例读取历史、来源隔离和安全错误。Runner 是受控 SQL，未调用真实模型。
- API/reader/旧 API 专项 40/40 PASS（Hermetic）。最新全量结果见下表。复现记录：[`task-api-acceptance-2026-10-10.md`](evaluation-artifacts/task-api-acceptance-2026-10-10.md)。
- R2-005b2a 当时没有应用Runner/启动入口，现已由 R2-005b2b 补齐实现；前端和真实模型仍未验收，不是完整 R2 或可部署 MVP。

## R2-001：已完成并由主线程验收

- `backend/migrations/001_app_state.sql` 提供独立、幂等目标为 `app_state` 的
  应用状态 Schema，覆盖数据源、同步 Run、调查 Run、Tool Call、Observation、
  Evidence、Diagnosis 和多 Evidence 链接；未执行迁移。
- `backend/app/persistence/models.py` 提供不可变 `RunState`/`RunStatus` 状态机和
  `SourceReference`；非法创建、非法迁移和终态转换均 fail-closed。
- `backend/app/persistence/migrations.py` 只读取 SQL 文本；`tests/test_persistence.py`
  检查状态机、环境枚举、Schema/FK/约束形状和敏感列名排除。
- 本切片尚未接入 repository、FastAPI、Agent Runtime、worker 或真实 PostgreSQL；
  测试不代表迁移执行、重启恢复或真实持久化验收。

## R2-002：已完成并由主线程验收

- `backend/app/persistence/repository.py` 新增 `ApplicationStateRepository` 和
  `InvestigationRunSummary`，仅接受已建立的 DB-API connection；调用者负责
  transaction，不保存 `DATABASE_URL`，不自动 commit/rollback，不执行 migration。
- repository 使用参数绑定 SQL 保存 data source、queued investigation run、受
  `RunState` 规则约束的条件状态迁移、Tool Call、Observation、Evidence、
  Diagnosis 及 `diagnosis_evidence` 链接，并支持按 run id 读取最小摘要。
- 写入前统一校验 source/environment、状态枚举、空 ID、递归敏感 key 和 JSON
  可序列化性；认证字段不会写入 arguments、parameters、capabilities 或 payload。
- `backend/tests/test_persistence_repository.py` 提供 FakeConnection/FakeCursor
  合同测试；专项 9/9 PASS，全量 Hermetic unittest 490/490 PASS。
- 这是 repository 合同层证据；未执行 `001_app_state.sql`，未接线 FastAPI、
  Agent Runtime 或 worker，未证明真实 PostgreSQL、事务提交和重启恢复。
- Schema 目前只保证各事实所引用的来源/环境有效；尚未在数据库层保证它们一定
  等同于所属 Investigation Run 的来源/环境。R2-003 必须在应用接线与最终迁移
  设计中落实这项 provenance 一致性，当前不得宣称完整持久化隔离。

## R2-003：已完成并由主线程验收

- `EvidenceDrivenRunSummary` 新增完整、不可变 `observation_catalog`，并将每个
  Observation 的顺序、ID、Tool Call ID 和 Tool Name 与已验证 Trace 重新核对。
  这让持久化边界拥有完整事实目录，而非仅有最终 Evidence/Diagnosis。
- `backend/app/persistence/investigation_writer.py` 的
  `EvidenceDrivenRunPersistenceWriter` 只接受一个 `DataSourceDescriptor`；所有
  Tool Call、Observation、Evidence、Diagnosis 的 source/environment 均从此派生。
  它在任何写入前检查 Trace、catalog、Evidence 和 Diagnosis 的引用关系，按
  source → queued → running → facts → diagnosis → succeeded 顺序调用 Repository。
- Writer 不建立连接、不执行 migration、不 commit/rollback，Repository 异常原样
  传播且不会错误标记 succeeded。专项 29/29 PASS，后端全量 Hermetic unittest
  496/496 PASS。
- 未接线 FastAPI/worker；没有真实 PostgreSQL、运行中进度、失败持久化或重启恢复
  验收，不能把该合同测试表述为产品持久化已完成。

## R2-004a：已完成并由主线程验收，迁移尚未执行

- `backend/migrations/002_enforce_investigation_provenance.sql` 只为 `app_state`
  增加约束：Tool Call、Observation、Evidence、Diagnosis 的
  `(investigation_run_id, source_id, environment)` 将分别外键引用同一
  Investigation Run；这补齐了此前只验证“来源存在”、未验证“来源属于该 Run”的
  Schema 缺口。
- 每个约束增加前都会检查 `pg_constraint`，并且没有 DROP/TRUNCATE/DELETE、warehouse、
  Olist 或认证字段。`tests/test_persistence.py` 的专项 12/12 PASS，后端全量
  Hermetic unittest 498/498 PASS。
- 迁移未执行；SQLGlot 只能把 PostgreSQL `DO $$` 块降级为通用 Command，故这仅是
  SQL 文本/合同验证，不是 PostgreSQL 解析、约束生效或真实数据完整性证据。

## R2-004b：已完成并由主线程验收，未接线事务 owner

- Repository 的 `fail_investigation_run()` 只允许 queued/running → failed，并以
  参数化 SQL 把严格受控的 1–64 位小写 failure code 保存为 `{"code": ...}`；没有
  原始异常、stack trace、凭据或连接配置的参数入口。
- Writer 已拆分 `start()`（source→queued→running）、`complete()`（facts→succeeded）
  与 `fail()`；`write()` 仍为向后兼容组合，但对完整 Summary 先验证，避免坏数据
  产生孤立 running 记录。专项 23/23 PASS，后端全量 Hermetic unittest 506/506 PASS。
- 没有 API/worker、connection factory、commit/rollback owner、重试、领取或真实数据库
  验收；这些接口是下一步短事务服务的基础，不能当作已部署任务队列。

## R2-004c：已完成并由主线程验收，未接线 API/worker

- `InvestigationTransactionCoordinator` 对 start、complete、fail 分别从注入的
  factory 获取一个连接，成功才 commit，执行/commit 失败则 best-effort rollback，最后
  close；它不会跨模型调用持有连接，也不会读取环境变量、保存 URL 或创建网络连接。
- `InvestigationRunHandle` 是不可变的 run/source/data-version 绑定，complete/fail
  只能从 handle 获取来源身份。commit 已成功后的 cleanup 错误被隔离，避免调用方把
  已落库操作当作可安全重试的失败。
- 专项 11/11 PASS，后端全量 Hermetic unittest 517/517 PASS。仍未接 FastAPI、worker、
  实际 connection factory、PostgreSQL 或 migration；没有真实任务状态持久化证据。

## R2-005a：已完成并由主线程验收，未接线 HTTP/worker

- `InvestigationTaskExecutionService` 按 `start → injected runner → complete/fail`
  编排单个调查，Runner 在两个 coordinator 短事务之间执行；服务没有连接、线程、网络
  或环境配置责任。
- `InvestigationTaskRequest` 是不可变且来源绑定的请求合同，递归拒绝敏感 key 和非
  JSON 参数。Runner 异常仅落受控 code 后原样抛出；start 失败不执行 runner，complete
  失败不二次 fail 覆盖可能已发生的持久化事实。
- 专项 11/11 PASS，后端全量 Hermetic unittest 528/528 PASS。未运行真实 Agent、API、
  worker、PostgreSQL 或 migration，不能据此宣称已具备后台持久任务。

## 尚未实现

- 能力契约与真实应用 Runner、数据库来源发现及外部连接器的产品级接入（新任务 API 已使用服务器能力合同校验；不代表真实源可用）。
- Shopify 或用户外部 PostgreSQL 的产品级接入、连接器实现、数据同步和水位（当前绝对未接入真实外部库或 Shopify API）。
- 用户取消/显式重试、生产进程恢复和持久化后的多 grain 查询支持。
- 真实模型少量重复评测及完整单进程浏览器复跑；单次真实SDK成功调查与独立桌面刷新读取已通过，不能再列为未实现。
- 工作概览趋势汇总、外部数据连接与刷新 API。指标读取/手动扫描及Lab操作已实现；不把来源能力目录当作连接健康或同步状态。
- 用户认证、生产安全、后台进程生命周期与服务器部署资产。
- 独立 Holdout、真实外部数据评测、Next Action/Stop Condition 评分。

## 当前阻碍与待提供资源

1. 单次真实模型调查已成功；缺少少量重复样本、停止语义评分和Token/成本记录，不能推断稳定正确率。大量Observation仍逐条显示，不把数值格式优化称为大规模阅读方案。
2. 首次一体化浏览器验收因API过早退出未取得同进程终态；已补保活并通过受控HTTP生命周期回归、真实PG既有结果确认，但没有把它们冒充修复后的真实模型浏览器复跑。
3. 用户可准备Shopify开发店，但店/应用/只读权限尚未提供；无可用业务PostgreSQL。最小准备清单见data-source-selection.md第6节；不要在聊天中提供凭据。
4. 开发店真实API/刷新不等于真实经营数据。最终live来源仍需授权与实际capability验收，不以sandbox更名过关。

## 下一步具体工作

用户已恢复持续推进；按 Roadmap 优先补产品闭环的验收证据：

1. 以现有一次性harness完成同一API中的浏览器提交/轮询/刷新真实验收；沿用明确的调用预算，不自动重试。随后以少量异常/无显著异常样本验证Driver、Scope和停止，记录失败与可获取的usage。
2. R1-004b probe离线准备已完成；等用户提供店/应用/read_orders后先验证Orders粒度与字段，再做最小两次更新/幂等同步，不推导商品级转化率。
3. 在上述真实gate基础上补最小部署与安全验收；服务器操作另行确认。业务PostgreSQL只在有授权资源时启用，不并行建设两套连接器。

原型登记提交为 `313b7ae`；随后R4-001新增客户端与只读配置目录，并重跑离线回归和前端验证。未重跑真实数据库/模型，不将下列历史数据库结果表述为本次验收。

## 历史验证快照（以各行日期为准，非本轮全量重验）

| 检查 | 结果 | 边界 |
|---|---|---|
| 数据源能力契约专项 | 6/6 PASS | 纯领域单元测试，覆盖基础合同、Olist、独立维度、跨 grain 保护、fail-closed 和深层不可变 |
| R2-001 持久化专项 | 10/10 PASS | 纯 Python 状态机、环境值、只读 migration loader、Schema/FK/约束形状和敏感列名排除；未执行 SQL |
| R2-002 repository 专项 | 9/9 PASS | Fake connection；参数化/事务边界/证据链/来源环境；未执行 SQL |
| R2-003 Runtime/Writer 专项 | 29/29 PASS | Fake/Spy repository；完整 catalog、来源派生、写入顺序、失败闭合；未执行 SQL |
| R2-004a provenance 专项 | 12/12 PASS | SQL 文本/合同；未执行 migration，`DO $$` 未获完整 parser 验证 |
| R2-004b lifecycle 专项 | 23/23 PASS | Fake/Spy repository；失败代码、start/complete/fail、无成功漂移；未执行 SQL |
| R2-004c transaction 专项 | 11/11 PASS | Fake connection；短事务、回滚、关闭与来源句柄；未执行 SQL |
| R2-005a task-service 专项 | 11/11 PASS | Fake/Spy coordinator；事务外 Runner、失败分类与输入隔离；未执行 SQL |
| 后端全量 unittest（2026-10-10，历史回归） | Ran 638 tests / OK (skipped=3) | 含CLI脱敏守卫；未配置专用 DB 变量，三个数据库测试类跳过；该命令无真实模型/Shopify调用 |
| 第二次SDK实际调用 | FAIL / AuthenticationError / 401；0/0/0/0事实 | 一次新授权已使用；真实PG失败Run/新应用回读/SQL核对通过；模型成功未通过 |
| 模型/Shopify脚本守卫复验 | 26/26 PASS | patch/MockTransport、CLI输入不回显；不是平台/模型通过证据 |
| R4-005新提交与成功页面 | POST1后实际SQL成功；只读resume PASS、POST0；服务重启/页面刷新读回1/1/1/1 | 首次脚本两次断言失败如artifact记载；稳定Synthetic+受控Runner，不验证模型/异常归因/外部源，测试进程已停 |
| R1-004b探测器专项 | 18/18 PASS | MockTransport/patch，仅离线守卫；实际平台API与持续同步未验收 |
| R4-004格式/客户端/界面 | 格式10/10、客户端18/18、lint/类型/build PASS；受控HTTP Edge PASS | 精度/大整数/null、原生键盘明细、任务行为；无真实模型或外部来源 |
| R4-004真实PG历史页面复验 | PASS；4Tool Call/27Observation/0Diagnosis；0写请求 | 同一既有Olist记录，前后计数一致，进程已停止；未新建调查 |
| R4-001客户端合同 | 18/18 PASS | Fake Fetch；目录/任务/来源/Decimal/编码/安全错误/取消；未做浏览器与真实HTTP端到端验收 |
| R4-001配置目录/任务API/应用 | 24/24 PASS | TestClient+实际application配置合同；不连接数据库、不调用模型 |
| 单源Worker领取/恢复实际PG补验 | 应用7/7；完整PG回归26/26 PASS | 两来源交叉队列/中断恢复/错误provider隔离；受控Runner，无模型调用 |
| Olist/真实调用验收脚本守卫 | 13/13 PASS | 主线程离线终验；不是模型或数据库调查运行 |
| Olist SQL/持久步骤专项（2026-10-10） | PASS | 实际公开 CSV / PostgreSQL / Analytics；受控4步27Observation，预期失败留存与新应用读回；不调用模型 |
| 真实SDK持久调查尝试（2026-10-10） | FAIL / InternalServerError | 仅一次授权；0工具/0Observation/0Diagnosis；失败状态和新应用读取通过，模型调查未验收 |
| R4-002最终浏览器 UI | PASS；POST1 / detailReads2 | 本机真实 Edge + 受控 HTTP fixture；覆盖历史翻页、成功/失败详情、失败无伪Diagnosis、任务提交/轮询终止、来源切换和服务错误；未连接 PostgreSQL、外部源或模型 |
| R4-003真实数据库历史浏览器 | PASS；4Tool Call/27Observation/0Diagnosis | 真实PostgreSQL+独立API进程+Edge+production build，页面刷新重读、0写请求、SQL/API值核对；读取既有受控Runner失败记录，不调用模型 |
| R2-005b2b PostgreSQL 应用接线 | 4/4 PASS；含全部持久化/Worker/API 回归23/23 PASS | 实际Analytics SQL/Observation、只读拒写、元数据保留、独立本地API进程；受控Runner |
| R2-005b2a PostgreSQL API | 4/4 PASS；含持久化/Worker 回归 19/19 PASS | 真实 PostgreSQL 17.11 + TestClient + 受控 SQL Runner；无模型/外部业务数据 |
| 新 API/reader + 旧 API | 40/40 PASS | Hermetic；主线程执行，含安全输入错误响应 |
| R2-005b1 数据库/Worker 专项 | 15/15 PASS | PostgreSQL 17.11；全新库、升级库、事实重放、失败留存、实际子进程退出与安全终结 |
| SDK 进度回调专项 | 5/5 PASS | Fake Analytics + 真实 FunctionTool invocation；无真实模型 |
| R2-PG 真实数据库专项（2026-10-10） | 7/7 PASS | PostgreSQL 17.11；迁移、约束、受控 Runner、成功/失败、回滚、重连、安全错误文本 |
| PostgreSQL 进程重启读取（2026-10-10） | PASS | 同一成功 Run、Diagnosis、data_version/query_reference；不是 Worker 恢复 |
| Olist 验证能力专项 | 5/5 PASS | Registry grain/dimensions、漏斗指标 unavailable、非法维度与错误来源身份；Fake connection 未执行 SQL |
| FastAPI 专项 | 24/24 PASS | Live 分支使用 patch，只证明契约/wiring |
| 前端 lint | PASS | 静态检查 |
| TypeScript `--noEmit` | PASS | 不生成构建产物 |
| 前端production build（R4-001） | PASS | 写入被忽略的dist；仍是旧App，客户端尚未被页面消费；未部署 |
| Git 审查快照 | `eba3d1846d08876df42c9730289009875dd73dc0` | 原 11 个提交与审查分支保留；R2-PG 在本地 main 新增提交，不推送/合并 |

## 当前关键技术决策

- 产品方已于 2026-10-09 认可 R0 认知固化成果和当前 MVP Roadmap；后续按仓库长期文档自主推进。
- 保留 OpenAI Agents SDK 作为主 Runtime；没有独立 ADR 不建立第二套 Harness。
- PostgreSQL 继续作为 canonical analytics 与应用状态的主要基础，但不同责任需要隔离。
- Shopify 是首个持续真实源的优先候选，不是未经验证的既定实现。
- Olist 用作真实数据映射/契约验证，不宣称持续外部数据接入。
- Live Investigation 必须与 Synthetic Scenario Injection 解耦。
- 当前 R1-002 只为 Synthetic Semantic Layer 建立纯内存 metric × dimension × grain 适配，不把能力映射误认为真实来源连接或 Shopify 支持。
- 当前 R1-003 只为既有 Olist validation registry 建立 `OLIST + VALIDATION` 能力合同和本地 Hermetic 降级验证，不把 Olist 验证资产误认为持续真实连接器。
- 首版持久任务优先使用 PostgreSQL 状态机和简单 worker，不提前引入 Redis/Kafka/微服务。
- Jev、Webhook 自动触发和可替换 Harness 延后到真实闭环稳定后。

## 快速接管入口

- 产品目标：[`PRODUCT.md`](PRODUCT.md)
- 当前/规划架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 长期实施计划：[`ROADMAP.md`](ROADMAP.md)
- 历史 Live 记录：[`evaluation-artifacts/live-evaluation-2026-09-22.md`](evaluation-artifacts/live-evaluation-2026-09-22.md)
- Olist 验证：[`phase-9-olist-real-world-validation.md`](phase-9-olist-real-world-validation.md)
- 历史设计基线：[`../任务书.md`](../任务书.md)
