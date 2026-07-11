# Phase 1 数据迁移骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为小高AI系统一期先落下核心数据结构、迁移脚本和合同测试，后续业务阶段只能复用这些结构，不在本阶段接入任何发送、报表、前端或外部请求能力。

**Architecture:** 本阶段只做数据层骨架：SQLAlchemy ORM、Pydantic 结构、SQLite 过渡迁移、PostgreSQL Alembic 目标迁移和 schema 合同测试。现有 9000 主服务仍以 SQLite 开发兼容、PostgreSQL 为生产目标；执行窗口不得启动服务、不得对真实库执行迁移、不得触发抖音/巨量/微信/LLM/支付请求。

**Tech Stack:** FastAPI 结构层、SQLAlchemy ORM、SQLite 过渡迁移、PostgreSQL Alembic、pytest 静态/临时库合同测试。

---

## 阶段定位

阶段名称：`Phase 1 数据迁移骨架`

执行窗口：独立执行窗口 / 子代理。

审批窗口：当前窗口只接收结果并审批，不直接编码。

风险等级：`HIGH`

原因：本阶段涉及数据库结构、迁移文件、ORM 模型和后续阶段共享契约。即使不执行真实迁移，也必须按高风险流程设计、测试和回滚。

## 已知当前状态

正式仓库：

```text
路径：E:\work\project\auto_wechat
分支：master
状态：master...origin/master [ahead 24]
最近提交：6df4d8d docs：补充Phase 0-D清理执行包
工作区：执行前必须重新确认干净
```

当前迁移版本：

```text
SQLite 最新：migrations/versions/0026_external_merchant_bindings_unique_active_user.sql
PostgreSQL 9000 最新：migrations/postgres/auto_wechat/versions/0007_lead_type_widen.py
PostgreSQL 最新 revision：0007_lead_type_widen
PostgreSQL 最新 down_revision：0006_runtime_cutover_gap
```

Phase 1 本轮新迁移必须使用：

```text
SQLite：migrations/versions/0027_xiaogao_phase1_core.sql
PostgreSQL：migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py
revision = "0008_xiaogao_phase1_core"
down_revision = "0007_lead_type_widen"
```

注意：总控计划早期曾把 Phase 1 PostgreSQL 迁移编号写成 `0007`，该编号已经被 `0007_lead_type_widen.py` 占用。本执行包以 `0008` 为准。

## 本阶段目标

1. 给 `sales_staff` 增加 5 个规则布尔字段。
2. 给 `ai_reply_decision_logs` 增加有效性和模型字段。
3. 新增一期后续模块共用的数据表骨架。
4. 写入固定种子：3 类违禁词库、3 类回访提示词、3 个算力套餐、6 个算力上浮能力。
5. 提供 SQLite 过渡迁移和 PostgreSQL Alembic 目标迁移。
6. 提供 `tests/test_xiaogao_phase1_schema.py`，用合同测试锁定字段、版本、表名、seed、PG 禁止 SQLite 语法和 SQLite 临时库幂等 apply。

## 允许范围

本阶段允许修改：

```text
app/models.py
app/schemas.py
migrations/versions/0027_xiaogao_phase1_core.sql
migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py
tests/test_xiaogao_phase1_schema.py
```

本阶段允许只读参考：

```text
CLAUDE.md
docs/ai/01_READING_RULES.md
docs/ai/05_PROJECT_CONTEXT.md
docs/ai/02_EXECUTION_RULES.md
docs/ai/03_TESTING_RULES.md
docs/ai/04_OUTPUT_RULES.md
docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md
docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md
docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
migrations/migrate_sqlite.py
tests/test_db_migration_runner.py
tests/test_9000_postgres_runtime_cutover_gap_schema.py
tests/test_9000_postgres_compute_core_schema.py
```

如确需修改其他文件，必须停止并回传 `NEEDS_CONTEXT`，由审批窗口重新批准。

## 禁止事项

