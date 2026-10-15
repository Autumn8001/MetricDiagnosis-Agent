# 真实模型成功记录的桌面浏览器回读（2026-10-15）

## 本阶段实际能力

已有真实模型调查可经 PostgreSQL → 实际 HTTP API → React production build → Edge 桌面页面打开，显示观察、工具、Evidence 和 Diagnosis，刷新后从历史重新打开一致。本阶段只读，不是新一轮浏览器提交→真实模型执行验收，不是外部持续业务数据验收。

基线 `c3360ff46f9c553468ce7e7ae07eed827f7b4b5d`。输入为该版本既有成功 Run `dc6ab94f-8865-45bc-925d-db2ed8ab901f`，来源 `d6fcaba4-5340-4d00-b7d0-6a54e299b708`，Synthetic/sandbox，版本 `synthetic-live-acceptance-2026-10-10-v1`。模型生成过程见[真实SDK记录](live-model-task-scope-2026-10-15.md)。

## 实际结果

- 复用仓库外 PG17.11 集群，仅监听127.0.0.1:55440，库 `metricsleuth_r2_acceptance`。
- 独立 task_application API 进程，仅监听127.0.0.1:8012；profile synthetic，绑定上述 source/version，model 为未调用占位值。不读模型 `.env`，不启动Worker，不迁移或注入数据。
- `verify-postgres-workspace.mjs --expect succeeded`：实际 Edge、1440×1000桌面、只读本机代理 PASS。显示2 Tool Call、5 Observation、5 Evidence、1 Diagnosis，conversion_rate / marketplace=US；刷新后重开同一Run通过。0浏览器写请求尝试，禁止fixture兜底。
- 脚本核对API Evidence→Observation→Tool Call及Diagnosis引用，Driver/Scope由被引用的supporting Observation联合支撑。页面断言ID、数值、查询引用、Driver和Evidence IDs；主线程查看两张实际截图，确认诊断卡片与限制说明可见。
- 数据库前后总数均为 Run190 / Tool126 / Observation167 / Evidence80 / Diagnosis72，没有新增记录。
- `npm run build`（含TypeScript）、`npm run test:tasks`（18/18）、`npm run lint`、`node --check scripts/verify-postgres-workspace.mjs`通过。未改产品UI或业务API，无需重跑后端全量替代浏览器证据。
- 验收后停止本次API进程和隔离PG，8012/55440监听数0，数据保留。未部署、未访问Shopify或模型。

首次脚本 preflight_joint_support 失败：错误地使用 `Diagnosis.change.evidence_id` 要求Driver证据。该字段是目标sales变化证据，Driver可以来自另一条被引用Evidence；修正脚本为检查被引用supporting Evidence的Observation同时包含conversion_rate和US。没有修改业务数据、Diagnosis或领域验证。

## 复现

先按 task application 启动说明配置并启动上述隔离PG/API，只运行API，不运行Worker。在frontend执行：

```powershell
npm run build
node scripts/verify-postgres-workspace.mjs --api http://127.0.0.1:8012 --source d6fcaba4-5340-4d00-b7d0-6a54e299b708 --run dc6ab94f-8865-45bc-925d-db2ed8ab901f --expect succeeded --output D:/Rag/Agent/metricsleuth-live-browser-20261015
```

截图在仓库外上述output目录：`postgres-workspace-desktop.png`及`postgres-workspace-diagnosis.png`。不提交浏览器profile或原始数据库。

## 剩余边界

下一验收应覆盖从浏览器新建任务、真实Worker/SDK执行到页面结果与刷新；本次成功历史读取不能代替该验收。还需要少量不同场景重复评测、Shopify实际权限/字段与更新链路，以及服务器访问保护和部署恢复。现有置信度是模型输出，非经过校准的准确率；固定版本标签不是不可变数据库快照。
