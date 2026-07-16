# 小高AI系统一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `auto_wechat` 中完成小高AI系统一期扩展：抖音AI客服自动回复闭环、线索与留资口径、微信助手真实派单与日报、违禁词、回访提示词、AI回复记录、算力配置，以及“小高素材库 + AI 小高剪辑”本地 MVP。

**Architecture:** `auto_wechat` 9000 继续作为控制面，负责登录态消费、权限、商户隔离、任务持久化、审计和前端 API；9100 `apps/xg_douyin_ai_cs` 保持抖音AI客服/RAG/LLM 独立服务；19000 Local Agent 除本机微信 UI 自动化外，新增本地素材与剪辑任务协调，但重型媒体处理固定由随包 Python 3.11 `ai_edit_worker.exe` 子进程执行。`douyinAPI`、`auto_edit` 和 BrollStudio 只作为迁移来源，不作为长期生产依赖。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL 目标迁移、SQLite 开发兼容、React + TypeScript + Vite、Local Agent Windows UI Automation/OCR、Milvus/RAG、抖音 OpenAPI、Excel 导出。

---

## 范围总览

### 已确认的一期模块

1. 抖音AI客服：从回复建议改为自动回复闭环，唯一触发为企业号绑定智能体并开启 AI 托管。
2. AI小高线索：留资口径改为 `extracted_phone`、`extracted_wechat`、`all_extracted_contacts` 任一存在。
3. AI小高智能体：归属 `auto_wechat:douyin_ai_cs`，删除为硬删除，绑定中禁止删除。
4. 抖音企业号管理：商户自己的本地授权/Fake CRUD，不是抖音上游真实授权管理；解绑为本地 `bind_status=3`，删除软删。
5. 微信助手和日报：配置项为线索分配、短视频/直播留资管理表、每日线索销售反馈表、线索溯源表、销售单车成本表。
6. 销售反馈模板：`【线索反馈】`、`【线索更新】`、`【每日线索总结】`，数据 SQL 持久化，日报由 SQL 今日数据生成 Excel。
7. 小高算力：3 个套餐 seed，全局 Token 上浮比例，AI 操作埋点带 `model`，支付一期 Mock，余额不足不拦截。
8. 违禁词：全局 3 类词库，每词映射安全词，AI 和人工消息统一替换，替换后继续发送。
9. 回访提示词：全局 3 类模板，微信销售回复触发 LLM/关键字判断，再发抖音回访私信。
10. AI 回复记录：展示 AI 实发内容 `DouyinPrivateMessageSend.content`，与 `AiReplyDecisionLog` 关联，支持超管标记有效。
11. 一键过审：客户已取消（`CANCELLED_BY_CUSTOMER`）；保留历史代码和兼容字段，不继续实施。
12. AI 剪辑：迁入 `auto_edit` 剪辑内核和 BrollStudio 自动增稳能力，交付“小高素材库 + AI 小高剪辑”本地 MVP；19000 监管随包剪辑子进程，素材默认本地保存。
13. 自动发送放开：删除旧硬门禁，但保留违禁词、人工接管、限频、失败回写、幂等、紧急停止等运行保护。
14. 上游边界：登录、商户管理、管理员账号、功能授权在 NewCarProject/used-car，不在 auto_wechat 重建。
15. 前端旧口径清理：移除 `auto_send=false`、`sent=false`、假数据、假 CRUD、回复建议等旧文案。

### 明确不做

- 不在 auto_wechat 实现商户 CRUD、管理员账号管理、登录密码体系、功能授权发放。
- 不让前端直连 9100、Milvus 或持有 internal token。
- 不把 `douyinAPI` 作为生产依赖。
- 不从 auto_wechat 长期共享 `auto_edit/runs` 目录或外部仓库源码。
- 不绕过微信前台焦点、联系人校验、OCR/置信度保护、紧急停止。
- 不让违禁词命中阻断发送；一期统一替换后继续发送。
- 不做真实支付，充值订单保持 Mock。
- 不让 AI剪辑直接发布抖音，不做远程设备控制、商户间素材共享或完整多轨编辑器。

---

## 数据库设计总表

> 当前项目已同时存在 `migrations/versions/*.sql` 过渡迁移和 `migrations/postgres/auto_wechat/versions/*.py` PostgreSQL 目标迁移。执行时必须双轨维护：过渡 SQLite/本地 SQL 不扩散 SQLite 专属写法，PostgreSQL Alembic 版本作为生产目标真源。

### 改现有表

| 表 | 变更 |
|---|---|
| `sales_staff` | 新增 5 个规则布尔字段：`enable_lead_assignment`、`enable_short_video_live_lead_report`、`enable_daily_sales_feedback_report`、`enable_lead_trace_report`、`enable_sales_unit_cost_report` |
| `ai_reply_decision_logs` | 新增 `is_effective`、`effectiveness_reason`、`model`；保留建议/决策审计字段 |
| `douyin_private_message_sends` | 确认 `decision_log_id`、`send_source`、`auto_send`、`status` 可支撑 AI 实发记录；必要时补 `final_content_before_send` 不另建重复记录 |
| `compute_packages` | 写入 3 个套餐 seed：99/100000、299/350000、699/900000 |
| `douyin_authorized_accounts` | 取消授权仅更新 `bind_status=3`；删除仍软删并级联停用绑定 |

