# Shopify Orders probe：离线准备验收

> 日期：2026-10-10；分支：本地main；来源选择基线：`54cc574`。
> 判定：离线准备通过，真实商店API gate未通过。没有外部平台、模型或数据库调用。

## 实现与用途

新增 `backend/scripts/probe_shopify_orders.py` 和 `backend/tests/test_shopify_orders_probe.py`，只用于平台接入前的权限/字段/分页检查，不是连接器、同步器、指标导入或产品API。运行说明见 [`../shopify-orders-probe.md`](../shopify-orders-probe.md)。

固定 `currentAppInstallation` 与 Orders query，不接受任意查询/URL；只选订单ID、时间、测试/取消/财务状态和一个金额字段，在内存中校验后只输出脱敏汇总。固定请求版本2026-10，若响应版本回退则失败，未回显版本标记为未确认；不会打印原文错误或订单ID。

生产脚本要求独立显式sandbox确认和授权店主机，token仅来自独立进程环境；不加载`.env`，不申请/更改scope，不执行mutation。TLS验证、禁用环境代理/重定向、10秒分段超时与60秒检查预算、1MiB响应限制、最多5页和无重试限制已实现。预算不是网络操作的毫秒级硬截止；一次阻塞最多还受相应HTTP超时约束。

## 主线程检查和实际命令

在 `backend` 执行：

```powershell
python -B -m unittest tests.test_shopify_orders_probe -v
python -B -m unittest discover -s tests -p "test_*.py"
```

专项实际结果：`Ran 18 tests / OK`。所有HTTP通过MockTransport，CLI调用通过patch；不得将返回摘要中的 `api_verified` 当作商店实测记录。

最终全量回归实际结果：`Ran 630 tests in 17.032s / OK (skipped=3)`。三个数据库专项未配置专用环境而跳过；这是离线回归，不是新增数据库或真实模型验收。未改前端，本轮未重跑前端构建/浏览器。

守卫实进程验证：不带 `--allow-sandbox-read` 时输出固定 `sandbox_read_confirmation_required` 并exit1；带开关但host为 `private.example` 时输出固定 `invalid_shop_host` 并exit1。两次在读取token/创建HTTP客户端之前退出，没有网络请求。

主线程审查后修正了请求编码、nullable字段存在性、库入口校验、版本回退检测、GraphQL错误结构和日期搜索语法；额外亲测直接入口域名守卫和总时间预算停止。官方日期搜索要求引号，见 [搜索语法](https://shopify.dev/docs/api/usage/search-syntax)。

## 限制和下一验收

- 没有实际账号、token、店铺字段或权限验收；没有真实业务订单、持续更新或模型诊断。
- sandbox开关和订单test字段不能自动验证开发店身份，执行者必须人工核对获授权专用开发店。
- 本次分页读完不保证多页期间上游静止；`snapshot_consistent=false`。UTC样本覆盖不等于店时区经营数据完整性。
- 金额字段合法不等于销售/AOV口径验收。不会宣称sessions/转化率/商品/流量来源可用。
- 等用户准备开发店及应用只读授权后执行一次有限只读探测；验证实际覆盖与权限，再决定最小版本发布和SQL指标映射。不在真实API gate之前继续堆同步模块。
