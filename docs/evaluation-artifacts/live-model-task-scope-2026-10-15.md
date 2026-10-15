# 真实模型任务范围调查验收（2026-10-15）

## 结论与范围

现有 OpenAI Agents SDK 已在隔离 PostgreSQL 的 Synthetic 数据上成功完成一次动态调查并保存完整引用链。这是一次执行与持久化成功，不是持续外部数据、重复准确率或服务器部署验收。

配置模型标识为 `gemini-3.8-flash-high`，通过本机 CPA 的 Chat Completions 端点；未独立确认代理上游模型身份。每次完整调查最多 8 工具调用、10 轮，禁用客户端自动重试与远程 tracing。未访问生产、Shopify 或外部业务库；未修改 `.env` 或代理配置。

## 故障定位和变更

- 对比直接协议与最小 SDK Agent 后，定位到实际工具错误：查询遗漏任务固定过滤器，被 `_BoundAnalyticsTools.query_metric` 在 SQL 前拒绝。此前仅依据 `UserError` 认定 SDK 不兼容是不准确的。
- 仅增加提示仍有失败；临时开启 SDK 默认错误恢复后，错误输出无法通过现有严格 Trace 解析。这项实验路径已移除，最终代码继续传播异常，避免将原始异常交给模型、掩盖预算或持久化失败。
- `investigation_tools.py::_require_bound_filters` 在每次创建工具时深拷贝 Schema，为固定过滤器声明必填键及常量值；顶层 filters 必填，不接受 null。Schema 用于指导模型，执行权限仍由 `_BoundAnalyticsTools` 校验，不依赖代理强制执行 Schema。
- `SourceInvestigationRunner` 传递固定 filters，在任务路径关闭冗余定义工具；查询结果仍携带 Registry 定义。直接 Runtime 默认保留三个工具。不引入另一调查循环，不将场景答案传给模型。

## 首次成功运行（收紧错误处理之前）

Run：`369eea4b-b6e5-43dd-b059-c1dc13b4600c`。

| 项目 | 实际结果 |
|---|---|
| 状态 | succeeded |
| 模型轮次 / 工具调用 | 5 / 4 |
| Observation / Evidence / Diagnosis | 7 / 5 / 1 |
| Driver | conversion_rate |
| affected_scope | marketplace=US；查询始终绑定任务 asin |
| 引用完整性 | provenance 全部检查通过；新应用实例读取一致 |
| Token / 费用 | 现有验收脚本未采集；不可推断为零 |

工具顺序为 sales query_metric → sales query_related_metrics → conversion_rate 按 marketplace/traffic_source 查询 → conversion_rate 按 marketplace 查询。SQL 数据中 sales 为 80 对基线 100，orders 为 8 对 10，sessions 不变 100，conversion_rate 为 0.08 对 0.1，AOV 不变 10。Driver 与 US Scope 由同一支持性 Observation 联合支撑。

上述成功使用过临时错误恢复选项，不能冒充最终收紧版本的真实模型验收。此前多次失败 Run 保留，未清理或替换；不把“已完成工具记录数”当作包含失败调用的总尝试数。语义结果与 fixture 相符，但脚本仍报告 `semantic_evaluation=not_evaluated`，没有生成重复评测报告。

## 离线回归与后续

最终收紧版本真实复验通过，Run `dc6ab94f-8865-45bc-925d-db2ed8ab901f`：3轮、2次工具（sales query_metric → sales query_related_metrics），5 Observation / 5 Evidence / 1 Diagnosis，状态 succeeded，Driver conversion_rate，Scope marketplace=US。两次查询均携带任务 asin；完整 provenance 检查、新应用实例读回均通过。没有默认工具异常恢复；异常仍终止。此次结果确认最终实现的执行与持久化条件，不代表重复语义评测。隔离 PG 已停止，55440 监听数0，所有历史数据保留。

最终收紧版本：`backend` 目录执行 `python -B -m unittest discover -s tests -p 'test_*.py'`，691 tests / OK (skipped=6)。新增测试检查固定 filters 必填、常量、不可 null、不同任务 Schema 不串值；原有后端范围守卫和异常传播继续有效。跳过项不是数据库验收通过。

后续优先把真实模型结果经现有桌面调查详情页读回，再进入少量重复真实评测；Shopify Orders 权限验证仍依赖开发店与 read_orders 资源。不继续扩展任务调度底座。
