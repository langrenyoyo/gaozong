# M02 AI小高线索 链路说明

> 状态：G1 BASELINE（2026-08-14，基于 CODE_SOURCE_BASE=88235b5 冻结文件地图）
> 用途：M02 模块的链路骨架，支撑 G3 模块验真与独立验收。G1 阶段只登记事实，不展开 G3 验收。

## 1. Responsibility
- 线索全生命周期：webhook 入站 → 线索创建/去重 → 联系方式提取与状态（收集/格式/可达三态）→ 分配 → 销售跟进/回访 → 反馈 → 日报数据源 → 通知（微信派单）。
- **边界红线**：不负责真实微信发送（归 M04，本模块只产出通知任务/资格判定）；不负责 AI 客服自动回复主体（归 M01，但消费 M01 消息与共享联系人域）。
- DOMAIN_SHARED：contact_extractor / contact_state / customer_profile 等 7 个领域共享 service 归 M02 但被 M01 使用（OD-G1-04）。

## 2. User Entrypoints
- 5173 前端「线索」模块：线索管理、webhook 事件、通知记录、销售反馈、回访管理。
- 抖音 GMP webhook（商家私信/关注/表单）→ 9000 `integrations.py` → 线索域。

## 3. Frontend Entrypoints
- feature 目录：`frontend/src/features/leads/`（LeadsManagement / WebhookEventsPage / ChatPanel / ContactInfo / ContactList）。
- 页面：LeadsManagement、LeadsModulePage、WebhookEventsPage、AdminReturnVisitsPage。
- API clients：leads、webhookEvents、notifications、reports、staff、adminReturnVisits、contactInvalid、integrations。
- 共享组件（COMPAT）：components/ChatPanel、ContactInfo、ContactList（旧线索聊天组件，被 feature/leads 复用）。

## 4. Backend API Entrypoints
- `app/routers/leads.py`（线索 CRUD/分配）、`webhook_events.py`（事件）、`lead_notifications.py`/`lead_notification_actions.py`/`lead_notification_records.py`（微信派单通知，Windows-only）、`sales_feedback.py`、`admin_return_visits.py`、`admin_contact_invalid_mark.py`、`admin_test_customer_reset.py`（DEV_ONLY）、`reports.py`、`staff.py`、`integrations.py`（MIXED：webhook 主入口 + legacy_webhook + sync-leads）。
- 入站：GMP 回调 → `integrations.py` webhook → `webhook_event_service`。

## 5. Core Services
- `app/services/`：lead_service、lead_management_service、lead_wechat_notify_eligibility_service、webhook_event_service、douyin_webhook_idempotency_service、douyin_sync_service、douyin_resource_download_service、sales_feedback_parser、sales_followup_service、return_visit_run_service、feedback_service、notification_service、notification_template、assign_service、report_service、staff_service。
- DOMAIN_SHARED：contact_extractor、contact_state_service、contact_completion_resolver、contact_validity_analyzer、contact_invalid_followup_service、customer_profile_service、douyin_customer_profile_deriver。

## 6. Data Ownership
- 9000 库表：douyin_leads、lead_contacts（三态）、lead_notifications、webhook_events、sales_feedback、return_visit_runs、customer_profiles、daily_report_*（读 M04 数据源）、assignments。
- 被其他模块读写：M01 消费 contact_*（DOMAIN_SHARED）与创建线索；M04 消费通知任务并回写结果；M07 计费上报（return_visit/preview 幂等）。

## 7. Async / Worker Chain
- GMP webhook → integrations.py → webhook_event_service（幂等）→ 线索创建 + contact 提取（DOMAIN_SHARED）→ 分配（assign_service，原子带时区）→ 通知资格判定（lead_wechat_notify_eligibility）→ 通知任务（M04 消费）。
- 回访：scheduler → return_visit_run_service → 回访任务（M04 发送）→ 反馈（sales_feedback_parser）。
- 空号反馈追问：contact_invalid_followup_service（DOMAIN_SHARED，调度）。

## 8. External Dependencies
- Douyin GMP webhook（AUTH：签名；INPUT：事件；FAILURE：幂等去重 + retry）。
- NewCarProject：商户/销售组织/账号权限权威（AUTH）。
- 微信派单：不直接发，通知任务交 M04（Local Agent），检测链路只读。
- 抖音 OpenAPI（PLATFORM client）：消息资源下载。

## 9. Cross-Module Calls
- CALLS：M01（消费客服消息、触发线索/联系人更新）、M04（通知任务、日报数据）、M07（usage 上报幂等键）。
- PROVIDES：DOMAIN_SHARED 联系人能力供 M01；销售报表供 M04 日报聚合。
- READS：M01 的 douyin_ai_agents 判定账号 agent 归属（跨域读）。
- COMPAT_FOR：apps/leads 旧子应用（META 被 capability_gateway 引用）。

## 10. Auth / Merchant Boundary
- 权限码：`auto_wechat:leads`、`auto_wechat:sales_feedback` 等；require_leads_context（reports/staff）。
- merchant/tenant：PLATFORM-ISO 校验；lead 归属商户隔离；前端不可信上下文。
- Windows-only：lead_notifications/feedback routers（BC-05，仅 Windows 平台注册）。

## 11. Compatibility Layer
- apps/leads 旧子应用：COMPAT，META 被 capability_gateway.py 引用；旧 service 与 9000 语义并存。removal_prerequisite：capability_gateway META 引用迁移 + 旧 SQLite 表停写。
- integrations.py legacy_webhook：COMPAT 区（MIXED section evidence，BC-07）。

## 12. Legacy Candidates
- integrations.py sync-leads 旧拉取段：LEGACY_CANDIDATE（MIXED 内 section，BC-07）。
- apps/leads 内部旧逻辑：LEGACY 候选（登记 ≠ 可删除）。

## 13. Known Unknowns
- U-004：空号反馈追问链路（contact_invalid_followup）门禁豁免清单（G4/G5 豁免、G3/24h/Hard 保留）待用户逐项确认（见记忆 contact-invalid-followup-plan）。
- U-005：lead_notifications Windows-only 与 M04 通知消费的端到端时序未在 staging 复核（Gate2 为 HTTP 模拟非真实双 19000）。
- 历史 dry_run 基线失败：范围外，根因在历史服务，归属租户隔离子任务（记忆 dry-run-conversation-history-base-failure）。

## 14. Future G3 Acceptance Boundary
- G3 验收应覆盖：webhook 幂等→线索创建→contact 三态→分配→通知资格→回访→反馈全链路；空号反馈追问门禁逐项；M07 计费幂等（return_visit/preview NO_DOUBLE_CHARGE）；商户隔离；Windows-only 注册行为。G1 阶段不展开。
