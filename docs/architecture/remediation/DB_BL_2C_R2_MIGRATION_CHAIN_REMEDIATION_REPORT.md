# DB-BL-2C-R2 — Migration Chain Bootstrap Remediation 实施报告

> 阶段：DB-BL-2C-R2 Migration Chain Bootstrap Remediation **Implementation / Verification**
> 日期：2026-08-10
> 模式：**EXECUTION** — 已获 `DB-BL-2C-R2 = AUTHORIZED — MIGRATION CHAIN ONLY`，实施冻结的 Strategy A。
> 前置：`DB_BL_2C_R1_MIGRATION_CHAIN_REMEDIATION_DESIGN.md`（Strategy A 设计）、`DB_BL_2C_R1_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，授权 R2）、`DB_BL_2C_APPROVAL.md`（2C `BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE`）。
> 工作原则：实施前置 doc-sync → 最小修改 → MR-0~MR-6 全绿验证 → 仅宣布 Resume Eligibility，不进 2C/2D。

---

## 1. Scope

实际修改：**1 个文件、删 1 行、加 4 行中文注释**。

| 文件 | 改动 |
|---|---|
| `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py` | `create_table("ai_edit_job_artifacts", ...)` 内移除 `sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)`（原第 340 行），替换为说明性注释 |

diff 摘要：

```diff
-        sa.Column("mime_type", sa.String(length=64), nullable=True),
-        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
-        _created_at_column(),
+        sa.Column("mime_type", sa.String(length=64), nullable=True),
+        # file_size_bytes 不在此预声明：该列由 0025_ai_edit_result_delivery 正典引入
+        # （ORM 字段 + add_column + 结果交付功能同提交 231808d5 抵达，GIT_HISTORY_VERIFIED）。
+        # 0008 此处曾为 authoring-time forward declaration（PREDECLARED_FUTURE_SCHEMA），
+        # 导致空库自举在 0025 触发 DuplicateColumn；DB-BL-2C-R2 移除以恢复 canonical 时间线。
+        _created_at_column(),
```

未修改：
- `0025_ai_edit_result_delivery.py`（保留为 file_size_bytes 正典 introducer）
- ORM `app/models.py`（`AiEditJobArtifact.file_size_bytes` 第 1651 行保留不动）
- 不新建 repair revision
- 不 stamp（任何 revision，legacy / disposable / prod / staging）
- P1 Consumer / M07 Core 不动
- legacy dev PG（5432）READ-ONLY / UNTOUCHED
- `scripts/db_bl_2c_temporal_audit.py` / `db_bl_2c_chain_audit.py`：未改语义，仅运行验证（无最小 helper 调整需要）

独立 git provenance 复核（R2 执行窗口）：
- `0008` 提交历史：仅 `bc00897`(07-10 引入) / `3143b15`(07-31)，引入时第 340 行已含该列。
- `0025` 提交历史：仅 `231808d`(08-03)。
- ORM blame：`app/models.py:1651` = `231808d5 (2026-08-03) file_size_bytes = Column(BigInteger, comment="归档文件大小")`。

---

## 2. R1 Corrections Applied

实施前置 doc-sync，修正 `DB_BL_2C_R1_MIGRATION_CHAIN_REMEDIATION_DESIGN.md` 审批冻结的三项（无新事实冲突，无需重新审批）：

| Correction | 原表述 | 修正后 | 状态 |
|---|---|---|---|
| 1 环境兼容性过强 | "没有任何数据库曾合法执行过 revision 0025" | `EXISTING_ENVIRONMENT_COMPATIBILITY_RISK: LOW_BUT_NOT_GLOBALLY_PROVEN`，区分 `NO EVIDENCE FOUND` 与 `PROVEN NONE EXIST`，保留 production/staging `UNKNOWN` | ✅ APPLIED |
| 2 op.execute 表述不完整 | "全部为 UPDATE/DELETE" | "全部为 DML（INSERT/UPDATE/DELETE），无 schema DDL（`RAW SCHEMA DDL: NONE FOUND`），temporal audit 对 raw schema DDL 盲区在当前链未命中" | ✅ APPLIED |
| 3 Strategy B 等级 | `ACCEPTABLE_FALLBACK` | `CONDITIONAL_FALLBACK`，明确 `if exists: skip` 不得视为安全（须 type/nullable/default/comment 等 canonical semantic equivalence 校验），R2 不得切换到 Strategy B | ✅ APPLIED |

```
DB-BL-2C-R1:
CORRECTIONS_APPLIED
COMPLETE / FROZEN
```

---

## 3. Migration Change

```
0008_xiaogao_phase1_core.py:
  create_table("ai_edit_job_artifacts", ...) 内
  file_size_bytes REMOVED（原 PREDECLARED_FUTURE_SCHEMA 消除）

