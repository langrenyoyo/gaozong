# P1 — PostgreSQL Fresh Bootstrap Principal Reproducibility 实施报告

> 任务：`P1-PG-BOOTSTRAP-OWNER-DRIFT-2 — Fresh Bootstrap Principal Reproducibility 实施窗口`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE`
> 前序设计：[P1_PG_BOOTSTRAP_OWNER_DRIFT_DESIGN.md](P1_PG_BOOTSTRAP_OWNER_DRIFT_DESIGN.md)（`DESIGN_READY_FOR_APPROVAL`）
> 前序审批：[P1_PG_BOOTSTRAP_OWNER_DRIFT_APPROVAL.md](P1_PG_BOOTSTRAP_OWNER_DRIFT_APPROVAL.md)（`APPROVED_WITH_CORRECTIONS`，C1~C5）
> 日期：2026-08-11
> 窗口性质：实施窗口（LOCAL DEVELOPMENT ONLY + isolated clean-bootstrap verification environment）
> Source of Truth：本窗口独立只读 canonical 确认 + isolated fresh-bootstrap E2E（FB-0~FB-12）+ 真实 HTTP /ready

---

## 结论速览

| 维度 | 结论 |
|---|---|
| Governance Checkpoint | ✅ `36e36db`（`设计：冻结PostgreSQL可重复引导权限方案`，只含设计/审批文档）|
| Gap① Owner Correction | ✅ `001_create_databases.sql:20` `OWNER auto_wechat` → `OWNER postgres` |
| Gap② Permission Bootstrap | ✅ 新增 `scripts/pg/bootstrap_app_role_permissions.sql`（幂等 GRANT/ADP/REVOKE）|
| C2 Post-Alembic Caller | ✅ 新增 `scripts/pg/bootstrap_local_dev_pg.py`（alembic→permission 编排）|
| C5 Dev-only 边界证据 | ✅ init SQL 头部注释保留 DEV-ONLY + prod/staging 边界 |
| FB-0~FB-12 | ✅ 全 PASS |
| Canonical DB No-Drift | ✅ owner=postgres / head=0034 / tables=61 / CREATE=false 不变 |
| Gap 最终状态 | `RESOLVED / VERIFIED`（独立实施审批 APPROVED_WITH_CORRECTIONS，见 `P1_PG_BOOTSTRAP_OWNER_DRIFT_IMPLEMENTATION_APPROVAL.md`）|

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP      = RESOLVED
FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP        = RESOLVED
FRESH_BOOTSTRAP_PRINCIPAL_REPRODUCIBILITY          = VERIFIED
```

---

## 1. Governance Checkpoint

```text
设计审批 checkpoint commit = 36e36db
message = 设计：冻结PostgreSQL可重复引导权限方案
```

该 commit 只含两份设计/审批 candidate 文档：

- `docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_DESIGN.md`
- `docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_APPROVAL.md`

不含任何 implementation 代码。本 commit 只回答"为什么允许实施"（APPROVED_WITH_CORRECTIONS，C1~C5）。

实施窗口在本 checkpoint 之后开始，candidate diff 保持未提交（§38，交独立实施审批窗口）。

---

## 2. Applied Corrections C1-C5

| Correction | 内容 | 落地 |
|---|---|---|
| **C1** Gap①+Gap② 一个 implementation unit | owner 修正 + permission bootstrap + caller + E2E 同批实施 | ✅ 同批 |
| **C2** 必须有明确 post-Alembic caller | 新增 `scripts/pg/bootstrap_local_dev_pg.py`：alembic upgrade head → bootstrap_app_role_permissions.sql；alembic 失败 STOP，permission 不执行 | ✅ §7 |
| **C3** FB-11 Idempotency | run#1/#2 均 PASS，ACL/ADP 等价 | ✅ §15 |
| **C4** FB-12 Zero Manual Intervention | empty→chain→/ready 全自动，零手工 GRANT/ALTER/stamp | ✅ §16 |
| **C5** 001 dev-only 边界证据 | init SQL 头部注释保留 DEV-ONLY + prod/staging init 目录引用 | ✅ §8 |

