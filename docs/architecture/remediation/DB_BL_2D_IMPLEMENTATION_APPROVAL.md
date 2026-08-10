# DB-BL-2D-IMPLEMENTATION 独立审批报告

> 阶段：DB-BL-2D **Implementation — Independent Approval Window**
> 日期：2026-08-10
> 审批窗口：DB-BL-2D Legacy PostgreSQL Baseline Repair 独立审批窗口
> 审查对象：执行窗口提交的 Legacy PostgreSQL Baseline Repair 实施成果（`DB_BL_2D_IMPLEMENTATION_REPORT.md` + 候选 Git diff + 实际 PG 库状态）
> 工作原则：只读核验 → 不采信执行窗口自述 → 对照 2C/2B 冻结事实 + 实际 runtime 证据逐项判定 → 不修改代码/数据库/文档、不自行 commit、不开始 consumer PG verification。
> 范围：LOCAL DEVELOPMENT ONLY（本机 Docker `auto-wechat-postgres-dev` @ 5432 的 `auto_wechat` 库）。

---

## 审批结论（TL;DR）

```
审批状态 = APPROVED_WITH_CORRECTIONS
SCHEMA_BASELINE_MISMATCH = REMEDIATED
AUTO_WECHAT_DEV_PG      = CANONICAL_ALEMBIC_BASELINE@0034
DB-BL                   = REPAIR_VERIFIED / COMPLETE
COMMIT_CURRENT_APPROVED_DIFF = AUTHORIZED（须随附 CR-4 措辞修正，见 §22）
```

核心 Gate（DBR-3/4/5/6）全部独立复现通过；schema baseline 已确认为 canonical Alembic@0034。唯一修正项为 CR-4「application role permissions = granted」的**报告措辞与实际库不符**——不影响数据库正确性、不影响 schema baseline canonical 性质，属报告精度修正。

---

## 1. Technical Decision

```
DB-BL-2D-IMPLEMENTATION:
APPROVED_WITH_CORRECTIONS
```

执行窗口实际 repair 严格符合批准的 Strategy A / Replace-Before-Delete（A1 rename）：
- legacy `auto_wechat` → RENAME 保留为 `auto_wechat_legacy_backup`（未 DROP）；
- 新建空 `auto_wechat`；
- `EMPTY → alembic upgrade head → 0034`；
- 无 create_all / stamp / schema copy / manual business DDL。

repair 本身成立，2C 冻结输入未被违反，`STAMP_0030 = REJECTED` 仍为不可选项。CR-1~CR-8 已原位回写设计文档。唯一修正：CR-4 的 app-role 授权状态在报告中**过度声明**（见 §10 / §22），需按实际库状态纠正措辞。

---

## 2. Candidate Git Scope

审批开始即冻结 worktree。candidate diff 指纹（tracked）：

```
git diff (tracked) sha256 = ea967053919343e3e84adf7f6a8a613d66322a07850e6e850bfdfe8e81f73252
```

Tracked 改动（4 文件，42 行 +）：

| 文件 | 性质 |
|---|---|
| `scripts/init_db.py` | PostgreSQL RESTRICT guard（PG→sys.exit(1)，SQLite 保留 create_all）|
| `README.md` | §2 区分 SQLite 用 init_db.py / PG 用 alembic upgrade head |
| `docs/architecture/RUNTIME_ENTRYPOINTS.md` | init_db.py 标注 SQLite-only（PG refused）|
| `docs/architecture/remediation/DB_BL_2C_EXACT_RECONCILIATION.md` | 历史阻断证据头部标注（保留不删）|

Untracked（2D/2C 治理文档 + evidence + helper + 测试）：

```
docs/architecture/remediation/DB_BL_2C_EXACT_RECONCILIATION_RESUME.md
docs/architecture/remediation/DB_BL_2C_R2_APPROVAL.md
docs/architecture/remediation/DB_BL_2C_RESUME_APPROVAL.md
docs/architecture/remediation/DB_BL_2D_APPROVAL.md
docs/architecture/remediation/DB_BL_2D_IMPLEMENTATION_REPORT.md
docs/architecture/remediation/DB_BL_2D_LEGACY_POSTGRES_BASELINE_REPAIR_STRATEGY.md
docs/architecture/remediation/db_bl_2c_resume_evidence/   （2C 冻结 canonical evidence）
scripts/db_bl_2c_resume_snapshot.py
tests/test_init_db_postgres_guard.py
```

