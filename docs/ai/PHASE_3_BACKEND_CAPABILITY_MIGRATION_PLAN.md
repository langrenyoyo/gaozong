# Phase 3 后端能力服务迁移计划

> 阶段：Phase 3-A  
> 范围：后端能力迁移前只读审计与迁移计划  
> 结论：本阶段只输出审计和迁移计划，不迁移业务代码，不改数据库，不改接口行为。

## 1. 阶段边界

### 1.1 本阶段目标

1. 审计当前 9000 主后端中的 router、service、schema、model、test。
2. 按 6 个能力中心归类当前文件和接口。
3. 明确后续后端能力服务迁移顺序、迁移策略、依赖关系和风险边界。
4. 为 Phase 3-B 之后的实际迁移提供执行前清单。

### 1.2 本阶段允许范围

1. 新增本审计文档。
2. 新增只读结构检查测试，前提是不触碰业务行为。
3. 如存在文档索引，可补充文档链接。

### 1.3 本阶段禁止事项

1. 不迁移业务 router。
2. 不迁移业务 service。
3. 不修改数据库 model。
4. 不新增 migration。
5. 不修改 webhook 验签。
6. 不修改私信发送逻辑。
7. 不修改 19000 Local Agent、`input_writer`、微信 UI 自动化。
8. 不修改自动发送策略。
9. 不修改真实支付或算力扣费语义。
10. 不修改 NewCarProject 登录、权限、商户上下文门面。

## 2. 当前后端总体结构

当前 9000 主后端仍由 `app/main.py` 统一创建 FastAPI 应用并聚合业务 router。第一阶段已新增 6 个能力服务骨架目录：

| 能力 | 独立服务目录 | 当前状态 | 端口规划 |
|---|---|---|---|
| 抖音AI小高客服 | `apps/douyin_cs` | 骨架服务，已暴露 `/`、`/health`、`/openapi.json` | 9201 |
| AI小高线索 | `apps/leads` | 骨架服务，已暴露 `/`、`/health`、`/openapi.json` | 9202 |
| AI小高智能体 | `apps/agents` | 骨架服务，已暴露 `/`、`/health`、`/openapi.json` | 9203 |
| AI小高微信助手 | `apps/wechat_assistant` | 骨架服务，已暴露 `/`、`/health`、`/openapi.json` | 9204 |
| 小高算力 | `apps/compute` | 骨架服务，已暴露 `/`、`/health`、`/openapi.json` | 9205 |
| 统一知识库训练 | `apps/knowledge` | 骨架服务，已暴露 `/`、`/health`、`/openapi.json` | 9206 |

当前 9100 RAG/LLM 服务位于 `apps/xg_douyin_ai_cs`，已经是独立 FastAPI 服务；19000 Local Agent 位于 `app/local_agent_main.py`，不进入 Docker，不在本轮迁移。

## 3. 当前后端文件归类表

迁移判断说明：

- `可以迁移=是`：后续可以作为首批迁移候选，但仍需保留 9000 旧接口兼容。
- `可以迁移=部分`：需要先抽共享上下文、数据库、client 或兼容适配。
- `可以迁移=暂缓`：安全边界高、跨能力耦合深，当前不建议先动。
- `可以迁移=否`：应保留在 gateway / shared 层。

### 3.1 Gateway / 共享层

| 文件路径 | 当前职责 | 归属能力 | 是否可以迁移 | 风险等级 | 依赖项 |
|---|---|---|---|---|---|
| `app/main.py` | 9000 主应用入口、路由聚合、启动调度器、CORS、根路径 | gateway / main-api | 否 | 高 | 全部 router、scheduler、Windows 专用 router |
| `app/auth/context.py` | RequestContext 与商户上下文 | gateway / common | 否 | 高 | NewCarProject token/cookie、merchant_id |
| `app/auth/dependencies.py` | 登录态、权限依赖、RequestContext 注入 | gateway / common | 否 | 高 | `RequestContext`、权限字典 |
| `app/auth/newcar_client.py` | NewCarProject 鉴权门面和 mock client | gateway / common | 否 | 高 | 外部登录/权限契约 |
| `app/config.py` | 全局配置、webhook、外部服务、自动化开关 | gateway / common | 否 | 高 | 环境变量、webhook、9100、douyinAPI |
| `app/database.py` | 当前共享 SQLite 连接、Base、Session | common persistence | 否 | 高 | 所有 model、所有 9000 service |
| `app/models.py` | 当前所有 9000 SQLAlchemy model 集中定义 | common persistence | 部分 | 高 | SQLite、现有 migration、所有 service |
| `app/schemas.py` | 当前所有 9000 DTO 集中定义 | common schema | 部分 | 中 | 所有 router、前端兼容 |
| `app/routers/auth.py` | 登录态与回调探针 | gateway / main-api | 否 | 高 | `get_request_context_required` |
| `app/routers/capability_gateway.py` | `/api/{capability}/health` 网关健康前缀 | gateway / main-api | 否 | 中 | `apps/*/service.META`、`packages/common` |
| `packages/common/*` | 能力元数据和共享响应结构 | common | 否 | 低 | 6 个能力骨架、gateway |
| `packages/clients/*` | 预留跨服务 client 目录 | common client | 否 | 中 | 后续 HTTP/internal API |

### 3.2 抖音AI小高客服 `douyin-cs`

