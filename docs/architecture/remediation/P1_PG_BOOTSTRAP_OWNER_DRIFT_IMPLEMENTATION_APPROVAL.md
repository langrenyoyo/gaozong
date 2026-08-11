# P1-PG-BOOTSTRAP-OWNER-DRIFT-2 — Fresh Bootstrap Principal Reproducibility Implementation 独立审批报告

> 任务：`P1-PG-BOOTSTRAP-OWNER-DRIFT-2 — Fresh Bootstrap Principal Reproducibility 实施审批`
> 审批窗口：P1-PG-BOOTSTRAP-OWNER-DRIFT-2 独立实施审批窗口
> 审查对象：`P1_PG_BOOTSTRAP_OWNER_DRIFT_IMPLEMENTATION_REPORT.md` + candidate diff（working tree，未提交）
> 前序设计审批：`P1_PG_BOOTSTRAP_OWNER_DRIFT_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS`，C1~C5）
> 治理 checkpoint：`36e36db`（`设计：冻结PostgreSQL可重复引导权限方案`）
> 审批日期：2026-08-11
> Source of Truth：本窗口独立 isolated fresh-bootstrap PG runtime（FB-0~FB-12）+ 真实 /ready HTTP > 执行窗口报告 > 推测

---

## Technical Decision

```text
APPROVED_WITH_CORRECTIONS
```

Fresh bootstrap principal reproducibility runtime 成立——独立审批窗口用**自己的新隔离 PG**（`au-pg-approval-iso`@25434，与执行窗口 `au-pg-bootstrap-iso`@25433 完全不同）独立复现全部 13 个 FB Gate，candidate 无必须返工问题。

但报告与文档存在不改变实现正确性的过期状态/措辞修正，实施前必须应用：

- **CR-1**：实施报告 §21 + CLAUDE.md 仍把 `B. RAG Query 0005 PG` 列为 P1 remaining Technical Closure blocker——**过期状态，必须修正**。RAG Query 0005 已于 commit `5d8b6ba` PG_RUNTIME_VERIFIED，P1 ACTIVE CONSUMER PG VERIFICATION = COMPLETE，不得保留为 blocker。
- **CR-2**：normal bootstrap caller（`bootstrap_local_dev_pg.py`）的可发现入口目前仅在脚本 docstring + 实施报告。建议在 README/runbook 补最小调用说明（HOW/WHEN/WHAT COMMAND），但从脚本自身可发现，不阻断批准——属文档性提示而非正确性问题。

这些 correction 不改变 fresh-bootstrap runtime 正确性（已 13/13 PASS 独立验证），只修正过期状态与可发现性。

---

## Git / Scope

```text
HEAD = 36e36dbb2670d1f60fa15518d78da79351829d1c（设计审批 checkpoint）
worktree = M CLAUDE.md / M docker/postgres/init/001_create_databases.sql / M docs/ai/05_PROJECT_CONTEXT.md
           ?? docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_IMPLEMENTATION_REPORT.md
           ?? scripts/pg/
           ?? tests/test_pg_bootstrap_owner_drift.py
```

candidate diff 未提交（working tree），交独立实施审批。

独立确认 candidate scope：

```text
MODIFY:
  docker/postgres/init/001_create_databases.sql   （头部 DEV-ONLY 注释 + 第 20 行 OWNER postgres）
  CLAUDE.md                                        （A′ blocker 状态同步）
  docs/ai/05_PROJECT_CONTEXT.md                    （8.3 RAG 检索 scope 段同步）

CREATE:
  scripts/pg/bootstrap_app_role_permissions.sql     （Gap② 幂等 GRANT/ADP/REVOKE）
  scripts/pg/bootstrap_local_dev_pg.py             （C2 post-Alembic caller）
  tests/test_pg_bootstrap_owner_drift.py           （T1~T4 静态测试 16 个）
  docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_IMPLEMENTATION_REPORT.md
```

独立确认：

- ✅ 无业务代码改动（`apps/` / `app/` 无 diff）
- ✅ 无 9000 migration 改动（`migrations/postgres/auto_wechat/` 无 diff）
- ✅ 无 9100 migration 改动（`migrations/postgres/xg_douyin_ai_cs/` 无 diff）
- ✅ 无 M07 Core 改动
- ✅ 无 FastAPI startup 提权（`app/main.py` 无 diff）
- ✅ 无 staging/prod init 修改（`docker/postgres/init-prod/` / `init-staging/` 无 diff）
- ✅ 无 credentials / dump / snapshot 入库
- ✅ 无临时容器配置残留（验证脚本位于 worktree 外，`git status` clean of code）