确认：
- **无 migration 变化**（migrations/ 未触）；
- **无 ORM 变化**（app/models/ 未触）；
- **无 P1 Consumer 变化**（charge path 未触）；
- **无 M07 Core 变化**（record_usage / 0030 未触）；
- **无凭据**（报告/脚本/init_db 均无口令；口令仅本地 throwaway `change_me`，未写入任何 candidate 文件）；
- **dump/snapshot 未入 Git**：`docker-data/` 命中 `.gitignore:81`，`docker-data/db_bl_2d_rollback/auto_wechat_legacy.dump` 与 `new_actual_0034.json`、`independent_new_0034.json` 均未被跟踪；
- 2C evidence（`db_bl_2c_resume_evidence/expected_0034.json` 等）为既有未跟踪的冻结 canonical 参考，属 2C 产物，与本轮 2D candidate 在语义上应区分，但作为 frozen verification authority 应随相关治理文档一并入库（见 §22 commit scope 纪律）。

审批期间未修改 worktree。

---

## 3. CR-1 ~ CR-8

逐项核验设计文档 `DB_BL_2D_LEGACY_POSTGRES_BASELINE_REPAIR_STRATEGY.md` 是否完成审批要求的八项修正：

| CR | 要求 | 核验 | 落点 |
|---|---|---|---|
| CR-1 | provenance = MOST PLAUSIBLE / CURRENT RISK ENTRY，不得声称已证明 | ✅ APPLIED | §11.2：明确 `MOST PLAUSIBLE PROVENANCE / INFERRED`，RESTRICT 理由为 prevention closure（消除已知风险入口），非 provenance 证明 |
| CR-2 | 显式 Service Quiescence Gate RB-Q | ✅ APPLIED | §8a：rename 前硬前置 quiesce gate，列 9000/workers/alembic/scripts/dev server |
| CR-3 | DATABASE_URL config value ≠ existing connections | ✅ APPLIED | §2.4/§6.2：明确 config value 不变 vs 既有连接须重启重连，禁用"零切换"表述 |
| CR-4 | Database-Level Contract（owner/permission/extension）| ⚠️ APPLIED（设计存在）但实施报告措辞与实际库不符，见 §10/§22 | §7.4：区分 LEGACY vs PROJECT REQUIRED 属性 |
| CR-5 | Verification Authority = frozen 2C expected_0034.json | ✅ APPLIED | §9.2：主参考冻结为 `db_bl_2c_resume_evidence/expected_0034.json`，fresh snapshot 仅 supplemental |
| CR-6 | Seed/Bootstrap Runtime Gate：empty≠runnable | ✅ APPLIED | §9.3：明确空业务库≠可运行，须 /ready 实跑确认 |
| CR-7 | Rollback 顺序 + 原子停止点 | ✅ APPLIED | §8/§8b：dump→verify dump→quiesce→rename→create，各失败点 STOP 规则 |
| CR-8 | unlock label = UNBLOCKED_FOR_PG_VERIFICATION（不写 PG_VERIFIED）| ✅ APPLIED | §12.2：精确标签，仅一档不跳级 |

```
CR-1~CR-8: 7 项 APPLIED；CR-4 设计层 APPLIED 但实施报告 §9 措辞需修正（不影响策略与 schema 正确性）
```

---

## 4. init_db Guard

独立读代码 + 独立复现测试。

### 4.1 代码（`scripts/init_db.py`）

- `init_db()` 首行 `runtime = get_database_runtime()`；
- PostgreSQL 分支：打印明确错误（"PostgreSQL schema must be created/evolved by Alembic."）+ 提示 `alembic ... upgrade head` + `sys.exit(1)`。**拒绝 create_all，不 fallback、不 stamp、不 upgrade、不隐式补 schema**；
- 非 sqlite / 非 postgresql：`sys.exit(1)`；
- SQLite：保留 `Base.metadata.create_all(bind=engine)` + `DEFAULT_CONFIGS` seed 既有行为不变；
- 与 `app/main.py:273 ensure_runtime_schema()`（PG `startup_skip_create_all`，main.py:281 日志确认）语义对齐，runtime + bootstrap 工具双重拦截。