1. 禁止接入业务逻辑、service、router、scheduler、worker 或前端页面。
2. 禁止启动 9000 / 9100 / 19000 / 前端服务。
3. 禁止执行真实数据库迁移 apply；只允许在 pytest 临时 SQLite 文件上验证。
4. 禁止连接宝塔 production、读取 production SQLite、连接真实 PostgreSQL production。
5. 禁止触发抖音私信、巨量广告、微信自动化、LLM、Milvus、支付、短信、邮件等真实请求。
6. 禁止修改 `input_writer`、`contact_searcher`、微信 UI 自动化、Local Agent 发送链路。
7. 禁止新增依赖。
8. 禁止新增权限码。
9. 禁止把 Phase 2+ 的 API、页面、发送 gate、报表生成、Excel 生成、解析服务顺手实现。
10. 禁止在 PostgreSQL Alembic 迁移中出现 SQLite 专属语法：`IF NOT EXISTS`、`PRAGMA`、`INSERT OR IGNORE`、`datetime('now')`、`sqlite_autoincrement`。
11. 禁止在迁移、测试或文档中写入真实 token、password、连接串、Authorization、cookie 或完整客户消息。

## 数据结构设计

### 修改现有表

`sales_staff` 新增 5 个字段：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enable_lead_assignment` | Boolean | true | 是否参与线索分配；默认 true，避免后续接入时破坏现有分配行为 |
| `enable_short_video_live_lead_report` | Boolean | false | 是否接收短视频/直播留资管理表 |
| `enable_daily_sales_feedback_report` | Boolean | false | 是否接收每日线索销售反馈表 |
| `enable_lead_trace_report` | Boolean | false | 是否接收线索溯源表 |
| `enable_sales_unit_cost_report` | Boolean | false | 是否接收销售单车成本表 |

`ai_reply_decision_logs` 新增 3 个字段：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `is_effective` | Boolean nullable | null | 超管人工标记：null=未标记，true=有效，false=无效 |
| `effectiveness_reason` | Text nullable | null | 人工标记原因 |
| `model` | String(128) nullable | null | 对齐 `ComputeTransaction.model`，记录实际模型 |

### 新增全局配置表

这些表不按商户隔离，但必须有 `scope`、固定 key 或全局说明：

1. `forbidden_word_libraries`
   - 字段：`id`、`library_key`、`name`、`description`、`scope`、`enabled`、`sort_order`、`created_at`、`updated_at`
   - 唯一约束：`library_key`
   - seed：
     - `used_car_sales_base` / `二手车销售基础违禁词`
     - `finance_compliance` / `金融方案合规词库`
     - `vehicle_condition_risk` / `车况承诺风险词`

2. `forbidden_words`
   - 字段：`id`、`library_id`、`word`、`safe_word`、`severity`、`enabled`、`hit_count`、`created_at`、`updated_at`
   - 唯一约束：`library_id + word`
   - 本阶段只建表，不预置具体词条。

3. `return_visit_prompts`
   - 字段：`id`、`prompt_key`、`name`、`scene_type`、`template_text`、`scope`、`enabled`、`sort_order`、`created_at`、`updated_at`
   - 唯一约束：`prompt_key`
   - seed：
     - `retain_contact_conversion` / `留资转化回访`
     - `finance_plan_followup` / `金融方案回访`
     - `silent_customer_wakeup` / `沉默客户唤醒`

4. `compute_markup_ratios`
   - 字段：`id`、`capability_key`、`markup_basis_points`、`enabled`、`created_at`、`updated_at`
   - 唯一约束：`capability_key`
   - `markup_basis_points` 使用基点，`3300` 表示 33%，避免用浮点存配置。
   - seed 能力键必须且只能为：
     - `douyin-cs`
     - `leads`
     - `agents`
     - `wechat-assistant`
     - `compute`
     - `knowledge`

### 新增商户业务表

这些表必须有 `merchant_id`：

1. `forbidden_word_hit_logs`
   - 字段：`id`、`merchant_id`、`library_key`、`word`、`safe_word`、`source`、`context_type`、`context_id`、`before_text_summary`、`after_text_summary`、`created_at`
   - 说明：只保存摘要，不在本阶段设计完整 raw LLM response 或完整客户消息。

2. `return_visit_runs`
   - 字段：`id`、`merchant_id`、`lead_id`、`staff_id`、`reply_check_id`、`prompt_key`、`trigger_source`、`trigger_text`、`judgement_source`、`judgement_result`、`generated_content`、`final_content`、`send_status`、`send_id`、`error_message`、`created_at`、`updated_at`

3. `sales_lead_feedbacks`
   - 字段：`id`、`merchant_id`、`feedback_no`、`lead_id`、`staff_id`、`raw_text`、`wechat_status`、`opening_status`、`payment_method`、`car_model`、`match_status`、`budget_text`、`precision_status`、`imprecision_reason`、`intention_level`、`no_intention_reason`、`region_text`、`remark`、`parse_status`、`parse_error`、`feedback_date`、`created_at`、`updated_at`
   - 唯一约束：`merchant_id + feedback_no`

4. `sales_lead_updates`
   - 字段：`id`、`merchant_id`、`feedback_no`、`lead_id`、`staff_id`、`raw_text`、`visit_status`、`visit_time_text`、`deal_status`、`deal_time_text`、`remark`、`parse_status`、`parse_error`、`created_at`、`updated_at`

5. `sales_daily_summaries`
   - 字段：`id`、`merchant_id`、`staff_id`、`summary_date`、`sales_name`、`raw_text`、`overall_quality`、`main_problem`、`car_model_summary`、`budget_summary`、`cooperation_level`、`today_suggestion`、`extra_feedback`、`parse_status`、`parse_error`、`created_at`、`updated_at`
   - 唯一约束：`merchant_id + staff_id + summary_date`

6. `daily_report_jobs`
   - 字段：`id`、`merchant_id`、`report_date`、`report_type`、`receiver_staff_id`、`status`、`file_storage_key`、`file_name`、`error_message`、`generated_at`、`sent_at`、`created_at`、`updated_at`
   - 说明：不返回绝对路径；`file_storage_key` 为内部存储键。

7. `ad_review_oauth_accounts`
   - 字段：`id`、`merchant_id`、`advertiser_id`、`account_name`、`auth_status`、`access_token_cipher`、`refresh_token_cipher`、`token_expires_at`、`raw_body_json`、`created_at`、`updated_at`、`deleted_at`
   - 说明：一键过审授权账号独立于 `douyin_authorized_accounts`，不得建立强外键耦合。

8. `ad_review_suggestions`
   - 字段：`id`、`merchant_id`、`oauth_account_id`、`suggestion_key`、`advertiser_id`、`ad_id`、`material_id`、`rejection_reason`、`suggestion_text`、`adopt_status`、`raw_body_json`、`pulled_at`、`created_at`、`updated_at`
   - 唯一约束：`merchant_id + suggestion_key`

9. `ad_review_adopt_tasks`
   - 字段：`id`、`merchant_id`、`oauth_account_id`、`task_key`、`suggestion_ids_json`、`status`、`request_body_json`、`response_body_json`、`error_message`、`created_at`、`updated_at`、`completed_at`
   - 唯一约束：`merchant_id + task_key`

10. `ai_edit_jobs`
    - 字段：`id`、`merchant_id`、`job_id`、`status`、`source_type`、`input_json`、`result_json`、`error_message`、`created_at`、`updated_at`、`completed_at`
    - 唯一约束：`job_id`
    - 说明：只做 AI 剪辑迁入后的任务壳，不接外部 `auto_edit`。

11. `ai_edit_job_artifacts`
    - 字段：`id`、`merchant_id`、`job_id`、`artifact_id`、`artifact_type`、`storage_key`、`file_name`、`mime_type`、`file_size_bytes`、`created_at`
    - 唯一约束：`artifact_id`
    - 说明：禁止保存或返回外部仓库绝对路径。

### 套餐 seed

`compute_packages` 已存在，本阶段只写入幂等 seed：

| name | price_yuan | token_amount |
|---|---:|---:|
| 基础版 | 99 | 100000 |
| 标准版 | 299 | 350000 |
| 专业版 | 699 | 900000 |

## 停止门禁

执行窗口遇到以下任一情况必须停止并回传：

1. `git status --short --branch` 显示业务文件存在未提交改动。
2. `migrations/versions/0027_xiaogao_phase1_core.sql` 已存在。
3. `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py` 已存在。
4. PostgreSQL 最新迁移不再是 `0007_lead_type_widen.py`。
5. 已存在同名模型类或同名表结构，且与本执行包字段不一致。
6. 需要修改允许范围以外的文件。
7. 任何测试需要连接真实 PostgreSQL、production SQLite、抖音、巨量、微信、LLM、Milvus 或支付。

回传状态按实际情况使用 `NEEDS_CONTEXT` 或 `BLOCKED`。

## Task 1: 执行前核验和隔离工作区

**Files:**
- Read: `E:\work\project\auto_wechat`
- Optional create by Git: `E:\work\project\auto_wechat\.worktrees\phase1-data-migration-skeleton`

- [ ] **Step 1: 读取项目入口文件**

```powershell
Get-Content -Raw -Encoding UTF8 CLAUDE.md
Get-Content -Raw -Encoding UTF8 docs\ai\01_READING_RULES.md
Get-Content -Raw -Encoding UTF8 docs\ai\05_PROJECT_CONTEXT.md
Get-Content -Raw -Encoding UTF8 docs\ai\02_EXECUTION_RULES.md
Get-Content -Raw -Encoding UTF8 docs\ai\03_TESTING_RULES.md
Get-Content -Raw -Encoding UTF8 docs\ai\04_OUTPUT_RULES.md
Get-Content -Raw -Encoding UTF8 docs\ai\03_data_and_migration\POSTGRESQL_MIGRATION_NOTES.md
Get-Content -Raw -Encoding UTF8 docs\ai\01_product_prd\小高AI系统一期_需求理解与VibeCoding指令.md
```

预期：能复述 Phase 1 目标、允许范围、禁止事项、验收标准。

- [ ] **Step 2: 确认正式仓库状态**

```powershell
git status --short --branch
git log --oneline -5
```

预期：

```text
## master...origin/master [ahead 24]
```

允许 ahead 数字因用户提交变化而变化，但不能有未提交文件。若有未提交文件，停止。

- [ ] **Step 3: 建议创建独立 worktree**

如果执行窗口使用 worktree，推荐：

```powershell
git worktree add .worktrees/phase1-data-migration-skeleton master
```

后续命令工作目录切到：

```text
E:\work\project\auto_wechat\.worktrees\phase1-data-migration-skeleton
```

如不使用 worktree，必须在回传中说明原因，并证明正式仓库工作区干净。

- [ ] **Step 4: 确认迁移编号**

```powershell
Get-ChildItem migrations\versions | Sort-Object Name | Select-Object -ExpandProperty Name
Get-ChildItem migrations\postgres\auto_wechat\versions | Sort-Object Name | Select-Object -ExpandProperty Name
```

预期：

```text
SQLite 最新包含 0026_external_merchant_bindings_unique_active_user.sql
PostgreSQL 最新包含 0007_lead_type_widen.py
不存在 0027_xiaogao_phase1_core.sql
不存在 0008_xiaogao_phase1_core.py
```

## Task 2: 先写失败的 schema 合同测试

**Files:**
- Create: `tests/test_xiaogao_phase1_schema.py`

- [ ] **Step 1: 创建测试文件**

测试文件必须至少包含以下用例：

```text
test_sqlite_migration_file_exists_and_version
test_postgres_revision_file_exists_and_revisions
test_sales_staff_has_five_report_flags
test_ai_reply_decision_logs_has_effectiveness_and_model_fields
test_phase1_new_tables_are_declared_in_models
test_pydantic_schemas_declare_phase1_structures
test_postgres_revision_creates_expected_tables_and_columns
test_postgres_revision_adds_existing_table_columns
test_postgres_revision_has_no_sqlite_specific_syntax
test_compute_markup_ratios_has_six_capability_keys
test_seed_data_contains_fixed_libraries_prompts_packages
test_sqlite_migration_apply_on_temp_db_is_idempotent
test_ad_review_tables_do_not_foreign_key_douyin_authorized_accounts
test_ai_edit_artifacts_do_not_store_absolute_paths
```

测试实现建议：

1. 对 PostgreSQL 迁移使用纯文本断言，参考 `tests/test_9000_postgres_runtime_cutover_gap_schema.py`。
2. 对 ORM 使用 `from app.models import ...` 后检查 `__tablename__`、`__table__.columns`、`__table__.indexes`。
3. 对 SQLite 迁移使用临时库创建最小前置表后调用 `migrations.migrate_sqlite.apply_migration()`。
4. 不连接真实 PostgreSQL。

- [ ] **Step 2: 跑红灯**

```powershell
pytest tests/test_xiaogao_phase1_schema.py -v
```

预期：失败，至少因为迁移文件和模型类不存在。

若测试因为 import 项目现有代码失败且与本阶段无关，先记录完整错误并停止回传 `NEEDS_CONTEXT`。

## Task 3: 修改 ORM 模型和 Pydantic 结构

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`

