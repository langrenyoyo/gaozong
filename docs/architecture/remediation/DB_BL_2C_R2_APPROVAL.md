# DB-BL-2C-R2 — Migration Chain Bootstrap Remediation Implementation 审批报告

> 阶段：DB-BL-2C-R2 **Approval Window**
> 日期：2026-08-10
> 审批窗口：DB-BL-2C-R2 Migration Chain Bootstrap Remediation Implementation 审批窗口
> 审查对象：commit `3b84fe4`
> 审查范围：R2 实施结果独立审查 + Bootstrap Gate 独立 runtime 复跑
> 前置冻结：R1 设计 `DB_BL_2C_R1_MIGRATION_CHAIN_REMEDIATION_DESIGN.md`（Strategy A = APPROVED）、R1 审批 `DB_BL_2C_R1_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`）、2C 审批 `DB_BL_2C_APPROVAL.md`（`BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE`）、2B `DB_BL_2B_APPROVAL.md`（Schema Authority MODEL A / Bootstrap Contract 冻结）。
> 工作原则：独立核验 → 不采信报告自述 → 真实 PG runtime 重跑 → 仅判定 Resume Eligibility，不自行恢复 2C、不进 2D。

---

## 1. Technical Decision

```
DB-BL-2C-R2:
APPROVED
```

实施严格遵循 R1 冻结的 Strategy A（唯一批准策略），范围最小（0008 删 1 行 file_size_bytes 预声明 + 4 行中文注释）。审批窗口使用**自建的全新空 disposable PG** 独立重跑全部 Bootstrap Gate，所有 runtime 证据真实复现，与 R2 报告逐项精确吻合，无 scope 越界、无 legacy/prod/staging 误操作、无新增 regression。

---

## 2. Scope Compliance（Q1）

独立核验 commit `3b84fe4` 的真实 diff 与文件清单。

### 提交触及文件清单（独立 `git show --name-status`）

| 文件 | 状态 | 性质 | 是否授权范围内 |
|---|---|---|---|
| `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py` | M | 唯一迁移文件改动 | ✅ Strategy A 授权 |
| `docs/architecture/remediation/DB_BL_2A_APPROVAL.md` 等 9 份文档 | A | R2 报告 + R1 设计 + 2A/2B/2C 治理链产出 | ✅ 说明性文档 / 已批准 R1 correction |
| `scripts/db_bl_2c_chain_audit.py` / `scripts/db_bl_2c_temporal_audit.py` | A | 只读静态审计工具 | ✅ verification helper，未改迁移语义 |

### 0008 真实 diff（唯一迁移改动）

```diff
-        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
+        # file_size_bytes 不在此预声明：该列由 0025_ai_edit_result_delivery 正典引入
+        # （ORM 字段 + add_column + 结果交付功能同提交 231808d5 抵达，GIT_HISTORY_VERIFIED）。
+        # 0008 此处曾为 authoring-time forward declaration（PREDECLARED_FUTURE_SCHEMA），
+        # 导致空库自举在 0025 触发 DuplicateColumn；DB-BL-2C-R2 移除以恢复 canonical 时间线。
```

### 范围合规逐项判定

| 项 | 授权要求 | 实际 | 判定 |
|---|---|---|---|
| 迁移逻辑 diff | 仅 0008 删 file_size_bytes 预声明 | 仅 0008 删 1 行 + 4 行注释 | ✅ |
| 0025 | UNCHANGED | 未出现在提交 stat；line 59 add_column + comment="归档文件大小" 保留 | ✅ |
| ORM | UNCHANGED | `app/models.py` 未在提交中 | ✅ |
| Revision Graph | UNCHANGED | 仍 33 revision，链不变 | ✅ |
| New Migration | NONE | 无新建 | ✅ |
| Legacy DB | NO WRITE | 5432 legacy 仍无 `alembic_version`（READ-ONLY，未触碰） | ✅ |
| Stamp | NONE | 无 stamp | ✅ |
| P1 Consumer / M07 Core | UNCHANGED | 未触及 | ✅ |
| prod/staging | NO OPERATION | 未触碰 | ✅ |
| DB-BL-2D | NOT AUTHORIZED | 未进入 | ✅ |

未发现任何未经批准的 schema 行为变化。

---

## 3. MR-0 ~ MR-6 Verdict（逐 Gate 独立核验）

### MR-0 Temporal Audit（Q3）— 独立重跑

