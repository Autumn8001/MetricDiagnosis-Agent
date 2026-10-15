# 持久调查语义回溯检查（2026-10-15）

## 结论与边界

两条此前真实模型成功生成的Synthetic调查，在真实PostgreSQL重新读取后，目标指标、预期终态及主要Driver均符合fixture设计；复用现有 `score_unsupported_claims()` 后，目标变化、Driver及Scope声明全部有引用证据支持。历史401失败记录仍按执行失败保留，没有生成Diagnosis。

这是**已知历史样本的回溯检查**，不是本轮新模型执行、预先注册的重复实验、独立holdout、整体准确率或外部经营数据验收。没有把2条成功样本汇总成“100%准确率”，也没有把历史失败从所选3条记录中删除。

源码基线：`2546350e784d6e801e87c8996d5e2552482bdeaa` 加本切片。分支 `codex/r5-004-validation`。本轮没有读取 `.env`、配置模型客户端、提交任务、执行Worker或迁移；没有访问生产/Shopify。

## 依据及判定

已有fixture在前7日每天sales100/orders10/sessions100，目标日sales80/orders8/sessions100，因此sales下降20%，conversion_rate由0.1降至0.08，sessions与AOV不变。预期 `target_metric=sales`、`status=diagnosed`、`primary_driver=conversion_rate` 从该设计指定，不能从模型输出反向生成。

对应fixture和实际模型执行记录见 [任务范围验收](live-model-task-scope-2026-10-15.md)、[浏览器提交验收](live-model-browser-submission-2026-10-15.md)、[历史401](live-task-authentication-attempt-2026-10-10.md)。此简单fixture没有异市场/商品/渠道负对照，不能唯一确定最精确的影响边界；本切片只检查Scope声明有无同Driver的联合Evidence支持，**不评分Scope准确率**。

| Run | 已存工具结果 | 结果 | 引用声明支持 | 复算退出码 |
|---|---:|---|---|---:|
| `dc6ab94f-8865-45bc-925d-db2ed8ab901f` | 2 | 指标/终态/Driver符合预期 | 3/3，Unsupported Claim Rate=0 | 0 |
| `e9e35d23-0870-44d0-a8c4-2ff76feb5b7d` | 5 | 指标/终态/Driver符合预期 | 4/4，Unsupported Claim Rate=0 | 0 |
| `d5fbbc43-3ddc-48c9-a263-feb864c40ba4` | 0 | 历史execution_failed；无Diagnosis | 不可评分，不填伪零值 | 1 |

工具列表示已持久化的工具记录，不代表失败前总尝试数。三条记录的Token/成本均为null；停止时机、冗余调用、独立Scope准确率均未评测。不能由已终止或预算未超推断“停止及时”。

## 实现及安全边界

- `backend/scripts/score_persisted_task.py`：只接受本机专用 `metricsleuth_r2_acceptance`；UUID参数、Synthetic/Sandbox数据库身份和版本匹配校验。单个repeatable-read只读事务读取来源及事实，statement_timeout=10秒。
- 复用 `InvestigationTaskReadRepository`、既有provenance校验、Evidence/Diagnosis领域模型及 `score_unsupported_claims()`，不另建Runtime或模型循环。
- 把持久记录还原为领域对象时保留Decimal、证据角色、原查询范围和引用；Driver/Scope不能从无关指标借用证据。
- `semantic_passed` 仅表示本脚本声明的指标/终态/Driver与引用支持检查通过，不表示R6全部完成。失败记录保留sample_count=1，语义不可评分项为null。
- 参数和读取错误只输出固定code，不输出连接串、原始异常、任意模型文本或外部响应。

## 复现

先按已有 [数据库验收记录](postgres-persistence-acceptance-2026-10-10.md) 启动保留的专用测试PG；不要初始化、重置或删除其数据。从 `backend` 运行：

```powershell
$testDb = 'postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B scripts/score_persisted_task.py --database-url $testDb --source-id d6fcaba4-5340-4d00-b7d0-6a54e299b708 --run-id dc6ab94f-8865-45bc-925d-db2ed8ab901f --data-version synthetic-live-acceptance-2026-10-10-v1 --expected-metric sales --expected-status diagnosed --expected-driver conversion_rate
python -B scripts/score_persisted_task.py --database-url $testDb --source-id 31f228eb-9fba-4fe2-911c-7b6850fc3c30 --run-id e9e35d23-0870-44d0-a8c4-2ff76feb5b7d --data-version synthetic-live-browser-acceptance-2026-10-15-v1 --expected-metric sales --expected-status diagnosed --expected-driver conversion_rate
python -B scripts/score_persisted_task.py --database-url $testDb --source-id 52e2a825-ef26-402f-b1ec-53f852c869d8 --run-id d5fbbc43-3ddc-48c9-a263-feb864c40ba4 --data-version synthetic-live-acceptance-2026-10-10-v1 --expected-metric sales --expected-status diagnosed --expected-driver conversion_rate
```

最后一条**应返回退出码1**，因为它检查的是历史执行失败，并非本轮评测器故障。退出码2表示读取/输入/还原不可用，不等于模型给错答案。命令依赖保留的三条记录，不能在空库直接复现历史模型执行。

实际只读核对：Run/Tool/Observation/Evidence/Diagnosis全表计数，复算前后均为 **191/131/175/86/73**。没有新增记录或改写既有结果。首次本地检查曾误用Reader方法名 `get_detail`，返回安全失败code；按实际 `get_details` 修正后通过，未修改业务Reader或数据库。

离线专项 `python -B -m unittest tests.test_persisted_semantic_replay -v`：8项通过，含不相关指标不能支持Driver/Scope、独立预期Driver不符、无异常、失败无Diagnosis、断链/错源/错版本、CLI脱敏与误连拒绝。这些专项数据由测试构造，不是新增真实模型样本。

全量后端 `python -B -m unittest discover -s tests -p "test_*.py" -q`：Ran710 / OK(skipped=6)。未配置数据库测试类的跳过不作为本次PG验收证据；另行执行的上述三个只读复算才是本轮真实PG证据。仍有既有event loop ResourceWarning及websockets依赖弃用警告；未修改或重跑前端。核对后已停止本轮启动的PG，数据保留。

## 后续验收门

R6仍需预先确定小样本异常/无异常及负对照，再在用户授权预算内执行新的真实调查，保留所有失败、可获取usage及停止依据。完整同进程真实模型浏览器复跑、Shopify持续更新与服务器部署仍未完成。本记录不关闭这些门槛。
