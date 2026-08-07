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

## E2E 验收清单（待 2-M01.2）

1. **webhook→outbox→9100→发送 端到端**：真实 webhook 事件触发 auto-reply 完整链路
2. **Agent Contract 一致性**：binding.agent DB 配置与 preview 草稿值字段一致（复用 M03 ISSUE-M03-002 三处组装验证）
3. **三场景事实隔离**：Preview 不偷 DB 档案 / Auto Reply 可读可信事实 / Training 无真实客户信息
4. **空号追问端到端**：mark_contact_invalid → create_followup_task → Worker claim → send → 回写
5. **outbox 恢复**：send_authorized 崩溃 → 按流水对账 → sent/send_unknown
6. **manual_takeover 端到端**：人工发送 → im_send_msg 标记 → auto-reply 阻断
