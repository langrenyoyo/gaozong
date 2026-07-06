# Phase 3-F-A 抖音AI小高客服能力服务迁移只读评审

更新时间：2026-06-22

## 1. 本轮范围

本轮只读审计“抖音AI小高客服”当前 9000 / 9100 / 9201 / frontend 调用链，评估后续迁入 9201 `douyin-cs` 服务的边界。

本轮不修改代码、不提交、不迁移私信发送、不修改 `manual_confirmed=true`、不修改 `auto_send=false`、不修改 19000 / `input_writer` / 微信 UI 自动化、不修改 webhook、不修改 sync-leads、不修改 DB model / migration、不修改 NewCarProject/auth、不修改前端页面行为、不修改 9100 RAG / reply-suggestion 业务语义。

## 2. 当前调用链

### 2.1 工作台主链路

```text
frontend DouyinAiCsWorkbenchPage
  -> frontend/src/api/douyinAiCsClient.ts
  -> 9000 /integrations/douyin/accounts
  -> 9000 /integrations/douyin/accounts/{account_id}/conversations
  -> 9000 /integrations/douyin/conversation-messages
  -> 9000 /integrations/douyin/accounts/{account_id}/conversations/{conversation_key}/profile
  -> 9000 /integrations/douyin-ai-cs/accounts/{account_open_id}/agents
  -> 9000 /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion
  -> 9100 /douyin/conversations/{conversation_id}/reply-suggestion
```

事实依据：

- `frontend/src/api/douyinAiCsClient.ts` 中工作台账号、会话、消息、画像、Agent 列表、可信 reply-suggestion 均走 9000。
- `app/routers/integrations.py` 提供会话、消息、画像 read-only 聚合接口。
- `app/routers/douyin_ai_cs_proxy.py` 提供 9000 到 9100 的可信 reply-suggestion / RAG 代理。

### 2.2 私信发送与资源链路

```text
frontend DouyinAiCsWorkbenchPage
  -> 9000 /integrations/douyin/live-check/messages/send
  -> douyin_private_message_send_service.send_manual_private_message()
  -> douyin_workbench_conversation_service.get_send_msg_context()
  -> douyin OpenAPI /send_msg
  -> douyin_private_message_sends 写发送流水
```

资源下载 / 图片上传：

```text
frontend
  -> 9000 /integrations/douyin/live-check/resources/download
  -> douyin_resource_download_service.download_douyin_resource()

frontend
  -> 9000 /integrations/douyin/live-check/resources/upload-image
  -> douyin_image_upload_service.upload_douyin_image()
```

### 2.3 AI 自动回复 dry-run 链路

```text
9000 webhook / internal webhook result
  -> 9000 run_ai_auto_reply_dry_run(event_id)
  -> resolve_webhook_bound_agent()
  -> get_account_autoreply_settings()
  -> build_conversation_history()
  -> 9000 注入 agent_config / allowed_category_keys
  -> 9100 reply-suggestion
  -> 9000 强制 final auto_send=false
  -> ai_reply_decision_logs / ai_auto_reply_runs
```

注意：`app/services/ai_auto_reply_send_service.py` 已存在真实自动发送代码路径，但本轮评审结论是 read-only 迁移阶段不得触碰该链路，私信发送必须单独阶段评审。

## 3. 当前路由清单

### 3.1 9000 抖音客服 / 企业号 / 会话相关路由

`app/routers/integrations.py`：

- `GET /integrations/douyin/accounts/{account_id}/conversations`
- `GET /integrations/douyin/conversations/{conversation_key}/messages`
- `GET /integrations/douyin/accounts/{account_id}/conversations/{conversation_key}/profile`
- `GET /integrations/douyin/conversation-messages`
- `POST /integrations/douyin/sync-leads`
- `POST /integrations/douyin/webhook`

其中会话、消息、画像属于工作台 read-only 候选；sync-leads 与 webhook 不属于 Phase 3-F 迁移范围。

`app/routers/douyin_accounts.py`：

- `GET /integrations/douyin/accounts`
- `PUT /integrations/douyin/accounts/{account_open_id}/agent-binding`
- `DELETE /integrations/douyin/accounts/{account_open_id}/agent-binding`
- `POST /integrations/douyin/accounts/{account_open_id}/cancel-authorization`
- `DELETE /integrations/douyin/accounts/{account_open_id}`

