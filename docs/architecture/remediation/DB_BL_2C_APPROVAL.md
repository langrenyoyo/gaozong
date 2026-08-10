# DB-BL-2C — Exact Reconciliation 审批报告

> 审批日期：2026-08-10
> 审批窗口：DB-BL-2C Exact Reconciliation Approval
> 审查对象：`docs/architecture/remediation/DB_BL_2C_EXACT_RECONCILIATION.md` + `scripts/db_bl_2c_chain_audit.py`
> 前置：`DB_BL_2A_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS` → 2A `COMPLETE / FROZEN`）、`DB_BL_2B_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS` → 2C 合同冻结）
> 审查方法：**独立读取 migration 源文件 + 独立只读实跑审计脚本 + 独立只读核验 disposable/legacy PG runtime 证据**，非复述探索窗口摘要
> 模式：**APPROVAL / AUDIT ONLY**（不实施任何数据库修复、不设计 migration 修复、不进入 R1）

---

## 0. 审批窗口独立核验记录（先于判定）

审批窗口未接受报告转述，独立执行以下只读核验，全部命中报告结论：

| 核验项 | 方法 | 结果 |
|---|---|---|
| 静态审计"全链 create-vs-add 重复 = 1 处" | 审批窗口亲自运行 `python scripts/db_bl_2c_chain_audit.py` | 33 revision 线性链 0001→0034；重复列 1 处：`0025 / ai_edit_job_artifacts.file_size_bytes` ✓ |
| `0008` create_table 含 `file_size_bytes` | 审批窗口亲读 `0008_xiaogao_phase1_core.py:340` | `sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)` 在 `create_table("ai_edit_job_artifacts")` 内 ✓ |
| `0025` add_column 同列 | 审批窗口亲读 `0025_ai_edit_result_delivery.py:59` | `op.add_column("ai_edit_job_artifacts", sa.Column("file_size_bytes", ..., comment="归档文件大小"))` ✓ |
| Expected@0030 失败 DB 保留状态 | 审批窗口只读查询 disposable `db_bl_2c_expected_0030`（5433） | `alembic_version=0016`、`ai_edit_job_artifacts.file_size_bytes` 已存在（bigint）、业务表 54 ✓ |
| Expected@0034 失败 DB 保留状态 | 审批窗口只读查询 disposable `db_bl_2c_expected_0034`（5433） | `alembic_version=0016`、业务表 54 ✓ |
| legacy 只读合规与数据可处置性 | 审批窗口只读查询 legacy `auto_wechat`（5432，`SET default_transaction_read_only=on`） | `alembic_version` 表不存在、业务表 57、compute_* 共 5 行、PII 表全 0、`daily_report_jobs.current_generation_id` 缺失 ✓ |
| disposable / legacy 隔离 | 容器/端口/卷/库名核验 | disposable=`db-bl-2c-expected-pg`/5433/`db_bl_2c_expected_*`/`db_bl_2c_expected_data`；legacy=`auto-wechat-postgres-dev`/5432/`auto_wechat`/`auto_wechat_postgres_data` —— 物理隔离 ✓ |

> 审批窗口全程未对任何 DB 执行写入、stamp、upgrade、repair。两次 alembic 失败证据为探索窗口此前在 disposable 5433 产生并保留，审批窗口仅只读复核。

---

## 1. Technical Decision

```
APPROVED / BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE
```

探索窗口执行正确、证据可信、只读边界严守。Exact Reconciliation 因 migration chain 自身存在阻断性 runtime 缺陷（非环境阻断）无法按 2C 合同完成。

正式状态：

```
DB-BL-2C = BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE
           (environment reachable; chain defect at 0025 blocks Expected schema generation)
```

**不判 `CHANGES_REQUIRED`**：报告如实提交了一个真实、可独立复现的 runtime 失败，未用静态推断替代 runtime reconciliation，未越权修复。把"正确发现真实失败"误判为返工，会逼迫下一窗口伪造 Expected 数据。阻断来自链本身，不来自探索质量。

---

## 2. Runtime Bootstrap Verdict

| 路径 | 结果 | 失败 revision | 失败点 | 证据等级 |
|---|---|---|---|---|
| Expected@0030（空 PG → `alembic upgrade 0030`） | **FAIL** | 0025 | `0025_ai_edit_result_delivery.py:59` → `DuplicateColumn ai_edit_job_artifacts.file_size_bytes` | `PG_RUNTIME_VERIFIED_FAILURE`（审批窗口独立只读复核失败 DB 保留状态） |
| Expected@0034（空 PG → `alembic upgrade head`） | **FAIL** | 0025 | 同点 | `PG_RUNTIME_VERIFIED_FAILURE` |

