# DB-BL-2C-R1 — Migration Chain Bootstrap Remediation Design 审批报告

> 审批日期：2026-08-10
> 审批窗口：DB-BL-2C-R1 Migration Chain Bootstrap Remediation Design Approval
> 审查对象：`docs/architecture/remediation/DB_BL_2C_R1_MIGRATION_CHAIN_REMEDIATION_DESIGN.md` + `scripts/db_bl_2c_temporal_audit.py`（只读审计工具）
> 前置：`DB_BL_2C_APPROVAL.md`（`APPROVED / BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE`，授权 R1 设计/审计）、`DB_BL_2B_APPROVAL.md`（Schema Authority MODEL A 冻结）、`DB_BL_2A_APPROVAL.md`（2A COMPLETE）
> 审查方法：**独立 git 历史核验（git log --follow / git show / git blame / git log -S）+ 独立只读实跑两个审计脚本 + 独立核验 op.execute 全链 DDL 盲区 + 独立核验 Alembic checksum 现状 + 复核 2C 审批窗口已冻结的 DB 证据**，非复述 R1 报告转述
> 模式：**APPROVAL / AUDIT ONLY** — 本窗口不修改任何 migration、不触数据库、不 stamp、不进入 DB-BL-2D

---

## 0. 审批窗口独立核验记录（先于判定）

审批窗口未接受 R1 转述，独立执行以下只读核验，逐项命中 R1 结论：

| 核验项 | 命令 | 独立结果 | 与 R1 一致 |
|---|---|---|---|
| 0008 提交历史 | `git log --follow -- 0008_*.py` | 仅 2 提交：`bc00897`(07-10 引入) / `3143b15`(07-31) | ✓ |
| 0008 引入即含该列 | `git show bc00897:0008_*.py \| grep file_size_bytes` | 第 340 行 `sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)` 已存在 | ✓ |
| 0008 后续修改未触碰该列 | `git show 3143b15 -- 0008_*.py` | 仅 +1 行 seed（"ai_edit"）+ 注释；未触及 `create_table("ai_edit_job_artifacts")` 列集 | ✓ |
| 0025 提交历史 | `git log --follow -- 0025_*.py` | 仅 1 提交：`231808d`(08-03) | ✓ |
| 0025 在引入提交的父提交不存在 | `git show 231808d~1:0025_*.py` | fatal: not in tree（首次引入确认） | ✓ |
| 0025 add_column 从首次提交即存在 | `git show 231808d -- 0025_*.py \| grep file_size_bytes` | 全为 `+` 新增行（docstring 第 60 行、add_column 第 99 行、downgrade drop 第 109 行） | ✓ |
| ORM 字段引入提交 = 0025 同提交 | `git blame -L 1645,1660 app/models.py` | 行 1651 = `231808d5 (2026-08-03) file_size_bytes = Column(BigInteger, comment="归档文件大小")` | ✓ |
| ORM `-S` 全历史多类区分 | `git log -S file_size_bytes -- app/models.py` | 4 提交命中，但 `AiEditJobArtifact` 那行（comment="归档文件大小"）仅 231808d5；其余为图片记录/素材库/daily report 等不同 ORM 类的无关同名列 | ✓ |
| 0025 docstring 设计意图 | `git show 231808d:0025_*.py \| sed -n '1,30p'` | docstring 明确把 `file_size_bytes` 列为 0025 `ai_edit_job_artifacts` 新增列，与 is_final_video/delivery_status/archive_object_key/archive_error 并列 | ✓ |
| 全链线性 | 逐文件 grep revision/down_revision | 33 revision 单链 0001→0034；0031 编号跳号（0032.down_revision=0030），非分叉；head=0034 唯一 | ✓ |
| temporal audit 输出 | 审批窗口亲自运行 `python scripts/db_bl_2c_temporal_audit.py` | 33 revisions / 356 ops；CONFIRMED=1（0025 file_size_bytes）；POTENTIAL=1（0004 双索引）；tables=60 cols=867 indexes=128 uniques=42 fks=1 checks=33 | ✓ |
| chain audit 输出 | 审批窗口亲自运行 `python scripts/db_bl_2c_chain_audit.py` | duplicate=1（0025 file_size_bytes） | ✓ |
| op.execute 全链 DDL 盲区 | `grep -rni "op.execute.*(ALTER TABLE\|CREATE INDEX\|DROP \|RENAME\|ADD COLUMN)"` | **NONE_FOUND**；全链 21 处 op.execute 均为 DML（INSERT/UPDATE/DELETE） | ✓（见 Correction 2） |
| Alembic checksum 现状 | `grep checksum/hash/verify env.py` | NONE；项目无 migration 文件完整性校验 | ✓ |
| 0004 双索引 false positive | 审批窗口亲读 `0004_*.py:89-109` | `idx_..._merchant_account`=全表普通索引无 WHERE；`uk_..._active_default`=partial index 带 `postgresql_where=status='active' AND is_default IS TRUE AND deleted_at IS NULL`；不同名不同谓词，PG 合法共存 | ✓ |
| 现有 DB 证据 | 复核 `DB_BL_2C_APPROVAL.md` §0/§9（审批窗口此前独立只读复核） | legacy 无 alembic_version（5 行无 PII，DISPOSABLE）；disposable 停 0016；prod/staging UNKNOWN | ✓（见 Correction 1） |

