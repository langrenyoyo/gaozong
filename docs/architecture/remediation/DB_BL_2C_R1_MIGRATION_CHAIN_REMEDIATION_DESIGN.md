# DB-BL-2C-R1 — Migration Chain Bootstrap Remediation Design

> 阶段：DB-BL-2C-R1 Migration Chain Bootstrap Remediation **Design / Audit**
> 日期：2026-08-10
> 模式：**DESIGN / AUDIT ONLY** — 仅有历史事实调查、provenance、全链 temporal drift audit、修复方案设计权限；**无 migration 修复实施权限**。
> 前置：`DB_BL_2C_APPROVAL.md`（`APPROVED / BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE`，授权 R1 设计/审计）、`DB_BL_2B_APPROVAL.md`（Schema Authority MODEL A 冻结）、`DB_BL_2A_APPROVAL.md`（2A COMPLETE）。
> 工作原则：**事实 → 设计 → 审批 → 实施**。先证明 Historical Schema Change Ownership，再允许修改 Migration History。

---

## 1. Current Failure

冻结 0025 runtime failure（来源：`DB_BL_2C_APPROVAL.md` §2，审批窗口 `PG_RUNTIME_VERIFIED_FAILURE` 独立复核）：

```
EMPTY PG → alembic upgrade 0030   → FAIL @ revision 0025
EMPTY PG → alembic upgrade head   → FAIL @ revision 0025
```

- 失败点：`0025_ai_edit_result_delivery.py:59`
- 失败 SQL：`ALTER TABLE ai_edit_job_artifacts ADD COLUMN file_size_bytes BIGINT`
- 错误：`DuplicateColumn: column "file_size_bytes" of relation "ai_edit_job_artifacts" already exists`
- 失败 DB 保留状态：`alembic_version=0016` / 业务表 54（0001–0016 事务内已提交，0017–0025 外层事务回滚）。0008 建表已创建该列 → 0025 add_column 命中已存在列。

```
DUPLICATE_COLUMN_CHAIN_DEFECT =
  CODE_VERIFIED + PG_RUNTIME_VERIFIED_FAILURE
table:  ai_edit_job_artifacts
column: file_size_bytes
```

当前冻结：不得预先判断"0008 一定被后续错误回填"或"0025 一定应改成 conditional migration"。provenance 见 §2。

---

## 2. Historical Provenance（Q1）

### 调查方法

纯 git 历史调查（`git log --follow` / `git show <rev>:<path>` / `git blame`），覆盖：

- `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py`
- `migrations/postgres/auto_wechat/versions/0025_ai_edit_result_delivery.py`
- `app/models.py`（`AiEditJobArtifact` 类）

### A. 0008 第一次进入仓库时是否已含 file_size_bytes？

```
结论：PRESENT
证据等级：GIT_HISTORY_VERIFIED
```

0008 引入提交：`bc00897 db：增加小高AI一期数据迁移骨架`（2026-07-10 19:01:40 +0800）。
`git show bc00897:migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py` 第 340 行已存在：

```python
sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
```

位于 `create_table("ai_edit_job_artifacts", ...)` 内。**出生即含。**

### B. 0025 第一次进入仓库时的设计意图

```
结论：INTRODUCE file_size_bytes（明确列为 0025 新增列）
证据等级：GIT_HISTORY_VERIFIED（docstring + add_column 同提交）
```

0025 引入提交：`231808d 功能：AI剪辑结果交付闭环（标题/归档/播放下载删除/搜索/标签/软删除）`（2026-08-03 20:35:02 +0800）。
0025 文件头 docstring（第 15–20 行）明确把 `file_size_bytes` 列为 0025 要新增的列；第 59 行 `op.add_column("ai_edit_job_artifacts", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True, comment="归档文件大小"))`。

### C. ORM 字段的加入时间（决定性证据）

```
AiEditJobArtifact.file_size_bytes ORM 字段引入提交 = 231808d5（2026-08-03 19:38:19 +0800）
与 migration 0025 同一提交。
```

`git blame app/models.py:1651`：

