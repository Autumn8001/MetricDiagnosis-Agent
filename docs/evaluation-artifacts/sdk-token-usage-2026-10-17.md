# SDK Token用量采集（2026-10-17）

## 已实现与边界

基线`d8484d6`。现有`EvidenceDrivenRunSummary`增加可选只读`token_usage`，仅允许`responses/input_tokens/output_tokens/total_tokens`四个正整数字段。`_reported_token_usage()`读取SDK每轮`raw_responses[].usage`；每轮均有正的输入/输出Token且总数一致才汇总，否则整体为`None`。缺字段、SDK归零、部分轮次无用量、布尔值及不一致计数不当作零消耗或完整总数。

这是SDK报告值，不是独立核验的上游账单。`responses`是返回的模型响应数量，不是网络请求尝试数或工具次数。保守策略可能将合法零输出轮次也标为未知；不为填表猜测缺失值。

`run_sandbox_live_evaluation.py`与`serve_live_browser_task_acceptance.py`把有效计数写入已有仓库外安全日志`telemetry.tokens`，未返回用量时仍为null，`cost`保持null。不保存原始usage载荷、请求ID、Prompt或响应正文。失败中途没有返回完整summary时仍未知，没有新增模型调用、自动重试或远程tracing。

没有数据库迁移、用量API或前端展示，也没有回填历史6笔数据。产品级用量历史及实际CPA是否返回完整计数仍未验证；此切片不关闭整个usage/成本或R6质量门。

## 依据与验证

核对了[官方Agents SDK入口](https://developers.openai.com/api/docs/guides/agents-sdk)；该入口不足以确定细节，具体字段以本机`openai-agents 0.22.0`的`agents.items.ModelResponse`、`agents.usage.Usage`源码为准。SDK字段存在不等于当前兼容端点一定提供用量。

- SDK ScriptedModel三轮各输入100/输出20，实际Runtime summary汇总为300/60/360，响应数3；测试数值仅为受控fixture，不是实际模型消耗。
- 汇总不可写，额外原始字段拒绝；缺失/归零/部分缺失/布尔值/不一致均保留未知。原有浏览器失败遥测仍不记录原始异常，成功无用量仍不估算费用。
- `python -B -m unittest tests.test_diagnosis_runtime tests.test_live_browser_task_acceptance_guards tests.test_sandbox_live_evaluation_guards -v`：33项通过。
- `python -u -B -m unittest discover -s tests -p 'test_*.py'`：Ran727 / OK(skipped=6)。默认离线，数据库类跳过不算数据库验收；既有解析提示/依赖警告不作为失败或真实调查证据。

前端未改。本切片没有启动数据库、访问外部服务或消费模型预算。下一次经授权的真实调查再核对实际用量是否可得；原6笔严格证据覆盖仍0/6。
