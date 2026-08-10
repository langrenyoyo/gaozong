# DB-BL-2C — auto_wechat PostgreSQL Exact Reconciliation

> ⚠️ **本报告为原始 2C 尝试的历史阻断证据（保留不删）。**
> 该 `BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` 已由 R2 修复并 `AUTHORIZED_TO_RESUME`；2C 复跑结果见
> `DB_BL_2C_EXACT_RECONCILIATION_RESUME.md`（Revision Identity = `NOT_EQUIVALENT_TO_0030`）。
> 本文件以下内容为 2026-08-10 R2 修复前的真实 runtime 事实，不作为当前 2C 结论。

> 报告日期：2026-08-10
> 阶段：P1 `COMPUTE-IDEMPOTENCY-001` Technical Closure / Blocker A（auto_wechat schema baseline）
> 模式：**EXACT RECONCILIATION**（只读对账 + disposable PG 受控 bootstrap）
> 实施：**NOT AUTHORIZED**（无任何 legacy DB 修复）
> 前置：
> - `DB_BL_2A_MIGRATION_CHAIN_COMPLETENESS.md`（`COMPLETE / FROZEN`，11 条冻结事实）
> - `DB_BL_2B_SCHEMA_OWNERSHIP_DESIGN.md` + `DB_BL_2B_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，2C 合同冻结：两层 target / 三方比较 / stamp 门禁 / 禁止倒推）
> Source of Truth：真实 PG runtime 证据 > 冻结文档 > 推测

---

## 0. 执行摘要（先读）

**本阶段发现一个阻断性新事实，导致三组对账矩阵无法按合同完成：**

```
MIGRATION_CHAIN_RUNTIME_BOOTSTRAP:
    FAILED
```

`alembic upgrade` 从**空 PG** 自举时，在 revision **0025** 失败：

```
psycopg.errors.DuplicateColumn:
    column "file_size_bytes" of relation "ai_edit_job_artifacts" already exists
