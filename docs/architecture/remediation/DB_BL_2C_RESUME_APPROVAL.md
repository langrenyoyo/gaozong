# DB-BL-2C-RESUME — PostgreSQL Exact Reconciliation 审批报告

> 阶段：DB-BL-2C-RESUME **Approval Window**
> 日期：2026-08-10
> 审批窗口：DB-BL-2C-RESUME PostgreSQL Exact Reconciliation 审批窗口
> 审查对象：报告 `DB_BL_2C_EXACT_RECONCILIATION_RESUME.md` + 证据目录 `db_bl_2c_resume_evidence/` + 工具 `scripts/db_bl_2c_resume_snapshot.py`
> 审查范围：只读独立核验——Expected runtime 证据 / table-count 口径 / 快照工具只读与确定性 / normalization contract / Matrix A·B·C / Revision Identity / Stamp Eligibility / 集合一致性 / name-only / disposability
> 前置冻结：2C 原 `DB_BL_2C_EXACT_RECONCILIATION.md`（BLOCKED 证据保留）、R2 `DB_BL_2C_R2_MIGRATION_CHAIN_REMEDIATION_REPORT.md` + `DB_BL_2C_R2_APPROVAL.md`（`AUTHORIZED_TO_RESUME`，`MIGRATION_CHAIN_BOOTSTRAP_REMEDIATION = VERIFIED`）、2B `DB_BL_2B_APPROVAL.md`（Schema Authority MODEL A）。
> 工作原则：独立核验 → 不采信报告自述 → 对冻结 JSON 证据用工具纯函数独立复算三张 Matrix → 逐分类核对 → 仅判定 2C Completion 与 2D Authorization，不 stamp、不 upgrade、不 rebuild、不 repair、不自行进入 2D。

---

## 1. Technical Decision

```
DB-BL-2C-RESUME:
APPROVED_WITH_CORRECTIONS
```

核心身份判定 `NOT_EQUIVALENT_TO_0030` 成立，三张 Matrix 与集合一致性经独立复算精确吻合，Stamp Eligibility 与 Disposability 成立，DB-BL-2C 可正式 COMPLETE，DB-BL-2D 可授权 DESIGN/AUDIT ONLY。

**修正项（不影响 Revision Identity）**：`comment_diff` 应从 `SEMANTIC_DIFF` 单列为 `METADATA_DIFF`，以提升 Matrix 精度并供 2D 区分"结构 drift"与"文档 drift"。报告 §3.5 已自觉提示此点。排除全部 576 项 comment 后，仍余 **629 项无争议 type/nullable/default/index/constraint/column drift**，远超"至少一项"阈值，`NOT_EQUIVALENT_TO_0030` 独立于 comment 分类成立。

---

## 2. Expected Runtime Evidence（Q1）

审批窗口对三份冻结 snapshot JSON 的头部字段独立核验（直接读取 `current_database` / `alembic_version` / `readonly_guard` / `object_counts`，非采信报告自述）：

| 维度 | Expected@0030 | Expected@0034 | Legacy Actual |
|---|---|---|---|
| `current_database` | `db_bl_2c_resume_e0030` | `db_bl_2c_resume_ehead` | `auto_wechat` |
| `readonly_guard` | `False`（disposable bootstrap target，授权写入） | `False` | **`True`** |
| `has_alembic_version_table` | `True` | `True` | `False` |
| `alembic_version` | `0030` | `0034` | `None` |
| 业务表数 | 57 | 60 | 57 |
| 列数 | 915 | 932 | 906 |
| FK 数 | 20 | 21 | 18 |

结论：

```
Expected@0030 = PG_RUNTIME_VERIFIED
Expected@0034 = PG_RUNTIME_VERIFIED   (revision=0034, head, 单头)
```

