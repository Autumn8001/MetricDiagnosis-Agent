# R5-001：隔离实验资产核对与首验边界

日期：2026-10-12；基线`039b59ae81898d7ba54a82851064c1160659c715`。状态：只读源码/内存验证完成；Sandbox写入、API及页面未实现。本轮无数据库连接、迁移、数据修改、模型请求或外部平台调用。

## 已确认的可复用资产

- `warehouse/seed.py::generate_normal_records()`固定Random(20260131)，生成2026-01-01至01-31、3 ASIN×3 marketplace×2 traffic_source，共558行。目标日01-31为18行；01-24至01-30的7天基线126行。
- `warehouse/anomaly_injector.py::generate_current_normal_records()`与seed生成的目标日18行逐字段一致。`apply_scenario(records, scenario)`是内存操作，但会原地修改输入，必须使用新生成或复制的记录。
- `warehouse/schema.sql`的两张表及`configs/metrics.yaml`可继续供现有AnalyticsTools读取；粒度仍为date×asin×marketplace×traffic_source，不引入通用行业模型。

## 不能直接用于产品写入的旧入口

| 入口 | 源码事实 | 对Lab的影响 |
| --- | --- | --- |
| seed.main / --reset | schema在autocommit连接上执行；reset无条件DELETE事实表和产品表，产品及事实还有全局upsert | 不允许连接现有Benchmark/Olist/外部业务库，不调用reset作为实验操作 |
| anomaly_injector.main | 验证目标日全局18行后，事务中按日期/分段键重写全部18行 | 数据表没有source_id隔离条件；只改日期并不能隔离实验，也会覆盖同日期已有变化 |
| get_database_url | 两脚本显式CLI优先，否则读DATABASE_URL；没有自行加载.env | 新入口必须显式受控配置、不能回退默认连接；避免误用环境变量指向的数据库 |
| CLI异常输出 | seed捕获Exception后直接输出异常文本 | 产品入口必须固定安全错误，不复用原始数据库异常输出 |

`ensure_schema(conn)`接收connection，但其DDL执行是否与DML同事务由调用者决定；旧main不能直接证明原子发布。`test_production_runtime_has_no_ground_truth_reference`只是SDK Runtime源码字样检查，不是完整信息流证明。

## 主线程实际验证（不是SQL/模型验收）

通过`python -B`在内存导入两个模块，仅调用生成器和apply_scenario，未调用get_database_url、main或psycopg.connect。两次基线生成相同；injector正常目标日与seed目标日一致。Decimal按现有sales字段计算：

| 内存场景 | 目标日sales | 前7日日均sales | 原始相对变化 |
| --- | --- | --- | --- |
| no_anomaly | 52000.0 | 52034.28571428571428571428571 | -0.0006589062156819679332308367286 |
| canonical | 45760.0 | 同上 | -0.1205798374698001317812431363 |
| traffic | 46400.0 | 同上 | -0.1082802547770700636942675159 |

这只是输入数据核对，不是Analytics SQL、Observation异常判定、Driver/Scope或真实模型结果。主线程在backend cwd执行`python -B -m unittest tests.test_development_scenarios tests.test_benchmark_cases -q`：21/21通过，exit0，属于离线测试。未重跑前一阶段数据库或浏览器验收，不重复计为本轮证据。

## 当前实施取舍与下一步验收条件

1. 首个写入切片使用新建、空的专用Sandbox验收数据库。复用内存生成函数与已有表/指标公式，不复用旧reset/main，不改既有fixture，不新建Runtime或任务调度。
2. 写入前验证显式目标、实际数据库身份、Synthetic+Sandbox绑定及空目标；非空目标或身份冲突安全拒绝。schema、维表和事实写入须在一个事务内验证失败回滚；不靠字符串source标签宣称物理隔离。
3. 数据发布后从新的只读连接，经现有MetricReadService/Analytics SQL读取正常或变化结果，并对比现有两个验收库的计数及数据未变。数据版本继续诚实标记label，未经验证不称不可变快照。
4. 实验输入/预期答案仅供实验记录和评测，不能进入Agent Prompt或工具返回；source/版本标识不得暗含Driver或Scope答案。GroundTruth不得用作生成Diagnosis的捷径。
5. 不先建大套实验仓储或队列。真实数据库验收后再决定最小产品记录/API与桌面Lab接线；并发、版本保留、重复请求和清理方案仍待实现，不能当前宣称完整实验室可用。

首验必须提供真实PG身份、写入/拒绝/回滚/重连查询及其他库未变的证据；不能只增加Mock测试。真实模型与Shopify资源gate继续优先，有资源后立即回到真实主线。