```
python scripts/db_bl_2c_temporal_audit.py   （审批窗口亲自运行）
  → 33 revisions, 356 upgrade ops
  → CONFIRMED temporal conflicts: 0   （原 1 处 0025 file_size_bytes 已消失）
  → POTENTIAL conflicts: 1             （0004 双索引，FALSE_POSITIVE 保持）
  → tables=60  total_cols=867  indexes=128  uniques=42  fks=1  checks=33

python scripts/db_bl_2c_chain_audit.py      （审批窗口亲自运行）
  → duplicate add_column (create-already-has) count: 0
```

- 0004 双索引核验：`uk_dy_account_agent_bindings_active_default`（partial unique，`postgresql_where = status='active' AND is_default IS TRUE AND deleted_at IS NULL`）vs `idx_dy_account_agent_bindings_merchant_account`（全表普通索引）——不同名、不同 WHERE 谓词、不同语义，PG 合法共存。**FALSE_POSITIVE 分类保持正确**，未为"全零输出"删除合法 index。
- 0008 仅移除预声明、0025 仍 add 该列 → 全链落点列数不变（total_cols=867 与修复前一致）。

```
MR-0: PASS
EVIDENCE: STATIC_AUDIT_VERIFIED
```

### MR-1 Empty → 0030（Q4）— 审批窗口自建独立空库重跑

审批窗口**自建全新空 disposable 库** `db_bl_2c_r2appr_mr1 @ 127.0.0.1:5433`（非复用报告方库、非复用停 0016 失败库、非 legacy 5432、非生产/预发布）：

```
before:   EMPTY（0 表, 无 alembic_version）   ← 审批窗口独立确认
command:  alembic upgrade 0030                 ← exit 0
after:    alembic current = 0030
          alembic_version.version_num = 0030
          table count = 58
```

报告称 58 表 → 审批窗口独立重跑得 58 表，**精确吻合**。

```
MR-1: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
EMPTY_TO_0030: PG_RUNTIME_VERIFIED
```

### MR-2 Empty → Head / 0034（Q5）— 审批窗口自建独立空库重跑（最关键 Gate）

审批窗口**另一独立全新空库** `db_bl_2c_r2appr_mr2`（非 0030 DB → 0034 替代，独立空库直跑 head）：

```
before:   EMPTY
command:  alembic upgrade head                 ← exit 0
after:    alembic current = 0034 (head)
          alembic heads = 0034 (head)   单头
          table count = 61
关键表落点:
  daily_report_generations             PRESENT  ← 0032 create_table
  ai_edit_material_analysis_executions PRESENT  ← 0033 create_table
  ai_preview_executions                PRESENT  ← 0034 create_table
  ai_edit_job_artifacts                PRESENT
  compute_transactions                 PRESENT
```

报告称 61 表 → 审批窗口独立重跑得 61 表，三张新增表逐一核验存在，**精确吻合**。这是 `MIGRATION_CHAIN_BOOTSTRAP_FAILURE` 是否真正解除的决定性证据——**真实 PG runtime empty→head 一次完整 bootstrap 成功**。

```
MR-2: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
EMPTY_TO_HEAD: PG_RUNTIME_VERIFIED
```

### MR-3 file_size_bytes Runtime Timeline（Q6）— 审批窗口自建独立空库逐步升级

审批窗口**第三独立空库** `db_bl_2c_r2appr_mr3` 逐步升级，以 PG catalog 为准：

```
@0024:
  alembic upgrade 0024 → exit 0
  ai_edit_job_artifacts 表: PRESENT
  ai_edit_job_artifacts.file_size_bytes: ABSENT   （information_schema.columns count = 0）

@0025:
  alembic upgrade 0025 → exit 0
  ai_edit_job_artifacts.file_size_bytes: PRESENT   （count = 1）
  canonical schema 属性（PG catalog 可靠核验）:
    type     = bigint       （对应 0025 sa.BigInteger()）
    nullable = YES          （对应 0025 nullable=True）
    default  = NULL         （对应 0025 无 default）
    comment  = 归档文件大小  （PG col_description 可靠核验，对应 0025 comment）
```

审批窗口独立确认：列在 0025 抵达（非 0008），canonical schema 属性全等价于 0025 定义。

```
MR-3: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
```

### MR-4 Schema Checkpoints（Q7）— 实际 schema objects 落地核验

不只接受 `alembic_version 前进`，独立确认实际 schema 落点（审批窗口对报告方库只读核验 + 自建库重跑双重确认）：

#### @0030（`db_bl_2c_r2_mr1_0030` 报告方库 + 审批窗口自建库双确认）

