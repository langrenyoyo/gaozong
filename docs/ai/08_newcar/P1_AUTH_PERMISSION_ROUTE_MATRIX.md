# P1 后端权限路由矩阵

更新时间：2026-07-02

## 1. 本轮目标

把 NewCarProject 外部 token 登录后的业务接口权限边界整理成可执行矩阵，并记录本轮已经补齐的最小后端门禁。

本轮只收口 9000 后端权限现状和第一轮补丁，不改前端 direct exchange-code，不改 19000，不改微信自动化，不改抖音自动发送。

## 2. 已确认对接事实

来源：`docs/external-auth-integration.md`、本地代码、联调验证记录。

- NewCarProject 后端联调地址：`http://192.168.110.19:8790`
- NewCarProject 登录页：`http://192.168.110.19:5174/login`
- auto_wechat 前端：`http://192.168.110.113:5173`
- 登录后工作台目标页：`/douyin-cs/workbench?code=xxx&source=new_car_project`
- 前端直接调用 NewCarProject：`POST /api/external-auth/exchange-code`
- 9000 后端只校验 `Authorization: Bearer <token>`，并生成可信 `RequestContext`
- 不恢复 9000 `/auth/callback` 代换 code
- 业务接口不信任前端传入的 `merchant_id`

## 3. 正式权限码来源

`docs/external-auth-integration.md` 当前列出的外部权限码包括：

| 权限码 | 含义 |
| --- | --- |
| `auto_wechat:use` | 进入外部系统 |
| `auto_wechat:douyin_ai_cs` | 抖音 AI 小高客服 |
| `auto_wechat:leads` | AI 小高线索 |
| `auto_wechat:agent` | 小高 AI 微信助手 |
| `auto_wechat:compute` | 小高算力 |
| `auto_wechat:admin:forbidden_words` | 外部违禁词管理 |
| `auto_wechat:admin:accounts` | 外部账号管理 |
| `auto_wechat:admin:ai_reply_records` | AI 回复记录 |
| `auto_wechat:admin:compute_config` | 算力配置管理 |

代码中还存在历史兼容权限，例如 `auto_wechat:ai_agents`、`auto_wechat:knowledge`、`auto_wechat:knowledge_training`、`auto_wechat:wechat_agent`、`auto_wechat:wechat_assistant`。这些只能视为当前代码兼容项，不能当作上游正式权限码。

## 4. 认证与商户上下文

当前入口在 `app/auth/dependencies.py`：

- `/auth/me` 使用 `get_request_context_required`
- 真实 NewCarProject token 由 `NewCarProjectAuthClient.introspect_token()` 调上游 `/api/external-auth/me`
- 缺少 `auto_wechat:use` 时返回 `PERMISSION_DENIED`
- 非 mock 真实模式下会走本地 `external_merchant_bindings` 解析
- 命中本地绑定后，`RequestContext.merchant_id` 和 `merchant_ids` 使用本地可信商户
- 未绑定时返回 `EXTERNAL_MERCHANT_NOT_BOUND`

## 5. 当前路由权限矩阵

