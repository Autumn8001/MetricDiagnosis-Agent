# R4-001：持久调查前端合同与配置来源目录

日期：2026-10-10。源码起点：`313b7aefbe9f61774b84a987fe39812bbd85290d`。
范围：任务客户端与配置目录；不修改认可原型、旧 React 页面、Runtime、Worker 或数据库迁移。

## 产品作用与验证边界

这项工作为调查页面提供创建任务、读取任务历史/详情和选择服务器允许来源的基础。不是完整页面接线或浏览器验收，也不是新的真实 PostgreSQL/模型验收。

- `frontend/src/tasks/contracts.ts` 对应 `backend/app/api/task_schemas.py` 的公开字段，保留 Decimal 字符串和 nullable 数据，不把缺失 Diagnosis 补成结论。
- `frontend/src/tasks/client.ts::createTaskClient` 提供 sources/submit/list/detail。返回值先校验结构和来源/任务身份；HTTP 失败只保留状态与安全 code，网络异常与响应原文不透传。POST 不自动重试，取消请求不等于取消服务端任务。
- `GET /api/investigation-sources` 只投影服务已配置的 `TaskSourceBinding`：身份、环境、版本标签和指标能力；没有数据库连接、网络探测或任务创建。未配置服务仍返回 503。
- 配置目录不证明连接健康、持续同步、真实模型可用或日期覆盖；`data_version` 仍是标签。当前显式应用仅有 Synthetic sandbox 与 Olist static validation；不发明原型里的 Shopify 已连接状态。

## 复现命令

在 `frontend` 执行：

```powershell
npm run test:tasks
npm run lint
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json
npm run build
```

`test:tasks` 使用现有 TypeScript 与 Node 内置 test，无新增依赖。只将客户端编译到唯一 OS 临时目录，退出时清理本次目录；测试 transport 为 Fake Fetch，不发请求。生产构建写入被忽略的 `frontend/dist/`，不部署。

在 `backend` 执行：

```powershell
python -B -m unittest tests.test_task_source_catalog tests.test_task_api tests.test_task_application -v
python -B -m unittest discover -s tests -p "test_*.py"
```

配置目录测试使用实际 application builder/来源能力合同与 TestClient，但连接 factory 和 Worker 均不执行；数据库专项未配置时跳过，不算数据库验收。

## 验收结果

主线程亲自执行并检查最终代码：

| 检查 | 结果 | 证明边界 |
| --- | --- | --- |
| `npm run test:tasks` | 18/18 PASS | Fake Fetch；覆盖目录、编码、来源/任务校验、Decimal/null、安全错误、POST不重试及取消。 |
| 前端 lint / TypeScript / production build | PASS，lint无警告 | 静态/编译兼容性；构建产物保持旧页面，新增客户端尚未被 App 消费。 |
| 来源目录 + 任务 API + 应用专项 | 24/24 PASS | TestClient/受控配置；无数据库、模型或外部连接。 |
| 后端全回归 | Ran 612 tests / OK (skipped=3) | 离线测试；三个 PostgreSQL 类跳过，不替代此前独立真实数据库验收。 |
| 原型 SHA-256 | 与 PRODUCT.md 基线一致 | 原 HTML 文件未修改。 |

首次前端测试启动遇到 TypeScript 6 的显式文件编译要求与 rootDir 输出层级问题，已在测试脚本补 `--ignoreConfig` 与 `--rootDir src`，最终命令通过。主审补齐特殊过滤维度 `__proto__` 的保留测试，避免对象原型赋值吞掉查询范围；分页拒绝不安全整数。

## 剩余接线

下一切片由原型调查页面消费上述接口，补实际状态刷新、历史导航与证据引用。来源日期覆盖和维度可选值没有接口，不能使用原型的日期/商品/国家值填充为真实范围。页面不提供尚未实现的任务取消、自动重试或预设追问。