```
231808d5 (2026-08-03 19:38:19) 1651)     file_size_bytes = Column(BigInteger, comment="归档文件大小")
```

该 ORM 字段在 0008 引入时（07-10）**尚不存在**，直到 08-03 与 0025 同提交抵达。

### 时间线

| 日期 | 提交 | 事件 | file_size_bytes 状态 |
|---|---|---|---|
| 2026-07-10 19:01 | `bc00897` | 0008 引入 | migration create_table 已含；**ORM 无此字段**；无交付功能 |
| 2026-07-31 12:37 | `3143b15` | 0008 唯一后续修改 | **未触碰 file_size_bytes**（仅给 seed 补 ai_edit 能力行） |
| 2026-08-03 19:38 | `231808d5` | 0025 引入 + ORM 字段引入 + 结果交付功能 | ORM 字段 + 0025 add_column + 业务功能**同提交**抵达 |

### Historical Ownership Verdict

```
file_size_bytes
HISTORICAL SCHEMA OWNER (by intent) = 0025
CODE-LEVEL FIRST APPEARANCE         = 0008（投机性预声明，非后续回填）
EVIDENCE                             = GIT_HISTORY_VERIFIED
```

判定理由（非 AMBIGUOUS，证据可可靠证明）：

1. **0025 是该列的正典 introducer**：ORM 字段、migration `add_column`、结果交付业务功能三者在同一提交 `231808d5` 抵达，构成一个完整 feature 单元。
2. **0008 是无 ORM/功能支撑的投机性预声明**：0008 引入时（07-10）ORM 尚无此字段（08-03 才有），0008 在建表 DDL 中提前声明了一列当时无 ORM 映射、无业务功能消费的列。
3. **0008 的预声明是"出生即含"，不是后续回填**：0008 唯一的后续提交 `3143b15`（07-31）经 diff 核验未触碰 file_size_bytes（仅加 seed 能力行）。
4. 0008 的投机性预声明具有**部分性/不一致性**：0025 给 artifacts 表加的 5 列（is_final_video / delivery_status / archive_object_key / archive_error / file_size_bytes）中，**只有 file_size_bytes 被提前预声明进 0008**，其余 4 列正确等到 0025。单个游离列 = 作者ing slip，非"0008 拥有全部交付列"的刻意设计。

> 不判 AMBIGUOUS：ORM-blame 是硬 git 事实（非推断），与 0025 add_column 同提交可可靠证明 0025 是 owner。0008 的预声明属"出生即含的投机性预声明"——既非"legitimate fix"也非"historical backfill/mutation"，是第三类（authoring-time forward declaration）。

---

## 3. Migration Mutation Timeline（Q2）

调查 0008 是否在后续提交中被修改、使早期 revision 吸收未来 schema。

```
结论：NO HISTORICAL MUTATION / NO BACKFILL
类型：authoring-time forward declaration（出生即含，从未被后续修改）
证据等级：GIT_HISTORY_VERIFIED
```

0008 完整提交历史（`git log --follow`）：

| 提交 | 日期 | 是否触碰 file_size_bytes | 实际改动 |
|---|---|---|---|
| `bc00897` | 2026-07-10 19:01 | —（引入，已含） | 引入 0008，create_table 出生即含 file_size_bytes |
| `3143b15` | 2026-07-31 12:37 | **否** | 仅在 `compute_markup_ratios` seed 列表补 `ai_edit` 能力行（消除 MARKUP_RATIO_DRIFT 500） |

`git show 3143b15 -- 0008_*.py` diff 确认：后续修改仅 +1 行 seed（`"ai_edit"`），未触及 `create_table("ai_edit_job_artifacts")` 列集。

```
TEMPORAL_MIGRATION_DRIFT 判定：NOT APPLICABLE（无后续 mutation/backfill）
缺陷性质：0008 authoring-time speculative forward declaration
```

> 与审批窗口纪律一致（`DB_BL_2C_APPROVAL.md` §3 "审批窗口不采信'0008 一定是后来被错误修改的'"）：本 R1 经 git 证实——0008 确实不是"后来被修改"，而是"出生即含"。审批窗口的谨慎推断现被 git 事实闭合：drift 在 0008 authoring 时即存在。