| 模块 | 接口范围 | 当前后端校验 | 当前权限码 | 备注 |
| --- | --- | --- | --- | --- |
| 登录态 | `GET /auth/me` | 是 | `auto_wechat:use` + 本地商户绑定 | 统一恢复登录态和可信 `merchant_id` |
| 抖音 AI 客服 | `/integrations/douyin-ai-cs/*` | 是 | `auto_wechat:douyin_ai_cs` | reply-suggestion、RAG documents/train、账号 agent 查询 |
| 抖音企业号管理 | `/integrations/douyin/accounts/*` | 是 | `auto_wechat:douyin_ai_cs` | 账号列表、Agent 绑定、取消授权、删除 |
| 抖音自动回复配置 | `/douyin-autoreply/settings/*` | 是 | `auto_wechat:douyin_ai_cs` | 配置、模式、托管相关接口仍保持 `auto_send=false` 边界 |
| AI 回复记录 | `/ai-reply-decision-logs/*` | 是 | `auto_wechat:douyin_ai_cs` | 商户侧只读记录 |
| 自动回复运行记录 | `/ai-auto-reply-runs/*` | 是 | `auto_wechat:douyin_ai_cs` | 商户侧运行记录 |
| AI 小高线索 | `/leads/*` | 是 | `auto_wechat:leads` | 通过 `lead_management_service.require_leads_context()` 校验权限和商户上下文 |
| 报表 | `/reports/summary` | 是 | `auto_wechat:leads` | 同样复用 `require_leads_context()` |
| 旧同步线索 | `POST /integrations/douyin/sync-leads` | 本轮已补 | `auto_wechat:leads` | 保留旧同步链路，但不作为 webhook 归属 |
| 原始事件查询 | `/webhook-events/*` | 本轮已补 | `auto_wechat:leads` | 只读查看原始 webhook/invalid 事件 |
| 通知记录 | `GET /lead-notifications/records` | 本轮已补 | `auto_wechat:leads` | 已保留原有 merchant_id 隔离 |
| 抖音现场联调账号 | `GET /integrations/douyin/live-check/accounts`、`POST /integrations/douyin/live-check/accounts/sync-bind-info` | 第二轮已补 | `auto_wechat:douyin_ai_cs` | 仅补浏览器业务入口；OAuth/Webhook 回调未套浏览器登录态 |
| 抖音现场联调发送/资源 | `POST /integrations/douyin/live-check/messages/send`、`POST /integrations/douyin/live-check/resources/download`、`POST /integrations/douyin/live-check/resources/upload-image` | 第二轮已补 | `auto_wechat:douyin_ai_cs` | 只在进入原 service 前加门禁，未改变 manual_confirmed、send_context、24h 等原安全检查 |
| 回复检测记录 | `GET /checks` | 第二轮已补 | `auto_wechat:leads` | 按 `DouyinLead.merchant_id` 使用可信 RequestContext 做查询隔离；`POST /checks/run` 仍按历史调试/自动化入口待确认 |
| 发送给销售 | `POST /lead-notifications/send-to-staff` | 是 | `auto_wechat:leads` + `auto_wechat:agent` | 既访问线索，也创建微信助手任务 |
| 销售管理 | `/staff/*` | 是 | `auto_wechat:agent` | 小高 AI 微信助手销售配置 |
| 微信任务 | `/wechat-tasks/*` | 是 | `auto_wechat:agent` | 任务队列与结果回写，仍不代表放开自动发送 |
| Agent | `/agents/*` | 是 | `auto_wechat:ai_agents` 或 `auto_wechat:agent` | `auto_wechat:ai_agents` 为历史兼容，正式权限需按上游字典收口 |
| 知识分类 | `/knowledge-categories/*` | 是 | `auto_wechat:ai_agents` 或 `auto_wechat:agent` | 同上，当前与 Agent 管理绑定 |
| 商户算力 | `/compute/*` | 是 | `auto_wechat:compute` 或 `auto_wechat:agent` | `auto_wechat:agent` 为过渡兼容 |
| 超管算力 | `/admin/compute/*`、`/admin/merchants/*/compute/*` | 是 | `super_admin` | 当前代码不是 `auto_wechat:admin:compute_config` |
| 内部算力消耗 | `POST /internal/compute/usage` | 是 | `X-Internal-Token` 或开发放行 | 不是 NewCar 外部权限入口 |

## 6. 本轮未动的待确认入口

这些入口不能一刀切加 NewCar 外部权限，需要先区分业务入口、回调入口、调试入口或 Local Agent 内部入口：

| 接口/文件 | 当前判断 | 待确认点 |
| --- | --- | --- |
| `app/routers/douyin_live_check.py` | 混合业务、授权、状态、回调入口 | 需要拆出登录页/OAuth 回调/公开 observe/callback/业务发送下载上传接口 |
| `app/routers/checks.py` | 历史检测接口 | 是否仍对商户前端开放，还是仅 demo/内部 |
| `app/routers/replies.py` | 历史回复检测与 agent-write-back | 是否属于 Local Agent 内部回写，而不是 NewCar 商户权限 |
| `app/routers/agent.py` | Local Agent 心跳/状态 | 更适合内部 agent token 或本机边界，不应直接套外部商户权限 |
| `app/routers/lead_notifications.py` | 旧 Windows 专用通知入口 | 是否下线、归档或只允许内部调用 |
| webhook 回调入口 | `/webhook/douyin`、`/integrations/douyin/webhook` | webhook 应使用签名校验，不应要求 NewCar 浏览器 token |

## 7. 本轮补丁

已补三个明确业务数据入口：

1. `POST /integrations/douyin/sync-leads`
   - 新增登录态依赖
   - 新增 `auto_wechat:leads` 校验