### 4.2 独立复现测试

```
tests/test_init_db_postgres_guard.py::test_init_db_refuses_postgresql   PASS
tests/test_init_db_postgres_guard.py::test_init_db_allows_sqlite        PASS
tests/test_9000_postgres_runtime_startup.py::test_postgresql_runtime_does_not_auto_create_schema  PASS
tests/test_9000_postgres_runtime_startup.py::test_sqlite_runtime_keeps_auto_create_schema         PASS
```

独立运行 **4 passed**（与执行窗口声称一致）。

```
POSTGRES_GUARD          = VERIFIED
SQLITE_COMPATIBILITY    = VERIFIED
```

---

## 5. Environment Identity

```
LOCAL DEVELOPMENT ONLY
NOT PRODUCTION / NOT STAGING
```

| 维度 | 值 | 核验 |
|---|---|---|
| 容器 | `auto-wechat-postgres-dev`（Up 5 hours (healthy)，PG 16）| `docker ps` 确认 |
| host:port | `127.0.0.1:5432`（0.0.0.0:5432->5432/tcp）| 确认 |
| 数据库 | `auto_wechat`（新）+ `auto_wechat_legacy_backup`（legacy）| `\l` 确认二者并存 |
| 其他库（未触碰）| `xg_douyin_ai_cs` / `auto_wechat_outbox_test` / `postgres` / `template0/1` | 确认存在未动 |
| 环境分类 | local development | 确认 |

生产/staging 未被执行任何 DB 操作。

---

## 6. Disposability

独立只读 COUNT legacy backup（`auto_wechat_legacy_backup`）：

| 表 | 行数 |
|---|---|
| compute_transactions | 3 |
| compute_accounts | 1 |
| compute_markup_ratios | 1 |
| douyin_leads | 0 |
| customer_profiles | 0 |
| sales_lead_feedbacks | 0 |
| wechat_tasks | 0 |
| **合计** | **5** |

与 2C 冻结（5 行、无 PII、可由 fixture 重建）**精确一致**。

```
DISPOSABILITY_RECONFIRMED
```

（未输出任何 PII 内容。）

---

## 7. Rollback Dump

| 项 | 值 | 核验 |
|---|---|---|
| 路径 | `docker-data/db_bl_2d_rollback/auto_wechat_legacy.dump` | 确认 |
| 格式 | pg_dump custom-format（gzip）| `pg_restore --list` header `Compression: gzip` 确认 |
| 大小 | 383,285 bytes（>0）| `ls -la` 确认 |
| 完整性 | `pg_restore --list` 成功：TOC 1162 entries，**57 DATA entries**，dbname=auto_wechat | 独立 `docker exec -i ... pg_restore --list`（stdin，read-only，无挂载）复现 |
| Git ignore | `.gitignore:81 docker-data/` 命中 | `git check-ignore -v` 确认 |
| 未入 Git | `git ls-files docker-data/` 空 | 确认 |
| 凭据泄漏 | 无 | dump 不含口令 |

```
ROLLBACK_DUMP = VERIFIED
```

未删除，保留作 rollback artifact。

---

## 8. Legacy Backup

独立连接 `auto_wechat_legacy_backup` 只读确认：

- 库存在（owner=auto_wechat，UTF8，en_US.utf8）；
- 57 业务表仍在；
- `has_alembic_version_table = false`（从未经 Alembic 管理，未被偷偷 stamp）；
- 数据仍在（5 行：compute_*=3/1/1，PII 表全 0）；
- 未被 DROP、未 upgrade、未 stamp；
- 可作为 rollback identity（rename 回切或 pg_restore）。

```
LEGACY_BACKUP: RETAINED / RECOVERABLE
```

---

## 9. Replacement Database Identity

核验新 `auto_wechat` 是 rebuild 后的新库，而非旧库原地 repair：

- database identity 正确（新建空库，owner=auto_wechat）；
- business schema 来自 Alembic（`EMPTY → alembic upgrade head`，非 schema copy）；
- 无 create_all（init_db.py 在 PG 下被 RESTRICT 拒绝；ensure_runtime_schema PG skip）；
- 无 schema copy、无 stamp、无 manual business DDL；
- alembic_version 由框架首次 upgrade 自动创建（1 行，version_num=0034），**非人为 stamp**。

