# PRODUCTION-SCHEMA-BASELINE-CATCHUP-0028-TO-0034 — Reality / Migration Chain Audit

> 本文件是 **READ ONLY / AUDIT ONLY** 产出。未执行任何生产迁移、未改代码、未改迁移、未 commit、未 push。
> 审计窗口：auto_wechat Merchant 生产实例 PostgreSQL `0028` → 本地 pre-P2 技术基线 `0034` 的 schema/code migration chain 独立只读审计。
> 证据层级标注：`CODE_VERIFIED` / `MIGRATION_VERIFIED` / `GIT_HISTORY_VERIFIED` / `USER_CONFIRMED_TOPOLOGY` / `PRODUCTION_READ_ONLY_VERIFIED` / `UNKNOWN`。

---

## 1. Governance Baseline

```
P1 COMPUTE-IDEMPOTENCY-001       = CLOSED
P1 TECHNICAL_CLOSURE              = VERIFIED          （不重新打开）
P1 CODE_CLOSURE                  = CLOSED
P1 PRODUCTION_DEPLOYMENT_BASELINE = BEHIND / UNDER_AUDIT

P2 TECHNICAL_REMEDIATION          = VERIFIED
P2 M04 CLAIM/LEASE                = REMEDIATED
P2 PRODUCTION_CUTOVER             = BLOCKED_BY_B7_B8

B7 PRODUCTION_SCHEMA_BASELINE_BEHIND = CONFIRMED      （M1 证据）
B8 PRODUCTION_CODE_BASELINE_BEHIND  = CONFIRMED      （M1 证据 + git 核实）
```

**关键定性（M1 证据后纠正）：** 生产当前不是"新代码 + 旧 schema"的 drift 状态，而是 **CODE + MIGRATION SET + DB 三者共同停留在 0028 的一致旧 baseline**。因此 `0028→0034` 不得被设计成单纯 schema migration，必须按 **PRODUCTION CODE + SCHEMA BASELINE CATCH-UP** 审计。

---

## 2. Production Topology

```
PRODUCTION_NOTIFY_SALES_OWNER     = merchant
PRODUCTION_PRIMARY_SERVER         = merchant
PRODUCTION_DATABASE               = PostgreSQL / auto_wechat
PRODUCTION_CURRENT_ALEMBIC        = 0028
EXPECTED_PRODUCTION_AGENT_ENDPOINT = merchant（cutover 前 B2/B5 现场一致性，非本轮 schema audit blocker）

callback.misanduo.com             = LEGACY_GRAY_TEST_SERVER / OLD DEV / GRAY ENV
                                   = NOT P2 PRODUCTION TARGET / OUT OF B7 TARGET
```

`callback` SQLite 0033 不属于本轮 schema catch-up 范围；不升级、不对齐、不比较其 schema 作为 production target、不写入 B7 plan。

---

## 3. B6 Resolution

```
PRODUCTION_TOPOLOGY_ROLE           = RESOLVED          （M1 USER_CONFIRMED_TOPOLOGY）
```

`ACTUAL_PRODUCTION_AGENT_SERVER_URL` 仍属 cutover 前 B2/B5 现场一致性验证，不在本轮 schema audit 范围。

---

## 4. Production Owner

```
PRODUCTION_SCHEMA_OWNER   = merchant（auto_wechat PG 实例）
PRODUCTION_NOTIFY_SALES_OWNER = merchant
```

---

## 5. Current Production Revision

```
PRODUCTION_APP_ALEMBIC_CURRENT = 0028     （M1）
PRODUCTION_APP_ALEMBIC_HEAD    = 0028     （M1：生产代码迁移集本身只到 0028）
PRODUCTION_DB_ALEMBIC          = 0028     （M1）
PRODUCTION_READY_EXPECTED      = 0028     （M1）
PRODUCTION_READY_ACTUAL        = 0028     （M1）
PRODUCTION_READY               = PASS     （M1）
PRODUCTION_PUBLIC_TABLE_COUNT  = 58       （M1）
```

三态一致：`code alembic head == code alembic current == DB alembic == 0028`，`/ready` PASS。

---

## 6. Current Production Code

```
CURRENT_PRODUCTION_CODE_COMMIT = f453f44e6a70de3eb5fa8f808cf4b6a9d72ea6c1
```

- `GIT_HISTORY_VERIFIED`：`f453f44 = "fix: 导出脚本兼容多版本 pymilvus 迭代 API"`。
- 在 master 第一父链上，是当前 HEAD `36fe68a` 的祖先。
- 是 0029 引入 commit `8579289` 的祖先 → **f453f44 严格早于 0029**。
- `ac04159`（0028 引入）是 f453f44 的祖先 → f453f44 **含 0028 迁移**。
- f453f44 时 `versions/` 目录恰好 28 个文件 `0001..0028`（`GIT_HISTORY_VERIFIED`）。
- f453f44 时 `app/models.py` 不含 `compute_transactions.idempotency_key/payload_evidence`、`AiPreviewExecution`、`DailyReportGeneration`、`AiEditMaterialAnalysisExecution`、`daily_report_jobs.current_generation_id`（`CODE_VERIFIED`；命中的 `idempotency_key` 属 `return_visit_runs`，0011 既有，与 0030 无关）。
- f453f44 时 `CustomerProfile.confirmed_fields_json/inferred_fields_json` 已用 `_JSONStringJSONB()`（`CODE_VERIFIED`，与 HEAD 同）。

**结论：** f453f44 = 干净的 0028 代码 baseline，零 0029~0034 迁移文件、零 0029~0034 消费者。`B8 PRODUCTION_CODE_BASELINE_BEHIND = CONFIRMED`。

---

## 7. Revision Graph

逐文件读取 `revision` / `down_revision`（`MIGRATION_VERIFIED`）。**关键纠正：0031 不存在于仓库**，是刻意跳号（0032 文件头注明：避免与 SQLite `0031_compute_billing.sql` 编号语义混淆）。真实链为单线、无分叉、无 merge、单 head=`0035`：

```
0028  down=0027   contact_invalid_followup_tasks（建表）
0029  down=0028   customer_profiles TEXT→JSONB（2 列）
0030  down=0029   compute_transactions +idempotency_key +payload_evidence +UK
      ───── 0031 不存在（刻意跳号）─────
0032  down=0030   daily_report_generations（建表）+ daily_report_jobs.current_generation_id
0033  down=0032   ai_edit_material_analysis_executions（建表）
0034  down=0033   ai_preview_executions（建表）
0035  down=0034   wechat_tasks claim/lease 4 列（P2，OUT OF B7 TARGET）
```

