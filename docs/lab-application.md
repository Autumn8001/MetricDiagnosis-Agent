# 本地 Lab 入口（R5-004 临时 PostgreSQL 验收通过）

仅监听loopback的开发入口，尚非生产方案。先在独立应用状态库人工按顺序应用backend/migrations/001至005，入口不会自动迁移。每个实验需要全新的专用空PostgreSQL库，名称以metricsleuth_sandbox_开头；连接地址为明确loopback，目标与状态库分离。每目标只能发布一次，最多20个；不得覆盖或重置已用空间，新增空间由维护者显式准备。当前数据日期固定2026-01-31，来自既有生成资产。

METRICSLEUTH_LAB_TARGETS_FILE指定本项目私有JSON文件路径，权限0600、最大32KB。数组每项只能含source_id（唯一UUID）、display_name、database_url。连接串自行填写，不提交Git；目标只允许Synthetic/Sandbox，客户端不能指定数据库。另设METRICSLEUTH_STATE_DATABASE_URL、METRICSLEUTH_TASK_MODEL。Worker还需要本项目专用OPENAI_API_KEY和既有Runtime端点配置；模型ID以实际API为准。不使用其他项目凭据，不把秘密写进命令历史/日志。

在隔离Python环境及backend目录运行：

```bash
python -m app.lab_application api --port <空闲本地端口>
python -m app.lab_application worker --once
```

API：GET /api/lab/catalog，POST及GET /api/lab/experiments，GET /api/lab/experiments/{id}，POST /api/lab/experiments/{id}/investigations。发布正文source_id/scenario_id/idempotency_key；相同键和正文复用记录，不同正文409。调查正文target_metric，页面首版使用sales；同一实验关联稳定ID任务。来源、指标和证据仍由既有investigation-sources、investigations、metrics/scan接口查询。失败只显示固定安全码，启动恢复不重写数据或重放模型。旧入口未配置Lab时返回明确503。

离线回归：python -B -m unittest discover -s tests -p 'test_*.py'。真实PG专项：python -B scripts/verify_lab_application.py --postgres-bin <专用PG二进制目录>，该脚本仅创建自己拥有的临时集群，运行需许可。浏览器脚本frontend/scripts/verify-lab-workspace.mjs需显式指定METRICSLEUTH_BROWSER_TOOLS和METRICSLEUTH_CHROMIUM_PACK，使用受控HTTP响应，不连接数据库或模型。前端保持既有同源/代理设置，npm run lint、npm run test:lab、npm run build。

已证明：005迁移、临时PostgreSQL完整链路、受控Runner下的发布/恢复/调查持久化。尚未证明：真实模型成功、持续外部接入、生产鉴权/部署。本轮没有创建常驻服务或执行生产操作。
