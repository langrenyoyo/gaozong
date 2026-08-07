# M01 真实运行链路

> source_baseline: c26ec227e70d | 所有链路附 file:line 证据

## 端到端全链路

```
GMP webhook
  → /integrations/douyin/webhook 或 /webhook/douyin(COMPAT)
  → _handle_douyin_webhook (integrations.py:459)
    → verify_signature (douyin_webhook.py:70, SHA256(SECRET+body+"-"+timestamp))
    → has_encoded 解码 (integrations.py:540, _try_decode_masked_text, 仅 im_receive_msg)
    → LEADS_WEBHOOK_INTERNAL_ENABLED ? 9202 internal : 9000 本地 (integrations.py:566)
    → process_webhook_event (douyin_webhook.py:1043)
      → claim_webhook_event 原子占位 (idempotency_service.py:54, ON CONFLICT DO NOTHING)
      → 胜出者: upsert_lead_from_webhook (douyin_webhook.py:678, douyin_leads)
      → _post_process_im_send_msg (douyin_webhook.py:1272, 标记 manual_takeover)
      → enqueue_auto_reply_run (douyin_webhook.py:1224, ai_auto_reply_runs pending, 仅 flush)
    → maybe_schedule_ai_auto_reply (integrations.py:272)
      → BackgroundTask _wake_outbox_scheduler → run_outbox_cycle (outbox_service.py:544)
        → recover_expired_leases → claim_next_batch (条件 UPDATE + lease_owner)
        → _process_one → _run_with_session_for_outbox (dry_run_service.py:66)
          → _run_with_session (dry_run_service.py:97)
            → event_load → dedupe_check → agent_binding(resolve_webhook_bound_agent)
            → account_settings → latest_message_state
            → pre_llm_gate (gate_service.py:63, manual_takeover/频率/消息方向)
            → build_reply_conversation_context (douyin_conversation_history_service.py)
              → 读取会话历史(脱敏) + customer_memory + CustomerProfile(merge)
              → build_request_contact_state (contact_state_service.py:183)
            → agent_config 组装 (dry_run_service.py:315-336, binding.agent DB)
            → 9100 suggest_reply (xg_douyin_ai_cs_client.py:52, HTTP)
              → 9100 build_reply_suggestion (reply_decision_service.py)
                → resolve_reply_agent(agent_config) → _merge_agent_into_prompt
                → RAG search_with_diagnostics (rag_enabled 由 allowed_category_keys 推导)
                → _build_fixed_prompt_template(固定V2.0) + 商户system_prompt + 运行时约束
                → LLM chat (OpenAICompatibleClient, :1060)
                → _apply_safety_postprocess (hard guard + prompt_injection 确定性检测)
                → 算力上报 compute_usage_client.report_usage (capability_key=douyin-cs)
            → customer_profile 持久化 (dry_run_service.py:437-493, 代码层校验+confirmed写入)
            → post_llm_gate (gate_service.py:117, hard_block/manual_required/risk_flags/require_rag)
            → record_ai_reply_decision (ai_reply_decision_log_service.py:18)
            → _finish_run (decided + auto_send 收敛)
            → send_ai_auto_reply_for_run (send_service.py:126, lease_owner 贯穿)
              → 检查点1 decided→send_processing
              → real_send_gate (gate_service.py:209)
              → manual_takeover_gate (send_service.py:252, conversation_autopilot_state)
              → latest_message_recheck (send_service.py:268, outbound_after_trigger/changed)
              → 检查点2 send_processing→send_authorized
              → _send_private_message_with_context (private_message_send_service.py:102)
                → 创建 DouyinPrivateMessageSend(pending) → call_douyin_openapi(/send_msg)
                → 成功: upstream_msg_id 回写, status=sent
              → 终态 sent (guarded UPDATE, mark_ai_replied)
```

## M01-A 入口与会话

### webhook 入口
- 代码：`integrations.py:459-592`（_handle_douyin_webhook）
- 入口路由：`integrations.py:845`（主）/ `integrations.py:867`（COMPAT）
- 幂等：`idempotency_service.py:54`（INSERT ON CONFLICT DO NOTHING RETURNING，胜出者 won=True）
- has_encoded 解码：`integrations.py:540-555`（DOUYIN_DECODE_MASKED_ENABLED + im_receive_msg）
- internal 模式：`integrations.py:566`（LEADS_WEBHOOK_INTERNAL_ENABLED → 9202 LeadsClient）

### 会话聚合
- 代码：`douyin_workbench_conversation_service.py`
- 增量协议：`after_event_id` 游标（:742 cursor_mode）
- 已读状态：`mark_conversation_read`（:449-567，条件 UPDATE 推进水位）
- 未读数：`get_account_unread_counts`（权威，不从页求和）

