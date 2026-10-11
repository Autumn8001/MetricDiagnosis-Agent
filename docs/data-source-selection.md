# R1-004a：持续来源选择与 Shopify 验证边界

> 日期：2026-10-10；源码基线 `eef65bd75ddeaf453524cfd5956c51e8308a7945`。
> 结论：资料/源码比较已完成；外部 API、账号权限和连接器尚未验收。此文不宣称持续真实数据接入完成。

## 1. 已确认选择

用户目前没有可提供的业务 PostgreSQL，可准备 Shopify 开发店。因此**下一个外部接入验证对象为 Shopify 开发店**，来源身份为 `shopify / sandbox`，不是 `live`。官方明确开发店只用于开发测试，不能处理真实交易；真实平台 API、可持续变化的测试订单与真实生产经营数据是三个不同概念。[开发店限制](https://shopify.dev/docs/apps/build/stores/development-stores)

先验证订单域的最小闭环，不要求一次实现原型中的全部指标。不购买付费套餐、不创建/授权账号、不生成订单、不安装 Shopify CLI 或新 SDK，除非后续具体任务获得所需权限。现有 OpenAI Agents SDK 内核保持不变。

若后续获得合法持续业务数据库或实际商店授权，再做 `live` 来源验收；不能通过改环境标签把测试数据变成真实经营数据。稳定的 PRODUCT MVP 验收标准未降低。

## 2. 仓库当前约束（Current）

| 资产/边界 | 源码证据 | 对接入的影响 |
| --- | --- | --- |
| 来源身份与能力 | `backend/app/data_sources/capabilities.py` | 有 PostgreSQL/Shopify enum，不等于有连接器；按指标独立 grain/维度校验。 |
| 语义与 SQL | `backend/app/metrics/registry.py`、`backend/app/analytics/tools.py::query_metric` | Registry单一source.table；受控聚合SQL，只支持单日与前7天比较；没有跨粒度任意join。 |
| 显式本地入口 | `backend/app/task_application.py::TaskApplicationConfig` / `build_task_application` | 仅Synthetic/Olist Profile、loopback数据库；不是远程业务库或Shopify产品接入入口。不得直接解除保护冒充已接入。 |
| 来源Runner | `backend/app/persistence/source_runner.py` | 每次分析查询独立只读短事务；data_version仅标签，不能保证调查期间多次读取一致。 |
| 既有合同 | `configs/metrics.yaml`、`configs/olist_validation_metrics.yaml` | Synthetic sales是USD gross且不扣退款；Olist是delivered商品GMV/订单，不自动适用于Shopify销售。 |
| 实际验收 | `evaluation-artifacts/postgres-browser-history-acceptance-2026-10-10.md` | Olist静态SQL/保存/浏览器读取已证实；不是外部同步或模型成功。 |

## 3. 两种方案比较与成本取舍

| 项目 | 获授权的业务 PostgreSQL 只读视图 | Shopify 开发店 |
| --- | --- | --- |
| 当前资源 | 用户未提供 | 用户可准备，尚未提供可用店/应用权限 |
| 复用程度 | psycopg、固定聚合视图与语义层复用较多 | 需订单API读取、分页、状态/币种映射及内部发布过程 |
| 持续更新 | 取决于真实上游业务与视图契约 | 可从真实平台读取更新，但订单是测试店数据 |
| 指标完整性 | 必须逐视图核实，不能假设有sessions | 订单域可先验证；访问/转化需不同接口和权限 |
| 运维风险 | 网络/TLS、最小权限、SQL耗时和上游一致性 | 账号权限、API版本/成本限流、字段访问、分页与时间覆盖 |
| 成本判断 | 已有授权视图时实现成本较低；现在无可用资源 | 新增适配工作，但当前更有资源可行性；不承诺套餐费或免费analytics能力 |

这是依据当前源码和资源条件的工程判断，不是两个连接器的性能/费用实测。现在只实现一个最小平台路径，不并行建设两套连接器或通用映射平台。

## 4. Shopify 指标能力 gate

官方订单访问默认窗口是最近60天，较老订单需额外 `read_all_orders` 审批；只读接入不申请 `write_orders`。日期覆盖必须由实际返回与完整分页验证，而非根据店龄猜测。[访问权限](https://shopify.dev/docs/api/usage/access-scopes)

| 指标/维度 | 第一切片处理 | 必须验证的证据 |
| --- | --- | --- |
| Orders | 候选支持，未验收 | 稳定订单ID、完整分页、test/cancel/payment状态的明确纳入规则；计数为去重订单而非line item数。 |
| Sales / AOV | 不沿用Synthetic销售公式 | 先明确业务金额口径、币种、折扣、运费、税、退款和取消；AOV分子/分母必须为相同订单集合。验证后使用明确命名，不称已匹配Shopify报表净销售。 |
| Country | 可选，未验收 | 收货国家、店铺市场、会话国家不同；字段权限/空值和业务定义确认后才声明维度。首轮可仅总量，不申请完整地址PII。 |
| Product | 后续订单明细切片 | line item分页、跨商品订单不重复累计总订单；不得把订单级总金额复制到每件商品。 |
| Traffic Source | 第一切片不可用 | 订单来源平台字段不等于会话获客来源；需单独验证归因覆盖和窗口。 |
| Sessions / Conversion Rate | 默认不可用，禁止补造 | 需sessions数据集权限、同粒度分子分母与事件采集证据。商品销售额/全店sessions不是商品转化率。 |

官方 ShopifyQL 已有 `sessions` 数据集及referrer/地理维度，因此不能笼统断言平台无流量API。其转化率是完成checkout的sessions占sessions比例，不可直接替换为本项目Synthetic的orders/sessions。[sessions语义](https://shopify.dev/docs/api/shopifyql/latest/schemas/sessions_and_behavior/sessions)

`shopifyqlQuery` 文档列出 `read_reports`、Level 2 protected customer data和API版本条件；是否在实际店铺/应用可用必须spike，不因文档存在就宣布已支持。首轮不为漏斗调查申请不必要的PII权限。[ShopifyQL权限](https://shopify.dev/docs/apps/build/shopifyql/graphql-admin-api)

## 5. 最小实现方向（Proposed，尚未写代码）

```text
Shopify orders只读查询 / 获授权的固定PG视图
  → 完整读取与数据质量检查
  → 内部隔离的不可变发布版本
  → 明确grain/口径的MetricRegistry + capabilities
  → 已有AnalyticsTools / SDK / checkpoint /任务API
  → 已有React调查工作区
```

先做一次明确预算的只读API probe，核实 granted scopes、订单分页、字段可用性、时间覆盖与错误脱敏。不要直接让Agent访问平台任意API或自动创建订单。Orders支持更新时间过滤，后续同步必须处理更新而非只追加；查询成本/限流由平台返回，不能使用无界重试。[Orders读取](https://shopify.dev/docs/api/admin-graphql/latest/queries/orders)、[API limits](https://shopify.dev/docs/api/usage/limits)

低量第一版建议完整重读明确的有限日期窗口，检查所有页后原子发布；窗口外数据不宣称覆盖。取消、退款、修订和权限变化需要重读对账，失败不更新“最近成功刷新”或发布半成品。后续才考虑增量游标、重叠窗口/去重与删除对账，不先做通用ETL调度。

调查绑定已发布版本，后续刷新不能修改该版本；复用现有短事务而非在LLM思考时保持外部数据库长事务。需要最小发布清单（来源/环境、版本、覆盖区间、币种/时区、完整性、读取时间）和真实版本路由，不能仅新增一个标签。当前AnalyticsTools没有server-owned source/version行谓词；实现时必须固定可信的版本数据集或明确增加服务端约束，不把source_id标签当物理隔离。

PG候选若启用：限定获授权视图和SELECT权限，不能让Agent自由探索公司数据库；敏感网络连接验证证书/主机名。Repeatable Read仅保证一个事务内读取一致，不跨现有独立查询自动提供快照；应短时抽取后发布。[GRANT](https://www.postgresql.org/docs/current/sql-grant.html)、[TLS](https://www.postgresql.org/docs/current/libpq-ssl.html)、[事务隔离](https://www.postgresql.org/docs/current/transaction-iso.html)

## 6. 用户资源与验收顺序

需要用户准备（无需在聊天中发送秘密）：

1. Shopify开发账号及**专用开发店**，明确允许MetricSleuth读取；不是公司/客户未经授权的商店。
2. 安装到该店的应用和最小只读 `read_orders` 权限；实际token获取/有效期以该应用类型官方认证流程为准，不假定永久token。仅在本机被忽略的安全配置提供凭据。
3. 首轮权限/字段gate准备少量实际测试订单，说明日期、币种、时区、订单状态和是否包含取消/退款；后续单日对前7天指标验收才需要相应历史覆盖。新店没有8天历史不阻塞首轮API探测，也不能补造历史。用户创建测试数据，Agent不得自行执行平台mutation。
4. 一个获授权的平台数据变化案例，用于两次刷新对比；若历史不足，先报告覆盖不足，不伪造成功调查。

R1-004b（离线准备完成，实际调用待开展）：安全probe已实现并离线验证。通过条件仍为权限/完整分页/时间/字段实证、稳定失败分类、无原始响应/PII落日志；没有凭据时仅离线守卫测试不能过真实API gate。账号、Dev店、同组织应用/read_orders安装及24小时Token准备步骤见[只读探测操作指南](shopify-orders-probe.md)，2026-10-11按官方资料更新；现有脚本不会交换/刷新Token。

R3最小纵向切片（依赖probe）：抓取→完整版本发布→真实SQL指标→已保存任务结果→页面展示；受控Runner先证明同步/事务，再在新授权下验证真实模型。至少两次真实平台读取且版本和数据变化可追溯，才称持续外部测试店链路；实际经营数据验收仍需live授权来源。

本轮没有外部API请求、账号操作、安装、迁移、模型运行或业务代码修改。官网公开资料访问与实际商店API验收分开记录。