### 新表

| 表 | 用途 |
|---|---|
| `forbidden_word_libraries` | 全局固定 3 类违禁词库 |
| `forbidden_words` | 每个违禁词到安全词的映射、启停、命中统计 |
| `forbidden_word_hit_logs` | 记录 AI/人工/回访消息替换前后、命中词、发送上下文 |
| `return_visit_prompts` | 全局固定 3 类回访提示词模板 |
| `return_visit_runs` | 销售回复触发回访判断、生成、替换、发送的流水 |
| `sales_lead_feedbacks` | 单线索 `【线索反馈】` 解析后的结构化数据 |
| `sales_lead_updates` | 单线索 `【线索更新】` 解析后的结构化数据 |
| `sales_daily_summaries` | 销售每日 `【每日线索总结】` 原文和结构化字段 |
| `daily_report_jobs` | 每日报表生成、Excel 文件、发送对象和发送状态 |
| `compute_markup_ratios` | 6 个能力的全局 Token 上浮比例 |
| `ad_review_oauth_accounts` | 巨量广告 OAuth 授权账号，与抖音企业号授权隔离 |
| `ad_review_suggestions` | 拒审素材修复建议快照 |
| `ad_review_adopt_tasks` | 异步采纳任务和轮询结果 |
| `ai_edit_materials` | 商户私有/平台公共素材 metadata、本地/云端状态和回收站 |
| `ai_edit_material_analyses` | 版本化 ASR、分镜、标签、稳定性和可用区间 |
| `ai_edit_templates` | 超管维护的平台剪辑模板和 Prompt 版本 |
| `ai_edit_job_materials` | 任务素材角色、顺序、固定哈希和使用区间 |
| `ai_edit_jobs` | AI 剪辑任务、阶段、进度、设备、attempt、取消和恢复 |
| `ai_edit_job_artifacts` | 本地/云端产物映射和媒体完整性，禁止暴露内部绝对路径 |

### 迁移风险

| 风险 | 应对 |
|---|---|
| 历史 SQLite 与目标 PostgreSQL 字段差异 | 每个迁移同时补模型、SQLite 过渡 SQL、PostgreSQL Alembic、schema 测试 |
| 大表 ALTER 锁表 | 生产迁移前用 dry-run 统计行数；超 300 万行改用在线 DDL 方案或维护窗口 |
| 违禁词替换审计包含手机号/微信号 | 日志保存时脱敏上下文，保留命中词和替换词，不保存密钥或 raw LLM response |
| 抖音发送重复 | `auto_reply_run_id` 已有唯一约束继续复用；人工重试必须读取上一条发送记录 |
| Excel 文件泄露跨商户 | `merchant_id + report_date + report_type` 查询，下载和发送均按商户过滤 |
| AI 剪辑产物路径穿越 | 前端只拿 artifact id；后端按数据库内部路径读取，不接受前端 path |

---

## 实施顺序

### Phase 0: 文档与旧约束同步

**目的:** 防止后续 agent 继续按旧门禁、旧规则字段、旧一期范围开发。

**Files:**
- Modify: `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md`
- Modify: `CLAUDE.md`
- Modify: `frontend/src/features/capabilities.ts`
- Test: `tests/test_xiaogao_phase1_context_contract.py`

- [ ] **Step 1: 写上下文合同测试**
  - 断言需求理解文档包含 AI 剪辑、5 个报表规则字段、`all_extracted_contacts` 留资口径、自动发送放开和一键过审取消口径。
  - 断言文档不再包含“AI剪辑不属于一期”“sent 必须为 false”“系统最终保持 auto_send=false”。
  - Run: `pytest tests/test_xiaogao_phase1_context_contract.py -v`
  - Expected: FAIL，缺少新测试或旧文档口径未改。

- [ ] **Step 2: 更新项目上下文**
  - 把旧 4 个规则字段改为 5 个确认字段。
  - 将 AI 剪辑改为一期范围内的“小高素材库 + AI 小高剪辑”本地 MVP。
  - 将一键过审改为 `CANCELLED_BY_CUSTOMER`，不恢复执行。
  - 明确 NewCarProject 上游边界。
  - 明确 `auto_wechat:ai_edit` 只覆盖小高素材库和 AI 小高剪辑入口。

- [ ] **Step 3: 跑合同测试**
  - Run: `pytest tests/test_xiaogao_phase1_context_contract.py -v`
  - Expected: PASS。

- [ ] **Step 4: 提交**
  - Commit: `docs: 同步小高AI系统一期确认范围`

---

### Phase 1: 数据迁移骨架

**目的:** 先落所有表结构和模型字段，降低后续业务改造的交叉风险。

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Create: `migrations/versions/0027_xiaogao_phase1_core.sql`
- Create: `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py`
- Test: `tests/test_xiaogao_phase1_schema.py`

- [ ] **Step 1: 写 schema 测试**
  - 覆盖新增表、字段、索引、约束、默认值。
  - 检查 `sales_staff` 是 5 个规则字段，不是旧 4 个字段。
  - 检查 `compute_markup_ratios.capability_key` 只允许 6 个能力。
  - 检查 `ad_review_*` 与 `douyin_authorized_accounts` 没有外键耦合。
  - Run: `pytest tests/test_xiaogao_phase1_schema.py -v`
  - Expected: FAIL。