---

## 4. Full-chain Temporal Drift Audit（Q3）

### 方法

扩展只读静态审计工具 `scripts/db_bl_2c_temporal_audit.py`（新建，AST 解析 `upgrade()` 函数体，覆盖全类别，不连库、不改文件；原有 `db_bl_2c_chain_audit.py` 保持不动，其输出已被审批窗口冻结为 column-audit 证据）。

覆盖类别（按链顺序累积 schema 状态，检测后续 op 命中已存在对象）：

- column：`create_table` 列 / 内联约束 vs 后续 `add_column`
- index：`create_index` 同名 / 同表同列序
- unique：`create_unique_constraint` / 内联 `sa.UniqueConstraint` 同名 / 同表同列序
- FK：`create_foreign_key` / 内联 `sa.ForeignKeyConstraint` / `sa.ForeignKey` 同名
- CHECK：`create_check_constraint` / 内联 `sa.CheckConstraint` 同名
- 二次 `create_table` 已存在表
- `alter_column` / `drop_*` 作用于不存在对象

> 本链 `op.execute` 共 21 处，经核验全部为 DML（INSERT seed / UPDATE 回填 / DELETE 清理），**无原生 schema DDL**（`ALTER TABLE ADD COLUMN` / `CREATE INDEX` / `DROP` / `RENAME` 均未命中，`RAW SCHEMA DDL: NONE FOUND`）。故 temporal audit 对 raw schema DDL 的盲区在当前链上未命中：全链 schema DDL 纯走 Alembic `op.*`，可纯 AST 审计（保守下界：不解析 `op.execute` 原生 SQL，但本链无需解析，盲区即实际下界）。

### 审计结果

```
33 revisions, 356 upgrade ops
tables=60  total_cols=867  indexes=128  uniques=42  fks=1  checks=33
```

| 类别 | 计数 | 明细 |
|---|---|---|
| CONFIRMED_TEMPORAL_CONFLICT | **1** | `[0025]` `ai_edit_job_artifacts.file_size_bytes` DuplicateColumn（create-vs-add，runtime 已印证） |
| POTENTIAL_CONFLICT | 1 | `[0004]` `douyin_account_agent_bindings(merchant_id, account_open_id)` 上 `uk_..._active_default` vs `idx_..._merchant_account` |
| FALSE_POSITIVE | 1 | 上项——见下 |
| NAME_ONLY / SEMANTICALLY_DIFFERENT | 0 | — |

### 候选分类

#### 1. CONFIRMED_TEMPORAL_CONFLICT — `[0025] ai_edit_job_artifacts.file_size_bytes`

- 已有真实 PG runtime failure（§1），非仅静态。
- 0008 create_table 已含该列 → 0025 add_column 命中 → `DuplicateColumn`。
- 这是**全链唯一阻断 fresh bootstrap 的 conflict**。

#### 2. FALSE_POSITIVE — `[0004] douyin_account_agent_bindings 双索引`

- `idx_dy_account_agent_bindings_merchant_account`：全表普通 btree 索引，列 `(merchant_id, account_open_id)`。
- `uk_dy_account_agent_bindings_active_default`：**partial unique 索引**，同列但 `postgresql_where = status='active' AND is_default IS TRUE AND deleted_at IS NULL`。
- 两者：不同名、不同语义（一个全表查询用、一个仅对 active+default 子集强制唯一）、不同 WHERE 谓词。
- PG 下合法共存（partial unique 索引与全表普通索引是两个独立对象）。
- 审计脚本仅比较列元组、忽略 `postgresql_where` 谓词与 `unique` 标志 → 误报。
- **结论：FALSE_POSITIVE，无需修复。**

### Full-chain 审计结论

```
全链 0001→0034 temporal drift 缺陷清单：
  - 阻断 fresh bootstrap 的 CONFIRMED conflict：1 处（0025 file_size_bytes）
  - 其他类别（index/unique/FK/CHECK/rename/alter/drop）CONFIRMED conflict：0
  - POTENTIAL/语义重复：0（0004 项为 false positive）
```