- [ ] **Step 1: 修改 `SalesStaff` 和 `AiReplyDecisionLog`**

要求：

1. `SalesStaff` 加 5 个规则布尔字段。
2. `enable_lead_assignment` 默认 true。
3. 其他 4 个报表字段默认 false。
4. `AiReplyDecisionLog.is_effective` 必须允许 null。
5. 不修改现有发送逻辑注释以外的业务行为。

- [ ] **Step 2: 新增模型类**

新增模型类必须与数据结构设计章节一致，类名建议：

```text
ForbiddenWordLibrary
ForbiddenWord
ForbiddenWordHitLog
ReturnVisitPrompt
ReturnVisitRun
SalesLeadFeedback
SalesLeadUpdate
SalesDailySummary
DailyReportJob
ComputeMarkupRatio
AdReviewOAuthAccount
AdReviewSuggestion
AdReviewAdoptTask
AiEditJob
AiEditJobArtifact
```

要求：

1. 表名使用小写下划线复数，和本执行包一致。
2. 商户业务表必须有 `merchant_id`。
3. 全局配置表必须有 `scope`、固定 key 或全局说明。
4. 不在模型里新增 relationship，除非测试必须；本阶段以结构骨架为主。
5. 不拆分 `models.py`，保持项目现有单文件模型风格，避免 Phase 1 做无关重构。