0025_ai_edit_result_delivery.py:
  UNCHANGED（保留为 file_size_bytes 正典 introducer）
```

### 为什么

1. **git provenance 闭合**（R1 §2 / R1 审批 §2，`GIT_HISTORY_VERIFIED`）：0025 是 `file_size_bytes` 的正典 owner——ORM 字段（`git blame` 行 1651 = `231808d5`）、migration `add_column`（0025 第 59 行）、结果交付业务功能（docstring 明确列为 0025 新增列）三者在同一提交 `231808d5` 抵达。0008 的预声明是 authoring-time forward declaration（出生即含，07-10 `bc00897`），既非 legitimate fix 也非 historical backfill/mutation。
2. **恢复 canonical 历史时间线**：列在 0025 抵达，与 ORM 历史一致；migration chain 重新成为 schema 演进的可靠记录。
3. **确定性 / 不掩盖 drift / 与 provenance 一致**：不引入状态依赖，drift 被消除（非合法化）。
4. **最小 diff**：0008 删 1 行。不改 0025，不新建 revision，不 stamp。
5. **环境零风险（已证明 DB 范围）**：无可信 DB 曾穿越 0025（legacy 无 `alembic_version`；disposable 停 0016；R2 三个新库为新创 disposable）。Alembic 不校验 migration 文件 checksum（`env.py` 无 hash/verify 注入）。

---

## 4. MR-0 Temporal Audit

实施 Strategy A 后重跑两个只读静态审计脚本：

```
python scripts/db_bl_2c_temporal_audit.py
  → 33 revisions, 356 upgrade ops
  → CONFIRMED temporal conflicts: 0   （原 1 处 0025 file_size_bytes 已消失）
  → POTENTIAL conflicts: 1             （0004 双索引，FALSE_POSITIVE 保持）
  → tables=60  total_cols=867  indexes=128  uniques=42  fks=1  checks=33

python scripts/db_bl_2c_chain_audit.py
  → duplicate add_column (create-already-has) count: 0
```

0004 `douyin_account_agent_bindings(merchant_id, account_open_id)` 双索引保持 `FALSE_POSITIVE` 分类（partial unique 索引带 `postgresql_where` 谓词 vs 全表普通索引，PG 合法共存），未为"全零输出"删除合法 index。

total_cols=867 与修复前一致（0008 仅移除预声明，0025 仍 add 该列，全链落点列数不变），符合预期。

```
MR-0: PASS
EVIDENCE: STATIC_AUDIT_VERIFIED（AST 静态解析，不连库、不改文件）
```

---

## 5. MR-1 Empty → 0030

新建全新空库 `db_bl_2c_r2_mr1_0030`（5433 disposable，不复用停 0016 的失败库），实跑 `alembic upgrade 0030`。

```
database identity:  db_bl_2c_r2_mr1_0030 @ 127.0.0.1:5433（disposable, postgres:dbbl2c_local）
before revision:   EMPTY（0 表, 无 alembic_version）
target revision:   0030
after revision:    alembic current = 0030   （alembic_version.version_num = 0030）
table count:       58
```

`upgrade 0030` 真实成功（exit 0）。R1 时代 `EMPTY PG → alembic upgrade 0030 → FAIL @ 0025 DuplicateColumn` 已消除。

```
MR-1: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
```

---

## 6. MR-2 Empty → 0034

另一独立全新空库 `db_bl_2c_r2_mr2_head`，实跑 `alembic upgrade head`。

```
database identity:  db_bl_2c_r2_mr2_head @ 127.0.0.1:5433（独立 disposable, postgres:dbbl2c_local）
before revision:   EMPTY（0 表, 无 alembic_version）
target revision:   head
after revision:    alembic current = 0034 (head)
                   alembic heads = 0034 (head)   单头
