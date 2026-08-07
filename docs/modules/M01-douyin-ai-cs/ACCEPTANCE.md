# M01 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

### COVERED

| 能力 | 测试文件 | 关键用例 |
|---|---|---|
| webhook 入口+幂等 | test_douyin_webhook_atomic_idempotency.py | A1-A14 全覆盖（SQL合同/派单事务/20路并发/重复继承） |
| outbox claim/lease/retry | test_ai_auto_reply_outbox_service.py + test_ai_auto_reply_outbox_postgres_mvcc.py | guarded lease/send_authorized对账/20并发单飞/PG MVCC |
| auto-reply 编排 | test_ai_auto_reply_dry_run.py | 事件门禁/重复跳过/绑定阻断/9100调用/LLM异常/历史失败 |
| pre-LLM/post-LLM gate | test_ai_auto_reply_dry_run.py + test_p0a_hard_gate.py + test_p0_3_rag_fallback_auto_send_contract.py | manual_takeover/频率/HARD_BLOCK/RAG退化/prompt_injection |
| 真实发送+回执 | test_ai_auto_reply_send_service.py | send_enabled/disabled/dry_run/灰度/白名单/manual_takeover/latest_message/send_context/防重发/频控 |
| contact_state/customer_profile | test_customer_profile_three_source_unified.py + test_douyin_customer_profile_deriver.py + test_douyin_workbench_tenant_isolation_r2.py | 三源统一/派生器/商户隔离 |
| 回访 | test_phase9_return_visit_e2e.py + 配套 5 文件 | happy_path/suppress/confidence_low/disabled/rate_limited/send_unknown/idempotent/cooldown |
| 商户隔离 | test_douyin_workbench_tenant_isolation_r2.py + test_ai_reply_decision_logs_api.py + test_ai_auto_reply_outbox_service.py | 跨商户会话拒绝/游标防泄露/历史NULL/决策日志隔离/人工重试 |
| 决策日志/可观测 | test_ai_reply_decision_logs_api.py + test_latency_timing_selfcheck.py | list/detail/pagination/send_source/effectiveness/审计/分阶段耗时/无PII |

### PARTIAL

| 能力 | 现状 | 缺什么 |
|---|---|---|
| 空号追问 | 任务创建/取消/文本构建 COVERED | _process_one/_check_freshness/_check_gates/调度器/真实发送链路无单测 |

### MISSING

| 能力 | 现状 |
|---|---|
| 9100 真实集成 | 无 xg_douyin_ai_cs_client 真实调用集成测试（dry_run 用 mock） |
| 三场景隔离 E2E | Preview/Auto Reply/Training 事实隔离未 E2E 验证 |

## E2E 验真结果（2-M01.2 Docker，2026-08-07）

环境：docker compose dev（9000 + 9100 + PG + 能力中心）

| E2E | 域 | 结果 | 证据 |
|---|---|---|---|
| A | Webhook 幂等 | **PASS** | 重复事件 is_duplicate=True；WebhookEvent 胜出者=1；AutoReplyRun 不重复创建 |
| B | Outbox 状态机 | **PASS** | pending/retry_wait 可处理；processing/send_processing 可恢复；sent/send_unknown 终态不重发；failed 可人工重试(仅 pre_send_temporary_failure 白名单) |
| C | Gate Matrix | **PASS** | HARD_BLOCK 3 flag（虚假确认/重复索要/资料承诺）不可豁免；prompt_injection 不在 9000；unfounded 已停用 |
| D | Customer Fact Matrix | **PASS** | NONE/PARTIAL/VALID/INVALID/AMBIGUOUS 五态全部 PASS（analyze_contact_state 五态全覆盖，confidence 分级正确；INVALID 由 12012345678 触发 invalid_mobile_prefix） |
| E | Agent Contract | **PASS** | DB 保存 prompt/knowledge_base_text/store_address 一致；知识绑定 read-back 一致；Preview 用 DB 配置+LLM 回复成功 |
| F | Preview/Auto 事实源 | PARTIAL | Preview 已验证（M03 复用）；Auto Reply 事实源需真实 webhook 触发 |

### M03 Gate 回填

| Gate | 状态 | 证据 |
|---|---|---|
| GATE-M03-01（Agent Binding→Auto Reply） | **PENDING_STAGING** | 已验证子结论 M03-CONTRACT-PREVIEW（Agent persisted config → Preview consumption）PASS，但不能替代 Agent Binding→Auto Reply 真实消费 |
| GATE-M03-02（Auto Reply 事实隔离） | **PENDING_STAGING** | E2E-F PARTIAL，Auto Reply 事实源需真实 webhook 触发验证 |
| GATE-M03-03（Training 隔离） | **PENDING_STAGING** | 需真实知识库训练端调用验证 |

> M03 三个 Staging Gate 全部 PENDING_STAGING。M03-CONTRACT-PREVIEW 是已验证子结论（Preview 消费 DB 配置一致），但不替代真实 webhook→auto-reply→binding.agent 消费链路。

### 仍 SKIP（需 staging/生产）

- 真实 GMP webhook → 9000 → outbox → 9100 → LLM → 发送 → im_send_msg 回执全链路
- Auto Reply 事实源差异（需真实 webhook + customer_memory）
- 空号追问端到端（需 CONTACT_INVALID_FOLLOWUP_ENABLED=true + 真实发送）

**E2E 状态：`M01_DOCKER_E2E_VERIFIED_PENDING_STAGING`**（无 BLOCKER，A-E 全 PASS，F PARTIAL）