### Lead 更新
- 代码：`douyin_webhook.py:678-860`（upsert_lead_from_webhook）
- 聚合键：`(account_open_id, conversation_short_id)`（:733-738）
- 跨租户防御：`_detect_tenant_scope_conflict`（:744-762）
- SAVEPOINT 隔离：`:787-790`

## M01-B 编排

### webhook→AiAutoReplyRun
- 同事务 enqueue：`douyin_webhook.py:1222-1234`（enqueue_auto_reply_run，仅 flush）
- BackgroundTask wake：`integrations.py:336-340`（_wake_outbox_scheduler → run_outbox_cycle）
- 受 AI_AUTO_REPLY_OUTBOX_ENABLED 开关

### outbox claim/lease/retry
- run_outbox_cycle：`outbox_service.py:544-607`（单飞锁+rearm+recover→claim→process→compensate→alert）
- claim_next_batch：`outbox_service.py:200-265`（条件 UPDATE + lease_owner + lease_expires_at）
- guarded 推进：`_guarded_lease_update`（:58-94，校验 expected_status + 原始 owner + 未过期）
- recover_expired_leases：`:271-351`（processing→pending；send_authorized 按流水对账不重发）
- retry 退避：`dry_run_service.py:921-986`（BACKOFF_1=60s/BACKOFF_2=300s，超限→failed）

### dry-run 编排
- _run_with_session：`dry_run_service.py:97-620`
- 编排顺序：event_load→dedupe→agent_binding→settings→latest_message→pre_gate→context→9100→profile→post_gate→decision_log→finish→send

## M01-C Agent/Prompt/9100 Contract

### Agent binding
- 兼容入口：`douyin_ai_cs_binding_service.py:21-79`（_find_authorized_account 四级匹配）
- 权威服务：`douyin_account_agent_binding_service.py:333-399`（merchant/账号/agent 三重校验）
- webhook 解析：`resolve_webhook_bound_agent`（:402-494，不依赖 RequestContext）

### agent_config 组装（三处一致）
- auto-reply：`dry_run_service.py:315-336`（binding.agent DB）
- 会话预览：`douyin_ai_cs_proxy.py:322-343`（agent DB + getattr）
- preview：`agents.py:241-262`（前端 payload 草稿）
- 字段：13 基础 + 10 商家变量，三处完全一致

### Prompt 三层
1. 固定模板：`reply_decision_service.py:1411-1735`（V2.0 硬编码，13 变量占位）
2. 商户 system_prompt：`:839` resolve_reply_agent（config.system_prompt or config.prompt）
3. 运行时约束：`:3051-3073` known_customer_info（budget/brand/city/salutation/contact_invalid）

### RAG 触发
- rag_enabled：`reply_decision_service.py:3746-3760`（显式或 allowed_category_keys 非空）
- 检索：`:677-690` search_with_diagnostics（unified KB scope，top_k=5）

## M01-D 客户事实

### contact_state
- 单一可信源：`contact_state_service.py:183-298` build_request_contact_state
- current vs known_valid 分离：current=当前消息状态，known_valid=Lead 严格验证
- 禁止 has_contact 直接升级 VALID（:225-231）

### CustomerProfile
- 读取：`customer_profile_service.py:34-67` load_customer_profile
- 合并：`:187-238` merge_profile_with_memory（DB优先+field_sources标注）
- 写入：`:70-148` upsert_customer_profile（SAVEPOINT+confirmed/inferred 分层）
- 代码层校验：`dry_run_service.py:437-493`（只写客户消息有依据的字段）

### 空号追问接入点（M01 侧）
1. 块3 触发：`admin_contact_invalid_mark.py:46-143`（admin 标记→create_followup_task）
2. 块2 状态迁移：`customer_profile_service.py:256-301` mark_contact_invalid / `:304-342` recover
3. 块4 Prompt 兜底：`reply_decision_service.py:3068-3069,1725-1734`（contact_invalid 注入+规则）
4. webhook 自动恢复：`douyin_webhook.py:1194-1211` recover_contact_valid
5. UI 回复标记/恢复：`wechat_ui_reply_service.py:403-436`
- **auto_reply 仅只读镜像**（merge_profile_with_memory :228-237），不直接 mark/recover

## M01-E 决策门禁

### pre-LLM gate
- 代码：`gate_service.py:63` evaluate_pre_llm_gates
- 链：settings缺失→manual_takeover阻断→latest_message_not_customer→每小时频控

### post-LLM gate
- 代码：`gate_service.py:117` evaluate_post_llm_gates
- 链：empty_reply→send_disabled→HARD_BLOCK(3flag不可豁免)→manual_required(可豁免)→risk_flags转人工→intent→confidence→require_rag→require_rag_sources
- HARD_BLOCK_RISK_FLAGS：hard_false_contact_confirmation / hard_reask_contact_after_valid / hard_off_platform_detail_promise

