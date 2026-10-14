# 真实模型调查尝试（2026-10-14）

## 结果

本次在独立 `metricsleuth_r2_acceptance` Synthetic 测试库上执行了一次真实 SDK 调查，使用仓库既有 `verify_live_task_persistence.py`，限制为最多 8 次工具调用、10 轮、关闭自动重试和远程 tracing。模型配置从本机 `.env` 读取，但没有输出或提交任何凭据。

结果为失败：上游返回 `AuthenticationError`，HTTP 状态 401。实际模型执行轮数和工具调用数均为 0，因此没有产生 Observation、Evidence 或 Diagnosis，不能评价 Driver、Scope 或停止条件。

随后使用同一 `.env` 的 `OPENAI_BASE_URL` 和 `OPENAI_API_KEY`，只发送标准 `Authorization: Bearer` 的 `GET /v1/models` 探测（不产生模型推理），端点仍返回 HTTP 401。这将故障边界定位在 CPA 代理的凭据/授权接受状态，而不是模型工具协议或调查逻辑。

## 已验证的失败持久化

- 任务 Run 已保存为 `failed`，安全错误码为 `execution_failed`。
- 失败 Run 的 Tool Call、Observation、Evidence、Diagnosis 数量均为 0，没有伪造调查事实。
- 来源仍明确为 Synthetic/Sandbox，数据版本为本次验收固定标签。
- PostgreSQL 测试实例已停止，55440 端口无监听；本次没有访问 Shopify 或生产数据库。

## 解释边界

这次运行证明了失败路径和安全留存仍可工作，但没有证明真实模型可用，也没有产生计费意义上的成功调用结果。后续必须先由用户或端点维护者修复/确认 CPA 鉴权与模型访问，再获得新的有限授权；不得在相同 401 条件下重复调用。

## 需要的外部修复

请在 CPA 服务侧确认当前 API key 仍有效、账号有 Gemini 模型访问权限，并确认本机代理要求的鉴权方式与 `.env` 中的 `OPENAI_BASE_URL` / `OPENAI_API_KEY` 匹配。更新凭据后先重新执行无推理的 `/v1/models` 状态检查；只有返回成功，才再次授权真实调查。不要在聊天或仓库中提供密钥。