[SQL: ALTER TABLE ai_edit_job_artifacts ADD COLUMN file_size_bytes BIGINT]
```

- 根因（`CODE_VERIFIED`）：`0008_xiaogao_phase1_core.py:340` 的 `create_table("ai_edit_job_artifacts")` 已包含 `file_size_bytes` 列；`0025_ai_edit_result_delivery.py:59` 又 `op.add_column("ai_edit_job_artifacts", "file_size_bytes")` → 空库自举时重复建列。
- 后果：`Expected@0030` 与 `Expected@0034` **均无法**通过 runtime 取得（两条路径都在 0025 同点失败，停在 revision 0016 / 54 表）。
- 这是 2A 警告的"PG Alembic 链是独立手写翻译，存在已知 drift 风险"在 runtime 真实暴露；2A 的 `STATIC_CHAIN_VERIFIED`（表级）与 `PG_RUNTIME_NOT_VERIFIED`（runtime 未实跑）分层标签在此被证伪/证实：表级完整，但**列级自举存在阻断缺陷**。
- 静态审计（`scripts/db_bl_2c_chain_audit.py`，仅读文件）：全链**仅此 1 处** create-vs-add 重复列（保守下界，不覆盖 `op.execute` raw SQL ALTER 与重复 index/FK 等其他缺陷类别）。

> 因此本阶段**未能取得** `Expected@0030` / `Expected@0034` 两份独立 schema，三组矩阵（A/B/C）**BLOCKED**。Revision Identity 无法按合同方法判定。这不是环境不可达（环境已恢复可达），而是 **migration chain 自身存在阻断性 runtime 缺陷**。

依据本任务 §17，本阶段**已停止 bootstrap 路径**，未手工补表、未改 migration、未 stamp、未 patch DB。该缺陷的修复属独立审批的 migration chain remediation，**不在 2C 范围**。

环境已恢复可达，且 legacy dev PG 数据可处置性已升级为 `DISPOSABLE`（`READ_ONLY_PG_VERIFIED`，全库仅 5 行、无 PII）。

---

## 1. Environment Evidence

### 1.1 Legacy Dev PG（READ-ONLY）

| 维度 | 值 |
|---|---|
| host | 本机 Docker `127.0.0.1` |
| port | 5432 |
| database | `auto_wechat`（owner `auto_wechat`，由 `docker/postgres/init/001_create_databases.sql` 创建） |
| 容器 | `auto-wechat-postgres-dev`（image `postgres:16-alpine`，PG 16.14） |
| 数据卷 | named volume `auto_wechat_postgres_data`（非 prod compose 的 `./docker-data/postgres` bind） |
| 环境分类 | **local development**（bind 挂本地 repo `docker/postgres/init`、容器名带 `-dev`、非 staging `auto_wechat_staging`、非 prod compose `docker-compose.yml`） |
| 其他库（同实例） | `xg_douyin_ai_cs`、`postgres`、`auto_wechat_outbox_test` |
| 密码 | 未输出（按任务要求脱敏） |

只读证据：所有查询均 `SELECT` 系统目录 + `SET default_transaction_read_only=on` 会话守卫；**未执行任何 DDL/DML 写入**。

> 与 2A 对比：2A 时 `Test-NetConnection 127.0.0.1:5432 → TcpOpen=False`、`docker ps` 空。本轮容器 `auto-wechat-postgres-dev` 已存在（`Exited 255`），本阶段 `docker start` 后 `running/healthy`。**环境由 2A 的"不可达"恢复为"可达"**——这是 2A 冻结事实 #9（dev PG 状态）依赖的外部环境变化，dev PG 内部状态（57 表 / 无 alembic_version / 缺 0032-0034）经本轮只读复核**仍然成立**。

### 1.2 Disposable Verification PG（CONTROLLED CREATE / ALEMBIC UPGRADE）

| 维度 | 值 |
|---|---|
| host | 本机 Docker `127.0.0.1` |
| port | 5433（与 legacy 5432 明确隔离） |
| 容器 | `db-bl-2c-expected-pg`（image `postgres:16-alpine`，与 legacy 同 PG 16.14） |
| 数据卷 | 全新 named volume `db_bl_2c_expected_data`（与 legacy `auto_wechat_postgres_data` 完全独立） |
| 验证 DB | `db_bl_2c_expected_0030`、`db_bl_2c_expected_0034`（名称与 legacy `auto_wechat` 明确区分） |
| 环境分类 | **disposable local verification**（非 prod / 非 staging / 不覆盖现有业务库） |
| 密码 | throwaway 本地口令 `dbbl2c_local`，仅运行时传入，未写入任何脚本/文件 |

Environment Gate 五项均满足：本地开发地址 ✓ / 非 production ✓ / 非 staging ✓ / disposable 与 legacy 库名明确不同 ✓ / 不覆盖现有业务库 ✓。

> 禁止：本阶段未将 `DATABASE_URL` 指向 legacy 5432/`auto_wechat` 执行任何 alembic upgrade。两次 alembic 均显式指向 disposable 5433/`db_bl_2c_expected_*`。

---

## 2. Alembic Bootstrap Runtime Verification

### 2.1 Expected@0030（Layer 2 Historical Anchor Candidate）

```
RESULT: FAIL
```

证据等级：`PG_RUNTIME_VERIFIED`（真实空 PG 实跑，失败证据已保留）。

执行：`DATABASE_URL=...@127.0.0.1:5433/db_bl_2c_expected_0030` + `alembic upgrade 0030`。

结果：

```
psycopg.errors.DuplicateColumn:
    column "file_size_bytes" of relation "ai_edit_job_artifacts" already exists