---

## 3. Changed Files

### PROPOSED MODIFY

| 文件 | 改动 |
|---|---|
| [docker/postgres/init/001_create_databases.sql](docker/postgres/init/001_create_databases.sql) | 头部加 DEV-ONLY 边界注释（C5）；第 20 行 `OWNER auto_wechat` → `OWNER postgres` + 原因注释（Gap①）|

### PROPOSED CREATE

| 文件 | 内容 |
|---|---|
| [scripts/pg/bootstrap_app_role_permissions.sql](scripts/pg/bootstrap_app_role_permissions.sql) | 幂等 GRANT/ADP/REVOKE + fail-closed guard（Gap②）|
| [scripts/pg/bootstrap_local_dev_pg.py](scripts/pg/bootstrap_local_dev_pg.py) | 最小 post-Alembic caller（C2）：alembic→permission 编排，local dev guard，单事务 fail-closed |
| [tests/test_pg_bootstrap_owner_drift.py](tests/test_pg_bootstrap_owner_drift.py) | T1~T4 focused static tests |

### READ ONLY / 未修改

compose（dev/prod/staging）、init-prod/init-staging 010、alembic、app/main.py、health.py、db_readiness.py、init_db.py、当前 canonical DB、.env、M07/consumer/RB-10/DB-BL/9100。

---

## 4. Fresh Bootstrap Timeline

```text
[1] docker run --name au-pg-bootstrap-iso -p 25433:5432 \
      -v docker/postgres/init:/docker-entrypoint-initdb.d:ro postgres:16-alpine
    POSTGRES_USER=postgres（superuser），独立 volume + 端口 25433
    与 canonical auto-wechat-postgres-dev@5432 完全隔离（FB-0）
          ↓
[2] PG entrypoint 执行 001_create_databases.sql（一次性，空 volume）
    产物：role auto_wechat（LOGIN，非 superuser）
          + database auto_wechat OWNER postgres  ← Gap① 修正后 fresh 即正确
          + database xg_douyin_ai_cs OWNER xg_douyin_ai_cs（9100 不变，§9100 boundary）
          ↓
[3] docker exec pg_isready → healthy
          ↓
[4] python scripts/pg/bootstrap_local_dev_pg.py（SMOKE_DATABASE_URL=postgres@25433）
    Stage 1: alembic upgrade head → 0034（61 表，对象 owner=postgres）
    Stage 2: bootstrap_app_role_permissions.sql（GRANT/ADP/REVOKE，单事务）
    → LOCAL_DEV_PG_BOOTSTRAP=COMPLETE
          ↓
[5] uvicorn app.main:app --port 9001（DATABASE_URL=auto_wechat@25433，app principal）
    ensure_runtime_schema → startup_skip_create_all（PG 不建表）
          ↓
[6] GET /ready → HTTP 200，backend=postgresql，head=0034（FB-9）
```

步骤 [2] fresh bootstrap 即 owner=postgres，**无需手工 ALTER DATABASE OWNER**（Gap① 修复）；步骤 [4] permission bootstrap 自动重建 GRANT/ADP（Gap② 修复）。全程零手工 GRANT/REVOKE/ADP/stamp（FB-12）。

---

## 5. Owner Correction（Gap①）

### 修改

`001_create_databases.sql` 第 20 行：

