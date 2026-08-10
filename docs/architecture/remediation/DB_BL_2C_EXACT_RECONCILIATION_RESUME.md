# DB-BL-2C-RESUME — auto_wechat PostgreSQL Exact Reconciliation（R2 修复后恢复）

> 报告日期：2026-08-10
> 阶段：DB-BL-2C `AUTHORIZED_TO_RESUME`（原 `BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` 已由 R2 正式解除）
> 模式：**EXACT RECONCILIATION**（只读对账 + disposable PG 受控 bootstrap）
> 角色：**DB-BL-2C-RESUME 执行/探索窗口**（生成 Expected / 读取 Legacy Actual / 精确对账 / 产出 Matrix 与 Revision Identity）
> 实施：**NOT AUTHORIZED**（无任何 legacy DB 修复；无 stamp；无 migration 改动）
> 前置：
> - `DB_BL_2C_R2_MIGRATION_CHAIN_REMEDIATION_REPORT.md`（R2 = APPROVED，`MIGRATION_CHAIN_BOOTSTRAP_REMEDIATION = VERIFIED`）
> - `DB_BL_2C_R2_APPROVAL.md`（`DB-BL-2C = AUTHORIZED_TO_RESUME`，`EMPTY→0030` / `EMPTY→0034` 均 `PG_RUNTIME_VERIFIED`）
> - `DB_BL_2C_EXACT_RECONCILIATION.md`（原阻断证据，保留不删，见 §0）
> - `DB_BL_2B_APPROVAL.md`（Schema Authority MODEL A / Bootstrap Contract 冻结）
> Source of Truth：真实 PG runtime 证据 > 冻结文档 > 推测

---

## 0. RESUME AFTER R2（历史证据保留，不删除）

按任务 §28，原 2C 尝试的阻断证据保留如下，不抹除：

```text
Original 2C attempt:
    BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE
    （alembic upgrade 0030/head 在 revision 0025 失败：
     DuplicateColumn ai_edit_job_artifacts.file_size_bytes，停 0016 / 54 表）

R2 Remediation:
    VERIFIED  （0008 移除 file_size_bytes 预声明，恢复 canonical 时间线；
               MR-0~MR-6 全绿；审批窗口独立重跑确认）

R2 审批结论:
    DB-BL-2C = AUTHORIZED_TO_RESUME
    EMPTY → 0030 = PG_RUNTIME_VERIFIED
    EMPTY → 0034 = PG_RUNTIME_VERIFIED
    CURRENT_MIGRATION_CHAIN_CONFORMANCE = PASS
```

> 旧 `PG_RUNTIME_VERIFIED_FAILURE @ 0025` 仍是 R2 修复前的真实 runtime 事实，R2 的修复与重跑使其被 supersede，而非抹除。完整原始阻断证据见 `DB_BL_2C_EXACT_RECONCILIATION.md`。

---

## 1. Environment

### 1.1 Expected@0030（Layer 2 — Historical Reconciliation Anchor Candidate）

| 维度 | 值 |
|---|---|
| host / port | 本机 Docker `127.0.0.1:5433`（disposable 实例 `db-bl-2c-expected-pg`，PG 16） |
| database | `db_bl_2c_resume_e0030`（**本轮新建**，不复用 R2 `db_bl_2c_r2_mr1_0030`，不复用原失败库 `db_bl_2c_expected_0030`） |
| 起始状态 | **EMPTY**（0 表，无 alembic_version） |
| 生成命令 | `DATABASE_URL=postgresql+psycopg://…@127.0.0.1:5433/db_bl_2c_resume_e0030 alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade 0030` → exit 0 |
| 落点 revision | `alembic_version = 0030` |
| 业务表数 | **57**（excl alembic_version；含 alembic_version 共 58，与 R2 MR-4 @0030 吻合） |
| 密码 | 本地 throwaway 口令，运行时注入，未写入脚本/报告 |

### 1.2 Expected@0034（Layer 1 — Canonical Final Target）

| 维度 | 值 |
|---|---|
| host / port | 本机 Docker `127.0.0.1:5433`（同一 disposable 实例，独立 database） |
| database | `db_bl_2c_resume_ehead`（**本轮新建**，不复用 R2 `db_bl_2c_r2_mr2_head`） |
| 起始状态 | **EMPTY**（0 表，无 alembic_version） |
| 生成命令 | `… upgrade head` → exit 0 |
| 落点 revision | `alembic_version = 0034 (head)`，单头 |
| 业务表数 | **60**（excl alembic_version；含 alembic_version 共 61，与 R2 MR-4 @0034 吻合） |