> 修复 0025 后，链中**无下一个 conflict 顶上来**。修复范围最小且有界：仅需消除 file_size_bytes 这一处 create-vs-add 重复。R2 实施后重跑全链 temporal audit 须输出 0 CONFIRMED。

---

## 5. Existing Environment Compatibility（Q6 / Q12 / Q13）

### 已有数据库 revision 证据（来源：`DB_BL_2C_APPROVAL.md` §0/§9，审批窗口 `READ_ONLY_PG_VERIFIED`）

| 数据库 | alembic_version | 建表方式 | 是否跑过 0008→0025 alembic upgrade | 处置 |
|---|---|---|---|---|
| legacy dev PG（5432 / `auto_wechat`） | **表不存在**（count=0） | `create_all`（57 表残骸，无 alembic_version） | **从未** | `DISPOSABLE`（5 行 compute_* seed，无 PII） |
| disposable 失败 DB `db_bl_2c_expected_0030`（5433） | `0016` | fresh alembic upgrade（失败停在 0016） | 跑到 0016，**0025 失败** | disposable 测试产物 |
| disposable 失败 DB `db_bl_2c_expected_0034`（5433） | `0016` | fresh alembic upgrade（失败停在 0016） | 跑到 0016，**0025 失败** | disposable 测试产物 |
| production / staging PG | `UNKNOWN` | 无 cutover 证据（P1 checkpoint 显示 PG 迁移多 PENDING / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT） | 无证据 | 未 cutover |

### 关键事实

```
EXISTING ENVIRONMENT COMPATIBILITY RISK: LOW_BUT_NOT_GLOBALLY_PROVEN
```

已证明事实（来源：2C 审批窗口 `READ_ONLY_PG_VERIFIED`）：

- legacy dev PG 无 `alembic_version` 表（`create_all` 建，从未 alembic upgrade）。
- disposable 失败 DB 停在 0016（0025 即阻断，从未成功穿越 0025）。

未证明但未发现证据的环境风险：

- production/staging revision = `UNKNOWN`（无 cutover 证据，但未正面排除；仓库无证据 ≠ 生产环境从未运行过 0025）。

> 纪律（应 R1 审批 Correction 1）：不得因"仓库无证据"就绝对宣称"没有任何数据库曾合法执行过 revision 0025"，须区分 `NO EVIDENCE FOUND` 与 `PROVEN NONE EXIST`。可用证据未识别可信 ≥0025 DB，但 production/staging revision 未正面排除。

因此：**修改 historical migration 0008/0025 在已证明的 DB 范围内不破坏可信数据库**（无可信 DB 穿越 0025）；production/staging 风险记为 `UNKNOWN`。所有已证明的 alembic-tracked PG 要么停在 0016（disposable），要么无 `alembic_version`（legacy，create_all）。

### Historical Migration Modification Risk（Q13）

1. **Alembic 是否使用 migration file checksum？** 否。标准 Alembic 以 `revision`/`down_revision` 标识符 + `alembic_version` 表追踪，**不对 migration 源文件做 hash 校验**。修改 migration 文件不影响"已跑过该 revision 的 DB 的后续 upgrade"（Alembic 不会重跑或校验已应用 revision 的文件）。
2. **项目是否有 migration artifact hash / release evidence？** 无证据显示项目接入 migration 文件完整性插件。本治理阶段（DB-BL-2）正在建立 PG migration baseline，尚无已发布的 migration artifact hash。
3. **修改已执行 migration 是否影响已存在 DB 的后续 upgrade？** 不影响。已停在 0016 的 disposable DB 不会因 0008 文件改动而回退或重跑 0008；它们只是继续从 0016 向 0025 跑（仍会在 0025 失败，除非重建）。
4. **是否影响治理审计和 Git history？** Git history 保留完整（可追溯）。需在本文档 + commit message 记录 `historical migration remediation` 事实。
5. **是否需要文档记录？** 是——本设计文档 + R2 commit message 须明确记录：0008 create_table 移除 file_size_bytes，理由 = 0025 为正典 owner（§2 provenance），0008 预声明为 authoring drift。