---

## C1 — 双 Gap 共同闭环

独立确认实现同时解决 Gap① + Gap② 作为一个 implementation unit：

```text
Gap① LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP
  → 001_create_databases.sql:20 OWNER auto_wechat → OWNER postgres（1 行）

Gap② FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP
  → scripts/pg/bootstrap_app_role_permissions.sql（幂等 GRANT/ADP/REVOKE）
  → scripts/pg/bootstrap_local_dev_pg.py（C2 post-Alembic caller）
```

Fresh bootstrap 最终同时满足（我独立 fixture 验证）：

```text
correct DB ownership（owner=postgres）
+ application runtime DML（sel=61/ins=60/upd=60/del=60）
+ alembic_version SELECT-only（ins/upd/del/trunc 全 denied）
+ sequence privileges（USAGE+SELECT 60 seq）
+ future ADP（2 条，creator=postgres，无 TRUNCATE）
+ DDL/TRUNCATE denied（CREATE TABLE / TRUNCATE 全 permission denied）
```

无任何一层依赖人工 runbook——FB-12 零手工干预 PASS。

---

## C2 — Post-Alembic Caller

`scripts/pg/bootstrap_local_dev_pg.py` 是真正调用 permission SQL 的正式入口，非 dormant helper。

```text
WHO      = scripts/pg/bootstrap_local_dev_pg.py（deployment/migration administration，非 FastAPI runtime）
WHEN     = alembic upgrade head 之后、应用启动之前
HOW      = subprocess 跑 alembic → psycopg3 执行 permission SQL（单事务）
PRINCIPAL= postgres（migration/admin principal）
ENVIRONMENT = LOCAL DEVELOPMENT（host 白名单 + database=auto_wechat + APP_ENV≠production guard）
WHAT COMMAND = python scripts/pg/bootstrap_local_dev_pg.py（SMOKE_DATABASE_URL=postgres@...）
```

正式链（我独立执行验证）：

```text
PG role/database init（001_create_databases.sql，owner=postgres）
  → alembic upgrade head（caller stage 1，postgres migration principal）
  → permission bootstrap（caller stage 2，bootstrap_app_role_permissions.sql，单事务）
  → application /ready（auto_wechat principal）
```

### Caller Failure Semantics

- alembic 失败 → `raise SystemExit` → permission bootstrap **不执行**（代码 `returncode != 0` 分支，T4 静态验证）
- permission 失败 → `raise SystemExit`，退出非零
- 不隐式使用 `DATABASE_URL`，必须显式 `SMOKE_DATABASE_URL`（与既有 smoke 一致）
- 不启动业务 runtime、不修改 FastAPI startup、不自行业务提权
- local dev guard：`APP_ENV=production` → STOP；host 不在 `{localhost,127.0.0.1,postgres,auto-wechat-postgres-dev}` → STOP；database≠auto_wechat → STOP

### CR-2 可发现性提示

caller 的调用方式目前仅在脚本 docstring + 实施报告 §7。脚本自身 docstring 含完整使用示例（`SMOKE_DATABASE_URL=... python scripts/pg/bootstrap_local_dev_pg.py`），从脚本可发现。建议在 README/runbook 补最小调用说明提升可发现性，但不阻断批准——脚本非休眠（FB-12 已证 normal chain 自动调用）。

---

## FastAPI Runtime Boundary

独立确认未修改 `app/main.py` / FastAPI startup/lifespan。业务 runtime 不执行 GRANT/REVOKE/ADP/ALTER OWNER。正式责任仍是 deployment/migration administration（`bootstrap_local_dev_pg.py`），非 application runtime。

```text
app/main.py = UNCHANGED
FastAPI startup DOES NOT execute admin GRANT/REVOKE/ADP = VERIFIED
```

---

## Owner Correction

`docker/postgres/init/001_create_databases.sql` 第 20 行：

