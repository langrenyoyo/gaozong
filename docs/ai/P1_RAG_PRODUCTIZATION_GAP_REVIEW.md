# P1-RAG-PRODUCTIZATION-GAP-REVIEW-1

更新时间：2026-07-02

## 1. 本轮口径

本轮按 `P1-RAG-UNIFIED-KB-CONSUMPTION-CLOSURE-1` 更新后的产品口径审计：

1. 当前阶段不开放商户知识库管理。
2. 只有管理员 / 内部训练入口可以训练 / 维护统一“小高 AI 知识库”。
3. 商户的抖音 AI 客服 / 自动回复能力只消费管理员维护的小高 AI 知识库。
4. `auto_wechat:douyin_ai_cs` 控制商户使用抖音 AI 客服能力，不代表商户拥有知识库管理权限。
5. `auto_wechat:knowledge` 不是 NewCar 上游正式权限码，只能作为项目内历史 / 过渡权限记录。
6. 知识库训练入口最终准入以 IP 白名单为准；商户 NewCar 登录态不能替代 IP 白名单。
7. `auto_wechat:knowledge_training` 如在历史代码或测试中出现，只能视为历史 / 阶段性 / 待清理实现，不写成最终正式商户权限码。

## 2. 已扫描范围

前端：

1. `frontend/src/features/knowledge/*`
2. `frontend/src/features/routes.ts`
3. `frontend/src/features/capabilities.ts`
4. `frontend/src/features/douyin-cs/pages/DouyinAiCsTestPage.tsx`
5. `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`
6. `frontend/src/api/douyinAiCsClient.ts`

后端：

1. `app/routers/douyin_ai_cs_proxy.py`
2. `app/routers/knowledge_training.py`
3. `app/routers/knowledge_categories.py`
4. `app/routers/agents.py`
5. `app/services/xg_douyin_ai_cs_client.py`
6. `apps/xg_douyin_ai_cs/routers/rag.py`
7. `apps/xg_douyin_ai_cs/routers/knowledge_training.py`
8. `apps/xg_douyin_ai_cs/services/reply_decision_service.py`

## 3. 当前事实

### 3.1 商户正式菜单没有开放知识库管理

事实：

1. `frontend/src/features/capabilities.ts` 的商户导航中没有“知识库”入口。
2. `frontend/src/features/routes.ts` 没有把 `knowledgeRoutes` 合并进 `capabilityRoutes`。
3. 旧路径 `/knowledge-base`、`/knowledge-categories`、`/knowledge/base`、`/knowledge/categories` 都重定向到 `/douyin-cs/workbench`。
4. `KnowledgeBasePage.tsx` 和 `features/knowledge/api.ts` 仍存在，但当前不属于商户正式路由。

结论：当前商户正式菜单未暴露知识库训练 / 文档管理 / 分类管理。

### 3.2 商户生产回复建议走 9000 可信代理

事实：

1. 正式工作台使用 `getTrustedReplySuggestion()`。
2. `getTrustedReplySuggestion()` 调用 `9000 /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`。
3. `app/routers/douyin_ai_cs_proxy.py` 在该接口校验 `auto_wechat:douyin_ai_cs`。
4. 9000 从 `RequestContext.merchant_id` 注入可信商户上下文，不信任前端传入 merchant_id。
5. 9000 校验抖音账号与 Agent 绑定关系。
6. 9000 读取 `agent_knowledge_categories` 并注入 `agent_config.allowed_category_keys`。
7. 9000 记录 `ai_reply_decision_logs`，并强制最终 `auto_send=false`。

结论：商户生产回复建议链路没有绕过 9000。

### 3.3 调试页仍可直连 9100，但当前不在正式路由

事实：

1. `DouyinAiCsTestPage` 使用 `searchRag()` 直连 `9100 /rag/search`。
2. `DouyinAiCsTestPage` 使用 `getReplySuggestion()` 直连 9100 回复建议接口。
3. `frontend/src/features/routes.ts` 将 `/douyin-ai-cs-test` 重定向到 `/douyin-cs/workbench`。
4. 测试页页面文案已标注“内部调试面板”。
5. `searchRag()` 和 `getReplySuggestion()` 已补注释，标明内部调试专用，正式商户侧应走 9000 可信代理。

结论：当前调试能力仍在代码中保留，但不作为商户正式入口。后续若重新暴露测试页，必须加内部白名单或管理员门禁。

### 3.4 管理员统一知识库训练走 9000 IP 白名单代理

事实：

1. `app/routers/knowledge_training.py` 提供 `POST /knowledge-training/ask` 和 `POST /knowledge-training/{training_id}/feedback`。
2. 两个接口都依赖 `require_knowledge_training_ip_whitelist`。
3. 白名单来自 `KNOWLEDGE_TRAINING_IP_WHITELIST`，默认仅本机来源。
4. 9000 使用固定 `KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID` 和 `KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID` 调用 9100。
5. 该代理返回字段经过 `_public_payload()` 收口，只暴露训练必要字段。
6. 甲方已确认知识库训练端由管理员统一使用，非白名单无法进入；该入口不对商户开放。