- Expected 两个库名（`db_bl_2c_resume_*`）与 R2 库名（`db_bl_2c_r2_*`）明确不同 → **本轮新建，非复用 R2 库**。
- Expected 与 legacy 端口/库名隔离（5433 disposable vs 5432 `auto_wechat`），Expected 均空库直跑 bootstrap，非 prod / 非 staging / 非 legacy / 非 R2 验证库。
- Legacy `readonly_guard=True`、`has_alembic_version_table=False`、`alembic_version=None` → legacy 从未经 alembic 管理，与报告一致。
- Expected `readonly_guard=False` 是正确语义：alembic upgrade 需写 disposable 库，写仅作用于 5433 disposable，**未对 legacy 5432 执行任何 alembic 操作**。

---

## 3. Table Count Convention（Q2）

```
COUNTING_CONVENTION_ONLY  — 非 factual conflict
```

| 库 | 业务表（excl alembic_version） | + alembic_version | total |
|---|---|---|---|
| Expected@0030 | 57 | 1 | 58 |
| Expected@0034 | 60 | 1 | 61 |
| Legacy Actual | 57 | 0（无该表） | 57 |

R2 曾报告 0030=58 表 / 0034=61 表；本轮报告 0030=57 业务表 / 0034=60 业务表。差异 **恰好** 来自 `alembic_version` 系统簿记表。审批窗口确认：

```
Expected@0030: 57 business + 1 alembic_version = 58 total
Expected@0034: 60 business + 1 alembic_version = 61 total
```

不是矛盾。**修正建议**：正式文档统一表述为「业务表数 + 系统簿记表数」双口径，避免未来再次混淆。报告 §1.1/§1.2 已正确双列，仅需在 Matrix 摘要处固化该口径说明。

---

## 4. Snapshot Tool Verdict（Q3）

```
SNAPSHOT_TOOL: READ_ONLY_VERIFIED
```

`scripts/db_bl_2c_resume_snapshot.py` 独立审查结论：

| 审查项 | 结论 | 依据 |
|---|---|---|
| 三库同一套 PostgreSQL catalog inspection | ✅ | 单一 `_snapshot()` + 同一组 `SQL_*` 常量，Expected 与 Actual 共用 |
| Expected 与 Legacy 无不同模型 | ✅ | 均走 pg_catalog，无分支差异 |
| 无 ORM metadata 当 Actual 替代 | ✅ | 全部 `format_type` / `pg_get_expr` / `pg_get_constraintdef(oid,true)` / `pg_get_indexdef` / `pg_am` |
| legacy 连接明确只读 | ✅ | `--readonly` 时会话 `SET default_transaction_read_only=on`；snapshot 头部 `readonly_guard=True` 印证 |
| 无写 SQL | ✅ | 全部语句为 `SELECT`；唯一非 SELECT 是只读守卫 `SET`，其作用是**收紧**写权限 |
| 无自动 repair | ✅ | diff 为纯 JSON 对比函数 `_diff_snapshots`，无 DDL/DML 输出 |
| 无生产凭据 | ✅ | DSN 调用方传入，密码走 `PGPASSWORD`，不写入脚本/文件 |
| 确定性排序 | ✅ | snapshot 所有 dict `sorted()`、SQL `ORDER BY`；独立重跑三张 Matrix 计数**逐项精确复现** |
| selfcheck 覆盖 | ✅ | `_selfcheck()` 验证 name-only / semantic 分类逻辑（序列名差异 → name-only、缺表 → semantic），`selfcheck` PASS |

补充确定性证据：审批窗口用工具纯函数对冻结 JSON 重跑全部三张 Matrix，A=1205/9/0、B=30/0/0、C=1235/9/0 与报告**逐项精确吻合**（见 §4/§6/§7），等价于"同库二次快照 diff=0"的可重复性证明。

---

## 5. Normalization Contract（Q4）

```
NORMALIZATION_CONTRACT: APPROVED
```

Normalization 规则保守、可审计、不掩盖真实 drift，也不过度归一制造假 diff：

