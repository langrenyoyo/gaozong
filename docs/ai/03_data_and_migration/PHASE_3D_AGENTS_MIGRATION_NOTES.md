# Phase 3-D AI小高智能体后端能力迁移说明

## 本轮范围

本轮只迁移 `agents` 能力的后端服务入口，新增 9203 独立能力服务路径：

```text
/api/agents
/api/agents/{agent_id}
/api/agents/{agent_id}/knowledge-categories
/api/agents/{agent_id}/training-chat
```

旧 9000 接口继续保留兼容：

```text
/agents
/agents/{agent_id}
/agents/{agent_id}/knowledge-categories
/agents/{agent_id}/training-chat
```

本轮没有把 9000 旧接口改成 HTTP 转发，旧前端调用不需要变更。

## 当前过渡形态

1. `apps/agents` 已具备独立 FastAPI app、router、service、schemas、dependencies。
2. 9203 当前仍共享现有 SQLite 数据库和 `app.models`，这是能力服务拆分过程中的过渡态，不是最终拆库形态。
3. `AiAgent`、`AgentKnowledgeCategory`、`KnowledgeCategory`、`DouyinAccountAgentBinding` 未从 `app/models.py` 移动。
4. 未新增 migration，未修改任何表结构、字段、索引或默认值。
5. 旧 `app/services/ai_agent_service.py` 与 `app/services/agent_knowledge_category_service.py` 保留为 re-export 兼容入口。

## 能力边界

1. 9203 不信任前端传入的 `merchant_id` 或 `tenant_id`。
2. 可信上下文只来自 9000 gateway 注入的 `X-Gateway-*` header。
3. Agent CRUD 保持商户隔离：跨商户 Agent 不可读、不可改、不可删。
4. Agent 知识分类绑定保持原有可见性规则：`base` 默认有效，商户自建分类只在本商户可绑定。
5. `apps/agents` 不直接 import `apps/knowledge` 或 `app.services.knowledge_category_service`，分类校验在共享 DB / 共享模型过渡层内完成。

## 未迁移内容

1. 抖音企业号绑定 Agent 的高风险主链路未迁移。
2. `douyin_account_agent_binding_service.py` 未迁移。
3. `douyin_ai_cs_binding_service.py` 与 reply-suggestion 前置绑定校验未迁移。
4. reply-suggestion 主链路未修改。
5. 9100 RAG / LLM 行为未修改。
6. 19000 Local Agent、`input_writer`、微信 UI 自动化路径未修改。

## Client

新增 `packages/clients/agents_client.py`，用于后续 gateway 或其他能力服务通过 HTTP/internal API 调用 9203。

当前 client 覆盖：

1. gateway header 注入。
2. 内部 token 透传。
3. 超时配置。
4. HTTP 错误、网络错误、JSON 解析错误映射。

本轮没有让 9000 旧接口主动改用该 client。

## 生产前待补

1. 9203 当前标记为 dev/internal-only 过渡服务。
2. 生产前必须补齐服务间鉴权，包括内部 token、gateway 来源校验、调用方身份审计和失败日志。
3. 后续如将 9000 `/agents/*` 改为 HTTP 转发，应通过 `packages.clients.agents_client` 调用 9203。
4. 后续迁移抖音企业号绑定前，需要先设计 douyin-cs 与 agents 的 client 边界，禁止跨服务直接 import 业务 service。

## 未触碰安全边界

本轮未修改：

1. DB model / migration。
2. webhook 验签逻辑。
3. 抖音私信发送逻辑。
4. `manual_confirmed=true` 要求。
5. `auto_send=false` 安全边界。
6. 19000 Local Agent。
7. `input_writer` / 微信 UI 自动化路径。
8. 真实支付或 compute 扣费语义。
9. NewCarProject 登录、权限和 RequestContext 门面。