结论：当前管理员统一知识库训练入口是“内部白名单代理”，不是商户菜单能力；商户登录态和商户权限不能替代 IP 白名单。

### 3.5 9100 内部接口增加服务间 token 门禁

事实：

1. `apps/xg_douyin_ai_cs/routers/rag.py` 暴露 `/rag/documents`、`/rag/train`、`/rag/search`。
2. `apps/xg_douyin_ai_cs/routers/knowledge_training.py` 暴露 `/knowledge-training/ask` 和 `/knowledge-training/{training_id}/feedback`。
3. `apps/xg_douyin_ai_cs/routers/ai_reply.py` 暴露 `/douyin/reply-suggestion` 和 `/douyin/conversations/{conversation_id}/reply-suggestion`。
4. 这些 9100 内部接口已增加 `X-Internal-Service-Token` 校验。
5. `app/services/xg_douyin_ai_cs_client.py` 在配置 `XG_DOUYIN_AI_CS_SERVICE_TOKEN` 后会向 9100 发送 `X-Internal-Service-Token`。
6. `docker-compose.dev.yml` 已把同一个 `XG_DOUYIN_AI_CS_SERVICE_TOKEN` 注入 9000 和 9100。
7. 内部 token 不进入任何 `VITE_*` 环境变量，不暴露给浏览器。
8. `health` / `ready` / `version` 不受内部 token 门禁影响。
9. 开发环境未配置 token 时兼容放行；`APP_ENV=production` 且未配置 token 时，9100 内部接口拒绝访问。

结论：9100 应视为内部服务，商户浏览器生产链路必须走 9000 可信代理，不允许直连 9100。

## 4. 当前风险

### P0：9100 内部服务 token 需要生产配置落地

`P1-RAG-INTERNAL-SERVICE-AUTH-GATE-1` 已补 9100 内部 token 门禁和 9000 请求头注入验证。生产部署仍必须确保：

1. 9000 和 9100 配置同一个非空 `XG_DOUYIN_AI_CS_SERVICE_TOKEN`。
2. 不把该 token 放入任何前端 `VITE_*` 环境变量。
3. 9100 不直接暴露给商户浏览器公网访问。

### P0：9000 商户 RAG 写入 / 训练代理仍存在

`app/routers/douyin_ai_cs_proxy.py` 仍保留：

1. `POST /integrations/douyin-ai-cs/rag/documents`
2. `POST /integrations/douyin-ai-cs/rag/train`

当前前端正式菜单没有调用它们，但后端接口仍可被持有 `auto_wechat:douyin_ai_cs` 的商户直接请求。

建议下一步任务：

```text
P1-RAG-MERCHANT-KB-MANAGEMENT-DISABLE-1
```

最小方向：将这两个 9000 代理标记为内部 / 管理员入口，或临时禁用商户访问；不要把 `auto_wechat:douyin_ai_cs` 当作知识库管理权限。

### P1：Agent 分类绑定仍暴露在智能体接口中

`/agents/{agent_id}/knowledge-categories` 当前仍由智能体权限保护，产品上是否继续允许商户配置“使用哪些统一知识分类”需要确认。

建议下一步任务：

```text
P1-RAG-AGENT-KB-CATEGORY-SCOPE-CONFIRM-1
```

待确认：商户是否可以选择统一知识库分类，还是统一由管理员配置。

## 5. 建议收口方案

### 5.1 商户正式入口

保持现状：

1. 不把 `knowledgeRoutes` 合并进 `capabilityRoutes`。
2. 不在 `capabilities.ts` 增加“知识库”菜单。
3. `/knowledge/*` 继续重定向到 `/douyin-cs/workbench`。

### 5.2 商户生产消费链路

保持并强化：

```text
DouyinAiCsWorkbenchPage
  -> getTrustedReplySuggestion()
  -> 9000 /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion
  -> RequestContext.merchant_id
  -> 账号 / Agent 绑定校验
  -> 9000 注入 allowed_category_keys
  -> 9100 reply-suggestion
  -> 9100 RAG 检索统一知识库
  -> 9000 强制 auto_send=false 并记录日志
```

### 5.3 管理员训练链路

保持并强化：

```text
管理员 / 内部工具
  -> 9000 /knowledge-training/*
  -> IP 白名单
  -> 固定 xiaogao_system / xiaogao_base scope
  -> 9100 /knowledge-training/*
```

后续可把 IP 白名单升级为管理员登录态 + 内部服务 token 双门禁。

### 5.4 调试入口