其中 `GET /integrations/douyin/accounts` 可作为 read-only 迁移候选；绑定、解绑、取消授权、删除账号属于写操作，建议继续留在 9000。

`app/routers/douyin_ai_cs_proxy.py`：

- `POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`
- `POST /integrations/douyin-ai-cs/rag/documents`
- `POST /integrations/douyin-ai-cs/rag/train`
- `GET /integrations/douyin-ai-cs/accounts/{account_open_id}/agents`

其中 `GET /accounts/{account_open_id}/agents` 是 agent 绑定读取候选；reply-suggestion、RAG 文档创建和训练继续留在 9000 代理。

`app/routers/douyin_live_check.py`：

- `GET /integrations/douyin/live-check/auth-url`
- `GET /integrations/douyin/live-check/oauth-callback`
- `GET /integrations/douyin/live-check/auth-redirect`
- `GET /integrations/douyin/live-check/status`
- `GET /integrations/douyin/live-check/accounts`
- `POST /integrations/douyin/live-check/accounts/sync-bind-info`
- `POST /integrations/douyin/live-check/accounts/bind-authorized-open-id`
- `POST /integrations/douyin/live-check/messages/send`
- `POST /integrations/douyin/live-check/resources/download`
- `POST /integrations/douyin/live-check/resources/upload-image`
- `POST /integrations/douyin/live-check/webhook-observe`
- `POST /integrations/douyin/live-check/callback`

授权、同步、绑定、发送、资源、webhook observe/callback 均不建议混入 read-only 迁移。

### 3.2 9100 路由

`apps/xg_douyin_ai_cs/main.py` 注册：

- health
- categories
- accounts
- conversations
- ai_reply
- rag
- knowledge_training

关键接口：

- `GET /douyin/accounts`
- `GET /douyin/accounts/{account_id}/agents`
- `GET /douyin/accounts/{account_id}/conversations`
- `GET /douyin/conversations/{conversation_id}/messages`
- `GET /douyin/conversations/{conversation_id}/profile`
- `POST /douyin/conversations/{conversation_id}/reply-suggestion`
- `POST /rag/documents`
- `POST /rag/train`
- `POST /rag/search`
- `POST /knowledge-training/ask`
- `POST /knowledge-training/{training_id}/feedback`

9100 的 accounts / conversations 当前仍主要是 mock workbench 能力；正式工作台主链路已经转向 9000 聚合真实 webhook 事件。

### 3.3 9201 现有骨架

`apps/douyin_cs` 当前只有能力服务骨架：

- `main.py`：通过 `create_capability_app(META, router)` 创建应用。
- `router.py`：只注册通用 capability router。
- `service.py`：只定义 `CapabilityMeta(service="douyin_cs", name="抖音AI小高客服", ...)`。
- `schema.py`：只导出通用 `CapabilityRoot` / `CapabilityStatus`。

结论：9201 目前尚无业务 router / services / schemas / dependencies，适合从 read-only 内部 API 开始补齐，不适合直接承接发送、授权或 AI 自动回复。

## 4. 当前服务清单

9000 关键服务：

- `douyin_workbench_conversation_service.py`：从 `douyin_webhook_events` / `douyin_leads` 聚合企业号、会话、消息、客户画像、发送上下文。
- `douyin_private_message_send_service.py`：人工确认后发送私信，写 `douyin_private_message_sends`。
- `douyin_account_agent_binding_service.py`：企业号与 Agent 绑定、解绑、校验、webhook 绑定解析。
- `xg_douyin_ai_cs_client.py`：9000 调用 9100 的可信客户端。
- `douyin_ai_cs_binding_service.py`：reply-suggestion 前置绑定校验。
- `douyin_conversation_history_service.py`：为 9100 构造可信 conversation history。
- `ai_auto_reply_dry_run_service.py`：webhook 后台 dry-run 编排。
- `ai_auto_reply_send_service.py`：真实自动发送执行，暂缓迁移。

9100 关键服务：

- `reply_decision_service.py`：RAG / LLM / 规则回复建议，固定返回 `auto_send=false`。
- `rag.repository`：知识库文档、训练、检索。
- `knowledge_training_service.py`：知识库训练问答与反馈。
- `mock_workbench_service.py`：demo 账号、会话、消息能力。

## 5. 9000 / 9100 / 9201 职责边界

### 5.1 9000 gateway 必须保留

9000 当前是可信上下文与权限边界：