```sql
-- 修改前
SELECT 'CREATE DATABASE auto_wechat OWNER auto_wechat'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec

-- 修改后
SELECT 'CREATE DATABASE auto_wechat OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

### 9100 boundary

第 23 行 `CREATE DATABASE xg_douyin_ai_cs OWNER xg_douyin_ai_cs` **未变**（§9100 不属本 gap 主体，§36 禁止范围）。

### fresh bootstrap 验证（FB-1）

```text
iso_db_owner=postgres          ← fresh 即正确（零手工 ALTER）
iso_app_is_dbo_member=false    ← ownership blocker 不重现
iso_app_db_create=false
iso_app_schema_create=false
iso_app_superuser=false createdb=false createrole=false bypassrls=false  ← Role Hard Gate
iso_tables_before_alembic=0    ← init 阶段无业务表
iso_9100_db_owner=xg_douyin_ai_cs  ← 9100 未变
```

---

## 6. Permission SQL Contract（Gap②）

[scripts/pg/bootstrap_app_role_permissions.sql](scripts/pg/bootstrap_app_role_permissions.sql) 幂等 SQL，由 `postgres` migration principal 执行，post-Alembic 阶段运行。

### Fail-closed guard

```sql
DO $$
BEGIN
  IF current_database() <> 'auto_wechat' THEN RAISE EXCEPTION 'FAIL CLOSED...'; END IF;
  IF current_user <> 'postgres' THEN RAISE EXCEPTION 'FAIL CLOSED...'; END IF;
END
$$;
```

不满足即 RAISE，单事务回滚，无任何授权生效。

### Database / Schema contract

```text
DATABASE CONNECT = allowed（显式 GRANT CONNECT）
DATABASE CREATE  = denied（app role 非 owner，无 ownership 派生）
public USAGE      = allowed（显式 GRANT USAGE）
public CREATE     = denied（app role 非 pg_database_owner 成员）
```

### 既有业务表 DML

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;
```

无 TRUNCATE / REFERENCES / TRIGGER，无 ALL PRIVILEGES。

### alembic_version 收敛

```sql
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM auto_wechat;
```

C3 顺序硬约束：broad DML GRANT 之后立即 REVOKE → SELECT-only。

### 既有序列

```sql
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;
```

无 UPDATE/setval，无 ALL PRIVILEGES。

### 未来对象 ADP

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
```

creator=postgres（FROZEN），无 TRUNCATE。ADP 只覆盖新建对象，不反向覆盖既有对象（既有对象由 ALL TABLES/SEQUENCES 显式 GRANT）。

---

## 7. Post-Alembic Caller（C2）

```text
WHO      = scripts/pg/bootstrap_local_dev_pg.py（deployment/migration administration，非 FastAPI runtime）
WHEN     = alembic upgrade head 之后、应用启动之前
HOW      = subprocess 跑 alembic → psycopg3 执行 permission SQL（单事务）
PRINCIPAL= postgres（migration/admin principal）
ENVIRONMENT = LOCAL DEVELOPMENT（host 白名单 + database=auto_wechat + APP_ENV≠production guard）
```

### 正式链

```text
PG role/database init（001_create_databases.sql，owner=postgres）
  → alembic upgrade head（caller stage 1）
  → permission bootstrap（caller stage 2，bootstrap_app_role_permissions.sql）
  → application /ready