两条路径均在 revision 0025 同点失败，失败后 DB 停在 `alembic_version=0016` / 业务表 54（0001–0016 事务内已提交，0017–0025 外层事务回滚）。审批窗口独立查询两个失败 DB，`alembic_version` 与表数均印证。

失败列确为 `ai_edit_job_artifacts.file_size_bytes`，失败 SQL 为 `ALTER TABLE ai_edit_job_artifacts ADD COLUMN file_size_bytes BIGINT`。审批窗口独立确认：失败 DB 在 revision 0016 时该列已由 0008 建表创建并存在 → 0025 add_column 命中已存在列 → `DuplicateColumn`。前因-后果链 runtime 闭合。

> 证据等级为 `PG_RUNTIME_VERIFIED_FAILURE`（真实空 PG 实跑 + 审批窗口独立复核保留状态），非仅 `CODE_VERIFIED`。失败 DB（disposable 5433）保留运行，供后续核验。

---

## 3. Migration Defect

```
DUPLICATE_COLUMN_CHAIN_DEFECT = CODE_VERIFIED
table:   ai_edit_job_artifacts
column:  file_size_bytes
```

**当前文件事实（审批窗口亲读，CODE 级）**：

| 位置 | 操作 | 行为 |
|---|---|---|
| `0008_xiaogao_phase1_core.py:340` | `create_table("ai_edit_job_artifacts", ...)` 内 `sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)` | 建表时即创建该列 |
| `0025_ai_edit_result_delivery.py:59` | `op.add_column("ai_edit_job_artifacts", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True, comment="归档文件大小"))` | 重复添加同列 |

空库自举路径：0008 建表已含 `file_size_bytes` → 0025 add_column 触发 `DuplicateColumn`。审计脚本静态扫描全链 33 个 revision，create-vs-add 重复列仅此 1 处（保守下界，不覆盖 `op.execute(raw SQL ALTER)` / 重复 index / 重复 FK / 动态列名）。

**Provenance 区分（审批窗口纪律）**：

- 审批窗口**只确认当前文件冲突事实**，不自动推断历史成因。
- `0025` 文件头 docstring（第 15–20 行）把 `file_size_bytes` 列为 0025 要新增的列——这是"0025 是该列的 intended introducer"的**信号**，指向"0008 被后续回填为当前 ORM 全列集"的假设，但**不是历史证明**。
- **审批窗口不采信"0008 一定是后来被错误修改的"这一推断**。`file_size_bytes` 的历史 schema provenance、0008 / 0025 哪个偏离原始 migration intent、0008 是否曾在后续被回填——这些必须由 R1 阶段通过 git history / git blame / migration introduction commits / historical docs 已有环境 revision evidence 查清。
- 当前只知道：**current migration files conflict**；尚不知道：**historical canonical migration intent**。

---

## 4. Previous Evidence Correction

### 4.1 DB-BL-2A 静态证据——分层更新，不全推翻

| 2A 冻结项 | 本轮 runtime 证据影响 | 更新后状态 |
|---|---|---|
| revision 线性、无分支、链结构完整 | 审批窗口重跑审计：33 revision 线性 0001→0034 | **保持 `STATIC_CHAIN_VERIFIED`（表集合 / revision topology）** |
| 表集合覆盖（60 表、无链外表引用） | 表级结构仍然成立 | **保持 `STATIC_CHAIN_VERIFIED`（表级）** |
| 列级自举正确性 | runtime 证伪：空库 upgrade 在 0025 DuplicateColumn | **新增 `PG_RUNTIME_VERIFIED_FAILURE`（runtime bootstrap conformance）**；2A 显式声明的 `column_level_reconciliation = NOT_DONE` 在此印证 |
| `STATIC_CHAIN_VERIFIED` + `PROJECTED` 的"链可空库自举"能力 | runtime 证伪 | **projected bootstrap 结论被 supersede**；静态完整 ≠ runtime 可顺序执行 |

> 审批窗口纪律：不得把 2A 的静态结论全部推翻，也不得继续写"空库自举能力已验证成立"。分层标签的意义正在于此——表集合/拓扑静态完整，不代表 migration operation timeline 可顺序执行。