> 审批窗口全程未对任何 migration 文件、任何数据库执行写入、stamp、upgrade、repair。两个审计脚本为只读静态解析（AST，不连库、不改文件），本窗口仅运行核验。

---

## 1. Technical Decision

```
APPROVED_WITH_CORRECTIONS
```

R1 的 provenance 闭合、全链 temporal audit、Strategy A 设计三者的**核心论证成立**，可冻结为正式 remediation direction 并授权 R2 实施。

不判 `APPROVED`（裸批）的原因：R1 存在 3 处表述瑕疵，虽不影响核心论证与授权结论，但须在 R2 实施前修正，避免下游窗口误读：

- **Correction 1（表述过强 / 环境兼容性）**：§5 主体"关键事实"框断言"没有任何数据库曾合法执行过 revision 0025 的 alembic upgrade"——这是 over-strong absolute claim。production/staging revision = `UNKNOWN`（无 cutover 证据，但未正面排除）。审批窗口纪律要求区分"NO EVIDENCE FOUND"与"PROVEN NONE EXIST"。R1 §5 残留风险段已给出正确口径，但主体框与残留风险框存在内部张力。须统一为 `EXISTING_ENVIRONMENT_COMPATIBILITY_RISK: LOW_BUT_NOT_GLOBALLY_PROVEN`。
- **Correction 2（op.execute 表述不完整）**：§4 称 op.execute"全部为 UPDATE/DELETE"——实际还有 INSERT（seed 回填，如 0008 compute seed、0023 INSERT）。不影响 temporal audit 完整性结论（INSERT/UPDATE/DELETE 均为 DML，不修改 schema DDL，不产生 schema 累积状态变化），但表述须修正为"全部为 DML（INSERT/UPDATE/DELETE），无 schema DDL"。
- **Correction 3（Strategy B 等级）**：§6 标 B = `ACCEPTABLE_FALLBACK`。审批窗口要求至少 `CONDITIONAL_FALLBACK`——`exists → skip` 单独不安全（须 type/nullable/default/comment 全等价校验；R1 自检已发现 comment 不一致：0025 有"归档文件大小"，0008 预声明无 comment）。当前无证据需要 B，保留为 conditional fallback 合理，但等级须明确，且 R2 不得在未经审批转 B 前擅自把 0025 改 conditional。

不判 `CHANGES_REQUIRED`：上述 3 处均为表述层修正，historical ownership 与 Strategy A 的核心论证（git 事实）未被证伪，R2 实施不受阻。

---

## 2. Historical Ownership Verdict

```
file_size_bytes
HISTORICAL_SCHEMA_OWNER = 0025
EVIDENCE                = GIT_HISTORY_VERIFIED
```

审批窗口独立 git 核验（非 AMBIGUOUS，证据可可靠证明）：

