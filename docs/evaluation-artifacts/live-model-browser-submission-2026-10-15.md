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