| 维度 | 处理 | 评价 |
|---|---|---|
| 类型 canonical | `format_type(atttypid, atttypmod)` → PG canonical（`bigint`/`character varying(255)`/`timestamp with time zone`/`jsonb`） | ✅ PG 自身归一 |
| default 表达式 | `None`→`<no_default>`；`now()`/`CURRENT_TIMESTAMP`/`current_timestamp`→`<timestamp_now>`；`nextval('seq'::regclass)`→`<nextval>`；其余保留 `pg_get_expr` 原始 | ✅ 语义等价形式归一为同一键，文本差异落 `NORMALIZATION_ONLY`；序列名差异落 `NAME_ONLY` |
| 约束定义 | `pg_get_constraintdef(oid, true)`（PG pretty normalized） | ✅ 无二次宽松归一 |
| 索引定义 | `pg_get_indexdef(oid, 0, true)` + `predicate`（`pg_get_expr(indpred)`）+ `method`(`pg_am`) | ✅ predicate 进入语义键 |
| CHECK 表达式 | 以 `table+definition` 为键，`definition` 来自 `pg_get_constraintdef` | ✅ |
| 名称与语义定义分离 | 约束/索引按语义键（table+columns+method+predicate / table+definition）匹配，名称差异单独落 `NAME_ONLY_DIFF` | ✅ |
| whitespace/parentheses | 由 PG `pg_get_*def(..., true)` 统一处理 | ✅ |

**未发现**两类错误：
- ❌ "不同文本一律视为不同" → 未发生：`now()` vs `CURRENT_TIMESTAMP` 已正确落 `NORMALIZATION_ONLY`（本批为 0，说明无此类假阳性）。
- ❌ "过度 normalize 吃掉真实 drift" → 未发生：`default_diff` 抽样核验（§8）显示 `legacy=None / expected=now()` 在归一后仍判为 semantic，真实缺 server default 未被掩盖；`type_diff` 抽样为 `integer↔bigint`/`text↔jsonb`/`timestamp without tz↔with tz` 真实结构差异。

---

## 6. Matrix A Verdict（Q5）

```
left  = legacy_actual  (5432 / auto_wechat / create_all)
right = expected_0030   (5433 / db_bl_2c_resume_e0030 / alembic upgrade 0030)

semantic = 1205   name_only = 9   normalization_only = 0
```

### 6.1 逐分类独立复算（审批窗口用工具纯函数对冻结 JSON 重跑）

| 类别 | 报告 | 独立复算 | 核对 |
|---|---|---|---|
| `comment_diff` | 576 | 576 | ✅ |
| `type_diff` | 238 | 238 | ✅ |
| `default_diff` | 178 | 178 | ✅ |
| `nullable_diff` | 93 | 93 | ✅ |
| `extra_index` | 65 | 65 | ✅ |
| `missing_index` | 16 | 16 | ✅ |
| `extra_check` | 13 | 13 | ✅ |
| `extra_column` | 9 | 9 | ✅ |
| `index_def_diff` | 5 | 5 | ✅ |
| `extra_unique` | 4 | 4 | ✅ |
| `extra_fk` | 3 | 3 | ✅ |
| `missing_check` | 2 | 2 | ✅ |
| `extra_pk` | 1 | 1 | ✅ |
| `missing_unique` | 1 | 1 | ✅ |
| `missing_fk` | 1 | 1 | ✅ |
| **合计** | **1205** | **1205** | ✅ 全部一致 |

### 6.2 表名集合等价

```
legacy 业务表 = 57，expected_0030 业务表 = 57
only in legacy  = []   only in expected = []
set(legacy) == set(expected_0030) : True
```

→ drift 全部在列属性/索引/约束层，无表级缺失/多余。

### 6.3 高价值类别抽样核验

**type_diff（238）** — 真实结构差异，非工具误报：
```
ad_review_adopt_tasks.id               : legacy=integer                              expected=bigint
ad_review_adopt_tasks.request_body_json : legacy=text                                 expected=jsonb
ad_review_adopt_tasks.created_at        : legacy=timestamp without time zone          expected=timestamp with time zone
```
与项目历史反复根因吻合（PG jsonb ORM 漏用致生产 500；PG timezone=True 列与 naive datetime 相减 TypeError）。

