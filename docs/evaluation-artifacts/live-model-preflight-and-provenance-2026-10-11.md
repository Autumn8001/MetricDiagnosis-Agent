# 模型预检失败与持久证据链校验

> 日期：2026-10-11；基线：`d672131e232560dc24c2ebc6cd56786c28fb07a3`，加本次验收脚本校验。
> 判定：一次实际预检返回401，完整调查未执行；持久证据链检查已用既有真实PostgreSQL记录验证。

## 授权与实际请求

用户新授权先做低成本连通性/工具协议检查，通过后才执行一次隔离Synthetic调查（最多8工具/10轮）。禁用重试与远程tracing，不修改CPA服务或其他账号。Shopify开发店及read_orders尚未准备好，本轮没有商店调用。

主线程读取仓库根目录`.env`，没有读取backend内另一份配置。四个必需字段存在且无重复声明；未发现已知占位密钥、与`.env.example`相同的密钥或密钥内部空白。显式创建的AsyncOpenAI客户端使用同一API key及Base URL，max_retries=0。Base URL为本机HTTP端点、路径/v1；不记录完整地址、密钥或指纹。上述检查只能排除这些本地读取问题，不能证明密钥被服务端接受。

实际单次非流式Chat Completions请求使用配置标识`gemini-3.8-flash-high`、max_tokens=256、timeout=30秒。工具为无副作用`acceptance_ping`，要求一次调用且参数`marker=ok`；JSON Schema限制额外字段，tool_choice指定此工具。此探测若成功只能证明接受工具声明并生成符合参数的调用，不能替代SDK工具往返或结构化Diagnosis测试。接口形式参考[官方Chat Completions文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)；CPA实际兼容性以请求结果为准。

| 项目 | 实际结果 |
|---|---|
| 实际请求数 | 1；无自动或手动重试 |
| 模型 | 请求标识gemini-3.8-flash-high；未获得服务端模型回执，不能证明上游执行了该模型 |
| API模式 | chat_completions |
| 预检 | AuthenticationError / HTTP401 |
| 工具调用 | 未获得模型响应，完成工具调用0 |
| Token/费用 | 未获得usage，不记为0Token或零费用；未查看账单 |
| 完整调查 | 因前置gate失败而未执行；没有新Run、Tool、Observation、Evidence或Diagnosis |

已停止请求。401不能单独区分访问密钥不匹配、服务端授权策略或代理路由/上游鉴权问题；未查看CPA其他账号凭据，未修改服务。需要用户在本机确认项目密钥与CPA允许的客户端访问配置一致；修复后另行确认一次有限探测/调查，不自动沿用本次请求继续消耗。

## 验收工具改动，不是新产品模块

`backend/scripts/verify_live_task_persistence.py::_validate_persisted_provenance`只处理已读回的详情，输出布尔检查与固定错误码：

```text
Diagnosis引用 → 已保存Evidence → 已保存Observation → 已保存Tool Call
                 query_reference一致；各层data_version与请求来源绑定一致
```

检查来源/provider/environment、声明数量、唯一非空ID、完整引用链、DiagnosisChange引用、成功状态及非空事实。工具query_reference可为null，不制造不符合实际Writer的约束。data_version仍是标签，不代表不可变快照。脚本输出新增`acceptance_scope=sdk_execution_and_persistence`及`semantic_evaluation=not_evaluated`；passed不代表Driver、Scope或停止时机正确，不向Runtime注入Ground Truth。

## 主线程验证与复现边界

- `python -B -m unittest tests.test_live_task_acceptance_guards -v`：18/18 PASS（离线），包括断链、版本/来源/数量冲突、重复ID、缺失与非列表引用、缺失change证据、安全错误、模型调用opt-in守卫。
- 最终全量：`python -B -m unittest discover -s tests -p 'test_*.py' -q`，Ran659 tests / OK(skipped=4)；四个专用数据库测试类未配置而跳过。Hermetic结果不是模型准确率；本轮真实PG仅为下述只读复验。日志出现SQL解析fallback和unclosed event loop ResourceWarning，未导致失败，作为后续测试资源清理债务保留，不隐去警告。
- 真实PG：显式启动仓库外既有隔离PG17.11，仅监听127.0.0.1:55440；通过新TaskApplication、TestClient GET及新连接读取旧记录，不启动Worker，不迁移、不注入fixture、不调用模型。
- `metricsleuth_r4_browser_acceptance`既有成功Run `bba6edd9-c0fb-446b-8915-7140a44eb92b`，source `3989c537-a555-4828-80e5-28b45a9624fa`，version `synthetic-eight-days-v1`：九项检查全部true。工具查询引用为null仍合法；只在内存篡改Evidence.tool_call_id后被拒绝。
- `metricsleuth_r2_acceptance`既有401失败Run `d5fbbc43-3ddc-48c9-a263-feb864c40ba4`，source `52e2a825-ef26-402f-b1ec-53f852c869d8`，version `synthetic-live-acceptance-2026-10-10-v1`：正确返回失败，未伪造Diagnosis。历史身份与记录见[第二次调查尝试](live-task-authentication-attempt-2026-10-10.md)和[受控成功记录](browser-task-roundtrip-acceptance-2026-10-10.md)。

复读时可使用`TaskApplicationConfig`固定上述URL/source/version/profile=synthetic/model=unused-no-model，`build_task_application`只构造服务/Worker；仅调用`create_app(..., include_legacy_routes=False)`的GET `/api/investigations/{run_id}?source_id=...`，将response.json传入上述纯函数。禁止调用返回的Worker、POST或模型验收脚本主入口来重放历史。

直接只读SQL核对前后Run/Tool/Observation/Evidence/Diagnosis数量保持不变：R4专用库1/1/1/1/1，R2专用库179/117/155/70/70。验收后通过pg_ctl正常停止本轮启动的隔离PG，保留所有数据；没有新的API/Worker后台进程。主线程审查最终diff并执行上述测试，不以子代理返回成功代替验收。

本轮不修改Agent、Prompt、数据库结构、产品API或前端；真实模型成功gate与Shopify持续更新gate仍未通过。