保留但不开放：

1. `DouyinAiCsTestPage` 继续标为内部调试面板。
2. `searchRag()` 和直连 `getReplySuggestion()` 继续只用于调试。
3. 如未来需要访问测试页，应加管理员权限或内部白名单，不进入商户导航。

## 6. 本轮代码状态

本轮没有开放商户知识库菜单，没有新增商户训练入口，没有修改 NewCar 登录协议，没有恢复 `/auth/callback`，没有改 9100 检索核心，没有改自动发送链路。

仅保留两处注释标识：

1. `frontend/src/features/knowledge/api.ts`：标明直连 RAG search 是内部调试能力，正式写入 / 训练应走 9000。
2. `frontend/src/api/douyinAiCsClient.ts`：标明直连 9100 reply-suggestion 是内部调试能力，正式工作台应使用 `getTrustedReplySuggestion()`。

## 7. 仍待确认

1. 管理员知识库管理最终入口放在 auto_wechat 9000，还是 NewCarProject 管理后台。
2. 9000 的 `/integrations/douyin-ai-cs/rag/documents` 和 `/rag/train` 是否立即禁用商户访问，还是先加管理员 / 内部白名单。
3. 商户是否允许配置 Agent 使用的统一知识分类。
4. 9100 内部服务 token 的环境变量名称、部署注入方式和失败返回格式。

## 8. P1-RAG-WRITE-TRAIN-PROXY-LOCKDOWN-1 补充审计

更新时间：2026-07-02

### 8.1 本轮产品口径

事实：
1. 当前阶段不开放商户知识库管理。
2. 管理员 / 内部训练端统一维护“小高 AI 知识库”，准入方式为 IP 白名单。
3. 商户抖音 AI 客服只消费统一知识库，不允许训练、写入、管理或直接搜索知识库。
4. `auto_wechat:douyin_ai_cs` 只代表商户可使用抖音 AI 客服能力，不代表知识库管理权限。
5. `auto_wechat:knowledge`、`auto_wechat:knowledge_training` 只按历史 / 过渡 / 待清理权限记录处理，不写成 NewCar 正式商户权限码。

### 8.2 已扫描文件

后端：
1. `app/routers/douyin_ai_cs_proxy.py`
2. `app/routers/knowledge_categories.py`
3. `app/routers/knowledge_training.py`
4. `app/services/xg_douyin_ai_cs_client.py`
5. `apps/knowledge/routers.py`
6. `apps/knowledge/dependencies.py`
7. `apps/knowledge/services.py`

前端：
1. `frontend/src/features/routes.ts`
2. `frontend/src/features/capabilities.ts`
3. `frontend/src/features/knowledge/api.ts`
4. `frontend/src/features/knowledge/pages/KnowledgeBasePage.tsx`
5. `frontend/src/features/knowledge/pages/KnowledgeCategoriesPage.tsx`
6. `frontend/src/features/douyin-cs/pages/DouyinAiCsTestPage.tsx`

### 8.3 接口分类和处理结果

| 接口 / 入口 | 分类 | 本轮处理 | 说明 |
|---|---|---|---|
| `POST /knowledge-training/ask` | 管理员 / 内部训练入口 | 保持 IP 白名单 | 不走商户 NewCar 权限。 |
| `POST /knowledge-training/{training_id}/feedback` | 管理员 / 内部训练入口 | 保持 IP 白名单 | 保持 wrong 反馈只进入 `knowledge_training_feedbacks`、`pending_review` 的语义。 |
| `POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion` | 商户 AI 客服消费入口 | 保持现状 | 继续校验 `auto_wechat:douyin_ai_cs`，由 9000 注入可信上下文。 |
| `POST /integrations/douyin-ai-cs/rag/documents` | 历史 / 待清理写入代理 | 已锁定 | 商户请求返回 403 `RAG_MERCHANT_WRITE_DISABLED`，不会调用 9100。 |
| `POST /integrations/douyin-ai-cs/rag/train` | 历史 / 待清理训练代理 | 已锁定 | 商户请求返回 403 `RAG_MERCHANT_TRAIN_DISABLED`，不会调用 9100。 |
| `GET /knowledge-categories` | 只读分类展示 / 历史辅助 | 保持只读 | 当前仍供 Agent 分类绑定等历史链路读取。 |
| `POST /knowledge-categories` | 历史商户分类管理入口 | 已锁定 | 商户请求返回 403 `KNOWLEDGE_CATEGORY_CREATE_DISABLED`。 |
| `apps/knowledge` 下 `/api/knowledge/*` | dev/internal-only 过渡服务 | 本轮只记录 | 未挂入 9000 主应用；未来启用需单独加内部鉴权或下线。 |
| `DouyinAiCsTestPage` | 内部调试页 | 保持不进正式路由 | `/douyin-ai-cs-test` 当前重定向到 `/douyin-cs/workbench`。 |
| `frontend/src/features/knowledge/*` | 历史页面 / 待清理代码 | 保持不进正式路由 | 正式 `capabilityRoutes` 未合并 `knowledgeRoutes`。 |