**default_diff（178）** — 归一化后仍不同，真实缺 server default：
```
ad_review_adopt_tasks.created_at  : legacy_default=None  expected_default='now()'
ad_review_adopt_tasks.updated_at  : legacy_default=None  expected_default='now()'
ad_review_oauth_accounts.created_at : legacy_default=None  expected_default='now()'
```

**nullable_diff（93）** — 真实 NOT NULL 差异：
```
ad_review_adopt_tasks.created_at  : legacy_notnull=False  expected_notnull=True
ad_review_adopt_tasks.updated_at  : legacy_notnull=False  expected_notnull=True
```

**extra_column（9，含 1 簿记）** — 排除 `alembic_version.version_num` 后真实业务缺失列 = 8：
```
douyin_leads.tenant_id            sales_staff.sort_order
wechat_tasks.tenant_id            sales_staff.remark
wechat_tasks.merchant_id          knowledge_categories.key
sales_staff.tenant_id             knowledge_categories.description
```
均属 alembic 引入、ORM/create_all 未建的多租户列 + 辅助列，与 2A "ORM 与链列级未对账"一致，非工具误识别。

### 6.4 comment_diff 分类修正（APPROVED_WITH_CORRECTIONS 原因）

报告当前将 576 项 `comment_diff` 计入 `SEMANTIC_DIFF`（依据任务 §8 将 comment 列为可比维度）。但 PostgreSQL `COMMENT` 是 catalog metadata，**不影响 schema execution semantics、数据完整性或查询行为**。报告 §3.5 已自觉提示此点。

**修正要求**：将 `comment_diff` 从 `SEMANTIC_DIFF` 单列为 `METADATA_DIFF` 类别，Matrix A 头部语义计数相应调整为「1205 semantic（含 576 metadata）/ 629 结构 semantic（不含 metadata）」。这不改变 `NOT_EQUIVALENT_TO_0030` 判定（见 §7），但提升 Matrix 精度，供 2D 区分"结构 drift"与"文档 drift"。

---

## 7. Revision Identity

### 7.1 最低充分证据

即使审批窗口按 §6.4 将全部 576 项 `comment_diff` 移出 semantic，剩余无争议结构 drift：

```
type_diff(238) + default_diff(178) + nullable_diff(93)
+ extra_index(65) + missing_index(16) + index_def_diff(5)
+ extra_check(13) + missing_check(2)
+ extra_column(8 业务) + extra_unique(4) + missing_unique(1)
+ extra_fk(3) + missing_fk(1) + extra_pk(1)
= 629 项无争议 revision-relevant semantic difference
```

远超任务 §9「至少一项无争议 revision-relevant semantic difference」阈值。**`NOT_EQUIVALENT_TO_0030` 独立于 comment 分类成立。**

### 7.2 Verdict

```
LEGACY_DEV_PG_REVISION_IDENTITY:
NOT_EQUIVALENT_TO_0030
```

判定理由：
1. 表名集合等价（57==57 同名），但列/属性/索引/约束全面不等价。
2. 629 项无争议结构 drift（排除 comment 后），覆盖 8 真实业务缺失列、238 类型、178 default、93 nullable、86 索引、15 CHECK、8 业务列、6 unique、4 FK、1 PK。
3. drift 性质印证 2A/2B 预测：legacy 为 create_all 快照，与 alembic canonical 链在列类型/默认/可空/索引/约束层系统性漂移。
4. 未使用倒推：独立生成 Expected@0030 → 独立只读采集 Legacy Actual → 比较 → 判定，未因"57==57"推断等价。

> 不使用：基本等价 / 大致 0030 / 看起来一样 / 接近 0030（任务 §4 禁用表述）。

---

## 8. Matrix B Verdict（Q6）

```
left  = expected_0030
right = expected_0034 (head)

semantic = 30   name_only = 0   normalization_only = 0
```