```sql
-- 修改前
SELECT 'CREATE DATABASE auto_wechat OWNER auto_wechat'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec

-- 修改后
SELECT 'CREATE DATABASE auto_wechat OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

### 9100 boundary

第 23 行 `CREATE DATABASE xg_douyin_ai_cs OWNER xg_douyin_ai_cs` **未变**（9100 不属本 gap 主体，§9100 boundary 保持）。我独立核验 fresh bootstrap 后 `xg_douyin_ai_cs` owner = `xg_douyin_ai_cs`（未变）。

### fresh bootstrap 验证（FB-1，我独立 fixture）

```text
iso_db_owner=postgres          ← fresh 即正确（零手工 ALTER）
iso_app_is_dbo_member=false    ← ownership blocker 不重现
iso_app_db_create=false
iso_app_schema_create=false
iso_app_superuser=false createdb=false createrole=false bypassrls=false
iso_tables_before_alembic=0    ← init 阶段无业务表
iso_9100_db_owner=xg_douyin_ai_cs  ← 9100 未变
```

---

## DEV-only Environment Boundary（C5）

独立重新确认：

```text
docker-compose.dev.yml:41     → ./docker/postgres/init:/docker-entrypoint-initdb.d:ro   （dev 用 init/）
docker-compose.yml:19         → ./docker/postgres/init-prod:ro                          （prod 用 init-prod/）
docker-compose.staging.yml:37 → ./docker/postgres/init-staging:ro                      （staging 用 init-staging/）
```

三个环境用各自独立 init 目录，不共享。`001_create_databases.sql` 仅被 dev compose 引用。init SQL 头部加 DEV-ONLY 边界注释（C5）。

```text
LOCAL DEV = affected
STAGING = NO WRITE / unchanged
PRODUCTION = NO WRITE / unchanged
```

T2 静态测试（我独立运行 16 passed）：prod 用 init-prod / staging 用 init-staging / dev init 含 DEV-ONLY marker，全 PASS。

---

## Permission SQL Contract（Gap②）

`scripts/pg/bootstrap_app_role_permissions.sql` 幂等 SQL，由 `postgres` migration principal 执行，post-Alembic 阶段运行。

### Fail-Closed Guard

```sql
DO $$
BEGIN
  IF current_database() <> 'auto_wechat' THEN RAISE EXCEPTION 'FAIL CLOSED...'; END IF;
  IF current_user <> 'postgres' THEN RAISE EXCEPTION 'FAIL CLOSED...'; END IF;
END
$$;
```

不满足即 RAISE，单事务回滚，无任何授权生效。

### Database / Schema Contract（FB-2，我独立 fixture）

```text
DATABASE CONNECT = allowed
DATABASE CREATE = denied（app role 非 owner，无 ownership 派生）= f
public USAGE = allowed = t
public CREATE = denied（app role 非 pg_database_owner 成员）= f
database owner = false
schema owner = false
```

### Existing Table Privileges（FB-4，我独立 fixture）

```text
SELECT = 61（60 业务表 + alembic_version）
INSERT = 60（alembic_version 已 REVOKE）
UPDATE = 60
DELETE = 60
TRUNCATE = 0（符合 contract，无 TRUNCATE 授予）
```

无 TRUNCATE / REFERENCES / TRIGGER，无 ALL PRIVILEGES 捷径。

### alembic_version Hardening（FB-5，我独立 fixture 写尝试）

C3 顺序硬约束：broad DML GRANT 之后立即 REVOKE → SELECT-only。

```text
INSERT INTO alembic_version → permission denied for table alembic_version
UPDATE alembic_version      → permission denied for table alembic_version
DELETE FROM alembic_version  → permission denied for table alembic_version
TRUNCATE alembic_version    → permission denied for table alembic_version
revision after attempts     → 0034（不变）
```

四路写均 denied，revision 零修改。**alembic_version 不可写 = VERIFIED**。

### Sequence Contract（我独立 fixture）

```text
sequences（public）= 60
granted = USAGE, SELECT（无 UPDATE/setval，无 ALL PRIVILEGES）
```

### ADP Contract（FB-8，我独立 fixture）

```text
pg_default_acl（public, creator=postgres）= 2
  tables    → DELETE,INSERT,SELECT,UPDATE（无 TRUNCATE/REFERENCES/TRIGGER）
  sequences → SELECT,USAGE（无 UPDATE/setval）