### 8.4 本轮锁定的风险面

事实：
1. 持有商户登录态和 `auto_wechat:douyin_ai_cs` 的用户不能再通过 9000 创建 RAG 文档。
2. 持有商户登录态和 `auto_wechat:douyin_ai_cs` 的用户不能再通过 9000 触发 RAG 训练。
3. 持有商户登录态和历史 Agent 权限的用户不能再通过 `POST /knowledge-categories` 创建商户知识分类。
4. 以上锁定都发生在入口最前面，前端伪造 `merchant_id` / `tenant_id` / `douyin_account_id` 不会进入旧写入链路。
5. 9000 调 9100 的正式消费链路仍通过 `X-Internal-Service-Token` 走内部服务调用。

### 8.5 未处理风险和原因

1. `apps/knowledge` 过渡服务仍保留旧写入 / 训练能力：该服务未挂入 9000 主应用，本轮按审计记录处理；如果未来启用或部署，需要单开 `P1-RAG-KNOWLEDGE-APP-LOCKDOWN-1`。
2. `/agents/{agent_id}/knowledge-categories` 仍允许 Agent 分类绑定：是否允许商户配置“消费哪些统一知识分类”仍需产品确认，本轮不顺手修改 Agent UI 和绑定逻辑。
3. 前端历史知识库页面代码仍存在：正式路由不触达，本轮不删除代码；如要彻底清理，需要单开前端历史入口清理任务。

### 8.6 建议下一步任务

```text
P1-RAG-KNOWLEDGE-APP-LOCKDOWN-1
P1-RAG-AGENT-KB-CATEGORY-SCOPE-CONFIRM-1
P1-FRONTEND-KNOWLEDGE-LEGACY-CLEANUP-1
```

## 9. P1-RAG-KNOWLEDGE-APP-LOCKDOWN-1 审计结果

更新时间：2026-07-02

### 9.1 本轮产品口径

事实：
1. 知识库训练端只给管理员 / 内部统一使用，不对商户开放。
2. 管理员训练入口最终准入方式为 IP 白名单。
3. 商户抖音 AI 客服 / 自动回复只消费管理员维护的统一“小高 AI 知识库”。
4. `apps/knowledge` 是过渡服务，不能成为商户绕过 9000 / 9100 安全边界的入口。
5. `auto_wechat:knowledge` 和 `auto_wechat:knowledge_training` 只按历史 / 过渡 / 待清理权限记录处理，不写成 NewCar 正式商户权限码。

### 9.2 已扫描文件

1. `apps/knowledge/main.py`
2. `apps/knowledge/router.py`
3. `apps/knowledge/routers.py`
4. `apps/knowledge/dependencies.py`
5. `apps/knowledge/services.py`
6. `apps/knowledge/schemas.py`
7. `docker-compose.dev.yml`
8. `Dockerfile.backend.dev`
9. `app/main.py`
10. `app/routers/capability_gateway.py`
11. `tests/test_knowledge_app.py`
12. `tests/test_capability_service_boundaries.py`
13. `frontend/src/features/knowledge/*`
14. `frontend/src/pages/KnowledgeBasePage.tsx`
15. `frontend/src/pages/KnowledgeCategoriesPage.tsx`

### 9.3 暴露面判断

事实：
1. `apps/knowledge` 有独立 FastAPI app，入口为 `apps.knowledge.main:app`。
2. `docker-compose.dev.yml` 当前定义了 `knowledge-service`，并映射宿主端口 `9206:9206`。
3. `app/main.py` 没有 include `apps.knowledge` 路由；9000 只挂载 `app.routers.knowledge_categories` 和 `app.routers.knowledge_training`。
4. 前端正式生产入口没有调用 `http://*:9206/api/knowledge/*`。
5. `frontend/src/features/knowledge/*` 仍保留历史页面和 API，但当前正式路由已回落到 `/douyin-cs/workbench`。

结论：`apps/knowledge` 不是 9000 主应用路由，但在 dev compose 中可独立启动并对宿主暴露 9206，因此不能仅按“未暴露过渡代码”处理。

### 9.4 apps/knowledge 路由清单