### auto_send 三层收敛
- 9100 返回值 → 9000 post-gate 收敛（:512-517）→ 真实发送条件（:567-570, decided+real_send+auto_send=True）

### hard guard
- 代码：`apps/.../reply_hard_rules.py`
- 虚假确认/重复索要/资料承诺（3 个不可豁免 flag）
- unfounded_contact_followup_commitment **已停用**（:116-125 返回 None）
- prompt_injection 在 9100 侧确定性检测（`reply_decision_service.py:2392`），不进 9000 HARD_BLOCK

### latest_message_changed
- 仅在发送服务：`send_service.py:268-288`（outbound_after_trigger/latest_message_changed/send_context 校验）
- pre-LLM 侧只查 latest_is_customer_message

### 24h 窗口
- 不在 gate_service，在 `douyin_private_message_send_service.py:251-261` _is_context_expired

## M01-F 发送

### 真实发送
- 代码：`ai_auto_reply_send_service.py:126-404`
- 链：mode_check→decision_gate→dedupe→sanitize→检查点1→real_send_gate→manual_takeover→latest_recheck→检查点2→_send_private_message_with_context→终态

### send_source 白名单
- ai_auto：`send_service.py:336`
- return_visit_auto：`return_visit_run_service.py:928`
- contact_invalid_followup：`contact_invalid_followup_service.py:249`
- manual：`douyin_private_message_send_service.py:95`
- 校验：`douyin_private_message_send_service.py:29-33`（未知 source 拒绝发送）

### im_send_msg 回执
- 创建流水(pending)→调上游 /send_msg→成功回写 upstream_msg_id+status=sent
- 代码：`douyin_private_message_send_service.py:102-231`

### AI/人工识别
- classifier：`douyin_outbound_message_classifier.py`
- is_effective_human_outbound_message：im_send_msg+非duplicate+非skip+非AI自动发送
- AI 匹配：查 DouyinPrivateMessageSend.send_source=="ai_auto"

### manual_takeover
- 阻断点：`send_service.py:252-266`
- gate 实现：`conversation_autopilot_state_service.py:62-112`
- 标记触发：webhook im_send_msg 后置 `douyin_webhook.py:1272-1323`

## M01-G 后续能力

### 回访
- 代码：`return_visit_run_service.py`
- 双通道触发：writeback（销售微信反馈）+ silent_scan（沉默扫描）
- 9100 判定→G1-G10 门禁→发送分类
- scheduler：`return_visit_silent_scan_scheduler.py`（RETURN_VISIT_SILENT_SCAN_ENABLED）

### 空号追问
- 主动追问：create_followup_task（状态迁移时创建）→ Worker run_followup_cycle 周期 claim 发送
- 被动兜底：_check_freshness 检测客户发新消息→取消主动追问→交被动 AI 主链路
- 固定话术不依赖 LLM：_build_followup_text
- 门禁：_check_gates（G4 manual_takeover + 24h/send_context）
- scheduler：CONTACT_INVALID_FOLLOWUP_ENABLED（**CONFIG_BYPASS**，直接读 os.environ 未进 config.py）

## M01-H 可观测

### 决策日志
- `ai_reply_decision_log_service.py:18` record_ai_reply_decision
- 写入 AiReplyDecisionLog（全量字段，失败不阻断主链路）

### run 状态流转
- pending→processing→decided→send_processing→send_authorized→sent（成功）
- 失败分支：failed/send_unknown/blocked/skipped/send_skipped/retry_wait

### error stage 分类
- upstream_business_error → failed（终态不重发）
- 其余 → send_unknown（可人工重试，仅 pre_send_temporary_failure 白名单）

### LLM 失败重试
- _handle_llm_failure：attempt_count<=max_retries→retry_wait+退避；超限→failed

### dead task 补偿
- recover_expired_leases：send_authorized 崩溃按流水对账
- compensate_missing_runs：扫描无 run 的客户私信事件幂等补建
- manual_retry_run：仅 failed + 白名单 failure_stage + 无发送流水

### health/readiness
- /health：进程存活即可
- /ready：PG 连接 + database 名 + alembic head + 关键表，失败 503

## 三场景链路差异

| 维度 | Preview | Auto Reply | Training |
|---|---|---|---|
| 入口 | POST /agents/preview | webhook→outbox→dry_run | POST /knowledge-training/ask |
| agent_config 来源 | 前端 payload 草稿 | DB binding.agent | 不注入 |
| 商户变量 | 前端传入 | DB 真实值 | 全部"未配置" |
| 客户事实 | 前端传入(脱敏) | DB 会话历史+customer_memory+contact_state | 无 |
| LLM 路径 | 9100 build_reply_suggestion | 同 preview（共享） | 独立 _build_answer |
| 真实发送 | 否(auto_send=False硬编码) | 可能(decided+real_send+auto_send) | 否 |