### 1.3 Legacy Actual（READ-ONLY）

| 维度 | 值 |
|---|---|
| host / port | 本机 Docker `127.0.0.1:5432`（`auto-wechat-postgres-dev`，PG 16.14，healthy） |
| database | `auto_wechat`（owner `auto_wechat`，create_all 建成，local development） |
| 只读守卫 | 会话 `SET default_transaction_read_only = on`；全程仅 `SELECT` 系统目录，**零写入** |
| `alembic_version` 表 | **不存在**（legacy 从未经 alembic 管理） |
| 业务表数 | **57** |
| 环境分类 | local development（非 prod / 非 staging / 非 R2 验证库） |

> Environment Gate：Expected 与 legacy 端口明确隔离（5433 vs 5432）、库名明确不同（`db_bl_2c_resume_*` vs `auto_wechat`）、Expected 均空库直跑 bootstrap、非 prod/staging、不覆盖现有业务库。`alembic upgrade` 全程仅指向 5433 disposable，**未对 legacy 5432 执行任何 alembic 操作**。

---

## 2. Expected Bootstrap

```text
Expected@0030（empty → alembic upgrade 0030）:  PASS   (exit 0, alembic_version=0030, 57 业务表)
Expected@0034（empty → alembic upgrade head）:  PASS   (exit 0, alembic_version=0034, 60 业务表)
```

证据等级：**`PG_RUNTIME_VERIFIED`**（本轮独立空 PG 实跑，非复用 R2 库）。

> R2 修复后，0025 `DuplicateColumn` 阻断已消失；两条 bootstrap 路径均真实成功。与 R2 审批窗口独立重跑结果精确吻合（0030=58 表含 alembic / 0034=61 表含 alembic），无 `MIGRATION_CHAIN_BOOTSTRAP_REGRESSION`。

---

## 3. Snapshot / Normalization Method

### 3.1 工具

新增只读 helper：`scripts/db_bl_2c_resume_snapshot.py`（任务 §21 授权）。
- 默认无写能力：仅 `SELECT` pg_catalog；`--readonly` 时会话强制 `default_transaction_read_only=on`。
- 不含生产凭据：DSN 调用方传入，密码走 `PGPASSWORD` 环境变量。
- 三库**同一套** inspection 逻辑（任务 §7）：Expected 与 Actual 均来自 PostgreSQL system catalog，非 Alembic metadata / 非 ORM。禁止用 ORM metadata 当 target（§6/§18 禁止倒推）。
- diff 可重复：快照所有键排序输出，diff 确定性（已做"同库二次快照 diff=0"确定性自检，通过）。
- 含无依赖自检 `selfcheck`：验证 diff 分类逻辑（name-only / semantic 各按预期），通过。

### 3.2 数据来源（全部 pg_catalog）

| 维度 | catalog 来源 | 归一化 |
|---|---|---|
| 表 | `pg_class`(relkind='r', public) excl alembic_version | — |
| 列 | `pg_attribute` + `format_type` + `pg_get_expr(adbin)` | 见下 |
| 列注释 | `col_description` | 原文 |
| PK / FK / unique / CHECK | `pg_constraint` + `pg_get_constraintdef(oid,true)` | `pg_get_constraintdef` 已 pretty normalized |
| FK ondelete/onupdate | `confdeltype`/`confupdtype` | 码表 → `NO ACTION`/`RESTRICT`/`CASCADE`/`SET NULL`/`SET DEFAULT` |
| 索引（standalone） | `pg_index` + `pg_get_indexdef` + `pg_am` | 排除 backing constraint 索引（避免与 PK/unique 重复计） |

### 3.3 Normalization 规则（可审计，保守，不为消除 diff 而掩盖）

- column default：`pg_get_expr` 原始输出 + 归一化键。归一规则：
  - `None` → `<no_default>`
  - `now()` / `CURRENT_TIMESTAMP` / `current_timestamp` → `<timestamp_now>`（语义等价，文本不同 → 记 `NORMALIZATION_ONLY`）
  - `nextval('seq'::regclass)` → `<nextval>`（序列名与表绑定，序列名差异 → `NAME_ONLY_DIFF`）
  - 其余保留 `pg_get_expr` 原始（已含 PG canonical cast）。