2. `GET /lead-notifications/records`
   - 新增 `auto_wechat:leads` 校验
   - 保留原有 merchant_id 隔离

3. `GET /webhook-events` 和 `GET /webhook-events/{event_id}`
   - 新增登录态依赖
   - 新增 `auto_wechat:leads` 校验

## 8. 测试覆盖

已补权限回归：

- `tests/test_douyin_sync.py`
  - 有 `auto_wechat:leads` 可访问
  - 无 `auto_wechat:leads` 返回 `403 PERMISSION_DENIED`

- `tests/test_lead_notification_records_route.py`
  - 无 `auto_wechat:leads` 返回 `403 PERMISSION_DENIED`

- `tests/test_webhook_events.py`
  - 列表无 `auto_wechat:leads` 返回 `403 PERMISSION_DENIED`
  - 详情无 `auto_wechat:leads` 返回 `403 PERMISSION_DENIED`

已执行：

```powershell
python -m pytest tests/test_douyin_sync.py tests/test_lead_notification_records_route.py tests/test_webhook_events.py -q
```

结果：`58 passed, 149 warnings`

## 9. 后续建议

1. 第二轮审计 `douyin_live_check.py`、`checks.py`、`replies.py`、`agent.py`、`lead_notifications.py`，先分类再决定是否补权限。
2. 将 `agents.py`、`knowledge_categories.py` 中的历史兼容权限收口方案单独确认，避免误删现有可用链路。
3. 将超管算力从 `super_admin` 切到 `auto_wechat:admin:compute_config` 之前，先确认 NewCar 外部账号是否承载超管语义。
4. 对权限相关测试做更广回归：`tests/test_auth_context.py`、`tests/test_compute_router.py`、`tests/test_agents_app.py`、`tests/test_douyin_ai_cs_proxy.py`。

## 10. 第二轮混合入口审计

任务名：`P1-BACKEND-MIXED-ENTRYPOINT-AUDIT-1`

审计日期：2026-07-02

本轮只做混合入口分类和风险记录，不改 NewCar exchange-code 流程，不改前端，不改 9100，不改 19000，不改微信自动化，不改抖音自动发送，不恢复 `/auth/callback`。

### 10.1 已扫描文件

| 文件 | 说明 |
| --- | --- |
| `app/routers/douyin_live_check.py` | 抖音现场联调、OAuth 观察、GMP 授权回跳、账号同步、私信发送、资源代理、事件回调混合入口 |
| `app/routers/checks.py` | 历史回复检测查询和手动触发入口 |
| `app/routers/replies.py` | 历史手工回复、旧本机微信检测、Local Agent 回写、微信 UI 调试入口 |
| `app/routers/agent.py` | Local Agent 服务端状态和心跳入口 |
| `frontend/src/api/douyinLiveCheck.ts` | 前端已封装 live-check auth-url/status/accounts/bind 入口 |
| `frontend/src/api/douyinAiCsClient.ts` | 前端已调用 live-check 私信发送、资源下载、图片上传入口 |
| `frontend/src/api/checks.ts` | 前端已调用 `GET /checks` |
| `frontend/src/api/replies.ts` | 前端已调用 `POST /replies/current-wechat-detect` |
| `frontend/src/api/agent.ts` | 前端已调用 `GET /agent/status` |
| `app/services/douyin_live_check_service.py` | 确认部分账号同步/状态逻辑支持 `context.merchant_id` |
| `app/services/douyin_private_message_send_service.py` | 确认发送成功后通过账号绑定反查 `merchant_id` 做人工接管记录，但入口未校验请求者归属 |
| `app/services/douyin_resource_download_service.py` | 确认资源下载按 conversation/open_id 查事件，不接收 `RequestContext` |
| `app/services/douyin_image_upload_service.py` | 确认图片上传按 open_id 调上游，不接收 `RequestContext` |
| `app/services/reply_checker.py` | 确认手工回复、全量检测、检测列表没有 merchant 过滤 |
| `app/services/wechat_ui_reply_service.py` | 确认旧本机微信检测和 agent-write-back 通过 lead_id/staff_id/task_id 回写，不接收 `RequestContext` |
| `app/services/agent_status_service.py` | 确认 `/agent/status` 只读内存心跳和自动化开关，`/agent/heartbeat` 写入内存心跳 |

### 10.2 Route 分类表