[SQL: ALTER TABLE ai_edit_job_artifacts ADD COLUMN file_size_bytes BIGINT]
```

- 失败点：`0025_ai_edit_result_delivery.py:59`。
- 失败后状态：`alembic_version=0016`，public 业务表 54 张（恰为链内 ≤0016 建表数：0002+0003+0004+0005+0006+0008+0009+0010+0013+0015 = 54）。
- 0001–0016 已提交（事务内提交），0017–0025 回滚（外层事务回滚），最终停在 0016。

### 2.2 Expected@0034（Layer 1 Canonical Final Target）

```
RESULT: FAIL
```

证据等级：`PG_RUNTIME_VERIFIED`。

执行：`DATABASE_URL=...@127.0.0.1:5433/db_bl_2c_expected_0034` + `alembic upgrade head`。

结果：与 Expected@0030 **完全相同**——在 0025 同点失败（`DuplicateColumn ai_edit_job_artifacts.file_size_bytes`），停在 revision 0016 / 54 表。因 0025 < 0034，head 路径必先经过 0025，确定性同点失败。

### 2.3 失败处理合规性

按本任务 §17：本阶段**未**手工补表、**未**改 migration、**未** stamp、**未** patch DB 后继续。已停止 bootstrap 路径并保留错误证据（错误堆栈、SQL、失败后 DB 状态）。该失败本身是重要 DB-BL 证据。

> 该失败可能影响 DB-BL-2B 的静态判断（2B §3 Bootstrap Contract = 空 PG → upgrade head，被证伪为 runtime 不可用），需审批窗口重新评审（见 §12 / §14）。

---

## 3. Expected Schema Summary

### 3.1 Expected@0030

```
NOT OBTAINABLE — blocked by 0025 bootstrap failure
```

无法通过合同方法（独立空 PG → alembic upgrade 0030）取得。`PG_RUNTIME_VERIFIED`（失败）。不得以 ORM metadata 或静态推断替代（§6/§7 禁止 reverse inference / 禁止以 ORM 为 target）。

### 3.2 Expected@0034

```
NOT OBTAINABLE — blocked by 0025 bootstrap failure (identical)
```

### 3.3 Expected@0016（部分 / 最近 runtime-verified 检查点）

虽非 2C 合同 target，但作为"链最后一次干净 runtime 落点"记录，供审批窗口判断链修复范围参考：

| 维度 | 值 |
|---|---|
| revision | 0016 |
| 业务表 | 54（excl `alembic_version`） |
| 列 | 813 |
| 约束 | 517 |
| 索引 | 211 |
| FK | 20 |
| 证据等级 | `PG_RUNTIME_VERIFIED`（0001–0016 干净提交） |

---

## 4. Legacy Actual Summary

### 4.1 基础事实（`READ_ONLY_PG_VERIFIED`，复核 2A 冻结事实 #9）

| 维度 | 值 |
|---|---|
| 业务表 | 57（public，excl alembic_version） |
| `alembic_version` 表 | **不存在**（count=0）→ 不对应任何 Alembic revision |
| 列 | 906 |
| 约束 | 439 |
| 索引 | 172 |
| FK | 18 |
| 缺失表（0032/0033/0034） | `daily_report_generations`、`ai_edit_material_analysis_executions`、`ai_preview_executions` **均缺失** |
| `daily_report_jobs.current_generation_id`（0032 新增列） | **缺失**（列级确证 legacy < 0032） |

### 4.2 Schema 特征

- 57 表 = 2A 冻结的 create_all 快照；表数 57 = 链 60 − 缺失 3（0032/0033/0034）。表级与 2A #9 一致。
- **drift 信号**（跨 revision，非 contracted Matrix A，仅作信号）：legacy（≈0030-era create_all 快照）表数/列数多于 Expected@0016（54 表/813 列），但**约束/索引/FK 反而更少**（439<517、172<211、18<20）。这表明 `create_all` 快照遗漏了 migration 显式定义的部分约束/索引/FK —— 与 2A "ORM 与链是两个独立维护源、列级/约束级未对账"一致。

### 4.3 只读证据

- 全部查询 `SELECT` 系统目录 + `SET default_transaction_read_only=on`。
- 未执行 CREATE/ALTER/DROP/INSERT/UPDATE/DELETE/TRUNCATE/VACUUM FULL/REINDEX/alembic stamp/upgrade。

---

## 5. Migration Chain Bootstrap Defect（核心证据）

### 5.1 缺陷定位（`CODE_VERIFIED`）

| 位置 | 操作 | 表.列 |
|---|---|---|
| `0008_xiaogao_phase1_core.py:340` | `create_table("ai_edit_job_artifacts")` 内 `sa.Column("file_size_bytes", sa.BigInteger(), nullable=True)` | `ai_edit_job_artifacts.file_size_bytes`（建表时即创建） |
| `0025_ai_edit_result_delivery.py:59` | `op.add_column("ai_edit_job_artifacts", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True, comment=...))` | `ai_edit_job_artifacts.file_size_bytes`（重复添加） |

runtime 印证：失败 DB 在 revision 0016 时 `ai_edit_job_artifacts` 已含 `file_size_bytes bigint`（0008 建表创建）→ 0025 add_column 命中已存在列 → `DuplicateColumn`。

### 5.2 缺陷性质

- `0025` 文件头注释明确"file_size_bytes：归档文件大小"是 0025 要**新增**的列。说明历史演进意图：0008 建表时**不含** file_size_bytes，0025 引入它。
- 但当前 `0008` 的 create_table **已包含** file_size_bytes → create_table 被回填为**当前 ORM 全列集**（含本应由后续 migration 引入的列），属典型的手写翻译 drift。
- 该 drift 在 create_all 路径（legacy dev PG）下不可见（create_all 直接以当前 ORM 建表，不经过 0025 的 add_column），故 legacy dev PG 从未触发该缺陷；仅在"空库 → alembic upgrade"的合同 bootstrap 路径下暴露。

### 5.3 缺陷范围（静态审计，`CODE_VERIFIED` / 保守下界）

工具：`scripts/db_bl_2c_chain_audit.py`（只读 AST 解析全部 33 个 migration 文件，不连库、不修改）。

```
duplicate add_column (create-already-has) count: 1
  [0025] 0025_ai_edit_result_delivery.py: table=ai_edit_job_artifacts column=file_size_bytes