- 类型：`format_type(a.atttypid, atttypmod)`（PG canonical：`bigint`/`character varying(255)`/`timestamp with time zone`/`jsonb` 等）。
- 约束/索引定义：直接用 `pg_get_constraintdef` / `pg_get_indexdef`（PostgreSQL 自身归一化，不做二次宽松归一）。

### 3.4 diff 分类（任务 §9）

- `SEMANTIC_DIFF`：缺/多对象、类型/nullable/default/identity/comment 不同、PK 列不同、FK target/ondelete 不同、unique 列不同、check 表达式不同、索引列/method/unique/predicate 不同。
- `NAME_ONLY_DIFF`：约束/索引名不同但语义键匹配（create_all 自动命名 `ix_*`/`*_key` vs alembic 显式 `idx_*`/`uk_*`/`fk_*`）。
- `NORMALIZATION_ONLY`：归一化后语义一致（如 `now()` vs `CURRENT_TIMESTAMP`）。

### 3.5 已知限制

- 列注释维度：`comment_diff` 列入 `SEMANTIC_DIFF`（任务 §8 将 comment 列为可比维度）。注释不影响数据完整性/查询行为，但属真实 schema catalog 差异；本报告在 §4 单列其方向，供审批窗口与 2D 区分"结构 drift"与"文档 drift"。
- 序列名归一：`<nextval>` 归一后序列名差异归 `NAME_ONLY`，不掩盖真实 default 存在性。
- 不覆盖 `op.execute(raw SQL)` 引入的对象：本轮为 runtime PG snapshot，已覆盖所有实际落地对象，无此盲区。

---

## 4. Matrix A — Legacy Actual vs Expected@0030（本阶段最关键输出）

```text
left  = legacy_actual（5432 / auto_wechat / create_all 快照）
right = expected_0030  （5433 / db_bl_2c_resume_e0030 / alembic upgrade 0030）
```

### 4.1 计数

```text
semantic           = 1205
name_only          = 9
normalization_only = 0
```

### 4.2 Semantic 分类构成

| 类别 | 数量 | 方向说明 |
|---|---|---|
| `comment_diff` | 576 | 574 项 legacy 有注释 / expected 空（ORM `comment=` 注入，alembic ≤0030 链未设）；2 项反向 |
| `type_diff` | 238 | 典型：legacy `integer`↔expected `bigint`；legacy `text`↔expected `jsonb`；legacy `timestamp without time zone`↔expected `timestamp with time zone` |
| `default_diff` | 178 | 典型：legacy 无 default ↔expected `now()`/`false`（归一化后仍不同，真实缺 server default） |
| `nullable_diff` | 93 | 典型：legacy 列 NULLABLE ↔ expected NOT NULL（如 `*_created_at`/`updated_at`） |
| `extra_index` | 65 | expected 有、legacy 无的索引（alembic 显式 create_index，create_all 未建） |
| `missing_index` | 16 | legacy 有、expected 无的索引（create_all 自动建，alembic 未定义；多为 `ix_*`） |
| `extra_check` | 13 | expected 有、legacy 无的 CHECK 约束 |
| `extra_column` | 9 | expected 有、legacy 无的列（见 §4.3） |
| `index_def_diff` | 5 | 同语义键但定义文本不同 |
| `extra_unique` | 4 | expected 有、legacy 无的 unique 约束 |
| `extra_fk` | 3 | expected 有、legacy 无的 FK |
| `missing_check` | 2 | legacy 有、expected 无的 CHECK |
| `extra_pk` | 1 | expected 有、legacy 无的 PK |
| `missing_unique` | 1 | legacy 有、expected 无的 unique |
| `missing_fk` | 1 | legacy 有、expected 无的 FK |

### 4.3 表名集合：完全一致

```text
legacy 业务表 = 57，expected_0030 业务表 = 57
set(legacy) == set(expected_0030) : True
only in legacy   : []
only in expected  : []
```

→ **drift 全部在列属性 / 索引 / 约束层，无表级缺失/多余。** Legacy 与 Expected@0030 拥有完全相同的 57 张业务表名，但表内列的类型/默认/可空/注释与索引/约束存在系统性差异。