| Method | Path | 函数 | 当前认证/权限依赖 | merchant_id 使用 | 前端调用证据 | 分类 | 建议处理 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GET | `/integrations/douyin/live-check/auth-url` | `get_auth_url` | 无，仅 `_ensure_enabled()` | 无 | `frontend/src/api/douyinLiveCheck.ts` 已封装 | 调试/联调授权入口 | 需要人工确认；若商户前端继续可点授权，补 NewCar 登录态 + `auto_wechat:douyin_ai_cs`；若只联调，改内部白名单或隐藏 |
| GET | `/integrations/douyin/live-check/oauth-callback` | `oauth_callback` | 无，仅 `_ensure_enabled()` | 无 | 测试覆盖，未见前端直接调用 | OAuth callback/观察入口 | 不加浏览器登录态；按 OAuth state、来源和回调安全边界处理 |
| GET | `/integrations/douyin/live-check/auth-redirect` | `auth_redirect` | `get_request_context_optional` | optional context 传给 `sync_bind_info_accounts` | 测试覆盖，302 回前端 | OAuth/GMP 授权回跳入口 | 不直接改 required 登录态，避免授权回调断链；需专项确认 state 与商户归属绑定 |
| GET | `/integrations/douyin/live-check/status` | `status` | `get_request_context_optional` | 有 context 时按商户查账号状态，否则用内存观察态 | `frontend/src/api/douyinLiveCheck.ts` 已封装 | 浏览器业务/联调状态混合 | 若面向商户前端，补 NewCar 登录态 + `auto_wechat:douyin_ai_cs`；若仅联调，内部白名单 |
| GET | `/integrations/douyin/live-check/accounts` | `accounts` | 第二轮已加固：`get_request_context_required` + `auto_wechat:douyin_ai_cs` | 无；服务返回持久账号/事件兜底列表 | `frontend/src/api/douyinLiveCheck.ts` 和测试已调用 | 浏览器业务/联调混合 | 已加固入口门禁；后续仍需确认是否只返回当前 merchant 绑定账号 |
| POST | `/integrations/douyin/live-check/accounts/sync-bind-info` | `sync_accounts_bind_info` | 第二轮已加固：`get_request_context_required` + `auto_wechat:douyin_ai_cs` | context 传给 `sync_bind_info_accounts` 写入/保护账号 `merchant_id` | 测试已调用 | 浏览器业务/联调混合 | 已加固入口门禁 |
| POST | `/integrations/douyin/live-check/accounts/bind-authorized-open-id` | `bind_authorized_open_id` | `get_request_context_required` + `auto_wechat:douyin_ai_cs` | 强制使用 `context.merchant_id` | `frontend/src/api/douyinLiveCheck.ts` 已封装 | 浏览器业务接口 | 保持现状 |
| POST | `/integrations/douyin/live-check/messages/send` | `send_message` | 第二轮已加固：`get_request_context_required` + `auto_wechat:douyin_ai_cs` | 入口校验登录态和权限；原 service 仍通过账号绑定反查商户做人工接管记录 | `frontend/src/api/douyinAiCsClient.ts` 已调用 | 浏览器业务/高风险发送接口 | 已加固入口门禁；未改变 manual_confirmed、send_context、24h 等原安全检查 |
| POST | `/integrations/douyin/live-check/resources/download` | `download_resource` | 第二轮已加固：`get_request_context_required` + `auto_wechat:douyin_ai_cs` | 入口校验登录态和权限；原 service 按 conversation/open_id 查事件 | `frontend/src/api/douyinAiCsClient.ts` 已调用 | 浏览器业务/资源下载代理 | 已加固入口门禁；后续仍需专项补 conversation/open_id 归属校验 |
| POST | `/integrations/douyin/live-check/resources/upload-image` | `upload_image` | 第二轮已加固：`get_request_context_required` + `auto_wechat:douyin_ai_cs` | 入口校验登录态和权限；原 service 按 open_id 调上游 | `frontend/src/api/douyinAiCsClient.ts` 已调用 | 浏览器业务/资源上传代理 | 已加固入口门禁；后续仍需专项补 open_id 归属校验 |
| POST | `/integrations/douyin/live-check/webhook-observe` | `webhook_observe` | 无，仅 `_ensure_enabled()` | 无 | 测试覆盖，未见前端业务调用 | Webhook callback/观察入口 | 不加浏览器登录态；按签名校验、来源限制、幂等和联调开关处理 |
| POST | `/integrations/douyin/live-check/callback` | `live_check_callback` | 无，仅 `_ensure_enabled()` | 无 | 测试覆盖，未见前端业务调用 | Webhook callback | 不加浏览器登录态；按 webhook 签名、来源、幂等处理 |
| POST | `/checks/run` | `run_checks` | 无 | 无；扫描全部 pending 检测记录 | 未见前端调用 | 历史 Windows 自动化/调试 | 不直接套 NewCar；标记下线候选或内部白名单，确认是否仍使用 |
| GET | `/checks` | `list_checks` | 第二轮已加固：`get_request_context_required` + `auto_wechat:leads` | 入口使用 `lead_management_service.require_leads_context()` 校验可信商户上下文；查询按关联 `DouyinLead.merchant_id` 隔离 | `frontend/src/api/checks.ts` 已调用 | 浏览器业务/历史数据查询 | 已加固入口门禁和查询级商户隔离 |
| POST | `/replies/manual` | `manual_reply` | 无 | 无；可按 lead_id/staff_id 写入回复并改线索状态 | 未见前端当前封装 | 历史手工录入/模拟接口 | 高风险写入口；若保留，补登录态 + 权限 + lead/staff 归属；否则下线候选 |
| POST | `/replies/current-wechat-detect` | `wechat_current_detect` | 无 | 无；按 lead_id/staff_id 回写状态 | `frontend/src/api/replies.ts` 已调用 | 历史 Windows 自动化接口 | 不应直接作为 NewCar 浏览器业务放开；当前架构倾向 19000 Local Agent 执行微信检测，需人工确认保留/隐藏/下线 |
| POST | `/replies/agent-write-back` | `agent_write_back` | 无 | 无；Local Agent 按 lead_id/staff_id/task_id 回写检测结果 | `app/local_agent_main.py` 调用 | Local Agent 内部接口 | 暂不加浏览器权限，避免 19000 断链；应设计 Local Agent 内部认证、任务绑定校验或签名 |
| GET | `/replies/debug/windows` | `debug_windows` | 无 | 无 | 未见前端业务调用 | 调试接口 | 内部白名单/开发开关/下线候选；不应对局域网公开 |
| GET | `/replies/debug/messages` | `debug_messages` | 无 | 无 | 未见前端业务调用 | 调试接口 | 内部白名单/开发开关/下线候选；可能暴露本机微信消息结构 |
| GET | `/replies/debug/raw-tree` | `debug_raw_tree` | 无 | 无 | 未见前端业务调用 | 实验调试接口 | 内部白名单/开发开关/下线候选 |
| POST | `/replies/debug/sender-experiment` | `debug_sender_experiment` | 无 | 无 | 未见前端业务调用 | 实验调试接口 | 内部白名单/开发开关/下线候选 |
| GET | `/agent/status` | `read_agent_status` | 无 | 无；只读内存心跳和自动化开关 | `frontend/src/api/agent.ts` 已调用 | 浏览器状态展示/Local Agent 状态 | 风险较低但会暴露本地 Agent 状态；建议后续补登录态或确认公开只读策略 |
| POST | `/agent/heartbeat` | `receive_agent_heartbeat` | 无 | 无；写入内存心跳 | `app/local_agent_main.py` 调用 | Local Agent 内部接口 | 不加 NewCar 浏览器权限；建议加 Local Agent 内部认证或来源白名单/共享 token |