1. **0025 是正典 introducer**：ORM 字段（`git blame` 行 1651 = `231808d5`）、migration `add_column`（0025 第 59 行，从 `231808d` 首次提交即 `+` 新增）、结果交付业务功能（docstring 明确列为 `ai_edit_job_artifacts` 新增列）三者在同一提交 `231808d5` 抵达，构成完整 feature 单元。`git show 231808d~1:0025_*.py` 确认 0025 在该提交首次进入仓库。
2. **0008 是无 ORM/功能支撑的预声明**：0008 引入时（07-10 `bc00897`）ORM 尚无该字段（08-03 才有）。0008 在 `create_table("ai_edit_job_artifacts")` DDL 中提前声明了一列当时无 ORM 映射、无业务功能消费的列。
3. **0008 预声明是"出生即含"，非后续回填**：0008 唯一后续提交 `3143b15`（07-31）经 diff 核验仅 +1 行 seed（"ai_edit"）+ 注释，未触及列集。
4. **预声明的不一致性印证 authoring slip**：0025 给 artifacts 表加的 5 列中只有 `file_size_bytes` 被提前预声明进 0008，其余 4 列正确等到 0025。单个游离列 = 作者时疏漏，非"0008 拥有全部交付列"的刻意设计。
5. **ORM `-S` 多类区分**：`git log -S file_size_bytes -- app/models.py` 命中 4 个更早提交，但经审批窗口逐提交核验上下文，均为其他 ORM 类（图片记录/素材库/daily report）的无关同名列（comment 不同："文件大小（字节）"/"文件字节数"），不影响 `AiEditJobArtifact` 的 owner 判定。

### 术语裁定（应 R1 §五要求）

事实确认：0008 从第一次提交起就含 `file_size_bytes`。故审批窗口不使用"0008 later backfilled file_size_bytes"（已被 R1 证伪）。准确术语：

```
0008 缺陷性质 = ORIGINAL_AUTHORING_TEMPORAL_DRIFT
                (= PREDECLARED_FUTURE_SCHEMA)
```

> 核心含义：0008 在其诞生时就错误包含了未来 0025 才正式拥有的 schema change。既非"legitimate fix"也非"historical backfill/mutation"，是 authoring-time forward declaration（出生即含，从未被后续修改）。

---

## 3. Temporal Drift Verdict

```
TEMPORAL_AUDIT: STATIC_AUDIT_VERIFIED（保守下界，盲区已独立确认对本链不产生遗漏）
```

| 类别 | 计数 | 明细 | evidence level |
|---|---|---|---|
| CONFIRMED_TEMPORAL_CONFLICT | **1** | `[0025]` `ai_edit_job_artifacts.file_size_bytes` DuplicateColumn（create-vs-add，runtime 已印证） | CODE_VERIFIED + PG_RUNTIME_VERIFIED_FAILURE |
| POTENTIAL_CONFLICT | 1 | `[0004]` `douyin_account_agent_bindings(merchant_id, account_open_id)` 双索引 | — |
| FALSE_POSITIVE | 1 | 上项（审批窗口亲读 0004:89-109 确认） | — |
| 其他类别（index/unique/FK/CHECK/rename/alter/drop）CONFIRMED | 0 | — | — |

### 工具覆盖与盲区评估（应审批窗口 §七要求）

1. **完整 revision chain 覆盖**：✓ 工具按 down_revision 拓扑排序遍历全部 33 revision，链输出 `0001→…→0034` 与人工 grep 一致（0031 编号跳号非分叉）。
2. **op.execute raw DDL 漏检风险**：工具不解析 `op.execute()` 内原生 SQL。审批窗口独立核验：全链 21 处 `op.execute`，`grep` 原生 DDL 关键词（ALTER TABLE / CREATE INDEX / DROP / RENAME / ADD COLUMN）= **NONE_FOUND**。实际全为 DML（INSERT seed / UPDATE 回填 / DELETE 清理），不产生 schema 累积状态变化。**故该盲区对本链不产生实际遗漏**（保守下界 = 实际下界）。
3. **AST 解析可靠性**：工具只取字面量字符串列名/约束名；动态构造（`<expr>`）会被跳过不纳入比较。本链检测到的 CONFIRMED conflict（file_size_bytes）与 POTENTIAL（0004 双索引）均为字面量，解析可靠。动态列名在本链未被 op.execute 用于 schema DDL（见上），故不产生未检测 conflict。
4. **FALSE_POSITIVE 判定合理性**：审批窗口亲读 0004 源文件确认——`idx_dy_account_agent_bindings_merchant_account`（行 89-93，全表普通 btree 索引，无 WHERE 谓词）与 `uk_dy_account_agent_bindings_active_default`（行 104-109，partial index，`postgresql_where = status='active' AND is_default IS TRUE AND deleted_at IS NULL`）。两者不同名、不同 WHERE 谓词、不同 unique 语义，PostgreSQL 下为两个独立合法共存对象。工具仅比较列元组、忽略 `postgresql_where` 与 `unique` 标志 → 误报为 POTENTIAL。**FALSE_POSITIVE 判定合理，无需修复。**