### 4.4 缺失列（expected 有、legacy 无；9 项含 1 簿记）

| 缺失列 | 归属 |
|---|---|
| `alembic_version.version_num` | **预期内簿记差异**（legacy 从无 alembic_version 表，非业务 drift） |
| `douyin_leads.tenant_id` | 业务 drift（alembic 引入，ORM/create_all 未建） |
| `wechat_tasks.tenant_id` | 业务 drift |
| `wechat_tasks.merchant_id` | 业务 drift |
| `sales_staff.tenant_id` | 业务 drift |
| `sales_staff.sort_order` | 业务 drift |
| `sales_staff.remark` | 业务 drift |
| `knowledge_categories.key` | 业务 drift |
| `knowledge_categories.description` | 业务 drift |

→ 排除 alembic_version 簿记后，**真实业务缺失列 = 8**（典型为 tenant_id/merchant_id 多租户列 + sales_staff/knowledge_categories 辅助列，与 2A "ORM 与链列级未对账"一致）。

### 4.5 type_diff 抽样（真实结构差异，非工具误报）

```
ad_review_adopt_tasks.id              : legacy=integer            expected=bigint
ad_review_adopt_tasks.request_body_json: legacy=text              expected=jsonb
ad_review_adopt_tasks.created_at       : legacy=timestamp without time zone  expected=timestamp with time zone
```

> 类型 drift 与项目历史反复根因吻合（PG jsonb 列 ORM 漏用导致生产 500；PG timezone=True 列与 naive datetime 相减 TypeError）。属真实可观测的结构差异。

### 4.6 NAME_ONLY（9 项，语义匹配，仅命名约定不同）

```text
fk_name_diff        1  （wechat_tasks.report_delivery_id FK：legacy 自动名 _fkey vs alembic fk_ 前缀）
unique_name_diff    3  （ai_auto_reply_runs/check_configs/douyin_private_message_sends 的 unique 约束名）
index_name_diff     5  （douyin_private_message_sends/knowledge_categories 索引名）
```

→ 命名差异方向统一为：legacy(create_all) 使用 SQLAlchemy 自动命名（`ix_*`/`*_key`/`*_fkey`），alembic 使用显式前缀命名（`idx_*`/`uk_*`/`fk_*`）。语义键全部匹配，符合 `NAME_ONLY_DIFF` 定义。

### 4.7 索引 drift 性质

- 65 `extra_index`（alembic 定义、create_all 未建）+ 16 `missing_index`（create_all 自动建、alembic 未定义）。
- `missing_index` 抽样：多为 `douyin_webhook_events`/`douyin_leads` 上的 `ix_*` 单列索引（create_all 自动建），alembic 链未显式 create。
- 这是 2A 已冻结结论的 runtime 印证：**legacy 约束/索引计数反而少于 expected**（legacy 439 约束/172 索引 vs expected 551/225 含 backing），create_all 快照遗漏了 migration 显式定义的部分约束/索引。

完整 Matrix A 明细见 `db_bl_2c_resume_evidence/matrix_a.txt`。

---

## 5. Revision Identity Verdict

```text
LEGACY_DEV_PG_REVISION_IDENTITY:
NOT_EQUIVALENT_TO_0030
```

判定理由（严格身份判断，非相似度）：

1. **表名集合等价**：legacy 与 Expected@0030 拥有完全相同的 57 张业务表名（0 表级缺失/多余）。
2. **但列/属性/索引/约束全面不等价**：1205 项 semantic diff，覆盖 8 真实业务缺失列、238 类型 diff、178 default diff、93 nullable diff、576 注释 diff、81 索引 diff（65 缺 + 16 多）、15 CHECK diff、5 unique diff、4 FK diff、1 PK diff。
3. 任务 §12 明确：**即使 1 项 semantic diff 也不得写 `EXACT_EQUIVALENT_TO_0030`**。本阶段 1205 项，结论无歧义。
4. drift 性质印证 2A/2B 预测：legacy 为 create_all 快照，与 alembic canonical 链在**列类型/默认/可空/注释/索引/约束**层系统性漂移（ORM 与链是两个独立维护源，列级/约束级从未对账）。典型：`integer`↔`bigint`、`text`↔`jsonb`、`timestamp without tz`↔`with tz`、缺 `now()`/`false` server default。
5. 未使用倒推（§18）：独立生成 Expected@0030 → 独立只读采集 Legacy Actual → 比较 → 判定。未因"表数 57 == 0030-era 表数 57"就推断 legacy == 0030。