| 文件路径 | 当前职责 | 归属能力 | 是否可以迁移 | 风险等级 | 依赖项 |
|---|---|---|---|---|---|
| `app/routers/douyin_live_check.py` | 抖音授权、账号同步、工作台消息、私信发送、资源下载/上传、webhook observe | douyin-cs | 部分 | 高 | `RequestContext`、`_handle_douyin_webhook`、OpenAPI、私信发送 |
| `app/routers/douyin_accounts.py` | 抖音企业号列表、Agent 绑定、取消授权、删除 | douyin-cs | 部分 | 高 | 权限、商户隔离、`DouyinAuthorizedAccount`、Agent 绑定 |
| `app/routers/douyin_ai_cs_proxy.py` | 9000 到 9100 的可信 reply-suggestion / RAG 文档训练代理 | douyin-cs / knowledge | 部分 | 高 | `xg_douyin_ai_cs_client`、Agent、知识分类、权限 |
| `app/routers/ai_reply_decision_logs.py` | AI 回复记录查询 | douyin-cs | 是 | 中 | `RequestContext.merchant_id`、`AiReplyDecisionLog` |
| `app/routers/douyin_autoreply_settings.py` | 自动回复配置查询和更新 | douyin-cs | 部分 | 高 | `auto_send=false` 边界、企业号归属 |
| `app/routers/ai_auto_reply_runs.py` | 自动回复运行记录查询 | douyin-cs | 是 | 中 | `AiAutoReplyRun`、权限 |
| `app/routers/integrations.py` 部分路径 | 抖音会话、消息、profile、webhook、同步入口 | douyin-cs / leads | 部分 | 高 | webhook 验签、线索生成、工作台 |
| `app/services/douyin_live_check_service.py` | 抖音授权签名、账号绑定、OpenAPI 调用 | douyin-cs | 部分 | 高 | `DouyinAuthorizedAccount`、OpenAPI 配置 |
| `app/services/douyin_openapi_client.py` | 抖音 OpenAPI 通用调用 | douyin-cs | 是 | 中 | 上游 OpenAPI、超时、错误处理 |
| `app/services/douyin_workbench_conversation_service.py` | 工作台会话列表、消息、profile、发送上下文 | douyin-cs | 部分 | 高 | `DouyinWebhookEvent`、`DouyinLead`、联系信息提取 |
| `app/services/douyin_private_message_send_service.py` | 人工确认后私信发送、发送记录、接管状态 | douyin-cs | 暂缓 | 高 | `manual_confirmed=true`、OpenAPI、`ConversationAutopilotState` |
| `app/services/douyin_resource_download_service.py` | 私信资源下载记录和 OpenAPI 下载 | douyin-cs | 是 | 中 | `DouyinMessageResourceDownload`、OpenAPI |
| `app/services/douyin_image_upload_service.py` | 图片上传记录和 OpenAPI 上传 | douyin-cs | 是 | 中 | `DouyinImageUpload`、OpenAPI |
| `app/services/douyin_account_agent_binding_service.py` | 企业号与 Agent 绑定 | douyin-cs / agents | 部分 | 高 | `AiAgent`、`DouyinAuthorizedAccount`、权限 |
| `app/services/douyin_ai_cs_binding_service.py` | reply-suggestion 前绑定校验 | douyin-cs / agents | 部分 | 高 | Agent 绑定、企业号归属 |
| `app/services/douyin_conversation_history_service.py` | 为 9100 构造会话历史 | douyin-cs | 是 | 中 | 工作台消息服务 |
| `app/services/xg_douyin_ai_cs_client.py` | 9000 调 9100 client | douyin-cs / knowledge | 是 | 中 | 9100 URL、超时、RequestContext |
| `app/services/ai_reply_decision_log_service.py` | 记录 AI 回复建议决策日志 | douyin-cs | 是 | 中 | `AiReplyDecisionLog`、结构化字段 |
| `app/services/ai_reply_decision_log_query_service.py` | AI 回复记录查询 | douyin-cs | 是 | 中 | `AiReplyDecisionLog` |
| `app/services/douyin_autoreply_settings_service.py` | 自动回复配置读取与更新 | douyin-cs | 部分 | 高 | `DouyinAccountAutoreplySetting`、企业号归属 |
| `app/services/douyin_autoreply_gate_service.py` | 自动回复前后置门禁 | douyin-cs | 暂缓 | 高 | `auto_send=false`、人工接管、运行记录 |
| `app/services/ai_auto_reply_dry_run_service.py` | 自动回复 dry-run 编排 | douyin-cs | 暂缓 | 高 | 9100、Agent、知识分类、发送门禁 |
| `app/services/ai_auto_reply_send_service.py` | 自动回复发送执行服务 | douyin-cs | 暂缓 | 高 | 私信发送、`auto_send=false`、人工接管 |
| `app/services/ai_auto_sent_message_matcher.py` | webhook 事件与 AI 自动发送记录匹配 | douyin-cs | 暂缓 | 高 | webhook、发送记录 |
| `app/services/ai_auto_reply_run_query_service.py` | 自动回复运行记录查询 | douyin-cs | 是 | 中 | `AiAutoReplyRun`、`DouyinPrivateMessageSend` |
| `app/services/conversation_autopilot_state_service.py` | 会话托管/人工接管状态 | douyin-cs | 暂缓 | 高 | 私信发送、自动回复门禁 |
| `apps/xg_douyin_ai_cs/**` | 9100 RAG/LLM、mock 工作台、回复建议、RAG 搜索 | douyin-cs / knowledge | 暂缓 | 高 | 独立 DB、LLM、RAG、compute usage client |
| `tests/test_douyin_*`、`tests/test_ai_reply_*`、`tests/test_ai_auto_*`、`tests/test_xg_douyin_ai_cs_*` | 抖音客服、回复建议、自动回复、9100 测试 | douyin-cs | 复制/改造 | 高 | 9000/9100 边界、安全断言 |

### 3.3 AI小高线索 `leads`

| 文件路径 | 当前职责 | 归属能力 | 是否可以迁移 | 风险等级 | 依赖项 |
|---|---|---|---|---|---|
| `app/routers/leads.py` | 线索创建、列表、详情、分配 | leads | 部分 | 中 | `DouyinLead`、销售、RequestContext |
| `app/routers/reports.py` | 线索统计汇总 | leads | 是 | 中 | `report_service`、`lead_management_service` |
| `app/routers/staff.py` | 销售人员 CRUD | leads / wechat-assistant | 部分 | 中 | `SalesStaff`、派单 |
| `app/routers/webhook_events.py` | 原始 webhook / invalid 只读查询 | leads / douyin-cs | 暂缓 | 高 | webhook 事件、联系信息提取 |
| `app/routers/integrations.py` 部分路径 | `/integrations/douyin/sync-leads` 和 webhook 线索生成 | leads / douyin-cs | 暂缓 | 高 | douyinAPI、webhook 验签、线索入库 |
| `app/integrations/douyin_api_client.py` | 拉取 douyinAPI 线索 | leads | 是 | 中 | 上游 douyinAPI |
| `app/integrations/douyin_webhook.py` | webhook 验签、事件入库、线索生成 | leads / douyin-cs | 暂缓 | 高 | 签名、原始 body、`DouyinWebhookEvent`、`DouyinLead` |
| `app/services/lead_service.py` | 基础线索 CRUD | leads | 是 | 中 | `DouyinLead` |
| `app/services/lead_management_service.py` | 线索列表、详情、评分、时间线、商户隔离 | leads | 部分 | 高 | `RequestContext`、`SalesStaff`、`LeadNotification`、`ReplyCheck` |
| `app/services/assign_service.py` | 线索分配和检查配置 | leads / wechat-assistant | 部分 | 中 | `SalesStaff`、`ReplyCheck`、`CheckConfig` |
| `app/services/douyin_sync_service.py` | 拉取上游线索、入库、自动分配、可选创建微信任务 | leads / wechat-assistant | 暂缓 | 高 | douyinAPI、分配、微信任务、自动通知 |
| `app/services/contact_extractor.py` | 联系方式提取规则 | leads | 是 | 中 | webhook、工作台 profile |
| `app/services/webhook_event_service.py` | 原始事件列表、详情、摘要 | leads / douyin-cs | 部分 | 高 | `DouyinWebhookEvent`、联系信息提取 |
| `app/services/report_service.py` | 报表汇总 | leads | 是 | 中 | `DouyinLead`、`ReplyCheck`、`SalesStaff` |
| `app/services/staff_service.py` | 销售人员 CRUD | leads / wechat-assistant | 部分 | 中 | `SalesStaff` |
| `tests/test_leads_*`、`tests/test_douyin_sync.py`、`tests/test_webhook_events.py`、`tests/test_contact_extractor.py`、`tests/test_reports*` | 线索、同步、webhook 事件、统计测试 | leads | 复制/改造 | 高 | webhook 和商户隔离 |

### 3.4 AI小高智能体 `agents`

| 文件路径 | 当前职责 | 归属能力 | 是否可以迁移 | 风险等级 | 依赖项 |
|---|---|---|---|---|---|
| `app/routers/agents.py` | Agent CRUD、知识分类绑定、训练对话 | agents | 部分 | 中 | `RequestContext`、`AiAgent`、知识分类 |
| `app/services/ai_agent_service.py` | Agent CRUD 与商户隔离 | agents | 是 | 中 | `AiAgent`、权限上下文 |
| `app/services/agent_knowledge_category_service.py` | Agent 绑定知识分类 | agents / knowledge | 部分 | 中 | `AgentKnowledgeCategory`、`KnowledgeCategory` |
| `app/services/douyin_account_agent_binding_service.py` | Agent 与抖音企业号绑定 | agents / douyin-cs | 部分 | 高 | `DouyinAuthorizedAccount`、`AiAgent` |
| `app/models.py` 中 `AiAgent`、`AgentKnowledgeCategory`、`DouyinAccountAgentBinding` | Agent 与绑定模型 | agents | 暂留共享层 | 高 | 现有共享 SQLite |
| `app/schemas.py` 中 `AiAgent*`、`AgentKnowledgeCategories*` | Agent DTO | agents | 部分 | 中 | 前端旧导入和 router |
| `tests/test_ai_agents.py`、`tests/test_agent_knowledge_categories.py`、`tests/test_douyin_account_agent_binding_service.py`、`tests/test_douyin_ai_cs_binding_service.py` | Agent 与绑定测试 | agents | 复制/改造 | 中 | 知识分类、抖音账号 |

