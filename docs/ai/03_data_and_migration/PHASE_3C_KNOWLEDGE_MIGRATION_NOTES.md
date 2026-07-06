# Phase 3-C 统一知识库训练后端能力迁移说明

## 本轮范围

本轮只迁移 `knowledge` 能力的后端服务入口，新增 9206 独立能力服务路径：

```text
/api/knowledge/categories
/api/knowledge/rag/documents
/api/knowledge/rag/train
```

旧 9000 接口继续保留兼容：

```text
/knowledge-categories
/integrations/douyin-ai-cs/rag/documents
/integrations/douyin-ai-cs/rag/train
```

## 当前过渡形态

1. `apps/knowledge` 已具备独立 FastAPI app、router、service、schemas、dependencies。
2. 9206 当前仍共享现有 SQLite 数据库和 `app.models`，这是能力服务拆分过程中的过渡态，不是最终拆库形态。
3. `KnowledgeCategory` / `AgentKnowledgeCategory` 等模型未迁移，`app/models.py` 未修改。
4. 未新增 migration，未修改任何表结构、字段、索引或默认值。
5. 旧 `app/services/knowledge_category_service.py` 保留为 re-export 兼容入口，避免旧 9000 调用方失效。

## RAG 边界

1. 9100 RAG SQLite DB 没有迁移。
2. 9100 embedding、chunker、vector search、lexical fallback 等内部实现没有迁移。
3. 9206 的 RAG documents/train 只是统一知识库训练能力入口，继续通过现有 9100 client 调用 RAG API。
4. RAG search 本轮不强行迁移，仍按现有 9100 / 调试入口边界保留。

## 可信 Scope

1. 9206 不信任前端传入的 `merchant_id`、`tenant_id`、`douyin_account_id`、`allowed_category_keys` 或 `agent_config`。
2. `merchant_id` / `tenant_id` / `user_id` 仅来自 9000 gateway 注入的 `X-Gateway-*` header。
3. RAG documents/train 会在后端校验 `account_open_id` 是否属于当前可信商户。
4. `category_key` 会在后端校验是否是 `base` 或当前商户 active 分类。
5. 发往 9100 的 payload 由 9206 后端重新构造可信 scope。

## 生产前待补

1. 9206 当前标记为 dev/internal-only 过渡服务。
2. 生产前必须补齐服务间鉴权，至少包含内部 token、gateway 来源校验、调用方身份审计和失败日志。
3. 后续如果 9000 旧接口切换为 HTTP 转发，应通过 `packages/clients/knowledge_client.py` 调用 9206。
4. 后续是否迁移 RAG 文档、训练、搜索的内部实现，需要单独评审 9100 数据与向量检索边界。

## 未触碰安全边界

本轮未修改：

1. webhook 验签逻辑。
2. 抖音私信发送逻辑。
3. `manual_confirmed=true` 要求。
4. `auto_send=false` 安全边界。
5. 19000 Local Agent。
6. `input_writer` / 微信 UI 自动化路径。
7. 真实支付或算力扣费语义。
8. DB model / migration。

## 验证记录

本轮新增和更新的测试覆盖：

1. 9206 `/`、`/health`、`/openapi.json` 可访问。
2. 9206 `/api/knowledge/categories` GET / POST 可访问。
3. base 分类默认可见。
4. 商户自定义分类按可信 merchant_id 隔离。
5. RAG documents/train 忽略前端伪造 scope，由后端注入可信 payload。
6. 9206 拒绝跨商户企业号。
7. `packages.clients.knowledge_client` 覆盖 gateway header、超时、HTTP 错误、网络错误和 JSON 错误映射。

## 后续建议

Phase 3-D 进入 `agents` 能力迁移前，建议保持当前策略：

1. 继续保留 9000 旧接口兼容。
2. 不拆数据库。
3. 不改变 NewCarProject 登录、权限和 RequestContext 门面。
4. 不迁移 reply-suggestion 主链路，除非单独进入对应阶段。