> 修复 0025 后，链中无下一个 conflict 顶上来（其他类别 CONFIRMED=0）。审批窗口不因脚本输出"1 处"就绝对宣称全链零问题，但独立盲区核验确认：对本链，保守下界即实际下界。

---

## 4. Existing Environment Risk

审批窗口严格区分"已证明的事实"与"未证明但未发现证据的环境风险"：

### 已证明的事实（来源：2C 审批窗口此前独立只读复核，`READ_ONLY_PG_VERIFIED`）

| 数据库 | alembic_version | 建表方式 | 是否穿越 0025 | 处置 |
|---|---|---|---|---|
| legacy dev PG（5432 / `auto_wechat`） | `alembic_version` 表不存在（count=0） | `create_all`（57 表残骸） | 从未 alembic upgrade | DISPOSABLE（5 行 compute_* seed，无 PII） |
| disposable 失败 DB `db_bl_2c_expected_0030`（5433） | `0016` | fresh alembic upgrade | 跑到 0016，**0025 失败** | disposable 测试产物 |
| disposable 失败 DB `db_bl_2c_expected_0034`（5433） | `0016` | fresh alembic upgrade | 跑到 0016，**0025 失败** | disposable 测试产物 |

### 未证明但未发现证据的环境风险

```
production / staging PG revision = UNKNOWN
  - 无 cutover 证据（P1 checkpoint 显示 PG 迁移多 PENDING / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT）
  - 但未正面排除（仓库无证据 ≠ 生产环境从未运行过 0025）
```

### 裁定（应审批窗口 §八要求）

R1 §5 主体框"没有任何数据库曾合法执行过 revision 0025"为 over-strong absolute claim。审批窗口不因其降格整体结论，但要求 R1 / R2 文档统一采用：

```
EXISTING_ENVIRONMENT_COMPATIBILITY_RISK: LOW_BUT_NOT_GLOBALLY_PROVEN
NO TRUSTED DB > 0025 IDENTIFIED
```

不得因仓库无证据就绝对宣称生产环境从未运行过 0025。MR-4 Gate 保留 production/staging UNKNOWN 的正面确认要求（见 §7）。

### Alembic Historical Migration Mutation 风险（应审批窗口 §九要求）

独立确认：

1. **Alembic 是否校验 migration file checksum？** 否。审批窗口核验 `migrations/postgres/auto_wechat/env.py` 无 checksum/hash/verify 注入。标准 Alembic 以 `revision`/`down_revision` 标识符 + `alembic_version` 表追踪，不对 migration 源文件做 hash 校验。修改 migration 文件不影响"已跑过该 revision 的 DB 的后续 upgrade"（Alembic 不会重跑或校验已应用 revision 的文件）。
2. **项目是否有 migration hash/checksum gate？** 无证据显示项目接入 migration 文件完整性插件。本治理阶段（DB-BL-2）正在建立 PG migration baseline，尚无已发布 migration artifact hash。
3. **修改已执行 migration 是否影响已存在 DB 的后续 upgrade？** 不影响。已停在 0016 的 disposable DB 不会因 0008 文件改动而回退或重跑 0008；它们只是继续从 0016 向 0025 跑。
4. **对审计证据的影响**：Git history 保留完整（可追溯）。须在 R2 commit message 记录 historical migration remediation 事实。

**治理定性**：虽 Alembic 无 checksum，但修改 0008 仍属历史迁移修改，非普通 feature patch。须明确记录为：