```

### Hard Contract

- alembic 失败 → `raise SystemExit` → permission bootstrap **不执行**（T4 静态验证 + 代码 `returncode != 0` 分支）
- permission 失败 → `raise SystemExit`，退出非零
- 不隐式使用 `DATABASE_URL`，必须显式 `SMOKE_DATABASE_URL`（与既有 smoke 一致）
- 不启动业务 runtime、不修改 FastAPI startup、不自行业务提权
- local dev guard：`APP_ENV=production` → STOP；host 不在 `{localhost,127.0.0.1,postgres,auto-wechat-postgres-dev}` → STOP；database≠auto_wechat → STOP

### 未引入

- 大型 bootstrap 平台 / 复杂权限服务
- FastAPI startup 提权（app/main.py 未改，§15）
- 通用远程数据库权限部署工具

---

## 8. Environment Boundary（C5）

### 静态证据

```text
docker-compose.dev.yml:41     → ./docker/postgres/init:/docker-entrypoint-initdb.d:ro   （dev 用 init/）
docker-compose.yml:19         → ./docker/postgres/init-prod:ro                          （prod 用 init-prod/）
docker-compose.staging.yml:37 → ./docker/postgres/init-staging:ro                      （staging 用 init-staging/）
```

三个环境用各自独立 init 目录，不共享。`001_create_databases.sql` 仅被 dev compose 引用，**dev-only**。

### T2 测试验证

- `test_t2_prod_uses_init_prod_not_dev_init` PASS
- `test_t2_staging_uses_init_staging_not_dev_init` PASS
- `test_t2_dev_init_sql_has_dev_only_boundary_marker` PASS（头部注释含 DEV-ONLY + init-prod + init-staging）

### 边界声明

```text
LOCAL DEV IMPLEMENTATION = APPLIED
STAGING    = NO WRITE / RUNTIME_UNKNOWN
PRODUCTION = NO WRITE / RUNTIME_UNKNOWN
```

---

## 9. Existing Object Privileges

fresh bootstrap + caller 后，isolated PG 权限快照（以 postgres 只读）：

```text
app_table_select   = 61   （60 业务表 + alembic_version）
app_table_insert   = 60   （alembic_version 已 REVOKE）
app_table_update   = 60
app_table_delete   = 60
app_table_truncate = 0    （符合 contract）
app_adp_count      = 2    （creator=postgres，grantee=auto_wechat）
```

与 canonical contract（PR-3/PR-13）完全一致。

---

## 10. alembic_version Hardening

```text
SELECT version_num FROM alembic_version;                → 0034   PASS
INSERT INTO alembic_version(version_num) VALUES('0034'); → DENIED (permission denied for table alembic_version)
UPDATE alembic_version SET version_num=... WHERE false;  → DENIED
DELETE FROM alembic_version WHERE false;                  → DENIED
TRUNCATE alembic_version;                                 → DENIED
revision after attempts                                   → 0034（不变）
```

四路写均 `permission denied for table alembic_version`，revision 零修改。C3 顺序硬约束（broad GRANT → REVOKE）经实际写尝试反证。

### Recreation Contract

若未来 alembic_version 被 DROP/recreate，重跑 `bootstrap_app_role_permissions.sql` 即重新收敛到 SELECT-only（ADP 会让重建对象拿到 DML，REVOKE 再收敛）。caller 每次 alembic upgrade head 后都执行 permission bootstrap，保证 alembic_version 始终 SELECT-only。

---

## 11. Sequence Contract

```text
sequences（public）= 60
granted = USAGE, SELECT
```

未使用 ALL PRIVILEGES，无 UPDATE/setval。代表表 `autoreply_admin_audit_logs_id_seq`：nextval（INSERT 触发）PASS / currval PASS。

---

## 12. ADP Contract

```text
pg_default_acl（public, creator=postgres）= 2
  tables    → DELETE,INSERT,SELECT,UPDATE（无 TRUNCATE/REFERENCES/TRIGGER）
  sequences → SELECT,USAGE（无 UPDATE/setval）
