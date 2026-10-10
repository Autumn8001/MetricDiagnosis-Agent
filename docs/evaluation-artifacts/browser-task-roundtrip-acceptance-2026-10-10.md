# R4-005：浏览器提交与隔离PostgreSQL任务闭环

> 日期：2026-10-10；源码基线：`a58d28cce7126f76c47b4edf7465bbdb1f914112`。
> 当前判定：受控任务闭环通过；首次单次POST成功，两个验收断言纠正后以只读resume完成浏览器复验。不是一次无失败的完整脚本运行，也不是模型验收。

## 范围与产品意义

验证用户在默认React调查工作区点击提交后，任务确实通过实际HTTP进入PostgreSQL，由既有Worker领取、执行实际Analytics SQL、保存Observation/Evidence/Diagnosis，再由页面读取及刷新复读。工具选择和最终诊断意图由验收Runner控制，不宣称动态模型成功。

本次使用专用 `metricsleuth_r4_browser_acceptance` 数据库，与原有 `metricsleuth_r2_acceptance` 完全分开。既有仓库外PG17.11仅监听127.0.0.1:55440；新库在2026-10-10创建并确认没有app_state/warehouse schemas。数据为Synthetic/sandbox，不是Olist或真实商店。

## 实现边界

- `backend/scripts/serve_browser_task_acceptance.py` 只在验收脚本注入受控Runner，复用现有task application、Worker、短事务、Mapper与Diagnosis领域校验；产品入口不增加Fake模式。
- 显式准备只允许固定专用空库，执行既有迁移与warehouse schema，种1商品8天稳定数据。不覆盖已有schema、不删除旧数据、不加载`.env`、不调用模型。
- `frontend/scripts/verify-postgres-task-roundtrip.mjs` 先核对专用harness manifest及来源，再允许一次固定POST；不是修改只读历史验收脚本的安全规则。无fixture响应兜底或自动重提。
- 100/100/0的稳定指标支持no_material_anomaly；不制造Driver/Scope，不将固定Runner视为Agent动态策略或模型评测。

## 复现入口（专用空库已由操作人员准备）

在 `backend` 启动有限生命周期的验收API/Worker：

```powershell
python -B -m scripts.serve_browser_task_acceptance --database-url postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r4_browser_acceptance --source-id 3989c537-a555-4828-80e5-28b45a9624fa --port 8013 --prepare-synthetic-fixture
```

在 `frontend` 使用已构建的实际页面：

```powershell
node scripts/verify-postgres-task-roundtrip.mjs --api http://127.0.0.1:8013 --source 3989c537-a555-4828-80e5-28b45a9624fa --output C:/Users/星烛/.codex/visualizations/2026/10/09/01a11e69-2efd-7a23-8450-901add13d890/r4-005-task-roundtrip --allow-test-task-write
```

已产生历史的source不能自动重新运行写入验收；不要删除数据以让测试通过。需要再次提交时必须另行准备符合脚本严格守卫的专用空库；本次已有库不能重放。显式 `--resume-run` 仅用于只读复验已存在的唯一成功任务，禁止任何POST。

## 首次执行及安全恢复

- 实际浏览器只提交了一次，任务 `bba6edd9-c0fb-446b-8915-7140a44eb92b` 已成功；SQL确认1个成功Run及1/1/1/1个Tool Call/Observation/Evidence/Diagnosis。
- 第一次浏览器脚本退出1：`FAIL detail_observation_link`。原因是验收断言误要求可选Tool Call.query_reference与Observation.query_reference一致；现有Writer允许该工具字段为null，引用链由tool_call_id以及Observation→Evidence的query_reference建立。没有改产品API、Writer或数据来迎合验收。
- API确认current/baseline为100.00/100.00，relative_change为0；Evidence引用同一Observation与Tool Call，Diagnosis引用此Evidence，primary_driver=null且affected_scope={}。
- 受控Diagnosis的confidence=1来自固定规则及领域要求，不是模型置信度校准或准确率；limitations明确标记 `Controlled Runner acceptance; not a model diagnosis`。
- 首个API/Worker已停止，重新创建API应用进程并新连接读取同一成功任务，未启动第二Worker或追加模型请求。后续浏览器仅以显式resume只读模式完成剩余验收。
- 首次只读resume退出1：`FAIL browser_resume_rendered_fact`。验收脚本误要求UI显示Diagnosis ID；实际UI显示结论、值、Evidence IDs与限制，Diagnosis ID只在API中提供。修正脚本区分API身份断言与页面实际展示，不为测试修改业务UI。