- 读取 `RequestContext`。
- 校验 `auto_wechat:douyin_ai_cs` 权限。
- 注入 `merchant_id`。
- 校验企业号归属。
- 校验 Agent 归属和绑定关系。
- 注入真实 `agent_config`。
- 注入 `allowed_category_keys`。
- 记录 AI 回复决策日志。
- 最终强制 `auto_send=false`。
- 保留人工发送与授权高风险边界。

### 5.2 9100 继续作为 RAG / LLM 能力服务

9100 继续负责：

- reply-suggestion 计算。
- RAG 搜索、文档、训练。
- 结构化回复建议。

9100 不应直接暴露给前端作为正式产品入口；前端直连 9100 的函数只能保留为测试 / demo，不应进入工作台主链路。

### 5.3 9201 建议定位

9201 `douyin-cs` 建议先成为抖音客服 read-only 能力服务：

- 会话列表 read-only。
- 消息列表 read-only。
- 客户画像 read-only。
- 企业号列表 read-only。
- Agent 绑定读取 read-only。

9201 首阶段不承接：

- 私信发送。
- 图片上传。
- 资源下载。
- 授权 / OAuth callback。
- 绑定、解绑、取消授权、删除账号。
- reply-suggestion 的可信代理。
- AI 自动回复 dry-run / auto-reply run。

## 6. 可先迁移的 read-only 能力

建议 F-B 只迁 read-only internal API：

- 企业号列表：从 `GET /integrations/douyin/accounts` 拆出只读能力。
- 会话列表：从 `GET /integrations/douyin/accounts/{account_id}/conversations` 拆出只读能力。
- 消息列表：从 `GET /integrations/douyin/conversation-messages` 拆出只读能力。
- 客户画像：从 `GET /integrations/douyin/accounts/{account_id}/conversations/{conversation_key}/profile` 拆出只读能力。
- Agent 绑定读取：从 `GET /integrations/douyin-ai-cs/accounts/{account_open_id}/agents` 拆出只读能力。

迁移方式建议：

- 9201 提供 internal read-only API。
- 9000 继续作为前端入口。
- 9000 在 F-C 再通过开关可配置代理到 9201。
- 9201 不直接接受浏览器可信身份，不直接替代 9000 的 RequestContext 权限边界。

## 7. 暂缓迁移的高风险能力

以下能力必须暂缓迁移：

- 私信发送：`POST /integrations/douyin/live-check/messages/send`。
- 图片上传：`POST /integrations/douyin/live-check/resources/upload-image`。
- 资源下载：`POST /integrations/douyin/live-check/resources/download`。
- AI 自动回复 dry-run：`run_ai_auto_reply_dry_run()`。
- AI 自动回复真实发送：`send_ai_auto_reply_for_run()`。
- AI 自动回复运行记录与托管状态变更。
- 企业号授权 URL、OAuth callback、auth-redirect。
- 企业号绑定授权 open_id。
- 企业号绑定 / 解绑 Agent。
- 取消授权。
- 删除企业号。
- webhook observe / callback / formal webhook。
- sync-leads。

原因：

- 这些能力涉及第三方 OpenAPI、授权、状态写入、发送动作、资源处理、审计日志和自动化安全边界。
- 它们依赖 9000 的 RequestContext、商户隔离、现有审计表和发送门禁。
- 与 read-only 会话/消息迁移混在同一阶段会扩大回归面。

## 8. 私信发送安全边界

`app/services/douyin_private_message_send_service.py` 当前边界：

- `send_manual_private_message()` 要求 `manual_confirmed is True`，否则返回 400。
- 人工发送路径调用 `_send_private_message_with_context(... manual_confirmed=True, auto_send=False, send_source="manual")`。
- 发送前必须通过 `get_send_msg_context()` 找到可回复的前置客户消息上下文。
- `get_send_msg_context()` 排除 `im_send_msg` 企业号自己发出的消息，避免拿企业号发送回执作为回复 `msg_id`。
- 发送上下文必须包含 `conversation_id` 与 `msg_id`。
- `msg_id` 超过 24 小时会拒绝发送。
- `scene` 由后端 `_default_scene()` 根据前置事件推导；`im_enter_direct_msg` 保留，否则默认为 `im_reply_msg`。
- 发送日志对 `conversation_short_id`、`server_message_id` 做 hash 前缀脱敏，不记录明文 open_id / message_id / conversation_id / secret / 完整 body / Authorization。
- 发送成功后写 `douyin_private_message_sends`，并调用 `mark_manual_takeover()` 标记人工接管。