table count:       61
```

`upgrade head` 真实成功（exit 0）。证明真正 `empty → head` 一次完整 bootstrap 可行。未用 0030 DB → upgrade 0034 替代本 Gate（独立空库直跑 head）。

```
MR-2: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
```

---

## 7. MR-3 Historical Timeline

用第三个独立空库 `db_bl_2c_r2_mr3_timeline` 逐步升级，核验 `file_size_bytes` 历史所有权已恢复。

### Before 0025（@0024）

```
alembic upgrade 0024 → alembic current = 0024
ai_edit_job_artifacts.file_size_bytes = ABSENT   （information_schema.columns count = 0）
```

### At / After 0025（@0025）

```
alembic upgrade 0025 → alembic current = 0025
ai_edit_job_artifacts.file_size_bytes = PRESENT   （count = 1）

canonical schema 属性（PG catalog 可靠核验）:
  type     = bigint       （对应 0025 sa.BigInteger()）
  nullable = YES          （对应 0025 nullable=True）
  default  = NULL         （对应 0025 无 default）
  comment  = 归档文件大小  （对应 0025 comment="归档文件大小"，PG col_description 可靠核验）
```

历史时间线已恢复：列在 0025 抵达（非 0008），与 git provenance 一致。不仅确认列名存在，且 canonical schema 属性全等价于 0025 定义。

```
MR-3: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
```

---

## 8. MR-4 Schema Checkpoints

不只验证 `alembic current`，还核验关键 schema 落点（确认 revision 前进伴随实际 schema 落地）。

### @0030（db_bl_2c_r2_mr1_0030）

```
table count:        58
total columns:      915
indexes:            225
foreign keys:       20
constraints total:  551

关键 migration objects:
  ai_edit_job_artifacts 表: PRESENT
  ai_edit_job_artifacts.file_size_bytes: PRESENT (bigint, nullable)  ← 由 0025 正典引入
  compute_transactions.idempotency_key:  PRESENT (character varying, nullable)  ← 0030 add_column
  compute_transactions.payload_evidence: PRESENT (text, nullable)  ← 0030 add_column
  uk_compute_transactions_merchant_idempotency: PRESENT  ← 0030 create_unique_constraint
  0032/0033/0034 表: ABSENT (count=0)  ← 0030 落点尚未到达
```

### @0034（db_bl_2c_r2_mr2_head）

```
table count:        61
total columns:      932
indexes:            231
foreign keys:       21
constraints total:  571

关键 migration objects:
  daily_report_generations:               PRESENT  ← 0032 create_table
  ai_edit_material_analysis_executions:   PRESENT  ← 0033 create_table
  ai_preview_executions:                  PRESENT  ← 0034 create_table
  ai_edit_job_artifacts.file_size_bytes:  PRESENT (bigint, nullable)