```

```text
existing objects = explicit GRANT ON ALL TABLES/SEQUENCES
future objects = ADP（ALTER DEFAULT PRIVILEGES FOR ROLE postgres）
ADP 不反向覆盖既有对象（PG 语义事实）
```

Future object runtime（postgres 创建 future table+seq，**不重跑 permission script**）：

```text
future table INSERT（含 owned seq nextval）→ PASS
future table UPDATE/SELECT/DELETE         → PASS
future table TRUNCATE                     → DENIED（ADP 未授予 TRUNCATE）
future standalone seq nextval             → PASS
```

ADP 真实生效，cleanup 后 tables=61 无残留。

---

## Static Tests（我独立运行）

`tests/test_pg_bootstrap_owner_drift.py`：**16 passed in 0.08s**（我独立执行确认）。

| 测试组 | 覆盖 | 结果 |
|---|---|---|
| T1 Owner Contract | init SQL OWNER postgres / 9100 未变 / role 无 elevated capability | ✅ |
| T2 Environment Boundary | prod 用 init-prod / staging 用 init-staging / DEV-ONLY marker | ✅ |
| T3 Permission SQL Contract | DML grant / no ALL PRIVILEGES / no TRUNCATE / no REFERENCES/TRIGGER / sequence / alembic_version ordering / ADP / fail-closed guard | ✅ |
| T4 Caller Ordering | alembic before permission / alembic failure stops | ✅ |

**分类**：静态测试为字符串/AST 解析，不连 DB。我已用独立 isolated PG runtime 证据（FB-0~FB-12）补充——静态测试不是 runtime 证据，但作为 contract 回归守护有价值。

---

## Independent Fresh Bootstrap Environment

审批建立**自己的新隔离 PG**，不采信执行窗口 `au-pg-bootstrap-iso@25433`：

```text
container = au-pg-approval-iso（独立容器名）
host port = 25434（独立端口，与 canonical@5432 + 执行窗口@25433 都隔离）
volume    = au_pg_approval_v3（独立 volume）
image     = postgres:16-alpine
init      = docker/postgres/init/001_create_databases.sql（修改后 owner=postgres）
```

与 canonical `auto-wechat-postgres-dev`@5432 完全隔离（FB-0）。

---

## FB Gate Verdict（我独立 fixture，13/13 PASS）

| Gate | 验证内容 | 裁定 | 我的独立证据 |
|---|---|---|---|
| FB-0 | Isolation | **PASS** | `au-pg-approval-iso`@25434 / volume `au_pg_approval_v3`，canonical@5432 只读 |
| FB-1 | Fresh Database Owner | **PASS** | fresh owner=postgres（零手工 ALTER）/ app 非 pg_database_owner 成员（f）|
| FB-2 | CREATE Boundary | **PASS** | app db_create=f / schema_create=f / schema_usage=t |
| FB-3 | Empty → Alembic Head | **PASS** | normal caller head=0034 / 61 表 / 60 seq，无 stamp/create_all |
| FB-4 | Application Runtime DML | **PASS** | sel=61/ins=60/upd=60/del=60/trunc=0 + 事务写 INSERT/UPDATE/DELETE ROLLBACK residual=0 |
| FB-5 | alembic_version | **PASS** | SELECT=0034 PASS；INSERT/UPDATE/DELETE/TRUNCATE ×4 permission denied，revision 不变 |
| FB-6 | DDL Negative | **PASS** | CREATE TABLE → permission denied for schema public，无残留 |
| FB-7 | TRUNCATE Negative | **PASS** | TRUNCATE fb7_probe → permission denied，rows_preserved=1 |
| FB-8 | Future Object Contract | **PASS** | future DML PASS / TRUNCATE DENIED / seq PASS（ADP 真实生效，不重跑 script），cleanup tables=61 |
| FB-9 | /ready As App Principal | **PASS** | HTTP 200 / backend=postgresql / database=auto_wechat / head=0034 / principal=auto_wechat（非 postgres/非 SQLite/非 canonical）|
| FB-10 | Cleanup | **PASS** | 临时容器+volume 删除 |
| FB-11 | Permission Bootstrap Idempotency | **PASS** | second run exit 0，snapshot `61/60/2/postgres/0034` before==after 等价，alembic_version 仍 SELECT-only |
| FB-12 | Zero Manual Intervention | **PASS** | empty→init→caller(alembic+permission)→/ready 全自动，零手工 GRANT/ALTER/stamp |

```text
ALL 13 FB GATES = PASS（独立审批窗口自有隔离 fixture）
```

---

## Permission Bootstrap Idempotency（FB-11）

### before snapshot（run#1 后）

```text
select=61 / insert=60 / adp=2 / owner=postgres / head=0034
alembic_version: sel=t / ins=f / trunc=f
```

### second run（全 chain）

```text
LOCAL_DEV_PG_BOOTSTRAP=COMPLETE
exit code=0
no error / no duplicate
```

### after snapshot（run#2 后）

```text
select=61 / insert=60 / adp=2 / owner=postgres / head=0034
alembic_version: sel=t / ins=f / trunc=f
```

before/after 完全等价，无额外高权限，无重复状态。

```text
PERMISSION_BOOTSTRAP_IDEMPOTENCY = VERIFIED
```

---

## Zero Manual Intervention（FB-12）

从全新隔离 PG 开始，只使用批准后的 normal bootstrap chain：

```text
docker run（init SQL 修改后 owner=postgres 自动生效）
  → python scripts/pg/bootstrap_local_dev_pg.py
      → alembic upgrade head（自动）
      → bootstrap_app_role_permissions.sql（自动，单事务）
  → uvicorn app.main:app（DATABASE_URL=auto_wechat@25434）
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