- [ ] **Step 2: 修改 SQLAlchemy 模型**
  - 新增模型类，保持 `merchant_id` 商户隔离字段。
  - 枚举字段用 `String` + 应用层校验，避免 SQLite/PostgreSQL 方言差异。
  - 时间字段统一 `DateTime`。
  - JSON 字段优先使用 SQLAlchemy `JSON`，读取时兼容字符串。

- [ ] **Step 3: 添加过渡 SQL 迁移**
  - 使用 `ALTER TABLE ... ADD COLUMN`、`CREATE TABLE IF NOT EXISTS`、`CREATE INDEX IF NOT EXISTS`。
  - Seed 使用幂等写法，重复执行不重复插入。
  - 不写 SQLite 独有的 `INSERT OR IGNORE` 到 PostgreSQL 目标迁移中。

- [ ] **Step 4: 添加 PostgreSQL Alembic 迁移**
  - 使用 `op.create_table`、`op.add_column`、`sa.CheckConstraint`、`op.create_index`。
  - 迁移编号使用 `revision = "0008_xiaogao_phase1_core"`，`down_revision = "0007_lead_type_widen"`。
  - downgrade 不 drop 历史核心表；新增表可按反向顺序 drop。

- [ ] **Step 5: 跑迁移与 schema 测试**
  - Run: `pytest tests/test_xiaogao_phase1_schema.py tests/test_db_migration_0001.py -v`
  - Expected: PASS。

- [ ] **Step 6: 提交**
  - Commit: `db: 增加小高AI一期核心表结构`

---

### Phase 2: 违禁词统一替换服务

**目的:** 自动发送和人工发送共用同一个替换服务。

**Files:**
- Create: `app/services/forbidden_word_service.py`
- Create: `app/routers/forbidden_words.py`
- Modify: `app/main.py`
- Modify: `app/services/douyin_private_message_send_service.py`
- Modify: `app/services/ai_auto_reply_send_service.py`
- Modify: `app/services/feedback_service.py`
- Test: `tests/test_forbidden_word_service.py`
- Test: `tests/test_forbidden_words_api.py`

- [ ] **Step 1: 写替换服务测试**
  - AI 自动回复命中违禁词后替换为安全词并继续发送。
  - 工作台人工发送命中违禁词后替换为安全词并继续发送。
  - 命中多词时按最长词优先，避免短词破坏长词替换。
  - 记录 `forbidden_word_hit_logs`，保存替换前后摘要和上下文。

- [ ] **Step 2: 实现服务**
  - `replace_forbidden_words(db, merchant_id, source, content, context)` 返回 `final_content`、`hits`、`changed`、`audit_id`。
  - 固定 3 类词库 seed。
  - 每词单独安全词映射。

- [ ] **Step 3: 接入发送链路**
  - 抖音 AI 自动发送、人工发送、回访发送在调用 OpenAPI 前替换。
  - 微信派单模板发送前也走同服务，来源记为 `wechat_dispatch`。

- [ ] **Step 4: 接入超管 API**
  - `GET /admin/forbidden-word-libraries`
  - `GET /admin/forbidden-words`
  - `POST /admin/forbidden-words`
  - `PUT /admin/forbidden-words/{id}`
  - `POST /admin/forbidden-words/{id}/toggle`

- [ ] **Step 5: 跑测试**
  - Run: `pytest tests/test_forbidden_word_service.py tests/test_forbidden_words_api.py tests/test_ai_auto_reply_send_service.py -v`
  - Expected: PASS。

- [ ] **Step 6: 提交**
  - Commit: `feat: 增加违禁词统一替换服务`

---

### Phase 3: 抖音AI客服自动回复闭环

**目的:** 把 9100 回复建议链路收束为企业号绑定智能体 + AI 托管触发的真实自动回复。

**Files:**
- Modify: `apps/xg_douyin_ai_cs/services/reply_decision_service.py`
- Modify: `apps/xg_douyin_ai_cs/routers/ai_reply.py`
- Modify: `app/services/ai_auto_reply_dry_run_service.py`
- Modify: `app/services/ai_auto_reply_send_service.py`
- Modify: `app/services/douyin_autoreply_gate_service.py`
- Modify: `app/routers/douyin_ai_cs_proxy.py`
- Test: `tests/test_ai_auto_reply_dry_run.py`
- Test: `tests/test_ai_auto_reply_send_service.py`

- [ ] **Step 1: 写触发条件测试**
  - 未绑定智能体不调用 9100。
  - 关闭 AI 托管不调用 9100。
  - 人工接管中不发送。
  - 限频超限不发送。
  - 9100 返回 `auto_send=true` 且所有 gate 通过时真实发送。

- [ ] **Step 2: 保留 9100 独立服务**
  - 9100 继续负责 RAG/LLM 生成、模型字段、客户信息提取。
  - 9000 注入可信 `merchant_id`、`account_open_id`、`agent_id`。

- [ ] **Step 3: 移除前端 reply_suggestion 调试入口**
  - API 可保留内部兼容，但用户界面不再显示“AI回复建议”。
  - 日志和文案改为“AI自动回复决策/实发”。