```
table count:        58
total columns:      915
indexes:            225
foreign keys:       20

关键 migration objects:
  ai_edit_job_artifacts 表: PRESENT
  ai_edit_job_artifacts.file_size_bytes: PRESENT (bigint, nullable)  ← 0025 正典引入
  compute_transactions.idempotency_key:  PRESENT  ← 0030 add_column
  compute_transactions.payload_evidence: PRESENT  ← 0030 add_column
  uk_compute_transactions_merchant_idempotency: PRESENT  ← 0030 create_unique_constraint
  0032/0033/0034 表: ABSENT (count=0)  ← 0030 落点尚未到达
```

#### @0034（`db_bl_2c_r2_mr2_head` 报告方库 + 审批窗口自建库双确认）

```
table count:        61
total columns:      932
indexes:            231
foreign keys:       21

关键 migration objects:
  daily_report_generations              PRESENT  ← 0032 create_table
  ai_edit_material_analysis_executions  PRESENT  ← 0033 create_table
  ai_preview_executions                 PRESENT  ← 0034 create_table
  ai_edit_job_artifacts.file_size_bytes PRESENT (bigint, nullable)  ← canonical 定义保持
```

0030→0034 增量方向一致（+3 表 / +17 列 / +6 索引 / +1 FK / +20 约束），非减少。审批窗口独立确认三张新增表分别对应 0032/0033/0034 的 `create_table` object，非仅依赖 table count。报告的 cols/indexes/fks 计数经审批窗口独立查询**精确吻合**。

```
MR-4: PASS
EVIDENCE: PG_RUNTIME_VERIFIED
```

### MR-5 Existing DB Compatibility（Q8）— 表述准确性核验

R1 冻结 `EXISTING_ENVIRONMENT_COMPATIBILITY_RISK: LOW_BUT_NOT_GLOBALLY_PROVEN`。R2 报告 `NOT_APPLICABLE / NO_TRUSTED_EXISTING_REVISION_FIXTURE`，`production/staging revision = UNKNOWN`。审批窗口独立核验表述准确性：

- legacy dev PG（5432）：无 `alembic_version`（审批窗口确认 count=0），create_all 建，从未 alembic upgrade。✅
- disposable 失败 DB（停 0016）：0025 即阻断，从未成功穿越 0025。✅
- 审批窗口自建三个验证库：本轮新创 disposable，空库直跑。✅
- production/staging：仓库无 cutover 证据，未正面排除 → `UNKNOWN` 保留。✅

报告**未**把"没有发现 trusted fixture"升级为"证明不存在任何已穿越 0025 的环境"，`LOW_BUT_NOT_GLOBALLY_PROVEN` 风险正确保留。MR-5 N/A 不阻断 R2，但风险记录保留。

```
MR-5: NOT_APPLICABLE / NO_TRUSTED_EXISTING_REVISION_FIXTURE
PRODUCTION/STAGING REVISION: UNKNOWN（风险保留，不升级不删除）
```

### MR-6 Revision Chain Integrity（Q9）— 独立核验

```
revision chain: 单链 0001_empty_baseline → … → 0029 → 0030 → 0032 → 0033 → 0034
  （0031 编号跳号：0032.down_revision = "0030"，非分叉，保持）
alembic heads = 0034 (head)   单头   ← 审批窗口 alembic heads 独立确认
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

## 4. Bootstrap Runtime Verdict

审批窗口使用**三个自建全新空 disposable PG** 独立重跑（非采信报告方库）：

```
empty → 0030:   PASS   (alembic current = 0030, 58 表)        PG_RUNTIME_VERIFIED
empty → 0034:   PASS   (alembic current = 0034 head, 61 表)   PG_RUNTIME_VERIFIED
```

两个最关键 Bootstrap Gate 均取得独立 `PG_RUNTIME_VERIFIED`。审批窗口自建库验证完成后已清理自身 disposable（不影响报告方库与 legacy）。

---

## 5. Historical Ownership Runtime Confirmation（0024/0025 时间线）

```
@0024:
  ai_edit_job_artifacts.file_size_bytes = ABSENT
@0025:
  ai_edit_job_artifacts.file_size_bytes = PRESENT
    type = bigint
    nullable = YES
    default = NULL（无 default）
    comment = 归档文件大小
```

```
HISTORICAL_SCHEMA_OWNER(file_size_bytes) = 0025
CANONICAL TIMELINE: RESTORED（列在 0025 抵达，与 git provenance + ORM blame 一致）
```

---

## 6. Previous Failure Supersession

```
BEFORE R2:
  PG_RUNTIME_VERIFIED_FAILURE @ 0025
  （EMPTY PG → alembic upgrade 0030/head → FAIL @ 0025 DuplicateColumn）

