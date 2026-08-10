# DB-BL-2D — Legacy PostgreSQL Baseline Repair 实施报告

> 阶段：DB-BL-2D **Implementation**
> 日期：2026-08-10
> 窗口：DB-BL-2D Legacy PostgreSQL Baseline Repair 执行窗口
> 授权：`DB_BL_2D_APPROVAL.md` = `APPROVED_WITH_CORRECTIONS`（Strategy A / Replace-Before-Delete / A1 rename），`AUTHORIZED (CONDITIONAL ON CR-1~CR-8 APPLIED)` — CR 已回写。
> 范围：**LOCAL DEVELOPMENT ONLY**（本机 Docker `auto-wechat-postgres-dev` @ 5432 的 `auto_wechat` 库）。非 prod / 非 staging / 不改 P1 Consumer / 不改 M07 Core / 不 DROP legacy。
> Source of Truth：真实 PG runtime 证据 > 冻结文档 > 推测。

---

## 1. Scope

| 类别 | 范围 |
|---|---|
| 文档 | CR-1~CR-8 原位回写 `DB_BL_2D_LEGACY_POSTGRES_BASELINE_REPAIR_STRATEGY.md`（§2.4/§6.2/§7.4/§8/§8a/§8b/§9.2/§9.3/§11.2/§12.2/§16 + 文末结论）；README:75；RUNTIME_ENTRYPOINTS.md:242 |
| 代码 | `scripts/init_db.py` PostgreSQL RESTRICT guard（SQLite 行为不变）|
| 测试 | 新增 `tests/test_init_db_postgres_guard.py`（2 用例）|
| 数据库 | `auto_wechat` legacy rename → `auto_wechat_legacy_backup`；新建空 `auto_wechat`；`alembic upgrade head`@0034；schema 对账（**未执行 GRANT，app-role 权限 gap 见 §9**）|
| 不在范围 | prod/staging、P1 Consumer、M07 Core、0032/0033/0034 consumer PG verification、DROP legacy、stamp、RAG Query 0005 |

---

## 2. CR-1 ~ CR-8

```text
CR-1 (provenance = MOST PLAUSIBLE / CURRENT RISK ENTRY)   APPLIED  (§11.2)
CR-2 (显式 Service Quiescence Gate RB-Q)                   APPLIED  (§8a)
CR-3 (DATABASE_URL config value vs existing connections)  APPLIED  (§2.4 / §6.2)
CR-4 (Database-Level Contract: owner/role/encoding/ext)   APPLIED  (§7.4)
CR-5 (Verification Authority = frozen 2C expected_0034)    APPLIED  (§9.2)
CR-6 (Seed/Bootstrap Runtime Gate: empty≠runnable)         APPLIED  (§9.3)
CR-7 (Rollback 顺序 + 原子停止点)                          APPLIED  (§8 / §8b)
CR-8 (unlock label = UNBLOCKED_FOR_PG_VERIFICATION)       APPLIED  (§12.2)
```

八项修正原位回写设计文档，无新事实冲突（无需重新审批）。实施授权据此生效。

---

## 3. init_db.py RESTRICT

### 3.1 代码 diff（`scripts/init_db.py`）

- 新增 `get_database_runtime` 导入 + backend 守卫。
- **PostgreSQL**：检测到 PG backend → 打印明确错误（"PostgreSQL schema must be created/evolved by Alembic."）+ 提示 `alembic upgrade head` 命令 + `sys.exit(1)`。**拒绝 create_all，不 fallback。**
- **SQLite**：保留 `create_all + seed DEFAULT_CONFIGS` 既有行为不变。
- 与 `app.main.ensure_runtime_schema()`（main.py:273，PG startup_skip_create_all）语义对齐，形成 runtime + bootstrap 工具双重 PG create_all 拦截。

### 3.2 Focused tests

`tests/test_init_db_postgres_guard.py`（2 用例）+ 既有 `tests/test_9000_postgres_runtime_startup.py`（2 用例），共 **4 passed**：

```text
test_init_db_refuses_postgresql         PASS  (PG 下 sys.exit(1)，create_all 不调用)
test_init_db_allows_sqlite              PASS  (SQLite 下 create_all 被调用，行为保留)
test_postgresql_runtime_does_not_auto_create_schema  PASS
test_sqlite_runtime_keeps_auto_create_schema         PASS
```

---

## 4. Environment Identity（DBR-1 / RB-0）

```text
LOCAL DEVELOPMENT ONLY
NOT PRODUCTION / NOT STAGING
```