**Catch-up 目标链 = `0028→0029→0030→0032→0033→0034`（5 个迁移）。** 任务书原假设的 `…→0031→0032…` 已纠正为 `0030→0032`。无 branch / merge / multiple heads。

---

## 8. 0029 Audit — customer_profiles TEXT→JSONB

**文件：** `0029_customer_profiles_jsonb_unify.py`（`MIGRATION_VERIFIED`）

- `upgrade()`：`ALTER COLUMN confirmed_fields_json TYPE JSONB USING confirmed_fields_json::text::jsonb`；同样改 `inferred_fields_json`。
- `downgrade()`：JSONB→TEXT 回退兜底（丢 JSONB 查询/索引能力）。
- **分类：** `CONSTRAINT_TIGHTENING` / 类型收紧（非 additive）。物理列从 TEXT 改 JSONB。
- **DML/Backfill：** 无 `op.execute/UPDATE/INSERT`；`postgresql_using` 在线转换已存 JSON 字符串。
- **NOT NULL：** 无新增 NOT NULL；两列保持 nullable（JSONB `none_as_null=True`）。
- **UNIQUE：** 无。
- **FK：** 无。
- **CHECK：** 无。
- **Index：** 无（不加索引；如已有 JSONB 索引需另议，本迁移无）。
- **DATA_PRECONDITION：** 已存非 NULL 值必须是合法 JSON 字符串，否则 `ALTER TYPE … USING ::jsonb` 报错。迁移文件头已自带预检 SQL。
- **Lock：** `ALTER COLUMN TYPE` 触发表重写，`ACCESS EXCLUSIVE` 锁持表 → `HIGH / UNKNOWN_UNTIL_ROWCOUNT`（customer_profiles 行数）。
- **代码依赖：** f453f44 ORM 已用 `_JSONStringJSONB()` → 代码侧早已期望 JSONB；0029 仅修物理列对齐。生产 0028 物理列若为 TEXT，迁移后变 JSONB；若已被手工改为 JSONB，`ALTER TYPE JSONB` 幂等无副作用。
- **P1 关系：** 非 P1 计费核心；属 customer_profiles JSONB/TEXT 一致性修复（任务 3.2）。

---

## 9. 0030 Audit — compute 幂等基础设施

**文件：** `0030_compute_idempotency.py`（`MIGRATION_VERIFIED`，引入 commit `cb86c3b` "P1 Stage 1 M07 Core 幂等基础设施"）

- `upgrade()`：
  - `ADD COLUMN idempotency_key String(255) nullable`（comment：None 走旧逻辑裸扣）
  - `ADD COLUMN payload_evidence Text nullable`
  - `CREATE UNIQUE CONSTRAINT uk_compute_transactions_merchant_idempotency (merchant_id, idempotency_key)`
- `downgrade()`：drop constraint + drop 2 columns。
- **分类：** `SCHEMA_ONLY_ADDITIVE`（nullable 列 + nullable UK）。
- **DML/Backfill：** 无 backfill；无 server_default（两列 nullable）。
- **NOT NULL：** 两新增列均 `nullable=True` → 已有行不失败。
- **UNIQUE：** `uk_compute_transactions_merchant_idempotency (merchant_id, idempotency_key)`。`idempotency_key` 对所有存量行恒为 NULL；SQL 标准 NULL 不参与唯一约束 → 存量行不冲突、`CREATE UNIQUE CONSTRAINT` 扫描通过。无生产重复风险（列尚不存在，无可预检重复）。
- **FK/CHECK：** 无。
- **Lock：** ADD COLUMN nullable 无 default → PG11+ 元数据级即时；`CREATE UNIQUE CONSTRAINT` 需扫 `compute_transactions` 全表（SHARE→校验期 AccessExclusive）→ `MEDIUM / UNKNOWN_UNTIL_ROWCOUNT`。
- **代码依赖：** f453f44 不引用 `compute_transactions.idempotency_key`（`CODE_VERIFIED`）→ 旧代码忽略新列。target 0034 代码（M07 `record_usage`）写入 `idempotency_key` 并依赖该 UK 兜底。
- **P1 关系：** P1 COMPUTE-IDEMPOTENCY-001 Stage 1 M07 Core 幂等基础设施。技术正确性已在 P1 TECHNICAL_CLOSURE=VERIFIED 闭环；本轮只审生产是否具备该 schema，不重审正确性。

---

## 10. 0031 — 不存在（跳号）

仓库无 `0031_*` 迁移文件。0032 的 `down_revision=0030`，刻意跳过 0031 以避免与 SQLite 迁移系统 `0031_compute_billing.sql` 编号混淆（0032 文件头注明）。**不得**在报告中形成 `0028→0030` 跳跃；真实链含 0029、0030，仅缺 0031 编号。

---

## 11. 0032 Audit — daily_report_generations

**文件：** `0032_daily_report_generations.py`（`MIGRATION_VERIFIED`，引入 commit `91afaef` "P1 5C-4"）

- `upgrade()`：
  - `CREATE TABLE daily_report_generations`（id PK, `job_id INT NOT NULL`, `lifecycle_status String(20) NOT NULL server_default='pending'`, `created_at NOT NULL server_default=now()`, PK/FK(`job_id`→`daily_report_jobs.id`)/CHECK）
  - `CREATE INDEX idx_daily_report_generations_job (job_id)`
  - `ADD COLUMN daily_report_jobs.current_generation_id INT nullable`
- `downgrade()`：drop column + drop index + drop table。
- **分类：** `SCHEMA_ONLY_ADDITIVE`（新表 + nullable 列 + 索引 + 约束，全在新建/新列上）。
- **DML/Backfill：** 无 backfill；无 server_default on existing rows（`current_generation_id` nullable，旧行 NULL，不阻塞）。
- **NOT NULL：** 新表 `job_id`/`lifecycle_status`/`created_at` NOT NULL 但均有 server_default 且为新表无存量行；`current_generation_id` nullable。无既有表 ADD NOT NULL 风险。
- **UNIQUE：** 无。
- **FK：** `daily_report_generations.job_id → daily_report_jobs.id`。新建表无存量 child 行 → 无 orphan 风险。父表 `daily_report_jobs` 须存在（0028 前已建，M2 预检父表存在）。
- **CHECK：** `ck_daily_report_generations_status lifecycle_status IN ('pending','running','succeeded','failed')`，仅约束新表新行 → 无存量违反。
- **Index：** `idx_daily_report_generations_job` 在新表上，无锁表风险。
- **Lock：** CREATE TABLE 元数据级；ADD COLUMN nullable 即时；CREATE INDEX 在新表上无竞争 → `LOW`。
- **代码依赖：** f453f44 不引用 `daily_report_generations`/`current_generation_id`（`CODE_VERIFIED`）。target 0034 代码（DailyReport consumer）按 `current_generation_id` 确定性恢复，禁止 `ORDER BY id DESC` 猜测。
- **P1 关系：** P1 Stage 5C-4 方案 B billing identity 层；Reliability Gap `DAILY_REPORT` OUT_OF_P1。