AFTER R2:
  PG_RUNTIME_VERIFIED_PASS @ 0025
  （EMPTY PG → alembic upgrade 0030/head → PASS，file_size_bytes 由 0025 正典引入）
```

旧 failure 保留为历史真实证据，**不删除**——`PG_RUNTIME_VERIFIED_FAILURE` 仍是 R2 修复前的真实 runtime 事实，R2 的修复与重跑使其被 supersede，而非抹除。

---

## 7. Migration Chain Conformance

```
CURRENT_MIGRATION_CHAIN_CONFORMANCE: PASS
MIGRATION_CHAIN_BOOTSTRAP_REMEDIATION: VERIFIED
MIGRATION CHAIN: BOOTSTRAP CONFORMANCE RESTORED
```

空 PG → alembic head 一次完整 bootstrap 已被独立 PG runtime 证明可行；0008 authoring-time forward declaration drift 已消除（非合法化、非掩盖）；canonical 历史时间线与 git provenance 一致。

---

## 8. DB-BL-2C Resume Decision

```
DB-BL-2C:
PREVIOUS STATUS = BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE
NEW STATUS      = AUTHORIZED_TO_RESUME
```

`BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` **正式解除**。允许重新启动 `DB-BL-2C Exact Reconciliation`：重新生成 `Expected@0030` / `Expected@0034` / `Legacy Actual` 及 Matrix A（Legacy Actual vs Expected@0030）/ B（Expected@0030 vs Expected@0034）/ C（Legacy Actual vs Expected@0034）。

---

## 9. DB-BL-2B Bootstrap Contract

```
POSTGRESQL SCHEMA AUTHORITY:
MODEL A — APPROVED / FROZEN

BOOTSTRAP CONTRACT (设计批准):
EMPTY PG → ALEMBIC HEAD — APPROVED / FROZEN

BOOTSTRAP CONTRACT IMPLEMENTATION CONFORMANCE:
PG_RUNTIME_VERIFIED  ← 本次 MR-2 通过，首次升级为 runtime conformance 证据
```

设计批准（2B 冻结）与实现 runtime conformance 已区分：本次 R2 首次以独立 PG runtime 证据证明 `EMPTY PG → ALEMBIC HEAD` contract 的实现符合。

---

## 10. DB-BL-2D

```
DB-BL-2D: NOT AUTHORIZED
```

即使 R2 完全通过，`DB-BL-2C != COMPLETE`。尚未完成 Matrix A / Matrix B / Matrix C / Revision Identity Verdict / Stamp Eligibility。2C 完成并审批后才有资格进入 2D。

---

## 11. R1 Corrections Doc-Sync（Q11）— 独立核验

审批窗口独立确认 R1 审批要求的三项 correction 已正确写入 `DB_BL_2C_R1_MIGRATION_CHAIN_REMEDIATION_DESIGN.md`：

| Correction | 要求 | 实际（审批窗口 grep 核验） | 判定 |
|---|---|---|---|
| 1 环境兼容性 | `LOW_BUT_NOT_GLOBALLY_PROVEN`，区分 `NO EVIDENCE FOUND` 与 `PROVEN NONE EXIST`，保留 prod/staging `UNKNOWN` | line 219/246 `LOW_BUT_NOT_GLOBALLY_PROVEN`，§5 明确区分且保留 `UNKNOWN` | ✅ |
| 2 op.execute 表述 | 包含 INSERT/UPDATE/DELETE，但 `RAW SCHEMA DDL = NONE_FOUND` | line 159 "全部为 DML（INSERT seed / UPDATE 回填 / DELETE 清理），无原生 schema DDL，`RAW SCHEMA DDL: NONE FOUND`" | ✅ |
| 3 Strategy B 等级 | `CONDITIONAL_FALLBACK`（非 `ACCEPTABLE_FALLBACK`） | line 284 `Strategy B = CONDITIONAL_FALLBACK`，全库无 `ACCEPTABLE_FALLBACK` | ✅ |

```
R1: CORRECTIONS_APPLIED
COMPLETE / FROZEN
```

---

## 12. Regression Verification（Q10）— 独立核验

审批窗口独立运行受影响测试：

```
python -m pytest tests/test_xiaogao_phase1_schema.py -k "postgres_revision"
  → 6 passed, 14 deselected