| 维度 | 值 |
|---|---|
| 容器 | `auto-wechat-postgres-dev`（本机 Docker，PG 16.14，healthy）|
| host:port | `127.0.0.1:5432` |
| 数据卷 | `auto_wechat_postgres_data` |
| superuser | `postgres`（本地 throwaway 口令，运行时注入，未写入报告/脚本）|
| app role | `auto_wechat`（DB owner）|
| 其他库（不触碰）| `xg_douyin_ai_cs`（RAG 库）、`auto_wechat_outbox_test`（测试残留）、`postgres`/`template0`/`template1` |
| 环境分类 | local development |

环境身份无歧义。

---

## 5. Disposability Reconfirmation（DBR-2 / RB-1）

精确 COUNT（READ_ONLY）：

| 表 | 行数 |
|---|---|
| compute_transactions | 3 |
| compute_accounts | 1 |
| compute_markup_ratios | 1 |
| douyin_leads / customer_profiles / sales_lead_feedbacks / wechat_tasks（PII 表）| 0 |
| **合计** | **5** |

与 2C 冻结（5 行、无 PII、可由测试 fixture 重建）精确一致。

```text
DISPOSABILITY_RECONFIRMED
```

无新业务数据、无 PII、无不可重建数据。

---

## 6. Rollback Evidence（RB-2a/2b）

| 项 | 值 |
|---|---|
| 格式 | pg_dump custom-format（`-Fc`）|
| 路径 | `docker-data/db_bl_2d_rollback/auto_wechat_legacy.dump`（`docker-data/` 已 gitignore，**未提交 Git**）|
| 大小 | 383,285 bytes（>0）|
| dump exit | 0 |
| 完整性核验 | `pg_restore --list` 成功（TOC 1162 entries，57 DATA entries，gzip）|

```text
ROLLBACK_DUMP: VERIFIED
```

dump 失败 → STOP（未发生）。

---

## 7. Quiescence Evidence（RB-Q）

rename 前最终连接清查（排除查询会话自身）：

```text
auto_wechat active business connections = 0
DB_CONSUMERS_QUIESCED: VERIFIED
```

当前所有 dev env（`.env.development.local` / `.env.lan.local` / `.env.development.example`）`DATABASE_URL` 均指向 SQLite，无进程持有 `auto_wechat` PG 连接。19000 Local Agent 不直接持有该 DB 连接。

---

## 8. Replacement Operations（A1）

### 8.1 Rename（RB-2c）

```sql
ALTER DATABASE auto_wechat RENAME TO auto_wechat_legacy_backup;  -- exit 0
```

- 预检：`auto_wechat_legacy_backup` 名未占用（count=0）✅
- rename 后：`auto_wechat_legacy_backup` 存在（owner=auto_wechat，数据完整），原 `auto_wechat` 不存在

```text
LEGACY: RETAINED / RECOVERABLE
```

### 8.2 Create replacement（RB-3）

```sql
CREATE DATABASE auto_wechat OWNER auto_wechat;  -- exit 0
```

- 创建后 business_tables = 0（empty，alembic 前不预建业务 schema）✅

> 凭据未出现在报告中（本地 throwaway）。

---

## 9. Database-Level Contract（CR-4）

新库 properties（区分 PROJECT REQUIRED vs LEGACY）：

| 维度 | 值 | 性质 |
|---|---|---|
| database owner | `auto_wechat`（与 legacy + 生产意图一致）| PROJECT REQUIRED |
| encoding | UTF8 | PROJECT REQUIRED |
| collate | en_US.utf8 | 默认（项目无显式约束）|
| required extensions | 无（迁移链无 CREATE EXTENSION；legacy 仅 plpgsql）| PROJECT REQUIRED — 无依赖 |
| schema/search_path | public（默认）| 默认 |
| app role permissions | **`APPLICATION_ROLE_PERMISSION_GAP`（见 §9 决策记录修正）**：`auto_wechat` 角色存在且可 LOGIN，但当前未验证到任何 table/sequence/default ACL grants | PROJECT REQUIRED — 未满足 |

> 决策记录（CR-4 审批冻结事实，2026-08-10 独立审批窗口只读核验）：
> - canonical schema / baseline 验证（alembic upgrade + DBR-4 snapshot/diff）与 `/ready` smoke 均以 `postgres` superuser 连接（有本地 throwaway 凭据，未触碰未知的 `auto_wechat` 角色密码）；
> - alembic 以 superuser 运行 → 全部 61 表 owner=postgres，`public` schema ACL 仅有 `pg_database_owner` 与 PUBLIC USAGE；
> - 独立只读核验 `auto_wechat` 角色实际权限：`role_table_grants`=空、序列 grants=0、`pg_default_acl`=空、`douyin_leads.relacl`=NULL → **application-role data access 尚未配置/验证**；
> - 本轮**未执行任何 GRANT**（审批范围不授权权限变更）；
> - **此 gap 不影响 `SCHEMA_BASELINE_MISMATCH=REMEDIATED`**：DBR-4 schema 精确度只读 diff=0，baseline canonical 性质取决于 schema 来源（Alembic@0034），与角色权限无关；
> - consumer PG verification（0032/0033/0034）若使用 `auto_wechat` app role，须另行解决权限（补 GRANT 或以 superuser 连接），属后续独立阶段。