```
REPLACEMENT_IDENTITY = NEW REBUILD（非原地 repair）
```

---

## 10. Database-Level Contract

独立只读核验新 `auto_wechat` properties：

| 维度 | 报告值 | 实际值 | 核验 |
|---|---|---|---|
| database owner | `auto_wechat` | `auto_wechat` | ✅ `\l` 确认 |
| encoding | UTF8 | UTF8 | ✅ |
| locale | en_US.utf8 | en_US.utf8（libc）| ✅ |
| required extensions | 无（仅 plpgsql）| 仅 plpgsql | ✅ `pg_extension` 确认，migration chain 无 CREATE EXTENSION 依赖 |
| **application role permissions** | **GRANT auto_wechat 表读写+序列+default privileges** | **❌ 未落地** | ⚠️ 见下 |

**CORRECTION（CR-4 精度修正，不影响 schema baseline）**：

实施报告 §9 与 §16 DBR 表声称"app role permissions = granted（CR-4）"——对 `auto_wechat` 角色 GRANT 了表 SELECT/INSERT/UPDATE/DELETE + 序列 USAGE/SELECT + DEFAULT PRIVILEGES。独立只读核验显示**与实际库不符**：

```
table owners                = postgres（全部 61 表，alembic 以 superuser 跑）
role_table_grants(auto_wechat) = EMPTY（无 SELECT/INSERT/UPDATE/DELETE）
sequence grants(auto_wechat)   = 0
pg_default_acl(public)         = EMPTY（无 default privileges）
douyin_leads.relacl            = NULL（仅 owner postgres 隐式访问）
auto_wechat role              = 存在、rolcanlogin=t，但无任何表/序列访问权限
public schema nspacl          = {pg_database_owner=UC, =U}（PUBLIC 仅 USAGE，无表访问）
```

即：报告所述 GRANT 在实际库中**未生效/未落地**。`/ready`（DBR-6）是以 `postgres` superuser 验证的，故未暴露此 gap——DBR-6 不证明 `auto_wechat` app 角色可用。

影响评估：
- **不影响 schema baseline 正确性**（DBR-4 独立 diff=0，canonical Alembic@0034）；
- **不影响 SCHEMA_BASELINE_MISMATCH 关闭**（该 blocker 是 schema 非 canonical 问题，已解决）；
- **不阻断 0032/0033/0034 解锁**（解锁条件是 schema baseline canonical，已满足）；
- 仅意味着：若以 `auto_wechat` app 角色连接 PG 跑应用，会因无表权限失败；默认本地开发配置仍为 SQLite（见 §16），故不阻塞当前 baseline；后续 consumer PG verification（0032/0033/0034）若用 app 角色须先补 GRANT，或以 superuser 连接。

```
DATABASE_LEVEL_CONTRACT:
  owner / encoding / locale / extensions = VERIFIED
  application role permissions           = NOT GRANTED（报告措辞需修正，见 §22）
```

---

## 11. Alembic Bootstrap

独立确认新 `auto_wechat` 由 `EMPTY → alembic upgrade head → 0034` 产生：

```
alembic_version.version_num = 0034          （psql 确认）
alembic_version row count    = 1            （单头）
physical tables              = 61           （60 business + 1 alembic_version）
business tables (excl alembic_version) = 60
```

`alembic_version` 由框架首次 upgrade 自动创建，非人为 stamp（DB 为新建空库，唯一填充路径是 `alembic upgrade head`；2C 已 PG_RUNTIME_VERIFIED `EMPTY→0034` PASS）。

```
PG_RUNTIME_VERIFIED
```

---

## 12. Frozen Expected Comparison

**最重要 Gate 之一。** 独立复现（非采信预生成 `dbr4_diff.txt`）：

1. 以 `scripts/db_bl_2c_resume_snapshot.py`（与 2C 同一套只读 catalog inspection contract）对新 `auto_wechat` 生成 fresh snapshot（连 `postgres@127.0.0.1:5432/auto_wechat`，read-only）；
2. 与 **2C 冻结** `docs/architecture/remediation/db_bl_2c_resume_evidence/expected_0034.json`（主 canonical 参考，非本轮重新生成）做 diff。