### 8.1 逐分类独立复算

| 类别 | 报告 | 独立复算 | 核对 |
|---|---|---|---|
| `extra_table` | 3 | 3 | ✅ |
| `extra_column` | 17 | 17 | ✅ |
| `extra_pk` | 3 | 3 | ✅ |
| `extra_fk` | 1 | 1 | ✅ |
| `extra_check` | 3 | 3 | ✅ |
| `extra_index` | 3 | 3 | ✅ |
| **合计** | **30** | **30** | ✅ |

### 8.2 Delta 归属

| owner | delta 对象 |
|---|---|
| **0032** | 新表 `daily_report_generations`（4 列）+ `daily_report_jobs.current_generation_id` 列 + PK + FK(`job_id→daily_report_jobs.id`) + CHECK(`lifecycle_status`) + index(`job_id`) |
| **0033** | 新表 `ai_edit_material_analysis_executions`（6 列）+ PK + CHECK + index(`material_id`) |
| **0034** | 新表 `ai_preview_executions`（6 列）+ PK + CHECK + index(`merchant_id`) |

- 全部 30 项可归属到 0032/0033/0034 的 `create_table` object，**无未归属 difference**。
- 增量方向纯加法（+3 表 / +17 列 / +6 索引 / +1 FK / +3 CHECK / +3 PK，无减少），与 R2 MR-4 @0030→@0034 增量方向一致。
- 完全来自真实 Expected PG schema difference，非从 migration 文件摘要复制。

```
MATRIX_B: LEGITIMATE_POST_0030_DELTA_VERIFIED
```

---

## 9. Matrix C Verdict（Q7）

```
left  = legacy_actual
right = expected_0034 (head)

semantic = 1235   name_only = 9   normalization_only = 0
```

### 9.1 构成（A ∪ B 并集）

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

### 9.2 集合一致性独立核验

审批窗口以 object identity（category + 定位键）构造语义键集合，独立验证：

```
semantic_keys(C) == semantic_keys(A) ∪ semantic_keys(B)

|A| = 1205   |B| = 30   |A ∪ B| = 1235   |C| = 1235
C - (A ∪ B) 多余 = 0
(A ∪ B) - C 缺失 = 0
C == A ∪ B : True
```

Matrix B 的 30 项全部为 legacy 缺少的合法 post-0030 delta，**未与 Matrix A 的 drift 抵消或重叠**。整个 reconciliation 模型自洽。

```
MATRIX_SET_CONSISTENCY: VERIFIED
```

---

## 10. Name-only Differences（Q8）

9 项 `NAME_ONLY_DIFF` 全部独立列出核验，均为约束/索引名不同但语义键匹配（columns/type/target/predicate/uniqueness/FK action 一致）：

| # | 类别 | 对象 | legacy 名（create_all 自动） | expected 名（alembic 显式） |
|---|---|---|---|---|
| 1 | fk_name_diff | `wechat_tasks.report_delivery_id → daily_report_deliveries.id` | `wechat_tasks_report_delivery_id_fkey` | `fk_wechat_tasks_report_delivery_id` |
| 2 | unique_name_diff | `ai_auto_reply_runs(trigger_event_key)` | `ai_auto_reply_runs_trigger_event_key_key` | `uk_ai_auto_reply_runs_trigger_event_key` |
| 3 | unique_name_diff | `check_configs(config_key)` | `check_configs_config_key_key` | `uk_check_configs_config_key` |
| 4 | unique_name_diff | `douyin_private_message_sends(auto_reply_run_id)` | `douyin_private_message_sends_auto_reply_run_id_key` | `uk_douyin_private_message_sends_auto_reply_run` |
| 5 | index_name_diff | `douyin_private_message_sends(conversation_short_id)` | `ix_douyin_private_message_sends_conversation_short_id` | `idx_douyin_private_message_sends_conversation` |
| 6 | index_name_diff | `douyin_private_message_sends(decision_log_id)` | `ix_douyin_private_message_sends_decision_log_id` | `idx_douyin_private_message_sends_decision_log` |
| 7 | index_name_diff | `douyin_private_message_sends(send_source)` | `ix_douyin_private_message_sends_send_source` | `idx_douyin_private_message_sends_send_source` |
| 8 | index_name_diff | `douyin_private_message_sends(server_message_id)` | `ix_douyin_private_message_sends_server_message_id` | `idx_douyin_private_message_sends_server_message` |
| 9 | index_name_diff | `knowledge_categories(merchant_id,category_key,status)` | `idx_knowledge_categories_merchant_key_status` | `idx_knowledge_categories_merchant_category_status` |