> 不使用：基本等价 / 大致 0030 / 看起来一样 / 接近 0030（任务 §4 禁用表述）。

---

## 6. Matrix B — Expected@0030 vs Expected@0034（Legitimate Alembic Delta）

```text
left  = expected_0030
right = expected_0034 (head)
```

```text
semantic           = 30
name_only          = 0
normalization_only = 0
```

### 6.1 Delta 全部 30 项归属

| owner | delta |
|---|---|
| **0032** | 新表 `daily_report_generations`（4 列：id/created_at/job_id/lifecycle_status）+ `daily_report_jobs.current_generation_id` 列 + PK(`daily_report_generations.id`) + FK(`daily_report_generations.job_id → daily_report_jobs.id`) + CHECK(`lifecycle_status ∈ pending/running/succeeded/failed`) + index(`daily_report_generations.job_id`) |
| **0033** | 新表 `ai_edit_material_analysis_executions`（6 列：id/material_id/source_sha256/lifecycle_status/created_at/completed_at）+ PK + CHECK(`lifecycle_status ∈ running/completed/failed`) + index(`material_id`) |
| **0034** | 新表 `ai_preview_executions`（6 列：id/merchant_id/agent_id/lifecycle_status/created_at/completed_at）+ PK + CHECK(`lifecycle_status ∈ running/completed/failed`) + index(`merchant_id`) |

构成：3 `extra_table` + 17 `extra_column` + 3 `extra_pk` + 1 `extra_fk` + 3 `extra_check` + 3 `extra_index` = 30。

### 6.2 增量方向

```text
0030 → 0034: +3 表 / +17 列 / +6 索引 / +1 FK / +3 CHECK / +3 PK  （仅增加，无减少）
```

与 R2 MR-4 @0030(57表/915列/225索引/20FK) → @0034(60表/932列/231索引/21FK) 增量方向一致（+3表/+17列/+6索引/+1FK）。

> Matrix B 完全来自真实 Expected PG schema difference，非从 migration 文件摘要复制（任务 §13）。每项 delta 均可归属到 0032/0033/0034 的 `create_table` object。完整明细见 `db_bl_2c_resume_evidence/matrix_b.txt`。

---

## 7. Matrix C — Legacy Actual vs Expected@0034（Final Repair Gap）

```text
left  = legacy_actual
right = expected_0034
```

```text
semantic           = 1235   (= Matrix A 1205 + Matrix B 30，A∪B 并集，无重叠)
name_only          = 9      (= Matrix A 9，B 无 name_only)
normalization_only = 0
```

### 7.1 构成（A ∪ B）

| 类别 | C 计数 | 来源 |
|---|---|---|
| comment_diff | 576 | A |
| type_diff | 238 | A |
| default_diff | 178 | A |
| nullable_diff | 93 | A |
| extra_index | 68 | A(65)+B(3) |
| extra_column | 26 | A(9)+B(17) |
| missing_index | 16 | A |
| extra_check | 16 | A(13)+B(3) |
| index_def_diff | 5 | A |
| extra_unique | 4 | A |
| extra_pk | 4 | A(1)+B(3) |
| extra_fk | 4 | A(3)+B(1) |
| extra_table | 3 | B（0032/0033/0034 三张新表，legacy 缺失） |
| missing_check | 2 | A |
| missing_unique | 1 | A |
| missing_fk | 1 | A |

### 7.2 Final Gap 概要

legacy dev PG 距离合法 head 0034：

- **缺 3 张表**（`daily_report_generations` / `ai_edit_material_analysis_executions` / `ai_preview_executions`，0032/0033/0034 引入）。
- **缺 17 列**（上述 3 表全部列 + `daily_report_jobs.current_generation_id`）。
- **缺对应 PK/FK/CHECK/INDEX**（见 §6）。
- **同 57 张存量表内系统性列级/约束级 drift**（1205 项 A 类差异）：类型/默认/可空/注释/索引/约束全面漂移。