| 接口 | 分类 | 本轮处理 | 说明 |
|---|---|---|---|
| `GET /` | 只读健康 / 状态 | 保持现状 | capability 根信息。 |
| `GET /health` | 只读健康 / 状态 | 保持现状 | 健康检查。 |
| `GET /openapi.json` | 只读调试 / 文档 | 保持现状 | 仅反映服务接口文档。 |
| `GET /api/knowledge/categories` | 历史只读 / 待确认 | 保持只读 | 仍要求 gateway context；后续建议随 9206 去留一起处理。 |
| `POST /api/knowledge/categories` | 已暴露写入接口 | 已锁定 | 固定返回 403 `KNOWLEDGE_APP_CATEGORY_WRITE_DISABLED`。 |
| `POST /api/knowledge/rag/documents` | 已暴露 RAG 写入接口 | 已锁定 | 固定返回 403 `KNOWLEDGE_APP_RAG_WRITE_DISABLED`，不调用 9100。 |
| `POST /api/knowledge/rag/train` | 已暴露 RAG 训练接口 | 已锁定 | 固定返回 403 `KNOWLEDGE_APP_RAG_TRAIN_DISABLED`，不调用 9100。 |

### 9.5 本轮锁定的风险面

事实：
1. 即使请求方伪造 `X-Gateway-*` 上下文，也不能通过 9206 创建知识分类。
2. 即使请求方伪造 `merchant_id`、`tenant_id`、`douyin_account_id`、`allowed_category_keys`，也不能通过 9206 写入 RAG 文档。
3. 即使请求方具备历史 `auto_wechat:knowledge` 或 `auto_wechat:douyin_ai_cs` 字段，也不能通过 9206 触发 RAG 训练。
4. 三个锁定入口在进入旧业务逻辑前直接返回 403，不写数据库，不调用 9100。
5. health / root / openapi 保持可用，避免破坏 capability 边界测试。

### 9.6 未处理风险和原因

1. `GET /api/knowledge/categories` 仍保留：本轮目标是锁定旧写入 / 训练 / 搜索能力；只读分类是否继续保留，需要结合 Agent 分类消费口径单独确认。
2. `knowledge-service` 仍保留宿主端口 `9206:9206`：本轮不做部署结构删除，避免影响 capability service 边界验证；后续如果不再需要独立过渡服务，应单开任务移除 compose 服务或改为仅内部网络。
3. 旧代码中不可达的写入实现暂未删除：本轮采用最小锁定，不删除历史代码，便于后续按产品确认统一清理。

### 9.7 后续建议

```text
P1-RAG-KNOWLEDGE-SERVICE-DECOMMISSION-1
P1-RAG-AGENT-KB-CATEGORY-SCOPE-CONFIRM-1
P1-FRONTEND-KNOWLEDGE-LEGACY-CLEANUP-1
```

## 10. P1-AGENT-KB-CATEGORY-CONSUMPTION-POLICY-AUDIT-1 只读审计

更新时间：2026-07-02

### 10.1 审计范围

已扫描：

1. `app/routers/agents.py`
2. `app/routers/knowledge_categories.py`
3. `app/routers/douyin_ai_cs_proxy.py`
4. `app/services/agent_knowledge_category_service.py`
5. `apps/agents/services.py`
6. `app/services/knowledge_category_service.py`
7. `apps/knowledge/services.py`
8. `app/models.py`
9. `app/schemas.py`
10. `migrations/versions/0012_agent_knowledge_categories.sql`
11. `migrations/versions/0013_knowledge_categories.sql`
12. `tests/test_knowledge_categories_api.py`
13. `tests/test_ai_agents.py`
14. `tests/test_douyin_ai_cs_proxy.py`
15. `tests/test_xg_douyin_ai_cs_app.py`
16. `frontend/src/features/agents/pages/SuperMerchantAgent.tsx`
17. `frontend/src/api/aiAgents.ts`
18. `frontend/src/features/routes.ts`
19. `frontend/src/features/capabilities.ts`
20. `frontend/src/features/knowledge/*`
21. `frontend/src/features/douyin-cs/pages/DouyinAiCsTestPage.tsx`

本轮只读审计业务代码和前端代码；本节为文档记录，不修改接口、权限、前端 UI、9100、19000、NewCar 登录协议或自动发送链路。

### 10.2 后端接口清单