### 4.2 DB-BL-2B 设计结论——目标成立，实现不符

| 2B 冻结项 | 本轮影响 | 结论 |
|---|---|---|
| Schema Authority = Model A | 链缺陷不改变所有权模型；反证 ORM-vs-chain drift 真实存在，以 ORM 为 target 会掩盖缺陷 | **成立** |
| 0030 = Historical Anchor Candidate | 0032.down_revision=0030 仍成立；anchor 判定延后至链修复 + 2C 复跑 | **选型不推翻，判定延后** |
| Bootstrap Contract（空 PG → upgrade head）作为目标 | 目标正确；当前链实现无法达成 | **目标成立，实现不符**（见 §5） |
| target 基于 Alembic expected schema（非 ORM） | 链缺陷反证设计原则 | **成立** |

---

## 5. Bootstrap Contract Status

审批窗口区分两层，不因链缺陷而混淆：

```
TARGET CONTRACT（DB-BL-2B 冻结）:
    EMPTY PG → alembic upgrade head → /ready → traffic
    Schema Authority = Model A
    STATUS: APPROVED / FROZEN  （目标不因实现缺陷重选）

CURRENT MIGRATION CHAIN CONFORMANCE:
    EMPTY PG → alembic upgrade head = FAIL @ 0025
    STATUS: FAIL
```

**审批窗口纪律**：

- 不得因 Alembic 链存在缺陷，就自动重新选择 `create_all + stamp` 作为正式 PostgreSQL bootstrap 模型。`create_all + stamp` 正是 legacy dev PG 57 表残骸的根因（2B §2 已冻结），是治理对象，不是回退方案。
- 目标契约（Model A / 空 PG upgrade head）保持冻结；变的是"当前链实现需先修复才能符合该契约"。

---

## 6. Matrix Status

Expected@0030 / Expected@0034 因 0025 bootstrap 失败均不可生成（审批窗口独立复核失败 DB 停在 0016）。按 2C 合同不得以 ORM metadata 或静态推断替代 expected schema。

| Matrix | 比较 | 状态 | 原因 |
|---|---|---|---|
| A | Legacy Actual vs Expected@0030 | **BLOCKED** | Expected@0030 不可得 |
| B | Expected@0030 vs Expected@0034 | **BLOCKED** | 两份 Expected 均不可得 |
| C | Legacy Actual vs Expected@0034 | **BLOCKED** | Expected@0034 不可得 |

已有**非 contracted** 替代证据（仅供审批参考，不替代矩阵）：

- Legacy Actual：57 表 / 无 `alembic_version` / 缺 0032-0034 表 / 缺 `daily_report_jobs.current_generation_id`（审批窗口独立只读复核）。
- Expected@0016 检查点：54 表 / 813 列 / 517 约束 / 211 索引 / 20 FK（最近一次干净 runtime 落点，角色见 §9）。
- drift 信号：legacy（≈0030-era create_all 快照）约束/索引/FK 反而少于 Expected@0016（439<517、172<211、18<20），印证 ORM-vs-chain drift 真实存在。

---

## 7. Revision Identity

```
UNVERIFIED_DUE_TO_MIGRATION_CHAIN_BOOTSTRAP_FAILURE
```

判定理由（审批窗口确认）：

- 回答"legacy dev PG 是否精确等价于合法 revision 0030"**必须**依赖 `Expected@0030`（2B §6 target 基于 Alembic expected，非 ORM；对账前禁止倒推）。
- `Expected@0030` 不可得 → Matrix A 无法产出 → **无法判定**等价与否。
- verdict 区别于 `UNVERIFIED_DUE_TO_ENVIRONMENT`：环境已恢复可达（审批窗口确认 legacy 5432 与 disposable 5433 均 Up），阻断来自链自身。

**严禁反向推断 `legacy == 0030`**：

- 不得以"legacy 57 表 == 链 0030-era 57 表"倒推。
- 不得以"legacy 缺 0032/33/34 → 推断 legacy 停在 0030"。
- 不得以"Expected@0016 54 表 + legacy 57 表 + 缺 3 表 = 57"外推 legacy == 0030。
- 表级相等不蕴含列级/约束级/索引级相等（2A 已登记列级未对账；§4.2 drift 信号已见约束/索引 drift）。0016 ≠ 0030，0017–0030 段 runtime 尚未被验证（0025 即阻断）。