---

## 12. 0033 Audit — ai_edit_material_analysis_executions

**文件：** `0033_material_analysis_executions.py`（`MIGRATION_VERIFIED`，引入 commit `fe91a05` "P1 5F-3"）

- `upgrade()`：`CREATE TABLE ai_edit_material_analysis_executions`（id PK, `material_id String(64) NOT NULL`, `source_sha256 String(64) NOT NULL`, `lifecycle_status String(20) NOT NULL server_default='running'`, `created_at NOT NULL server_default=now()`, `completed_at nullable`, CHECK）+ `CREATE INDEX idx_ai_edit_material_analysis_executions_material (material_id)`。
- `downgrade()`：drop index + drop table。
- **分类：** `SCHEMA_ONLY_ADDITIVE`（新表 + 索引 + 约束）。
- **DML/Backfill：** 无。
- **NOT NULL：** 新表列 NOT NULL 均有 server_default，新表无存量行。
- **UNIQUE/FK：** 无。
- **CHECK：** `ck_ai_edit_material_analysis_executions_status lifecycle_status IN ('running','completed','failed')`，仅新表新行。
- **Index：** 新表上，无锁表风险。
- **Lock：** `LOW`。
- **代码依赖：** f453f44 不引用（`CODE_VERIFIED`）。target 0034 代码（M05 `material_analysis` consumer）每次 `analyze_material_async` 显式建行作 billing identity，durable commit（MA-0）。
- **P1 关系：** P1 Stage 5F-3 方案 B；Charge Path #8；Reliability Gap `M05_ANALYSIS_USAGE_REPORT` OUT_OF_P1。本轮独立审，不与 dormant AiEditMaterialProcess 五阶段表混。

---

## 13. 0034 Audit — ai_preview_executions

**文件：** `0034_preview_executions.py`（`MIGRATION_VERIFIED`，引入 commit `3eddc84` "P1 5G-2"）

- `upgrade()`：`CREATE TABLE ai_preview_executions`（id PK, `merchant_id String(128) NOT NULL`, `agent_id String(128) nullable`, `lifecycle_status String(20) NOT NULL server_default='running'`, `created_at NOT NULL server_default=now()`, `completed_at nullable`, CHECK）+ `CREATE INDEX idx_ai_preview_executions_merchant (merchant_id)`。
- `downgrade()`：drop index + drop table。
- **分类：** `SCHEMA_ONLY_ADDITIVE`。
- **DML/Backfill：** 无。
- **NOT NULL：** 新表列 NOT NULL 均有 server_default，新表无存量行。
- **UNIQUE/FK：** 无。
- **CHECK：** `ck_ai_preview_executions_status lifecycle_status IN ('running','completed','failed')`，仅新表新行。
- **Index：** 新表上，无锁表风险。
- **Lock：** `LOW`。
- **代码依赖：** f453f44 不引用（`CODE_VERIFIED`）。target 0034 代码依赖：M01 Preview consumer + **F-1 Trusted Reply-Suggestion proxy**。F-1 复用 `AiPreviewExecution` 作 durable billing identity 容器，identity namespace `ai_preview_execution:{id}:{stage}`；9000 `_create_preview_execution` 创建并透传 `preview_execution_id` 到 9100（`CODE_VERIFIED`：`app/routers/douyin_ai_cs_proxy.py` import `_create_preview_execution`/`_finalize_preview_execution`，payload 仅设 `preview_execution_id`）。
- **F-1 schema 依赖确认：** F-1 所依赖的 durable execution identity/schema 即 `ai_preview_executions`（0034）。生产 0028 不具备该表 → F-1 代码不可在 0028 schema 运行。F-1 计费正确性属 P1（已 RESOLVED），本轮只确认生产是否具备所需 schema：**否（0028），需 catch-up 到 0034**。
- **P1 关系：** P1 Stage 5G-2 方案 A（9000 创建）；Charge Path #7。

---

## 14. Migration Inventory

| Revision | Parent | Tables | Columns | Indexes | Constraints | Backfill/Data DML | Destructive? |
| -------- | ------ | ------ | ------- | ------- | ----------- | ----------------- | ------------ |
| 0029 | 0028 | — | customer_profiles.confirmed_fields_json/inferred_fields_json (TEXT→JSONB) | — | — | 无（USING 在线转换） | 否（类型改，非删） |
| 0030 | 0029 | — | compute_transactions +idempotency_key, +payload_evidence | — | +UK(merchant_id,idempotency_key) | 无 | 否 |
| 0031 | — | — | — | — | — | — | （不存在） |
| 0032 | 0030 | +daily_report_generations | daily_report_jobs +current_generation_id | +idx_daily_report_generations_job | +FK(job_id→daily_report_jobs.id), +CHECK | 无 | 否 |
| 0033 | 0032 | +ai_edit_material_analysis_executions | — | +idx_..._material | +CHECK | 无 | 否 |
| 0034 | 0033 | +ai_preview_executions | — | +idx_..._merchant | +CHECK | 无 | 否 |
| 0035 | 0034 | — | wechat_tasks +4列 | +idx_status_lease | — | 无 | 否（P2，OUT） |

---

## 15. DDL Inventory

- `ALTER COLUMN TYPE`：0029 ×2（customer_profiles 两列）。
- `ADD COLUMN`：0030 ×2（compute_transactions）、0032 ×1（daily_report_jobs）、0035 ×4（wechat_tasks，OUT）。
- `CREATE TABLE`：0028×1（基线锚点，已存在于生产）、0032×1、0033×1、0034×1。
- `CREATE UNIQUE CONSTRAINT`：0030 ×1。
- `CREATE INDEX`：0032×1、0033×1、0034×1、0035×1（OUT）。
- `CHECK`：0032×1、0033×1、0034×1。
- `FK`：0032×1。
- **全链无 DROP / TRUNCATE / DELETE / RENAME。** 0029 类型改是唯一非常规 additive 项。

---

## 16. DML / Backfill

逐迁移搜 `op.execute / connection.execute / UPDATE / INSERT / DELETE / bulk_insert / server_default / ALTER…SET NOT NULL`：