```

- 受影响的 0008 PG 文件断言（`test_postgres_revision_file_exists_and_revisions` / `test_postgres_revision_creates_expected_tables_and_columns` / `test_postgres_revision_adds_existing_table_columns`）全部 PASS。断言为 spot-check（断言关键列 `["job_id","artifact_id","storage_key"]` **存在**，非断言 file_size_bytes 缺失），移除预声明不破坏断言。
- 报告 baseline 12 == after 12、0 new regression 主张结构成立：12 个 baseline 失败全部定性为环境/既有 drift（`EXPECTED_HEAD_9000` 硬编码过期 / SQLite 迁移路径 / TOS 凭证缺失），与 0008 PG 改动无关。
- 报告**未**为让测试全绿扩大修复既有 12 失败，纪律保持。

```
NEW_REGRESSION = 0
```

---

## 13. Legacy Dev PG 状态

```
LEGACY DEV PG (5432):
DISPOSABLE
READ_ONLY_PG_VERIFIED   ← 审批窗口确认仍无 alembic_version 表，create_all 状态未变
```

`DISPOSABLE` 不等于本阶段授权 rebuild。审批窗口全程：

```
NO LEGACY WRITE
NO REBUILD
NO STAMP
NO UPGRADE
```

---

## 14. Explicitly Forbidden（继续冻结）

即使本审批通过，以下行为在本阶段继续被禁止：

```
NO STAMP
NO LEGACY UPGRADE
NO LEGACY REPAIR
NO REBUILD
NO PROD/STAGING DB OPERATION
NO DB-BL-2D
NO 自行恢复 2C Exact Reconciliation（须独立 2C 复跑窗口）
NO 删除旧 PG_RUNTIME_VERIFIED_FAILURE 历史证据
```

---

## 15. 审批结论

```
DB-BL-2C-R2:
APPROVED

MIGRATION_CHAIN_BOOTSTRAP_REMEDIATION:
VERIFIED

CURRENT_MIGRATION_CHAIN_CONFORMANCE:
PASS

EMPTY → 0030:
PG_RUNTIME_VERIFIED

EMPTY → 0034:
PG_RUNTIME_VERIFIED

PREVIOUS FAILURE SUPERSESSION:
BEFORE R2 = PG_RUNTIME_VERIFIED_FAILURE
AFTER R2 = PG_RUNTIME_VERIFIED_PASS（旧证据保留不删）

DB-BL-2C:
AUTHORIZED_TO_RESUME
（BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE 正式解除）

DB-BL-2B BOOTSTRAP CONTRACT IMPLEMENTATION CONFORMANCE:
PG_RUNTIME_VERIFIED

DB-BL-2D:
NOT AUTHORIZED
```

---

## 附：审批窗口独立核验证据索引

| Gate | 审批窗口独立操作 | 结果 | 证据等级 |
|---|---|---|---|
| Q1 Scope | `git show 3b84fe4 --stat/diff` | 仅 0008 删 1 行 + 注释；0025/ORM/revision graph 不变 | GIT_DIFF_VERIFIED |
| Q2 Timeline | 0008 当前仅注释；0025 line 59 add_column 保留 | HISTORICAL_SCHEMA_OWNER=0025 恢复 | STATIC_VERIFIED |
| MR-0 | 亲自运行 temporal/chain audit | CONFIRMED=0 / duplicate=0 | STATIC_AUDIT_VERIFIED |
| MR-1 | 自建空库 `db_bl_2c_r2appr_mr1` → upgrade 0030 | current=0030, 58 表 | PG_RUNTIME_VERIFIED |
| MR-2 | 自建空库 `db_bl_2c_r2appr_mr2` → upgrade head | current=0034(head), heads=0034 单头, 61 表, 0032/0033/0034 表落地 | PG_RUNTIME_VERIFIED |
| MR-3 | 自建空库 `db_bl_2c_r2appr_mr3` → upgrade 0024→0025 | @0024 ABSENT / @0025 PRESENT, bigint/nullable/无default/comment=归档文件大小 | PG_RUNTIME_VERIFIED |
| MR-4 | 报告方库只读核验 + 自建库重跑 | 0030=58表/915列/225索引/20FK；0034=61表/932列/231索引/21FK；关键 object 落地 | PG_RUNTIME_VERIFIED |
| MR-5 | legacy 5432 确认无 alembic_version；表述准确性核验 | N/A，prod/staging UNKNOWN 保留，风险不升级不删除 | READ_ONLY_PG_VERIFIED |
| MR-6 | chain audit + alembic heads | 单链 head=0034，无新增 revision | STATIC_AUDIT_VERIFIED |
| Q10 Regression | 亲自运行 0008 PG 断言测试 | 6 passed，0 new regression | TEST_VERIFIED |
| Q11 R1 Correction | grep 核验 R1 设计文档 | 三项 correction 已写入 FROZEN | DOC_VERIFIED |

审批报告完成。停止于此，不自行恢复 2C，不进入 2D。