### 残留风险（须 R2 审批前确认）

```
EXISTING_ENVIRONMENT_COMPATIBILITY_RISK: LOW_BUT_NOT_GLOBALLY_PROVEN
NO TRUSTED DB > 0025 IDENTIFIED（基于已证明 DB 范围）
production/staging PG revision = UNKNOWN（无 cutover 证据，未正面排除）
```

R2 实施前须由审批窗口确认：已证明 DB 范围内无可信 DB 穿越 0025；production/staging revision = UNKNOWN 的正面确认留待 MR-5 Gate（若无可安全验证的 trusted old-revision fixture → `NOT_APPLICABLE / NO_TRUSTED_FIXTURE`，保留 `UNKNOWN` 风险记录）。若发现存在可信 DB 已 alembic-tracked 至 0008≤r<0025 且须保留，须转 Strategy B 评估（须 type/nullable/default/comment 语义等价校验）。

---

## 6. Strategy Comparison（Q4 / Q10）

| 维度 | Strategy A（恢复 0008 canonical 历史 schema，移除 file_size_bytes） | Strategy B（0025 改 conditional：列存在则跳过/校验） | Strategy C（新建 forward repair revision） |
|---|---|---|---|
| Fresh empty bootstrap | ✅ 0008 建表无此列 → 0025 add → PASS | ✅ 0008 建表含此列 → 0025 见存在跳过 → PASS | ❌ 空 PG 在 0025 即失败，**到不了** repair revision |
| Existing trusted DB compatibility | ✅ 无可信 DB 穿越 0025（§5），无风险 | ✅ 允许停在 0016 的 DB 穿越过去（但均为 disposable） | ❌ 同上 |
| Revision semantics correctness | ✅ 恢复正典时间线：列在 0025 抵达（与 ORM 同提交） | ❌ 0025 变状态依赖，列"何时出现"取决于 0008 是否预声明 | ❌ 不解决根本 |
| Determinism | ✅ 确定性 | ❌ 非确定（依 0008 预声明状态） | ❌ |
| Risk of hiding drift | ✅ 不掩盖（drift 被消除） | ❌ **掩盖 0008 预声明 drift**，未来读者无法从 migration 看出列真正归属 | ❌ |
| Historical auditability | ✅ 与 git provenance 一致（owner=0025） | ❌ 与 git provenance 矛盾（让 0008 预声明"合法化"） | ⚠️ 新增 revision，但根因仍在 |
| Change scope | 最小：0008 删 1 行 | 0025 改逻辑 + 须加 type/nullable/default/comment 等价校验 | 新增 revision + 仍须先解 0025 |
| Rollback feasibility | ✅ downgrade 不受影响（0008 downgrade 无该列依赖；0025 downgrade 仍 drop_column） | ⚠️ conditional downgrade 复杂 | ⚠️ |

### Strategy B 的"exists → skip"安全性评估（即使 B 非首选，仍须回答）

"列名存在即跳过"**单独不足够安全**（`if column exists: skip` 不得视为安全）。须至少验证 canonical semantic equivalence：

- `type`：0025 = `BigInteger`；0008 预声明 = `BigInteger`。✅ 一致
- `nullable`：0025 = `True`；0008 = `True`。✅ 一致
- `default`：0025 无；0008 无。✅ 一致
- `comment`：0025 有（`归档文件大小`）；0008 无。⚠️ 不一致（非阻断，但语义不等价）
- 其他 migration contract 所需属性同理须校验，差异须显式处理（补 comment 或显式接受差异）。

本例 type/nullable/default 一致，故 B 在技术上可安全 skip；但 B 仍因**掩盖 drift + 非确定 + 与 provenance 矛盾**被治理原则否决。

### 结论

