# R4-006 指标页接线验收

状态：验收通过，独立视觉复核ship。基线：`3b5078e`，本轮只改变客户端/页面与验证工具，没有后端、数据库迁移或Runtime改动。

## 产品能力与边界

经营指标页保留认可原型的导航、配色和能力目录；标题下提供显式指标/日期和只读查询。展示实际单日值、前七日基线、原始相对变化、单位和既有mapper状态。没有趋势图、自动扫描、自动模型调查或预填示例日期。缺失值不转成0。

来源身份/环境/版本标签与目录不一致时拒绝展示。修改输入、来源切换和离页使旧请求失效。原生明细保留原始Decimal、样本量、source_status、数据期间、查询完成时间与read-query引用。引用未保存为Evidence，版本不是snapshot，查询完成时间不是上游更新时间。

“带入调查”仅填写指标/日期、打开新调查表单；用户必须手动提交。不因正常或证据不足而伪造Diagnosis。真实模型成功仍未通过（此前401，一次性授权已用完），Shopify实际API和持续更新尚未验收。

## 主线程已执行的静态与数据库测试

- `npm run test:metrics`：31/31，离线fetch fixture，严格响应/Decimal/null/身份/时期/安全错误/取消竞态，不代表真实数据或模型。
- `npm run test:tasks`：18/18；`node scripts/test-decimal-format.mjs`：10/10。
- `npm run lint`、TypeScript `--noEmit`、`npm run build`：PASS。构建产物只在被忽略的dist，没有部署。
- 后端实际PG读取与API/Runner/应用专项：31/31（其中真实数据库读取4项），复用专用fixture，无迁移/种子/调查写入。
- 前端技能mechanical detector仅执行一次，结果 `[]`。原型SHA-256仍为 `ae62216b9871c4cf2ee3651ea5e4d1c87a10d499beca2897db69dc80823fe76c`。

## 浏览器验收

主线程已实际执行独立本地API进程、生产前端build、只读同源代理和真实Edge，Synthetic sandbox与公开静态Olist validation均PASS。每个profile摘要为metricGET=4、controlled503=1、delayedReads=1、writeBlocked=0。四次实际SQL分别是初读、手动重读、延迟旧请求和无数据查询。503与响应延迟故障由验证代理控制，只是受控失败测试，不称外部平台实际失败。

界面验收包含：默认日期为空/不能查询；真实值、原始十进制/数据区间/read-query引用与API一致；安全503不显示marker、不自动重试，点击原“读取指标”按钮手动重试；带入正确指标/日期但不POST；修改日期后延迟旧查询不得覆盖；2000-01-01无数据保留不足状态/null；返回/刷新不自动查询。375px手机无横向溢出。并非已验证异常归因或真实模型。

截图在仓库外：`D:/Rag/Agent/metricsleuth-metric-ui-20261011-b6246a/`，子目录synthetic/olist各含metrics-desktop.png（1440×1000）和metrics-mobile.png（375×812）。主线程已查看Synthetic截图，独立reviewer另查看两profile。独立复核最初fix仅因PRODUCT.md仍称未接线，已修文档并复核resolved/remaining clear/disposition ship；无视觉改动，无不必要截图重复。对比范围是冻结设计/新增界面，不是完整原型像素验收；手机折叠以下内容与键盘焦点仅有源码证据。

专项脚本：`frontend/scripts/verify-metric-observation.mjs`。该工具只接受loopback API与固定验证profile，拒绝写请求，不运行Worker/模型。两套已有隔离库验收前后计数Run/Tool/Observation/Evidence/Diagnosis均为1/1/1/1/1和179/117/155/70/70，已由主线程实际SQL确认一致。成功验收的Edge/proxy已关闭，临时profile清理成功；本轮API/PG均已停止，55440/8014/8015无监听，测试数据保留。

首次脚本尝试在browser_exit处失败，未进入业务查询；Edge155在此机使用launcher退出0后relaunch模式。随后专用诊断确认DevTools端点仍存在，原脚本错误地把launcher退出等同浏览器终止。仅修验收脚本：等待实际DevTools HTTP/WebSocket句柄，finally使用CDP关闭真正浏览器，清理失败不输出PASS。之后两profile验收通过，未改变业务功能迎合测试。主线程按CIM核实仅停止首次失败与诊断的两个隔离Edge root；没有关闭日常Edge。两份早期临时profile清理遭终端策略拒绝，未换手段绕过，系统临时目录下可能残留 `metricsleuth-metric-browser-kQkQy9`、`metricsleuth-edge-diagnostic-uPhhxU`；这些不含业务数据、未进Git，进程已停止。

设计记录复核确认：新增状态色、控件、系统字体、手机单列及原生事实明细符合既有DESIGN；查询优先顺序/基线/handoff是局部策略，不升级为全局设计规则。因此普通扩展保留DESIGN.md与sidecar，没有借过时提示重新生成设计体系。

## 复现

需先按原task_application安全说明启动显式API；Synthetic验收使用metricsleuth_r4_browser_acceptance，Olist使用metricsleuth_r2_acceptance。本脚本不创建fixture，不适用于生产经营库。

```powershell
# frontend目录；output替换为本次独立的绝对证据目录
node scripts/verify-metric-observation.mjs --api http://127.0.0.1:8014 --source 3989c537-a555-4828-80e5-28b45a9624fa --profile synthetic --output D:/Rag/Agent/metric-ui-evidence/synthetic
node scripts/verify-metric-observation.mjs --api http://127.0.0.1:8015 --source bbaf0fe3-c61a-4d03-acca-4e10b69d24b7 --profile olist --output D:/Rag/Agent/metric-ui-evidence/olist
```

## 取舍与下一步

优先让既有数据/指标能力成为可操作界面，不增加调度基础设施。下一主线仍为模型鉴权与成功gate、开发店Orders实际能力验证，再做最小持续更新；Sandbox操作与服务器安全部署尚未完成。本轮技能更新命令已按用户授权执行，但工具未识别既有目录，exit1，没有重新安装；sidecar过时提示已报告，没有顺带改设计体系。