- 0029：`postgresql_using` 在线转换（非独立 DML），无 `op.execute`。
- 0030：两列 `nullable=True` 无 server_default；无 backfill。
- 0032：`current_generation_id` nullable 无 server_default；新表列 server_default 仅作用于新行。
- 0033/0034：新表 server_default 仅新行。
- **结论：0029~0034 无任何 backfill / 批量 DML。** 唯一依赖已有生产数据满足前提的是 **0029**：存量非 NULL JSON 字符串须合法（见 §17/§26）。

---

## 17. NOT NULL Audit

0029~0034 新增 `nullable=False` 字段：

| 字段 | 新建表 or 既有表 | default/backfill | 已有 row 风险 |
| ---- | ---------------- | ---------------- | ------------- |
| 0032 daily_report_generations.job_id | 新表 | — | 无（新表无行） |
| 0032 …lifecycle_status | 新表 | server_default='pending' | 无 |
| 0032 …created_at | 新表 | server_default=now() | 无 |
| 0033 …material_id / source_sha256 | 新表 | — | 无（新表） |
| 0033 …lifecycle_status / created_at | 新表 | server_default | 无 |
| 0034 …merchant_id | 新表 | — | 无 |
| 0034 …lifecycle_status / created_at | 新表 | server_default | 无 |

**无任何"既有表 ADD COLUMN NOT NULL"。** 0030/0032 既有表新增列（compute_transactions×2、daily_report_jobs×1）全部 nullable。无既有行失败风险。

---

## 18. UNIQUE Audit

新增 UNIQUE：仅 `0030 uk_compute_transactions_merchant_idempotency (merchant_id, idempotency_key)`。

- 生产 0028 该列不存在 → 无可预检重复；迁移后存量行 `idempotency_key` 全 NULL，NULL 不参与唯一约束 → 不冲突。
- **无需生产去重修复。** 无后续修复 SQL。

---

## 19. Foreign Key Audit

新增 FK：仅 `0032 daily_report_generations.job_id → daily_report_jobs.id`。

- 父表 `daily_report_jobs` 须存在（0028 前已建，M2 预检父表存在）。
- child 为新建表，无存量 child 行 → 无 orphan。
- 无 `VALIDATE` 子句（标准 FK 建表内联）。

---

## 20. CHECK Constraint Audit

| 迁移 | 约束名 | 表达式 | 存量违反风险 |
| ---- | ------ | ------ | ------------ |
| 0032 | ck_daily_report_generations_status | lifecycle_status IN ('pending','running','succeeded','failed') | 无（新表） |
| 0033 | ck_ai_edit_material_analysis_executions_status | lifecycle_status IN ('running','completed','failed') | 无（新表） |
| 0034 | ck_ai_preview_executions_status | lifecycle_status IN ('running','completed','failed') | 无（新表） |

均仅约束新建表新行，无存量数据可违反。预检 SQL 见 §33。

---

## 21. Index Audit

| 迁移 | 索引 | 目标表 | 列 | unique | partial | 锁风险 |
| ---- | ---- | ------ | -- | ------ | ------- | ------ |
| 0032 | idx_daily_report_generations_job | daily_report_generations | job_id | 否 | 否 | LOW（新表） |
| 0033 | idx_..._material | ai_edit_material_analysis_executions | material_id | 否 | 否 | LOW（新表） |
| 0034 | idx_..._merchant | ai_preview_executions | merchant_id | 否 | 否 | LOW（新表） |

三索引均在新建表上创建，无大表锁表风险。均非 `CREATE INDEX CONCURRENTLY`（alembic `op.create_index` 默认），但新表无竞争不影响。

---

## 22. Locking Risk（M2 实际行数最终评级）

M2 实际行数：`customer_profiles=1`、`compute_transactions=1698`、`daily_report_jobs=0`。不再 `UNKNOWN_UNTIL_ROWCOUNT`。

| 迁移 | 操作 | 锁类型 | 行数 | 风险 |
| ---- | ---- | ------ | ---- | ---- |
| 0029 | ALTER COLUMN TYPE ×2（jsonb→jsonb 幂等重写） | ACCESS EXCLUSIVE（表重写） | customer_profiles=1 | **LOW**（1 行重写瞬时；虽 ACCESS EXCLUSIVE 但行数极小） |
| 0030 | ADD COLUMN ×2 nullable | 元数据级（PG11+） | compute_transactions=1698 | LOW |
| 0030 | CREATE UNIQUE CONSTRAINT | 校验期 AccessExclusive 扫表 | compute_transactions=1698 | **LOW**（1698 行扫描瞬时；存量 idempotency_key 全 NULL 不冲突） |
| 0032 | CREATE TABLE + ADD COLUMN nullable + CREATE INDEX(新表) | 元数据级 | daily_report_jobs=0 | LOW |
| 0033 | CREATE TABLE + INDEX(新表) | 元数据级 | 新表（0 行） | LOW |
| 0034 | CREATE TABLE + INDEX(新表) | 元数据级 | 新表（0 行） | LOW |

**全链锁/运行风险 = LOW。** 0029 虽为 ACCESS EXCLUSIVE 表重写，但 customer_profiles 仅 1 行；0030 UK 扫描仅 1698 行。无大表锁表风险。生产窗口仍建议低峰执行（0029/0030 持 AccessExclusive）。

---

## 23. Production Physical Schema（M2 最终裁定）

```
PHYSICAL_SCHEMA_STRICT_MATCH_0028 = NO
```

`PRODUCTION_READ_ONLY_VERIFIED`（M2，READ ONLY 事务 `transaction_read_only=on` 已确认）：

- `alembic_version = 0028`、`public_table_count = 58`、58 表清单与 0028 预期一致。
- 0030~0034 touched 新对象**全部 NOT EXISTS**：3 新表（daily_report_generations / ai_edit_material_analysis_executions / ai_preview_executions）`to_regclass` 均 `f`；3 新增列（compute_transactions.idempotency_key/payload_evidence、daily_report_jobs.current_generation_id）0 行；UK `uk_compute_transactions_merchant_idempotency` 0 行；3 索引 0 行；3 CHECK 0 行。
- **但** `customer_profiles.confirmed_fields_json` 与 `inferred_fields_json` 物理类型已为 `jsonb`（`data_type=jsonb, udt_name=jsonb`），而 alembic_version=0028（0028 schema 定义这两列为 TEXT）→ 0029 的内容已提前落地于物理层。
- 父表 `daily_report_jobs` EXISTS（`parent_exists=t`）。
- touched existing tables 指纹：customer_profiles 列/约束/索引与 0028 一致（除两列类型 drift）；compute_transactions 列含 `tenant_id`/`llm_call_stage` 等 0028 既有列，约束 9 条全 0028 既有（无 0030 UK）；daily_report_jobs 22 列全 0028 既有（无 current_generation_id），UK `uk_daily_report_jobs_merchant_day_type_variant` 0028 既有。

