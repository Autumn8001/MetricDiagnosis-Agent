# R1-004b：Shopify 开发店只读 Orders 探测

> 更新日期：2026-10-11；范围：接入前资源准备与安全探测，不是同步连接器。
> 实际商店 API 验收待账号/权限；离线测试不关闭真实 API gate。

## 用途与边界

先回答应用是否有订单读取权限、有限日期窗口能否完整分页，以及订单时间、测试/取消状态和金额字段是否可用。调用的是 Shopify Admin GraphQL 的固定只读 query；HTTP POST 不代表平台 mutation。

不创建订单、不写数据库、不调用模型、不发布数据版本、不输出原始订单。仅探测 `currentSubtotalPriceSet.shopMoney` 的字段合法性，不把它直接命名为销售额或 AOV。不会宣称支持 Sessions、Conversion Rate、Product 或 Traffic Source。

脚本不安装应用、不获取或刷新 token。账号与最小权限准备见 [来源决策](data-source-selection.md)。只读探测也必须获得目标店授权；显式 CLI 开关是防误触机制，不替代商店授权，也不能自动证明商店属于开发店。执行者必须人工核对专用店环境，订单的 `test` 标志也不能证明整个商店是测试环境。

## 安全限制

- 固定 HTTPS `*.myshopify.com` 店铺主机与请求 API `2026-10`；不接受自定义端点、代理、关闭 TLS 验证或重定向。若响应版本与请求不同则失败；未返回版本头时不得称版本已确认。
- 仅从进程环境 `METRICSLEUTH_SHOPIFY_ACCESS_TOKEN` 取 token；不自动读取 `.env`，不接受命令行 token。凭据不要粘贴在聊天或提交到 Git。
- 先检查当前应用的 `read_orders` 授权，再读取订单。最多1次权限请求和5页订单，每页50条；每次10秒超时、总时间预算60秒，无重试，响应体上限1MiB。
- 日期按 UTC 闭区间指定，最多31天；不是店铺本地经营日期。实际历史访问还受授权窗口限制。
- 分页超限、重复订单、游标循环、缺字段、GraphQL/HTTP错误都失败；不把不完整读取称为成功。
- 成功输出只有聚合计数、规范化日期与币种等白名单摘要；失败只输出受控 code。不得保存原始响应、ID、游标、地址、异常或 token。令牌只存在当前进程和 HTTPS 请求头；终端历史也不应包含令牌赋值原文。

## 执行前准备

以下为用户操作指南，依据2026-10-11读取的官方资料；尚未替用户创建账号、店铺、应用或凭据。页面标签可能变化，遇到不同界面先确认组织和Dev店类型，不购买生产套餐来绕过限制。

### 1. 创建专用开发店