注意：`_send_private_message_with_context()` 也被 `ai_auto_reply_send_service.py` 调用，并可传入 `manual_confirmed=False, auto_send=True`。这属于后续自动发送高风险能力，不得在 F-B read-only 迁移中触碰。

## 9. AI建议 / AI自动回复边界

### 9.1 reply-suggestion 当前由谁调用

正式工作台调用链：

```text
frontend getTrustedReplySuggestion()
  -> 9000 POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion
  -> 9000 XgDouyinAiCsClient.suggest_reply()
  -> 9100 POST /douyin/conversations/{conversation_id}/reply-suggestion
```

前端仍保留 `getReplySuggestion()` 直连 9100 的函数，但工作台主链路使用的是 `getTrustedReplySuggestion()`。

### 9.2 9000 注入的可信上下文

9000 在 reply-suggestion 中注入：

- `tenant_id` / `source_system`
- `merchant_id`
- `douyin_account_id`
- `account_open_id`
- `agent_id`
- 真实 `agent_config`
- `agent_config.allowed_category_keys`
- `conversation_history`

9000 同时执行：

- `require_permission("auto_wechat:douyin_ai_cs")`
- `validate_douyin_agent_binding()`
- `get_agent()` 并校验 Agent active
- `build_conversation_history()`
- `record_ai_reply_decision()`
- 将 9100 返回的 `auto_send` 强制改为 `False`

结论：9201 不应在首阶段直接调用 9100 替代 9000。reply-suggestion 必须继续由 9000 gateway 代理，除非后续 9201 完整具备 RequestContext、商户权限、企业号归属、Agent 绑定、分类权限、决策日志和 `auto_send=false` 后置门禁。

## 10. 企业号授权 / 绑定 / 删除账号边界

以下能力应继续留在 9000：

- 授权 URL 生成。
- OAuth callback 观察。
- auth-redirect 后同步企业号并跳转前端。
- 绑定授权 open_id 到当前商户。
- Agent 绑定。
- Agent 解绑。
- 取消授权。
- 删除企业号。

理由：

- 这些操作依赖 `RequestContext.merchant_id`。
- 绑定逻辑必须阻止跨商户绑定。
- 删除 / 取消授权会更新 `douyin_authorized_accounts` 和 `douyin_account_agent_bindings`。
- 上游取消授权目前 `upstream_cancel_supported=false`，需要在 9000 保留本地审计语义。

## 11. Leads 深链接影响评估

当前工作台支持从 URL 读取：

```text
/douyin-ai-cs?account_open_id=...&conversation_short_id=...&open_id=...
```

同时前端路由层已有旧路径重定向：

```text
/douyin-ai-cs -> /douyin-cs/workbench
```

`DouyinAiCsWorkbenchPage` 会读取：

- `account_open_id`
- `conversation_short_id`
- `open_id`

并用于选中企业号与会话。

结论：

- 只迁 read-only internal API 不应影响 deep link。
- 9000 前端入口不变，旧链接继续由前端重定向到 `/douyin-cs/workbench`。
- F-C 代理到 9201 时必须透传 `account_open_id`、`conversation_short_id`、`open_id` 的筛选语义。
- 9201 read-only API 的响应必须保持现有 `conversation_key` / `conversation_short_id` / `open_id` 字段兼容，避免 leads 深链接无法定位会话。

## 12. 分阶段迁移计划

### F-A：只读评审

本阶段只输出文档，不改代码。

交付：

- 当前调用链。
- 路由与服务清单。
- 9000 / 9100 / 9201 边界。
- read-only 迁移候选。
- 高风险暂缓清单。
- 测试与回滚建议。

### F-B：9201 read-only 会话 / 消息能力

建议只新增 9201 internal read-only API：

- accounts list
- conversations list
- messages list
- profile
- account agents read

约束：

- 不接私信发送。
- 不接资源上传 / 下载。
- 不接授权 / 绑定写操作。
- 不接 reply-suggestion。
- 不接 AI 自动回复 dry-run / run。
- 不改前端工作台入口。
- 不改 9000 默认行为。

### F-C：9000 可配置代理到 9201

在 9000 增加默认关闭的代理开关。

建议配置形态：