**裁定：物理 schema 并非严格 0028，存在 0029 JSONB 类型提前 drift。**

---

## 24. Schema Drift（M2 最终裁定）

```
SCHEMA_DRIFT_FOUND = YES
SCHEMA_DRIFT_SCOPE  = 0029_JSONB_TYPE_AHEAD_ONLY
```

精确范围（不泛化）：

- **drift 对象 1：** `customer_profiles.confirmed_fields_json`，物理 `jsonb`，0028 定义 `TEXT`，0029 定义 `JSONB`。即 0029 的类型变更已提前存在于物理层。
- **drift 对象 2：** `customer_profiles.inferred_fields_json`，同上。

无其他 drift：
- 无 missing objects（58 表齐、/ready PASS）。
- 无 ahead-of-revision 新表/新列/UK/索引/CHECK（0030~0034 全 NOT EXISTS）。
- 无 modified definition（除上述两列类型）。
- 无手工索引/表/列（touched 表指纹与 0028 一致）。

**drift 性质：** 0029 是"类型收紧"迁移（TEXT→JSONB），生产物理层已处于 0029 期望的终态，但 revision 仍 0028。即 drift 方向与 catch-up 目标一致（ahead-of-revision，且方向正确），不构成 catch-up 阻断——前提是 0029 对已-jsonb 列幂等安全（见 §8/§17 重新裁定 = §40）。

`SCHEMA_DRIFT_FOUND = YES` 但**不**自动判 `BLOCKED_BY_SCHEMA_DRIFT`：drift 方向与目标一致且 0029 幂等兼容（§40 验证）。

---

## 25. Production Row Counts Needed

| 表 | 用途 | 迁移 |
| -- | ---- | ---- |
| customer_profiles | 0029 ALTER TYPE 表重写锁时长 | 0029 |
| compute_transactions | 0030 UK 创建扫描锁时长 | 0030 |
| daily_report_jobs | 0032 ADD COLUMN（即时，参考） | 0032 |

M2 行数统计见 §33。不查询业务敏感内容。

---

## 26. Data Preconditions（M2 最终裁定）

逐迁移 DATA_PRECONDITION（M2 证据）：

| 迁移 | 前提 | M2 结果 | 裁定 |
| ---- | ---- | ------- | ---- |
| 0029 | 存量非 NULL JSON 须合法（`ALTER USING ::jsonb`） | invalid_confirmed=0, invalid_inferred=0 | **PASS** |
| 0030 | UK `(merchant_id,idempotency_key)` 存量无重复 | 列不存在→无存量值，全 NULL 不冲突 | **PASS** |
| 0032 | FK 父表 `daily_report_jobs` 存在；child 新表无 orphan | parent_exists=t；新表无行 | **PASS** |
| 0033 | 新表无存量 | 新表 NOT EXISTS | **PASS** |
| 0034 | 新表无存量 | 新表 NOT EXISTS | **PASS** |

**全部 DATA_PRECONDITION = PASS。** 0029 JSON 合法性 0/0；0030 无重复风险；0032 父表存在且 child 无 orphan。

---

## 27. Current App / Intermediate Schema Matrix

**current prod code = f453f44 × schema：**

| App Code | Schema | Compatible? | Evidence |
| -------- | ------ | ----------- | -------- |
| f453f44 | 0028 | YES（current） | M1 三态一致 /ready PASS |
| f453f44 | 0029 | YES | ORM 已 `_JSONStringJSONB`（CODE_VERIFIED）；0029 仅修物理列对齐 |
| f453f44 | 0030 | YES | 0030 全 additive nullable；f453f44 不引用 compute_transactions.idempotency_key |
| f453f44 | 0032 | YES | 新表 + nullable 列；f453f44 不引用 |
| f453f44 | 0033 | YES | 新表；additive |
| f453f44 | 0034 | YES | 新表；additive |

**结论：f453f44 旧代码对 0029~0034 全链前向兼容。** 所有中间态对旧代码安全（`INTERMEDIATE_STATE_SAFE`）。

---

## 28. Target 0034 Code Baseline

```
TARGET_0034_CODE_COMMIT = 9db3f58
```

- `GIT_HISTORY_VERIFIED`：0035 迁移在 `36fe68a`（当前 HEAD）引入；其父 `9db3f58` = "设计：批准M04微信任务执行所有权方案"。
- `9db3f58` stat：纯文档（3 个设计 .md），无代码/迁移改动 → 其树功能等同最后一个代码 commit `eb9f182`（FC-F1 并发修复）。
- 9db3f58 树含：0029~0034 迁移 + 全部 P1 消费者（M07 record_usage、DailyReport generation、M05 analysis、Preview/F-1）+ F-1 closure（cab2e96）+ FC-F1 修复（eb9f182）；**不含 0035**。
- **不得使用当前 HEAD 36fe68a** 作 target：它已含 P2/0035（migration + wechat_task_service/local_agent_main 等）。

候选备选：`1d7f1f5`（P1 技术收口，纯文档）亦为合法 0034 baseline，但 `9db3f58` 是 0035 引入前最新 commit，取其为 target。

---

## 29. Target App / Schema Matrix

**target 0034 code = 9db3f58 × schema：**

| App Code | Schema | Compatible? | Evidence |
| -------- | ------ | ----------- | -------- |
| 9db3f58 | 0028 | **NO** | 消费者写 idempotency_key(0030列)、daily_report_generations(0032表)、ai_edit_material_analysis_executions(0033表)、ai_preview_executions(0034表，含 F-1)；缺对象→INSERT/SELECT 报错；F-1 fail-closed 降级但其余 identity 创建会错 |
| 9db3f58 | 0029 | NO | 缺 0030~0034 对象 |
| 9db3f58 | 0030 | NO | 缺 0032~0034 对象 |
| 9db3f58 | 0032 | NO | 缺 0033/0034 对象 |
| 9db3f58 | 0033 | NO | 缺 0034（ai_preview_executions，F-1 依赖） |
| 9db3f58 | 0034 | YES | schema 与代码匹配 |

**结论：target 0034 代码不能在 0028 schema 运行；target 代码必须 schema 到位后方可启用。** 中间态对 target 代码均不安全。

---

## 30. P1 Production Deployment Boundary