→ 命名差异方向统一：legacy(create_all) 用 SQLAlchemy 自动命名（`ix_*`/`*_key`/`*_fkey`），alembic 用显式前缀（`idx_*`/`uk_*`/`fk_*`）。语义键全部匹配，符合 `NAME_ONLY_DIFF` 定义，**不计入 revision identity semantic failure**。保留供未来治理参考。

---

## 11. Legacy Data Disposability（Q9）

```
DISPOSABLE
READ_ONLY_PG_VERIFIED — UNCHANGED（继承 R2 审批冻结状态）
```

- 无新反证使该判断失效。legacy dev PG 仍 `DISPOSABLE`（全库 5 行、无 PII，见原 2C 报告 §11）。
- 本轮 legacy 连接 `readonly_guard=True`，全程仅 SELECT，未重复读取 PII。
- `DISPOSABLE != authorized to rebuild`。本审批不授权 rebuild，仅作为 2D repair strategy 比较的有力候选输入。

---

## 12. Stamp Eligibility

```
STAMP_0030: REJECTED_AS_REPAIR_CANDIDATE
```

依据：
- Matrix A = `NOT_EQUIVALENT_TO_0030`（§7，629 项无争议结构 drift）。
- Database Revision Identity 前提不成立 → 未来 DB-BL-2D **不得**选择 `stamp 0030 → upgrade 0032/0033/0034` 作为直接合法方案。
- 不得以后重新因 `57 tables == 57 tables` 把 stamp 路线带回。
- 本审批窗口未对 legacy DB 执行任何 `alembic stamp`，未创建/修改 legacy `alembic_version`（legacy snapshot 头部 `has_alembic_version_table=False`、`alembic_version=None` 印证）。

> Reject stamp ≠ 决定 rebuild。本审批仅排除直接 stamp-to-0030 路径，不因此批准 rebuild。rebuild / targeted reconciliation / 其他有证据方案的比较由 DB-BL-2D 设计决定。

---

## 13. DB-BL-2C Final Status

全部 Completion Gate 成立：

```
Expected@0030          = PG_RUNTIME_VERIFIED          ✅
Expected@0034          = PG_RUNTIME_VERIFIED          ✅
Matrix A               = VERIFIED（1205/9/0，15 分类逐项复算一致）  ✅
Matrix B               = VERIFIED（30/0/0，合法 0032/0033/0034 delta） ✅
Matrix C               = VERIFIED（1235/9/0，完整 head gap）  ✅
Matrix Set Consistency = VERIFIED（C == A ∪ B，0 多余 0 缺失）  ✅
Revision Identity      = VERIFIED（NOT_EQUIVALENT_TO_0030）  ✅
Stamp Eligibility      = VERIFIED（REJECTED_AS_REPAIR_CANDIDATE）  ✅
Snapshot Tool          = READ_ONLY_VERIFIED           ✅
Normalization Contract = APPROVED                    ✅
```

```
DB-BL-2C:
EXACT_RECONCILIATION_VERIFIED
```

原 `BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` 作为历史状态保留（R2 已解除其阻断，本轮以 runtime 证据完成精确对账）。

---

## 14. DB-BL-2D Authorization

```
DB-BL-2D: AUTHORIZED — DESIGN / AUDIT ONLY
```