1. 准备有应用开发/创建Dev店权限的Shopify账号，在[Dev Dashboard](https://dev.shopify.com/)选择自己的组织。
2. 打开Stores → Create store，类型选择Dev，名称可为MetricSleuth Sandbox。首轮订单读取只需核心功能，建议Basic，不为Sessions/报表提前选择额外能力或预览功能。
3. 创建后确认店铺出现在当前组织的Stores列表。保存实际`*.myshopify.com`主机名；不是自定义域名，也不是含`https://`或`/admin`的URL。另记店铺币种、时区。
4. 仅使用专用Dev店，不使用公司/客户店。开发店不能处理真实交易或转换为生产店；来源将保持`shopify / sandbox`。[官方Dev店流程与限制](https://shopify.dev/docs/apps/build/stores/development-stores)

### 2. 创建应用并安装只读权限

1. 在同一组织打开Apps → Create app → Start from Dev Dashboard，命名MetricSleuth Orders Reader。
2. 创建应用版本。首轮不是嵌入式产品，可按官方流程使用默认App URL `https://shopify.dev/apps/default-app-home`；不要求现在部署MetricSleuth公网服务。
3. Scopes只配置`read_orders`。不为测试数据创建申请`write_orders`，不申请`read_customers`、`read_reports`或`read_all_orders`。若后续字段被平台保护而拒绝，先报告实际缺口，不擅自扩大权限。
4. Release版本后选择Install app，将它安装到上一步专用Dev店并确认授权。仅在版本中填写scope不等于商店已授予它；后续scope变化需重新获店铺批准。Webhook版本字段若界面要求可填写当时支持的稳定版本，但本阶段不配置Webhook订阅。[官方创建与安装流程](https://shopify.dev/docs/apps/build/dev-dashboard/create-apps-using-dev-dashboard)

默认订单访问为最近60天，较老订单另需审批。首轮选择近期日期窗口，不为历史不足申请更多权限。[Orders权限](https://shopify.dev/docs/api/usage/access-scopes)

### 3. 准备凭据，不把Client secret误当Access token

在应用Settings的Credentials卡片取得Client ID和Client secret，保存到本机私有密码管理器或受控秘密配置。不要把Secret/Token发到聊天、截图、命令行参数、Git或前端配置；也不要为方便演示生成公开凭据文件。

本方案优先采用同一Shopify组织内的client credentials grant：店和应用必须都出现在同一组织下，仅“我是店主”或“应用已安装”不足以满足条件。它向`https://{shop}/admin/oauth/access_token`交换Token，使用grant_type=client_credentials、client_id、client_secret，Token约24小时有效。不是后台复制永久Token的旧教程；其他组织商店不能硬套此流程。[官方认证与组织限制](https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant)

**现有脚本只接收已经取得的Access token，不会交换或自动刷新Token，也不读取Client secret。** 不要将Client ID/Secret直接放进`METRICSLEUTH_SHOPIFY_ACCESS_TOKEN`。资源就绪后先通知技术负责人；获得该店一次有限Token交换及只读探测授权后，再安排安全交换和进程环境注入。该交换步骤尚未在仓库实现或实际验收，本说明不把它描述为连接器能力。

若用户自行按官方流程取得Token，只将其注入即将执行probe的同一终端进程环境`METRICSLEUTH_SHOPIFY_ACCESS_TOKEN`，不要使用包含Token字面量的历史命令。结束后移除该进程变量、关闭终端；Python子进程继承变量，另一终端或单独的系统设置未必能及时传递。Token失效时停止并重新确认授权，不无界刷新或重试。

### 4. 准备能被Orders查询到的测试数据

- 最低API gate先准备少量已完成的测试订单，例如2–5笔，使用虚构测试身份、不使用真实付款或真实客户信息。可由用户在专用Dev店用平台测试支付方式完成；项目读取应用仍只需要read_orders。
- 若选择生成demo data，先检查Orders和Draft orders。官方说明生成的订单案例可能是草稿；草稿不等于本脚本查询的Orders。用户可在专用店后台将适当草稿标记已付款成为订单，脚本不会执行draftOrderComplete或其他mutation。[生成数据说明](https://shopify.dev/docs/apps/build/stores/generated-test-data)
- 记录少量订单的日期、币种、测试/取消/付款状态和预期数量，只需脱敏汇总，不发送姓名、地址、订单原文或ID。测试订单test标志与Dev店身份分别核对，不能由一个推断另一个。
- 第一次API字段/权限gate不要求8天都有订单，新店可以先选有订单的当天。后续单日对前7天指标验收需要实际日期覆盖；没有历史时等待真实积累或核实平台已有样本，不把今天创建的数据伪装成过去7天经营数据。
- 后续两次更新验收由用户在专用店执行一项已确认的变化，再授权第二次读取；当前probe不保存版本或同步状态，不能只运行两次就宣布持续更新已交付。

### 5. 向技术负责人反馈什么

只需说明：专用Dev店已创建、店与应用同一组织、read_orders版本已发布并安装、凭据已私下保存、实际订单数量/日期窗口、币种与时区。主机名可在获授权的本机配置中提供；聊天无需秘密或完整订单。随后明确批准该店有限只读探测；若需要client credentials交换，授权应同时涵盖这一步。提供这些资源不等于授权写订单、持续抓取、生产操作或付费模型调查。

## 授权后的探测命令（当前尚未执行）

在安全的本地进程环境注入凭据后，从 `backend` 运行以下命令。店铺占位符必须替换为自己的获授权开发店，日期也必须根据实际测试数据选择；示例不包含凭据。

```powershell
python -B scripts/probe_shopify_orders.py --allow-sandbox-read --shop your-dev-store.myshopify.com --start-date 2026-10-11 --end-date 2026-10-11
```

当前未执行这条外部请求命令。没有权限时不要为了运行示例而使用公司/客户商店或申请写权限。

预定请求上限仍为1次权限请求及最多5页Orders，无重试。额外Token交换是认证步骤，不计入这6次GraphQL上限，执行前单独明确其次数；本轮没有执行任何交换。

## 如何解释结果

完整分页只说明本次查询返回链路已读完，不保证上游在多页读取期间静止。输出不得声称跨页快照一致。每日存在样本也不证明当天经营数据完整；没有样本可能是真实零订单，也可能是历史/权限不足，需要人工核对。

即使脚本在开发店成功，也只是 `shopify / sandbox` 的真实平台 API 证据，不是生产经营数据、持续同步、SQL指标或 Agent 诊断验收。连续更新需要至少两次授权读取、数据变化对比及后续不可变版本发布。

## 验证与通过条件

离线守卫验证（不会访问 Shopify）：

```powershell
python -B -m unittest tests.test_shopify_orders_probe -v
```

真实 API gate 仍待执行：记录实际授权、请求页数、完整性、时间/币种覆盖和固定错误分类；人工核对测试订单计数与状态。记录中不包含店铺秘密、订单原文或用户信息。没有实际调用证据时，Roadmap 保持“准备完成，真实验收待开展”。

成功摘要中`api_verified/complete=true`只证明这次请求与分页通过；版本头缺失时`version_confirmed=false`不能关版本确认gate。空店可以完整返回0笔，但`sample_days_covered=0`，不能证明订单字段/金额/状态映射。人工预期样本与实际摘要匹配、API版本确认且无脱敏违规后才关闭首轮能力gate；8天指标、持续发布和Agent另行验收。401/403、缺read_orders、页数预算或字段保护失败时先记录受控错误，不重试或扩大权限。

本次文档准备的主线程离线复验：`tests.test_shopify_orders_probe`18/18 PASS，MockTransport/patch；没有Shopify或模型调用，没有数据库操作。官方流程未在用户账号实际演练，账号界面与权限仍需用户确认。

官方接口依据：[当前应用权限](https://shopify.dev/docs/api/admin-graphql/latest/queries/currentAppInstallation)、[订单查询](https://shopify.dev/docs/api/admin-graphql/latest/queries/orders)、[订单字段](https://shopify.dev/docs/api/admin-graphql/latest/objects/Order)、[搜索语法](https://shopify.dev/docs/api/usage/search-syntax)。日期值按官方要求加引号。实际字段授权与 API 行为仍以本店只读探测为准。
