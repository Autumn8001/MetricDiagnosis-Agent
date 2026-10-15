# 浏览器提交真实模型任务验收（2026-10-15）

## 范围与边界

本次只使用本机回环专用 PostgreSQL `metricsleuth_r2_acceptance`（`127.0.0.1:55440`）和一次新的 Synthetic/Sandbox fixture。没有访问 Shopify、外部业务数据库或生产环境。模型配置只从已忽略的根目录 `.env` 读取；没有输出、写入或提交凭据。自动重试和远程 tracing 均关闭，预算限制为最多 8 次工具调用、10 轮。

前端增加了一个最小的可选范围筛选控件。它只列出服务端来源能力已声明的维度；未填写时仍提交空筛选。此次浏览器明确选择 `asin` 并填写本次 Synthetic fixture 的 UUID，浏览器代理只放行这一笔准确的 `POST /api/investigations`。

## 已实际发生的链路

```text
Edge 桌面浏览器一次 POST
  -> FastAPI 202 queued
  -> PostgreSQL Worker
  -> OpenAI Agents SDK / 本机已配置模型端点
  -> Analytics SQL（仅本次 asin Synthetic 数据）
  -> PostgreSQL Tool Call / Observation / Evidence / Diagnosis
```

- 本次 Run：`e9e35d23-0870-44d0-a8c4-2ff76feb5b7d`
- 实际持久化终态：`succeeded`
- 安全 SQL 计数核对：5 Tool Call、8 Observation、6 Evidence、1 Diagnosis。
- 随后以独立只读 `task_application api` 读取同一 source/run，React production build 在真实 Edge 桌面显示并刷新重读通过；浏览器输出同样为 5/8/6/1。该只读显示过程没有调用模型或创建任务。

截图保存在仓库外：`D:\Rag\Agent\metricsleuth-live-browser-task-20261015`。

## 验收脚本生命周期缺陷与处理

首次运行时，`serve_live_browser_task_acceptance.py` 在 Worker 完成后立即停止 API。模型和 Worker 已成功，数据库也已保存终态，但浏览器轮询在 API 退出后无法获取终态，首次浏览器脚本返回 `browser_terminal`。

这是验收 harness 的生命周期问题，不是模型、工具或持久化失败。脚本现已改为等待浏览器读完终态后向仅供本机验收的 `POST /__acceptance__/complete` 发出结束信号，才停止 API/Worker。为控制模型调用和费用，本次没有在修复后再发起第二笔模型任务。

因此，本记录证明浏览器提交、真实 Worker/SDK 执行与真实持久化均发生，且同一记录的桌面刷新读取通过；但“同一存活 API 进程中浏览器提交后自动轮询到终态”的最终一体化 harness 复跑仍待下一次明确的有限模型调用授权。不得把该待复跑项说成已经完成。

## 清理与非结论

- 临时 API 已停止，隔离 PostgreSQL 已停止；`8014`、`8015`、`55440` 无监听。
- 数据库保留新 UUID 记录以供只读复核；没有 DELETE、TRUNCATE、DROP 或迁移操作。
- 这是一笔 Synthetic 数据上的真实模型执行，不是 Shopify、持续外部数据接入、模型重复性评测或生产部署验证。

## 后续复核：保活、单次提交与读取确认（2026-10-15）

本轮没有新增模型请求、任务、fixture或迁移。实现与验证的边界如下：

- Python harness独立验证完整任务意图，只允许一次提交。并发提交只执行一次底层写入；未知写结果不重试。此限制只存在于显式验收应用，不改变产品任务API的正常使用。
- 完成端点现在要求 `{"run_id":"本次Run ID"}`，Worker返回值必须匹配该Run。随后通过新连接读取持久详情，复用 `_validate_persisted_provenance` 验证引用链；失败任务、断链和读取失败均不能发出完成信号，错误只返回受控code。
- 浏览器必须在刷新后取得新的成功详情响应，并核对与首次持久事实一致；实际页面文字必须包含Diagnosis状态、引用的Evidence及其Observation/Tool/Query/Version。
- 实际loopback Uvicorn/HTTP生命周期测试使用受控Worker和内存事实：Worker结束后服务仍能响应，确认完成后进程正常退出。它不是真实模型、真实数据库或真实Edge验收。