- [ ] **Step 3: 新增 Pydantic 结构**

在 `app/schemas.py` 增加最小结构类，建议命名：

```text
ForbiddenWordLibraryOut
ForbiddenWordOut
ForbiddenWordHitLogOut
ReturnVisitPromptOut
ReturnVisitRunOut
SalesLeadFeedbackOut
SalesLeadUpdateOut
SalesDailySummaryOut
DailyReportJobOut
ComputeMarkupRatioOut
AdReviewOAuthAccountOut
AdReviewSuggestionOut
AdReviewAdoptTaskOut
AiEditJobOut
AiEditJobArtifactOut
AiReplyDecisionEffectivenessPatch
```

要求：

1. 只定义结构，不接 router。
2. 使用项目现有 Pydantic 版本兼容写法。
3. 不引入新依赖。

- [ ] **Step 4: 跑针对性测试**

```powershell
pytest tests/test_xiaogao_phase1_schema.py -v
```

预期：与模型和 schema 相关的断言转绿，迁移文件相关断言仍失败。

## Task 4: 添加 SQLite 过渡迁移

**Files:**
- Create: `migrations/versions/0027_xiaogao_phase1_core.sql`

- [ ] **Step 1: 创建迁移文件**

要求：

1. 文件头说明本阶段只做结构骨架和 seed。
2. 使用 `ALTER TABLE ... ADD COLUMN` 补现有表字段。
3. 使用 `CREATE TABLE IF NOT EXISTS` 和 `CREATE INDEX IF NOT EXISTS`。
4. seed 使用 `INSERT INTO ... SELECT ... WHERE NOT EXISTS (...)`，避免重复插入。
5. 不依赖 PostgreSQL 语法。

