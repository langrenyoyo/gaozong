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