```
HISTORICAL_MIGRATION_REMEDIATION
  target: 0008_xiaogao_phase1_core.py（移除 PREDECLARED_FUTURE_SCHEMA）
  reason: 0025 为 file_size_bytes 正典 owner（GIT_HISTORY_VERIFIED）
  classification: authoring-time forward declaration 消除，非 backfill/mutation
```

---

## 5. Strategy Decision

### Strategy A — Restore Historical Canonical Ownership

```
APPROVED
```

R1 推荐设计（0008 移除 file_size_bytes，0025 不动）经审批窗口逐项判定：

| 判定维度 | 结果 |
|---|---|
| 与 git provenance 一致 | ✓ owner=0025，0008 预声明为 authoring drift |
| 恢复 deterministic migration timeline | ✓ 列在 0025 抵达，与 ORM 历史一致 |
| 不掩盖 schema drift | ✓ drift 被消除（非合法化） |
| 解决 empty bootstrap 0025 DuplicateColumn | ✓ 0008 建表不含该列 → 0025 add_column 不冲突 |
| 对已有合法 revision DB 风险可接受 | ✓ LOW_BUT_NOT_GLOBALLY_PROVEN（无可信 DB 穿越 0025；见 §4） |
| scope 足够小 | ✓ 0008 删 1 行，不改 0025 / 不新建 revision / 不 stamp |

> 冻结：`file_size_bytes` Historical Schema Owner = 0025，0008 应恢复到不预声明该列的历史时间线。此为 `REMEDIATION DESIGN APPROVED`，**非 `MIGRATION CHANGE EXECUTED`**——R2 实施前不得改任何文件。

### Strategy B — 0025 conditional（exists → verify → skip）

```
CONDITIONAL_FALLBACK
```

审批窗口将 R1 的 `ACCEPTABLE_FALLBACK` 升格为更严格的 `CONDITIONAL_FALLBACK`：

- 单纯 `if exists: skip` **不得视为安全**。R1 自检已发现语义不等价：0025 `comment="归档文件大小"`，0008 预声明无 comment（type=BigInteger / nullable=True / default 无 均一致，仅 comment 不一致）。
- 若未来发现必须兼容已带预声明列的可信中途 DB，转 B 前须保证 `type`/`nullable`/`default`/`comment` 与 canonical 0025 target 全等价，差异须显式处理（补 comment 或显式接受差异）。
- **当前无证据需要 B**（无可信 DB 停在 0008≤r<0025 且须保留）。保留为 conditional fallback，R2 不得在未经审批转 B 前擅自把 0025 改 conditional。

### Strategy C — New forward repair revision

```
REJECTED
```

独立确认：empty PG 在 0025 即失败，**到不了** repair revision（repair revision 必然位于 0025 之后）。新建 repair revision 无法解决 bootstrap 路径断裂。REJECTED 成立。

### Preferred Strategy Verdict 汇总

```
Strategy A: APPROVED
Strategy B: CONDITIONAL_FALLBACK（当前不启用，R2 不得擅自转 B）
Strategy C: REJECTED
```

---

## 6. R2 Scope（冻结最小实施范围）

若 R2 获授权（见 §9），严格限制为：

```
1. 修改 1 个文件、删 1 行：
   - migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py
   - 移除 create_table("ai_edit_job_artifacts", ...) 内第 340 行
     sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)
   - 不改任何其他列、约束、seed、index

2. 不修改 0025_ai_edit_result_delivery.py（保留为正典 introducer）

3. 不新建 repair revision

4. 不 stamp（任何 revision，legacy / disposable / prod / staging）

5. 不修改 legacy dev PG（5432 READ-ONLY / UNTOUCHED）

6. 不修改 P1 consumer / M07 Core（record_usage / 0030 / 原子所有权 / IntegrityError replay）

7. 不修改 ORM（app/models.py）—— AiEditJobArtifact.file_size_bytes 字段保留不动
```

**审计脚本调整**：仅允许对 `scripts/db_bl_2c_temporal_audit.py` / `db_bl_2c_chain_audit.py` 做 verification helper 的最小改动（如 MR-0 输出格式校准），不得扩大其语义、不得使其自动修改任何 migration 文件。