```
P1 TECHNICAL_CLOSURE              = VERIFIED          （不重新打开）
P1 PRODUCTION_DEPLOYMENT_BASELINE = BEHIND / UNDER_AUDIT
```

P1 技术正确性已闭环；本轮只审生产是否具备 0029~0034 schema。生产 0028 不具备 0030/0032/0033/0034 → P1 计费幂等所需的 durable identity 表（compute idempotency、daily report generation、M05 analysis、preview/F-1）在生产**不存在**。catch-up 到 0034 后生产才具备 P1 所需 schema/code 基线。

---

## 31. P2 0035 Boundary

```
0035 = OUT OF B7 EXECUTION TARGET
```

- 0035（wechat_tasks claim/lease 4 列 + idx）属 P2 M04，在 36fe68a 引入。
- 本轮最多确认 0034 是 0035 的合法前置（`down_revision=0034`，已确认单线）。
- **不得**把 `0028→0035` 设计成一次 migration batch。正确治理顺序：`0028→0034 baseline catch-up → verify → 返回 P2 cutover → 0035`。
- 本轮不审 0035 内容正确性，不执行、不设计 0035 catch-up。

---

## 32. Callback Legacy Boundary

```
callback.misanduo.com = LEGACY_GRAY_TEST_SERVER / OUT OF B7 TARGET
```

不升级、不对齐、不比较其 SQLite schema 作 production target、不写入 B7 migration plan。仅在 P2 最终 cutover 时确认生产 Agent 不再指向 callback。

---

## 33. Production Preflight SQL Pack（M2 READ-ONLY）

> 严格只读：仅 `SELECT / information_schema / pg_catalog`。无 `UPDATE/INSERT/DELETE/ALTER/CREATE/DROP/TRUNCATE/LOCK`。
> 用途：① 裁定 `PHYSICAL_SCHEMA_MATCHES_0028` vs `SCHEMA_DRIFT_FOUND`；② 0029 JSON 合法性 DATA_PRECONDITION；③ 0029/0030 锁风险行数；④ touched objects 指纹。

```sql
-- ============================================================
-- M2-A  Baseline / 三态复核
-- ============================================================
SELECT version_num AS db_alembic_version FROM alembic_version;
SELECT COUNT(*) AS public_table_count
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

-- 全部 public 表名（核对 58 与是否有 ahead-of-revision 表）
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;

-- ============================================================
-- M2-B  ahead-of-revision drift 检测（0029~0034 新对象，期望全 NOT EXISTS）
-- 任意一行 exists=t 表示生产已提前存在该对象 → SCHEMA_DRIFT / ahead-of-revision
-- ============================================================
SELECT 'daily_report_generations' AS obj, to_regclass('public.daily_report_generations') IS NOT NULL AS exists
UNION ALL SELECT 'ai_edit_material_analysis_executions', to_regclass('public.ai_edit_material_analysis_executions') IS NOT NULL
UNION ALL SELECT 'ai_preview_executions', to_regclass('public.ai_preview_executions') IS NOT NULL;

-- 新增列（期望 NOT EXISTS）
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema='public'
  AND (
        (table_name='compute_transactions'  AND column_name IN ('idempotency_key','payload_evidence'))
     OR (table_name='daily_report_jobs'    AND column_name='current_generation_id')
  );

-- 新增 UK 约束（期望 NOT EXISTS）
SELECT conname FROM pg_constraint
WHERE conname='uk_compute_transactions_merchant_idempotency';

-- 新增索引（期望 NOT EXISTS）
SELECT indexname FROM pg_indexes
WHERE schemaname='public'
  AND indexname IN ('idx_daily_report_generations_job',
                    'idx_ai_edit_material_analysis_executions_material',
                    'idx_ai_preview_executions_merchant');

-- 新增 CHECK（期望 NOT EXISTS）
SELECT conname FROM pg_constraint
WHERE conname IN ('ck_daily_report_generations_status',
                  'ck_ai_edit_material_analysis_executions_status',
                  'ck_ai_preview_executions_status');

-- ============================================================
-- M2-C  0029 DATA_PRECONDITION：customer_profiles 两列实际类型 + JSON 合法性
-- 期望 data_type='text'（0028）；若 'jsonb' → drift（0029 幂等，但须登记）
-- ============================================================
SELECT column_name, data_type, udt_name
FROM information_schema.columns
WHERE table_schema='public' AND table_name='customer_profiles'
  AND column_name IN ('confirmed_fields_json','inferred_fields_json');

-- 非法 JSON 行预检（任一返回 >0 → 0029 ALTER TYPE USING 会失败，须先治理）
SELECT id, 'confirmed_fields_json' AS col, confirmed_fields_json::text AS val
FROM customer_profiles
WHERE confirmed_fields_json IS NOT NULL
  AND confirmed_fields_json::text !~ '^\s*[\{\[]';
SELECT id, 'inferred_fields_json' AS col, inferred_fields_json::text AS val
FROM customer_profiles
WHERE inferred_fields_json IS NOT NULL
  AND inferred_fields_json::text !~ '^\s*[\{\[]';

-- ============================================================
-- M2-D  FK 父表存在性（0032 job_id → daily_report_jobs.id）
-- 期望 daily_report_jobs EXISTS
-- ============================================================
SELECT to_regclass('public.daily_report_jobs') IS NOT NULL AS parent_exists;

-- ============================================================
-- M2-E  锁风险行数（0029 表重写 / 0030 UK 扫描 / 0032 参考）
-- ============================================================
SELECT 'customer_profiles' AS t, COUNT(*) AS rows FROM customer_profiles
UNION ALL SELECT 'compute_transactions', COUNT(*) FROM compute_transactions
UNION ALL SELECT 'daily_report_jobs', COUNT(*) FROM daily_report_jobs;

-- ============================================================
-- M2-F  touched existing tables 指纹（列定义 + 约束 + 索引）
-- ============================================================
-- customer_profiles（0029 触及）
SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name='customer_profiles' ORDER BY ordinal_position;
SELECT conname, contype, pg_get_constraintdef(oid) AS def
FROM pg_constraint WHERE conrelid='public.customer_profiles'::regclass ORDER BY conname;
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='customer_profiles' ORDER BY indexname;

-- compute_transactions（0030 触及）
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name='compute_transactions' ORDER BY ordinal_position;
SELECT conname, contype, pg_get_constraintdef(oid) AS def
FROM pg_constraint WHERE conrelid='public.compute_transactions'::regclass ORDER BY conname;
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='compute_transactions' ORDER BY indexname;

-- daily_report_jobs（0032 触及）
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name='daily_report_jobs' ORDER BY ordinal_position;
```