- [ ] **Step 4: 发送记录写实发内容**
  - `DouyinPrivateMessageSend.content` 保存违禁词替换后的最终实发内容。
  - `AiReplyDecisionLog.model` 记录模型。
  - `decision_log_id` 关联发送流水。

- [ ] **Step 5: 跑测试**
  - Run: `pytest tests/test_ai_auto_reply_dry_run.py tests/test_ai_auto_reply_send_service.py tests/test_douyin_ai_cs_proxy.py -v`
  - Expected: PASS。

- [ ] **Step 6: 提交**
  - Commit: `feat: 放开抖音AI客服自动回复闭环`

---

### Phase 4: AI回复记录改造

**目的:** 超管看 AI 实发记录，而不是建议记录。

**Files:**
- Modify: `app/services/ai_reply_decision_log_query_service.py`
- Modify: `app/routers/ai_reply_decision_logs.py`
- Modify: `app/schemas.py`
- Modify: `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx`
- Test: `tests/test_ai_reply_decision_logs_api.py`

- [ ] **Step 1: 写查询测试**
  - 查询源为 `DouyinPrivateMessageSend JOIN AiReplyDecisionLog`。
  - 返回最终实发内容、发送状态、商户、模型、是否有效、有效性原因。
  - 超管可按商户筛选，商户用户只能看自己。

- [ ] **Step 2: 实现查询服务**
  - 普通人工手动发送不进入 AI 回复记录。
  - `send_source='ai_auto'` 或有关联 `decision_log_id` 的发送记录才展示。

- [ ] **Step 3: 实现有效性标记**
  - `PATCH /ai-reply-decision-logs/{id}/effectiveness`
  - 仅超管可改。
  - 写审计日志。

- [ ] **Step 4: 更新前端旧文案**
  - 删除“不会自动发送”“auto_send=false”等旧提示。
  - 页面标题和详情改为“AI实发记录”。

- [ ] **Step 5: 跑测试**
  - Run: `pytest tests/test_ai_reply_decision_logs_api.py && cd frontend && npm run build`
  - Expected: PASS。

- [ ] **Step 6: 提交**
  - Commit: `feat: AI回复记录展示实发内容`

---

### Phase 5: 线索留资与对话跳转

**目的:** 统一留资口径，修复状态展示和对话跳转。

**Files:**
- Modify: `app/services/lead_management_service.py`
- Modify: `apps/leads/webhook_events.py`
- Modify: `frontend/src/features/leads/pages/LeadsManagement.tsx`
- Test: `tests/test_leads_management.py`
- Test: `tests/test_douyin_webhook.py`

- [ ] **Step 1: 写留资口径测试**
  - `extracted_phone` 非空算留资。
  - `extracted_wechat` 非空算留资。
  - `all_extracted_contacts` 非空算留资。
  - `lead.status=replied` 不再是唯一留资口径。

- [ ] **Step 2: 修改服务和展示**
  - 统计卡、列表状态、详情标签统一调用 `has_retained_contact(lead)`。
  - 联系电话为空但微信号存在时显示“已留微信”或对应占位。

- [ ] **Step 3: 对话跳转**
  - 关联键使用 `account_open_id + conversation_short_id + source_id/open_id`。
  - 缺少会话时给明确提示，不跳假页面。

- [ ] **Step 4: 跑测试**
  - Run: `pytest tests/test_leads_management.py tests/test_douyin_webhook.py -v`
  - Expected: PASS。

- [ ] **Step 5: 提交**
  - Commit: `fix: 统一线索留资判断口径`

---

### Phase 6: 智能体与企业号管理

**目的:** 按确认边界修正权限、删除、解绑、软删和前端字段。

**Files:**
- Modify: `app/routers/agents.py`
- Modify: `apps/agents/services.py`
- Modify: `app/routers/douyin_accounts.py`
- Modify: `app/services/douyin_account_agent_binding_service.py`
- Modify: `frontend/src/features/agents/pages/SuperMerchantAgent.tsx`
- Test: `tests/test_ai_agents.py`
- Test: `tests/test_douyin_accounts.py`

- [ ] **Step 1: 写删除测试**
  - 智能体无 active 绑定时硬删除。
  - 智能体有 active 企业号绑定时返回 409，提示先解绑。
  - 企业号删除软删，绑定记录停用。

- [ ] **Step 2: 权限统一**
  - AI小高智能体入口使用 `auto_wechat:douyin_ai_cs`。
  - 微信助手继续使用 `auto_wechat:agent`。

- [ ] **Step 3: 企业号管理前端**
  - 隐藏抖音号数字 ID 或显示 `-`。
  - 取消授权只更新本地状态为未授权。
  - 页面文案说明这是商户本地授权管理。

- [ ] **Step 4: 跑测试**
  - Run: `pytest tests/test_ai_agents.py tests/test_douyin_accounts.py -v`
  - Expected: PASS。

- [ ] **Step 5: 提交**
  - Commit: `fix: 调整智能体和企业号绑定边界`

---

### Phase 7: 微信助手真实派单与销售反馈

**目的:** 放开微信真实发送，同时解析销售反馈模板并持久化。