- [ ] **Step 2: SQLite 前置表兼容**

测试中的临时库至少需要先建这些前置表，再应用 `0027`：

```text
schema_migrations
sales_staff
ai_reply_decision_logs
compute_packages
```

如果 `0027` 要引用其他已存在表，测试也必须创建最小前置表。

- [ ] **Step 3: 迁移内容要求**

`0027` 必须包含：

1. `sales_staff` 五个字段。
2. `ai_reply_decision_logs` 三个字段。
3. 15 张新增表。
4. 3 类违禁词库 seed。
5. 3 类回访提示词 seed。
6. 3 个套餐 seed。
7. 6 个 `compute_markup_ratios` seed。

- [ ] **Step 4: 跑 SQLite 临时库测试**

```powershell
pytest tests/test_xiaogao_phase1_schema.py::test_sqlite_migration_apply_on_temp_db_is_idempotent -v
```

预期：通过。测试应验证第一次 apply 成功，第二次同版本 apply 被 `schema_migrations` 幂等跳过，核心列、表和 seed 存在。

## Task 5: 添加 PostgreSQL Alembic 目标迁移

**Files:**
- Create: `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py`

- [ ] **Step 1: 创建 Alembic 文件**

文件必须包含：

```python
revision = "0008_xiaogao_phase1_core"
down_revision = "0007_lead_type_widen"
branch_labels = None
depends_on = None
```

