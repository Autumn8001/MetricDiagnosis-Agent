# R5-004 Lab 接线验证记录

日期2026-10-13；基线R5-003 77f25d8b246fbf5098895a210f9483bd34762145；分支work/r5-004-witt。实现可审查，真实数据库gate待执行。

已实施：独立实验表/仓储、幂等预留、受保护单次发布、状态/分页历史、manifest身份/版本/场景校验、来源会话锁及恢复、稳定调查ID和关联修复；复用原Runtime/Worker/指标服务。React Lab替换占位页，空来源也可进入，支持发布/历史/轮询/指标/关联调查打开，错误只显示安全文案，显式重试保持幂等键，无自动发布或调查重试。

实际离线全量输出Ran690 tests in13.708s、OK(skipped=5)。Lab客户端7项通过，既有tasks/metrics/decimal脚本通过；lint/类型/Vite构建通过。跳过项未算作PG或模型通过。

实际浏览器1440×1000，隔离Chromium与随机loopback HTTP端口：空目录进入Lab、一次发布POST、响应52000展示、来源/日期带入调查、刷新原关联、安全503错误、无水平溢出，通过。全部响应为明确受控HTTP fixture；关联调查是失败且无证据/诊断的记录，未编造模型结论。real_database=false、real_model=false。

首次sandbox无法监听；获得仅HTTP验证许可后执行。调查测试曾因闭合disclosure可见性及summary选择器不唯一失败，修正测试定位后完整通过，未修改跳转数据逻辑。视觉context/detector权限拒绝未执行；不宣称检测器通过。独立复核指出Lab局部对比不足和产品状态旧描述；已加深错误正文/成功状态并更新PRODUCT三处，重新构建、完整HTTP流程及同尺寸截图通过。独立reviewer逐项判定两项resolved、disposition ship，结论仅限修复清单，不扩展成PG/模型通过。

独立documenter核对DESIGN.md、sidecar、PRODUCT、CSS、组件和三张桌面截图：普通扩展兼容既有配色、系统字体、238px导航、组件及事实边界，无需修改系统文件。历史设计记录中的手机验证措辞保留，未按本轮桌面边界重写历史。使用impeccable技能的fresh reviewer/documenter流程，其余开发独立完成。

真实PG脚本verify_lab_application.py已准备，拟覆盖005迁移、发布/重读、幂等冲突、正常及受控失败任务、锁/恢复和断链修复。执行请求被拒绝，未运行；不能声称真实完整链路通过。既有R2/R4库未访问，指纹未复验。

模型请求0、Shopify请求0；无其他项目凭据、推送、部署、全局安装或既有服务重启。每实验消耗一个预配置空目标，不支持覆盖或无限创建。配置与复现见../lab-application.md。