```

### Future Object Runtime（FB-8）

postgres 创建临时 `fb_adp_vt`（bigserial PK）+ `fb_adp_vs`（standalone seq）：

```text
future table INSERT（含 owned seq nextval）→ PASS
future table UPDATE                          → PASS
future table SELECT                          → PASS
future table DELETE                          → PASS
future table TRUNCATE                        → DENIED（ADP 未授予 TRUNCATE）
future standalone seq nextval                → PASS
```

验证后 postgres DROP TABLE/SEQUENCE，residual=0，tables=61 不变。ADP 真实生效。

---

## 13. Static / Focused Tests

`tests/test_pg_bootstrap_owner_drift.py`（16 tests，纯静态解析，不连 DB）：

| 测试 | 内容 | 结果 |
|---|---|---|
| T1 `test_t1_auto_wechat_database_owner_is_postgres` | init SQL `OWNER postgres`，无残留 `OWNER auto_wechat` | ✅ |
| T1 `test_t1_9100_database_row_unchanged` | xg_douyin_ai_cs 行未变 | ✅ |
| T1 `test_t1_auto_wechat_role_no_elevated_capability` | role 无 SUPERUSER/CREATEDB/CREATEROLE | ✅ |
| T2 `test_t2_prod_uses_init_prod_not_dev_init` | prod 用 init-prod | ✅ |
| T2 `test_t2_staging_uses_init_staging_not_dev_init` | staging 用 init-staging | ✅ |
| T2 `test_t2_dev_init_sql_has_dev_only_boundary_marker` | DEV-ONLY 注释 + 边界证据 | ✅ |
| T3 `test_t3_existing_table_dml_grant` | GRANT SELECT/INSERT/UPDATE/DELETE | ✅ |
| T3 `test_t3_no_all_privileges_shortcut` | GRANT 行无 ALL PRIVILEGES | ✅ |
| T3 `test_t3_no_truncate_grant` | GRANT 行无 TRUNCATE；REVOKE 含 TRUNCATE | ✅ |
| T3 `test_t3_no_references_trigger_grant` | GRANT 行无 REFERENCES/TRIGGER | ✅ |
| T3 `test_t3_sequence_usage_select` | GRANT USAGE,SELECT ON ALL SEQUENCES | ✅ |
| T3 `test_t3_alembic_version_hardening_after_grant` | REVOKE 在 broad GRANT 之后 | ✅ |
| T3 `test_t3_adp_for_role_postgres` | ADP FOR ROLE postgres | ✅ |
| T3 `test_t3_fail_closed_guard` | guard 校验 current_database/current_user | ✅ |
| T4 `test_t4_alembic_before_permission_in_main` | main 中 alembic 调用在 permission 之前 | ✅ |
| T4 `test_t4_alembic_failure_stops_before_permission` | alembic 失败 raise SystemExit | ✅ |

```text
16 passed in 0.09s
```

---

## 14. FB-0~FB-12

| Gate | 验证内容 | 裁定 | 证据 |
|---|---|---|---|
| FB-0 | Isolation | **PASS** | 临时容器 `au-pg-bootstrap-iso`@25433，独立 volume，与 canonical@5432 隔离 |
| FB-1 | Fresh Database Owner | **PASS** | `iso_db_owner=postgres` / `iso_app_is_dbo_member=false` |
| FB-2 | CREATE Boundary | **PASS** | `iso_app_db_create=false` / `iso_app_schema_create=false` |
| FB-3 | Empty → Alembic Head | **PASS** | head=0034 / tables=61 / seqs=60，无 stamp/create_all |
| FB-4 | Application Runtime DML | **PASS** | INSERT/UPDATE/SELECT/DELETE 事务内+ROLLBACK，residual=0 |
| FB-5 | alembic_version | **PASS** | SELECT=0034 PASS；INSERT/UPDATE/DELETE/TRUNCATE DENIED ×4，revision 不变 |
| FB-6 | DDL Negative | **PASS** | CREATE TABLE→permission denied for schema public，无残留 |
| FB-7 | TRUNCATE Negative | **PASS** | TRUNCATE fb_adp_vt→permission denied，rows_preserved=1 |
| FB-8 | Future Object Contract | **PASS** | future DML PASS / TRUNCATE DENIED / seq PASS（ADP 真实生效），cleanup residual=0 |
| FB-9 | /ready As Application Principal | **PASS** | HTTP 200 / backend=postgresql / db=auto_wechat / head=0034 / principal=auto_wechat |
| FB-10 | Cleanup | **PASS** | 临时容器/volume 删除，canonical 无变化 |
| FB-11 | Permission Bootstrap Idempotency | **PASS** | run#1/#2 均 PASS，ACL（61/60/60/60/0）/ADP（2）/owner/head 等价 |
| FB-12 | Zero Manual Intervention | **PASS** | empty→init→caller(alembic+permission)→/ready 全自动，零手工 GRANT/ALTER/stamp |

---

## 15. Permission Bootstrap Idempotency（FB-11）

### before snapshot（run#1 后）

```text
before_select=61 / before_insert=60 / before_update=60 / before_delete=60 / before_truncate=0
before_adp=2
before_alembic_sel=true / before_alembic_ins=false
before_db_owner=postgres
```

### 第二次执行（run#2，全 chain）

```text
LOCAL_DEV_PG_BOOTSTRAP=COMPLETE
no error / no duplicate
```

### after snapshot（run#2 后）

```text
after_select=61 / after_insert=60 / after_update=60 / after_delete=60 / after_truncate=0
after_adp=2
after_alembic_sel=true / after_alembic_ins=false
after_db_owner=postgres
after_head=0034
```

### 裁定

before/after 完全等价，无额外高权限，无重复状态。

```text
PERMISSION_BOOTSTRAP_IDEMPOTENCY = VERIFIED
```

---

## 16. Zero Manual Intervention Evidence（FB-12）

从全新隔离 PG 开始，只使用批准后的 normal bootstrap chain：

```text
docker run（init SQL 修改后 owner=postgres 自动生效）
  → python scripts/pg/bootstrap_local_dev_pg.py
      → alembic upgrade head（自动）
      → bootstrap_app_role_permissions.sql（自动，单事务）
  → uvicorn app.main:app（DATABASE_URL=auto_wechat）
  → GET /ready → HTTP 200
