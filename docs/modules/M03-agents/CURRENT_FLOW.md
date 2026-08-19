# M03 真实运行链路

> source_baseline: c26ec227e70d | 所有链路附 file:line 证据

## 1. Create 智能体

```
Frontend: SuperMerchantAgent.tsx:609 点"创建智能体" → setEditorAgent(null)
  → :84-367 AgentEditor 弹窗（agent=null 新建模式）
  → :192-206 submit → onSave(payload, categoryKeys)
  → :544-574 saveAgent
API: api/aiAgents.ts:105 createAiAgent(payload) → POST /agents
Router: agents.py:87-98 create_agent → _auth(require_permission "auto_wechat:douyin_ai_cs")
Service: apps/agents/services.py:53-81 create_agent
  → require_context_merchant(context) 取 merchant_id
  → AiAgent(agent_id=f"agent_{uuid4().hex[:16]}", merchant_id=..., ...)
Table: ai_agents (models.py:802-833)
下游: db.add + commit + refresh
  → :552 updateAgentKnowledgeCategories → PUT /agents/{id}/knowledge-categories
  → replace_agent_categories → agent_knowledge_categories 表
```

## 2. Edit 智能体

```
Frontend: SuperMerchantAgent.tsx:676 点编辑 → setEditorAgent(agent)
  → :103-125 useEffect 填充 draft
  → :547 updateAiAgent(agent_id, payload)
API: api/aiAgents.ts:110 → PUT /agents/{agentId}
Router: agents.py:114-126 update_agent → _auth + get_agent(merchant 过滤) → update_agent
Service: apps/agents/services.py:98-122 update_agent
  → payload.model_dump(exclude_unset=True) 仅更新显式字段
  → store_name 同校验（trim 后非空、≤255）；_STORE_CONFIG_FIELDS 门店普通事实字段循环 setattr
Table: ai_agents
```

## 3. Knowledge Binding

```
Frontend: SuperMerchantAgent.tsx:552 updateAgentKnowledgeCategories(agent_id, categoryKeys)
API: api/aiAgents.ts → PUT /agents/{id}/knowledge-categories
Router: agents.py:170-191 → replace_agent_categories(db, context, agent_id, category_keys)
Service: apps/agents/services.py:347-380
  → _get_active_agent(merchant_id 过滤)
  → ensure_category_usable_for_merchant(merchant_id 过滤 KnowledgeCategory)
  → 软删多余绑定行 + bind_agent_categories 补齐
Table: agent_knowledge_categories + knowledge_categories(校验)
```

## 4. Preview（AI回复预览）

```
Frontend: SuperMerchantAgent.tsx 弹窗内触发
API: api/aiAgents.ts → POST /agents/preview
Router: agents.py:194-315 preview_agent
  → _auth + merchant_id 校验
  → 按 agent_id → get_agent(merchant 过滤) 校验归属（P0-V3：配置必须服务端读取）
  → 服务端 list_agent_category_keys 读知识绑定
  → 组装 agent_config dict（唯一白名单构造器 build_agent_config，来源：可信 AiAgent ORM）
    字段：agent_id/agent_name/store_name/status/allowed_category_keys/rag_enabled
          + 门店普通事实字段；不含 system_prompt/prompt/knowledge_base_text/store_phone/store_wechat（R2 完整退出）
  → 补 direct_llm_policy + forbidden_words
  → get_xg_douyin_ai_cs_client().suggest_reply(
        context, conversation_id="agent-preview", request=request_payload)
Client: xg_douyin_ai_cs_client.py:52-65
  → POST /douyin/reply-suggestion 到 9100（仅补 merchant_id + conversation_short_id）
9100: ai_reply.py:20-29 → build_reply_suggestion(conversation_id, request)
  → reply_decision_service.py:677-690 RAG 检索（rag_enabled 由 allowed_category_keys 推导）
  → :1020-1060 真实调用 LLM（OpenAICompatibleClient.chat）
  → :1160-1167 算力消耗上报（capability_key="douyin-cs"）
  → :3783 ComputeUsageClient.report_usage HTTP 到 9000 /internal/compute/usage
返回: agents.py:300-313 reply_text/source/used_category_keys/source_chunks/
      manual_required/llm_used/rag_used/auto_send=False(硬编码)/warnings

★ Preview 绝对不触发真实抖音发送：
  - auto_send=False 硬编码（agents.py:311）
  - 不创建 AiAutoReplyRun，不进入 ai_auto_reply_dry_run_service
  - preview 代码范围 grep send_msg/send_private_message 零命中
```

## 5. Douyin Account Binding

```
入口: M01 binding service（不在 M03 router 直接暴露）
Service: app/services/douyin_account_agent_binding_service.py
  → :128 bind_agent_to_account(merchant_id=context.merchant_id)
  → :333-364 validate_douyin_agent_binding
    → agent.merchant_id != context.merchant_id → AGENT_MERCHANT_DENIED
    → :497-535 _validate_account_context（账号归属校验）
  → super_admin 可绕过（douyin_ai_cs_binding_service.py:42-47，仅留审计 warning）
Table: douyin_account_agent_bindings (models.py:424-447)
  → auto-reply 链路通过它解析 binding.agent 读取 AiAgent
```

## 6. M01 Auto Reply 消费

```
webhook 事件 → run_ai_auto_reply_job(event_id)
  → ai_auto_reply_dry_run_service.py:290-297 build_reply_conversation_context（DB 会话历史）
  → :297 binding.agent（DB AiAgent 模型，从 douyin_account_agent_bindings 解析）
  → :315-336 组装 agent_config（唯一白名单构造器 build_agent_config，来源：binding.agent DB 模型）
    字段结构与 preview 完全一致（agent_id/agent_name/store_name/status/allowed_category_keys/
    rag_enabled + 门店普通事实字段，不含四旧字段）
  → :347-356 _build_request_contact_state（contact_state + customer_memory）
  → :384 调 9100 suggest_reply → build_reply_suggestion（与 preview 同一 9100 管线）
  → :567-570 若 decided + real_send_candidate + auto_send=True → send_ai_auto_reply_for_run（真实发送）
```
