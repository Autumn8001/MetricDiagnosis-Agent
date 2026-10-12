# R4-007：手动指标扫描桌面页面验收

日期：2026-10-12。基线：`86fc8692f16498c5abb10049234d6ef09d491d3a`加本次页面/验收脚本。状态：功能验收通过；独立桌面视觉复核`ship`，无material_fixes。

## 实际能力与边界

`MetricScanPanel.tsx`在既有业务指标页增加显式日期与扫描按钮，复用`createMetricClient.scan()`及已验收的只读接口。只在用户点击时GET；保留单指标查询。页面核对来源目录provider/environment/version及完整支持指标集合，显示每项数值、异常候选与不确定状态，原生details保留原值、区间、来源、UTC查询时间及查询引用。handoff仅填写调查表单，不自动POST或调用模型。

日期变化/卸载使用epoch与Abort，来源身份/版本/能力改变触发key清理；查询失败清旧结果，只能用户手动重读。没有候选不等于全体正常。版本仍为label、扫描不持久化、各指标独立只读事务而非一致性快照；时间不是上游更新时间。不是趋势图、持续更新、Evidence持久化或Diagnosis验收。

本轮没有修改后端、Runtime、数据库迁移、依赖、线上配置或原型。HTML SHA256仍为`ae62216b9871c4cf2ee3651ea5e4d1c87a10d499beca2897db69dc80823fe76c`。用户随后明确MVP仅桌面浏览器Web，手机专项暂不开展；保留已有响应式样式，早于该决定产生的附带手机截图不是后续验收要求。

## 主线程实际验证

- 显式隔离PG17.11，127.0.0.1:55440，原有Synthetic库`metricsleuth_r4_browser_acceptance`与Olist库`metricsleuth_r2_acceptance`；无迁移、注入或Worker。独立API分别8001/8002，只启用显式任务应用、model标识`unused-no-model`，未读取.env或使用模型凭据。
- Synthetic/sandbox：2026-10-10，5项正常，sales100.00/100.00；Olist/validation：2017-03-20，3项不确定，GMV16861.09/13355.61，无sessions。Olist是公开静态数据，Synthetic是模拟fixture，都不是持续外部经营数据。
- 实际Edge、production build及仅GET本机代理：两profile分别PASS。各7次成功scan GET批次（不是SQL语句或Agent工具次数）、1受控503、1受控版本冲突、2延迟响应、1受控来源目录切换，写请求0。检查完整字段/原值/状态与API一致、缺数null非0、safe error清结果/显式retry、延迟日期与来源切换不显示过期结果、handoff不POST、返回及刷新不自动扫描。首次失败检查额外读取1次Synthetic批次，不隐含在最终7次统计内。
- 受控版本冲突只修改已克隆的响应，原SQL事实不被改写；受控第二来源只存在于代理目录，history由代理返回受控空列表，未连接另一业务库或增加真实source。它们验证UI守卫，不当成真实多源接入。
- 原生details真实键盘Enter展开通过。默认单指标read模式亦实际浏览器PASS：Synthetic4次真实读取、1受控503、1延迟、0写请求，保留原有交互。
- 主线程最终客户端58/58、任务客户端18/18、lint/tsc noEmit/build全exit0；node --check与git diff --check通过。实际PG只读专项`tests.test_postgres_metric_read_api`7/7，无跳过。本轮未重跑后端全量668项，不借历史全量替代本次验收。

## 失败与收尾

第一次Synthetic浏览器验收在`browser_scan_keyboard_toggle`失败；CDP只有keyDown/keyUp，未发送Enter字符事件。补齐char事件后真实原生details展开通过，再跑完整Synthetic与Olist验收；未修改产品元素或伪造open状态以绕过键盘检查。脚本的缺数据断言、无自动查询比较及加载时切源覆盖也在主审中按真实合同纠正，而非降低产品语义。

前后独立SQL核对Run/ToolCall/Observation/Evidence/Diagnosis计数一致：Synthetic1/1/1/1/1，Olist179/117/155/70/70。没有新调查、Evidence或Diagnosis。测试API按准确进程身份停止，隔离PG按准确data目录停止；8001/8002/55440监听为0，数据库和日志保留。Browser.close及临时profile清理由脚本验证，成功exit0才计PASS。

截图：仓库外`D:/Rag/Agent/metricsleuth-scan-ui-20261012/`，synthetic/olist的scan-desktop.png（1440×1000）；read-regression/metrics-desktop.png为单指标回归。独立fresh reviewer只审桌面，按冻结HTML/既有桌面参考/现有DESIGN判定`ship`。设计记录只读复核一致，不重写DESIGN或sidecar，不新增视觉世界。早先附带手机截图保持历史文件，不安排追加工作。

## 复现入口

先按`task-application-acceptance-2026-10-10.md`配置并显式启动上述隔离库两个只读API；不指向生产、不运行worker、不读默认.env。backend执行专用PG读取测试时需按`source-metric-scan-acceptance-2026-10-11.md`配置两个受守卫的测试变量；未配置时跳过不是通过。

frontend cwd，在已有build与准确API配置下，原验收脚本可复现如下（脚本保留历史附带响应式检查；当前产品验收目标仅桌面）：

```powershell
npm run test:metrics
npm run test:tasks
npm run lint
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json
npm run build
node scripts/verify-metric-observation.mjs --mode scan --api http://127.0.0.1:8001 --source 3989c537-a555-4828-80e5-28b45a9624fa --profile synthetic --output D:/Rag/Agent/scan-evidence/synthetic
node scripts/verify-metric-observation.mjs --mode scan --api http://127.0.0.1:8002 --source bbaf0fe3-c61a-4d03-acca-4e10b69d24b7 --profile olist --output D:/Rag/Agent/scan-evidence/olist
```

MVP仍未完成：真实模型成功调查gate、Shopify实际Orders/持续更新、可执行隔离Lab、重复真实评测与安全部署仍是主线缺口。既有401后未新增授权调用，本次没有模型或Shopify请求。
