# R4-002：持久调查工作区浏览器验收

日期：2026-10-10。源码起点：`7269f53c5a59ba189cc56ec95e82229a9bb8a185`。
范围：默认 React 页面消费已实现的持久调查 API；没有修改 Runtime、Worker、数据库迁移或认可 HTML 原文件。

## 实际产品能力

`frontend/src/App.tsx` 现在加载 `product/InvestigationWorkspace.tsx`。用户可以选择服务端配置的来源和支持指标，明确选择日期，提交调查、翻页查看历史，并打开已保存的 Tool Trace、Observation、Evidence、Diagnosis 和安全失败代码。页面不再启动时自动加载 Mock Fixture，也不调用旧场景注入接口。

五个导航区域保留认可原型的设计。工作概览计数只针对当前列表页（最多20条），不是全库总数；指标页是能力目录，不是实时趋势；来源页是配置身份，不是连接或刷新验证；实验室明确尚未接线。没有取消、自动重放、固定百分比或预设追问。

提交 POST 不自动重试；提交失败提示先检查历史，避免在结果不确定时重复创建。切换来源取消当前浏览请求并清空旧详情和日期，但不代表取消已入队任务。详情对 queued/running 每2秒刷新，终态或读取错误停止，错误后由用户手动重试。

## 验证边界

浏览器使用真实 Edge、实际 production build 和 Node 内置 HTTP 服务。服务返回**受控测试记录**，不是实际 PostgreSQL 查询或模型结果。成功记录也是受控 fixture；失败记录不补造缺失的 Diagnosis。脚本不启动 Worker、不读取 `.env`、不连接外部服务。

脚本：`frontend/scripts/verify-task-workspace.mjs`。运行时生成唯一临时浏览器 profile，结束后清理本次 profile，截图独立保留。需要本机 Edge，或显式设置 `METRICSLEUTH_TEST_BROWSER` 为浏览器可执行文件；未安装浏览器时不是验收通过。

## 复现

在 `frontend` 执行：

```powershell
npm run test:tasks
npm run lint
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json
npm run build
node scripts/verify-task-workspace.mjs
```

最后一个命令输出截图目录；也可传入绝对输出目录。构建写入被忽略的 `dist/`，不部署。开发代理默认指向显式任务应用 `http://127.0.0.1:8001`；`METRICSLEUTH_DEV_API_TARGET` 可显式覆盖。应用配置仍按 `task-application-acceptance-2026-10-10.md`，没有自动迁移或凭据读取。

在 `backend` 执行非数据库专项：

```powershell
python -B -m unittest tests.test_task_source_catalog tests.test_task_api tests.test_task_application -v
```

## 主线程验证记录

- 客户端合同：18/18 PASS，Fake Fetch，无数据库或模型。
- 来源目录/任务 API/应用专项：24/24 PASS，TestClient/受控配置。首次误写不存在的模块名 `test_investigation_source_catalog` 导致命令失败；纠正为现存 `test_task_source_catalog` 后通过，未修改业务代码迎合测试。
- 首轮浏览器：PASS，验证失败事实、成功证据、显式日期提交一次、状态轮询至失败并停止、来源切换清空旧详情/日期、503安全错误、无旧注入调用。
- 最终主线程 lint / TypeScript / production build：全部 PASS，lint 无警告。
- 最终浏览器：PASS；新增验证 next/prev 实际改变列表，手机新建及历史入口均可识别；仅一次 POST，`detailReads=2`，终态后不再轮询。所有截图尺寸均通过无页面水平溢出的断言。
- 最终截图本机目录：`C:/Users/星烛/.codex/visualizations/2026/10/09/01a11e69-2efd-7a23-8450-901add13d890/r4-002-browser-final/`。截图为受控 fixture，不提交为真实模型运行记录。

## 原型与独立审查

保留238px深色侧栏、浅画布、白蓝表面、系统字体、左结果右过程和移动五导航。原型 SHA-256 仍为 `ae62216b9871c4cf2ee3651ea5e4d1c87a10d499beca2897db69dc80823fe76c`。

首轮独立审查要求恢复星芒品牌/首页图标/实验分组、明确历史 summary、提高小字可读性和对比、移除 Lab 重复 eyebrow，并更新过时的 Current 文档。修复集中执行一次，随后做最终复拍；不重新设计原型。

主线程复拍检查了成功桌面、手机新建及手机历史入口；视觉实现记录在根目录 `DESIGN.md` 与 `.impeccable/design.json`。该记录提取认可原型/实际代码，不新定品牌或产品方向。

独立 finish reviewer 最终结论 `ship`：原修复项全部解决；该结论仅针对本次 UI 接线和视觉完成度，不批准真实数据库、模型或生产闭环。

## 剩余 gate

下一步先做隔离 PostgreSQL → 显式 API → 实际浏览器历史读取，不调用模型或注入新业务事件。随后继续真实模型成功 gate 与持续外部来源验证。当前不能宣称真实模型成功、持续真实数据接入、完整指标趋势、Sandbox事件闭环或服务器部署完成。