---

## 34. Evidence Gaps（M2 后更新）

| 项 | 状态 | 说明 |
| -- | ---- | ---- |
| 生产拓扑 / owner / alembic | `USER_CONFIRMED_TOPOLOGY`（M1） | — |
| 生产 git HEAD / 代码 baseline | `GIT_HISTORY_VERIFIED`（f453f44） | — |
| revision graph / 迁移内容 | `MIGRATION_VERIFIED` | — |
| 应用代码依赖 | `CODE_VERIFIED` | — |
| 生产物理 schema 指纹 | `PRODUCTION_READ_ONLY_VERIFIED`（M2） | 0029 JSONB drift 已确认；其余 matches 0028 |
| 生产行数（锁风险） | `PRODUCTION_READ_ONLY_VERIFIED`（M2） | 1 / 1698 / 0 |
| 0029 JSON 合法性 | `PRODUCTION_READ_ONLY_VERIFIED`（M2） | 0/0 |
| 生产 Agent endpoint（B2/B5） | cutover 前，非本轮 blocker | — |

无 `UNKNOWN` 证据缺口（除 B2/B5 非本轮范围）。

---

## 35. Blockers（M2 后最终裁定）

| # | 问题 | 分类 | 裁定 |
| - | ---- | ---- | ---- |
| BLK-1 | 生产物理 schema 是否严格 0028 | SCHEMA_DRIFT | `SCHEMA_DRIFT_FOUND=YES`，scope=`0029_JSONB_TYPE_AHEAD_ONLY`；drift 方向与目标一致 + 0029 幂等兼容 → **非阻断**（NON_BLOCKING） |
| BLK-2 | 0029 customer_profiles JSON 合法性 | DATA_PRECONDITION | PASS（0/0）→ 非阻断 |
| BLK-3 | 0029/0030 锁风险行数 | MIGRATION_LOCK_RISK | LOW（1 / 1698 行）→ 非阻断 |

**无阻断 blocker。** drift 存在但方向正确且幂等兼容；data precondition 全 PASS；lock risk 全 LOW。无 `CODE_SCHEMA_COMPATIBILITY` blocker（§27/§29 兼容矩阵已定）。

---

## 36. Non-Blocking Notes

- 0029 `ALTER TYPE JSONB` 对已是 JSONB 的列幂等无副作用（若 M2-C 发现已 jsonb，仅登记 drift，不阻断）。
- 0030 UK 存量行全 NULL 不冲突；无去重修复。
- 0032 FK child 为新表无 orphan；父表 daily_report_jobs 0028 前已建（M2-D 复核）。
- 0033/0034 全新表 + server_default，零存量风险。
- 9db3f58 纯文档提交，树功能等同 eb9f182；1d7f1f5 亦合法 0034 baseline 备选。
- 全链无 DROP/TRUNCATE/RENAME/批量 DML；唯一非常规项为 0029 类型改。

---

## 37. Recommended Catch-up Strategy Input

**裁定：coordinated code+schema catch-up，schema-first 序列。** 本轮只分析不批准执行。

依据：
1. f453f44 旧代码对 0029~0034 全链前向兼容（§27）→ 可在旧代码仍服务时先迁移。
2. target 0034 代码（9db3f58）不能在 0028 schema 运行（§29）→ 不可 code-first。
3. 所有中间态对旧代码安全（`INTERMEDIATE_STATE_SAFE`）→ schema-first 可零停机（受限于 0029/0030 锁）。

推荐序列（输入，非批准）：
1. ~~M2 preflight 执行~~（已完成，见 §40）。
2. **isolated rehearsal（必须模拟生产 drift 事实）**：在隔离 PG 上构造 `alembic_version=0028` **但** `customer_profiles` 两 JSON 列已为 jsonb 的镜像（模拟真实生产物理 schema），用 9db3f58 迁移集 `alembic upgrade 0034` 验证 0029 对已-jsonb 列幂等不失败、0030~0034 正常建对象。**禁止只用纯净 fresh 0028 schema rehearsal**（其两列为 TEXT），否则无法覆盖真实生产升级路径。
3. **schema-first 迁移**：rehearsal 通过后，用 9db3f58 迁移集对生产 DB 执行 `alembic upgrade 0034`（9db3f58 处 head=0034，不含 0035），f453f44 旧代码继续服务（容忍 additive schema）。0029 幂等处理已-jsonb 列（表重写 1 行瞬时）；0030 ADD COLUMN + UK 扫描 1698 行。
4. **deploy target code**：部署 9db3f58 代码，消费者现具备 schema。
5. **验证**：/ready expected 升至 0034、/ready PASS、消费者 smoke。
6. **返回 P2 cutover 流程** → 0035（不在本轮）。

备选（code-first 但需停机）：部署 9db3f58 代码 + 维护态 + `alembic upgrade 0034` + 启动。downtime 更大，不推荐为首选。

---

## 38. Verdict（M2 最终裁定）

```
PRODUCTION_SCHEMA_CATCHUP_DESIGN_REQUIRED
```

- migration chain（0028→0029→0030→0032→0033→0034，0031 跳号纠正）、生产 code/schema baseline（f453f44 三态一致 0028）、code/schema 兼容矩阵、catch-up 策略（coordinated schema-first）均已建立。
- M2 最终裁定：`SCHEMA_DRIFT_FOUND=YES`（scope=`0029_JSONB_TYPE_AHEAD_ONLY`），但 0029 对已-jsonb 列幂等兼容（`0029_EXISTING_JSONB_COMPATIBILITY=PASS`），drift 方向与目标一致 → 非阻断。全部 DATA_PRECONDITION=PASS。lock risk 全 LOW（实际 1/1698/0 行）。
- **gate 关闭**：`PHYSICAL_SCHEMA_VERIFICATION = VERIFIED`（M2 已裁定）。不再 `PENDING_M2`。
- **不输出** `READY_TO_MIGRATE`（本轮仍为审计/设计阶段，执行需独立批准 + isolated rehearsal）。
- **不输出** `BLOCKED_BY_SCHEMA_DRIFT`（0029 幂等兼容）或 `BLOCKED_BY_DATA_PRECONDITION`（全 PASS）。
- 不重新打开 P1 TECHNICAL_CLOSURE；不进入 0035/P3a/RB-10。

---

## 39. Next Stage