---

## 10. Alembic Bootstrap（DBR-3）

```text
EMPTY PostgreSQL → alembic upgrade head → 0034   (exit 0)
目标库：新空 auto_wechat（5432，非 backup / 非 5433 disposable / 非 prod/staging）
```

PG runtime evidence（`PG_RUNTIME_VERIFIED`）：与 2C `EMPTY→0034` 路径复用一致。

---

## 11. Frozen Schema Comparison（DBR-4）

工具：`scripts/db_bl_2c_resume_snapshot.py`（与 2C 同一套只读 catalog inspection）。

```text
New Actual@0034（new auto_wechat）
  vs
FROZEN Expected@0034（docs/architecture/remediation/db_bl_2c_resume_evidence/expected_0034.json）
```

新库对象计数（与 R2 MR-4 @0034 吻合）：60 tables / 932 columns / 21 FK / 42 unique / 33 check / 128 standalone indexes。

```text
STRUCTURAL_DIFF (semantic) = 0
METADATA_DIFF (comment)    = 0
NAME_ONLY_DIFF             = 0
NORMALIZATION_ONLY         = 0
```

三者全 0（同链产物应自然达成）。Fresh `new_actual_0034.json` 作 supplemental sanity evidence（存 gitignore 路径，未覆盖 frozen canonical）。

---

## 12. Revision Gate（DBR-5）

```text
alembic current = 0034 (head)
alembic heads   = 0034      (单头)
alembic_version.version_num = 0034
physical tables = 61 (60 business + 1 alembic_version)
```

`alembic_version` 由框架首次 upgrade 自动创建，**非人为 stamp**。

---

## 13. Runtime Bootstrap / Seed（CR-6）

- migration `0006` 创建 `check_configs` 表但不 seed `DEFAULT_CONFIGS` → 新库 `check_configs` 为空表（0 行）。
- `/ready` 在空 `check_configs` 下 PASS（config 读取器有默认回退，空表不阻断启动）。
- **未** 调用 `scripts/init_db.py` 给 PG 补 seed（PG 下被 RESTRICT 拒绝）。
- **未** INSERT 任何 seed；**未** 恢复 5 条旧 compute_* 测试数据（DISPOSABLE）。

```text
RUNTIME_BOOTSTRAP_DATA_GAP: NONE（空 0034 DB 可运行，无 seed 依赖阻断）
```

---

## 14. /ready（DBR-6）

真实 HTTP 请求 `/ready`（httpx ASGITransport，走真实 FastAPI 路由，不触发 lifespan 避免热键/overlay/调度器）：

```text
HTTP 200
status: ok
checks:
  backend=postgresql          pass
  db_connect                  pass   (application 连接新 DB 成功)
  database_name               pass   (expected=auto_wechat, actual=auto_wechat)
  alembic_revision            pass   (expected=0034, actual=0034)
  critical_tables             pass   (douyin_leads, sales_staff 存在并可查)
```

证明：app 连新 DB ✅ / Alembic revision gate ✅ / superuser DB 权限 ✅（**非 `auto_wechat` app-role**，见 §9 `APPLICATION_ROLE_PERMISSION_GAP`）/ 无 create_all fallback ✅ / bootstrap 不阻塞 ready ✅。

---

## 15. Minimal Smoke（DBR-7）

- API 可创建：`create_app()` 在 PG DATABASE_URL 下成功（`ensure_runtime_schema` PG skip，无 create_all）。
- DB read path：`/ready` critical_tables（douyin_leads/sales_staff）可查 ✅。
- critical config read path：`check_configs` 可读（0 行，空表不阻断）✅。
- database readiness：见 §14。

未扩展为完整业务 E2E（Daily Report / M05 / Preview 不在本轮范围）。既有 `smoke_9000_postgres_startup.py`（create_app 验证）复用；其 route 检查在新版 FastAPI 下有预存 bug（`_IncludedRouter.path`），非本轮引入、非本轮范围，create_app 本身成功。

---

## 16. DBR-0 ~ DBR-9 逐项

