# M01 数据模型

> source_baseline: c26ec227e70d

## M01 拥有的表（11 张）

| 表 | 模型 | OWNER | 关键字段 | 迁移 |
|---|---|---|---|---|
| ai_auto_reply_runs | AiAutoReplyRun (models.py:530) | M01 | status/lease_owner/lease_expires_at/attempt_count/next_attempt_at/last_failure_stage/gate_results_json/mode/decision_log_id | PG 0016 |
| ai_reply_decision_logs | AiReplyDecisionLog (models.py:482) | M01 | risk_flags_json/manual_required/llm_used/rag_used/upstream_auto_send/final_auto_send/raw_response_json | — |
| douyin_private_message_sends | DouyinPrivateMessageSend (models.py:450) | M01 | send_source(manual/ai_auto/return_visit_auto/contact_invalid_followup)/upstream_msg_id/auto_reply_run_id/manual_confirmed/return_visit_run_id | — |
| douyin_account_autoreply_settings | DouyinAccountAutoreplySetting (models.py:576) | M01 | send_enabled/allowed_intents_json/manual_review_risk_flags_json/allow_release_manual_required/direct_llm_policy_json/频控字段 | PG 0018/0020 |
| douyin_webhook_events | DouyinWebhookEvent (models.py:339) | M01 | event/from_user_id/to_user_id/conversation_short_id/server_message_id/raw_body/parsed_content_json/merchant_id/tenant_id/lead_id/event_key(幂等)/is_duplicate | PG 0017(索引) |
| conversation_autopilot_states | ConversationAutopilotState (models.py:693) | M01 | mode(manual/auto)/manual_takeover_until/last_human_message_at | — |
| douyin_conversation_read_states | DouyinConversationReadState (models.py:722) | M01 | merchant_id/account_open_id/conversation_short_id/last_seen_event_id/last_seen_created_at | — |
| douyin_message_resource_downloads | DouyinMessageResourceDownload (models.py:749) | M01 | webhook_event_id/server_message_id/download_url/resource_status | — |
| douyin_image_uploads | DouyinImageUpload (models.py:774) | M01 | request/response_body_json | — |
| customer_profiles | CustomerProfile (models.py:1748) | M01/M02 共享 | gender/preferred_salutation/intent_car/car_year/budget/city/contact_state/confirmed_fields_json/inferred_fields_json/contact_invalid_* | PG 0026/0027 |
| contact_invalid_followup_tasks | ContactInvalidFollowupTask (models.py:1793) | M01/M02 共享 | invalid_version/followup_sequence/status/lease_owner/sent_message_id | PG 0028 |

## CustomerProfile 术语明确

代码实际**无第三个持久化层**。`derived` 不是持久化层，是运行时派生上下文：

- **Persistent（持久层，2 层）**：
  - `confirmed_fields_json` — 客户明确确认的字段集（高可信）
  - `inferred_fields_json` — LLM 推断的字段集（低可信）
  - 顶层业务字段（gender/intent_car/budget 等）— confirmed/inferred 的投影（confirmed 覆盖顶层，inferred 不覆盖 confirmed）
- **Runtime（运行时派生，非持久化）**：
  - `derived` context — 根据 confirmed/inferred/顶层字段 + 当前消息实时派生的运行时事实，**非第三个持久化层**
  - `field_sources` 标注：confirmed > inferred > derived（运行时生成，不落库）

## 商户隔离

所有核心表均按 merchant_id 过滤：
- douyin_webhook_events：`webhook_event_service.py:60` 查询过滤，`douyin_webhook.py:1078-1083` 入库固化归属
- ai_auto_reply_runs：`ai_auto_reply_run_query_service.py:106` 列表/详情过滤，`outbox_service.py:495` 人工重试校验
- ai_reply_decision_logs：`ai_auto_reply_run_query_service.py:155/197` 关联查询过滤
- customer_profiles：`merchant_id+account_open_id+customer_open_id` 唯一约束（models.py:1760）
- merchant_id 均为 nullable=False（硬隔离条件）

## 迁移版本（PG）

| 版本 | 内容 |
|---|---|
| 0016 | outbox 持久化任务字段（lease/attempt/failure_stage）+ 索引 |
| 0017 | webhook_events 商户账号复合索引（CONCURRENTLY） |
| 0018 | autoreply_settings.manual_review_risk_flags_json |
| 0019 | ai_agents 11 个商家可配置变量 |
| 0020 | autoreply_settings.allow_release_manual_required |
| 0026 | customer_profiles 表 |
| 0027 | customer_profiles contact_invalid 字段 |
| 0028 | contact_invalid_followup_tasks 表 |