**Files:**
- Modify: `app/services/notification_service.py`
- Modify: `app/services/wechat_task_service.py`
- Modify: `app/routers/wechat_tasks.py`
- Create: `app/services/sales_feedback_parser.py`
- Create: `app/routers/sales_feedback.py`
- Modify: `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
- Test: `tests/test_p0_5a_wechat_tasks.py`
- Test: `tests/test_sales_feedback_parser.py`

- [ ] **Step 1: 写微信发送测试**
  - 联系人验证通过且 Agent 返回 `sent=true` 时，任务状态为 `sent`。
  - `manual_review_required`、`partial_match`、前台丢失继续 blocked/failed。
  - 不再出现“当前安全门禁保持 sent=false”。

- [ ] **Step 2: 写销售反馈解析测试**
  - 解析 `【线索反馈】` 的微信、开口、方式、车型、匹配、预算、精准、意向、地区、备注等字段。
  - 解析 `【线索更新】` 的到店、成交、时间、备注。
  - 解析 `【每日线索总结】`，只保存当天实际提交总结的销售。
  - 无反馈编号或枚举非法时进入异常记录，不污染正式字段。

- [ ] **Step 3: 实现解析服务**
  - 使用固定字段名和枚举映射，不用脆弱的全文猜测。
  - 保存原文，结构化字段可为空。
  - `反馈编号` 由系统生成并回填到派单模板。

- [ ] **Step 4: 接入 ReplyCheck**
  - 销售回复被检测后，尝试解析反馈模板。
  - 无模板但有关键字时仍可进入回访判断。

- [ ] **Step 5: 更新微信助手前端**
  - 配置项改为 5 个报表/规则开关。
  - 本机 Agent 测试页删除旧 sent=false 文案。

- [ ] **Step 6: 跑测试**
  - Run: `pytest tests/test_p0_5a_wechat_tasks.py tests/test_sales_feedback_parser.py tests/test_lead_notifications.py -v`
  - Expected: PASS。

- [ ] **Step 7: 提交**
  - Commit: `feat: 接入销售反馈模板和微信真实派单`

---

### Phase 8-A: 每日自动报表（SQL 数据补录、4 类 Excel、后台管理、安全下载、定时生成）

**目的:** 从 SQL 今日数据生成 4 类日报 Excel（留资管理表、每日销售反馈表、销售单车成本表、线索溯源表），提供后台数据补录、安全下载和上一自然日定时生成；不包含微信附件真实发送。

**规则字段口径（2026-07-12 勘误）:** 4 类日报；SalesStaff 另有 1 个线索分配开关，共 5 个规则字段（原"5 类日报"表述作废）。

**状态（2026-07-12）:** 代码与测试链路完成（Task 2-9，提交 162ef4a/9a2f596/a591bd9/0c4d875/6522742/cf18f99/976f3d6/e361aba）；甲方样例 Excel 视觉验收未完成，整体保留 `DONE_WITH_CONCERNS`。微信 Excel 附件真实发送见 Phase 8-B。

**Files:**
- Create: `app/services/daily_report_service.py`
- Create: `app/services/daily_report_excel.py`
- Create: `app/services/daily_report_storage.py`
- Create: `app/services/daily_report_job_service.py`
- Create: `app/scheduler/daily_report_scheduler.py`
- Create: `app/routers/daily_reports.py`
- Test: `tests/test_daily_report_service.py`
- Test: `tests/test_daily_report_excel.py`
- Test: `tests/test_daily_reports_api.py`
- Test: `tests/test_daily_report_scheduler.py`

- [ ] **Step 1: 写报表聚合测试**
  - 短视频/直播留资管理表来自今日留资 SQL。
  - 每日线索销售反馈表只汇总有 `【每日线索总结】` 的销售，并用 LLM 摘要。
  - 线索溯源表按来源字段和留资字段统计。
  - 销售单车成本表按 SQL 数据自动计算指标。

- [ ] **Step 2: 实现聚合服务**
  - 以 `report_date` 和 `merchant_id` 为边界。
  - 所有指标从 SQL 查询得到，不从 Excel 反算。
  - LLM 摘要失败时保留原文摘要失败标记，不影响其他报表生成。

- [ ] **Step 3: 实现 Excel 生成**
  - 生成文件记录到 `daily_report_jobs`。
  - 文件路径不返回前端绝对路径。
  - 支持 dry-run 只生成记录和预览摘要。

- [ ] **Step 4: 跑测试**
  - Run: `pytest tests/test_daily_report_service.py tests/test_daily_report_excel.py tests/test_daily_reports_api.py tests/test_daily_report_scheduler.py -v`
  - Expected: PASS（8-A 验收口径：可生成、可下载、可定时；不包含真实发送）。

- [ ] **Step 5: 提交**
  - Commit: `功能：增加每日自动报表 8-A 生成下载与定时`

### Phase 8-B: 按销售开关发送日报 Excel 附件（高风险，另开执行包）

**目的:** 按 SalesStaff 的 4 个报表开关，将 8-A 生成的 Excel 以微信附件发送给销售。

**边界:** 必须另开高风险执行包并真机验收；依赖 Local Agent / 微信 UI 自动化；不得与 8-A 混为同一阶段验收。

**Files:**
- Modify: `app/services/wechat_task_service.py`（从 8-A 文件范围移到 8-B）
- Create: WechatTask 日报附件协议（专项设计）
- Test: 真机发送验收

**验收口径区分:**
- 8-A 可生成、可下载、可定时生成 → 不等于完整 Phase 8 已真实发送。
- 完整 Phase 8 验收必须在 8-B 真机附件发送通过后才能升级为无条件 `DONE`。

---

### Phase 9: 回访提示词与微信到抖音回访闭环

**目的:** 销售微信回复触发抖音私信回访。

**Files:**
- Create: `app/services/return_visit_prompt_service.py`
- Create: `app/services/return_visit_run_service.py`
- Create: `app/routers/return_visit_prompts.py`
- Modify: `app/services/wechat_ui_reply_service.py`
- Modify: `app/services/ai_auto_reply_send_service.py`
- Test: `tests/test_return_visit_prompt_service.py`
- Test: `tests/test_return_visit_flow.py`

- [ ] **Step 1: 写提示词 API 测试**
  - 3 类全局模板存在。
  - 超管可编辑模板和启停。
  - 非超管无权限。

- [ ] **Step 2: 写回访闭环测试**
  - 销售回复“手机号不对”命中留资转化回访。
  - 销售回复“客户问金融方案”命中金融方案回访。
  - 销售微信反馈“客户长期未回复、联系不上”等语义时，命中沉默客户唤醒。
  - 一期不实现基于抖音会话时间的自动扫描唤醒；沉默客户唤醒仍由销售微信反馈触发。
  - 需要存在可用 `send_msg context`，否则只记录不能发送。

- [ ] **Step 3: 实现语义判断**
  - LLM 判断优先，关键字兜底。
  - 结果保存到 `return_visit_runs`。

- [ ] **Step 4: 生成并发送抖音私信**
  - 使用对应提示词模板生成文案。
  - 进入违禁词替换服务。
  - 调用抖音发送服务。
  - 写发送流水和回访流水。

- [ ] **Step 5: 跑测试**
  - Run: `pytest tests/test_return_visit_prompt_service.py tests/test_return_visit_flow.py -v`
  - Expected: PASS。

- [ ] **Step 6: 提交**
  - Commit: `feat: 增加回访提示词和抖音回访闭环`

---

### Phase 10: 小高算力补齐

**目的:** 套餐 seed、上浮比例、模型字段、埋点和前端页面闭环。

**Files:**
- Modify: `app/services/compute_service.py`
- Modify: `app/routers/compute.py`
- Modify: `apps/xg_douyin_ai_cs/services/compute_usage_client.py`
- Modify: `frontend/src/features/compute/pages/ComputeCenter.tsx`
- Modify: `frontend/src/features/compute/pages/SuperComputeConfig.tsx`
- Test: `tests/test_compute_service.py`
- Test: `tests/test_compute_usage_client.py`

- [x] **Step 1: 写算力测试**
  - 3 个套餐 seed 幂等。
  - 上浮比例按 6 能力配置。
  - 上报消耗必须带 `model`。
  - 余额不足不拦截，只记录风险。

- [x] **Step 2: 实现上浮比例**
  - 新增 admin API 查询/更新。
  - `/internal/compute/usage` 根据 capability 上浮后写展示消耗。
  - 保留实际 token 字段用于审计。

- [x] **Step 3: 前端接入**
  - 商户算力中心显示余额、今日/昨日/累计、流水、Mock 充值。
  - 超管算力配置页管理套餐和上浮比例。

- [x] **Step 4: 跑测试**
  - Run: `pytest tests/test_compute_service.py tests/test_compute_usage_client.py && cd frontend && npm run build`
  - Expected: PASS。

- [x] **Step 5: 提交**
  - Commit: `feat: 补齐小高算力套餐和上浮比例`

---

### Phase 11: 一键过审（CANCELLED_BY_CUSTOMER）

**状态:** 客户已于 2026-07-13 取消，不再是一期交付范围。

- 不恢复执行，不新增入口、权限码或生产验证任务。
- 不删除历史代码、迁移、表和兼容字段。
- 历史实现过程由 Git 提交和归档文档追溯，不在当前计划保留待执行清单。

---

### Phase 12: 小高素材库与 AI 小高剪辑本地 MVP

**目的:** 将 `auto_edit` 剪辑内核和 BrollStudio 自动增稳能力迁入本仓库，在安装小高AI微信助手的同一台 Windows 电脑完成真实可操作的本地剪辑闭环。

**冻结设计:** `docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md`

- [x] **Step 1: 数据、权限与迁移**
  - 扩展现有 AI剪辑任务/产物壳，增加素材、分析、模板和任务素材关系。
  - SQLite/PG 双轨迁移；所有 9000 接口校验 `auto_wechat:ai_edit` 和可信商户上下文。

- [x] **Step 2: 19000 本地素材与进程监管**
  - 本地受管素材、元数据/缩略图同步、7 天回收站和可配置资源门禁。
  - 小高AI微信助手监管随包 Python 3.11 `ai_edit_worker.exe`，默认单任务排队，支持取消和重启恢复。

- [x] **Step 3: 迁入剪辑与增稳内核**
  - 迁入纯逻辑、FunASR、分镜、候选、Vid.Stab、字幕、BGM 和 FFmpeg 双分辨率渲染。
  - 不迁 PySide6、SQLite、本地 JSON 任务库、固定豆包客户端或外部 CLI 编排。

- [x] **Step 4: 9100 规划与算力**
  - 只发送转写和结构化镜头摘要；严格校验剪辑计划，不上传原媒体。
  - 仅 9100 规划与文案建议计入现有 `compute` 算力。

- [x] **Step 5: 前端真实闭环**
  - 实现小高素材库、任务进度、720P 草稿轻量调整、1080P 成片、下载和主动云端上传。
  - 不显示假任务、假素材、假统计，不直接发布抖音。

- [x] **Step 6: 本地/模拟验收**
  - 自动化测试零真实外部网络；使用合成媒体覆盖媒体链路。（Task 10-FIX1 已闭合 4 项 Must-Fix：前端改调 19000 / 素材同步 9000 / 持久化令牌+recover / 回写有界补偿；e2e 真实前端顺序 6 测试、零网络哨兵、替身媒体合同 smoke、设计 §2-15 落地合同、Phase 12 回归。检查点 C `CHECKPOINT_C_BLOCKED`，待三方复审 PASS。）
  - 使用获授权真实汽车素材在普通 Windows CPU 电脑完成单任务闭环，9100 使用替身。（留 Phase 13 后真实 ffmpeg/Worker 联调执行，归入 `baota_ai_edit_production_not_verified` concern。）
  - 宝塔、生产数据库和真实付费模型统一留到 Phase 13 后验证。

- [x] **Step 7: 甲方测试专用单入口 EXE 交付**
  - 检查点 C 通过后已构建单文件 `小高AI系统测试版.exe`；甲方只接收和启动一个文件，内部继续保持 Local Agent/Worker 双运行时和双进程隔离。
  - 当前 EXE 使用真实测试 API `https://merchant.xiaogaoai.cn/api`、前端 `https://merchant.xiaogaoai.cn/` 和商户 `m_nc_2bba00063cc13016`，SHA-256 见 Task 11 交付报告。
  - 按用户决定，Task 11 测试包不执行许可证、Defender、archive 或 FFmpeg buildconf 门禁；正式客户安装包仍未构建。
  - 宝塔生产验证继续留到 Phase 13 完成后统一执行；修复后的测试包待重新复制到干净虚拟机复测。

