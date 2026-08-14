# M01 抖音AI小高客服 链路说明

> 状态：G1 BASELINE（2026-08-14，基于 CODE_SOURCE_BASE=88235b5 冻结文件地图）
> 用途：M01 模块的链路骨架，支撑 G3 模块验真与独立验收。G1 阶段只登记事实，不展开 G3 验收。

## 1. Responsibility
- 抖音企业号私信 AI 客服：自动回复、人工接管、违禁词替换、发送 gate、会话历史、AI 回复决策、知识库检索（9100 RAG）。
- **边界红线**：不负责线索沉淀（归 M02，虽共享联系人领域）；不负责抖音账号↔agent 绑定（归 M03，本模块 router `douyin_accounts` 承载账号基础管理，跨 M03）；不负责算力计费（归 M07，但上报由 M01 链路触发）。
- 9100（apps/xg_douyin_ai_cs）为 M01 的 RAG/LLM 客服子应用；9000 通过 `douyin_ai_cs_proxy` 代理调用。

## 2. User Entrypoints
- 商户/管理员在 5173 前端「抖音AI客服」工作台查看会话、回复决策、自动回复运行、直播检查。
- 抖音用户私信企业号 → GMP webhook → 9000 → 触发自动回复链路。

## 3. Frontend Entrypoints
- feature 目录：`frontend/src/features/douyin-cs/`（workbench / autoreply settings / autoreply runs / reply decision logs / live check / risk flags）。
- 页面：DouyinAiCsWorkbenchPage、DouyinAutoReplySettingsPage、DouyinAutoReplyRunsPage、AiReplyDecisionLogsPage、DouyinLiveCheckPage、SuperAiReplyRecords、SuperForbiddenWords、SuperFollowUpPrompts、AdminAutoreplyRolloutPage。
- API clients：douyinCs、douyinAiCsClient、douyinAutoReplySettings、aiAutoReplyRuns、aiReplyDecisionLogs、forbiddenWords、douyinLiveCheck、adminAutoreplyRollout。
- 共享组件：components/douyin-ai-cs/ReplyDecisionPanel、feature douyin-cs/ReplyDecisionPanel。

## 4. Backend API Entrypoints
- `app/routers/douyin_ai_cs_proxy.py`：9000→9100 客服代理（含 Trusted Reply-Suggestion 幂等透传，closure cab2e96）。
- `app/routers/ai_reply_decision_logs.py`、`ai_auto_reply_runs.py`、`douyin_autoreply_settings.py`、`admin_autoreply_rollout.py`、`forbidden_words.py`、`douyin_live_check.py`、`douyin_accounts.py`（跨 M03）。
- 自动回复入站：`app/routers/integrations.py`（M02 MIXED 的 webhook 主入口）→ `app/services/webhook_event_service.py`（M02）→ 客服链路。
- 鉴权上下文：`auto_wechat:douyin_ai_cs` 权限码（workbench），全部经 PLATFORM-AUTH。

## 5. Core Services
- `app/services/`：douyin_autoreply_gate_service（PLATFORM-GATE）、ai_auto_reply_outbox_service（PLATFORM-OUTBOX）、ai_auto_reply_send_service、ai_auto_reply_dry_run_service、ai_auto_reply_run_query_service、ai_auto_sent_message_matcher、ai_auto_reply_content_sanitizer、conversation_autopilot_state_service、douyin_conversation_history_service、douyin_workbench_conversation_service、douyin_outbound_message_classifier、douyin_private_message_send_service、douyin_ai_cs_binding_service、autoreply_admin_rollout_service、ai_reply_decision_log_service/query、douyin_live_check_service、forbidden_word_service、douyin_image_upload_service、xg_douyin_ai_cs_client（HTTP client）。
- 9100 子应用 `apps/xg_douyin_ai_cs/`：llm/（ark client、embedding）、rag/（chunker、repository、vector_store）、services/（agent_runtime、reply_kernel、reply_hard_rules、reply_decision_service、knowledge_training_service、vector_store）、routers/（9 个，RAG ask/ingest/search-preview/training 等）。

## 6. Data Ownership
- 9000 库表：douyin_ai_agents、douyin_autoreply_settings、ai_auto_reply_runs、ai_reply_decision_logs、forbidden_words、ai_preview_executions（F-1 幂等复用）、douyin_conversations（增量）。
- 9100 库（xg_douyin_ai_cs）：documents、chunks、feedback、training_run、chat_history 等 metadata（真源=PG；Milvus 仅 embedding+向量副本）。
- 被其他模块读写：douyin_accounts（M03 绑定）、compute usage 上报（M07 计费，见 §9）。

