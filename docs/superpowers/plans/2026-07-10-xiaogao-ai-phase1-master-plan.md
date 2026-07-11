# 小高AI系统一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `auto_wechat` 中完成小高AI系统一期扩展：抖音AI客服自动回复闭环、线索与留资口径、微信助手真实派单与日报、违禁词、回访提示词、AI回复记录、算力配置、一键过审、AI剪辑迁入预留。

**Architecture:** `auto_wechat` 9000 继续作为控制面，负责登录态消费、权限、商户隔离、任务持久化、审计和前端 API；9100 `apps/xg_douyin_ai_cs` 保持抖音AI客服/RAG/LLM 独立服务；19000 Local Agent 继续只负责本机微信 UI 自动化。`douyinAPI` 和 `auto_edit` 只作为迁移来源，不作为长期生产依赖；`auto_edit` 后续代码迁入本仓库后仍以独立服务或 Worker 边界运行。

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
11. 一键过审：复制改造 `douyinAPI` 的巨量广告 OAuth 和拒审建议采纳能力，运行时不依赖 `douyinAPI`。
12. AI 剪辑：`auto_edit` 由同事先完成，后续源码迁入 `auto_wechat` 仓库，迁入后仍保持独立模块边界。
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
| `ai_edit_jobs` | AI 剪辑迁入后任务壳，当前可只建迁移草案，不提前接执行 |
| `ai_edit_job_artifacts` | AI 剪辑产物映射，禁止暴露内部绝对路径 |

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
  - 断言需求理解文档包含 AI 剪辑、一键过审、5 个报表规则字段、`all_extracted_contacts` 留资口径、自动发送放开。
  - 断言文档不再包含“AI剪辑不属于一期”“sent 必须为 false”“系统最终保持 auto_send=false”。
  - Run: `pytest tests/test_xiaogao_phase1_context_contract.py -v`
  - Expected: FAIL，缺少新测试或旧文档口径未改。

- [ ] **Step 2: 更新项目上下文**
  - 把旧 4 个规则字段改为 5 个确认字段。
  - 将 AI 剪辑改为一期范围内的迁入预留。
  - 将一键过审改为一期范围内的复制改造项。
  - 明确 NewCarProject 上游边界。
  - 明确 `auto_wechat:ai_edit` 覆盖 AI剪辑和一键过审。

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

### Phase 8: 每日自动报表

**目的:** 从 SQL 今日数据生成 5 类日报 Excel，并按销售配置发送。

**Files:**
- Create: `app/services/daily_report_service.py`
- Create: `app/services/daily_report_excel.py`
- Create: `app/routers/daily_reports.py`
- Modify: `app/services/wechat_task_service.py`
- Test: `tests/test_daily_report_service.py`
- Test: `tests/test_daily_report_excel.py`

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

- [ ] **Step 4: 实现按配置发送**
  - 销售配置启用哪个表，就发送哪个 Excel。
  - 发送失败记录 `failed` 和错误原因，不无限重试。

- [ ] **Step 5: 跑测试**
  - Run: `pytest tests/test_daily_report_service.py tests/test_daily_report_excel.py -v`
  - Expected: PASS。

- [ ] **Step 6: 提交**
  - Commit: `feat: 增加服务端每日自动报表`

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
  - 长时间未回复命中沉默客户唤醒。
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

- [ ] **Step 1: 写算力测试**
  - 3 个套餐 seed 幂等。
  - 上浮比例按 6 能力配置。
  - 上报消耗必须带 `model`。
  - 余额不足不拦截，只记录风险。

- [ ] **Step 2: 实现上浮比例**
  - 新增 admin API 查询/更新。
  - `/internal/compute/usage` 根据 capability 上浮后写展示消耗。
  - 保留实际 token 字段用于审计。

- [ ] **Step 3: 前端接入**
  - 商户算力中心显示余额、今日/昨日/累计、流水、Mock 充值。
  - 超管算力配置页管理套餐和上浮比例。

- [ ] **Step 4: 跑测试**
  - Run: `pytest tests/test_compute_service.py tests/test_compute_usage_client.py && cd frontend && npm run build`
  - Expected: PASS。

- [ ] **Step 5: 提交**
  - Commit: `feat: 补齐小高算力套餐和上浮比例`