| Method | Path | 函数名 | 当前权限依赖 | merchant_id | 可写 | 修改知识库内容 | 修改 Agent 分类绑定 | 调用 9100 | 影响 allowed_category_keys | 初步分类 |
|---|---|---|---|---|---|---|---|---|---|---|
| GET | `/knowledge-categories` | `list_knowledge_categories` | `get_request_context_required` + `auto_wechat:ai_agents` 或历史兼容 `auto_wechat:agent` | 是，缺失返回 `MERCHANT_ID_REQUIRED` | 否 | 否 | 否 | 否 | 间接提供可选分类 | 只读分类展示 / Agent 消费配置辅助 |
| POST | `/knowledge-categories` | `create_knowledge_category` | 入口先固定 403，旧逻辑未进入 | 未进入旧逻辑 | 否，已锁定 | 否 | 否 | 否 | 否 | 历史商户分类管理入口，已禁用 |
| GET | `/agents/{agent_id}/knowledge-categories` | `get_agent_knowledge_categories` | `get_request_context_required` + `auto_wechat:ai_agents` 或历史兼容 `auto_wechat:agent` | 是 | 否 | 否 | 否 | 否 | 返回当前 Agent 手动绑定 key | Agent 消费知识分类配置 |
| PUT | `/agents/{agent_id}/knowledge-categories` | `update_agent_knowledge_categories` | `get_request_context_required` + `auto_wechat:ai_agents` 或历史兼容 `auto_wechat:agent` | 是 | 是 | 否 | 是，替换 `agent_knowledge_categories` | 否 | 后续 reply-suggestion 会读取这些 key | Agent 消费知识分类配置 |
| POST | `/agents/preview` | `preview_agent` | `get_request_context_required` + `auto_wechat:ai_agents` 或历史兼容 `auto_wechat:agent` | 是 | 否 | 否 | 否 | 是 | 使用请求中的 `knowledge_category_keys` 构造预览用 `allowed_category_keys` | Agent 预览 / 调试消费链路 |
| POST | `/agents/{agent_id}/training-chat` | `training_chat` | `get_request_context_required` + `auto_wechat:ai_agents` 或历史兼容 `auto_wechat:agent` | 是 | 否 | 否 | 否 | 否 | 否 | 历史训练预览，不写知识库 |
| POST | `/integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion` | `create_reply_suggestion_proxy` | `get_request_context_required` + `auto_wechat:douyin_ai_cs` | 是，缺失返回 `MERCHANT_CONTEXT_MISSING` | 否 | 否 | 否 | 是 | 读取 `agent_knowledge_categories` 并注入 `agent_config.allowed_category_keys` | 商户 AI 客服消费统一知识库 |

说明：

1. 代码中不存在 `POST` / `DELETE` 形式的 `/agents/{agent_id}/knowledge-categories`，当前只有 `GET` 和 `PUT`。
2. `Agent CRUD` 请求体不携带分类字段，分类绑定通过独立 `PUT /agents/{agent_id}/knowledge-categories` 保存。
3. `PUT /agents/{agent_id}/knowledge-categories` 只写 9000 的绑定表，不创建、修改或删除 9100 知识文档。
4. `POST /knowledge-categories` 已固定返回 403 `KNOWLEDGE_CATEGORY_CREATE_DISABLED`，旧创建逻辑不可达。

### 10.3 前端入口清单

| 页面 / 组件 | 商户正式页面可见 | 知识分类勾选 | 当前文案 | 是否像知识库管理 | 实际语义 | 是否调用写入接口 | 调用 API |
|---|---|---|---|---|---|---|---|
| `frontend/src/features/agents/pages/SuperMerchantAgent.tsx` | 是，路由 `/agents` | 是 | `智能体知识库`、`小高知识库`、`配置名称、提示词、知识库提示词和知识库范围` | 有混淆风险 | Agent 可消费哪些知识分类 | 是，只写绑定 | `GET /knowledge-categories`、`GET/PUT /agents/{agent_id}/knowledge-categories` |
| `SuperMerchantAgent` 右侧预览面板 | 是，随 `/agents` 可见 | 间接读取绑定 | `统一知识库训练预览`、`输入训练问题` | 有混淆风险 | Agent 草稿预览 / 调试消费 | 否 | `POST /agents/preview` |
| `frontend/src/features/knowledge/pages/KnowledgeBasePage.tsx` | 否，正式路由已重定向 | 有知识范围选择 | `小高知识库`、`新增知识`、`整理小高知识库` | 是 | 历史知识写入 / 训练页面 | 是，但 9000 写入/训练代理已锁定 | `POST /integrations/douyin-ai-cs/rag/documents`、`POST /integrations/douyin-ai-cs/rag/train` |
| `frontend/src/features/knowledge/pages/KnowledgeCategoriesPage.tsx` | 否，正式路由已重定向 | 分类创建 | `知识分类`、`创建商户分类` | 是 | 历史分类管理页面 | 是，但后端已锁定 | `POST /knowledge-categories` |
| `frontend/src/features/douyin-cs/pages/DouyinAiCsTestPage.tsx` | 否，`/douyin-ai-cs-test` 已重定向 | 可填 `category_key` | `创建知识`、`训练知识库`、`搜索知识库` | 是 | 内部调试页残留 | 是 / 搜索 | `createRagDocument`、`trainRag`、`searchRag` |
| `frontend/src/features/knowledge/api.ts` | 不是页面 | 无 | 注释标注“内部调试专用” | 代码残留风险 | 历史/调试 API | 部分函数仍存在 | `searchRag` 仍直连 9100 `/rag/search`，但正式页面不触达 |

路由事实：

