# R5-002 隔离Sandbox首次发布：真实PostgreSQL验收

日期：2026-10-12。基线：`ccaa5e464d514ba2240e3fdd2339ce5143418cfa`，本记录随独立后续提交保存。本次是Python发布与真实SQL指标读取，不是模型Diagnosis、持续外部来源或Lab页面验收。

## 实现与边界

- `backend/app/sandbox/dataset_writer.py`：`SandboxTarget`、`publish_sandbox_dataset()`、`build_sandbox_rows()`。显式loopback专用库、UUID Synthetic/Sandbox、实际连接身份、非空拒绝、单事务DDL/DML、有限超时和advisory锁；不回退.env，不调用seed/reset/main，不覆盖数据。
- 复用`warehouse/seed.py`、`warehouse/anomaly_injector.py`内存函数与`warehouse/schema.sql`；正常/canonical/traffic生成558行，仅替换18目标日分段。实际PG本轮仅发布正常和canonical，traffic仅离线验证。
- manifest保存输入场景与中性发布元数据；Publication不含场景或预期Driver/Scope。checksum是生成输入摘要，data_version是标签，不是不可变数据库快照。应用自动绑定manifest、实验记录、Lab API/UI、生命周期/生产权限与实际并发验收均未实现。
- 测试复用现有MetricReadService与TestClient scan路由；实际数据库查询，但不是独立HTTP服务器或浏览器测试，没有Worker、模型、Shopify或生产连接。

## 本机实际结果

PostgreSQL17.11，127.0.0.1:55440，显式隔离角色metricsleuth_test；新建三个空库，无删除或重置。

| 保存的数据库 | 发布来源UUID | 结果 |
| --- | --- | --- |
| metricsleuth_sandbox_r5002_249fac13_normal | 07800e50-cb44-4a97-a8b6-ca9e9333c1fc | 3商品、558分段、1manifest，正常 |
| metricsleuth_sandbox_r5002_249fac13_canonical | 46e0d21e-6b78-419f-8493-0755d7d84fa0 | 3商品、558分段、1manifest，受控下降 |
| metricsleuth_sandbox_r5002_249fac13_rollback | 不发布 | CHECK失败后warehouse schema不存在 |

正常版本：`sandbox-fe1bc8e600fa47231f66a5e664a5d86b0c5996e25ccd9ef9b5119a35d9fc07ab`。
变化版本：`sandbox-8d3c2b1524b71d2dcdf6fd1427a50646ba194e054b0fc1dca7f50e8fda63cc08`。

目标2026-01-31；两库前7日基线126行、sales合计364240.00，日均52034.28571428571428571428571。正常sales52000.00、orders650；变化sales45760.00、orders572。变化候选为sales/orders/conversion_rate，sessions与AOV正常；正常候选为空。两次新应用/连接回读均通过，扫描persisted=false、snapshot_consistent=false，查询引用不是保存的调查证据。

## 主线程测试证据

- `test_sandbox_dataset_writer.py`：7项Fake/内存测试。
- `test_postgres_sandbox_dataset.py`：4项真实PG测试，验证发布与重连读取、非空拒绝且数据不变、实际误连旧库拒绝、负sales触发真实psycopg CheckViolation并回滚DDL/DML；对外仅sandbox_publish_failed。
- 合并专项命令：`python -B -m unittest discover -s tests -p 'test_*sandbox*.py' -v`，配置本节三个新空库后11/11 PASS，无跳过。
- 全量：`python -B -m unittest discover -s tests -p 'test_*.py' -q`，未配置专项DB变量，Ran675 / OK(skipped=5)。跳过不算真实数据库通过；输出中的Hermetic评分也不算模型验证。仍见既有SQL解析fallback与事件循环ResourceWarning，本轮没有修复或隐瞒。
- 每项真实测试前后核对旧库状态计数与业务表指纹；主线程随后新连接复读确认一致：R4旧库1/1/1/1/1、Synthetic8行指纹`a71ef7f8ba0dbcbdd44e452f29e088a2`；R2旧库179/117/155/70/70、Synthetic360行`d842cdb80f29b3ffa3b3dbe4dc52a71c`、Olist96478行`4d8bbd4fbf0720edc997c78297eeedb9`。仅输出聚合/hash，不输出个人记录。

首次专项失败已保留事实：`inet_server_addr()::text`实际返回127.0.0.1/32，Python IP守卫拒绝，发布尚未DDL；主线程查询确认后改用`host(inet_server_addr())`，未放宽身份守卫，再运行上述11项通过。同时加强库名字符规则和生成失败安全错误。

## 复现要求与安全停机

在backend目录运行专项前，需要受控启动上述本机隔离PG，并另外准备三个**全新空库**，分别匹配`metricsleuth_sandbox_r5002_<新唯一后缀>_normal/canonical/rollback`；配置`METRICSLEUTH_SANDBOX_TEST_URLS`为JSON对象，键normal/canonical/rollback，值为显式`postgresql://metricsleuth_test@127.0.0.1:55440/<对应新库名>`。测试还依赖既有R2/R4受保护fixture用于只读对照；不会创建或删除数据库。

不得对本次保存的normal/canonical库重跑首次发布类：它们已非空，设计上会拒绝。不要为重跑执行reset、DROP或TRUNCATE。没有显式变量时专项类跳过；仅需离线复验可运行`python -B -m unittest discover -s tests -p 'test_sandbox_dataset_writer.py' -v`。

收尾已执行pg_ctl fast stop，精确目标`D:/Rag/Agent/metricsleuth-test-pg-61dc9486/data-worker-fresh`；status显示no server running，55440监听数0。三个数据库及仓库外日志`sandbox-r5002-20261012.log`保留，未删除数据，未推送或部署。用户要求提交后暂停持续推进，等待查看成果。