```text
DOUYIN_CS_INTERNAL_ENABLED=false
DOUYIN_CS_FALLBACK_LOCAL=true
DOUYIN_CS_SERVICE_BASE_URL=http://auto-wechat-douyin-cs:9201
DOUYIN_CS_INTERNAL_TOKEN=<secret>
```

默认关闭时继续走 9000 本地 read-only 聚合。

开启时：

- 9000 校验 RequestContext 和权限。
- 9000 调用 9201 internal read-only。
- 9201 只返回只读数据。
- 9201 异常时 fallback 到 9000 本地聚合。

### F-D：灰度验收

按账号和环境灰度：

- 默认关闭部署。
- staging 开启 read-only internal。
- 验证账号列表、会话列表、消息列表、画像、Agent 读取。
- 验证 leads 深链接。
- 验证 fallback。
- 验证发送、授权、reply-suggestion、AI 自动回复仍走原链路。

### 私信发送单独阶段

私信发送不得混入 read-only 迁移。

单独阶段必须重新评审：

- `manual_confirmed=true`
- `auto_send=false`
- 只引用客户消息 `server_message_id`
- `scene` 后端推导
- 24 小时 msg_id 过期
- 人工接管状态
- 自动发送相关 `send_enabled` / `dry_run_enabled` / gate
- 上游 OpenAPI 失败和幂等

## 13. 必须保留的测试

F-B / F-C 后必须保留并扩展：

- `tests/test_douyin_live_check.py`
- `tests/test_douyin_ai_cs_proxy.py`
- `tests/test_douyin_workbench_conversation_service.py`
- `tests/test_leads_management.py`
- `tests/test_leads_app.py`
- `tests/test_auth_context.py`
- 9201 capability 边界测试。
- read-only internal 成功 / fallback / 404 / 403 测试。
- deep link 字段兼容测试。
- 发送接口不被 9201 代理的测试。
- reply-suggestion 仍由 9000 注入可信上下文的测试。

测试重点：

- 9000 仍保留 RequestContext / merchant_id / 权限边界。
- 前端不向 9201 直传可信 scope 字段。
- 9100 reply-suggestion 不直接暴露给正式前端。
- 9201 只读 API 不写 DB。
- fallback 后响应结构与旧工作台兼容。

## 14. 回滚方案

F-B 如仅新增 9201 read-only API：

- 不切 9000 流量即可回滚。
- 停止或忽略 9201 新接口。
- 无需 DB 回滚。

F-C 如 9000 增加代理开关：

```text
DOUYIN_CS_INTERNAL_ENABLED=false
重启 9000
保持前端入口不变
保持 9100 reply-suggestion 不变
不修改 DB
不停止 9201
```

回滚后确认：

- 账号、会话、消息、画像仍由 9000 本地聚合返回。
- reply-suggestion 仍由 9000 代理到 9100。
- 发送、上传、下载、授权仍留在 9000。
- leads 深链接仍能定位企业号与会话。

## 15. 多视角评审结论

技术视角：

- 9201 当前只有 capability 骨架，不具备直接承接高风险能力的基础。
- read-only 聚合接口是最小可迁移切片，适合先建立 9201 服务边界。
- reply-suggestion 依赖 9000 注入可信上下文，不应直接搬到 9201。

产品视角：

- 工作台用户最敏感的是会话、消息、画像能稳定打开，read-only 迁移不会改变操作体验。
- 发送、授权、绑定等操作一旦迁移失误会直接影响客服工作台可用性和账号安全，应单独灰度。
- deep link 必须保持兼容，否则 leads 到客服工作台的跳转会失效。

安全视角：

- 9000 仍是可信边界，不能让前端直接决定 `merchant_id`、`agent_config`、`allowed_category_keys` 或 `auto_send`。
- 9100 不应作为正式前端直连服务。
- 9201 首阶段必须保持 read-only，不接触私信发送、资源、OAuth、webhook 和自动回复发送。

## 16. 本轮结论

Phase 3-F 后续建议：

1. 第一阶段只迁 read-only。
2. 私信发送不混迁。
3. 9000 继续保留可信 RequestContext / merchant_id / 权限边界。
4. 9100 reply-suggestion 不直接暴露给正式前端。
5. 不影响 leads 深链接和现有工作台入口。
6. 9201 先补 read-only internal API，再由 9000 通过默认关闭开关灰度代理。