> 完整明细见 `db_bl_2c_resume_evidence/matrix_c.txt`。本阶段**仅说明 gap，不决定如何修**（任务 §15）。

---

## 8. Stamp Eligibility

```text
STAMP_0030: REJECTED_AS_REPAIR_CANDIDATE
```

依据（任务 §17）：

- Matrix A = `NOT_EQUIVALENT_TO_0030`（§5，1205 项 semantic diff）。
- → `REJECTED_AS_REPAIR_CANDIDATE`：未来 DB-BL-2D **不得**选择 `stamp 0030 → upgrade 0032/0033/0034` 作为直接方案。
- 本阶段**未对 legacy DB 执行任何 `alembic stamp`，未创建/修改 legacy `alembic_version`**（§27 严格只读）。

---

## 9. Legacy Data Disposability

```text
DISPOSABLE
READ_ONLY_PG_VERIFIED   — UNCHANGED（继承 R2 审批冻结状态）
```

- 无新反证使该判断失效。legacy dev PG 仍 `DISPOSABLE`（全库 5 行、无 PII，见原 2C 报告 §11）。
- `DISPOSABLE != authorized to rebuild`。本阶段 legacy 继续严格只读，未删除、未重建、未 stamp。
- 只读证据：本轮 legacy 连接 `default_transaction_read_only=on`，全程仅 SELECT。

---

## 10. Evidence Levels

| 事实 | 证据等级 |
|---|---|
| Expected@0030 bootstrap PASS（empty → 0030） | `PG_RUNTIME_VERIFIED` |
| Expected@0034 bootstrap PASS（empty → head/0034） | `PG_RUNTIME_VERIFIED` |
| Legacy 57 表 / 无 alembic_version / 906 列 / 18 FK | `READ_ONLY_PG_VERIFIED` |
| Legacy 表名集合 == Expected@0030 表名集合（57==57，同名） | `READ_ONLY_PG_VERIFIED` |
| Matrix A 1205 semantic diff（类型/默认/可空/注释/索引/约束/列） | `READ_ONLY_PG_VERIFIED`（runtime catalog 对账，确定性自检通过） |
| Matrix B 30 delta 归属 0032/0033/0034 | `PG_RUNTIME_VERIFIED`（Expected@0030 vs Expected@0034 真实 PG diff） |
| Matrix C 1235 = A∪B 并集 | `READ_ONLY_PG_VERIFIED` |
| Revision Identity = NOT_EQUIVALENT_TO_0030 | `READ_ONLY_PG_VERIFIED` |
| Name-only 9（命名约定差异，语义匹配） | `READ_ONLY_PG_VERIFIED` |
| Legacy 数据可处置性 = DISPOSABLE | `READ_ONLY_PG_VERIFIED`（UNCHANGED） |
| Expected 对象计数（915/932 列、20/21 FK） | `PG_RUNTIME_VERIFIED`（与 R2 审批窗口独立重跑精确吻合） |

---

## 11. DB-BL-2D Inputs

**仅列事实输入，不选择 repair strategy**（任务 §11/§27，本阶段无授权）：

| 输入 | 值 |
|---|---|
| Revision identity | `NOT_EQUIVALENT_TO_0030` |
| Matrix A（Actual vs 0030） | 1205 semantic / 9 name_only / 0 normalization_only（明细 `matrix_a.txt`） |
| Matrix B（0030 vs 0034） | 30 semantic（0032/0033/0034 合法 delta，明细 `matrix_b.txt`） |
| Matrix C（Actual vs 0034） | 1235 semantic / 9 name_only（A∪B 并集，明细 `matrix_c.txt`） |
| Stamp eligibility | `REJECTED_AS_REPAIR_CANDIDATE`（不得 stamp 0030 → upgrade） |
| Data disposability | `DISPOSABLE`（`READ_ONLY_PG_VERIFIED`，全库 5 行、无 PII，UNCHANGED） |
| 表名集合 | legacy 与 0030 完全一致（57 同名），drift 全在列/约束/索引层 |
| 主要 drift 类别 | 类型(238) / 默认(178) / 可空(93) / 注释(576) / 索引(81) / 约束(26) / 缺列(8 业务) |

---

## 12. DB-BL-2C Completion Verdict

三张 Matrix（A/B/C）与 Revision Identity 均已完成：