### 3.5 AI小高微信助手 `wechat-assistant`

| 文件路径 | 当前职责 | 归属能力 | 是否可以迁移 | 风险等级 | 依赖项 |
|---|---|---|---|---|---|
| `app/local_agent_main.py` | 19000 Local Agent、微信窗口、任务轮询、只读检测 | wechat-assistant | 暂缓 | 高 | Windows、UIA、OCR、剪贴板、运行锁 |
| `app/local_agent_exe_entry.py` | exe 启动入口 | wechat-assistant | 暂缓 | 高 | PyInstaller、19000 |
| `app/routers/agent.py` | 9000 Agent 心跳和状态 | wechat-assistant | 是 | 中 | `agent_status_service` |
| `app/routers/wechat_tasks.py` | 微信任务创建、pending、结果回写 | wechat-assistant | 暂缓 | 高 | `WechatTask`、通知、检测回写 |
| `app/routers/wechat_auto_detect.py` | 旧自动检测目标配置 | wechat-assistant | 暂缓 | 高 | 旧调度器、`ReplyCheck`、`CheckConfig` |
| `app/routers/automation_control.py` | 紧急停止、恢复、自动化状态 | wechat-assistant | 暂缓 | 高 | 运行锁、发送门禁 |
| `app/routers/checks.py` | 回复检测运行和列表 | wechat-assistant / leads | 部分 | 中 | `ReplyCheck`、`DouyinLead` |
| `app/routers/replies.py` | 手动回复、当前微信检测、agent-write-back、debug | wechat-assistant | 暂缓 | 高 | 微信 UI、只读检测、debug 序列化 |
| `app/routers/lead_notifications.py` | 通知销售、打开聊天、批量通知 | wechat-assistant / leads | 暂缓 | 高 | `input_writer`、联系人验证、paste_only |
| `app/routers/feedback.py` | 当前聊天反馈、debug、激活微信 | wechat-assistant | 暂缓 | 高 | 微信 UI、窗口控制 |
| `app/services/agent_status_service.py` | Agent 心跳状态 | wechat-assistant | 是 | 中 | 自动化状态 |
| `app/services/wechat_task_service.py` | 微信任务状态、结果回写、自动创建检测任务 | wechat-assistant | 暂缓 | 高 | `WechatTask`、`LeadNotification`、`ReplyCheck` |
| `app/services/notification_service.py` | 通知销售、联系人搜索、粘贴、自动检测目标 | wechat-assistant | 暂缓 | 高 | `input_writer`、`contact_searcher`、运行锁 |
| `app/services/wechat_ui_reply_service.py` | 9000 本机微信读取检测旧路径 | wechat-assistant | 暂缓 | 高 | `app/wechat_ui/*` |
| `app/services/reply_checker.py`、`app/services/reply_analyzer.py` | 回复检测规则和配置读取 | wechat-assistant / leads | 部分 | 中 | `ReplyCheck`、`CheckConfig` |
| `app/services/automation_control.py` | 自动化运行状态与紧急停止 | wechat-assistant | 暂缓 | 高 | 全局状态、发送门禁 |
| `app/services/hotkey_listener.py`、`app/services/desktop_overlay.py` | 桌面热键和浮层 | wechat-assistant | 暂缓 | 高 | Windows 桌面 |
| `app/wechat_ui/**` | 微信 UI 自动化、OCR、窗口、剪贴板、输入 | wechat-assistant | 暂缓 | 高 | UIA、Win32、OCR、`input_writer` |
| `app/scheduler/check_scheduler.py`、`app/scheduler/wechat_auto_detect_scheduler.py` | 检测调度和旧自动检测调度器 | wechat-assistant | 暂缓 | 高 | 后台任务、旧链路默认禁用 |
| `tests/test_p0_*`、`tests/test_p1_auto_*`、`tests/test_wechat_*`、`tests/test_local_agent_heartbeat.py`、`tests/test_agent_status.py` | Local Agent、安全门禁、任务轮询、检测测试 | wechat-assistant | 复制/改造 | 高 | sent=false、read_only、task_id |

### 3.6 小高算力 `compute`

| 文件路径 | 当前职责 | 归属能力 | 是否可以迁移 | 风险等级 | 依赖项 |
|---|---|---|---|---|---|
| `app/routers/compute.py` | 商户算力余额、流水、套餐、充值订单、超管配置、internal usage | compute | 是 | 中 | `RequestContext`、`compute_service` |
| `app/services/compute_service.py` | 算力账户、交易流水、套餐、充值 mock、usage 上报 | compute | 是 | 中 | `ComputeAccount`、`ComputePackage`、`ComputeTransaction` |
| `apps/xg_douyin_ai_cs/services/compute_usage_client.py` | 9100 向 9000 上报 usage 的 client | compute / douyin-cs | 部分 | 中 | 9000 internal API |
| `app/models.py` 中 `ComputeAccount`、`ComputeTransaction`、`ComputePackage` | 算力模型 | compute | 暂留共享层 | 高 | 现有 SQLite、migration |
| `app/schemas.py` 中 `Compute*` | 算力 DTO | compute | 是 | 中 | router、前端 |
| `tests/test_compute_models.py`、`tests/test_compute_router.py`、`tests/test_compute_service.py`、`tests/test_compute_usage_client.py` | 算力模型、router、service、9100 client 测试 | compute | 复制/改造 | 中 | 不引入真实支付 |

### 3.7 统一知识库训练 `knowledge`

| 文件路径 | 当前职责 | 归属能力 | 是否可以迁移 | 风险等级 | 依赖项 |
|---|---|---|---|---|---|
| `app/routers/knowledge_categories.py` | 9000 知识分类列表与创建 | knowledge | 是 | 中 | `RequestContext`、`KnowledgeCategory` |
| `app/routers/douyin_ai_cs_proxy.py` 中 `/rag/documents`、`/rag/train` | 9000 可信代理创建 RAG 文档和训练 | knowledge | 部分 | 高 | 9100 RAG、企业号归属、分类可见性 |
| `app/services/knowledge_category_service.py` | 分类 key 规范、商户可见分类、创建分类 | knowledge | 是 | 中 | `KnowledgeCategory`、商户上下文 |
| `app/services/agent_knowledge_category_service.py` | Agent 分类绑定与有效分类计算 | knowledge / agents | 部分 | 中 | `AgentKnowledgeCategory`、`KnowledgeCategory` |
| `apps/xg_douyin_ai_cs/routers/rag.py` | 9100 RAG 文档、训练、搜索 | knowledge | 暂缓 | 高 | 9100 独立 DB、embedding、LLM |
| `apps/xg_douyin_ai_cs/rag/**` | 9100 RAG SQLite、chunk、向量搜索 | knowledge | 暂缓 | 高 | 9100 SQLite、embedding |
| `apps/xg_douyin_ai_cs/routers/categories.py`、`services/category_service.py` | 9100 demo 分类配置 | knowledge | 暂缓 | 中 | 9100 mock / constants |
| `app/models.py` 中 `KnowledgeCategory`、`AgentKnowledgeCategory` | 知识分类与 Agent 绑定模型 | knowledge | 暂留共享层 | 高 | 现有 SQLite、Agent |
| `app/schemas.py` 中 `KnowledgeCategory*`、`AgentKnowledgeCategories*` | 知识分类 DTO | knowledge | 是 | 中 | router、Agent 页面 |
| `tests/test_knowledge_categories_api.py`、`tests/test_agent_knowledge_categories.py`、`tests/test_xg_douyin_ai_cs_rag.py` | 分类、绑定、RAG 测试 | knowledge | 复制/改造 | 高 | 9000/9100 边界 |