```

0030→0034 增量方向一致（+3 表 / +17 列 / +6 索引 / +1 FK / +20 约束），非减少。Alembic revision 成功不仅是 revision table 前进，实际 schema 也落地。

```
MR-4: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
```

---

## 9. MR-5 Existing DB Compatibility

审批已冻结 `EXISTING_ENVIRONMENT_RISK: LOW_BUT_NOT_GLOBALLY_PROVEN`。R2 正面确认：

- **已证明 DB 范围**：无可信 DB 穿越 0025。
  - legacy dev PG（5432）：无 `alembic_version`（create_all 建），从未 alembic upgrade。
  - disposable 失败 DB（5433 `db_bl_2c_expected_0030` / `db_bl_2c_expected_0034`）：停 0016（0025 即阻断，从未成功穿越 0025），disposable 测试产物。
  - R2 三个新验证库（`db_bl_2c_r2_mr1_0030` / `db_bl_2c_r2_mr2_head` / `db_bl_2c_r2_mr3_timeline`）：均为本轮新创 disposable，空库直跑。
- **production/staging**：仓库无 cutover 证据（P1 checkpoint 显示 PG 迁移多 PENDING / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT），未正面排除 → `UNKNOWN`。
- **trusted old-revision disposable fixture（≥0025）**：仓库/本地环境内无可安全验证的可证明 trusted fixture。

不得伪造 production/staging compatibility evidence。

```
MR-5: NOT_APPLICABLE / NO_TRUSTED_EXISTING_REVISION_FIXTURE
PRODUCTION/STAGING REVISION: UNKNOWN（保留风险记录）
```

这不阻断 Strategy A（无可信 DB 穿越 0025；Alembic 不校验 migration 文件 checksum）。

---

## 10. MR-6 Revision Integrity

```
revision chain: 单链 0001_empty_baseline → … → 0029 → 0030 → 0032 → 0033 → 0034
  （0031 编号跳号：0032.down_revision = "0030"，非分叉，保持）
alembic heads: 0034 (head)   单头
revision 标识符: 0008 revision 仍 = "0008_xiaogao_phase1_core"，down_revision 仍 = "0007_lead_type_widen"
revision graph: 未因修复改变
新增 revision: 无（仍 33 个 revision 文件）
```

未新增 revision，0025 保持原 revision（`0025`，down_revision `0024`），down_revision graph 不变，0031 跳号仍不是 branch。

```
MR-6: PASS
EVIDENCE: STATIC_AUDIT_VERIFIED
```

---

## 11. Regression Verification

R2 改动仅触及 0008 PG 迁移文件。回归集：与 ai_edit_job_artifacts / file_size_bytes / db migration / readiness / temporal audit 相关的测试。

| 维度 | baseline（0008 修复前） | after（0008 修复后） |
|---|---|---|
| 相关测试集 | 12 failed / 84 passed | 12 failed / 84 passed |
| new regressions | — | **0** |

`baseline failures == after failures`，完全一致，0 new regression。12 个 baseline 失败全部定性为环境/既有 drift，与 0008 PG 改动无关：

| 失败项 | 根因 | 与 0008 改动关系 |
|---|---|---|
| `test_db_readiness` ×4（`test_load_alembic_heads_9000/9100`、`test_pg_all_pass`、`test_pg_alembic_mismatch`、`test_pg_critical_table_missing`） | `EXPECTED_HEAD_9000` 硬编码旧值 `0007_lead_type_widen`，实际 head 已演进至 `0034`；其余需运行 PG 连接校验 | 无关（测试预期过期 / 环境） |
| `test_xiaogao_phase1_schema::test_sqlite_migration_apply_on_temp_db_is_idempotent` | SQLite migration seed 计数 drift（`assert 7 == 6`，compute_markup_ratios seed） | 无关（SQLite 迁移路径，非 PG alembic chain） |
| `test_ai_edit_result_delivery` ×6 | `UploadError: TOS 配置不全，需要 endpoint/region/bucket/access_key/secret_key` | 无关（环境缺 TOS 凭证；用 ORM `create_all` 建表，file_size_bytes 仍由 ORM 创建） |

补充确认：PG 0008 文件断言（`test_postgres_revision_file_exists_and_revisions` / `test_postgres_revision_creates_expected_tables_and_columns` / `test_postgres_revision_adds_existing_table_columns`）全部 PASS——列检查断言 `ai_edit_job_artifacts` 预期列 `["job_id","artifact_id","storage_key"]` 不含 `file_size_bytes`，与改动一致。

> 纪律：未为让测试全绿扩大修复范围。既有失败保留为 baseline，标注根因。

---

## 12. Resume Verdict

R2 同时满足全部 Gate：

```
MR-0  PASS  (STATIC_AUDIT_VERIFIED)   temporal/chain audit CONFIRMED=0
MR-1  PASS  (PG_RUNTIME_VERIFIED)     empty → 0030
MR-2  PASS  (PG_RUNTIME_VERIFIED)     empty → 0034/head
MR-3  PASS  (PG_RUNTIME_VERIFIED)     file_size_bytes timeline + canonical 属性
MR-4  PASS  (PG_RUNTIME_VERIFIED)     0030/0034 schema checkpoints
MR-5  NOT_APPLICABLE / NO_TRUSTED_EXISTING_REVISION_FIXTURE
      （PRODUCTION/STAGING REVISION: UNKNOWN，保留风险记录）
