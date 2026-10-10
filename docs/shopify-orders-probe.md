# R1-004b：Shopify 开发店只读 Orders 探测

> 日期：2026-10-10；范围：接入前安全探测，不是同步连接器。
> 实际商店 API 验收待账号/权限；离线测试不关闭真实 API gate。

## 用途与边界

先回答应用是否有订单读取权限、有限日期窗口能否完整分页，以及订单时间、测试/取消状态和金额字段是否可用。调用的是 Shopify Admin GraphQL 的固定只读 query；HTTP POST 不代表平台 mutation。

不创建订单、不写数据库、不调用模型、不发布数据版本、不输出原始订单。仅探测 `currentSubtotalPriceSet.shopMoney` 的字段合法性，不把它直接命名为销售额或 AOV。不会宣称支持 Sessions、Conversion Rate、Product 或 Traffic Source。

脚本不安装应用、不获取或刷新 token。账号与最小权限准备见 [来源决策](data-source-selection.md)。只读探测也必须获得目标店授权；显式 CLI 开关是防误触机制，不替代商店授权，也不能自动证明商店属于开发店。执行者必须人工核对专用店环境，订单的 `test` 标志也不能证明整个商店是测试环境。

## 安全限制

- 固定 HTTPS `*.myshopify.com` 店铺主机与请求 API `2026-10`；不接受自定义端点、代理、关闭 TLS 验证或重定向。若响应版本与请求不同则失败；未返回版本头时不得称版本已确认。
- 仅从进程环境 `METRICSLEUTH_SHOPIFY_ACCESS_TOKEN` 取 token；不自动读取 `.env`，不接受命令行 token。凭据不要粘贴在聊天或提交到 Git。
- 先检查当前应用的 `read_orders` 授权，再读取订单。最多1次权限请求和5页订单，每页50条；每次10秒超时，无重试，响应体上限1MiB。
- 日期按 UTC 闭区间指定，最多31天；不是店铺本地经营日期。实际历史访问还受授权窗口限制。
- 分页超限、重复订单、游标循环、缺字段、GraphQL/HTTP错误都失败；不把不完整读取称为成功。
- 成功输出只有聚合计数、规范化日期与币种等白名单摘要；失败只输出受控 code。不得保存原始响应、ID、游标、地址、异常或 token。令牌只存在当前进程和 HTTPS 请求头；终端历史也不应包含令牌赋值原文。

## 执行前准备

用户准备专用开发店及安装应用的只读授权。目标窗口最好覆盖目标日及前7天；不足时只能验收 API 字段，不能验收8天指标比较。创建/调整测试订单由用户在授权范围内完成，脚本不会执行此操作。

在安全的本地进程环境注入凭据后，从 `backend` 运行以下命令。店铺占位符必须替换为自己的获授权开发店，日期也必须根据实际测试数据选择；示例不包含凭据。

```powershell
python -B scripts/probe_shopify_orders.py --allow-sandbox-read --shop YOUR-DEV-STORE.myshopify.com --start-date 2026-10-01 --end-date 2026-10-08
```

当前未执行这条外部请求命令。没有权限时不要为了运行示例而使用公司/客户商店或申请写权限。

## 如何解释结果

完整分页只说明本次查询返回链路已读完，不保证上游在多页读取期间静止。输出不得声称跨页快照一致。每日存在样本也不证明当天经营数据完整；没有样本可能是真实零订单，也可能是历史/权限不足，需要人工核对。

即使脚本在开发店成功，也只是 `shopify / sandbox` 的真实平台 API 证据，不是生产经营数据、持续同步、SQL指标或 Agent 诊断验收。连续更新需要至少两次授权读取、数据变化对比及后续不可变版本发布。

## 验证与通过条件

离线守卫验证（不会访问 Shopify）：

```powershell
python -B -m unittest tests.test_shopify_orders_probe -v
```

真实 API gate 仍待执行：记录实际授权、请求页数、完整性、时间/币种覆盖和固定错误分类；人工核对测试订单计数与状态。记录中不包含店铺秘密、订单原文或用户信息。没有实际调用证据时，Roadmap 保持“准备完成，真实验收待开展”。

官方接口依据：[当前应用权限](https://shopify.dev/docs/api/admin-graphql/latest/queries/currentAppInstallation)、[订单查询](https://shopify.dev/docs/api/admin-graphql/latest/queries/orders)、[订单字段](https://shopify.dev/docs/api/admin-graphql/latest/objects/Order)、[搜索语法](https://shopify.dev/docs/api/usage/search-syntax)。日期值按官方要求加引号。实际字段授权与 API 行为仍以本店只读探测为准。
