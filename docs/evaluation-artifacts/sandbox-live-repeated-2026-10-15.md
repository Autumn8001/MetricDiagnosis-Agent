# 三场景真实模型重复评测（2026-10-15）

## 结论

用户授权最多6次调查，实际执行6次、失败0次、未执行0次，没有自动重试或补跑。转化率下降、流量下降、无明显异常各2次，目标/终态/Driver/Scope完全匹配6/6，持久引用链6/6有效，22/22诊断声明有证据支持。**按事前固定的完整证据要求，严格通过0/6**：稳定指标/负对照引用不完整。不能用“执行成功”替代质量验收。

这是既有Synthetic开发基准，不是holdout、持续外部数据或生产经营验证。6个样本不足以证明稳定泛化。精确停止时机、Token/成本仍未取得；此切片不关闭整个R6或MVP。

## 输入与执行边界

依据[已制定计划](sandbox-evaluation-plan-2026-10-15.md)。共同请求sales、2026-01-31、前7日基线、空filters/group_by；不预填正确Scope。每次8工具/10轮，单请求120秒，零重试与禁用远程tracing。配置模型标识 `gemini-3.8-flash-high`，chat_completions；未独立核验上游实际模型身份。

`run_sandbox_live_evaluation.py`没有复用旧的覆盖式injector；只在本机新建三个唯一Sandbox库，复用 `publish_sandbox_dataset()`、manifest身份读取、`build_task_application()`、任务服务及既有Worker/SDK。每场景558行，两次重复只读同一已发布输入；状态使用原隔离 `metricsleuth_r2_acceptance`，不执行迁移或旧reset。运行时收到的请求只有来源/指标/日期/范围，Ground Truth只供评测。鉴权、工具协议或传输错误会停止整组，本次未触发。

| 场景 | 来源UUID | 新建数据库 |
|---|---|---|
| canonical | `c24cd4d6-1c6a-40b8-bd9e-a1d99b7d136f` | `metricsleuth_sandbox_r6_d28e2792017f_canonical` |
| traffic | `40aca890-1c8c-456e-bb48-b79f963667d2` | `metricsleuth_sandbox_r6_d28e2792017f_traffic` |
| no_anomaly | `43fe5be1-7610-46f0-ba43-3144bcfc2e35` | `metricsleuth_sandbox_r6_d28e2792017f_no_anomaly` |

数据版本与计划中的三个SHA256一致。日志在首笔前保存了输入计划和Runtime/指标/领域/评分器/生成器源码指纹；执行后逐项重算一致。新增验收脚本随本次提交保存，不声称它也在旧准备脚本枚举的哈希集合中。

## 逐笔结果

全部succeeded，均有1条Diagnosis；四笔异常Scope均为US / ASIN-A / Ads，两笔正常Scope为空。表中覆盖率是最终**引用**的证据义务覆盖，不是工具查询成功率。

| 场景/重复 | Run UUID | 工具/观察/证据 | 轮数 | Runner耗时 | 证据覆盖 |
|---|---|---|---|---|---|
| canonical 1 | `48e4c2d7-3799-469a-9c4d-72ed38b54537` | 5/32/3 | 6 | 51.524秒 | 3/9 |
| canonical 2 | `5f30b1ea-0eb2-436b-9aab-1ac243addba4` | 5/32/6 | 6 | 44.901秒 | 4/9 |
| traffic 1 | `23a6c110-f9c5-403d-9e0b-ed06ff957c5f` | 6/38/6 | 7 | 43.817秒 | 4/9 |
| traffic 2 | `4b3c432a-1f2a-4e1f-9c8a-0c69a060d443` | 7/37/7 | 8 | 50.323秒 | 5/9 |
| no_anomaly 1 | `8f63a57d-7d6d-41af-bf91-d41ce47b07b4` | 2/5/5 | 3 | 27.228秒 | 5/13 |
| no_anomaly 2 | `5c0e3b0d-8ae9-45c1-88da-a4d2d146187f` | 2/5/5 | 3 | 20.128秒 | 5/13 |

共27工具/149观察/32证据/6诊断，平均Runner39.6535秒，平均工具4.5次；不是单请求耗时或费用估算。整体strict_passed=0使脚本exit1，这是质量门未满足的正常报告，不是6次运行崩溃。没有为通过而改提示词、输入或评分门槛。

## 已定位的质量缺口

新数据库连接读取所有Observation后，四笔异常都已出现5/5预期正常对照维度值，但最终Diagnosis没有完整引用它们：主要是“查到但未引用”。两笔正常调查只有全局5指标，维度正常对照观测为0/8：是“没有查到”，不能把未查询当正常。

`score_core_case()`验证结论；`score_unsupported_claims()`验证已声明内容；`score_evidence_citations()`验证最终引用对既定义务的覆盖。三个结果不同不矛盾：结论可以正确、已有声明可以可靠，但论证不完整。正常全局波动也不能证明所有分段都正常。完整列举已知开发对照是本次严格基准，未因此向产品Runtime泄漏答案。