MR-6  PASS  (STATIC_AUDIT_VERIFIED)   revision chain integrity
```

```
MIGRATION_CHAIN_BOOTSTRAP_REMEDIATION:
VERIFIED

EMPTY → 0030:
PG_RUNTIME_VERIFIED

EMPTY → 0034:
PG_RUNTIME_VERIFIED

MIGRATION CHAIN:
BOOTSTRAP CONFORMANCE RESTORED
```

```
DB-BL-2C:
ELIGIBLE_TO_RESUME
```

> 即使 R2 完全通过，**不直接进入 DB-BL-2D**。下一步返回 DB-BL-2C Exact Reconciliation：重新生成 Expected@0030 / Expected@0034 / Legacy Actual，完成 Matrix A（Legacy Actual vs Expected@0030）/ B（Expected@0030 vs Expected@0034）/ C（Legacy Actual vs Expected@0034）。只有 2C 完成并审批后才有资格进入 DB-BL-2D。

---

## 13. Implementation Status

```
MIGRATION CHAIN REMEDIATION:
IMPLEMENTED / VERIFIED

LEGACY DB REPAIR:
NOT STARTED

DB-BL-2D:
NOT AUTHORIZED
```

R2 范围内完成：
- R1 三项 Correction doc-sync（`DB_BL_2C_R1_MIGRATION_CHAIN_REMEDIATION_DESIGN.md` 已 FROZEN）
- Strategy A 实施（0008 删 1 行 file_size_bytes）
- MR-0~MR-6 全绿（2×STATIC_AUDIT_VERIFIED + 4×PG_RUNTIME_VERIFIED + 1×N/A）
- 回归 0 new regression

R2 范围外未触碰：
- 未修改 0025 / 未新建 revision / 未 stamp
- 未改 ORM / P1 Consumer / M07 Core
- 未触碰 legacy dev PG（5432 READ-ONLY）/ production / staging
- 未恢复 Exact Reconciliation（2C 复跑须独立窗口）
- 未进入 DB-BL-2D
- 未切换 Strategy B

---

## 附：证据等级索引

| 事实 | 证据等级 |
|---|---|
| 0008 引入即含 file_size_bytes / 0025 正典 owner / ORM blame 同提交 | `GIT_HISTORY_VERIFIED` |
| temporal audit CONFIRMED=0 / chain audit duplicate=0 / revision 链单链 head=0034 | `STATIC_AUDIT_VERIFIED` |
| empty → 0030 PASS / empty → 0034 PASS / file_size_bytes timeline + canonical 属性 / 0030+0034 schema checkpoints | `PG_RUNTIME_VERIFIED` |
| production/staging revision 未正面排除 | `UNKNOWN` |
| 无可信 trusted old-revision fixture | `NOT_APPLICABLE / NO_TRUSTED_EXISTING_REVISION_FIXTURE` |

R2 实施报告完成。停止于此，提交审批窗口。不自行恢复 2C，不进入 2D。
