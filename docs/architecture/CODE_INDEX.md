# auto_wechat 机器代码索引（CODE_INDEX）

> 本文档从 CODE_INDEX.yaml 生成，不两处人工维护。基于 1A.1 SYSTEM_MAP 事实，广度优先。
> source_baseline: `c26ec227e70d689e1b98f838253a36685aa6b0a6` | last_verified_at: 2026-08-07

## 平台公共底座（跨所有模块）

- **auth**: app/auth/ + app/routers/auth.py
- **database**: app/database.py
- **send_gate**: app/services/douyin_autoreply_gate_service.py
- **outbox**: app/services/ai_auto_reply_outbox_service.py
- **schedulers**: app/scheduler/* + app/main.py lifespan
- **merchant_isolation**: app/services/douyin_merchant_isolation.py

## 领域共享能力（客户/线索领域，非平台基础设施）

- **contact_extraction**: app/services/contact_extractor.py + contact_state_service.py + customer_profile_service.py + contact_completion_resolver.py + contact_validity_analyzer.py + contact_invalid_followup_service.py + douyin_customer_profile_deriver.py（客户/线索领域共享，非平台基础设施）

## 数据库

- 主库: auto_wechat (PostgreSQL, DATABASE_URL, app/database.py, 54 ORM 表)
- RAG 库: xg_douyin_ai_cs (PostgreSQL, RAG_DATABASE_URL, apps/xg_douyin_ai_cs/rag/database.py, 7 原生 SQL 表)

---

## M01 抖音AI小高客服 (`active`)

### 前端
- 路由: /douyin-cs/workbench / /douyin-cs/diagnostics
- nav_ids: douyin-ai-cs, douyin-auto-reply-diagnostics
- feature 目录: `frontend/src/features/douyin-cs/`
- 页面:
  - `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`
  - `frontend/src/features/douyin-cs/pages/DouyinAutoReplyRunsPage.tsx`

### 后端
- routers:
  - `app/routers/douyin_ai_cs_proxy.py`
  - `app/routers/douyin_autoreply_settings.py`
  - `app/routers/ai_auto_reply_runs.py`
  - `app/routers/ai_reply_decision_logs.py`
  - `app/routers/admin_autoreply_rollout.py`
- services:
  - `app/services/douyin_workbench_conversation_service.py`
  - `app/services/douyin_autoreply_settings_service.py`
  - `app/services/douyin_ai_cs_binding_service.py`
  - `app/services/xg_douyin_ai_cs_client.py`
  - `app/services/ai_auto_reply_dry_run_service.py`
- 子应用 `apps/xg_douyin_ai_cs/`:
  - routers: accounts, ai_reply, categories, conversations, daily_reports, health, knowledge_training, rag, return_visits
  - services: reply_decision_service, reply_hard_rules, reply_kernel/, agent_runtime, agent_context, vector_store, rag/repository.py
  - 入口: build_reply_suggestion, build_llm_messages, _build_fixed_prompt_template

### workers
- app/services/ai_auto_reply_outbox_service.py (claim/lease/恢复)
- app/services/contact_invalid_followup_service.py (空号追问调度)

### 外部依赖: douyin_gmp, milvus, xg_douyin_ai_cs_9100

### 数据表
- `douyin_webhook_events`
- `ai_auto_reply_runs`
- `ai_reply_decision_logs`
- `douyin_private_message_sends`
- `douyin_account_autoreply_settings`
- `autoreply_rollout_configs`
- `autoreply_whitelist_entries`
- `autoreply_admin_audit_logs`
- `conversation_autopilot_states`
- `douyin_conversation_read_states`
- `douyin_message_resource_downloads`
- `douyin_image_uploads`

### 配置项
- `DOUYIN_AUTO_REPLY_ENABLED`
- `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED`
- `DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT`
- `AI_AUTO_REPLY_OUTBOX_ENABLED`
- `DOUYIN_DECODE_MASKED_ENABLED`
- `DY_DECODE_MSG_TIMEOUT_SECONDS`

### 测试
- `tests/test_douyin_workbench_conversations.py`
- `tests/test_douyin_ai_cs_proxy.py`
- `tests/test_douyin_autoreply_settings_service.py`
- `tests/test_ai_auto_reply_dry_run.py`
- `tests/test_ai_auto_reply_outbox_service.py`
- `tests/test_douyin_webhook_resource_download.py`
- `tests/test_douyin_decode_msg_content.py`
- `tests/test_xg_douyin_ai_cs_llm.py`
- `tests/test_xg_douyin_ai_cs_rag.py`

### 依赖: M02, M03

### legacy_paths（只标记，不正式定性）
- app/routers/integrations.py:595 (sync-leads, auto_notify 已禁用)
- app/routers/integrations.py:45,867 (legacy_webhook_router 兼容路径)

---

## M02 AI小高线索 (`active`)

### 前端
- 路由: /leads / /chat
- nav_ids: leads, chat
- feature 目录: `frontend/src/features/leads/`
- 页面:
  - `frontend/src/features/leads/pages/LeadsManagement.tsx`
  - `frontend/src/features/leads/pages/LeadsModulePage.tsx`

### 后端
- routers:
  - `app/routers/leads.py`
  - `app/routers/integrations.py (webhook 入口)`
  - `app/routers/webhook_events.py`
  - `app/routers/lead_notifications.py`
  - `app/routers/lead_notification_actions.py`
  - `app/routers/lead_notification_records.py`
  - `app/routers/admin_contact_invalid_mark.py`
  - `app/routers/admin_test_customer_reset.py`
  - `app/routers/sales_feedback.py`
- services:
  - `app/services/lead_management_service.py`
  - `app/services/lead_service.py`
  - `app/integrations/douyin_webhook.py`
  - `app/services/douyin_resource_download_service.py`
  - `app/services/douyin_openapi_client.py`
- 入口函数: process_webhook_event, upsert_lead_from_webhook, _has_recent_lead_request

### workers
- app/services/contact_invalid_followup_service.py (空号追问，与 M01 共享)

### 外部依赖: douyin_gmp

### 数据表
- `douyin_leads`
- `lead_followup_records`
- `reply_checks`
- `check_configs`
- `feedback_records`
- `lead_notifications`
- `lead_report_attributions`
- `sales_lead_feedbacks`
- `sales_lead_updates`
- `customer_profiles`
- `contact_invalid_followup_tasks`
- `douyin_authorized_accounts`
- `douyin_oauth_states`

### 配置项
- `DY_SECRET_KEY`
- `DY_GMP_SECRET_KEY`
- `DY_OPENAPI_BASE_URL`
- `DY_MAIN_ACCOUNT_ID`
- `DOUYIN_CONTACT_FRAGMENT_WINDOW_SECONDS`
- `DOUYIN_LEAD_REQUEST_WINDOW_SECONDS`
- `LEADS_WEBHOOK_INTERNAL_ENABLED (默认 false)`

### 测试
- `tests/test_douyin_webhook.py`
- `tests/test_douyin_webhook_atomic_idempotency.py`
- `tests/test_leads_management.py`
- `tests/test_contact_extractor_pipeline.py`
- `tests/test_contact_state_machine.py`
- `tests/test_contact_invalid_followup.py`
- `tests/test_lead_request_context_boost.py`
- `tests/test_agent_write_back_contact_validity.py`

### 依赖: M03, M04

### legacy_paths（只标记，不正式定性）
- app/routers/integrations.py:595 (sync-leads)
- app/config.py:217 (DOUYIN_API_BASE_URL 默认 8081 demo)

---

## M03 AI小高智能体 (`active`)

### 前端
- 路由: /agents / /agent-create / /agent-edit
- nav_ids: ai-agents, agent-create, agent-edit
- feature 目录: `frontend/src/features/agents/`
- 页面:
  - `frontend/src/features/agents/pages/SuperMerchantAgent.tsx`

### 后端
- routers:
  - `app/routers/agents.py`
  - `app/routers/agent.py`
  - `app/routers/knowledge_categories.py`
  - `app/routers/knowledge_training.py`
- services:
  - `app/services/ai_agent_service.py`
  - `app/services/agent_status_service.py`
  - `app/services/agent_knowledge_category_service.py`
- 入口函数: create_agent, update_agent, bind_agent

### 外部依赖: xg_douyin_ai_cs_9100

### 数据表
- `ai_agents`
- `agent_knowledge_categories`
- `knowledge_categories`
- `douyin_account_agent_bindings`

### 配置项
- `XG_DOUYIN_AI_CS_SERVICE_TOKEN`

### 测试
- `tests/test_ai_agents.py`
- `tests/test_agent_knowledge_categories.py`
- `tests/test_agent_status.py`
- `tests/test_douyin_account_agent_binding_service.py`
- `tests/test_knowledge_categories_api.py`

### 依赖: M01

---

## M04 AI小高微信助手 (`active`)

### 前端
- 路由: /wechat/status / /wechat/config / /wechat/tasks / /wechat/download-test / /wechat/daily-reports
- nav_ids: ai-agent, wechat-config, wechat-tasks, wechat-download-test, wechat-daily-reports
- feature 目录: `frontend/src/features/wechat-assistant/`
- 页面:
  - `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
  - `frontend/src/features/wechat-assistant/pages/DailyReports.tsx`

### 后端
- routers:
  - `app/routers/wechat_tasks.py`
  - `app/routers/wechat_auto_detect.py`
  - `app/routers/replies.py`
  - `app/routers/checks.py`
  - `app/routers/daily_reports.py`
  - `app/routers/daily_report_deliveries.py`
- services:
  - `app/local_agent_main.py`
  - `app/services/wechat_ui_reply_service.py`
  - `app/services/wechat_task_service.py`
  - `app/services/daily_report_service.py`
  - `app/services/daily_report_delivery_service.py`
- 入口函数: agent_write_back_reply, record_manual_reply, create_local_agent_app

### workers
- app/scheduler/wechat_auto_detect_scheduler.py (默认禁用)
- app/scheduler/daily_report_scheduler.py
- app/scheduler/check_scheduler.py

### 数据表
- `wechat_tasks`
- `daily_report_jobs`
- `daily_report_deliveries`
- `sales_daily_summaries`
- `merchant_report_profiles`
- `daily_ad_metrics`

### 配置项
- `LOCAL_AGENT_TOKEN`
- `LOCAL_AGENT_AUTH_REQUIRED`
- `AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT (默认 0)`
- `LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED (默认关)`

### 测试
- `tests/test_local_agent_auth.py`
- `tests/test_local_agent_heartbeat.py`
- `tests/test_local_agent_runtime.py`
- `tests/test_wechat_auto_detect.py`
- `tests/test_wechat_task_history_api.py`
- `tests/test_daily_report_service.py`
- `tests/test_p0_reply_2_agent_write_back.py`

### 依赖: M02

### legacy_paths（只标记，不正式定性）
- app/config.py:349 (AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT 旧自动检测)
- app/routers/replies.py (LEGACY_WECHAT_DEBUG_ENDPOINTS 守卫)
- app/auth/local_agent_auth.py:62,67 (auth_mode=legacy 未认证回退)

---

## M05 小高素材库 (`active`)

### 前端
- 路由: /ai-edit/materials
- nav_ids: ai-edit-materials
- feature 目录: `frontend/src/features/ai-edit/`
- 页面:
  - `frontend/src/features/ai-edit/pages/MaterialLibrary.tsx`

### 后端
- routers:
  - `app/routers/ai_edit.py`
- services:
  - `app/services/ai_edit_service.py`
  - `app/services/ai_edit_storage.py`
  - `app/services/material_analysis.py`
- 入口函数: upload_material, analyze_material, list_materials

### 外部依赖: tos

### 数据表
- `ai_edit_materials`
- `ai_edit_material_analyses`
- `ai_edit_material_processes`
- `ai_edit_templates`
- `ai_edit_job_materials`

### 配置项
- `TOS_ACCESS_KEY`
- `TOS_SECRET_KEY`
- `TOS_BUCKET`

### 测试
- `tests/test_phase12_task12_material_api.py`
- `tests/test_phase12_task12_material_analysis.py`
- `tests/test_ai_edit_download_token.py`

### 依赖: M06

---

## M06 AI小高剪辑 (`active`)

### 前端
- 路由: /ai-edit/editor
- nav_ids: ai-edit-editor
- feature 目录: `frontend/src/features/ai-edit/ (与 M05 共享)`
- 页面:
  - `frontend/src/features/ai-edit/pages/LasRemixWorkbench.tsx`

### 后端
- routers:
  - `app/routers/ai_edit.py (与 M05 共享)`
- services:
  - `app/services/ai_edit_las_service.py`
  - `app/services/las_client.py`
  - `app/services/las_tos_uploader.py`
- 入口函数: create_las_job, process_las_job

### 外部依赖: las, tos

### 数据表
- `ai_edit_jobs`
- `ai_edit_job_artifacts`

### 配置项
- `LAS_API_KEY`
- `LAS_BASE_URL`
- `LAS_POLL_INTERVAL_SECONDS`
- `LAS_MAX_WAIT_SECONDS`

### 测试
- `tests/test_las_client.py`
- `tests/test_ai_edit_result_delivery.py`

### 依赖: M05

---

## M07 AI小高算力 (`active`)

### 前端
- 路由: /compute / /compute/token-transactions / /compute/recharge-orders
- nav_ids: compute, compute-token-transactions, compute-recharge-orders
- feature 目录: `frontend/src/features/compute/`
- 页面:
  - `frontend/src/features/compute/pages/ComputeCenter.tsx`
  - `frontend/src/features/compute/pages/SuperComputeConfig.tsx`

### 后端
- routers:
  - `app/routers/compute.py`
- services:
  - `app/services/compute_service.py (兼容入口, 实现收敛到 apps/compute/services/)`
- 入口函数: list_compute_accounts, get_compute_config

### 数据表
- `compute_accounts`
- `compute_transactions`
- `compute_packages`
- `compute_markup_ratios`

### 配置项
- `COMPUTE_INTERNAL_TOKEN`

### 测试
- `tests/test_compute_router.py`
- `tests/test_compute_service.py`
- `tests/test_compute_models.py`
- `tests/test_phase10_compute_metering.py`

### legacy_paths（只标记，不正式定性）
- app/services/compute_service.py:1-4 (Phase 3-B 兼容入口, 实现已迁移到 apps/compute/services/)

---

## 平台公共底座测试

- **auth**: tests/test_auth_context.py, tests/test_newcar_password.py, tests/test_newcar_logout.py
- **database**: tests/test_9000_database_factory.py, tests/test_db_pool_config.py, tests/test_db_readiness.py
- **outbox**: tests/test_ai_auto_reply_outbox_postgres_mvcc.py, tests/test_ai_auto_reply_outbox_restart_recovery.py
- **migration**: tests/test_db_migration_runner.py, tests/test_9000_postgres_jsonb_orm_parity.py
- **merchant_isolation**: tests/test_douyin_workbench_tenant_isolation_r2.py, tests/test_douyin_leads_session_isolation.py