1. ~~用户执行 §33 M2 READ-ONLY SQL PACK 并回传结果~~（已完成）。
2. ~~据结果裁定 `PHYSICAL_SCHEMA_MATCHES_0028` 或 `SCHEMA_DRIFT_FOUND`~~（已裁定：`SCHEMA_DRIFT_FOUND`，scope=`0029_JSONB_TYPE_AHEAD_ONLY`，非阻断）。
3. **下一阶段 = Catch-up Design/Verification**：
   a. **isolated rehearsal（模拟生产 drift 事实）**：隔离 PG 构造 `alembic_version=0028` + customer_profiles 两列已 jsonb 镜像 → 用 9db3f58 迁移集 `alembic upgrade 0034` 验证 0029 幂等 + 0030~0034 建对象。禁止纯净 fresh 0028（TEXT 列）rehearsal。
   b. rehearsal 通过 → Catch-up Design 文档（schema-first 序列、回滚策略、验证检查点）→ 独立审批。
   c. 批准后执行（独立执行窗口，需显式批准）。
4. 0034 catch-up 完成 + verify 后，返回 P2 cutover 流程处理 0035。

---

## 40. M2 Final Adjudication（逐项最终裁定）

M2 证据层级 = `PRODUCTION_READ_ONLY_VERIFIED`（READ ONLY 事务 `transaction_read_only=on` 已确认；`statement_timeout=120s`/`lock_timeout=3s` 只读安全）。

### 40.1 物理 schema 严格匹配

```
1. PHYSICAL_SCHEMA_STRICT_MATCH_0028 = NO
2. SCHEMA_DRIFT_FOUND                = YES
3. SCHEMA_DRIFT_SCOPE                = 0029_JSONB_TYPE_AHEAD_ONLY
```

精确 drift 对象（仅 2 列，不泛化）：
- `customer_profiles.confirmed_fields_json`：物理 `jsonb`，0028 定义 `TEXT`，0029 定义 `JSONB` → 0029 类型变更已提前落地。
- `customer_profiles.inferred_fields_json`：同上。

0030~0034 新对象全 NOT EXISTS；touched existing tables 其余定义与 0028 一致；父表 `daily_report_jobs` EXISTS。drift 方向与 catch-up 目标一致（ahead-of-revision 且方向正确）。

### 40.2 0029 对已-jsonb 列兼容性

```
4. 0029_EXISTING_JSONB_COMPATIBILITY = PASS
```

`MIGRATION_VERIFIED` + 推理：0029 `upgrade()` 用 `op.alter_column(type_=JSONB, postgresql_using="confirmed_fields_json::text::jsonb")`。alembic 不比较列现有类型，直接发 `ALTER TABLE ... ALTER COLUMN ... TYPE jsonb USING col::text::jsonb`。当列已是 jsonb：
- PG 逐行执行 `jsonb::text::jsonb`——任何合法 jsonb 值转换均合法，NULL 保持 NULL。
- 不报错、幂等、语义安全（迁移文件头已注明"对已是 JSONB 的列…无副作用"）。
- 唯一代价：表重写（ACCESS EXCLUSIVE），但 customer_profiles=1 行 → 瞬时。

**不选 B（重复 ALTER 失败）**：PG 对同类型 ALTER TYPE USING 不失败，仅重写。结论 = 安全识别/幂等处理（A），非阻断。

### 40.3 各迁移 DATA_PRECONDITION

```
5.  0029_DATA_PRECONDITION = PASS   （invalid_confirmed=0, invalid_inferred=0）
6.  0030_DATA_PRECONDITION = PASS   （列不存在→全 NULL 不冲突 UK）
7.  0032_DATA_PRECONDITION = PASS   （parent_exists=t；child 新表无 orphan）
8.  0033_DATA_PRECONDITION = PASS   （新表无存量）
9.  0034_DATA_PRECONDITION = PASS   （新表无存量）
```

### 40.4 各迁移生产 lock/runtime risk（实际行数）

M2 行数：`customer_profiles=1`、`compute_transactions=1698`、`daily_report_jobs=0`。

| 迁移 | 操作 | 行数 | 风险 |
| ---- | ---- | ---- | ---- |
| 0029 | ALTER TYPE ×2（jsonb→jsonb 幂等重写，ACCESS EXCLUSIVE） | 1 | **LOW** |
| 0030 | ADD COLUMN ×2 nullable（元数据级） | 1698 | **LOW** |
| 0030 | CREATE UNIQUE CONSTRAINT（AccessExclusive 扫表，存量全 NULL） | 1698 | **LOW** |
| 0032 | CREATE TABLE + ADD COLUMN nullable + INDEX(新表) | daily_report_jobs=0 | **LOW** |
| 0033 | CREATE TABLE + INDEX(新表) | 新表 0 | **LOW** |
| 0034 | CREATE TABLE + INDEX(新表) | 新表 0 | **LOW** |

全链 = LOW。不再 `UNKNOWN_UNTIL_ROWCOUNT`。

### 40.5 Target code baseline & 序列确认

```
10. TARGET_0034_CODE_COMMIT = 9db3f58   （再次确认，M2 不改变代码 baseline 判定）
11. Candidate sequence 仍成立：
    f453f44 + DB(0028 + 0029 JSONB drift)
    → isolated rehearsal（模拟 drift 事实）
    → target migration set (9db3f58) schema-first 升至 0034
    → verify old f453f44 remains healthy
    → deploy 9db3f58
    → verify /ready expected=actual=0034
    → baseline catch-up production verification
    → return P2
    → 0035 later
```

### 40.6 Rehearsal 必须模拟生产 drift 事实

当前生产物理 schema 非严格 0028（两 JSON 列已 jsonb）。后续 isolated rehearsal **必须**构造 `alembic_version=0028` + `customer_profiles` 两列 jsonb 的镜像，验证真实升级路径（0029 对已-jsonb 列幂等）。**禁止**只用纯净 fresh 0028 schema（TEXT 列）rehearsal——那无法覆盖 0029 的真实生产行为，会给出虚假"安全"结论。

### 40.7 最终 Verdict

```
PRODUCTION_SCHEMA_CATCHUP_DESIGN_REQUIRED
```

- 0029 安全兼容局部 drift（PASS）+ 所有 preconditions PASS + lock risk 全 LOW → 足以进入 Catch-up Design/Verification。
- gate `PHYSICAL_SCHEMA_VERIFICATION = VERIFIED`。
- 不输出 `READY_TO_MIGRATE`；不输出 `BLOCKED_BY_SCHEMA_DRIFT`；不输出 `BLOCKED_BY_DATA_PRECONDITION`。

---

*审计窗口结束。未执行任何迁移、未改代码/迁移、未 commit、未 push、未部署。仅留下本 audit candidate 文件。*