**commit message 要求**（中文，记录 historical migration remediation）：
- 说明 0008 移除 file_size_bytes 的 git provenance 依据（owner=0025，0008 为 `ORIGINAL_AUTHORING_TEMPORAL_DRIFT` / `PREDECLARED_FUTURE_SCHEMA`，非 backfill）。

---

## 7. R2 Verification Gates

R2 实施后须全部通过（设计预定义，非现在执行）：

```
MR-0  full temporal audit clean
      → python scripts/db_bl_2c_temporal_audit.py
      → CONFIRMED temporal conflicts = 0
      → python scripts/db_bl_2c_chain_audit.py 输出 0 duplicate column
      （POTENTIAL 1 的 0004 false positive 保持，不计入 confirmed）

MR-1  empty → 0030 PASS
      → 独立 disposable PostgreSQL（EMPTY PG）
      → alembic upgrade 0030
      → PG_RUNTIME_VERIFIED 成功，alembic current = 0030

MR-2  empty → 0034 PASS
      → 另一独立 disposable PostgreSQL（EMPTY PG）
      → alembic upgrade head
      → PG_RUNTIME_VERIFIED 成功，alembic current = 0034

MR-3  file_size_bytes Timeline
      → at revision before 0025：file_size_bytes = ABSENT
      → at revision 0025+：file_size_bytes = PRESENT
      → 最终 type = BIGINT（migration 0025 定义的精确 canonical type）
      → 列由 0025 正典引入，非 0008

MR-4  Expected Schema Checkpoints
      → 0030 落点表数/列数与 Expected@0016（54 表/813 列/517 约束/211 索引/20 FK）
        比对方向一致增长（0017–0030 增量表，非减少）
      → 0034 落点包含 0032/0033/0034 新增表
      → 不得仅以 "alembic current=head" 判断成功

MR-5  Existing Trusted Revision Compatibility
      → 确认无 production/staging PG 已 alembic-tracked 至 0008≤r（§4 UNKNOWN 风险的正面确认）
      → 若发现存在此类 DB，转 Strategy B 评估（须语义等价校验，见 §5 B）
      → 若不存在可安全使用的可证明 trusted old-revision DB：
        NOT_APPLICABLE / NO_TRUSTED_FIXTURE
      → 不得伪造 production evidence

MR-6  Revision Chain Integrity
      → down_revision 链仍 0001→0034 单链无分叉（0031 编号跳号保持，非缺陷）
      → head = 0034
      → revision 标识符不变，revision graph 未因修复改变
```

> MR-1 / MR-2 的 PG_RUNTIME_VERIFIED 是 DB-BL-2C Resume Condition 的直接前置（§8）。

---

## 8. Resume Condition（何时允许恢复 DB-BL-2C）

```
DB-BL-2C 只有在同时满足：
  empty → 0030  PG_RUNTIME_VERIFIED PASS
  empty → 0034  PG_RUNTIME_VERIFIED PASS
（即 MR-0 ~ MR-6 全绿）
后才恢复。
```

恢复回路（与 `DB_BL_2C_APPROVAL.md` §10 一致）：

```
R2 修复链（删 0008 第 340 行）
→ 重跑 db_bl_2c_chain_audit.py + db_bl_2c_temporal_audit.py（MR-0 全绿）
→ 实跑 alembic upgrade 0030 / head（MR-1 / MR-2 全绿）
→ 2C 复跑 Expected@0030 / Expected@0034 取数
→ Matrix A（Legacy Actual vs Expected@0030）
   / B（Expected@0030 vs Expected@0034）
   / C（Legacy Actual vs Expected@0034）
→ Revision Identity 判定
→ 2B §3 Bootstrap Contract 由 PG_RUNTIME_VERIFIED_FAILURE 升格为 PG_RUNTIME_VERIFIED
```

**不得因 R2 单元测试通过就直接进入 DB-BL-2D**——必须先完成 2C 复跑（Expected 取数 + Matrix A/B/C + Revision Identity 判定）。

---

## 9. Explicitly Forbidden

即使本审批报告批准 R2，在 R1 审批窗口本身及 R2 实施窗口未获对应独立审批前，以下行为仍明确禁止：