```

- 全链 create-vs-add 重复列 = **1 处**（即 0025 file_size_bytes）。
- **保守下界**：本扫描只覆盖 create_table 内显式 `sa.Column` 字面量 + 后续 `op.add_column` 同表同列；**不覆盖** `op.execute(raw SQL ALTER)`、重复 `create_index`/`create_foreign_key`/`create_unique_constraint`、动态列名等。0026–0034 的 runtime 在 0025 修复前**不可观测**，是否存在下游同类缺陷未知。

---

## 6. Matrix A — Legacy Actual vs Expected@0030

```
BLOCKED — Expected@0030 not obtainable
```

Matrix A 依赖 `Expected@0030`（独立空 PG → alembic upgrade 0030），该 schema 因 0025 bootstrap 失败无法取得（§2.1）。按 §6/§7 不得以 ORM metadata 或静态推断替代 expected。故 Matrix A 无法产出。

**已有替代证据（非 Matrix A，仅供审批窗口参考）**：

- Legacy Actual（57 表 / 无 alembic_version / 缺 0032-0034 表与列）见 §4。
- Legacy vs Expected@0016（不同 revision，非 contracted 对账）：见 §3.3 / §4.2 drift 信号。

---

## 7. Revision Identity Verdict

```
UNVERIFIED_DUE_TO_MIGRATION_CHAIN_BOOTSTRAP_FAILURE
```

> 本任务 §11 给出的 verdict 选项为 `EXACT_EQUIVALENT_TO_0030` / `NOT_EQUIVALENT_TO_0030` / `UNVERIFIED_DUE_TO_ENVIRONMENT`。本轮出现第三类阻断——**不是环境不可达**（环境已恢复可达，§1），而是 **migration chain 自身存在阻断性 runtime 缺陷**（§5），使 `Expected@0030` 无法生成。故以 `UNVERIFIED_DUE_TO_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` 表达，区别于环境阻断。

判定理由：

- 回答"当前 legacy dev PG 是否精确等价于合法 revision 0030"**必须**依赖 `Expected@0030`（§6.1/§6.2 冻结：target 基于 Alembic expected schema，非 ORM；对账前禁止倒推）。
- `Expected@0030` 不可得 → 无法做比较 1 → **无法判定** legacy 是否 == 0030。
- 不得"看 legacy 像 0030 → 推断是 0030"（§6.6 禁止倒推 / §9 stamp 门禁前置）。
- 不得用 `Expected@0016`（最近干净检查点）外推 0030——0016 ≠ 0030，且 0017–0030 段 runtime 尚未被验证（0025 即阻断，0017–0024 事务回滚未持久化）。

**未经审批不得**：以 legacy"表数 57 == 链 0030-era 表数 57"为由推断 legacy == 0030。表级相等不蕴含列级/约束级/索引级相等（2A 已登记列级未对账；§4.2 已见约束/索引 drift 信号）。

---

## 8. Matrix B — Expected@0030 vs Expected@0034

```
BLOCKED — both Expected@0030 and Expected@0034 not obtainable
```

两份 expected 均因 0025 失败不可得（§2.1/§2.2）。无法产出合法 0032/0033/0034 delta 矩阵。

（静态层面已知：0032 = 建 `daily_report_generations` + `daily_report_jobs.current_generation_id`；0033 = 建 `ai_edit_material_analysis_executions`；0034 = 建 `ai_preview_executions`。但本阶段禁止用静态推断替代 runtime expected，该 delta 须 2C 复跑后用实际 Expected PG schema 比较得出。）

---

## 9. Matrix C — Legacy Actual vs Expected@0034

```
BLOCKED — Expected@0034 not obtainable
```

依赖 `Expected@0034`，因 0025 失败不可得（§2.2）。无法产出完整最终差异矩阵。

已知 legacy 缺失项（来自 §4，非完整 gap matrix，仅供 2D 参考）：

- 缺表：`daily_report_generations`、`ai_edit_material_analysis_executions`、`ai_preview_executions`。
- 缺列：`daily_report_jobs.current_generation_id`（0032）。
- 其余列/约束/索引级 gap 须待 `Expected@0034` 可得后由 Matrix C 给出。

---

## 10. Stamp Eligibility

```
STAMP_0030: UNVERIFIED
```

- Stamp 门禁（§6.5/§14）：仅当 Matrix A 证明 `Legacy Actual == Expected@0030`（全维度）才 `ELIGIBLE_FOR_2D_CONSIDERATION`；若不等价则 `REJECTED_AS_REPAIR_CANDIDATE`。
- Matrix A BLOCKED → 既无法判等价、也无法判不等价 → `UNVERIFIED`。
- **本阶段未对 legacy DB 执行任何 `alembic stamp`，未创建/修改 legacy `alembic_version`**（§18 严格只读）。
- 严禁"先 stamp 0030 再修差异"（§14）。

---

## 11. Development Data Disposability

```
DISPOSABLE  (READ_ONLY_PG_VERIFIED，自 2A 的 LIKELY_DISPOSABLE 升级)
```

只读证据（legacy `auto_wechat` 库，精确 count）：

| 指标 | 值 |
|---|---|
| 全表总行数 | **5** |
| 非空表 | `compute_transactions`(3)、`compute_accounts`(1)、`compute_markup_ratios`(1) |
| PII 表行数 | `douyin_leads`=0、`customer_profiles`=0、`sales_lead_feedbacks`=0、`wechat_tasks`=0 |
| PII 明文 | **未输出**（§15，仅输出 count） |

归类理由：

- 全库仅 5 行，全部位于 compute/billing 测试种子数据（P1 Consumer Migration 测试产物）。
- 无任何 PII-bearing 表有数据；无手机号/微信号/客户资料/线索/销售反馈行。
- 无人工录入且无法 bootstrap 重建的数据（compute_* 为测试种子，可由测试 fixture/seed 重建）。
- 2A 的"LAN 联调可能写入真实留资手机号"缺口经核查**不成立**（douyin_leads=0）。

> 升级依据：2A 时 PG 不可达 → `LIKELY_DISPOSABLE`（INFERRED）；本轮 PG 可达，精确 count 为 `READ_ONLY_PG_VERIFIED` → `DISPOSABLE`。销毁前仍须 2D 独立数据确认 Gate（本阶段未删除任何数据）。

---

## 12. Evidence Levels

| 事实 | 证据等级 | 说明 |
|---|---|---|
| Legacy 57 表 / 无 alembic_version / 缺 0032-0034 | `READ_ONLY_PG_VERIFIED` | §4，本轮现场只读复核 2A #9 |
| Legacy `daily_report_jobs.current_generation_id` 缺失 | `READ_ONLY_PG_VERIFIED` | §4.1 |
| Legacy 数据可处置性 = DISPOSABLE | `READ_ONLY_PG_VERIFIED` | §11，精确 count |
| Legacy schema 对象计数（906/439/172/18） | `READ_ONLY_PG_VERIFIED` | §4.1 |
| `alembic upgrade 0030` 失败 @ 0025 | `PG_RUNTIME_VERIFIED`（失败） | §2.1，真实空 PG 实跑 |
| `alembic upgrade head` 失败 @ 0025 | `PG_RUNTIME_VERIFIED`（失败） | §2.2 |
| 失败 DB 停在 0016 / 54 表 | `PG_RUNTIME_VERIFIED` | §2.1/§2.2 |
| 0008:340 create 含 file_size_bytes | `CODE_VERIFIED` | §5.1 |
| 0025:59 add_column file_size_bytes（重复） | `CODE_VERIFIED` | §5.1 |
| 全链 create-vs-add 重复 = 1 处（保守下界） | `CODE_VERIFIED`（静态审计） | §5.3，不覆盖 op.execute/重复 index-FK |
| Expected@0016 检查点（54/813/517/211/20） | `PG_RUNTIME_VERIFIED` | §3.3 |
| Expected@0030 / Expected@0034 schema | `NOT_OBTAINABLE` | §3.1/§3.2，0025 阻断 |
| Revision Identity (legacy == 0030?) | `UNVERIFIED` | §7 |
| 0026–0034 是否存在下游同类 bootstrap 缺陷 | `UNKNOWN` | 0025 修复前 runtime 不可观测；静态扫描为保守下界 |
| Legacy 确切成表路径（init_db.py vs 更早 main.py） | `INFERRED`（沿用 2A） | 非 2C 必需 |

---

## 13. DB-BL-2D Inputs

仅列事实输入，**不选择 repair strategy**（本阶段无授权）：

| 输入 | 值 |
|---|---|
| Revision identity verdict | `UNVERIFIED_DUE_TO_MIGRATION_CHAIN_BOOTSTRAP_FAILURE` |
| Gap matrix (A/B/C) | BLOCKED（Expected@0030/0034 不可得） |
| Stamp eligibility | `UNVERIFIED` |
| Data disposability | `DISPOSABLE`（`READ_ONLY_PG_VERIFIED`，全库 5 行、无 PII） |
| Bootstrap runtime result | **FAIL** @ 0025（两路径同点失败，停 0016） |
| 已知 legacy 缺失项 | 缺 3 表 + `daily_report_jobs.current_generation_id`（详见 §4.1 / §9） |
| 链缺陷 | 1 处 create-vs-add 重复列（`ai_edit_job_artifacts.file_size_bytes`，0008:340 vs 0025:59），保守下界 |
| 环境状态 | legacy dev PG 已可达（5432）；disposable 验证 PG 已就绪（5433） |

### 13.1 进入 2D 前的硬阻塞（须审批窗口决策）

1. **migration chain 自举缺陷必须先修复**（独立审批的 chain remediation）：否则 `Expected@0030`/`Expected@0034` 永远不可得，Matrix A/B/C 无法完成，revision identity 永久 `UNVERIFIED`。
2. 链修复**不在 2C 范围**（§17/§22 禁止改 migration 文件）。链修复方案（如：从 0008 create_table 移除应由 0025 引入的列，或为 0025 add_column 加"列已存在则跳过"守卫）须独立设计 + 审批。
3. 链修复须**重跑** `scripts/db_bl_2c_chain_audit.py` 并实跑 `alembic upgrade 0030` / `head` 至全绿，方可回到 2C 完成 Expected 取数与三组矩阵。
4. 链修复后 2B §3 Bootstrap Contract（空 PG → upgrade head）方能由 `STATIC_CHAIN_VERIFIED` + `PROJECTED` 升格为 `PG_RUNTIME_VERIFIED`；当前为 `PG_RUNTIME_VERIFIED = FAILED`。

---

## 14. 对 DB-BL-2B 静态判断的影响（供审批窗口重新评审）

2B 冻结结论中受本轮 runtime 证据影响、需重新评审的点：

| 2B 冻结项 | 本轮 runtime 证据 | 影响 |
|---|---|---|
| §3 Bootstrap Contract = 空 PG → upgrade head（`STATIC_CHAIN_VERIFIED` + `PROJECTED`） | `alembic upgrade` 实跑 FAIL @ 0025 | 该路径**当前不可用**；2A/2B 的"链可空库自举"为静态推断，runtime 证伪。须链修复后重验。 |
| 2A #1/#2 链结构完整（60 表、线性无分支、无链外表引用） | 表级结构仍然成立；但**列级**存在 create-vs-add 重复缺陷 | 2A 的 `STATIC_CHAIN_VERIFIED` 范围限定为"表级 + 无链外表引用"，**不含列级自举正确性**——该限定在 2A 报告中已显式声明（`column_level_reconciliation = NOT_DONE`），本轮印证。 |
| 2B §6.1 target 基于 Alembic expected schema（非 ORM） | 正确性不变 | 链缺陷不改变"应以链 expected 为 target"的设计；反而证明 ORM-vs-chain drift 真实存在，以 ORM 为 target 会掩盖缺陷。设计结论**成立**。 |
| 2B §6.2 0030 作为 Historical Anchor Candidate | 0030 expected 不可得，anchor 比较无法执行 | **不推翻** 0030 作为候选的选型（0032.down_revision=0030 仍成立），但 anchor 判定**延后**至链修复 + 2C 复跑。 |

> 本轮未推翻 2B 的所有权模型（Model A）、Ownership Contract、target 设计原则；仅证伪"链当前可空库自举"这一 projected 假设，并定位其首个阻断点。

---

## 15. Implementation Status

```
LEGACY DB MODIFICATION:        NOT STARTED
REPAIR:                        NOT AUTHORIZED
MIGRATION CHAIN MODIFICATION:  NOT AUTHORIZED (out of 2C scope, §17/§22)
```

本阶段已完成（只读 + disposable 受控）：

- ✅ Environment Gate 确认（legacy 5432 / disposable 5433 隔离）
- ✅ Legacy dev PG 只读 schema 采集与对象计数
- ✅ Legacy 数据可处置性精确核查（→ `DISPOSABLE`）
- ✅ Disposable PG 受控 bootstrap 实跑（Expected@0030 / Expected@0034）→ 均 FAIL @ 0025
- ✅ 链缺陷定位（0008:340 vs 0025:59）+ 静态审计（1 处，保守下界）
- ✅ Expected@0016 部分检查点记录

本阶段未执行、且禁止执行：

- ❌ `alembic stamp`（任何 revision，legacy 或 disposable）
- ❌ 创建/修改 legacy `alembic_version`
- ❌ repair migration / 修改任何 migration 文件（含 0008 / 0025）
- ❌ legacy DB upgrade / downgrade
- ❌ DROP / recreate legacy dev PG
- ❌ 修改 legacy 数据
- ❌ 修改 init_db.py / main.py / P1 Consumer code / M07 Core
- ❌ 手工补表 / patch DB 让 bootstrap"继续通过"
- ❌ 自行进入 DB-BL-2D 或选择 repair strategy
- ❌ production / staging 操作

---

## 16. 本阶段完成条件评估

任务 §21 要求：取得足够证据回答 `Legacy Actual == Expected@0030 ?` 并产出三张矩阵后 2C 才 COMPLETE。

- `Expected@0030` / `Expected@0034` **不可得**（0025 阻断）→ 无法回答 revision identity → 三组矩阵 BLOCKED。
- **环境已恢复可达**，故不是 `AUTHORIZED_BUT_ENVIRONMENT_BLOCKED`。
- 本阶段以**阻断性证据**（链自举缺陷）如实提交，未用静态推断替代 runtime reconciliation（§21 禁止）。

```
DB-BL-2C:
    BLOCKED_BY_MIGRATION_CHAIN_BOOTSTRAP_FAILURE
    (environment reachable; chain defect at 0025 blocks Expected schema generation)