独立复现结果：

```
=== INDEPENDENT DBR-4: New auto_wechat vs FROZEN Expected@0034 ===
counts: semantic=0 name_only=0 normalization_only=0
```

新库对象计数（与 R2 MR-4 @0034 吻合）：

```
tables=60  columns=932  primary_keys=61  foreign_keys=21
unique_constraints=42  check_constraints=33  indexes_standalone=128
```

```
STRUCTURAL_DIFF = 0
METADATA_DIFF   = 0
NAME_ONLY_DIFF  = 0
```

三项全 0，主参考为 2C 冻结快照（未用本轮重新生成覆盖 canonical）。fresh `independent_new_0034.json` 存 gitignore 路径，未覆盖 frozen canonical。

```
FROZEN_EXPECTED_EXACTNESS = VERIFIED
```

---

## 13. Runtime Bootstrap Data

独立核验：

1. 新 PG `check_configs` 确实为空（`SELECT count(*) = 0`，psql 确认）；
2. `/ready` 在空 `check_configs` 下 PASS（config 读取器有默认回退，空表不阻断启动；见 §14）；
3. 未调用 `scripts/init_db.py` 给 PG 补 seed（PG 下被 RESTRICT 拒绝）；
4. 未 INSERT 任何 seed、未恢复 5 条旧 compute_* 测试数据（DISPOSABLE）；
5. application startup 未通过其他 create_all/init path 偷偷补数据（ensure_runtime_schema PG skip；init_db.py PG RESTRICT）。

```
RUNTIME_BOOTSTRAP_DATA_GAP: NOT OBSERVED
```

（仅证明当前 baseline readiness 不被缺失 seed 阻断，不证明未来所有业务都不需要 config data。）

---

## 14. PostgreSQL /ready Evidence

**独立复现，确认针对新 PG、非 SQLite。**

以显式 PG `DATABASE_URL=postgresql://postgres:***@127.0.0.1:5432/auto_wechat`、`EXPECTED_DATABASE_NAME=auto_wechat`，用 httpx ASGITransport（不触发 lifespan，避免热键/overlay/调度器）调用 `/ready`：

```
HTTP 200
status: ok
checks:
  backend          pass  backend=postgresql
  db_connect       pass  （application 连接新 DB 成功）
  database_name    pass  expected=auto_wechat, actual=auto_wechat
  alembic_revision pass  expected=0034, actual=0034
  critical_tables  pass  douyin_leads, sales_staff 存在并可查
```

证明：runtime DB backend = PostgreSQL ✅ / current_database() = auto_wechat ✅ / host:port = 本地 dev PG 127.0.0.1:5432 ✅ / alembic revision = 0034 ✅ / 无 create_all fallback ✅ / bootstrap 不阻断 ready ✅。

import app.main 时日志确认 `db_schema stage=startup_skip_create_all backend=postgresql`——runtime 守卫生效。

> 注意：/ready 以 `postgres` superuser 验证，未证明 `auto_wechat` app 角色访问（见 §10）。不阻断 DBR-6（任务 §15 要求证明 /ready 针对新 PG 而非 SQLite，已满足）。

```
DBR-6 = PASS（against NEW PostgreSQL, NOT SQLite）
```

---

## 15. Minimal Smoke

- `create_app()` 在 PG DATABASE_URL 下成功（`ensure_runtime_schema` PG skip，无 create_all，import 时日志确认）；
- DB read path：`/ready` critical_tables（douyin_leads/sales_staff）可查 ✅；
- config read path：`check_configs` 可读（0 行，空表不阻断）✅；
- database readiness：见 §14。

既有 `smoke_9000_postgres_startup.py` 复用；其 route 检查在新版 FastAPI 下有预存 bug（`_IncludedRouter.path`），非本轮引入、非本轮范围，create_app 本身成功。

未扩展为完整业务 E2E（Daily Report / M05 / Preview 不在本轮范围，属后续独立阶段）。

```
DBR-7 = PASS
```

---

## 16. Default Local Runtime Configuration 分层