- [ ] **Step 2: upgrade 要求**

`upgrade()` 必须：

1. `op.add_column` 给 `sales_staff` 加 5 个字段。
2. `op.add_column` 给 `ai_reply_decision_logs` 加 3 个字段。
3. `op.create_table` 创建本执行包列出的新增表。
4. `op.create_index` 创建必要索引。
5. 对关键枚举使用 `sa.CheckConstraint`。
6. 对 JSON 字段使用 `postgresql.JSONB(astext_type=sa.Text())`。
7. 使用 `sa.DateTime(timezone=True)` 和 `server_default=sa.text("now()")`。
8. seed 使用 PostgreSQL 安全写法，例如 `ON CONFLICT DO NOTHING` 或等效幂等 SQL。

- [ ] **Step 3: downgrade 要求**

`downgrade()` 必须：

1. 按依赖反向 drop 本阶段新增表。
2. 本阶段新增到现有表的字段可以 drop，但必须在注释中说明会丢弃 Phase 1 后产生的新配置值。
3. 不 drop `sales_staff`、`ai_reply_decision_logs`、`compute_packages` 等既有核心表。

- [ ] **Step 4: PostgreSQL 迁移静态测试**

```powershell
pytest tests/test_xiaogao_phase1_schema.py::test_postgres_revision_file_exists_and_revisions tests/test_xiaogao_phase1_schema.py::test_postgres_revision_has_no_sqlite_specific_syntax -v
```

预期：通过。

## Task 6: 全阶段验证

**Files:**
- Test only.

- [ ] **Step 1: 跑 Phase 1 专项测试**

```powershell
pytest tests/test_xiaogao_phase1_schema.py -v
```

预期：全部通过。

- [ ] **Step 2: 跑相邻迁移测试**

```powershell
pytest tests/test_xiaogao_phase1_schema.py tests/test_db_migration_runner.py tests/test_9000_postgres_runtime_cutover_gap_schema.py tests/test_9000_postgres_compute_core_schema.py -v
```

预期：全部通过。

- [ ] **Step 3: 语法/空白检查**

```powershell
git diff --check -- app/models.py app/schemas.py migrations/versions/0027_xiaogao_phase1_core.sql migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py tests/test_xiaogao_phase1_schema.py
```

预期：无输出，退出码 0。

- [ ] **Step 4: 工作区摘要**

```powershell
git status --short --branch
git diff --stat -- app/models.py app/schemas.py migrations/versions/0027_xiaogao_phase1_core.sql migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py tests/test_xiaogao_phase1_schema.py
```

预期：只出现本阶段允许的 5 个文件。

## Task 7: 提交和回传

**Files:**
- Commit allowed files only.

- [ ] **Step 1: 提交**

```powershell
git add -- app/models.py app/schemas.py migrations/versions/0027_xiaogao_phase1_core.sql migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py tests/test_xiaogao_phase1_schema.py
git commit -m "db：增加小高AI一期数据迁移骨架"
```

如果执行窗口所在流程不允许提交，必须回传未提交 diff 摘要，并说明未提交原因。

- [ ] **Step 2: 按固定格式回传**

