# M03 运行时依赖

> source_baseline: c26ec227e70d

## M03 → M01 Runtime（Preview 调 9100）

| 维度 | 事实 |
|---|---|
| 类型 | Runtime Call（R）|
| mechanism | HTTP |
| 调用方 | `app/routers/agents.py:272` preview 端点 |
| 被调方 | `apps/xg_douyin_ai_cs/routers/ai_reply.py:20-29` `/douyin/reply-suggestion` |
| client | `app/services/xg_douyin_ai_cs_client.py:52-65` suggest_reply |
| 走 RAG | 是（`reply_decision_service.py:677-690`，rag_enabled 由 allowed_category_keys 推导） |
| 调 LLM | 是（`:1020,1060` OpenAICompatibleClient.chat） |
| 算力消耗 | 是（`:1160-1167` _report_llm_usage → compute_usage_client.report_usage） |
| 真实发送 | **否**（`agents.py:311` auto_send=False 硬编码） |

## M01 ← M03 agent_config Contract（Payload Boundary）

| 维度 | 事实 |
|---|---|
| 类型 | Contract / Payload（X） |
| 组装方 | 9000（M03 路由组装 agent_config dict） |
| 组装点 | **3 处统一走唯一构造器 `ai_agent_service.build_agent_config`**（P0-V3/R2，字段结构一致）：① `agents.py`（preview，服务端 AiAgent ORM）② `douyin_ai_cs_proxy.py`（会话预览，DB）③ `ai_auto_reply_dry_run_service.py`（auto-reply，DB binding.agent） |
| 9100 消费 | `resolve_reply_agent`（`reply_decision_service.py`）→ `apply_agent_prompt` → `build_llm_messages` |
| Schema | `apps/xg_douyin_ai_cs/schemas.py` AgentConfig（**extra=forbid**） |
| 字段 | agent_id/agent_name/store_name/status/allowed_category_keys/rag_enabled + 门店普通事实字段；**不含 system_prompt/prompt/knowledge_base_text/store_phone/store_wechat（R2 已完整退出，携带即 422）** |
| 仅前端展示 | **无**（构造器从服务端可信 ORM 读取，调用方不得覆盖） |
| 重复组装 | **否**（三处统一调用同一构造器） |
| 正式 Schema | 9100 AgentConfig Pydantic model（extra=forbid） |

## M03 → 知识库 / RAG 实际依赖

| 维度 | 事实 |
|---|---|
| 绑定方式 | `agent_knowledge_categories` 表通过 `category_key` 指向 9100 RAG 分类 |
| M03 直连 Milvus | **否**（M03 不直接依赖 Milvus，经 9100 RAG 检索间接消费） |
| RAG 检索执行方 | 9100（`reply_decision_service.py:678` search_with_diagnostics） |
| 知识库 prompt | 文本知识库存 `ai_agents.knowledge_base_text`；RAG 向量知识经 category_key 绑定在 9100 检索后注入 user payload，不进 system prompt |

## M03 → 平台公共底座

| 底座 | 依赖方式 |
|---|---|
| auth/RBAC | `require_permission("auto_wechat:douyin_ai_cs")`（agents.py:50） |
| 数据库 | SessionLocal + AiAgent/AgentKnowledgeCategory/DouyinAccountAgentBinding ORM |
| 商户隔离 | `require_context_merchant(context)` 从 RequestContext 取 merchant_id |

## Prompt 层级真相

```
最终 system prompt 权威组装点：9100 build_llm_messages（reply_decision_service.py）

  system_parts = [
    _build_fixed_prompt_template(merchant_prompt),     # 固定模板 V3.1（6 节）
    运行时约束追加（留资目标/违禁词/Decision/知识降级/历史信任/联系方式状态）
  ]

R2：Agent system_prompt 已完全删除（_sanitize_merchant_system_prompt 已移除，不再有商户 system_prompt 次位）。
唯一权威路径：_build_fixed_prompt_template（V3.1 首部）+ 动态约束追加
```

## 三个 AI 场景对比

| 维度 | AI回复预览 | AI自动回复 | AI客服训练端 |
|---|---|---|---|
| 入口 | POST /agents/preview（agents.py:194） | webhook → run_ai_auto_reply_job | POST /knowledge-training/ask（knowledge_training.py:281） |
| Agent 配置来源 | 前端 payload 草稿值（agents.py:241-262） | DB binding.agent（ai_auto_reply_dry_run_service.py:315-336） | **不注入 agent_config**（knowledge_training_service.py:503-506） |
| 商户变量 | 前端传入真实值 | DB 真实值 | 全部"未配置"占位 |
| 客户事实 | 前端传入（脱敏） | DB 会话历史 + customer_memory + contact_state + lead | **无**（仅 question + RAG chunks） |
| 知识库 | RAG search_with_diagnostics | 同 preview | 独立 search，category_keys=["base"] |
| LLM 路径 | 9100 build_reply_suggestion → _build_llm_reply | **同 preview**（共享 9100 管线） | **独立**（_build_answer，不经 build_reply_suggestion） |
| 算力 capability_key | douyin-cs | douyin-cs | knowledge |
| 真实发送 | **否**（auto_send=False 硬编码） | 可能（decided + real_send + auto_send=True） | 否 |
| 隔离程度 | 与 auto-reply 共享 9100 LLM 代码路径 | 与 preview 共享 | 独立 LLM 路径 |

> **三场景隔离口径**：代码路径存在共享（preview 与 auto-reply 共用 9100 `build_reply_suggestion`），**事实来源隔离尚待 E2E 验证**。共用 LLM 代码本身没问题，真正要证明的是"同一套策略，不同事实源"。正式隔离规则见 ACCEPTANCE.md。