### 10.3 明确风险接口

| 风险 | 接口 | 依据 | 建议 |
| --- | --- | --- | --- |
| 账号列表越权 | `GET /integrations/douyin/live-check/accounts` | 第二轮前无认证，无 merchant context，前端已有封装 | 第二轮已加固入口门禁：`get_request_context_required` + `auto_wechat:douyin_ai_cs`；仍需后续确认 merchant 账号过滤 |
| 账号同步越权 | `POST /integrations/douyin/live-check/accounts/sync-bind-info` | 第二轮前 optional 登录态，无 context 时仍可同步 | 第二轮已加固入口门禁：`get_request_context_required` + `auto_wechat:douyin_ai_cs` |
| 抖音私信发送越权 | `POST /integrations/douyin/live-check/messages/send` | 第二轮前无认证；前端工作台已调用；请求体带 `operator_id` | 第二轮已加固入口门禁：`get_request_context_required` + `auto_wechat:douyin_ai_cs`；后续再补账号/会话归属，不在本轮改发送链路 |
| 资源下载越权 | `POST /integrations/douyin/live-check/resources/download` | 第二轮前无认证；按 conversation/open_id 代理下载资源 | 第二轮已加固入口门禁：`get_request_context_required` + `auto_wechat:douyin_ai_cs`；后续再补会话归属 |
| 图片上传越权 | `POST /integrations/douyin/live-check/resources/upload-image` | 第二轮前无认证；按 open_id 调上游上传 | 第二轮已加固入口门禁：`get_request_context_required` + `auto_wechat:douyin_ai_cs`；后续再补 open_id 归属 |
| 检测数据泄露 | `GET /checks` | 第二轮前无认证，无 merchant 过滤，前端已调用 | 第二轮已加固：`get_request_context_required` + `auto_wechat:leads`，并按关联 `DouyinLead.merchant_id` 做查询隔离 |
| 检测状态被任意触发 | `POST /checks/run` | 无认证，全量扫描 pending 检测记录 | 标记内部/历史接口；确认后白名单或下线 |
| 手工回复写入越权 | `POST /replies/manual` | 无认证，可写 reply_checks 并更新线索状态 | 标记下线候选；若保留需权限和归属校验 |
| 旧本机微信检测入口暴露 | `POST /replies/current-wechat-detect` | 无认证，会触发 9000 直接读本机微信 UI | 与当前“微信操作发生在客户机 19000”的边界冲突，需确认下线或内部化 |
| Local Agent 心跳伪造 | `POST /agent/heartbeat` | 无认证写内存心跳 | 不套浏览器权限，单独设计 Local Agent 内部认证 |
| 调试信息泄露 | `/replies/debug/*` | 无认证读取窗口、消息控件结构 | 开发开关/内部白名单/下线候选 |
| Webhook 观察转正式链路风险 | `/webhook-observe`、`/callback` + `DY_LIVE_CHECK_FORWARD_TO_FORMAL` | 开启后 `_maybe_forward_to_formal()` 调 `_handle_douyin_webhook(... skip_signature_verification=True)` | 专项确认来源保护，不能用浏览器登录态替代 webhook 签名 |

