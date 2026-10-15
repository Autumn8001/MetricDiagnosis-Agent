# Sandbox 小样本评测准备

状态：输入校核通过，模型实验未执行。基线分支 `codex/r5-004-validation`，准备始于 `4640fa0`。本计划使用已有开发场景，不是 holdout，也不替代真实外部数据验收。

## 目的与当前证据

把“模型能运行”与“调查是否正确”分开。下一组实验需要同时覆盖不同 Driver、正常业务波动及未受影响的范围；失败必须保留在样本分母中。上一笔浏览器调查失败及限制见[失败记录](live-model-browser-failure-2026-10-15.md)，本计划不追加任何计费调用。

实现入口为 `backend/scripts/prepare_sandbox_evaluation.py`。它只读取源码、Ground Truth 与内存生成数据，不读取 `.env`，不连接数据库、不调用模型、不发布数据。复用 `build_sandbox_rows()` 与 `load_ground_truth_cases()`；内存独立计算当前值及前7日基线，校核全局指标、联合 Driver/Scope、稳定指标，以及每个负对照范围的目标指标和 Driver。判定与当前 Observation mapper 一致：下降至少10%为异常，绝对变化小于5%为正常。它是输入校核，不是 Analytics SQL 的替代实现或模型评分器。

## 固定实验输入

共同输入：`sales`，日期 `2026-01-31`，基线 `2026-01-24` 至 `2026-01-30`，`filters={}`、`group_by=[]`。不把正确范围预填给模型。source_id 由隔离发布产生，必须以发布后的 manifest 身份绑定；不得复用其他fixture的source/version或在共享测试库调用旧 injector/reset。

| 场景 | 评测侧预期 | 558行数据 SHA256（版本为 sandbox- 加此值） |
|---|---|---|
| canonical | diagnosed；conversion_rate；US / ASIN-A / Ads | `8d3c2b1524b71d2dcdf6fd1427a50646ba194e054b0fc1dca7f50e8fda63cc08` |
| traffic | diagnosed；sessions；US / ASIN-A / Ads | `49c3d75766e768fb629ccbddabb5ae9a230c0064e621e4a842f2c275845c18cb` |
| no_anomaly | no_material_anomaly；无Driver、空Scope | `fe1bc8e600fa47231f66a5e664a5d86b0c5996e25ccd9ef9b5119a35d9fc07ab` |

负对照及稳定指标直接来自 `warehouse/benchmark_cases.json`，不复制另一份答案。每场景14项实际数值校核通过；3项测试覆盖可重复性、产品请求Schema、正常数据无法冒充异常、负对照污染拒绝。

准备输出含 `evaluator_only` 与 `fixture_checks`，整个文件只能由评测端保管。产品仅接收 `task_input` 加真实 source_id；不得将场景名、Ground Truth、预期Driver、Scope、控制组或校核输出传入Prompt/工具。输出还包含配置、Runtime、工具、领域模型、评测器、任务执行入口和数据生成源码的逐文件SHA256；执行前再次生成并比较，任何变化均建立新版本，不能悄悄覆盖旧实验。

复现（backend目录，无外部调用、无写入）：

```powershell
python -B scripts/prepare_sandbox_evaluation.py
python -B -m unittest tests.test_sandbox_evaluation_preparation -v
```

## 待授权实验与预先确定的判定

提案为每场景2次，共6次；**当前 authorized_model_calls=0**，这不是新授权。后续先补一次完整浏览器成功gate，再根据预算确认是否执行该组。每次最多8工具/10轮，无自动重试或远程tracing；若接口鉴权或工具兼容失败停止整组并记录未执行项。未执行不是失败，已启动失败不能排除或换一笔成功重填。

执行前保存：Git SHA、准备输出、实际配置模型标识、SDK/依赖版本、运行Prompt与工具合同版本、隔离source/version；日志在仓库外持久保存，仅允许安全异常类型/HTTP状态和计数，不存密钥、原始错误或响应。所有数值和语义结论最后仍需真实PostgreSQL查询/持久事实复核，内存预检通过不等于数据库验收。

| 项目 | 预先固定的验收规则 |
|---|---|
| 执行闭环 | 同一API进程浏览器提交、Worker终态轮询、刷新回读；成功须有真实持久Diagnosis，失败不补Diagnosis |
| Driver/Scope | 复用 `score_core_case()`：目标/状态/Driver准确，三个维度值及Scope键集合完全匹配；报告逐项及exact_match，不用平均维度得分掩盖范围错误 |
| 引用支持 | 复用 `score_unsupported_claims()` 及持久provenance检查；Driver与联合Scope必须有本轮对应指标Evidence，不借其他指标拼接 |
| 证据完整 | 复用 `build_evidence_obligations()` / `score_evidence_citations()`；分别报告稳定指标与负对照覆盖，不把未查询当正常 |
| 停止条件 | 最终引用缺少上述必要证据记为证据不足；超预算由既有守卫拒绝。精确“过早停止/冗余调用次数”需按时间顺序复查每一步完整事实，当前未实现自动评分，不能由总工具数推定 |
| 消耗 | 保存实测轮次、工具尝试/成功数和耗时；Token/费用不可获取则null，不能由已保存工具数推断总请求数或填0 |
| 汇总 | 展示计划/启动/完成/失败/未执行数量；失败计入启动样本。仅6次开发样本，不声明统计稳定性、holdout泛化或真实业务因果 |

## 当前限制与下一步

此切片没有发布新数据库、运行Worker或模型，没有修改产品Runtime/提示词/接口。后端全量实际运行715项，OK(skipped=6)，其中新增3项输入准备测试通过；仍有既有event loop ResourceWarning及依赖弃用警告。全量中的Hermetic模拟输出不是本计划的模型实验结果，跳过数据库专项不算数据库通过。前端未修改，本切片未重跑前端。

真实外部来源、持久usage、精确停止时机评分及服务器部署仍未通过。当前预检只覆盖三种已支持的Lab场景；其余开发案例和独立holdout留待最小闭环稳定后评估，不通过扩大框架回避真实模型失败。

下一次实际模型执行前先确保安全日志落盘，再按新预算执行有限gate；Shopify需用户准备开发店/应用/read_orders，步骤见 [Shopify资源指南](../shopify-orders-probe.md)。