---

### Phase 13: 前端入口与旧口径清理

**目的:** 所有用户可见文案和入口与确认后的产品口径一致。

**Files:**
- Modify: `frontend/src/features/capabilities.ts`
- Modify: `frontend/src/features/routes.ts`
- Modify: `frontend/src/components/SideNav.tsx`
- Modify: `frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx`
- Modify: `frontend/src/features/douyin-cs/pages/AiReplyDecisionLogsPage.tsx`
- Modify: `frontend/src/features/wechat-assistant/pages/WechatAgent.tsx`
- Modify: `frontend/src/pages/SuperForbiddenWords.tsx`
- Modify: `frontend/src/pages/SuperFollowUpPrompts.tsx`
- Test: `frontend/scripts/check-xiaogao-phase1-ui-contract.mjs`

- [ ] **Step 1: 写 UI 合同脚本**
  - 搜索并禁止旧文案：`auto_send=false`、`sent=false`、`不会自动发送`、`回复建议`。
  - 确认商户管理和管理员账号入口不展示。
  - 确认违禁词、回访提示词、AI回复记录、算力配置进入真实页面。

- [ ] **Step 2: 更新入口**
  - 商户默认进抖音AI客服。
  - 超管默认进 AI回复记录。
  - 小高素材库和 AI 小高剪辑位于 `auto_wechat:ai_edit` 能力中心；不展示已取消的一键过审入口。