## /ready As App Principal（FB-9）

启动最小应用 probe（port 9002，DATABASE_URL=auto_wechat@25434，principal=auto_wechat）：

```text
GET /ready → HTTP 200
body: {"service":"auto_wechat","status":"ok","checks":[
  {"name":"backend","status":"pass","backend":"postgresql"},
  {"name":"db_connect","status":"pass"},
  {"name":"database_name","status":"pass","expected":"auto_wechat","actual":"auto_wechat"},
  {"name":"alembic_revision","status":"pass","expected":["0034"],...}
]}
```

非 postgres principal / 非 SQLite fallback / 非 canonical PG。

---

## Canonical DB No-Drift

fresh-bootstrap 验证结束后，只读重新确认 canonical local PG（审批前快照 vs 审批后）：

| 维度 | 审批前 | 审批后 | drift? |
|---|---|---|---|
| owner | postgres | postgres | NO |
| head | 0034 | 0034 | NO |
| tables | 61 | 61 | NO |
| app db_create | f | f | NO |
| app schema_create | f | f | NO |
| app superuser | f|f|f | f|f|f | NO |

```text
CANONICAL LOCAL PG = NO DRIFT
```

零测试污染，canonical 未被触碰。

---

## Staging / Production Boundary

```text
STAGING    = NO WRITE / RUNTIME_UNKNOWN   （继续冻结）
PRODUCTION = NO WRITE / RUNTIME_UNKNOWN   （继续冻结）
```

- staging/prod 不使用 `001_create_databases.sql`（T2 + 我独立核验：prod 用 init-prod，staging 用 init-staging）
- 修改 init SQL 只影响 local dev fresh bootstrap
- staging/prod 用单 superuser role 模型，与分离 contract 本就不同，属 accepted residual risk
- 本窗口 NO REMOTE WRITE
- 不得宣称"staging/prod ownership fixed"

---

## RAG Query Status Correction（★ CR-1 核心 correction）

实施报告 §21 + CLAUDE.md diff 仍把 `B. RAG Query 0005 PG` 列为 P1 remaining Technical Closure blocker——**过期状态，必须修正**。

正式事实（commit `5d8b6ba`，2026-08-11 独立审批 APPROVED_WITH_CORRECTIONS）：

```text
RAG Query 0005 = PG_RUNTIME_VERIFIED
P1 ACTIVE CONSUMER PG VERIFICATION = COMPLETE
```

因此 P1 remaining Technical Closure 只能写：

```text
1. Global Active None Audit
2. Final PostgreSQL Concurrent Closure Gate
```

不得保留 `B. RAG Query 0005`，也不得继续把 A′ 写 OPEN（本轮审批通过后 A′ = RESOLVED）。

**裁定**：CR-1 不改变 fresh-bootstrap 实现正确性（已 13/13 PASS），但属过期状态必须修正。实施窗口在 commit 前须把实施报告 §21 + CLAUDE.md 的 B. RAG Query 0005 remaining blocker 行移除/修正。