下一修复应聚焦通用证据引用与结论范围：复用已得到的正常Observation，保留能排除其他解释的引用；若只有全局正常数据，明确未验证分段，不暗示全部业务正常。不新增固定SQL路径、队列或另一套Agent。修改后需要新授权复验，旧6笔结果保留不改分。

## 日志与只读复算

仓库外日志：`D:/Rag/Agent/metricsleuth-r6-six-run-20261015-safe.jsonl`，SHA256：

`74e5fbd0cd84b827d959b2e4c84f476bb6d270bd6f0d69a71775b1c7a616a6af`

包含输入、来源/版本、任务标识、安全异常及逐笔评分；不保存密钥、原始异常、Prompt或上游响应。`replay_sandbox_live_evaluation.py`复用同一评分函数，以新连接的repeatable-read/read-only事务读取持久事实，验证来源与输入指纹、拒绝重复Run/实验位置。

```powershell
# 原隔离PG显式启动后，从backend执行；不读取.env或调用模型：
python -B scripts/replay_sandbox_live_evaluation.py --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance --journal D:/Rag/Agent/metricsleuth-r6-six-run-20261015-safe.jsonl
```

实际exit0、replayed_runs=6、new_model_calls=0，全部评分与原日志一致。若未来相关源码变化，应在原提交复算，不能混用新规则与旧实验。历史200笔Run不属于本次样本分母；原始失败仍保留。

最终Run/Tool/Observation/Evidence/Diagnosis计数200/173/348/124/80，之前194/146/199/92/74。三个场景库均保留，测试PG已正常停止，55440/8014无监听，未部署/改main。

## 离线检查与剩余限制

新增执行/评分/复算守卫5项通过，覆盖未授权不得启动、遇鉴权/协议错误停止、正确Driver不掩盖错误Scope、失败不伪造评分、重复实验拒绝。添加复算入口后的全量离线回归exit0，仍有既有event loop ResourceWarning及依赖弃用警告；不将其中Hermetic输出当真实模型结果。前端未修改，本切片未重跑前端。

本次6次预算已全部使用。Shopify资源状态问题已提出，尚未收到更新，仍不能宣称持续外部数据已接入。部署、安全认证/TLS/备份演练及usage仍待完成。

## 2026-10-17 最小修正（未调用模型）

基线`ff66701`之后，`backend/app/agent_runtime/diagnosis_runtime.py`补充通用提示：最终引用应保留实际用于排除其他Driver或区分受影响/正常分段的Observation，相关稳定指标也应引用；优先用已有结果，不为引用重复查询。正常聚合结果可能掩盖分段变化，是否继续调查仍由模型结合请求、Observation和预算决定，没有固定维度顺序或已知对照值。

正常结论另由应用附加固定限制说明：只适用于引用的指标范围与比较期间，未查询分段仍可能异常。说明加入DiagnosisDraft并进入最终composition，模型原始intent不被改写；不改变证据集合、Driver/Scope或评分要求，不把范围说明计为负对照。

`python -B -m unittest tests.test_diagnosis_runtime tests.test_sandbox_live_evaluation_guards -v`共13项通过；全量离线回归exit0。测试使用ScriptedModel/Mock Analytics，验证SDK接线、原输出保留、无额外查询/证据与已有拒绝规则，不证明真实模型会完整引用对照。没有新模型或数据库调用，前端未改，既有6笔评分保持原样。全量测试包含Hermetic场景输出，不能当真实调查证据。

旧日志的源码指纹对应修正前代码，重放该基线请使用`ff66701`，不要用当前提示词指纹替换旧日志。修正后的真实调查、严格覆盖改善、正常场景维度检查及停止行为仍待新授权验证。

### 受控SDK与真实PostgreSQL回读补验

2026-10-17在本机专用`metricsleuth_r2_acceptance`实际执行：

```powershell
$env:METRICSLEUTH_TEST_DATABASE_URL = 'postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
python -B -m unittest tests.test_postgres_task_application.PostgresTaskApplicationTests.test_sdk_normal_scope_disclosure_survives_fresh_application_read -v
```

结果`Ran 1 test / OK`。新增测试只用ScriptedModel决定一次sessions查询与最终intent，查询工具/SQL/Observation映射/进度checkpoint/Writer和HTTP读取均为实际实现。当前日与基线均为100，Task终态succeeded；重新构建TaskApplication和TestClient后读回1工具/1观察/1证据/1诊断、原有asin过滤器、空分段/Driver、原证据ID及范围说明。SDK原始intent限制字段保持不变，没有自动补出正常分段证据。

首次运行因测试封装重复传入`run_config`而失败，已改为复用SourceRunner传入的配置后通过，失败任务保留。现有测试fixture会幂等重放应用迁移，并为每次运行新增唯一来源/商品与8行Synthetic日数据；没有删除或重置既有样本。PG实际启动和停止均成功，数据保留。未调用外部模型、未读取.env、未变更前端或生产；原6笔真实模型严格评分仍为0/6。此次只证明修正能沿实际持久化链路保存/回读，不证明提示词改善了真实模型引用。