```

过程中**未执行**：

```text
手工 ALTER DATABASE OWNER
手工 GRANT
手工 REVOKE
手工 ALTER DEFAULT PRIVILEGES
手工 CREATE business tables
blind stamp
ad-hoc repair SQL
```

全部 FB contract 自动成立。

```text
FRESH BOOTSTRAP PRINCIPAL CONTRACT = REPRODUCIBLE
ZERO MANUAL PRIVILEGE REPAIR = VERIFIED
```

---

## 17. Canonical DB No-Drift

fresh-bootstrap 验证结束后，只读重新确认 canonical local PG：

```text
canon_db_owner         = postgres   （未变）
canon_head             = 0034       （未变）
canon_tables           = 61         （未变）
canon_app_is_dbo_member = false     （未变）
canon_app_db_create     = false     （未变）
canon_app_schema_create = false     （未变）
canon_app_superuser     = false createdb=false createrole=false bypassrls=false  （未变）
```

与 §1 前置确认完全一致，零测试污染。

```text
CANONICAL LOCAL PG = NO DRIFT
```

---

## 18. Staging / Production Boundary

```text
STAGING    = NO WRITE / RUNTIME_UNKNOWN   （继续冻结）
PRODUCTION = NO WRITE / RUNTIME_UNKNOWN   （继续冻结）
```

- staging/prod 不使用 `001_create_databases.sql`（T2 静态验证：prod 用 init-prod，staging 用 init-staging）。
- 修改 init SQL 只影响 local dev fresh bootstrap。
- staging/prod 用单 superuser role 模型，与分离 contract 本就不同，属 accepted residual risk（前序 ownership 审批 §12）。
- 本窗口 NO REMOTE WRITE。
- **不得宣称** "staging/prod ownership fixed"。
- prod 若要落实分离 contract，属独立部署审批。

---

## 19. Residual / Cleanup

### isolated 验证环境

- 临时容器 `au-pg-bootstrap-iso`：已 `docker rm -f`
- 临时 volume：已删除
- 临时端口 25433：已释放
- 临时 future-object fixtures（`fb_adp_vt` / `fb_adp_vs`）：postgres 已 DROP，residual=0
- 临时验证行（`fb4_probe` / `fb8_probe`）：事务 ROLLBACK，residual=0
- 临时 uvicorn probe（port 9001）：已停止

### canonical

- canonical local PG：未触碰（§17 no-drift）
- canonical 应用角色权限：未改动
- migration / DB-BL：未改（0034 / 61 表不变）
- M07 Core / consumer 代码：未改

---

## 20. Verdict

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP
= RESOLVED

FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP
= RESOLVED

FRESH_BOOTSTRAP_PRINCIPAL_REPRODUCIBILITY
= VERIFIED
```

成功但未自行正式关闭（§34 纪律）。fresh bootstrap 从 empty isolated PG 经 normal chain 自动得到：

