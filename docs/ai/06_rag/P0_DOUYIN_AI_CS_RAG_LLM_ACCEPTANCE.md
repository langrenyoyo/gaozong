# P0 抖音AI小高客服 RAG/LLM 本地联调验收记录

## 1. 验收范围

本次验收覆盖 auto_wechat 当前 9100 抖音AI小高客服 RAG/LLM MVP 的本地闭环能力：

- `9000` AI小高线索主后端作为既有主业务服务保留。
- `9100` 抖音AI小高客服提供 SQLite RAG、LLM 回复建议和相关调试接口。
- `frontend` React 前端通过 `/douyin-ai-cs-test` 测试面板访问 9100。
- Docker 本地开发环境负责启动 `9000 + 9100 + frontend`。

本次验收不覆盖 `19000` 小高AI微信助手的真实微信 UI 自动化能力。`19000` 仍必须在 Windows 宿主机单独运行，不进入 Docker。

## 2. 已通过项

- `9100 /health` 验证通过。
- 创建 RAG 知识文档通过。
- 训练知识库通过。
- 搜索知识库通过。
- 生成回复建议通过。
- OpenRouter chat 真实联调通过。
- `llm_used=true`。
- `rag_used=true`。
- `manual_required=false`。
- `auto_send=false`。
- `warnings` 为空或不包含 `llm_not_configured`。
- `docker compose -f docker-compose.dev.yml config` 通过。
- frontend `/douyin-ai-cs-test` 可访问。

## 3. 关键配置模板

以下仅为本地配置模板，不得把真实 Key 写入仓库：

```env
XG_DOUYIN_AI_LLM_BASE_URL=https://openrouter.ai/api/v1
XG_DOUYIN_AI_LLM_API_KEY=<本地真实 Key，不提交>
XG_DOUYIN_AI_LLM_CHAT_MODEL=google/gemini-3-flash-preview
XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED=false
XG_DOUYIN_AI_LLM_TIMEOUT_SECONDS=30
XG_DOUYIN_AI_LLM_TEMPERATURE=0.3
```

当前建议先关闭真实 embedding provider，只验证 OpenRouter chat 链路。需要真实 embedding 时，应单独选择支持 `/embeddings` 的 provider 和模型，并再次做隔离检索验证。

## 4. 当前限制

- embedding 当前建议关闭真实 provider，使用本地 `mock_for_test_only`。
- OpenRouter 当前只作为 chat provider 使用，不作为默认 embedding provider。
- `/douyin-ai-cs-test` 是内部测试面板，不是最终产品页面。
- 当前只生成回复建议，不自动发送抖音私信。
- 正式抖音AI客服页面尚未融合。
- 商户知识库管理页面属于管理员/同事侧功能，不由当前抖音AI客服页面直接承载。
- 当前 auto_wechat / 9100 侧后续负责补齐商户知识库管理 API 和接口文档，交给管理员前端或同事对接。
- 9000 webhook / 原始事件 / 会话数据到 9100 回复建议的正式串联仍需后续实现。

## 5. 安全结论

当前 9100 的安全边界是“只建议、不发送”：

- `auto_send` 必须保持为 `false`。
- 没有自动发送抖音私信能力。
- 后续正式工作台必须保留人工确认动作。
- 文档、代码、测试和提交中不得写入真实 API Key 或 token。

## 6. 下一步建议

- P1：将 `/douyin-ai-cs-test` 的能力融合进正式抖音AI小高客服页面，重点覆盖会话消息、RAG 命中、AI 回复建议、人工确认/复制，不自动发送。
- P1：接入 9000 webhook / 原始事件 / 会话数据，生成可追溯的回复建议。
- P2：补齐商户知识库管理 API 和接口文档，交给管理员前端/同事对接。当前 9100 已有 create/train/search，但管理员知识库管理可能还需要 list/detail/update/disable/delete/training-runs 等接口。
- P2/P3：拆分 chat provider 与 embedding provider，接入真实 embedding 模型。
- P2/P3：补充真实 embedding 下的跨 `tenant_id + merchant_id + douyin_account_id` 隔离回归测试，并继续补齐权限和生产部署方案。