确认 `.env.development.local` / `.env.lan.local` / `.env.development.example` 的 `DATABASE_URL` 默认仍指向 SQLite。本 2D 任务**未授权**把默认开发环境切换为 PG，故**不修改 `.env.*` 是正确的 scope compliance**。

```
AUTO_WECHAT DEV POSTGRES BASELINE:
CANONICAL / READY（schema = Alembic@0034）

DEFAULT LOCAL DEVELOPMENT APP CONFIG:
STILL SQLITE（未切换）
```

"PG baseline repaired" ≠ "all local development now defaults to PG"。两者不同，审批报告明确区分。

---

## 17. DBR-0 ~ DBR-9 独立 Verdict

| Gate | 要求 | 独立 Verdict | 独立证据 |
|---|---|---|---|
| DBR-0 | Strategy approved（独立审批）| **PASS** | 2D APPROVAL = APPROVED_WITH_CORRECTIONS |
| DBR-1 | Environment identity（LOCAL DEV ONLY）| **PASS** | `docker ps` + `\l`，非 prod/staging |
| DBR-2 | Rollback artifact ready（dump verified）| **PASS** | pg_restore --list TOC 1162 / 57 DATA（独立 stdin 复现）|
| DBR-3 | Alembic bootstrap（EMPTY→0034）| **PASS** | 61 表，alembic_version=0034，非 stamp |
| DBR-4 | New Actual == frozen Expected@0034（三 0）| **PASS** | 独立 snapshot+diff = 0/0/0（frozen canonical）|
| DBR-5 | Revision identity（current=head=0034，单头）| **PASS** | version_num=0034，1 行 |
| DBR-6 | /ready PASS（against NEW PG）| **PASS** | HTTP 200，backend=postgresql，db=auto_wechat，rev=0034（非 SQLite）|
| DBR-7 | Minimal smoke PASS | **PASS** | create_app PG skip + read path + readiness |
| DBR-8 | Legacy retained & recoverable | **PASS** | legacy_backup 57 表 + 5 行 + 无 alembic，未被 DROP/upgrade/stamp |
| DBR-9 | Prevention closure（init_db guard + doc sync）| **PASS** | 4 passed + README/RUNTIME_ENTRYPOINTS 同批 |

RB-Q Service Quiescence（CR-2）：PASS（执行窗口证据 0 connections；当前无 9000/worker 进程持有 `auto_wechat` PG 连接，默认 env 仍 SQLite）。

核心 Gate DBR-3/4/5/6 全部独立 PASS。任一核心 Gate 未失败。

---

## 18. SCHEMA_BASELINE_MISMATCH Verdict

核心 Gate（DBR-3/4/5/6）独立通过：

```
SCHEMA_BASELINE_MISMATCH:
BLOCKING → REMEDIATED

AUTO_WECHAT_DEV_PG:
CANONICAL_ALEMBIC_BASELINE@0034

DB-BL:
REPAIR_VERIFIED / COMPLETE
```

可正式关闭 `SCHEMA_BASELINE_MISMATCH`。

---

## 19. 0032 / 0033 / 0034 Unlock Status

```
0032 Daily Report:
  BLOCKED_BY_SCHEMA_BASELINE_MISMATCH → UNBLOCKED_FOR_PG_VERIFICATION

0033 M05 Material Analysis:
  BLOCKED_BY_SCHEMA_BASELINE_MISMATCH → UNBLOCKED_FOR_PG_VERIFICATION

0034 Preview:
  BLOCKED_BY_SCHEMA_BASELINE_MISMATCH → UNBLOCKED_FOR_PG_VERIFICATION
```

**仅此一档，不跳级，不写 `PG_VERIFIED`。** Consumer 层证据（write/read、idempotency、schema behavior）仍需独立取得，属后续独立阶段。

新库已含三张实体表（独立确认）：`daily_report_generations` / `ai_edit_material_analysis_executions` / `ai_preview_executions`，证明三条 migration 在链中正常落地（结构性可达）。

---

## 20. P1 Status

```
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE       = PENDING
```

DB-BL repair 完成 ≠ P1 关闭。P1 Technical Closure 仍至少包括：