### 10.4 暂不应加浏览器权限的接口

这些入口不是普通浏览器业务接口，直接加 NewCar 登录态可能破坏 OAuth/Webhook/Local Agent/自动化链路：

| 接口 | 原因 | 推荐方向 |
| --- | --- | --- |
| `GET /integrations/douyin/live-check/oauth-callback` | OAuth 观察回调不携带 NewCar 浏览器 token | OAuth state / 来源校验 |
| `GET /integrations/douyin/live-check/auth-redirect` | GMP 授权 302 回跳，直接 required 登录态可能断链 | state 绑定当前商户，或回跳前端后由已登录态完成绑定 |
| `POST /integrations/douyin/live-check/webhook-observe` | webhook/观察入口不应要求浏览器 token | 签名、来源、幂等、联调开关 |
| `POST /integrations/douyin/live-check/callback` | 抖音私信事件回调入口 | 签名、来源、幂等 |
| `POST /replies/agent-write-back` | 由 19000 Local Agent 调 9000 回写 | Local Agent token/签名/任务绑定校验 |
| `POST /agent/heartbeat` | 由 Local Agent 周期上报 | Local Agent 内部认证或来源白名单 |
| `POST /replies/current-wechat-detect` | 历史 9000 直连本机微信检测入口 | 先确认是否废弃；不要用 NewCar 权限把它包装成正式浏览器能力 |
| `/replies/debug/*` | 微信 UI 调试/实验入口 | 开发开关、内网白名单或下线 |

### 10.5 需要人工确认的问题

1. `live-check` 是否仍是正式商户工作台链路的一部分，还是只保留现场联调能力。
2. `GET /integrations/douyin/live-check/auth-url` 是否允许商户前端直接触发授权；如果允许，应使用哪个页面权限承载，目前建议是 `auto_wechat:douyin_ai_cs`。
3. `GET /integrations/douyin/live-check/auth-redirect` 的 OAuth/GMP state 是否已能绑定到当前商户；当前代码只使用 optional context，未看到强 state 归属闭环。
4. `GET /integrations/douyin/live-check/accounts` 是否应只返回当前 merchant 绑定账号；当前入口未传 context。
5. 私信发送、资源下载、图片上传是否继续走 `live-check` 路由，还是迁到已受保护的抖音 AI 客服代理路由。
6. `GET /checks` 是否仍是商户前端检测记录数据源；如果是，需要补 merchant 过滤。
7. `POST /replies/current-wechat-detect` 是否可以下线；当前架构已经明确微信操作应发生在客户机 19000 Local Agent。
8. `/replies/debug/*` 是否只允许本机开发；如继续保留，建议用开发环境开关显式保护。
9. `/agent/status` 是否允许未登录访问；当前只读但暴露本地 Agent 和自动化状态。
10. `/agent/heartbeat` 和 `/replies/agent-write-back` 的 Local Agent 内部认证采用共享 token、签名还是局域网白名单，需要单独设计。