| Gate | 结果 | Evidence Level |
|---|---|---|
| DBR-0 Strategy approved | PASS | APPROVED（2D APPROVAL）|
| DBR-1 Environment identity (LOCAL DEV ONLY) | PASS | READ_ONLY_PG_VERIFIED |
| DBR-2 Rollback artifact (dump verified) | PASS | pg_restore --list VERIFIED |
| DBR-3 Alembic bootstrap (EMPTY→0034) | PASS | PG_RUNTIME_VERIFIED |
| DBR-4 Schema exactness vs frozen Expected@0034 | PASS | READ_ONLY_PG_VERIFIED（diff=0）|
| DBR-5 Revision identity (current=head=0034, single) | PASS | PG_RUNTIME_VERIFIED |
| DBR-6 /ready PASS | PASS | HTTP 200 runtime（**以 `postgres` superuser 验证，未覆盖 `auto_wechat` app-role 权限**，见 §9 `APPLICATION_ROLE_PERMISSION_GAP`）|
| DBR-7 Minimal smoke | PASS | runtime + create_app |
| DBR-8 Legacy retained & recoverable | PASS | legacy_backup + dump 存在 |
| DBR-9 Prevention closure (init_db guard + doc sync) | PASS | tests 4 passed + doc edits |

RB-Q Service Quiescence（CR-2）：PASS（0 connections）。

---

## 17. Rollback Status

```text
auto_wechat_legacy_backup: RETAINED（rename 保留，数据完整，owner=auto_wechat）
rollback dump:             docker-data/db_bl_2d_rollback/auto_wechat_legacy.dump（383KB，pg_restore --list 可读）
NO DROP LEGACY（本轮不删，RB-10 / CLEANUP GATE 后续独立决定）
```

legacy 随时可恢复（rename 回切或 pg_restore）。

---

## 18. Unlock Candidates（CR-8）

```text
0032 Daily Report:
  BLOCKED_BY_SCHEMA_BASELINE_MISMATCH → UNBLOCKED_FOR_PG_VERIFICATION

0033 M05 Material Analysis:
  BLOCKED_BY_SCHEMA_BASELINE_MISMATCH → UNBLOCKED_FOR_PG_VERIFICATION

0034 Preview:
  BLOCKED_BY_SCHEMA_BASELINE_MISMATCH → UNBLOCKED_FOR_PG_VERIFICATION
```

**仅此一档，不跳级。** 本轮未执行 consumer-level PG verification，**不写 `PG_VERIFIED`**。

---

## 19. DB-BL Verdict

```text
SCHEMA_BASELINE_MISMATCH:
REMEDIATED

AUTO_WECHAT_DEV_PG:
CANONICAL_ALEMBIC_BASELINE@0034

DB-BL:
REPAIR_IMPLEMENTED_PENDING_APPROVAL
```

执行窗口不自行宣布 DB-BL 正式关闭。提交独立审批窗口复核。

---

## 20. P1 Status（不得提前关闭）

```text
P1 COMPUTE-IDEMPOTENCY-001:
TECHNICAL_CLOSURE = PENDING
ROOT ISSUE         = OPEN
```

DB-BL repair 完成 ≠ P1 关闭。后续仍至少包括：

- 0032 Daily Report consumer PG verification
- 0033 M05 Material Analysis consumer PG verification
- 0034 Preview consumer PG verification
- RAG Query 0005 PG verification（xg_douyin_ai_cs，BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT，不在 2D 范围）
- Global Active None Audit
- Final PostgreSQL Concurrent Closure Gate

---

## 附：产物索引

| 产物 | 路径 |
|---|---|
| 2D 设计文档（CR 已回写）| `docs/architecture/remediation/DB_BL_2D_LEGACY_POSTGRES_BASELINE_REPAIR_STRATEGY.md` |
| 2D 审批 | `docs/architecture/remediation/DB_BL_2D_APPROVAL.md` |
| 本实施报告 | `docs/architecture/remediation/DB_BL_2D_IMPLEMENTATION_REPORT.md` |
| init_db.py guard | `scripts/init_db.py` |
| guard 测试 | `tests/test_init_db_postgres_guard.py` |
| README doc sync | `README.md` §2 |
| RUNTIME_ENTRYPOINTS doc sync | `docs/architecture/RUNTIME_ENTRYPOINTS.md` 七、CLI |
| rollback dump（未提交 Git）| `docker-data/db_bl_2d_rollback/auto_wechat_legacy.dump` |
| supplemental snapshot（未提交 Git）| `docker-data/db_bl_2d_rollback/new_actual_0034.json` |
| frozen canonical 主参考 | `docs/architecture/remediation/db_bl_2c_resume_evidence/expected_0034.json` |

---

## 执行窗口停止声明

DB-BL-2D Implementation 全部批准 Gate（DBR-0~DBR-9 + RB-Q + CR-1~CR-8）已通过。执行窗口到此停止，提交独立审批窗口复核。

**未**：DROP legacy backup / 开始 0032 验证 / 开始 0033 验证 / 开始 0034 验证 / RAG Query 0005 / Global None Audit / Final PG Closure / 宣布 P1 关闭。

完成即停止。