- [ ] **Step 3: 工具栏补齐**
  - 表情至少支持插入文本表情。
  - 图片/视频/文件接抖音素材上传和发送；能力不足时真实失败提示并记录。

- [ ] **Step 4: 跑构建**
  - Run: `node frontend/scripts/check-xiaogao-phase1-ui-contract.mjs && cd frontend && npm run build`
  - Expected: PASS。

- [ ] **Step 5: 提交**
  - Commit: `feat: 清理一期前端旧口径`

---

## 验证矩阵

| 层级 | 命令 |
|---|---|
| 后端单元 | `pytest tests/test_forbidden_word_service.py tests/test_sales_feedback_parser.py tests/test_return_visit_flow.py -v` |
| 抖音自动回复 | `pytest tests/test_ai_auto_reply_dry_run.py tests/test_ai_auto_reply_send_service.py -v` |
| 微信派单 | `pytest tests/test_p0_5a_wechat_tasks.py tests/test_lead_notifications.py -v` |
| 数据迁移 | `pytest tests/test_xiaogao_phase1_schema.py tests/test_db_migration_0001.py -v` |
| 算力 | `pytest tests/test_compute_service.py tests/test_compute_usage_client.py -v` |
| AI剪辑 | 按 Phase 12 逐任务执行包运行素材、任务、19000、Worker、媒体和前端专项测试 |
| 前端 | `cd frontend && npm run build` |
| UI 合同 | `node frontend/scripts/check-xiaogao-phase1-ui-contract.mjs` |
| 全量回归 | `pytest` |

---

## Dry-run 与回滚