```text
DB owner = postgres（migration principal）

application principal auto_wechat:
  CONNECT = PASS / DML = PASS / sequence = PASS
  DATABASE CREATE = DENIED / SCHEMA CREATE = DENIED / TRUNCATE = DENIED / DDL = DENIED
  alembic_version = SELECT-only
  future tables/sequences = correct ADP
  /ready = PASS as application principal

全程 ZERO MANUAL PRIVILEGE REPAIR
```

---

## 21. P1 Status

```text
P1 ACTIVE CONSUMER PG VERIFICATION = COMPLETE   （未改变，§33）

COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

本任务成果：
- Gap① owner drift：fresh bootstrap 即 owner=postgres（init SQL 1 行修正）
- Gap② grant reproducibility：permission bootstrap 脚本 + post-alembic caller
- C2~C5 corrections 全部应用
- FB-0~FB-12 全 PASS + canonical no-drift

剩余 P1 Technical Closure blockers（CR-1 修正：RAG Query 0005 已 PG_RUNTIME_VERIFIED @5d8b6ba，不再列为 blocker）：

```text
A′  Bootstrap Owner Drift        → RESOLVED（本报告，独立审批 APPROVED_WITH_CORRECTIONS）
C   Global Active None Audit      （独立执行，§19 未开始）
D   Final PG Concurrent Closure Gate（独立执行，§19 未开始）

RB-10 = NOT AUTHORIZED（不是 COMPUTE-IDEMPOTENCY-001 closure blocker）
```

---

## 22. Git

```text
设计审批 checkpoint = 36e36db（已提交，§0）
implementation candidate diff = 未提交（§38）
```

implementation candidate diff 包含：

- `docker/postgres/init/001_create_databases.sql`（M）
- `scripts/pg/bootstrap_app_role_permissions.sql`（A）
- `scripts/pg/bootstrap_local_dev_pg.py`（A）
- `tests/test_pg_bootstrap_owner_drift.py`（A）
- 本实施报告（A）

**未提交、未 push**，保持 candidate diff，交独立实施审批窗口。

未混入：业务代码 / migration 修改 / 9100 整改 / staging-prod write / Global None Audit / Final Concurrent Closure / RB-10。

---

## 23. STOP Rules 复核

| STOP 条件 | 是否触发 |
|---|---|
| 001 实际影响 staging/prod | NO（T2 静态验证 dev-only）|
| fresh auto_wechat role 能力超出批准 contract | NO（Role Hard Gate，无 SUPERUSER 等）|
| permission caller 修改 FastAPI startup | NO（app/main.py 未改）|
| Alembic 无法 empty→head | NO（FB-3 PASS，head=0034）|
| permission script 需手工 repair | NO（FB-12 零手工）|
| application role 仍是 DB owner | NO（FB-1 owner=postgres）|
| application role DDL/TRUNCATE 成功 | NO（FB-6/FB-7 DENIED）|
| alembic_version 可写 | NO（FB-5 四路 DENIED）|
| future ADP 失败 | NO（FB-8 PASS）|
| FB-11 第二次不收敛 | NO（before/after 等价）|
| FB-12 需 ad-hoc manual repair | NO（normal chain 全自动）|
| canonical DB 漂移 | NO（§17 no-drift）|

无 STOP 触发。

---

## 实施窗口停止点

```text
P1-PG-BOOTSTRAP-OWNER-DRIFT-2:
FRESH BOOTSTRAP PRINCIPAL REPRODUCIBILITY = VERIFIED
  Gap① LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = RESOLVED
  Gap② FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP = RESOLVED
  C1~C5 corrections = APPLIED
  FB-0~FB-12 = PASS（独立审批窗口用独立隔离 PG 复现，见 P1_PG_BOOTSTRAP_OWNER_DRIFT_IMPLEMENTATION_APPROVAL.md）
  Canonical DB = NO DRIFT
  STAGING / PRODUCTION = NO WRITE / RUNTIME_UNKNOWN
implementation candidate diff 交独立实施审批窗口（APPROVED_WITH_CORRECTIONS，CR-1/CR-2）。
```

未自行开始：Global Active None Audit / Final Concurrent Closure / RB-10 / P1 Closed。

实施窗口完成，停止。