---

## Final Gap Verdict

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP
= RESOLVED

FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP
= RESOLVED

FRESH_BOOTSTRAP_PRINCIPAL_REPRODUCIBILITY
= VERIFIED
```

同时：

```text
CURRENT CANONICAL LOCAL PG = VERIFIED
FRESH LOCAL PG BOOTSTRAP = REPRODUCIBLE
STAGING / PRODUCTION = RUNTIME_UNKNOWN
```

---

## P1 Remaining Technical Closure

```text
P1 ACTIVE CONSUMER PG VERIFICATION = COMPLETE
FRESH BOOTSTRAP PRINCIPAL REPRODUCIBILITY = VERIFIED

COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE = PENDING
```

剩余 Technical Closure（CR-1 修正后）：

```text
1. Global Active None Audit
2. Final PostgreSQL Concurrent Closure Gate
```

不得保留 `B. RAG Query 0005`（已 PG_RUNTIME_VERIFIED）或 `A′ Bootstrap Owner Drift`（本轮 RESOLVED）。

```text
RB-10 = NOT AUTHORIZED（不是 COMPUTE-IDEMPOTENCY-001 closure blocker）
```

---

## Commit Authorization

审批通过（APPROVED_WITH_CORRECTIONS），授权执行窗口完成一次独立 implementation closure commit。

允许范围：

```text
docker/postgres/init/001_create_databases.sql
scripts/pg/bootstrap_app_role_permissions.sql
scripts/pg/bootstrap_local_dev_pg.py
tests/test_pg_bootstrap_owner_drift.py
docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_IMPLEMENTATION_REPORT.md
docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_IMPLEMENTATION_APPROVAL.md（本审批报告）
CLAUDE.md
docs/ai/05_PROJECT_CONTEXT.md
```

必须把 `RESOLVED_PENDING_APPROVAL` 同步为 `RESOLVED / VERIFIED`，并修正过期的 RAG Query 0005 remaining blocker（CR-1）。

不得混入：Global None Audit / Final Concurrent Closure / 9100 权限整改 / migration / consumer 业务代码 / RB-10。

建议 commit message：

```text
修复：闭环本地PostgreSQL可重复权限引导
```

不得 push，除非用户另行明确要求。

---

## Corrections 清单

```text
CR-1: 实施报告 §21 + CLAUDE.md 仍把 B. RAG Query 0005 PG 列为 P1 remaining blocker
      → 过期状态，必须修正（RAG Query 0005 已 PG_RUNTIME_VERIFIED @5d8b6ba）
      → P1 remaining 只保留 C. Global Active None Audit + D. Final Concurrent Closure
      → 不改变 fresh-bootstrap 实现正确性

CR-2: normal bootstrap caller 可发现性
      → caller 调用方式仅在脚本 docstring + 实施报告，从脚本可发现，非休眠
      → 建议 README/runbook 补最小调用说明（HOW/WHEN/WHAT COMMAND）
      → 文档性提示，不阻断批准，不改变实现正确性
```

---

## 审批窗口纪律遵守

- ✅ 不采信执行窗口自述：用独立隔离 PG `au-pg-approval-iso`@25434（非执行窗口 `au-pg-bootstrap-iso`@25433）独立复现全部 13 FB Gate
- ✅ 不扰动 canonical DB：审批前/后只读快照比对 no-drift（owner/head/tables/CREATE 全不变）
- ✅ 未修改业务代码 / migration / M07 Core / DB-BL / FastAPI startup / staging-prod init
- ✅ 未设计/整改 9100 IAM（9100 owner 行未变，§9100 boundary 保持）
- ✅ 未开始 Global Active None Audit / Final Concurrent Closure / RB-10
- ✅ consumer 验证仅用 canonical app principal（非 superuser 替代）
- ✅ fresh-bootstrap 验证用隔离临时 PG，完成后清理（容器+volume 删除）
- ✅ /ready 以 application principal PASS（非 postgres / 非 SQLite / 非 canonical）

---

> 审批完成。按指令 §38：完成后停止。
> 不自行开始 Global Active None Audit 或 Final Concurrent Closure。
> 交执行窗口按 CR-1/CR-2 修正后做 implementation closure commit（LOCAL DEVELOPMENT ONLY）。