1. 所有迁移先在本地复制库执行 dry-run，输出表、字段、索引差异。
2. 自动发送发布前先开 shadow 模式：生成决策和最终内容，但不调用真实上游发送，核对违禁词和限频日志。
3. 抖音自动发送按商户白名单灰度，失败时关闭 AI 托管开关或禁用自动回复设置。
4. 微信派单按销售配置逐步开启，失败时通过紧急停止和配置开关回退。
5. 违禁词替换服务出现误替换时，可禁用对应词或词库；发送链路继续可人工接管。
6. 日报发送失败不影响数据持久化，可从 `daily_report_jobs` 人工重新生成或重发。
7. 一键过审已取消，不进入新的发布或验证流程。
8. AI剪辑按控制面、19000 协调层和随包 Worker 分层关闭；回滚不得删除原素材或已确认成片。

---

## 验收标准

1. 抖音AI客服能在绑定智能体且 AI 托管开启时自动生成、替换违禁词并真实发送私信。
2. 人工发送也经过违禁词替换，并记录最终实发内容。
3. AI回复记录展示实发内容，可由超管标记有效。
4. 线索留资按手机号、微信号、全部提取联系方式任一存在判定。
5. 微信助手可真实发送派单，失败/阻断/紧急停止有记录。
6. 销售反馈三类模板可解析并持久化。
7. 每日 5 类报表可由 SQL 今日数据生成 Excel，并按配置发送。
8. 小高算力套餐、Mock 充值、上浮比例、模型埋点可用。
9. 一键过审保持 `CANCELLED_BY_CUSTOMER`，不作为一期验收项。
10. 小高素材库和 AI 小高剪辑可在同机完成本地导入、分析、可选增稳、模拟规划、720P 草稿、轻量调整、1080P 成片和下载。
11. 商户管理、管理员账号管理不在 auto_wechat 出现假 CRUD。
12. 前端没有旧门禁文案和“回复建议不会发送”口径。

---

## 建议执行拆分

此总控计划不建议一次性由单个长任务完成。建议按以下里程碑分支执行：

1. `phase1-docs-schema`
2. `phase1-forbidden-words`
3. `phase1-douyin-auto-reply`
4. `phase1-wechat-feedback-reports`
5. `phase1-compute`
6. `phase1-ad-review`
7. `phase1-ai-edit-boundary`
8. `phase1-frontend-contract`

每个分支合并前必须至少完成对应阶段的专项测试和前端构建。

---

## 审批控制台模式

> 用户已确认：采用 Subagent-Driven 的阶段拆分和双评审机制，但本窗口只做审批和计划制定，不参与编码。

### 本窗口职责

1. 拆分阶段任务和阶段验收标准。
2. 为每个阶段准备 implementer / spec reviewer / code quality reviewer 的任务说明。
3. 审批执行窗口或子代理提交的阶段结果。
4. 判断是否允许进入下一阶段。
5. 维护计划文档和需求边界。

### 本窗口禁止事项

1. 不修改业务代码。
2. 不运行数据库迁移。
3. 不启动服务。
4. 不触发抖音、微信、巨量广告真实发送或采纳。
5. 不在当前窗口派发会直接改代码的实现任务。
6. 不绕过阶段评审直接进入下一阶段。

### 每阶段执行流

每个阶段必须在独立执行窗口或独立子代理中完成，按以下顺序返回结果：

1. **Implementer 执行**
   - 读取本计划中对应 Phase 的完整内容。
   - 使用 TDD：先写失败测试，再做最小实现。
   - 执行阶段指定测试。
   - 自审并提交变更摘要。
   - 返回状态：`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`。

2. **Spec Reviewer 评审**
   - 只检查是否满足本计划和已确认需求。
   - 明确列出缺失、超范围、误解需求。
   - 只有 `Spec Approved` 后才能进入代码质量评审。

3. **Code Quality Reviewer 评审**
   - 检查代码质量、测试有效性、安全、迁移风险、回滚能力。
   - 发现问题必须返回执行窗口修复并复评。
   - 只有 `Quality Approved` 后该阶段才可提交给本窗口审批。

4. **本窗口审批**
   - 核对阶段目标、测试结果、评审结论和剩余风险。
   - 通过后在本计划中标记阶段可进入下一阶段。
   - 未通过则要求执行窗口补充修复或重新拆分。

### 阶段回传格式

执行窗口完成每个阶段后，必须按以下格式回传：

```text
阶段：
状态：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
变更文件：
数据库迁移：
测试命令：
测试结果：
Spec Reviewer 结论：
Code Quality Reviewer 结论：
剩余风险：
需要本窗口审批的问题：
```

### 阶段准入规则

1. Phase 0 和 Phase 1 必须先执行，不能跳过。
2. Phase 2 违禁词必须早于任何真实自动发送扩大发布。
3. Phase 3 抖音自动回复真实发送必须晚于 Phase 2。
4. Phase 7 微信真实派单必须晚于 Phase 2。
5. Phase 8 日报依赖 Phase 7 的销售反馈结构化数据。
6. Phase 9 回访闭环依赖 Phase 2、Phase 3、Phase 7。
7. Phase 11 一键过审已由客户取消，不恢复执行。
8. Phase 12 按冻结设计交付本地 MVP；完成后进入 Phase 13 前端总收口，再统一制定宝塔生产验证执行包。

### 审批判定

本窗口对每个阶段只给三种结论：

```text
通过：允许进入下一阶段或合并。
有条件通过：允许继续，但必须在指定后续阶段补齐风险项。
不通过：必须回到执行窗口修复后重新评审。
```