DB-BL-2C 审批完成（`EXACT_RECONCILIATION_VERIFIED`），授权 DB-BL-2D Legacy PostgreSQL Baseline Repair Strategy 进入**设计/审计**阶段。2D 才回答：当前 legacy PG 应 rebuild、targeted reconcile，还是采用其他合法策略。

### 2D 冻结输入（Source of Truth）

| 输入 | 值 |
|---|---|
| Revision Identity | `NOT_EQUIVALENT_TO_0030` |
| Stamp Eligibility | `REJECTED_AS_REPAIR_CANDIDATE`（不得 stamp 0030 → upgrade） |
| Legacy Data | `DISPOSABLE`（`READ_ONLY_PG_VERIFIED`，全库 5 行、无 PII，UNCHANGED） |
| Canonical Final Target | `Expected@0034`（head，PG_RUNTIME_VERIFIED） |
| Migration Chain | `PG_RUNTIME_VERIFIED / CONFORMANT`（EMPTY→0030、EMPTY→0034 均 PASS） |
| Matrix A | legacy drift against 0030（1205 semantic，含 576 comment→METADATA、629 结构；9 name-only；明细 `matrix_a.txt`） |
| Matrix B | legitimate 0030→0034 delta（30 semantic，归属 0032/0033/0034；明细 `matrix_b.txt`） |
| Matrix C | full legacy→0034 gap（1235 semantic，A∪B；明细 `matrix_c.txt`） |
| 表名集合 | legacy 与 0030 完全一致（57 同名），drift 全在列/约束/索引层 |
| 主要结构 drift | 类型(238) / 默认(178) / 可空(93) / 索引(86) / 约束(26) / 缺列(8 业务) |

---

## 15. Explicitly Forbidden

即使 DB-BL-2D 设计获授权，本审批窗口及 2D 设计阶段仍禁止：

- ❌ `alembic stamp`（任何 revision，legacy / disposable / prod / staging）
- ❌ 创建/修改 legacy `alembic_version`
- ❌ legacy upgrade / downgrade / repair / rebuild / 删除
- ❌ 修改任何 migration 文件 / ORM / init_db.py / P1 Consumer / M07 Core
- ❌ production / staging 操作
- ❌ 跳过 2D 设计直接实施 repair

---

## 16. 修正项跟踪（APPROVED_WITH_CORRECTIONS）

| # | 修正项 | 影响范围 | 是否影响 Revision Identity | 责任 |
|---|---|---|---|---|
| C1 | `comment_diff`(576) 从 `SEMANTIC_DIFF` 单列为 `METADATA_DIFF`；Matrix A 头部分列「结构 semantic 629 / metadata 576」 | 报告 §4.2 / §5 / 证据 matrix_a.txt | 否（629 项结构 drift 仍判 NOT_EQUIVALENT） | 执行窗口文档更新 |
| C2 | 正式文档固化「业务表数 + 系统簿记表数」双口径表述 | 报告 §1.1/§1.2 已双列，仅需 Matrix 摘要固化 | 否 | 执行窗口文档更新 |

> 两条修正均为文档精度修正，不影响 Revision Identity、Stamp Eligibility、Matrix 集合一致性或 2D 授权结论。修正完成后 DB-BL-2C 即为 `COMPLETE`（当前实质已 `EXACT_RECONCILIATION_VERIFIED`）。

---

## 审批窗口声明

本审批窗口已完成独立核验：对冻结 JSON 证据用工具纯函数重跑三张 Matrix、逐分类核对、集合一致性验证、高价值抽样、只读边界与 normalization 审查。核心身份判定 `NOT_EQUIVALENT_TO_0030` 与 `REJECTED_AS_REPAIR_CANDIDATE` 成立，DB-BL-2C = `EXACT_RECONCILIATION_VERIFIED`，DB-BL-2D = `AUTHORIZED — DESIGN/AUDIT ONLY`。

审批窗口到此停止。不 stamp、不 upgrade、不 rebuild、不 repair、不自行进入 DB-BL-2D。