```text
DB-BL-2C:
EXACT_RECONCILIATION_COMPLETE_PENDING_APPROVAL
```

- Expected@0030 / Expected@0034 均已通过 runtime bootstrap 取得（`PG_RUNTIME_VERIFIED`），不复用 R2 库。
- Legacy Actual 只读采集完成（`READ_ONLY_PG_VERIFIED`）。
- 三张 Matrix 用同一套 catalog inspection 逻辑生成，确定性自检通过。
- Revision Identity 明确判定：`NOT_EQUIVALENT_TO_0030`。
- Stamp Eligibility 明确判定：`REJECTED_AS_REPAIR_CANDIDATE`。

---

## 13. Implementation Status

```text
LEGACY DB MODIFICATION:        NOT STARTED
LEGACY DB REPAIR:               NOT AUTHORIZED
LEGACY DB STAMP / UPGRADE:      NOT STARTED  (本阶段零写入)
MIGRATION CHAIN MODIFICATION:   NOT STARTED / NOT AUTHORIZED（R2 已 APPROVED，本阶段不再审查）
DB-BL-2D:                       NOT AUTHORIZED
```

本阶段已完成（只读 + disposable 受控 bootstrap）：

- ✅ Expected@0030 / Expected@0034 独立空 PG bootstrap（本轮新建 disposable 库，不复用 R2 库）
- ✅ Legacy Actual 只读 schema 采集（`default_transaction_read_only=on`）
- ✅ 同一套 catalog snapshot/normalization helper（`scripts/db_bl_2c_resume_snapshot.py`，只读，含自检）
- ✅ Matrix A / B / C 三张矩阵生成与分类
- ✅ Revision Identity Verdict（`NOT_EQUIVALENT_TO_0030`）
- ✅ Stamp Eligibility（`REJECTED_AS_REPAIR_CANDIDATE`）
- ✅ 确定性自检（同库二次快照 diff=0）+ diff 分类自检（`selfcheck` PASS）

本阶段未执行、且禁止执行（任务 §27）：

- ❌ `alembic stamp`（任何 revision，legacy / disposable / prod / staging）
- ❌ 创建/修改 legacy `alembic_version`
- ❌ legacy upgrade / downgrade / repair / rebuild / 删除
- ❌ 修改任何 migration 文件 / ORM / init_db.py / P1 Consumer / M07 Core
- ❌ 自行进入 DB-BL-2D 或选择 repair strategy
- ❌ production / staging 操作

---

## 附：证据文件索引

| 证据 | 路径 |
|---|---|
| snapshot Expected@0030 | `docs/architecture/remediation/db_bl_2c_resume_evidence/expected_0030.json` |
| snapshot Expected@0034 | `docs/architecture/remediation/db_bl_2c_resume_evidence/expected_0034.json` |
| snapshot Legacy Actual | `docs/architecture/remediation/db_bl_2c_resume_evidence/legacy_actual.json` |
| Matrix A 明细 | `docs/architecture/remediation/db_bl_2c_resume_evidence/matrix_a.txt` |
| Matrix B 明细 | `docs/architecture/remediation/db_bl_2c_resume_evidence/matrix_b.txt` |
| Matrix C 明细 | `docs/architecture/remediation/db_bl_2c_resume_evidence/matrix_c.txt` |
| snapshot/diff helper | `scripts/db_bl_2c_resume_snapshot.py` |
| 原始阻断证据（保留） | `docs/architecture/remediation/DB_BL_2C_EXACT_RECONCILIATION.md` |
| R2 修复报告 | `docs/architecture/remediation/DB_BL_2C_R2_MIGRATION_CHAIN_REMEDIATION_REPORT.md` |
| R2 审批 | `docs/architecture/remediation/DB_BL_2C_R2_APPROVAL.md` |

---

## 本阶段核心治理原则印证

> **Migration chain 已被证明可以制造合法数据库，本次用它证明了 Legacy Database Revision Identity。**

```text
先证明 Database Revision Identity → NOT_EQUIVALENT_TO_0030
再允许 Baseline Repair → 由 DB-BL-2D 独立设计（当前 NOT AUTHORIZED）
```

DB-BL-2C-RESUME 执行窗口到此停止，提交独立审批窗口复核。不 stamp、不 upgrade、不 rebuild、不 repair、不自行进入 DB-BL-2D。