```
Strategy A = PREFERRED
Strategy B = CONDITIONAL_FALLBACK（仅当未来因可信中途数据库必须采用 conditional migration 时；
            不得仅 if exists→skip，须至少验证 type/nullable/default/comment 等属性的 canonical semantic equivalence；
            当前无证据需要 B，R2 不得切换到 Strategy B）
Strategy C = REJECTED（空 PG 在 0025 失败，到不了 repair revision；无法解决 bootstrap 路径）
```

---

## 7. Preferred Remediation Design

**推荐 Strategy A — Restore Historical Migration Semantics。**

### 设计

```
0008_xiaogao_phase1_core.py:
  create_table("ai_edit_job_artifacts", ...) 内移除
    sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)   # 第 340 行
  其余列与约束不动。

0025_ai_edit_result_delivery.py: 不动（保留为 file_size_bytes 正典 introducer）。
```

### 理由

1. **git provenance 闭合**（§2）：0025 是 file_size_bytes 的正典 owner（ORM 字段 + add_column + 业务功能同提交 `231808d5`）。0008 的预声明是 authoring drift，非正典。
2. **恢复 canonical 历史时间线**：列在 0025 抵达，与 ORM 历史一致；migration chain 重新成为 schema 演进的可靠记录。
3. **确定性**：不引入状态依赖，不掩盖 drift，与治理原则（ORM-vs-chain drift 是治理对象，非掩盖对象）一致。
4. **环境零风险**（§5）：无可信 DB 曾穿越 0025；legacy 无 alembic_version；disposable 失败 DB 停在 0016 且 disposable。Alembic 不校验 migration 文件 checksum。
5. **最小 diff**：0008 删 1 行。不改 0025，不新建 revision，不 stamp。

### 不选 B/C 的关键

- B 掩盖 0008 预声明 drift，让 migration chain 失去"列何时抵达"的确定性，与 git provenance 矛盾；仅在存在须保留的可信中途 DB 时才考虑（当前无证据）。
- C 无法解决空 PG bootstrap（0025 在 repair revision 之前即失败）。

---

## 8. R2 Implementation Scope（仅定义，不实施）

```
R2 = NOT STARTED / NOT AUTHORIZED（待审批窗口批准本设计后授权）
```

未来 R2 最小实施范围（**仅定义**）：

1. **修改 1 个文件、删 1 行**：
   - `migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py`
   - 移除 `create_table("ai_edit_job_artifacts", ...)` 内第 340 行 `sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)`。
   - 不改任何其他列、约束、seed、index。
2. **不改**：
   - `0025_ai_edit_result_delivery.py`（保留为正典 introducer）
   - 不新建 repair revision
   - 不 stamp
   - 不触碰 legacy / disposable / production / staging 任何 DB
   - 不改 ORM（`app/models.py`）、不改 Consumer、不改 M07 Core
3. **commit message**（中文，记录 historical migration remediation）：
   - 说明 0008 移除 file_size_bytes 的 git provenance 依据（owner=0025，0008 为 authoring 预声明 drift）

---

## 9. R2 Verification Gates

R2 实施后须全部通过（设计预定义，非现在执行）：

```
MR-0  full temporal audit clean
      → python scripts/db_bl_2c_temporal_audit.py
      → CONFIRMED temporal conflicts = 0
      （同时 python scripts/db_bl_2c_chain_audit.py 仍输出 0 duplicate column）

MR-1  empty → 0030 PASS
      → EMPTY PG → alembic upgrade 0030
      → PG_RUNTIME_VERIFIED 成功，revision=0030

MR-2  empty → 0034 PASS
      → EMPTY PG → alembic upgrade head
      → PG_RUNTIME_VERIFIED 成功，revision=0034

MR-3  expected table/schema checkpoints
      → 0030 落点表数/列数与 Expected@0016（54 表/813 列/517 约束/211 索引/20 FK）
        比对方向一致增长（0017–0030 增量表，非减少）
      → 0034 落点包含 0032/0033/0034 新增表

MR-4  existing trusted revision compatibility
      → 确认无 production/staging PG 已 alembic-tracked 至 0008≤r（§5 残留风险）
      → 若存在则转 Strategy B 评估；当前判断：无此类 DB

MR-5  migration chain remains linear / head=0034
      → down_revision 链仍 0001→0034 单链无分叉
      → head=0034，revision 标识符不变

MR-6  file_size_bytes 列在 0034 落点存在且类型正确
      → ai_edit_job_artifacts.file_size_bytes 存在，type=bigint，nullable=YES
      （列由 0025 正典引入，非 0008）
```