---

## 8. Stamp Eligibility

```
STAMP_0030 = UNVERIFIED
```

- Stamp 门禁（2B §6.5）：仅当 Matrix A 证明 `Legacy Actual == Expected@0030`（全维度）才 `ELIGIBLE_FOR_2D_CONSIDERATION`；若不等价则 `REJECTED_AS_REPAIR_CANDIDATE`。
- Matrix A BLOCKED → 既无法判等价、也无法判不等价 → **`UNVERIFIED`**。
- 既不是 `ELIGIBLE_FOR_2D_CONSIDERATION`（无等价证据），也不是 `REJECTED`（无不等价证据）。
- 审批窗口独立确认：legacy `alembic_version` 表不存在（count=0）—— 本阶段未对 legacy 执行任何 stamp，未创建/修改 `alembic_version`。
- **严禁"先 stamp 0030 再修差异"**（2B §14）。

---

## 9. Data Disposability

```
DISPOSABLE  (READ_ONLY_PG_VERIFIED，自 2A 的 LIKELY_DISPOSABLE 升级)
```

审批窗口独立只读核验（legacy `auto_wechat`，`SET default_transaction_read_only=on`，仅输出 count、不输出 PII 明文）：

| 指标 | 探索窗口报告值 | 审批窗口独立复核值 | 一致 |
|---|---|---|---|
| `alembic_version` 表 | 不存在 | count=0（不存在） | ✓ |
| 业务表 | 57 | 57 | ✓ |
| `compute_transactions` | 3 | 3 | ✓ |
| `compute_accounts` | 1 | 1 | ✓ |
| `compute_markup_ratios` | 1 | 1 | ✓ |
| 全库总行数 | 5 | 5（3+1+1） | ✓ |
| `douyin_leads` / `customer_profiles` / `sales_lead_feedbacks` / `wechat_tasks` | 全 0 | 全 0 | ✓ |
| `daily_report_jobs.current_generation_id` | 缺失 | count=0（缺失） | ✓ |

统计方式足够：精确 count 覆盖全部业务表，PII-bearing 表逐表核验为 0，无人工录入且无法重建的数据（compute_* 为 P1 Consumer Migration 测试种子，可由 fixture/seed 重建）。2A 的"LAN 联调可能写入真实留资手机号"缺口经独立核查不成立（douyin_leads=0）。升级为 `DISPOSABLE` 成立。

> 纪律：`DISPOSABLE` 只代表未来 DB-BL-2D 可把 rebuild 纳入候选，**不代表本阶段允许 DROP / rebuild**。销毁前仍须 2D 独立数据确认 Gate。本阶段未删除任何数据。

### Expected@0016 的正式角色

```
LAST_SUCCESSFUL_RUNTIME_BOOTSTRAP_CHECKPOINT
```

- 角色仅为"链最后一次干净 runtime 落点"（54 表 / 813 列 / 517 约束 / 211 索引 / 20 FK @ revision 0016），供判断链修复范围参考。
- **不得升级为** Historical Reconciliation Anchor / Legacy DB revision / repair target。
- 0030 仍是 DB-BL-2B 冻结的 Historical Anchor Candidate，只是当前无法生成。

---

## 10. Next Stage Authorization

```
DB-BL-2C-R1 — Migration Chain Bootstrap Remediation Design
STATUS:    AUTHORIZED — DESIGN / AUDIT ONLY
TARGET:    NOT immediate migration edit
```

R1 是**设计/审计阶段**，先回答以下问题，不立即改 migration：

1. `file_size_bytes` 的历史 schema provenance（git history / git blame / migration introduction commits / historical docs / 已有环境 revision evidence）。
2. 0008 / 0025 哪个偏离原始 migration intent。
3. 0008 是否曾在后续被回填/修改（provenance 查清前不得假设）。
4. 是否存在其他"早期 create_table 已包含后续 revision 才 add 的对象"（见 Full-chain Temporal Drift Audit）。
5. 哪种修复策略能同时兼容：
   - fresh empty PostgreSQL bootstrap；
   - 已合法跑过旧 migration 的数据库；
   - 当前 Alembic revision contract。
6. 修改 historical migration 与 conditional migration 各自的风险。

### Full-chain Temporal Drift Audit（R1 必须扩大静态审计范围）

