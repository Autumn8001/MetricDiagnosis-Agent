# R5-003 Sandbox manifest 来源绑定验收

日期：2026-10-13。基线：b9186b4253c0c31962d82c3e5d4c796c1535b850。状态：Verified / Pending User Review。

## 产品变化

显式设置 `METRICSLEUTH_TASK_PROFILE=sandbox_manifest` 后，应用只读已有发布manifest，核对物理库和服务器配置来源，再将发布版本绑定到现有任务、Worker与指标服务。`METRICSLEUTH_TASK_DATA_VERSION` 可省略以读取标签，或设置以固定预期版本；source_id与model仍必需。默认synthetic/olist_validation行为不变，不自动迁移或发布。

数据库字段由现有 R5-002 writer 提供；Reader不读取Ground Truth、不返回场景答案、不运行模型。版本是发布标签，指标API的 `snapshot_consistent=false` 保持不变。

## 实际 PostgreSQL / API 验证

ARM64 主机使用 PostgreSQL 16.4 测试二进制，在 /tmp 内建立全新私有集群，选择空闲 loopback TCP 端口，不使用系统服务或已有集群。

二进制来自 [Zonky 测试二进制项目](https://github.com/zonkyio/embedded-postgres-binaries)，Maven artifact `io.zonky.test.postgres:embedded-postgres-binaries-linux-arm64v8:16.4.0`，下载JAR的SHA256：`5a281952dd35191be97809ce657d6cb1a7b42a8d8ca6195125dd368d47eb8c42`。不加入项目依赖，不随交付包分发。

运行：

```bash
cd backend
python -B scripts/verify_sandbox_manifest.py --postgres-bin /path/to/postgres/bin
```

脚本只操作自己新建临时集群；无生产连接、全局安装或系统配置修改。集群正常结束后停止，临时目录回收。

实际结果：

- `publish_sandbox_dataset` 生成Canonical Synthetic 558行及唯一manifest；新连接读取与初始Publication完整一致。
- 不存在版本、错误source_id、空库缺少manifest、连接工厂连接错误物理数据库全部fail-closed。
- 两个全新应用实例从manifest构造同一TaskSourceBinding，来源目录返回真实发布版本。
- 现有 `/api/metrics/scan` 查询实际PostgreSQL行，Sales为`45760.00`、候选true，来源Synthetic/Sandbox、版本为发布标签、snapshot_consistent=false。
- 两个**本脚本新建**控制数据库指纹不变；发布库仍558行、manifest仍1行。
- 测试集群已停止；模型请求0，外部业务数据访问0。

严格证据边界：本机未提供可访问的既有R2/R4测试库；本轮未访问它们，也未复验其历史指纹。新建控制库不冒充既有R2/R4验收证据。数据为真实PostgreSQL中的Synthetic行，不是Shopify或实时外部业务数据。

## 离线验证

新增8项manifest/配置合同测试通过，覆盖只读事务、关闭连接、错误身份/版本/元数据、异常脱敏、来源绑定、只解析一次及显式启动规则。真实网络验收独立于默认单测；默认不会启动数据库或请求模型。

隔离环境全量回归 `Ran 683 / OK (skipped=5)`：678项运行通过，原5个PostgreSQL测试类因未配置继续跳过；跳过不能解释为真实数据库通过。新增独立PG脚本已单独实际执行并通过。

## 剩余范围

R5-004实验记录/历史/API/Lab页面已在后续提交实现并通过独立临时PostgreSQL gate；本记录仍只描述R5-003。当前仍不提供旧发布版本快照、自动清理、外部同步或模型成功验收。