复现离线检查（仓库根目录；不会读取 `.env`）：

```powershell
Push-Location backend
python -B -m unittest tests.test_live_browser_task_acceptance_guards -v
python -B -m unittest discover -s tests -p "test_*.py"
Pop-Location
Push-Location frontend
node --test scripts/test-live-browser-readback.mjs
npm run lint
Pop-Location
```

结果：专项11项通过；全量Ran702 / OK(skipped=6)；前端断言3项通过，lint通过。全量输出仍有既有asyncio未关闭event loop的ResourceWarning及websockets弃用警告；不把退出码0表述为无警告。

另行启动已有隔离PG17.11，使用原source `31f228eb-9fba-4fe2-911c-7b6850fc3c30`、原Run与本记录data_version，构建新的任务服务，在TestClient中调用新完成端点：错误Run返回409，原Run返回200，完整provenance通过；再次建立独立服务读回5/8/6/1。没有调用 `submit()` 或 `worker.run_once()`，也没有配置模型客户端。五张应用状态表总计数按Run/Tool/Observation/Evidence/Diagnosis顺序，前后均为 **191/131/175/86/73**。数据库已停止，数据保留。

真实PG复核可复用 `build_task_application()`、`install_acceptance_boundary()` 和 `service.get_run()`，限定本记录已有隔离库/来源/Run；调用完成端点前只在内存中设定 `run_id` 和 `processed` 为上述Run，核对新读取链及前后计数。不要调用live脚本的 `main()` 来复现这项只读检查，因为它会新建fixture并运行模型。

在已有测试PG启动后，从 `backend` 执行以下只读复现。它依赖本记录保留的Run，不是可用于空库的初始化脚本：

```powershell
$readbackCheck = @'
import threading
import psycopg
from fastapi.testclient import TestClient
from app.task_application import TaskApplicationConfig, build_task_application
from app.main import create_app
from scripts.serve_live_browser_task_acceptance import install_acceptance_boundary, validate_database_url
url = 'postgresql://metricsleuth_test@127.0.0.1:55440/metricsleuth_r2_acceptance'
validate_database_url(url)
source = '31f228eb-9fba-4fe2-911c-7b6850fc3c30'
run = 'e9e35d23-0870-44d0-a8c4-2ff76feb5b7d'
version = 'synthetic-live-browser-acceptance-2026-10-15-v1'
def counts():
    with psycopg.connect(url) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        return connection.execute('SELECT (SELECT count(*) FROM app_state.investigation_runs), (SELECT count(*) FROM app_state.tool_calls), (SELECT count(*) FROM app_state.observations), (SELECT count(*) FROM app_state.evidence), (SELECT count(*) FROM app_state.diagnoses)').fetchone()
before = counts()
config = TaskApplicationConfig(url, url, 'synthetic', source, version, 'not-called')
service, _ = build_task_application(config)
app = create_app(investigation_tasks_service=service, include_legacy_routes=False)
state = {'run_id': run, 'processed': run, 'exception_type': None}
complete = threading.Event()
manifest = dict(source_id=source, data_version=version, target_metric='sales', target_date='2026-10-10', request_filters={'asin':'67bac68b-7059-48b6-bb57-1c85a72b1f1c'})
install_acceptance_boundary(app, manifest, state, threading.Lock(), complete)
with TestClient(app) as client:
    assert client.post('/__acceptance__/complete', json={'run_id':'wrong-run'}).status_code == 409
    assert not complete.is_set()
    assert client.post('/__acceptance__/complete', json={'run_id':run}).status_code == 200
    assert complete.is_set()
fresh_service, _ = build_task_application(config)
detail = fresh_service.get_run(run, source)
assert detail.run.status == 'succeeded'
assert [len(detail.tool_calls), len(detail.observations), len(detail.evidence), len(detail.diagnoses)] == [5,8,6,1]
assert before == counts()
print('PASS: existing-run completion and fresh PostgreSQL readback; no task/model execution')
'@
python -B -c $readbackCheck
```

结论：原提前退出缺陷已有实际HTTP受控回归，真实PG既有模型结果也通过新读取确认；**修正后的一体化真实模型浏览器复跑仍未执行**，不得关闭该gate。本轮修复不改变既有模型结果和语义评分。