---

### Phase 11: 一键过审

**目的:** 从 `douyinAPI` 复制改造巨量广告一键过审能力，纳入 `auto_wechat:ai_edit`。

**Files:**
- Create: `app/services/ad_review_oauth_service.py`
- Create: `app/services/ad_review_service.py`
- Create: `app/routers/ad_review.py`
- Create: `frontend/src/features/ai-edit/pages/AdReviewPage.tsx`
- Modify: `frontend/src/features/capabilities.ts`
- Modify: `frontend/src/features/routes.ts`
- Test: `tests/test_ad_review_service.py`
- Test: `tests/test_ad_review_api.py`

- [ ] **Step 1: 写接口测试**
  - OAuth 获取授权链接和回调记录按商户隔离。
  - 拉取拒审建议默认最近 7 天、未采纳。
  - 根据 `mid` 查询同主体账户建议。
  - 创建异步采纳任务一次最多 50 条。
  - 轮询采纳结果。

- [ ] **Step 2: 复制并重组 douyinAPI 代码**
  - 不复制单文件 `app.py` 的结构。
  - 把 OAuth、签名、API client、任务服务拆开。
  - 去掉全局最新 token，改为商户隔离授权记录。

- [ ] **Step 3: 前端页面**
  - 独立于抖音企业号管理。
  - 使用 `auto_wechat:ai_edit` 权限。
  - 展示建议列表、同主体查询、采纳任务、轮询结果。

- [ ] **Step 4: 跑测试**
  - Run: `pytest tests/test_ad_review_service.py tests/test_ad_review_api.py && cd frontend && npm run build`
  - Expected: PASS。

- [ ] **Step 5: 提交**
  - Commit: `feat: 接入巨量广告一键过审`

---

### Phase 12: AI剪辑迁入预留

**目的:** 为 `auto_edit` 迁入仓库做边界准备，不提前绑定未交付实现。

**Files:**
- Create: `apps/ai_edit/README.md`
- Create: `app/routers/ai_edit.py`
- Create: `frontend/src/features/ai-edit/routes.ts`
- Modify: `frontend/src/pages/AiVideoEditor.tsx`
- Test: `tests/test_ai_edit_boundary.py`

- [ ] **Step 1: 写边界测试**
  - `/ai-edit/*` 需要 `auto_wechat:ai_edit`。
  - 未配置剪辑服务时返回明确 `not_configured`，不造假任务。
  - 不允许前端传内部路径。

- [ ] **Step 2: 预留服务边界**
  - 只放健康检查、任务壳、配置检查。
  - 不调用外部 `E:\work\project\auto_edit` CLI。
  - 文档写明迁入目录建议为 `apps/ai_edit`。

- [ ] **Step 3: 前端预留页**
  - 显示真实接入状态。
  - 不加载假任务、假素材、假统计。

- [ ] **Step 4: 跑测试**
  - Run: `pytest tests/test_ai_edit_boundary.py && cd frontend && npm run build`
  - Expected: PASS。

- [ ] **Step 5: 提交**
  - Commit: `chore: 预留AI剪辑迁入边界`

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
  - AI剪辑和一键过审位于 `auto_wechat:ai_edit` 能力中心。

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
| 一键过审 | `pytest tests/test_ad_review_service.py tests/test_ad_review_api.py -v` |
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
7. 一键过审失败只影响 `ad_review_adopt_tasks` 状态，不回滚已成功采纳的巨量广告上游任务。
8. AI剪辑预留阶段不执行真实剪辑，因此回滚仅删除入口和任务壳。

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
9. 一键过审可完成 OAuth、建议拉取、同主体查询、异步采纳、结果轮询。
10. AI剪辑入口不造假，等待 `auto_edit` 迁入后接真实任务。
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
7. Phase 11 一键过审可与 Phase 3/7 并行，但必须等 Phase 1 数据迁移骨架完成。
8. Phase 12 AI剪辑只做预留，正式迁入需另开迁入专项计划。

### 审批判定

本窗口对每个阶段只给三种结论：

```text
通过：允许进入下一阶段或合并。
有条件通过：允许继续，但必须在指定后续阶段补齐风险项。
不通过：必须回到执行窗口修复后重新评审。
```