> MR-1/MR-2 的 PG_RUNTIME_VERIFIED 是 DB-BL-2C Resume Condition 的直接前置（§10）。

---

## 10. DB-BL-2C Resume Condition

```
只有同时满足：
  empty → 0030  PG_RUNTIME_VERIFIED
  empty → 0034  PG_RUNTIME_VERIFIED
后才能恢复 Exact Reconciliation（2C 复跑 Expected 取数 + Matrix A/B/C + Revision Identity 判定）。
```

恢复回路（`DB_BL_2C_APPROVAL.md` §10 一致）：

```
R2 修复链（删 0008 第 340 行）
→ 重跑 db_bl_2c_chain_audit.py + db_bl_2c_temporal_audit.py（MR-0 全绿）
→ 实跑 alembic upgrade 0030 / head（MR-1/MR-2 全绿）
→ 2C 复跑 Expected@0030 / Expected@0034 取数
→ Matrix A（Legacy Actual vs Expected@0030）/ B（Expected@0030 vs Expected@0034）/ C（Legacy Actual vs Expected@0034）
→ Revision Identity 判定
→ 2B §3 Bootstrap Contract 由 PG_RUNTIME_VERIFIED_FAILURE 升格为 PG_RUNTIME_VERIFIED
```

---

## 11. Implementation Status

```
STATUS:     NOT STARTED
AUTHORIZED: NOT AUTHORIZED（本文件为 DESIGN / AUDIT ONLY，须审批窗口批准后方可进入 R2 实施）
```

本阶段未修改任何 migration 文件、未修改任何数据库 schema、未 stamp、未创建/修改 legacy `alembic_version`、未 legacy upgrade、未 repair migration、未 rebuild legacy DB、未触碰 production/staging、未改 P1 Consumer、未改 M07 Core、未进入 DB-BL-2D、未手工 patch disposable DB。

本阶段产出：

- 本设计报告 `docs/architecture/remediation/DB_BL_2C_R1_MIGRATION_CHAIN_REMEDIATION_DESIGN.md`
- 只读全链 temporal 审计工具 `scripts/db_bl_2c_temporal_audit.py`（remediation verification helper，不自动修改任何 migration）

---

## 附：Provenance 证据索引

| 事实 | 命令 | 结果 |
|---|---|---|
| 0008 引入提交 | `git log --follow --oneline -- 0008_*.py` | `bc00897`（2026-07-10）/ `3143b15`（2026-07-31） |
| 0008 引入时已含 file_size_bytes | `git show bc00897:0008_*.py \| grep file_size_bytes` | 第 340 行命中 |
| 0008 后续修改未触碰该列 | `git show 3143b15 -- 0008_*.py` | 仅 +1 行 seed（ai_edit 能力行） |
| 0025 引入提交 | `git log --follow --oneline -- 0025_*.py` | `231808d`（2026-08-03） |
| 0025 引入时 0008 已含该列 | `git show 231808d:0008_*.py \| sed -n '338,342p'` | 第 340 行已存在 |
| ORM 字段引入提交 = 0025 同提交 | `git blame -L 1645,1655 app/models.py` | `231808d5`（2026-08-03 19:38） |
| 全链 down_revision 线性 | 逐文件 grep revision/down_revision | 0001→0034 单链，0030→0032（缺 0031） |
| 全链 temporal audit | `python scripts/db_bl_2c_temporal_audit.py` | CONFIRMED=1（0025 file_size_bytes），POTENTIAL=1（0004 false positive） |
| 现有 DB revision 证据 | `DB_BL_2C_APPROVAL.md` §0/§9 | legacy 无 alembic_version；disposable 停 0016；无可信 DB 穿越 0025 |

---

设计报告完成。停止于此，提交审批窗口。