### 10.6 建议下一步补洞任务

1. `P1-BACKEND-MIXED-ENTRYPOINT-GAP-FIX-1`
   - 只处理明确浏览器业务漏口：`live-check/accounts`、`sync-bind-info`、`messages/send`、`resources/download`、`resources/upload-image`。
   - 补 NewCar 登录态、`auto_wechat:douyin_ai_cs`、merchant/account/conversation 归属校验。

2. `P1-LEGACY-WECHAT-DEBUG-ENDPOINTS-LOCKDOWN-1`
   - 处理 `checks.py`、`replies.py` 的历史检测、手工写入和 debug 入口。
   - 决策路径：保留并加权限、改内部白名单、开发开关隐藏或下线。

3. `P1-LOCAL-AGENT-INTERNAL-AUTH-DESIGN-1`
   - 为 `/agent/heartbeat` 和 `/replies/agent-write-back` 设计 Local Agent 内部认证。
   - 不使用 NewCar 浏览器权限替代 Local Agent 信任边界。

4. `P1-LIVE-CHECK-CALLBACK-SAFETY-REVIEW-1`
   - 专项审计 `oauth-callback`、`auth-redirect`、`webhook-observe`、`callback`。
   - 重点确认 OAuth state、webhook 签名、幂等、来源限制和 `DY_LIVE_CHECK_FORWARD_TO_FORMAL` 的 `skip_signature_verification` 风险。

## 11. 第三轮最小补洞记录

任务名：`P1-BACKEND-MIXED-ENTRYPOINT-GAP-FIX-1`

补洞日期：2026-07-02

本轮只处理第二轮审计已明确的高风险浏览器业务入口：

| 接口 | 实际新增权限 |
| --- | --- |
| `GET /integrations/douyin/live-check/accounts` | `get_request_context_required` + `auto_wechat:douyin_ai_cs` |
| `POST /integrations/douyin/live-check/accounts/sync-bind-info` | `get_request_context_required` + `auto_wechat:douyin_ai_cs` |
| `POST /integrations/douyin/live-check/messages/send` | `get_request_context_required` + `auto_wechat:douyin_ai_cs` |
| `POST /integrations/douyin/live-check/resources/download` | `get_request_context_required` + `auto_wechat:douyin_ai_cs` |
| `POST /integrations/douyin/live-check/resources/upload-image` | `get_request_context_required` + `auto_wechat:douyin_ai_cs` |
| `GET /checks` | `get_request_context_required` + `auto_wechat:leads`，复用 `lead_management_service.require_leads_context()`，并按关联 `DouyinLead.merchant_id` 做查询隔离 |

本轮仍未处理且原因如下：

| 接口 | 原因 |
| --- | --- |
| `GET /integrations/douyin/live-check/oauth-callback` | OAuth callback，不应套 NewCar 浏览器登录态 |
| `GET /integrations/douyin/live-check/auth-redirect` | GMP 授权 302 回跳入口，需要 OAuth state / 商户绑定专项设计 |
| `POST /integrations/douyin/live-check/webhook-observe`、`POST /integrations/douyin/live-check/callback` | Webhook callback，应按签名、来源、幂等处理 |
| `POST /checks/run` | 历史检测/调试入口，不属于本轮浏览器查询补洞范围 |
| `POST /replies/agent-write-back`、`POST /agent/heartbeat` | Local Agent 内部接口，不应套 NewCar 浏览器权限 |
| `/replies/debug/*` | 微信 UI 调试/实验入口，后续按开发开关、白名单或下线处理 |

本轮没有改前端、9100、19000、NewCar exchange-code、`/auth/callback`、OAuth/Webhook 回调、Local Agent 回写/心跳、微信 UI debug 或抖音自动发送链路。