```text
阶段：Phase 1 数据迁移骨架
状态：DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED

工作区：
- 路径：
- 分支：
- 当前 HEAD：
- git status：

变更文件：
- app/models.py
- app/schemas.py
- migrations/versions/0027_xiaogao_phase1_core.sql
- migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py
- tests/test_xiaogao_phase1_schema.py

数据库迁移：
- SQLite 过渡迁移：0027_xiaogao_phase1_core.sql
- PostgreSQL Alembic：0008_xiaogao_phase1_core.py
- 是否执行真实库 apply：否
- 是否只在临时 SQLite 测试库 apply：是 / 否

业务逻辑改动：无
前端交互改动：无
服务启动 / 真实请求：无
未触碰：input_writer、contact_searcher、微信 UI 自动化、Local Agent、发送链路、router/service、前端页面

测试命令：
- pytest tests/test_xiaogao_phase1_schema.py -v
- pytest tests/test_xiaogao_phase1_schema.py tests/test_db_migration_runner.py tests/test_9000_postgres_runtime_cutover_gap_schema.py tests/test_9000_postgres_compute_core_schema.py -v
- git diff --check -- ...

测试结果：
- 首次红灯：
- 最终绿灯：
- 未执行测试及原因：

Implementer 自审结论：
- 是否只修改允许文件：是 / 否
- 是否没有业务逻辑/API/前端接入：是 / 否
- 是否没有真实库 apply：是 / 否
- 是否没有真实请求：是 / 否
- PostgreSQL down_revision 是否为 0007_lead_type_widen：是 / 否
- SQLite 迁移是否为 0027：是 / 否
- 是否包含固定 seed：是 / 否

Spec Reviewer 结论：Approved / Changes Required
Code Quality Reviewer 结论：Approved / Changes Required

剩余风险：
- Phase 1 只代表结构骨架，不代表违禁词服务、回访闭环、日报、自动发送、一键过审或 AI 剪辑已接入。
- PostgreSQL 迁移未对真实库执行 apply，需要后续阶段按 dry-run / staging / production 审批流程执行。

需要本窗口审批的问题：
- 是否允许宣布 Phase 1 数据迁移骨架通过。
- 是否允许进入 Phase 2 违禁词统一替换服务执行包制定。
```

## Spec Reviewer 清单

Spec Reviewer 只检查需求覆盖和边界：

1. 是否严格只覆盖 Phase 1 数据结构骨架。
2. 是否没有实现 Phase 2+ 的 service/router/前端/发送/报表/解析逻辑。
3. `sales_staff` 是否是确认后的 5 个字段，不是旧 4 字段。
4. 留资相关表是否能承接 `【线索反馈】`、`【线索更新】`、`【每日线索总结】`。
5. `sales_daily_summaries` 是否支持“只汇总有反馈的销售”。
6. `ai_reply_decision_logs` 是否有 `is_effective`、`effectiveness_reason`、`model`。
7. 违禁词库 seed 是否是 3 类固定词库。
8. 回访提示词 seed 是否是 3 类固定提示词。
9. `compute_markup_ratios` 是否只包含 6 个能力 key。
10. 一键过审表是否独立于抖音企业号授权表。
11. AI 剪辑表是否只是任务壳和产物映射，不依赖外部 `auto_edit`。
12. 是否没有新增权限码。

结论格式：

```text
Spec Reviewer 结论：Approved / Changes Required
问题列表：
是否允许进入 Code Quality Reviewer：是 / 否
```

## Code Quality Reviewer 清单

Code Quality Reviewer 在 Spec Approved 后执行：

1. 变更文件是否只包含允许的 5 个文件。
2. ORM、Pydantic、SQLite 迁移、PostgreSQL 迁移、测试之间字段名是否一致。
3. PostgreSQL 迁移 revision/down_revision 是否正确。
4. PostgreSQL 迁移是否没有 SQLite 专属语法。
5. SQLite 迁移是否能在临时库幂等 apply。
6. 新表是否有必要索引和唯一约束。
7. 商户业务表是否都有 `merchant_id`。
8. 全局配置表是否有固定 key / scope。
9. seed 是否幂等。
10. downgrade 是否不删除既有核心表。
11. 测试是否真正验证字段、表、seed 和迁移编号，而不是只检查文件存在。
12. `git diff --check` 是否通过。
13. 是否没有真实库 apply、服务启动或真实请求。

结论格式：

```text
Code Quality Reviewer 结论：Approved / Changes Required
问题列表：
剩余风险：
```

## 本窗口审批清单

收到执行结果后，本窗口只做审批：

1. 回传格式是否完整。
2. 执行状态是否为 `DONE` 或可接受的 `DONE_WITH_CONCERNS`。
3. Implementer 自审是否完整。
4. Spec Reviewer 是否 Approved。
5. Code Quality Reviewer 是否 Approved。
6. 是否只修改允许的 5 个文件。
7. 是否没有真实库 apply、服务启动、真实请求、发送链路或前端交互改动。
8. 测试命令和结果是否可信。
9. 是否可宣布 Phase 1 数据迁移骨架完成。
10. 是否可进入 Phase 2 违禁词统一替换服务执行包制定。

审批结论只能是：

```text
通过：Phase 1 数据迁移骨架完成，可制定 Phase 2 执行包。
有条件通过：Phase 1 主目标完成，但必须在指定后续阶段补齐风险项。
不通过：返回执行窗口修复后重新评审。
```
