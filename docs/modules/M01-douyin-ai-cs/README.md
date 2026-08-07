# M01 抖音AI客服

> 状态：CURRENT_REALITY_VERIFIED_PENDING_E2E
> 代码基线：c26ec227e70d | 验真日期：2026-08-07

## M01 是什么

M01 是抖音私信 AI 客服的核心运行模块，承担从消息入口到 AI 回复生成到真实发送的完整闭环，以及空号追问/回访等后续能力。它是系统最复杂模块（8 子域、11 张表、7+ 个 scheduler/worker）。

## 8 子域能力清单

| 子域 | 职责 | 核心代码 |
|---|---|---|
| M01-A 入口与会话 | GMP webhook 直收→幂等→Lead 更新→会话聚合→已读协议 | integrations.py / douyin_webhook.py / douyin_workbench_conversation_service.py |
| M01-B 编排 | webhook→AiAutoReplyRun→outbox claim/lease/retry→编排 | ai_auto_reply_outbox_service.py / ai_auto_reply_dry_run_service.py |
| M01-C Agent/Prompt/9100 | binding.agent 解析→agent_config 组装→9100 suggest_reply→RAG→LLM | douyin_account_agent_binding_service.py / ai_auto_reply_dry_run_service.py / xg_douyin_ai_cs_client.py |
| M01-D 客户事实 | contact_state 计算→CustomerProfile 读写→field_sources 标注→9100 注入 | contact_state_service.py / customer_profile_service.py / douyin_conversation_history_service.py |
| M01-E 决策门禁 | pre-LLM gate→post-LLM gate→auto_send 收敛→发送条件→hard guard | douyin_autoreply_gate_service.py / reply_hard_rules.py |
| M01-F 发送 | 真实发送→send_source→im_send_msg 回执→AI/人工识别→manual_takeover | ai_auto_reply_send_service.py / douyin_private_message_send_service.py / douyin_outbound_message_classifier.py |
| M01-G 后续能力 | 回访→空号追问(主动/被动)→scheduler | return_visit_run_service.py / contact_invalid_followup_service.py |
| M01-H 可观测 | 决策日志→run 状态流转→error stage 分类→retry→dead task→health/readiness | ai_reply_decision_log_service.py / ai_auto_reply_outbox_service.py / health.py |

## Owner

- **数据 Owner**：ai_auto_reply_runs / ai_reply_decision_logs / douyin_private_message_sends / douyin_account_autoreply_settings / douyin_webhook_events / conversation_autopilot_states / douyin_conversation_read_states / douyin_message_resource_downloads / douyin_image_uploads / customer_profiles / contact_invalid_followup_tasks（11 张表）
- **与 M02 共享**：customer_profiles / contact_invalid_followup_tasks

## 主要入口

- webhook：/integrations/douyin/webhook（主）+ /webhook/douyin（COMPAT）
- 工作台 API：/integrations/douyin-ai-cs（会话/消息/预览/设置）
- 自动回复记录：/ai-auto-reply-runs
- 决策日志：/ai-reply-decision-logs
- 9100 独立子应用：apps/xg_douyin_ai_cs/（build_reply_suggestion / RAG / LLM）

## 主要依赖

- → M02（data writes）：webhook upsert DouyinLead + recover_contact_valid
- → M02（data reads）：客服工作台读 customer_profiles
- → M03（contract）：消费 agent_config（经 payload，三处组装）
- → M07（runtime）：compute_usage_client HTTP 上报算力
- → 公共底座：auth/数据库/发送gate/outbox/调度器/商户隔离

## 当前状态

ACTIVE。8 子域功能完整，端到端链路打通。Prompt 三层架构清晰（固定模板+商户 prompt+运行时约束）。商户隔离严密。空号追问三路触发闭合（webhook 块4 + admin 1.4 + 销售回写 1.6）。outbox 持久化任务+claim/lease/retry+补偿对账+积压告警完整。