1. `frontend/src/features/routes.ts` 没有把 `knowledgeRoutes` 合并进 `capabilityRoutes`。
2. `/knowledge-base`、`/knowledge-categories`、`/knowledge/base`、`/knowledge/categories` 都重定向到 `/douyin-cs/workbench`。
3. `/agents/knowledge-categories` 重定向到 `/agents`。
4. 商户导航中没有单独的知识库管理菜单。

### 10.4 当前真实行为

事实：

1. Agent 分类绑定不会创建、修改或删除知识库文档。
2. Agent 分类绑定只写 `agent_knowledge_categories`，用于 9000 在 reply-suggestion 时注入 `agent_config.allowed_category_keys`。
3. 商户当前不能创建知识分类：`POST /knowledge-categories` 固定 403。
4. 商户当前可以通过 `/agents` 页面绑定 / 解绑已有可见分类，包括 `base`。
5. 当前前端允许取消 `base`；测试 `test_agent_base_knowledge_category_can_be_saved_and_unchecked` 也断言可取消。
6. `apps/agents/services.py` 的 `build_effective_category_keys()` 不自动追加 `base`，绑定为空时返回空列表。
7. 9000 reply-suggestion 代理 `_build_allowed_category_keys()` 直接读取绑定表并去重，不自动追加 `base`。
8. P1-AGENT-KB-DISABLE-RAG-SAFE-FIX-1 后，9000 在 reply-suggestion / Agent 预览 / 自动回复 dry-run 请求中显式注入 `agent_config.rag_enabled`；当绑定为空时为 `false`。
9. P1-AGENT-KB-DISABLE-RAG-SAFE-FIX-1 后，9100 收到 `rag_enabled=false` 或 `allowed_category_keys=[]` 时跳过 RAG 检索，`source_chunks=[]`、`rag_used=false`、`rag_sources=[]`，继续走 direct LLM 回复生成。
10. 分类绑定有 merchant_id 隔离：只允许 `base` 或当前商户 active 的 `KnowledgeCategory`；其他商户、disabled、deleted、missing 分类会被拒绝。
11. 前端伪造 `allowed_category_keys` 不影响正式 reply-suggestion：测试断言 9000 会忽略请求体伪造值，改用绑定表。
12. 代码中 `auto_wechat:knowledge` / `auto_wechat:knowledge_training` 仍出现在 mock 权限和历史记录里，只能按历史 / 过渡 / 待清理处理，不是 NewCar 正式商户权限码。

### 10.5 是否属于知识库管理

结论：`/agents/{agent_id}/knowledge-categories` 当前不是知识库内容管理入口，而是 Agent 消费知识分类的范围配置入口。

依据：

1. 它只写 `agent_knowledge_categories`。
2. 它不调用 9100 `/rag/documents`、`/rag/train`、`/rag/search`。
3. 它不写 `knowledge_documents`、`knowledge_chunks` 或 9100 RAG 数据。
4. 它会影响正式回复建议链路的 `allowed_category_keys`。

但存在产品表达风险：前端文案多处使用“智能体知识库”“训练预览”“维护提示词和知识库”，商户容易理解为自己可以管理知识库内容。若最终允许商户配置消费范围，应改为“回复知识范围 / AI 客服知识范围 / 可使用知识分类”。

### 10.6 风险点

1. 商户误以为在管理知识库：`/agents` 页面文案仍偏“知识库”而不是“消费范围”。
2. 商户取消 `base` 后的“空分类查全库”风险已由 P1-AGENT-KB-DISABLE-RAG-SAFE-FIX-1 收口：空绑定会显式禁用 RAG，不再查全库。
3. 商户可以绑定 / 解绑已有分类；这是否属于产品允许的“消费范围配置”尚未确认。
4. 分类绑定本身有 merchant_id 隔离，但 `base` 是全局允许项；如果 base 是否必选还未决策，需避免前端给出“可随意关闭统一知识库”的暗示。
5. 历史知识库页面和 `searchRag()` 直连 9100 的代码仍存在，当前正式路由不触达；后续清理前不要恢复为正式入口。
6. `auto_wechat:ai_agents` 在代码注释中写为“正式 NewCarProject 权限字典应补”，但本轮未取得上游确认；当前只能记录为项目内历史/过渡兼容事实，不应当作已确认上游权限。
7. 测试仍覆盖“base 可取消”；本轮已将“9100 空分类不过滤”的旧断言改为“空分类禁用 RAG”。

### 10.7 产品决策候选方案

说明：以下 A / B / C 是本只读审计阶段的候选命名；P1-AGENT-KB-DISABLE-RAG-SAFE-FIX-1 的最终产品口径以第 11 节为准。

方案 A：允许商户配置 Agent 消费分类。