## 7. Async / Worker Chain
- webhook → `integrations.py` → M02 webhook_event_service → outbox（PLATFORM-OUTBOX）→ ai_auto_reply_send_service（gate 校验）→ douyin_private_message_send_service（真实发送，gate: 违禁词/人工接管/限频/幂等/紧急停止）→ 失败回写。
- 发送后 → 9100 RAG/LLM 决策（proxy + xg_douyin_ai_cs_client）→ 回复决策日志；contact 提取/更新（M02 DOMAIN_SHARED）。
- 直播检查：scheduler 触发 douyin_live_check_service（P1 分队列）。

## 8. External Dependencies
- Douyin GMP：webhook 回调（AUTH：签名验证；INPUT：消息/事件；FAILURE：接收失败 retry）。
- Douyin OpenAPI（douyin_openapi_client，PLATFORM）：私信 API、解码（decode_msg_content 已上线）。
- 火山 Ark LLM + Embedding（9100 llm/）：生成回复与向量（FAILURE：降级 RAG）。
- Milvus：向量检索副本（FAILURE：降级 SQLite/PG 检索，禁因 active=0 跳过）。
- NewCarProject：商户/账号/权限权威（AUTH 来源，`auto_wechat:douyin_ai_cs`）。

## 9. Cross-Module Calls
- CALLS：M02（webhook_event_service 消费消息、contact_* DOMAIN_SHARED、lead 创建）、M03（agent 配置判定是否自动回复）、M07（compute_usage_client 上报 LLM/embedding 用量，M07 consumer 幂等键）。
- READS：M05 素材（客服发素材场景，扩展）；M06 剪辑结果（未启用）。
- AUTHORIZES：经 PLATFORM-AUTH。
- COMPAT_FOR：apps/douyin_cs（旧子应用 META 被 capability_gateway 引用）。

## 10. Auth / Merchant Boundary
- 权限码：`auto_wechat:douyin_ai_cs`（workbench 主码）；发送动作受 PLATFORM-GATE 管控。
- merchant/tenant 隔离：douyin_merchant_isolation（PLATFORM-ISO）校验账号归属与可信商户过滤；前端传入的 tenant/merchant/douyin_account_id 不可信。
- token：前端不持有 internal token；9100 调用经 9000 proxy（COMPUTE_INTERNAL_TOKEN 仅服务端）。

## 11. Compatibility Layer
- apps/douyin_cs 旧子应用：COMPAT，META 被 capability_gateway.py 引用；service 语义已被 9000 services 吸收。removal_prerequisite：capability_gateway META 引用迁移。
- douyin_api_client（app/integrations/）：LEGACY_CANDIDATE（LEGACY-003），demo/参考，8081 douyinAPI 非生产依赖。

## 12. Legacy Candidates
- LEGACY-003 douyinAPI client：DEAD_CANDIDATE，无生产调用；风险=低；登记 ≠ 可删除（G2 授权前）。
- 9100 旧 RAG 检索路径（SQLite-only 假设）：P0 已按硬约束修正，登记为已修复事实，非现存 Legacy。

## 13. Known Unknowns
- U-001：douyin_accounts router 的 M01/M03 边界未完全冻结（账号基础管理 vs agent 绑定）。
- U-002：AI 回复决策日志与发送 gate 的完整时序在 staging 未做 E2E 复核（M03 门禁缺口，见 m03-baseline-candidate）。
- U-003：9100 训练/反馈自动入库（training_feedback_auto_ingest）的 PG 事务边界 = PG_VERIFIED_MIDPOINT，生产 RUNTIME_UNKNOWN。
- Milvus canary 与生产容量未复核（G2C Gate 26 记录）。

## 14. Future G3 Acceptance Boundary
- G3 验收应覆盖：webhook 入站→自动回复→真实发送 gate 全链路（违禁词替换/人工接管/限频/幂等/紧急停止）；RAG ask 命中 Milvus 时不得跳过；contact 提取→M02 沉淀；M07 计费幂等（NO_DOUBLE_CHARGE）；商户隔离越权拒绝。G1 阶段不展开。