```

需要审批窗口决策：是否授权独立 migration chain remediation 修复 0025 缺陷（及重跑审计排查下游），修复后回到 2C 复跑 Expected 取数与三组矩阵。

---

## 附：关键证据索引

| 事实 | 证据 |
|---|---|
| Legacy 57 表 / 无 alembic_version | `docker exec auto-wechat-postgres-dev psql -U postgres -d auto_wechat` 只读 count |
| `daily_report_jobs.current_generation_id` 缺失 | information_schema.columns 只读查询（0 行） |
| 数据可处置性 | 精确 count：全库 5 行（compute_transactions 3 / compute_accounts 1 / compute_markup_ratios 1） |
| `alembic upgrade 0030` 失败 | `0025_ai_edit_result_delivery.py:59` → `DuplicateColumn ai_edit_job_artifacts.file_size_bytes`，停 0016 / 54 表 |
| `alembic upgrade head` 失败 | 同 0025 同点失败，停 0016 / 54 表 |
| 0008 create_table 含 file_size_bytes | `0008_xiaogao_phase1_core.py:340` |
| 0025 add_column file_size_bytes（重复） | `0025_ai_edit_result_delivery.py:59` |
| 静态审计全链重复列 | `scripts/db_bl_2c_chain_audit.py`（只读 AST，1 处） |
| Expected@0016 检查点 | `db_bl_2c_expected_0030` @ revision 0016（54/813/517/211/20） |
| Disposable 隔离 | 容器 `db-bl-2c-expected-pg` / 端口 5433 / 卷 `db_bl_2c_expected_data`（与 legacy 5432 / `auto_wechat_postgres_data` 独立） |