1. 允许商户选择“AI 客服可使用哪些管理员知识分类”。
2. 不允许商户新增、编辑、删除知识分类。
3. 前端文案改为“回复知识范围 / AI 客服知识范围 / 可使用知识分类”。
4. 权限建议归属抖音 AI 客服使用能力，即 `auto_wechat:douyin_ai_cs`，不要使用 `auto_wechat:knowledge`。
5. 当前已确认允许商户关闭知识库；关闭后 `allowed_category_keys=[]` 表示禁用 RAG，不表示“不限分类”。

方案 B：不允许商户配置消费分类。

1. 隐藏 Agent 分类勾选 UI。
2. 后端绑定接口禁用，或仅管理员 / 内部可用。
3. 统一由管理员配置知识分类和 Agent 消费范围。
4. 商户只看到“小高知识库已启用”之类状态。

方案 C：保留历史能力但暂不展示。

1. 后端保留绑定能力。
2. 前端隐藏分类勾选入口。
3. 文档标为历史 / 过渡能力。
4. 后续等产品确认后再开放。

### 10.8 推荐下一步任务名

```text
P1-AGENT-KB-CATEGORY-CONSUMPTION-POLICY-CONFIRM-1
P1-FRONTEND-AGENT-KB-COPY-CLEANUP-1
P1-FRONTEND-KNOWLEDGE-LEGACY-CLEANUP-1
```

## 11. P1-AGENT-KB-DISABLE-RAG-SAFE-FIX-1 修复记录

### 11.1 产品最终语义

本轮采用用户确认后的关闭知识库口径：

1. 商户可以选择关闭知识库。
2. 关闭知识库后仍然可以生成回复。
3. 关闭知识库后仍然允许自动发送，但是否自动发送继续由既有自动发送安全门禁决定。
4. 关闭知识库时必须明确不走 RAG / 不检索小高知识库。
5. `allowed_category_keys=[]` 不得解释为查全库。

### 11.2 修复位置

1. `app/routers/douyin_ai_cs_proxy.py`：正式商户 AI 客服 reply-suggestion 代理在 `agent_config` 中注入 `rag_enabled=bool(allowed_category_keys)`。
2. `app/routers/agents.py`：Agent 预览链路同步注入 `rag_enabled`。
3. `app/services/ai_auto_reply_dry_run_service.py`：自动回复 dry-run 链路同步注入 `rag_enabled`。
4. `apps/xg_douyin_ai_cs/schemas.py`：`AgentConfig` 增加 `rag_enabled` 可选字段。
5. `apps/xg_douyin_ai_cs/services/reply_decision_service.py`：9100 在 `rag_enabled=false` 或显式空分类时跳过 RAG 搜索，后续继续 direct LLM 生成。

### 11.3 行为结果

| 场景 | 行为 |
|---|---|
| Agent 绑定 `base` 或其他分类 | `rag_enabled=true`，9100 按 `category_keys` 过滤检索。 |
| Agent 未绑定任何分类 | `rag_enabled=false`，9100 不执行 RAG 检索。 |
| 商户取消 `base` / 小高知识库 | `allowed_category_keys=[]`，表示关闭知识库，不会查全库。 |
| 关闭知识库后生成回复 | 继续走 direct LLM / no RAG 路径，`source_chunks=[]`、`rag_used=false`。 |
| 自动发送安全门禁 | 本轮不修改 `DOUYIN_AUTO_REPLY_ENABLED`、真实发送开关、账号开关、白名单、`manual_required`、24h、`send_context`、`manual_confirmed` 等既有条件。 |

### 11.4 测试记录

已新增 / 更新测试覆盖：

1. `tests/test_douyin_ai_cs_proxy.py::test_proxy_disables_rag_when_agent_has_no_category_binding`
2. `tests/test_douyin_ai_cs_proxy.py::test_proxy_ignores_forged_allowed_category_keys_from_payload`
3. `tests/test_xg_douyin_ai_cs_app.py::test_reply_suggestion_empty_allowed_category_keys_disables_rag`
4. `tests/test_ai_agents.py` 中 Agent 预览请求断言 `rag_enabled=true`
5. `tests/test_ai_auto_reply_dry_run.py` 中自动回复 dry-run 空绑定断言 `rag_enabled=false`

聚焦红绿验证结论：

```text
python -m pytest tests/test_xg_douyin_ai_cs_app.py::test_reply_suggestion_empty_allowed_category_keys_disables_rag -q
1 passed

python -m pytest tests/test_douyin_ai_cs_proxy.py::test_proxy_disables_rag_when_agent_has_no_category_binding tests/test_douyin_ai_cs_proxy.py::test_proxy_ignores_forged_allowed_category_keys_from_payload -q
2 passed

python -m pytest tests/test_ai_agents.py -q
11 passed

python -m pytest tests/test_ai_auto_reply_dry_run.py -q
36 passed
```