当前审计脚本只覆盖 `create_table column → later add_column` 一类缺陷（保守下界）。R1 须扩大到全类别时间漂移审计，至少检查：

- CREATE TABLE column → later ADD COLUMN（当前已覆盖，1 处）
- CREATE INDEX → later CREATE INDEX（同表同索引名/同列集）
- CREATE UNIQUE → later UNIQUE
- CREATE FK → later ADD FK
- CREATE CHECK → later ADD CHECK
- DROP / ALTER / RENAME 相关时间线冲突

用于识别 historical migration backfill / temporal drift。**不得只修第一个 DuplicateColumn 后碰运气继续跑**。R1 须产出"全链时间漂移缺陷清单"，作为修复方案的设计输入。

### Provenance 是 R1 必须项

审批窗口**现在不选**修复方案。具体禁止现在直接选：

- **Option A**：从 0008 删除 `file_size_bytes`
- **Option B**：0025 改为"列存在则跳过"守卫

因为当前只知道 current migration files conflict，不知道 historical canonical migration intent。provenance 查清前选择任一方案均为凭假设推进，违反"不确认即停"。

### R1 完成后的回路

R1 产出修复方案 + 全链审计清单并经审批后，由独立实施阶段修复链 → 重跑 `scripts/db_bl_2c_chain_audit.py` 排查下游 + 实跑 `alembic upgrade 0030` / `head` 至全绿 → 回到 **2C 复跑** Expected 取数与三组矩阵（A/B/C）→ Revision Identity 判定 → 2B §3 Bootstrap Contract 由 `PG_RUNTIME_VERIFIED_FAILURE` 升格为 `PG_RUNTIME_VERIFIED`。

---

## 11. Explicitly Forbidden

本审批窗口明确禁止以下行为，R1 及后续任何窗口在获得对应独立审批前不得执行：

- **NO STAMP** — 任何 revision，legacy 或 disposable；不得创建/修改 legacy `alembic_version`。
- **NO LEGACY UPGRADE** — legacy 5432/`auto_wechat` 不得执行 alembic upgrade/downgrade。
- **NO REPAIR IMPLEMENTATION** — 本审批只授权 R1 设计/审计，不授权实施修复。
- **NO HISTORICAL MIGRATION EDIT YET** — 不得在 provenance 查清 + 修复方案获批前修改 0008 / 0025 或任何 migration 文件。
- **NO REBUILD** — 不得 DROP / recreate legacy dev PG（DISPOSABLE 仅纳 2D 候选，不授权本阶段销毁）。
- **NO PROD / STAGING** — 任何操作不得触碰 production / staging。
- **NO DB-BL-2D** — 2D 在 2C 复跑完成（Matrix A/B/C 产出 + Revision Identity 判定）前不得进入。

---

## 附：审批状态汇总

| 维度 | 判定 |
|---|---|
| Technical Decision | `APPROVED / BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` |
| Runtime Bootstrap（Expected@0030） | `FAIL @ 0025` — `PG_RUNTIME_VERIFIED_FAILURE` |
| Runtime Bootstrap（Expected@0034） | `FAIL @ 0025` — `PG_RUNTIME_VERIFIED_FAILURE` |
| Migration Defect | `DUPLICATE_COLUMN_CHAIN_DEFECT = CODE_VERIFIED`（0008:340 create + 0025:59 add；provenance 未定） |
| 2A 静态证据（表集合/拓扑） | `STATIC_CHAIN_VERIFIED` 保持 |
| 2A projected bootstrap | supersede → `PG_RUNTIME_VERIFIED_FAILURE` |
| 2B Bootstrap Contract（目标） | `APPROVED / FROZEN` 保持 |
| 2B 当前链实现符合度 | `FAIL` |
| Matrix A / B / C | `BLOCKED` / `BLOCKED` / `BLOCKED` |
| Revision Identity | `UNVERIFIED_DUE_TO_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` |
| Stamp Eligibility | `UNVERIFIED` |
| Data Disposability | `DISPOSABLE`（`READ_ONLY_PG_VERIFIED`，全库 5 行、无 PII） |
| Legacy Read-only Compliance | `VERIFIED`（隔离 + 只读 session + 零写入 + 无 stamp） |
| Next Stage | `DB-BL-2C-R1 = AUTHORIZED — DESIGN/AUDIT ONLY` |

审批报告完成。停止于此，不进入 R1，不进入 DB-BL-2D。