## 4. 当前接口归类表

### 4.1 Gateway / 通用接口

| 当前 path | HTTP method | 当前 router | 归属能力 | 未来目标 path | 是否需要旧接口兼容 | 是否涉及权限 / merchant_id / tenant_id |
|---|---|---|---|---|---|---|
| `/` | GET | `app.main` | gateway | `/` | 是 | 否 |
| `/auth/me` | GET | `auth.py` | gateway | `/auth/me` | 是 | 是，登录态和 RequestContext |
| `/auth/callback` | GET | `auth.py` | gateway | `/auth/callback` | 是 | 是，登录态和 RequestContext |
| `/api/{capability}/health` | GET | `capability_gateway.py` | gateway | `/api/{capability}/health` | 是 | 否 |

### 4.2 抖音AI小高客服 `douyin-cs`

| 当前 path | HTTP method | 当前 router | 归属能力 | 未来目标 path | 是否需要旧接口兼容 | 是否涉及权限 / merchant_id / tenant_id |
|---|---|---|---|---|---|---|
| `/douyin-live-check/auth-url` | GET | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/auth-url` | 是 | 是 |
| `/douyin-live-check/oauth-callback` | GET | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/oauth-callback` | 是 | 是 |
| `/douyin-live-check/auth-redirect` | GET | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/auth-redirect` | 是 | 是 |
| `/douyin-live-check/status` | GET | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/status` | 是 | 是 |
| `/douyin-live-check/accounts` | GET | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/accounts` | 是 | 是 |
| `/douyin-live-check/accounts/sync-bind-info` | POST | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/accounts/sync-bind-info` | 是 | 是 |
| `/douyin-live-check/accounts/bind-authorized-open-id` | POST | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/accounts/bind-authorized-open-id` | 是 | 是 |
| `/douyin-live-check/messages/send` | POST | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/messages/send` | 是 | 是，且必须保留 `manual_confirmed=true` |
| `/douyin-live-check/resources/download` | POST | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/resources/download` | 是 | 是 |
| `/douyin-live-check/resources/upload-image` | POST | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/resources/upload-image` | 是 | 是 |
| `/douyin-live-check/webhook-observe` | POST | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/webhook-observe` | 是 | 是，不能破坏 webhook 观察逻辑 |
| `/douyin-live-check/callback` | POST | `douyin_live_check.py` | douyin-cs | `/api/douyin-cs/callback` | 是 | 是，不能破坏 webhook 观察逻辑 |
| `/integrations/douyin/accounts` | GET | `douyin_accounts.py` | douyin-cs | `/api/douyin-cs/accounts` | 是 | 是 |
| `/integrations/douyin/accounts/{account_open_id}/agent-binding` | PUT | `douyin_accounts.py` | douyin-cs / agents | `/api/douyin-cs/accounts/{account_open_id}/agent-binding` | 是 | 是 |
| `/integrations/douyin/accounts/{account_open_id}/agent-binding` | DELETE | `douyin_accounts.py` | douyin-cs / agents | `/api/douyin-cs/accounts/{account_open_id}/agent-binding` | 是 | 是 |
| `/integrations/douyin/accounts/{account_open_id}/cancel-authorization` | POST | `douyin_accounts.py` | douyin-cs | `/api/douyin-cs/accounts/{account_open_id}/cancel-authorization` | 是 | 是 |
| `/integrations/douyin/accounts/{account_open_id}` | DELETE | `douyin_accounts.py` | douyin-cs | `/api/douyin-cs/accounts/{account_open_id}` | 是 | 是 |
| `/integrations/douyin/accounts/{account_id}/conversations` | GET | `integrations.py` | douyin-cs | `/api/douyin-cs/accounts/{account_id}/conversations` | 是 | 当前较弱，后续需补商户隔离 |
| `/integrations/douyin/conversations/{conversation_key}/messages` | GET | `integrations.py` | douyin-cs | `/api/douyin-cs/conversations/{conversation_key}/messages` | 是 | 当前较弱，后续需补商户隔离 |
| `/integrations/douyin/accounts/{account_id}/conversations/{conversation_key}/profile` | GET | `integrations.py` | douyin-cs | `/api/douyin-cs/accounts/{account_id}/conversations/{conversation_key}/profile` | 是 | 当前较弱，后续需补商户隔离 |
| `/integrations/douyin/conversation-messages` | GET | `integrations.py` | douyin-cs | `/api/douyin-cs/conversation-messages` | 是 | 当前较弱，后续需补商户隔离 |
| `/integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion` | POST | `douyin_ai_cs_proxy.py` | douyin-cs | `/api/douyin-cs/conversations/{conversation_id}/reply-suggestion` | 是 | 是，必须强制 `auto_send=false` |
| `/integrations/douyin-ai-cs/accounts/{account_open_id}/agents` | GET | `douyin_ai_cs_proxy.py` | douyin-cs / agents | `/api/douyin-cs/accounts/{account_open_id}/agents` | 是 | 是 |
| `/ai-reply-decision-logs` | GET | `ai_reply_decision_logs.py` | douyin-cs | `/api/douyin-cs/reply-decision-logs` | 是 | 是 |
| `/ai-reply-decision-logs/{log_id}` | GET | `ai_reply_decision_logs.py` | douyin-cs | `/api/douyin-cs/reply-decision-logs/{log_id}` | 是 | 是 |
| `/douyin-autoreply/settings` | GET | `douyin_autoreply_settings.py` | douyin-cs | `/api/douyin-cs/autoreply/settings` | 是 | 是，不能放宽自动发送 |
| `/douyin-autoreply/settings/{account_open_id}` | GET | `douyin_autoreply_settings.py` | douyin-cs | `/api/douyin-cs/autoreply/settings/{account_open_id}` | 是 | 是，不能放宽自动发送 |
| `/douyin-autoreply/settings/{account_open_id}` | PUT | `douyin_autoreply_settings.py` | douyin-cs | `/api/douyin-cs/autoreply/settings/{account_open_id}` | 是 | 是，不能放宽自动发送 |
| `/ai-auto-reply-runs` | GET | `ai_auto_reply_runs.py` | douyin-cs | `/api/douyin-cs/auto-reply-runs` | 是 | 是 |
| `/ai-auto-reply-runs/{run_id}` | GET | `ai_auto_reply_runs.py` | douyin-cs | `/api/douyin-cs/auto-reply-runs/{run_id}` | 是 | 是 |

### 4.3 AI小高线索 `leads`

| 当前 path | HTTP method | 当前 router | 归属能力 | 未来目标 path | 是否需要旧接口兼容 | 是否涉及权限 / merchant_id / tenant_id |
|---|---|---|---|---|---|---|
| `/leads` | POST | `leads.py` | leads | `/api/leads` | 是 | 当前需补强 merchant_id |
| `/leads` | GET | `leads.py` | leads | `/api/leads` | 是 | 是，依赖 RequestContext |
| `/leads/{lead_id}` | GET | `leads.py` | leads | `/api/leads/{lead_id}` | 是 | 是，详情需要归属校验 |
| `/leads/{lead_id}/assign` | POST | `leads.py` | leads / wechat-assistant | `/api/leads/{lead_id}/assign` | 是 | 是 |
| `/reports/summary` | GET | `reports.py` | leads | `/api/leads/reports/summary` | 是 | 是 |
| `/staff` | POST | `staff.py` | leads / wechat-assistant | `/api/leads/staff` | 是 | 后续需补 merchant_id |
| `/staff` | GET | `staff.py` | leads / wechat-assistant | `/api/leads/staff` | 是 | 后续需补 merchant_id |
| `/staff/{staff_id}` | GET | `staff.py` | leads / wechat-assistant | `/api/leads/staff/{staff_id}` | 是 | 后续需补 merchant_id |
| `/staff/{staff_id}` | PUT | `staff.py` | leads / wechat-assistant | `/api/leads/staff/{staff_id}` | 是 | 后续需补 merchant_id |
| `/integrations/douyin/sync-leads` | POST | `integrations.py` | leads | `/api/leads/integrations/douyin/sync-leads` | 是 | 当前较弱，后续需补商户隔离 |
| `/integrations/douyin/webhook` | POST | `integrations.py` | leads / douyin-cs | `/api/leads/webhook/douyin` | 是 | 是，涉及 webhook 验签 |
| `/webhook/douyin` | POST | `integrations.legacy_webhook_router` | leads / douyin-cs | `/api/leads/webhook/douyin` | 是，正式 callback 入口 | 是，涉及 webhook 验签 |
| `/webhook-events` | GET | `webhook_events.py` | leads | `/api/leads/webhook-events` | 是 | 后续需补 merchant_id |
| `/webhook-events/{event_id}` | GET | `webhook_events.py` | leads | `/api/leads/webhook-events/{event_id}` | 是 | 后续需补 merchant_id |

### 4.4 AI小高智能体 `agents`

| 当前 path | HTTP method | 当前 router | 归属能力 | 未来目标 path | 是否需要旧接口兼容 | 是否涉及权限 / merchant_id / tenant_id |
|---|---|---|---|---|---|---|
| `/agents` | GET | `agents.py` | agents | `/api/agents` | 是 | 是 |
| `/agents` | POST | `agents.py` | agents | `/api/agents` | 是 | 是 |
| `/agents/{agent_id}` | GET | `agents.py` | agents | `/api/agents/{agent_id}` | 是 | 是 |
| `/agents/{agent_id}` | PUT | `agents.py` | agents | `/api/agents/{agent_id}` | 是 | 是 |
| `/agents/{agent_id}` | DELETE | `agents.py` | agents | `/api/agents/{agent_id}` | 是 | 是 |
| `/agents/{agent_id}/knowledge-categories` | GET | `agents.py` | agents / knowledge | `/api/agents/{agent_id}/knowledge-categories` | 是 | 是 |
| `/agents/{agent_id}/knowledge-categories` | PUT | `agents.py` | agents / knowledge | `/api/agents/{agent_id}/knowledge-categories` | 是 | 是 |
| `/agents/{agent_id}/training-chat` | POST | `agents.py` | agents | `/api/agents/{agent_id}/training-chat` | 是 | 是 |

### 4.5 AI小高微信助手 `wechat-assistant`

| 当前 path | HTTP method | 当前 router | 归属能力 | 未来目标 path | 是否需要旧接口兼容 | 是否涉及权限 / merchant_id / tenant_id |
|---|---|---|---|---|---|---|
| `/agent/status` | GET | `agent.py` | wechat-assistant | `/api/wechat-assistant/agent/status` | 是 | 当前无商户隔离，后续需设计 |
| `/agent/heartbeat` | POST | `agent.py` | wechat-assistant | `/api/wechat-assistant/agent/heartbeat` | 是 | 当前无商户隔离，后续需设计 |
| `/wechat-tasks` | POST | `wechat_tasks.py` | wechat-assistant | `/api/wechat-assistant/tasks` | 是 | 后续需绑定商户 |
| `/wechat-tasks/pending` | GET | `wechat_tasks.py` | wechat-assistant | `/api/wechat-assistant/tasks/pending` | 是 | 后续需绑定 agent_client_id / merchant_id |
| `/wechat-tasks/{task_id}` | GET | `wechat_tasks.py` | wechat-assistant | `/api/wechat-assistant/tasks/{task_id}` | 是 | 后续需绑定商户 |
| `/wechat-tasks/{task_id}/result` | POST | `wechat_tasks.py` | wechat-assistant | `/api/wechat-assistant/tasks/{task_id}/result` | 是 | 后续需绑定 agent_client_id / merchant_id |
| `/wechat-auto-detect/target` | POST | `wechat_auto_detect.py` | wechat-assistant | `/api/wechat-assistant/auto-detect/target` | 是 | 后续需绑定商户 |
| `/wechat-auto-detect/status` | GET | `wechat_auto_detect.py` | wechat-assistant | `/api/wechat-assistant/auto-detect/status` | 是 | 后续需绑定商户 |
| `/wechat-auto-detect/clear` | POST | `wechat_auto_detect.py` | wechat-assistant | `/api/wechat-assistant/auto-detect/clear` | 是 | 后续需绑定商户 |
| `/automation/status` | GET | `automation_control.py` | wechat-assistant | `/api/wechat-assistant/automation/status` | 是 | 否，但涉及安全门禁 |
| `/automation/emergency-stop` | POST | `automation_control.py` | wechat-assistant | `/api/wechat-assistant/automation/emergency-stop` | 是 | 否，但涉及安全门禁 |
| `/automation/resume` | POST | `automation_control.py` | wechat-assistant | `/api/wechat-assistant/automation/resume` | 是 | 否，但涉及安全门禁 |
| `/checks/run` | POST | `checks.py` | wechat-assistant | `/api/wechat-assistant/checks/run` | 是 | 后续需绑定商户 |
| `/checks` | GET | `checks.py` | wechat-assistant | `/api/wechat-assistant/checks` | 是 | 后续需绑定商户 |
| `/replies/manual` | POST | `replies.py` | wechat-assistant | `/api/wechat-assistant/replies/manual` | 是 | 后续需绑定商户 |
| `/replies/current-wechat-detect` | POST | `replies.py` | wechat-assistant | `/api/wechat-assistant/replies/current-wechat-detect` | 是 | 涉及微信 UI，只读边界 |
| `/replies/agent-write-back` | POST | `replies.py` | wechat-assistant | `/api/wechat-assistant/replies/agent-write-back` | 是 | 后续需绑定 agent_client_id |
| `/replies/debug/*` | GET/POST | `replies.py` | wechat-assistant | `/api/wechat-assistant/replies/debug/*` | 是 | 高风险诊断，必须安全序列化 |
| `/lead-notifications/send-to-staff` | POST | `lead_notifications.py` | wechat-assistant | `/api/wechat-assistant/lead-notifications/send-to-staff` | 是 | 涉及 paste_only 和发送门禁 |
| `/lead-notifications/records` | GET | `lead_notifications.py` | wechat-assistant | `/api/wechat-assistant/lead-notifications/records` | 是 | 后续需绑定商户 |
| `/lead-notifications/open-chat` | POST | `lead_notifications.py` | wechat-assistant | `/api/wechat-assistant/lead-notifications/open-chat` | 是 | 涉及微信 UI |
| `/lead-notifications/send-pending-assigned` | POST | `lead_notifications.py` | wechat-assistant | `/api/wechat-assistant/lead-notifications/send-pending-assigned` | 是 | 涉及批量 paste_only |
| `/feedback/*` | GET/POST | `feedback.py` | wechat-assistant | `/api/wechat-assistant/feedback/*` | 是 | 涉及微信 UI |
| `19000 /health` | GET | `app/local_agent_main.py` | wechat-assistant | 保持 19000 本地路径 | 是 | 本机 Agent，不走 9000 权限 |
| `19000 /agent/tasks/poll-and-execute` | POST | `app/local_agent_main.py` | wechat-assistant | 保持 19000 本地路径 | 是 | 必须 task_id、paste_only、sent=false |
| `19000 /agent/tasks/poll-and-detect` | POST | `app/local_agent_main.py` | wechat-assistant | 保持 19000 本地路径 | 是 | 必须 read_only、不调 input_writer |
| `19000 /agent/wechat/*` | GET/POST | `app/local_agent_main.py` | wechat-assistant | 保持 19000 本地路径 | 是 | Windows 本机安全边界 |

### 4.6 小高算力 `compute`

| 当前 path | HTTP method | 当前 router | 归属能力 | 未来目标 path | 是否需要旧接口兼容 | 是否涉及权限 / merchant_id / tenant_id |
|---|---|---|---|---|---|---|
| `/compute/summary` | GET | `compute.py` | compute | `/api/compute/summary` | 是 | 是 |
| `/compute/transactions` | GET | `compute.py` | compute | `/api/compute/transactions` | 是 | 是 |
| `/compute/packages` | GET | `compute.py` | compute | `/api/compute/packages` | 是 | 是 |
| `/compute/recharge-orders` | POST | `compute.py` | compute | `/api/compute/recharge-orders` | 是 | 是，不引入真实支付 |
| `/admin/compute/packages` | GET/POST | `compute.admin_router` | compute | `/api/compute/admin/packages` | 是 | 是，超管权限 |
| `/admin/compute/packages/{package_id}` | PUT/DELETE | `compute.admin_router` | compute | `/api/compute/admin/packages/{package_id}` | 是 | 是，超管权限 |
| `/admin/compute/accounts/{merchant_id}/recharge` | POST | `compute.admin_router` | compute | `/api/compute/admin/accounts/{merchant_id}/recharge` | 是 | 是，超管权限 |
| `/admin/compute/accounts/{merchant_id}/grant-package` | POST | `compute.admin_router` | compute | `/api/compute/admin/accounts/{merchant_id}/grant-package` | 是 | 是，超管权限 |
| `/internal/compute/usage` | POST | `compute.internal_router` | compute | `/api/compute/internal/usage` | 是 | 是，internal token / 服务间鉴权待补 |

### 4.7 统一知识库训练 `knowledge`

| 当前 path | HTTP method | 当前 router | 归属能力 | 未来目标 path | 是否需要旧接口兼容 | 是否涉及权限 / merchant_id / tenant_id |
|---|---|---|---|---|---|---|
| `/knowledge-categories` | GET | `knowledge_categories.py` | knowledge | `/api/knowledge/categories` | 是 | 是 |
| `/knowledge-categories` | POST | `knowledge_categories.py` | knowledge | `/api/knowledge/categories` | 是 | 是 |
| `/integrations/douyin-ai-cs/rag/documents` | POST | `douyin_ai_cs_proxy.py` | knowledge | `/api/knowledge/rag/documents` | 是 | 是，9000 可信 scope 注入 |
| `/integrations/douyin-ai-cs/rag/train` | POST | `douyin_ai_cs_proxy.py` | knowledge | `/api/knowledge/rag/train` | 是 | 是，9000 可信 scope 注入 |
| `9100 /rag/documents` | POST | `apps/xg_douyin_ai_cs.routers.rag` | knowledge | 保持 9100 内部路径或迁入 knowledge 服务 | 是 | 是，scope 来自 9000 |
| `9100 /rag/train` | POST | `apps/xg_douyin_ai_cs.routers.rag` | knowledge | 保持 9100 内部路径或迁入 knowledge 服务 | 是 | 是，scope 来自 9000 |
| `9100 /rag/search` | POST | `apps/xg_douyin_ai_cs.routers.rag` | knowledge | 保持 9100 内部调试路径 | 是 | 是，不应信任前端 scope |
| `9100 /categories` | GET | `apps/xg_douyin_ai_cs.routers.categories` | knowledge | 后续由 knowledge 分类统一提供 | 是 | 否，当前 demo 分类 |

## 5. 服务依赖图

```text
React 前端
  -> 9000 gateway / main-api
       -> 登录态 / RequestContext / merchant_id 注入 / 权限校验
       -> 旧接口兼容层
       -> /api/{capability}/health
       -> SQLite DB（第一阶段继续共享）
       -> Douyin upstream / douyinAPI（线索同步、历史参考）
       -> 9100 RAG / LLM 服务（reply-suggestion、RAG 文档、训练、搜索）
       -> 19000 Local Agent（仅通过任务轮询和本机调用链，不直接操作微信）

9201 douyin-cs
  <- 9000 gateway 转发或内部 client
  -> Douyin OpenAPI
  -> 9100 RAG / LLM
  -> SQLite DB（第一阶段共享）

9202 leads
  <- 9000 gateway 转发或内部 client
  -> Douyin upstream / webhook 事件源
  -> SQLite DB（第一阶段共享）

9203 agents
  <- 9000 gateway 转发或内部 client
  -> knowledge 分类绑定 client
  -> douyin-cs 企业号绑定 client
  -> SQLite DB（第一阶段共享）

9204 wechat-assistant
  <- 9000 gateway 转发或内部 client
  -> 19000 Local Agent（客户 Windows 本机）
  -> SQLite DB（第一阶段共享）

9205 compute
  <- 9000 gateway 转发或内部 client
  <- 9100 compute usage client
  -> SQLite DB（第一阶段共享）

9206 knowledge
  <- 9000 gateway 转发或内部 client
  -> 9100 RAG / LLM 或承接后续 RAG API
  -> SQLite DB（第一阶段共享）

9100 RAG / LLM
  <- 9000 trusted proxy
  -> 9100 自有 SQLite RAG DB
  -> LLM / Embedding Provider
  -> 9000 /internal/compute/usage（当前 client）

19000 Local Agent
  <- 浏览器所在电脑 127.0.0.1:19000
  -> 9000 /wechat-tasks 等任务接口
  -> Windows 微信 UI / OCR / UI Automation
```

## 6. 推荐迁移顺序

### Phase 3-B：compute 能力迁移

优先级最高。原因：

1. 文件边界最清晰，主要集中在 `app/routers/compute.py`、`app/services/compute_service.py`、`Compute*` schema/model。
2. 与 webhook、19000、私信发送链路无直接耦合。
3. 业务安全边界明确：本阶段仍不引入真实支付，只保留 mock 充值订单和现有扣费语义。
4. 可以最早验证 gateway 旧接口兼容和能力服务新接口并存模式。

### Phase 3-C：knowledge 能力迁移

第二优先级。原因：

1. `knowledge_categories` 与 RAG proxy 已有较清晰边界。
2. 需要谨慎处理 9000 可信 scope 注入和 9100 RAG 的关系。
3. 不建议直接搬 9100 RAG DB；先迁 9000 分类和可信代理，再决定是否由 9206 承接 RAG 文档/训练入口。

### Phase 3-D：agents 能力迁移

第三优先级。原因：

1. Agent CRUD 边界清晰。
2. 与 knowledge 分类绑定、douyin-cs 企业号绑定存在双向业务关系。
3. 应在 knowledge 分类 API 稳定后迁移，避免跨服务直接 import。

### Phase 3-E：leads 能力迁移

第四优先级。原因：

1. 线索列表、详情、统计可以先迁。
2. webhook 直收、线索生成、同步、分配、微信任务联动较复杂。
3. 迁移时必须保持 `/webhook/douyin` 旧入口和验签不变。

### Phase 3-F：douyin-cs 能力迁移

第五优先级。原因：

1. 依赖抖音 OpenAPI、企业号授权、私信发送、9100 reply-suggestion、AI 回复记录、自动回复门禁。
2. `manual_confirmed=true`、`auto_send=false`、Agent 绑定、知识分类消费链路均是高风险边界。
3. 应在 compute、knowledge、agents 基础能力迁移后再动。

### Phase 3-G：wechat-assistant 网关化与边界隔离

最后迁移。原因：

1. 19000 Local Agent、`input_writer`、微信 UI 自动化、OCR、运行锁都是最高风险边界。
2. 当前安全验收依赖 `task_id` 指定执行、`paste_only`、`read_only`、`sent=false`。
3. 迁移前必须先有完整的网关转发、Agent 身份、任务归属、运行锁和回滚方案。

## 7. 每个能力的迁移策略

### 7.1 compute

| 项目 | 策略 |
|---|---|
| 可先搬 router | `app/routers/compute.py` 的商户、超管、internal 三组 router 可以最先迁到 `apps/compute/router.py` |
| 可先搬 service | `app/services/compute_service.py` |
| 暂留共享层 | `ComputeAccount`、`ComputeTransaction`、`ComputePackage` 先留在 `app/models.py` 或后续抽到 `packages/common/models_compute.py`，本轮不拆库 |
| schema 策略 | `Compute*` DTO 可复制到 `apps/compute/schema.py`，旧 `app/schemas.py` 保留 re-export 或兼容定义 |
| 必须测试 | `tests/test_compute_router.py`、`tests/test_compute_service.py`、`tests/test_compute_models.py`、`tests/test_compute_usage_client.py` |
| 旧接口兼容 | 9000 保留 `/compute/*`、`/admin/compute/*`、`/internal/compute/usage`，内部转发到 9205 或直接调用 client |
| gateway 转发 | 9000 负责 RequestContext、权限、merchant_id 注入；9205 不信任前端传入 merchant_id |

### 7.2 knowledge

| 项目 | 策略 |
|---|---|
| 可先搬 router | `app/routers/knowledge_categories.py`；`douyin_ai_cs_proxy.py` 中 RAG documents/train 可后置拆出 |
| 可先搬 service | `app/services/knowledge_category_service.py` |
| 暂留共享层 | `KnowledgeCategory`、`AgentKnowledgeCategory`、9100 RAG 自有 SQLite 模型 |
| schema 策略 | `KnowledgeCategory*` 放入 `apps/knowledge/schema.py`，旧 `app/schemas.py` 兼容 |
| 必须测试 | `tests/test_knowledge_categories_api.py`、`tests/test_agent_knowledge_categories.py`、`tests/test_xg_douyin_ai_cs_rag.py` |
| 旧接口兼容 | 9000 保留 `/knowledge-categories` 和 `/integrations/douyin-ai-cs/rag/*` |
| gateway 转发 | 9000 注入可信 `tenant_id`、`merchant_id`、`account_open_id`、`category_key` 可见性，禁止前端直接传可信 scope |

### 7.3 agents

| 项目 | 策略 |
|---|---|
| 可先搬 router | `app/routers/agents.py` 中 CRUD 和 training-chat；知识分类绑定可在 knowledge client 稳定后迁 |
| 可先搬 service | `app/services/ai_agent_service.py` |
| 暂留共享层 | `AiAgent`、`AgentKnowledgeCategory`、`DouyinAccountAgentBinding` |
| schema 策略 | `AiAgent*`、`AgentKnowledgeCategories*` 放入 `apps/agents/schema.py`，旧 schema 兼容 |
| 必须测试 | `tests/test_ai_agents.py`、`tests/test_agent_knowledge_categories.py`、`tests/test_douyin_account_agent_binding_service.py` |
| 旧接口兼容 | 9000 保留 `/agents/*` |
| gateway 转发 | 9000 负责权限和商户上下文；9203 通过 knowledge client 查询分类，通过 douyin-cs client 查询企业号绑定，不直接 import 对方 service |

### 7.4 leads

| 项目 | 策略 |
|---|---|
| 可先搬 router | `app/routers/leads.py` 的列表、详情、创建、分配；`reports.py` 的 summary 可同步迁 |
| 可先搬 service | `lead_service.py`、`lead_management_service.py`、`report_service.py`、`contact_extractor.py` |
| 暂缓搬迁 | `integrations.py` 中 webhook、`douyin_webhook.py`、`douyin_sync_service.py` 的自动分配和自动通知联动 |
| 暂留共享层 | `DouyinLead`、`DouyinWebhookEvent`、`LeadFollowupRecord`、`SalesStaff`、`ReplyCheck` |
| schema 策略 | `Lead*`、`WebhookEvent*`、`Report*` 可分批迁到 `apps/leads/schema.py` |
| 必须测试 | `tests/test_leads_management.py`、`tests/test_leads_contact_fields.py`、`tests/test_douyin_sync.py`、`tests/test_douyin_webhook.py`、`tests/test_webhook_events.py` |
| 旧接口兼容 | 9000 保留 `/leads/*`、`/reports/summary`、`/integrations/douyin/sync-leads`、`/webhook/douyin` |
| gateway 转发 | webhook 入口仍由 9000 先验签，再内部调用 leads；同步入口由 9000 注入 RequestContext 后调用 9202 |

### 7.5 douyin-cs

| 项目 | 策略 |
|---|---|
| 可先搬 router | AI 回复记录查询、自动回复运行记录查询、资源下载/上传记录查询类只读接口 |
| 暂缓搬迁 router | 私信发送、webhook observe/callback、reply-suggestion 可信代理、自动回复配置写入 |
| 可先搬 service | `ai_reply_decision_log_query_service.py`、`ai_auto_reply_run_query_service.py`、`douyin_openapi_client.py` |
| 暂缓搬迁 service | `douyin_private_message_send_service.py`、`ai_auto_reply_send_service.py`、`ai_auto_reply_dry_run_service.py`、`douyin_autoreply_gate_service.py` |
| 暂留共享层 | `DouyinAuthorizedAccount`、`DouyinWebhookEvent`、`DouyinPrivateMessageSend`、`AiReplyDecisionLog`、`AiAutoReplyRun`、`ConversationAutopilotState` |
| schema 策略 | `Douyin*`、`AiReplyDecisionLog*`、`AiAutoReplyRun*` 分批放入 `apps/douyin_cs/schema.py` |
| 必须测试 | `tests/test_douyin_live_check.py`、`tests/test_douyin_accounts_router.py`、`tests/test_douyin_ai_cs_proxy.py`、`tests/test_ai_reply_decision_logs_api.py`、`tests/test_ai_auto_reply_*` |
| 旧接口兼容 | 9000 保留 `/douyin-live-check/*`、`/integrations/douyin/accounts/*`、`/integrations/douyin-ai-cs/*`、`/ai-reply-decision-logs/*` |
| gateway 转发 | 9000 必须继续作为可信权限源和最终安全后处理层；`auto_send=false` 在 9000 和 9100 双侧强制 |

### 7.6 wechat-assistant

| 项目 | 策略 |
|---|---|
| 可先搬 router | `agent.py` 心跳和状态接口可先迁；其余任务和 UI 自动化接口暂缓 |
| 暂缓搬迁 router | `wechat_tasks.py`、`lead_notifications.py`、`replies.py`、`feedback.py`、`wechat_auto_detect.py`、`automation_control.py` |
| 可先搬 service | `agent_status_service.py` |
| 暂缓搬迁 service | `wechat_task_service.py`、`notification_service.py`、`wechat_ui_reply_service.py`、`automation_control.py`、`hotkey_listener.py`、`desktop_overlay.py` |
| 暂留共享层 | `WechatTask`、`LeadNotification`、`ReplyCheck`、`CheckConfig`、`DouyinLead`、`SalesStaff` |
| schema 策略 | `WechatTask*`、`Agent*`、`Notification*` 后续放入 `apps/wechat_assistant/schema.py` |
| 必须测试 | `tests/test_p0_main_5b_poll_and_execute.py`、`tests/test_p1_auto_1c_poll_and_detect.py`、`tests/test_p1_auto_1d_fix4_safe_json.py`、`tests/test_local_agent_heartbeat.py`、`tests/test_agent_status.py` |
| 旧接口兼容 | 9000 保留 `/wechat-tasks/*`、`/agent/*`、`/lead-notifications/*`、`/replies/*`、`/automation/*` |
| gateway 转发 | 9000 不直接操作微信；19000 继续只监听本机；poll-and-detect 禁止调用 `input_writer`；任务必须支持 `task_id` 指定执行 |

## 8. 旧接口兼容策略

1. 第一阶段迁移不得删除旧 9000 path。
2. 旧 path 的响应结构、状态码、鉴权行为保持不变。
3. 新能力服务 path 建议统一挂在 `/api/{capability}` 后面，但前端继续可以调用旧 path。
4. 9000 gateway 负责：
   - 登录态识别。
   - `RequestContext` 构造。
   - `merchant_id` / `tenant_id` 注入。
   - 权限校验。
   - 统一响应兼容。
   - 通过 `packages/clients` 或 HTTP/internal API 调用能力服务。
5. 能力服务之间禁止直接 import 对方业务 service。跨服务调用必须通过 client 或 HTTP/internal API。
6. 共享工具和 DTO 只能进入 `packages/common` 或 `packages/clients`；共享数据库模型在拆库前暂时保留现状。

## 9. 风险边界

### 9.1 webhook 验签

1. 禁止破坏 `/webhook/douyin` 和 `/integrations/douyin/webhook` 的验签一致性。
2. 禁止修改签名算法：`sha256Hex(SECRET_KEY + body + "-" + timestamp)`。
3. 禁止改变 production 强制验签边界。
4. webhook 迁移时必须由 9000 gateway 先读取原始 body 并完成验签，再调用后续能力服务。

### 9.2 抖音私信发送

1. 私信发送必须继续要求 `manual_confirmed=true`。
2. `auto_send=false` 不允许放宽。
3. reply-suggestion 链路必须继续由 9000 做最终安全后处理。
4. 前端不得传入可信 `allowed_category_keys` 或可信 `agent_config`。
5. 自动回复 dry-run 和真实发送能力不得在本阶段开启。

### 9.3 19000 Local Agent 与微信 UI 自动化

1. 19000 Local Agent 不进入本轮迁移。
2. 禁止修改 `input_writer`、`contact_searcher`、微信窗口定位、OCR、剪贴板、安全门禁。
3. `poll-and-execute` 只能处理 `notify_sales`，且保持 `paste_only` 和 `sent=false`。
4. `poll-and-detect` 只能处理 `detect_reply`，必须 `read_only`，不调用 `input_writer`，不写输入框，不按 Enter，不发送消息。
5. 任务执行必须继续支持 `task_id` 指定执行，避免旧 pending 队列阻塞。

### 9.4 数据库与迁移

1. Phase 3-A 不做 DB 拆库。
2. Phase 3-B 到 Phase 3-G 第一轮迁移可以继续共享同一个 SQLite 数据库文件。
3. 不新增 migration。
4. 不修改 `app/models.py` 字段、索引、表名和默认值。
5. 后续拆模型前必须先补兼容测试和回滚方案。

### 9.5 算力与支付

1. 不引入真实支付。
2. `/compute/recharge-orders` 保持 mock 订单语义，不真实到账。
3. `/internal/compute/usage` 迁移时必须保持当前扣费语义和幂等边界。
4. 9100 compute usage client 后续只能通过 internal API 或 client 调用 compute，不能直连 compute service 业务函数。

### 9.6 NewCarProject 登录 / 权限门面

1. 不修改 token/cookie 识别逻辑。
2. 不修改权限字典语义。
3. 不绕过 `RequestContext`。
4. 能力服务不能信任前端传入的 `merchant_id`、`tenant_id`。
5. gateway 仍是登录态、权限、商户上下文的权威边界。

## 10. 后续阶段测试清单

### 10.1 通用测试

1. 每个能力服务 `/`、`/health`、`/openapi.json`。
2. 9000 `/api/{capability}/health`。
3. 旧接口 path 兼容。
4. gateway 注入 RequestContext 和权限后再调用能力服务。
5. 能力服务之间不存在直接 import 对方业务 service。

### 10.2 compute 迁移测试

1. `tests/test_compute_router.py`
2. `tests/test_compute_service.py`
3. `tests/test_compute_models.py`
4. `tests/test_compute_usage_client.py`
5. 旧 `/compute/*`、`/admin/compute/*`、`/internal/compute/usage` 兼容测试。

### 10.3 knowledge 迁移测试

1. `tests/test_knowledge_categories_api.py`
2. `tests/test_agent_knowledge_categories.py`
3. `tests/test_xg_douyin_ai_cs_rag.py`
4. RAG documents/train 可信 scope 注入测试。
5. 前端不传 `merchant_id` / `tenant_id` / `allowed_category_keys` 的安全测试。

### 10.4 agents 迁移测试

1. `tests/test_ai_agents.py`
2. `tests/test_agent_knowledge_categories.py`
3. Agent 归属校验测试。
4. 企业号绑定跨能力 client 测试。

### 10.5 leads 迁移测试

1. `tests/test_leads_management.py`
2. `tests/test_leads_contact_fields.py`
3. `tests/test_douyin_sync.py`
4. `tests/test_douyin_webhook.py`
5. `tests/test_webhook_events.py`
6. `/webhook/douyin` 旧入口兼容和验签测试。

### 10.6 douyin-cs 迁移测试

1. `tests/test_douyin_live_check.py`
2. `tests/test_douyin_accounts_router.py`
3. `tests/test_douyin_ai_cs_proxy.py`
4. `tests/test_ai_reply_decision_logs_api.py`
5. `tests/test_ai_auto_reply_dry_run.py`
6. `tests/test_ai_auto_reply_send_service.py`
7. 强制 `auto_send=false`、`manual_confirmed=true` 测试。

### 10.7 wechat-assistant 迁移测试

1. `tests/test_p0_main_5b_poll_and_execute.py`
2. `tests/test_p1_auto_1c_poll_and_detect.py`
3. `tests/test_p1_auto_1d_fix4_safe_json.py`
4. `tests/test_local_agent_heartbeat.py`
5. `tests/test_agent_status.py`
6. `sent=false`、`paste_only`、`read_only`、`task_id`、安全 JSON 序列化测试。

## 11. Phase 3-B 执行前准入清单

进入 compute 迁移前必须确认：

1. 9000 gateway 旧接口兼容策略已经确定。
2. 9205 compute 服务启动、health、openapi 测试存在。
3. `packages/clients` 中 compute client 设计完成，避免其他服务直接 import compute service。
4. `RequestContext`、权限和商户上下文仍由 9000 注入。
5. 不新增 migration，不改变 `Compute*` 模型。
6. 不引入真实支付。
7. `/internal/compute/usage` 调用方和扣费语义有回归测试。

## 12. 本轮审计结论

1. 当前最适合先迁移的是 `compute`，不是抖音客服或 19000。
2. `knowledge`、`agents` 可以在 compute 之后迁移，但必须先明确跨能力 client。
3. `leads` 涉及 webhook、线索生成、同步、分配和微信任务联动，应晚于基础能力迁移。
4. `douyin-cs` 涉及私信发送、9100 RAG/LLM、AI 回复记录、自动回复安全门禁，应在 knowledge/agents 基础稳定后迁移。
5. `wechat-assistant` 涉及 19000、`input_writer`、微信 UI 自动化、OCR、安全锁，应最后迁移，并且优先做网关化和边界隔离，不直接搬动自动化实现。
6. 本阶段没有必要也不允许做数据库拆分、接口行为变更或业务代码搬迁。