## 只读复验入口

首个API/Worker停止后，本次用下列命令重新创建API应用（不启动Worker、不执行迁移、无模型请求）；manifest仅为验收用，不是产品能力：

```powershell
python -B -c "from scripts.serve_browser_task_acceptance import build_acceptance_app; import uvicorn; app,unused_worker=build_acceptance_app('postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r4_browser_acceptance','3989c537-a555-4828-80e5-28b45a9624fa'); uvicorn.run(app,host='127.0.0.1',port=8013,access_log=False,log_level='critical')"
```

然后在frontend目录只读验证指定Run；与写授权flag互斥：

```powershell
node scripts/verify-postgres-task-roundtrip.mjs --api http://127.0.0.1:8013 --source 3989c537-a555-4828-80e5-28b45a9624fa --output C:/Users/星烛/.codex/visualizations/2026/10/09/01a11e69-2efd-7a23-8450-901add13d890/r4-005-task-roundtrip --resume-run bba6edd9-c0fb-446b-8915-7140a44eb92b
```

## 主线程终验结果

| 检查 | 实际结果 | 证据边界 |
|---|---|---|
| 后端离线全量 | Ran 637 tests / OK (skipped=3) | 未配置专用DB测试变量；Fake/Hermetic结果，不含此次浏览器SQL验收 |
| 验收服务守卫专项 | 7/7 PASS | URL/参数脱敏、旧schema拒绝、manifest、Fake Analytics结果与受控Runner合同 |
| 前端客户端/格式化 | 18/18、10/10 PASS | 离线合同与精确数值格式化 |
| 语法/lint/类型/build | PASS | node --check、npm run lint、npm run build（含tsc） |
| 首次浏览器实际提交 | POST1，202 queued；随后succeeded | 真实Edge→实际FastAPI→PG→既有Worker；浏览器断言后续失败见上文，无二次提交 |
| SQL核对 | succeeded Run1、Tool/Observation/Evidence/Diagnosis各1；8天sales各100.00 | PostgreSQL 17.11，迁移001–004及warehouse/schema已在新库执行；稳定Synthetic，不是业务源 |
| API进程重新启动 | 同一Run及1/1/1/1事实读回 | 独立API进程、新数据库连接；未执行Worker或模型 |
| 最终浏览器resume | PASS，post_count=0；100.00/100.00/0，no_material_anomaly | 严格只读、终态无继续轮询、刷新并从历史重开、Evidence/Observation/Tool引用、限制文案、1440/390宽无横向溢出 |
| 原有测试库 | 178/117/155/70/70保持不变 | 原有Run/Tool/Observation/Evidence/Diagnosis，没有清理或覆盖 |
| 原型 | SHA256 AE62216B9871C4CF2EE3651EA5E4D1C87A10D499BECA2897DB69DC80823FE76C | 未修改产品UI或认可的HTML |
| 清理 | 两个API进程、Worker及PG停止；8013/55440无监听 | 保留隔离数据库与截图，没有删除历史数据 |

最终resume输出为 `PASS / real_database=true / controlled_runner=true / real_model=false / resume_read_only=true / post_count=0 / attribution_claim=false`。

主线程检查过桌面与移动端截图，位于仓库外：

- `C:/Users/星烛/.codex/visualizations/2026/10/09/01a11e69-2efd-7a23-8450-901add13d890/r4-005-task-roundtrip/postgres-task-roundtrip-desktop.png`
- 同目录 `postgres-task-roundtrip-mobile.png`。

UI实际展示Run/来源、Observation/Evidence/Tool IDs、原始数值、结论与限制；Diagnosis ID在API验证，不宣称页面已展示该字段。可选工具查询引用为null，Observation与Evidence保存一致查询引用；data_version仍是标签，不是不可变快照。

## 未完成的MVP gate

真实模型执行、异常Driver/Scope正确率、Shopify权限与持续同步、不可变数据版本、概览趋势/异常、可操作Lab、认证/部署仍需后续验收。本记录不批准生产部署、商店写入或任何新的收费模型调用。
