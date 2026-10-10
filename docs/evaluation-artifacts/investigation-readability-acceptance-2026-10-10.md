# R4-004：数值与调查明细阅读验收

日期：2026-10-10；基线：`17832804e22b049735aa460ca3edd30f98eac150`。
范围：仅前端数据呈现与验证工具；不改API、SQL、Worker、模型或原型。

## 用户可见能力

`frontend/src/product/formatDecimal.ts::formatDecimal` 用字符串逐位处理实现最多4位小数half-away-from-zero舍入和千分位；非零舍入显示≈，尾零移除不冒充近似。字符串大整数保留精度；null显示—不转0。科学计数在有界范围展开，极端长度/指数回退原文，避免无界扩展。Number输入只能保留API已交付的JavaScript表示，不恢复此前丢失精度。

Observation与Diagnosis change复用格式化显示，原始当前/基线/变化保留在可键盘展开的原生details。Observation第一条默认展开，其余明细按需读取；全部记录和外部维度摘要仍呈现。区间、筛选、维度、Observation/Tool Call ID、查询引用及错误code均保留。比率不改为百分比，不推测销售口径/币种，不生成Diagnosis。

认可HTML SHA-256仍为 `AE62216B9871C4CF2EE3651EA5E4D1C87A10D499BECA2897DB69DC80823FE76C`。Impeccable健壮性指引用于有界数据/可读字号/键盘明细，不更换原型视觉体系。

## 主线程验证

在 `frontend`：

```powershell
node scripts/test-decimal-format.mjs
npm run test:tasks
npm run lint
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json
npm run build
node scripts/verify-task-workspace.mjs C:/Users/星烛/.codex/visualizations/2026/10/09/01a11e69-2efd-7a23-8450-901add13d890/r4-004-browser-final
```

格式10/10、客户端18/18、lint/类型/build通过；测试runner只编译到自己创建的临时目录并清理该目录。后端未修改，本轮不把上一轮630项回归描述为重跑。

真实Edge与受控HTTP fixture最终PASS（POST1、detailReads2）。新增断言覆盖3条Observation全部保留、首条展开/其余折叠、长小数原值、≈标记、超过2^53大整数原值及键盘展开维度引用；仍覆盖分页/提交/轮询停止/来源切换/安全错误。第一次模拟Enter未触发summary，验收超时，未记为通过；确认native焦点并改用Space事件后实际展开通过。新增明细文字保持12px可读尺度。桌面/手机截图已检查，无页面水平溢出。

## 实际PostgreSQL复验（不是fixture）

复用仓库外专用PG17.11 / loopback55440 / `metricsleuth_r2_acceptance`，先确认停止后启动；没有initdb、迁移、导入或Worker。显式本地API8012/PID51584绑定既有Olist validation来源，model为未调用占位符，不读`.env`或模型凭据。

```powershell
node scripts/verify-postgres-workspace.mjs --api http://127.0.0.1:8012 --source bbaf0fe3-c61a-4d03-acca-4e10b69d24b7 --run 102bea3f-cc93-400a-a871-6ef90238972f --output C:/Users/星烛/.codex/visualizations/2026/10/09/01a11e69-2efd-7a23-8450-901add13d890/r4-004-postgres-browser
```

实际PASS：4Tool Call、27Observation、0Evidence、0Diagnosis；读取同一受控Runner生成的失败历史、刷新复读与原始数值/引用核对通过。浏览器代理拒绝写请求，本次写请求0。直接READ ONLY计数验收前后均为Run178 / Tool117 / Observation155 / Evidence70 / Diagnosis70，没有新增或修改调查。首条GMV展示16,861.09与13,355.61，原始16861.09与13355.61仍在明细；长比率显示≈0.2625，精确原值保留。

桌面/手机证据目录如命令所示，主线程已查看截图。验收后核对API进程身份再停止PID51584，停止本轮启动的隔离PG，`pg_ctl status`返回no server running（exit1表示已停止），数据与截图保留。

## 尚未证明

没有Shopify或真实模型调用；Olist是静态公开数据，不是连续来源。没有新的成功Diagnosis、浏览器提交→真实Worker完整闭环、生产部署或认证验收。27条结果虽然明细可折叠，但没有增加过滤/排序/分页，不能声称大规模数据阅读问题完全解决。