- **NO HISTORICAL MIGRATION EDIT IN R1** — 本 R1 审批窗口不修改 0008 / 0025 或任何 migration 文件（R1 = 设计/审计 only）。
- **NO STAMP** — 任何 revision，legacy / disposable / production / staging；不得创建/修改任何 `alembic_version`。
- **NO LEGACY UPGRADE / REBUILD** — legacy 5432 / `auto_wechat` 保持 READ-ONLY / UNTOUCHED；不执行 alembic upgrade / downgrade / DROP / recreate（DISPOSABLE 仅纳 2D 候选，不授权本阶段销毁）。
- **NO PROD / STAGING** — 任何操作不得触碰 production / staging。
- **NO DB-BL-2D** — 2D 在 2C 复跑完成（Matrix A/B/C 产出 + Revision Identity 判定）前不得进入。
- **NO P1 CONSUMER / M07 CORE MODIFICATION** — R2 不得修改 P1 consumer（11/11 charge path）或 M07 Core（record_usage / 0030 / 原子所有权 / IntegrityError replay）。
- **NO STRATEGY B SWITCH** — R2 不得在未经审批转 B 前擅自把 0025 改 conditional。

---

## 10. R2 授权裁定

基于本审批报告：

- Historical Ownership = `VERIFIED`（0025，`GIT_HISTORY_VERIFIED`）
- Temporal Drift = `STATIC_AUDIT_VERIFIED`（1 confirmed，1 false positive，盲区已确认对本链无遗漏）
- Existing Environment Risk = `LOW_BUT_NOT_GLOBALLY_PROVEN`（无可信 DB 穿越 0025，prod/staging UNKNOWN）
- Strategy A = `APPROVED`，B = `CONDITIONAL_FALLBACK`（不启用），C = `REJECTED`

审批窗口授权：

```
DB-BL-2C-R2
Migration Chain Bootstrap Remediation Implementation

STATUS:     AUTHORIZED
SCOPE:      MIGRATION CHAIN ONLY
            （仅 0008 删 1 行 file_size_bytes；不改 0025 / 不新建 revision / 不 stamp）
```

**重申约束**：

```
MIGRATION CHAIN ONLY
- legacy dev PG（5432）= READ-ONLY / UNTOUCHED
- R2 不得顺便进入 Exact Reconciliation（2C 复跑须 R2 完成后独立窗口执行）
- R2 须满足 MR-0 ~ MR-6 全绿后才能触发 2C Resume Condition
- R2 实施前须先落实 §1 的 3 处 Correction（文档表述修正）
```

---

## 附：审批状态汇总

| 维度 | 判定 |
|---|---|
| Technical Decision | `APPROVED_WITH_CORRECTIONS` |
| Historical Ownership | `VERIFIED` — owner=0025，evidence=`GIT_HISTORY_VERIFIED` |
| 0008 缺陷性质 | `ORIGINAL_AUTHORING_TEMPORAL_DRIFT`（=`PREDECLARED_FUTURE_SCHEMA`，非 backfill） |
| Temporal Drift | 1 confirmed（0025 file_size_bytes）/ 1 false positive（0004 双索引）/ 0 其他；`STATIC_AUDIT_VERIFIED`（盲区已确认无遗漏） |
| Existing Environment Risk | `LOW_BUT_NOT_GLOBALLY_PROVEN`（无可信 DB 穿越 0025；prod/staging UNKNOWN） |
| Alembic checksum | 无（env.py 无校验注入）；修改定性为 `HISTORICAL_MIGRATION_REMEDIATION` |
| Strategy A | `APPROVED` |
| Strategy B | `CONDITIONAL_FALLBACK`（当前不启用，转 B 须语义等价校验 + 审批） |
| Strategy C | `REJECTED` |
| R2 Scope | 0008 删 1 行；不改 0025 / 不新建 revision / 不 stamp / 不改 ORM / 不改 P1 consumer / 不改 M07 Core |
| R2 Gates | MR-0 ~ MR-6（见 §7） |
| Resume Condition | empty→0030 AND empty→0034 `PG_RUNTIME_VERIFIED PASS` 后恢复 DB-BL-2C |
| Legacy PG | `READ-ONLY / UNTOUCHED` |
| DB-BL-2D | 本阶段禁止进入 |

审批报告完成。停止于此，不修改任何 migration，不触数据库，不进入 DB-BL-2D。