- 0032 Daily Report consumer PG verification
- 0033 M05 Material Analysis consumer PG verification
- 0034 Preview consumer PG verification
- RAG Query 0005 PG verification（xg_douyin_ai_cs，BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT，不在 2D 范围）
- Global Active None Audit
- Final PostgreSQL Concurrent Closure Gate

本审批窗口**不关闭 P1**。

---

## 21. Cleanup Status

```
RB-10 CLEANUP:
NOT AUTHORIZED
```

- `auto_wechat_legacy_backup` **不得删除**（仍保留作 rollback identity）；
- rollback dump **继续保留**（`docker-data/db_bl_2d_rollback/auto_wechat_legacy.dump`）；
- 后续是否 cleanup 单独决定。

---

## 22. Commit Authorization

```
COMMIT_CURRENT_APPROVED_DIFF: AUTHORIZED
```

条件：

1. 审批后不得再改变代码逻辑（`scripts/init_db.py` 守卫逻辑冻结）；
2. **须随附 CR-4 措辞修正**（见下）——实施报告 `DB_BL_2D_IMPLEMENTATION_REPORT.md` §9 与 §16 DBR 表的 app-role 授权声明需按实际库状态纠正；
3. commit 前再次比较 candidate diff（应与指纹 `ea967053...8f73252` 一致，除 CR-4 措辞修正外不变）；
4. commit 内容必须与审批 scope 一致（init_db.py + README + RUNTIME_ENTRYPOINTS + 2C历史标注 + 2D/2C 治理文档 + helper + 测试 + 2C frozen evidence）；
5. 不得顺手加入 dump/snapshot（`docker-data/` 已 gitignore，确认未跟踪）、无关未跟踪文件；
6. commit 后报告 hash 和 final file list。

### CR-4 措辞修正要求（必须随 commit 落地）

`DB_BL_2D_IMPLEMENTATION_REPORT.md` §9 Database-Level Contract 与 §16 DBR-9 行，将：

```
application role permissions = auto_wechat GRANT USAGE on public + SELECT/INSERT/UPDATE/DELETE on tables + USAGE/SELECT on sequences + DEFAULT PRIVILEGES（CR-4）
```

修正为反映实际库状态，例如：

```
application role permissions = NOT GRANTED。alembic 以 postgres superuser 运行，故全部 61 表 owner=postgres；
  auto_wechat 角色存在且可 LOGIN，但无任何表/序列访问权限、无 default privileges（role_table_grants=空、sequence grants=0、pg_default_acl=空）。
  /ready（DBR-6）以 postgres superuser 验证，未证明 auto_wechat app 角色表访问。
  影响：不阻断 schema baseline canonical（DBR-4 diff=0）；默认本地开发配置仍 SQLite；
  后续 consumer PG verification（0032/0033/0034）若以 app 角色连接须先补 GRANT，或以 superuser 连接。
```

此为报告精度修正，不影响数据库正确性，不影响 schema baseline，不改变审批结论（APPROVED_WITH_CORRECTIONS）。

### 建议 commit message（中文）

```
修复：重建本地PostgreSQL Alembic基线@0034（DB-BL-2D）

- scripts/init_db.py：PostgreSQL RESTRICT 守卫（PG 拒绝 create_all，SQLite 保留）
- 重建 auto_wechat dev PG：legacy rename 保留 + 空库 alembic upgrade head@0034
- schema 对账：新库 vs 冻结 Expected@0034 = 0/0/0
- /ready 针对新 PG HTTP 200（backend=postgresql, alembic=0034）
- 0032/0033/0034 解锁 UNBLOCKED_FOR_PG_VERIFICATION（不跳级）
- legacy backup 与 dump 保留（RB-10 未授权清理）
```

---

## 23. 独立审批窗口停止声明

DB-BL-2D Implementation 独立审批完成。核心 Gate（DBR-3/4/5/6）独立复现通过，SCHEMA_BASELINE_MISMATCH 关闭为 REMEDIATED，0032/0033/0034 解锁 UNBLOCKED_FOR_PG_VERIFICATION，commit 授权（附 CR-4 措辞修正）。

**未做**：修改代码/数据库/文档（除本审批报告）、自行 commit、DROP legacy、开始 0032/0033/0034 consumer PG verification、RAG Query 0005、Global None Audit、Final PG Closure、宣布 P1 关闭。

完成即停止。
