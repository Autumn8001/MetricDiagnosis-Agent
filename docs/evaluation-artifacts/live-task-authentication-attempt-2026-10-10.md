# 真实SDK持久调查：第二次授权尝试因鉴权失败

> 日期：2026-10-10；源码基线：`850aa2340664fd35c4acfea0617c1c215ab7d8b7`，加本次验收CLI安全参数解析。
> 判定：FAIL，`AuthenticationError / HTTP 401`；真实模型成功gate仍未通过。

## 范围与授权

用户明确授权再执行一次隔离Synthetic调查，沿用本机现有`.env`模型/端点配置，最多8工具/10轮，禁用自动重试和远程tracing。不访问生产、Olist原始数据或Shopify，没有更换模型、探测模型列表或追加请求。该次授权已使用，下一次真实调用需要新授权。

执行复用 `backend/scripts/verify_live_task_persistence.py`、既有SDK、task API、来源绑定Runner与Worker。本轮仅将该脚本的argparse错误变为固定`invalid_arguments`，避免未知参数回显敏感输入；没有改业务Runtime、Prompt、预算、数据库迁移或诊断领域规则。

实际API模式为`chat_completions`，配置由显式文件提供；没有打印密钥、端点原文、原始异常、外部响应或密钥指纹。上一次记录的模型标识不作为本次服务商映射的证明。次数/超时不构成费用硬上限；未检查账单，不能由401断言费用为零。

## 执行与证据

专用测试库：PostgreSQL 17.11，`metricsleuth_r2_acceptance`，loopback `127.0.0.1:55440`。执行前真实SQL确认库名/监听地址/端口、活动Worker任务0，原Run/Tool/Observation/Evidence/Diagnosis计数为178/117/155/70/70。

新生成一个测试产品八行数据，baseline七天sales100/orders10/sessions100，目标日sales80/orders8/sessions100；参数化SQL与任务固定asin过滤隔开其他既有数据。这是受控Synthetic变化，不是平台数据、不可变快照或新增Benchmark案例。

```text
实际任务API → queued → Worker → 既有SDK
→ AuthenticationError / 401
→ failed / execution_failed
→ 新应用实例与新数据库连接读取同一失败任务
```

| 项目 | 实际结果 |
|---|---|
| Run | `d5fbbc43-3ddc-48c9-a263-feb864c40ba4` |
| Source | `52e2a825-ef26-402f-b1ec-53f852c869d8` |
| Fixture product | `627e45fc-1759-4de8-8252-1a7ca6f028da`，新测试UUID |
| Data version | `synthetic-live-acceptance-2026-10-10-v1`，现有标签，非快照 |
| Script exit/status | 1 / failed |
| Runtime exception/status | `AuthenticationError` / 401；只记录类型和整数状态码 |
| 完成模型轮数 | null，未获得可验证值，不称0轮成功 |
| Tool/Observation/Evidence/Diagnosis | 0/0/0/0 |
| API安全失败码 | `execution_failed` |
| 新应用重连回读 | PASS，同一详情完全一致；没有再次运行Worker或模型 |
| SQL失败字段 | 与`jsonb_build_object('code','execution_failed')`相等；不含原始异常 |
| Fixture SQL | 8行、sales780.00/orders78/sessions800 |
| 最终库计数 | 179/117/155/70/70，仅增加本次失败Run，无伪造事实 |
| 活动Worker任务 | 0 |

人工复核SQL首次误用了API投影字段`failure_code`作为数据库列，SELECT失败且无写入；随后按实际Schema的`failure_details`重查并得到上表结果，没有为验收修改Schema。

测试实例首次启动未显式指定端口，实际只监听本机5432；在任何模型执行前已停止该自启测试进程并按55440重新启动、验证。没有连接其它数据库实例。验收及只读复核后均停止本线程启动的PG，5432/55440/8013无监听；隔离数据保留，无删除/覆盖。

## 验收口径

当前脚本`status=passed`只表示SDK执行、持久化、Evidence引用和预算条件满足，不等于Driver/Scope或停止条件正确；合法的insufficient_evidence等终态也可能满足持久化gate。后续真实成功运行必须独立评估结论与实际Trace/Observation，不将此脚本当模型准确率评测。本次连执行gate也未通过。

401只能证明本次请求鉴权未通过，不能单独确定密钥失效、端点配置、服务商授权/路由或模型映射是哪一项原因。用户需在本机安全配置和提供方控制台确认；不要向聊天或Git提供凭据。不会因为此失败更换SDK或自动切换模型。

## 本轮主线程验证

- `python -B -m unittest tests.test_live_task_acceptance_guards tests.test_shopify_orders_probe -q`：26/26 PASS，patch/MockTransport，未访问实际服务。
- `python -B -m unittest discover -s tests -q`：Ran 638 tests / OK (skipped=3)，三个专用数据库测试类未配置而跳过；不是本次模型或Shopify通过证据。
- `git diff --check`；两文件安全修改经主线程审查。没有新增产品模块、同步底座、安装、推送或部署。

首次授权的`InternalServerError`记录仍保留在 [首次尝试](live-task-persistence-attempt-2026-10-10.md)，本记录不覆盖它。R4-005受控浏览器闭环与此真实模型失败分开记录。
