# P1 — PostgreSQL Application Role Permission 实施报告

> 任务：`P1-PG-APP-ROLE-2 — LOCAL PostgreSQL Application Permission 实施`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的 PostgreSQL runtime prerequisite
> 实施授权：`AUTHORIZED — LOCAL DEVELOPMENT ONLY`（来自 [P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md) §16）
> Ownership Correction 授权：`P1-PG-APP-ROLE-1R — Candidate A APPROVED`（[P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md) §8/§10）
> 实施审批：`P1-PG-APP-ROLE-2 Implementation = APPROVED`（见 [P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md)）
> 日期：2026-08-10
> 窗口：P1-PG-APP-ROLE-2 LOCAL PostgreSQL Application Permission 执行窗口
> Source of Truth：真实 PG runtime 证据（独立只读 catalog inspection + 应用角色实测 + 真实 HTTP /ready） > 冻结文档 > 推测

---

## 结论速览

| 维度 | 结论 |
|---|---|
| 前置 Git Checkpoint | ✅ `ea224a8`（C1-C4 corrections + blocked evidence + ownership approval）|
| Ownership Correction (Candidate A) | ✅ `ALTER DATABASE auto_wechat OWNER TO postgres;` 已执行 |
| PR-1B Hard Verification | ✅ PASS（DB owner=postgres，CREATE 泄漏消除）|
| PR-2 Before Snapshot | ✅ FROZEN |
| PR-3 Existing Object Grants | ✅ DML 60 表 + SELECT alembic_version + 60 sequences |
| C3 alembic_version 硬收敛 | ✅ SELECT-only（GRANT→REVOKE 顺序硬约束已落地）|
| PR-4 Future ADP (FOR ROLE postgres) | ✅ tables DML + sequences USAGE/SELECT |
| PR-5 alembic_version 运行时 | ✅ SELECT PASS / WRITE DENIED |
| PR-6 Elevated Capability Audit | ✅ 无 superuser/DDL/ownership 残留 |
| PR-7 /ready as Application Role | ✅ HTTP 200 / backend=postgresql / db=auto_wechat / head=0034 / principal=auto_wechat |
| PR-8 Representative DML | ✅ INSERT/UPDATE/SELECT/DELETE 事务内 ROLLBACK |
| PR-9 Sequence/Identity | ✅ nextval/currval PASS |
| PR-10 DDL Negative | ✅ CREATE TABLE → DENIED |
| PR-11 alembic_version Write Negative | ✅ UPDATE/INSERT/DELETE → DENIED |
| PR-12 TRUNCATE Negative | ✅ TRUNCATE → DENIED |
| PR-13 After Snapshot | ✅ FROZEN（before/after 对比符合目标 contract）|
| Future Object Runtime Test | ✅ ADP 真实生效（postgres 建表→app DML PASS / TRUNCATE DENIED / sequence PASS→清理）|
| DB-BL | 未重开（schema baseline 0034 / 61 表不变）|
| Permission Gap Verdict | `RESOLVED`（实施已独立审批 APPROVED，见 §22）|
| Consumer Unlock | `0032/0033/0034: UNBLOCKED_FOR_PG_VERIFICATION`（APPLICATION_ROLE_PREREQUISITE=VERIFIED；consumer runtime evidence 尚未执行，不得写 PG_VERIFIED）|
| P1 | OPEN / TECHNICAL_CLOSURE=PENDING（application-role prerequisite 已 VERIFIED，非整个 P1 closure）|

---

## 1. Corrections Applied（C1-C4）

C1-C4 Correction Doc-Sync 已在前序窗口完成并冻结于设计文档 [P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md](P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md)：

| Correction | 内容 | 落地位置 |
|---|---|---|
| C1 命名 | `Model A′` → `Runtime Principal Model: SEPARATED MIGRATION / APPLICATION RESPONSIBILITY` | DESIGN §2.2/§14 |
| C2 PR-12 | TRUNCATE 负向 gate | DESIGN §11/§12 |
| C3 硬收敛 | alembic_version GRANT→REVOKE 顺序硬约束；DROP/recreate 必须重新收敛 | DESIGN §3.5/§6.4 |
| C4 环境证据 | Dev=`LOCAL_PG_RUNTIME_VERIFIED`；Staging/Prod=`CONFIG_VERIFIED/RUNTIME_UNKNOWN` | DESIGN §1.4 |
| PR-11 | alembic_version 写负向独立 gate | DESIGN §11/§12 |

```text
P1-PG-APP-ROLE-1: CORRECTIONS_APPLIED / FROZEN
```

---

## 2. Environment Identity（PR-0）

```text
TARGET = LOCAL DEVELOPMENT ONLY

container/service = auto-wechat-postgres-dev (Up, healthy)
host:port          = 0.0.0.0:5432
database           = auto_wechat
current_database() = auto_wechat
server_version     = PostgreSQL 16.14 (x86_64-pc-linux-musl, Alpine)
alembic head       = 0034
physical tables    = 61

NOT PRODUCTION / NOT STAGING
```

**PR-0 = PASS。** 即 DB-BL-2D 冻结的 canonical local PG（`AUTO_WECHAT_DEV_PG = CANONICAL_ALEMBIC_BASELINE@0034`）。

---

## 3. Ownership Correction（Candidate A）

### 3.1 Before Owner（独立只读核验，与 1R 审批 §2.2 零偏差）

```text
database owner               = auto_wechat          ← BLOCKER 来源
auto_wechat role             = LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f / INHERIT=t
auto_wechat memberships      = (none)
auto_wechat = pg_database_owner member = TRUE（隐式，不可 REVOKE）
61 canonical objects owner    = postgres
auto_wechat effective DATABASE CREATE = true   ← ownership 派生
auto_wechat effective public SCHEMA CREATE = true ← ownership 派生（pg_database_owner → schema ownership）
public schema owner/acl      = pg_database_owner / {pg_database_owner=UC, =U}
current grants               = 0 table / 0 seq / 0 default_acl / douyin_leads.relacl=NULL
```

事实与 1R 审批冻结证据一致，无漂移。

### 3.2 Approved SQL（唯一批准路径）

来自 1R 审批 §8（Candidate A APPROVED / Candidate B REJECTED）：

```sql
ALTER DATABASE auto_wechat OWNER TO postgres;
```

执行结果：`ALTER DATABASE`（成功）。

执行范围严格隔离——本轮 ownership correction step **未同时**做 ALTER TABLE OWNER / ALTER SCHEMA OWNER / ALTER ROLE / GRANT / REVOKE / ALTER DEFAULT PRIVILEGES（这些在后续 PR-3/PR-4 独立步骤执行）。

### 3.3 PR-1B Hard Verification（transfer 后重跑）

| 验证项 | 期望 | 实测 |
|---|---|---|
| database owner | postgres | ✅ postgres |
| auto_wechat is db owner | false | ✅ f |
| pg_database_owner member | false | ✅ f（隐式成员关系随 ownership 转移消除）|
| effective DATABASE CREATE | false | ✅ f |
| effective public SCHEMA CREATE | false | ✅ f |
| effective DATABASE CONNECT | true（PUBLIC）| ✅ t |
| effective public USAGE | true（PUBLIC =U）| ✅ t |
| SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS | all false | ✅ f/f/f/f |
| memberships | none | ✅ (none) |
| 61 表 owner | postgres | ✅ 不变 |
| alembic head | 0034 | ✅ 不变 |

```text
PR-1B: PASS
APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER: RESOLVED
```

transfer 后 `auto_wechat` CREATE 的唯一来源（ownership 链）已消除，无残留 PUBLIC/explicit/membership/ACL 来源，无需 REVOKE，无需 STOP。

---

## 4. Migration Principal

```text
LOCAL MIGRATION PRINCIPAL = postgres  （FROZEN，1R 审批 §6 确认）
```

- postgres role：EXISTS / rolsuper=t / rolcanlogin=t / rolcreatedb=t；
- 61 canonical objects owner=postgres（transfer 后 database owner 也对齐 postgres）；
- Alembic 本地执行身份=postgres（env.py 读 DATABASE_URL，迁移代码无权限 DDL）；
- 未来 ADP contract 冻结 `FOR ROLE postgres`。

→ ownership transfer 后 database owner 与对象 owner 对齐到同一 migration principal，无"对象 owner=postgres 但 DB owner=auto_wechat"脱节残留。

---

## 5. PR-2 — Before Privilege Snapshot

post-ownership-transfer / pre-GRANT 完整快照（FROZEN）：

```text
auto_wechat role   : LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f / INHERIT=t
memberships        : (none)
database           : owner=postgres / datacl=(null)
                     CONNECT=t / CREATE=f / TEMP=t
public schema      : owner=pg_database_owner / USAGE=t / CREATE=f
                     ACL={pg_database_owner=UC/pg_database_owner, =U/pg_database_owner}
tables grants      : SELECT=0 / INSERT=0 / UPDATE=0 / DELETE=0 / TRUNCATE=0 / REFERENCES=0 / TRIGGER=0
sequence grants    : 0
sequence count     : 60 (public)
default ACL        : 0 (public)
douyin_leads.relacl: (null)
alembic_version    : SELECT=f / INSERT=f / UPDATE=f / DELETE=f / TRUNCATE=f （全无权限，gap 仍在）
```

---

## 6. Existing Object Grants（PR-3）

由 migration principal `postgres` 执行（对象 owner=postgres）：

```sql
GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;
GRANT USAGE ON SCHEMA public TO auto_wechat;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;
```

执行结果：4 × `GRANT`。

落地核验（information_schema 计数）：

```text
SELECT    = 61   （含 alembic_version）
INSERT    = 60   （alembic_version 将由 §7 REVOKE 排除）
UPDATE    = 60
DELETE    = 60
TRUNCATE  = 0    （未授予，符合 contract）
REFERENCES= 0
TRIGGER   = 0
```

代表性业务表 `douyin_leads` effective：`SEL=t INS=t UPD=t DEL=t TRUNC=f REF=f TRIG=f` ✅

---

## 7. alembic_version Hardening（C3 顺序硬约束）

broad DML GRANT 之后**立即**对 alembic_version 收敛写权限：

```sql
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;
```

执行结果：`REVOKE`。

C3 顺序硬约束落地核验——alembic_version effective：

```text
SELECT   = true   ← /ready 读 revision 合法需要
INSERT   = false
UPDATE   = false
DELETE   = false
TRUNCATE = false  （GRANT 集合本不含 TRUNCATE）
```

→ alembic_version 收敛为 SELECT-only，C3 硬约束满足。

---

## 8. Existing Sequences（Step 10）

```text
sequence count (public) = 60
granted privileges       = USAGE, SELECT
```

未使用 `ALL PRIVILEGES`，仅设计批准的最小权限（USAGE 供 nextval，SELECT 供 currval；不含 UPDATE/setval）。落地计数：`role_usage_grants(grantee=auto_wechat, object_type=SEQUENCE) = 60`。

---

## 9. Future Default Privileges（PR-4）

creator-specific 三要素齐备（`FOR ROLE postgres` + `IN SCHEMA public` + 对象类型）：

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
```

执行结果：2 × `ALTER DEFAULT PRIVILEGES`。

`pg_default_acl`（public）解码核验：

```text
creator=postgres / schema=public / objtype=r (tables)  / grantee=auto_wechat / privs=DELETE,INSERT,SELECT,UPDATE  （无 TRUNCATE/REFERENCES/TRIGGER）
creator=postgres / schema=public / objtype=S (sequences)/ grantee=auto_wechat / privs=SELECT,USAGE
```

→ 2 条 ADP，creator 正确，无 TRUNCATE 自动授予。

---

## 10. alembic_version Recreation Contract（Step 12）

继续冻结（C3）：若未来 `alembic_version` 被 DROP/recreate，ADP 会让重建对象自动拿到 DML，必须在重建后立即重跑 §7 REVOKE 重新收敛到 SELECT-only。当前不为该低频异常建 trigger/权限平台（YAGNI），但"重建后必须重新收敛"是 runbook 硬约束。

---

## 11. PR-5 — alembic_version Runtime Test（应用角色直连）

```text
SELECT version_num FROM alembic_version;          → 0034   PASS
UPDATE alembic_version SET version_num = version_num WHERE false; → DENIED (permission denied for table alembic_version)
```

正向 SELECT PASS、负向 WRITE DENIED。零 revision 修改。

---

## 12. PR-6 — Elevated Capability Audit

```text
auto_wechat: SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f
public schema CREATE = false
database CREATE      = false
auto_wechat is database owner = false
61 canonical business objects owner = postgres（application role 非 owner）
```

→ application role 无任何 ownership-level / DDL / superuser 残留。

---

## 13. PR-7 — /ready as Application Principal

显式以 `auto_wechat` 应用角色 PG 连接启动 9000（一次性容器 `au-ready-probe`，DATABASE_URL=`postgresql+psycopg://auto_wechat@auto-wechat-postgres-dev:5432/auto_wechat`，未用 postgres superuser）。

真实 HTTP /ready：

```json
HTTP 200
{
  "service": "auto_wechat", "status": "ok",
  "checks": [
    {"name":"backend","status":"pass","backend":"postgresql"},
    {"name":"db_connect","status":"pass"},
    {"name":"database_name","status":"pass","expected":"auto_wechat","actual":"auto_wechat"},
    {"name":"alembic_revision","status":"pass","expected":["0034"],"actual":["0034"]},
    {"name":"critical_tables","status":"pass","tables":[
       {"table":"douyin_leads","status":"pass"},
       {"table":"sales_staff","status":"pass"}]}
  ]
}
```

principal 证据（同 DATABASE_URL 连接打印）：`current_user=auto_wechat / current_database=auto_wechat`。

```text
backend  = PostgreSQL
database = auto_wechat
principal= auto_wechat（非 superuser）
revision = 0034
HTTP     = 200
```

未让默认 SQLite 环境参与证据。探测容器已停止移除（`docker stop au-ready-probe`，`--rm`）。

---

## 14. PR-8 — Representative Runtime DML

代表表 `autoreply_admin_audit_logs`（id bigserial、action/target_type NOT NULL、created_at default now()、无 FK）。事务内 INSERT→UPDATE→SELECT→DELETE→ROLLBACK：

```text
INSERT (action,target_type) VALUES ('perm_test_insert','perm_test') RETURNING id;  → id=1, INSERT 0 1   PASS
UPDATE ... SET action='perm_test_updated' WHERE action='perm_test_insert';         → UPDATE 1          PASS
SELECT id,action,target_type WHERE action='perm_test_updated';                     → 1 row             PASS
DELETE FROM ... WHERE action='perm_test_updated' RETURNING id;                    → DELETE 1          PASS
ROLLBACK                                                                                              → no pollution
residual count (action LIKE 'perm_test%') after rollback                          → 0                 PASS
```

无真实外部业务动作（未发抖音/微信/外部 API）。

---

## 15. PR-9 — Sequence / Identity

同 PR-8 事务内验证 SERIAL sequence：

```text
INSERT 触发 nextval('autoreply_admin_audit_logs_id_seq') → id=1   PASS (sequence USAGE)
SELECT currval('autoreply_admin_audit_logs_id_seq')     → 1       PASS (sequence SELECT)
```

应用角色 INSERT 不因 `permission denied for sequence` 失败。事务 ROLLBACK 后无残留。

---

## 16. PR-10 — DDL Negative Test（应用角色）

```sql
CREATE TABLE perm_neg_test_au(id bigint);
```

结果：`ERROR: permission denied for schema public`。**DENIED** ✅。未留下 table。CREATE 泄漏已消除（PR-1B ownership transfer + 无 schema CREATE）。

---

## 17. PR-11 — alembic_version Write Negative（应用角色）

```text
UPDATE alembic_version SET version_num = version_num WHERE false; → DENIED
INSERT INTO alembic_version(version_num) VALUES('0034');          → DENIED
DELETE FROM alembic_version WHERE false;                          → DENIED
```

三路写均 `permission denied for table alembic_version`。SELECT-only 收敛经实际写尝试反证。

---

## 18. PR-12 — TRUNCATE Negative（应用角色）

```sql
TRUNCATE douyin_leads;
```

结果：`ERROR: permission denied for table douyin_leads`。**DENIED** ✅。对真实业务表无风险（权限层先抛）。

---

## 19. PR-13 — After Privilege Snapshot

与 PR-2 同一 inspection contract（FROZEN）：

```text
auto_wechat role   : LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f
database           : owner=postgres / CONNECT=t / CREATE=f / TEMP=t
public schema      : owner=pg_database_owner / USAGE=t / CREATE=f
tables grants      : SELECT=61 / INSERT=60 / UPDATE=60 / DELETE=60 / TRUNCATE=0 / REFERENCES=0 / TRIGGER=0
douyin_leads       : SEL=t INS=t UPD=t DEL=t TRUNC=f
alembic_version    : SEL=t INS=f UPD=f DEL=f TRUNC=f
sequence grants    : 60
default ACL        : creator=postgres / schema=public / grantee=auto_wechat
                      tables  → DELETE,INSERT,SELECT,UPDATE
                      sequences→ SELECT,USAGE
```

### Before / After 对比

| 维度 | Before（PR-2）| After（PR-13）| 目标 |
|---|---|---|---|
| database owner | auto_wechat | **postgres** | postgres ✅ |
| auto_wechat SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS | f/f/f/f | f/f/f/f | all false ✅ |
| database CREATE | true（ownership 泄漏）| **false** | false ✅ |
| public CREATE | true（ownership 泄漏）| **false** | false ✅ |
| public USAGE | true（PUBLIC）| true（PUBLIC + 显式 GRANT）| true ✅ |
| business table SELECT | 0 | **60** | 60 ✅ |
| business table INSERT/UPDATE/DELETE | 0 | **60** | 60 ✅ |
| business table TRUNCATE/REFERENCES/TRIGGER | 0 | 0 | 0 ✅ |
| alembic_version SELECT | false | **true** | true ✅ |
| alembic_version INSERT/UPDATE/DELETE | false | **false**（已收敛）| false ✅ |
| sequence grants | 0 | **60** | 60 ✅ |
| default ACL (creator/grantee) | 0 | **postgres → auto_wechat** | postgres→auto_wechat ✅ |

---

## 20. Future Object Runtime Verification

不只看 `pg_default_acl`，由 migration principal `postgres` 创建专门临时验证对象（temporary verification only，非业务 schema，不动 Alembic revision）：

```sql
CREATE TABLE perm_adp_verify_tbl (id bigserial PRIMARY KEY, note text, created_at timestamptz DEFAULT now());
CREATE SEQUENCE perm_adp_verify_seq;
```

应用角色 `auto_wechat` 验证 creator-specific ADP 真实生效：

```text
future table INSERT (含 owned sequence nextval)  → id=1, INSERT 0 1   PASS
future table SELECT                              → 1 row             PASS
future table UPDATE                              → UPDATE 1          PASS
future table DELETE                              → DELETE 1          PASS
future table TRUNCATE                            → DENIED (permission denied for table)  ← ADP 未授予 TRUNCATE ✅
future standalone sequence nextval/currval       → nv=1, cv=1        PASS（ADP sequence 分支）
```

由 `postgres` 清理：

```sql
DROP TABLE perm_adp_verify_tbl;
DROP SEQUENCE perm_adp_verify_seq;
```

清理核验：`residual perm_adp objects = 0`；`alembic head = 0034`（不变）；`table count = 61`（不变，DB-BL 未重开）。

---

## 21. PR-0 ~ PR-13 逐项

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| PR-0 | 环境 LOCAL DEV ONLY | ✅ PASS | auto-wechat-postgres-dev @5432，db=auto_wechat，PG 16.14，head=0034 |
| PR-1 | 应用角色存在性 | ✅ PASS | LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f / memberships=none |
| PR-1B | Database/Schema Ownership Hard Gate | ✅ PASS | ALTER DATABASE OWNER→postgres 后 dbCREATE=f / schemaCREATE=f / pg_dbo_member=f |
| PR-2 | 实施前权限快照 | ✅ PASS | 0/0/0 grants，relacl null，post-transfer pre-GRANT FROZEN |
| PR-3 | 最小权限落地 | ✅ PASS | SELECT=61 / INSERT/UPDATE/DELETE=60 / TRUNCATE=0 / sequences=60 |
| PR-4 | 未来对象 ADP | ✅ PASS | 2 ADP rows，creator=postgres，grantee=auto_wechat，无 TRUNCATE |
| PR-5 | alembic_version 运行时 | ✅ PASS | SELECT→0034 PASS；UPDATE WHERE FALSE→DENIED |
| PR-6 | 无意外 DDL/superuser | ✅ PASS | superuser/createdb/createrole=f；schema/db CREATE=f；非对象 owner |
| PR-7 | /ready 以应用角色 PASS | ✅ PASS | HTTP 200，backend=postgresql，db=auto_wechat，head=0034，principal=auto_wechat |
| PR-8 | 代表性读写事务 | ✅ PASS | INSERT/UPDATE/SELECT/DELETE 事务内成功并 ROLLBACK，residual=0 |
| PR-9 | sequence/identity | ✅ PASS | nextval→1 / currval→1 |
| PR-10 | 负向 DDL | ✅ PASS | CREATE TABLE→permission denied for schema public |
| PR-11 | alembic_version 写负向 | ✅ PASS | UPDATE/INSERT/DELETE→DENIED |
| PR-12 | TRUNCATE 负向 | ✅ PASS | TRUNCATE douyin_leads→DENIED |
| PR-13 | 实施后快照对比 | ✅ PASS | before/after diff 符合目标 contract |
| Future Object Runtime Test | ADP 真实生效 | ✅ PASS | postgres 建表→app DML PASS / TRUNCATE DENIED / sequence PASS→清理 |

---

## 22. Permission Gap Verdict

实施已独立审批 `APPROVED`（[P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md)）。正式冻结：

```text
APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER:
RESOLVED

APPLICATION_ROLE_PERMISSION_GAP:
RESOLVED

LOCAL DEV application-role permission = VERIFIED
```

runtime evidence（保留）：

```text
db owner                          = postgres
app role                          = auto_wechat（非 superuser）
database CREATE                   = false
public schema CREATE              = false
DML contract (SELECT/INSERT/UPDATE/DELETE) = PASS（60 业务表）
alembic_version                   = SELECT-only（写 DENIED）
ADP creator                        = postgres（FOR ROLE postgres IN SCHEMA public）
/ready as auto_wechat              = PASS（HTTP 200 / postgresql / 0034）
DDL / TRUNCATE negative            = PASS（DENIED）
```

ownership blocker 已解除（PR-1B PASS），application role 携带合法最小 DML，`/ready` 以应用角色 PASS。本轮 DB 写操作均发生在 LOCAL DEV canonical PG，审批已复核实际数据库状态并 APPROVED。

环境证据纪律（C4 冻结）：

```text
LOCAL DEV    : application-role permission = VERIFIED
STAGING      : CONFIG_VERIFIED / RUNTIME_UNKNOWN
PRODUCTION   : CONFIG_VERIFIED / RUNTIME_UNKNOWN
```

不得写"PostgreSQL permissions fully resolved everywhere"。

---

## 23. Consumer Unlock

```text
0032 Daily Report         : UNBLOCKED_FOR_PG_VERIFICATION（APPLICATION_ROLE_PREREQUISITE = VERIFIED）
0033 M05 Material Analysis: UNBLOCKED_FOR_PG_VERIFICATION（APPLICATION_ROLE_PREREQUISITE = VERIFIED）
0034 Preview              : UNBLOCKED_FOR_PG_VERIFICATION（APPLICATION_ROLE_PREREQUISITE = VERIFIED）
```

application-role prerequisite 已 VERIFIED，consumer PG verification 解锁。但 consumer runtime evidence 尚未执行——**严禁写 `PG_VERIFIED`**。0032/0033/0034 须由独立 consumer PG verification 窗口实施。

---

## 24. P1 Status

```text
P1 COMPUTE-IDEMPOTENCY-001
  = OPEN
  TECHNICAL_CLOSURE = PENDING
```

当前完成的是 **PostgreSQL application-role prerequisite**（已 APPROVED / VERIFIED），不是整个 P1 closure。

本窗口成果：
- Ownership Correction（Candidate A）已执行 + PR-1B PASS；
- PR-2~PR-13 全 PASS + Future Object Runtime Test PASS；
- 应用角色 `/ready` 以非 superuser PASS；
- 实施已独立审批 APPROVED；
- DB-BL 未重开（0034 / 61 表不变），M07 Core / 迁移 / RB-10 / consumer 业务 未触碰；
- CR-4 措辞修正：LOCAL DEV app-role GRANT 已落地（permission VERIFIED）；但 staging/prod 仍 RUNTIME_UNKNOWN，CR-4 的 staging/prod 侧 application-role 治理属独立部署审批，不在本窗口范围。

### 24.1 Bootstrap Prevention Gap（新登记）

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP:
OPEN
```

原因：`docker/postgres/init/001_create_databases.sql:20-21` 仍含等价 `CREATE DATABASE auto_wechat OWNER auto_wechat`，会在未来 clean PostgreSQL bootstrap 时重新制造 `application principal = database owner`，与已冻结的 `SEPARATED MIGRATION / APPLICATION RESPONSIBILITY` 冲突。

```text
CURRENT RUNNING LOCAL DB : COMPLIANT（runtime 已 ALTER DATABASE OWNER TO postgres + GRANT/ADP 落地）
FRESH BOOTSTRAP PATH     : NOT YET COMPLIANT（init SQL 仍 OWNER auto_wechat）
```

该 gap **DOES NOT BLOCK 当前 0032/0033/0034 PG VERIFICATION**（当前运行库已合规），但必须在 next clean local PG bootstrap 或 P1 final technical closure 之前关闭。本轮**禁止修改 init SQL**（init SQL 同步修正属独立 runbook 审批）。

P1 Technical Closure 仍阻塞在：
- A. ~~Application Role Permission Implementation 独立审批复核~~ ✅ APPROVED（本报告）；
- A′. LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP（init SQL OWNER auto_wechat，fresh bootstrap 不合规，见 §24.1）；
- B. RAG Query 0005 PG（Docker 恢复后独立补）；
- C. Global Active None Audit；
- D. Final PG Concurrent Closure Gate。

---

## 25. 实施审批与提交

实施已独立审批 `APPROVED`（[P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md)）。审批后文档同步 + exact approved diff commit 已授权提交。

- 前置治理 checkpoint：`ea224a8`（C1-C4 corrections + blocked evidence + ownership approval，不含 ownership 实施结果）；
- 实施闭环 commit：见本仓库 git log（含本报告 + 实施审批 + CLAUDE.md/05_PROJECT_CONTEXT 状态同步）。

本窗口遵守 §26 全部禁令：
- ✅ 未碰 staging/prod；
- ✅ 未 SUPERUSER grant / CREATEDB/CREATEROLE grant；
- ✅ 未修改 migration（0034 不动）/ 未重开 DB-BL（schema baseline 不变）；
- ✅ 未动 P1 consumer 业务 / M07 Core / RB-10 cleanup；
- ✅ 未开始 0032/0033/0034 consumer verification；
- ✅ 未用 ALL PRIVILEGES 捷径；
- ✅ 未改 init SQL（001_create_databases.sql 仍 `OWNER auto_wechat`——init SQL 同步修正属后续 runbook 审批，不在本窗口范围）。

提交：**P1-PG-APP-ROLE-2 Implementation 独立审批窗口。**

---

## 附：本窗口独立核验证据索引

| 核验项 | 方法 | 结论 |
|---|---|---|
| 前置 checkpoint | `git log ea224a8` | C1-C4 + blocked + ownership approval 已提交 |
| 环境身份 | `psql current_database/user/version` | auto_wechat / postgres / PG 16.14 / head=0034 / 61 表 |
| Ownership before | `pg_database.datdba` | auto_wechat（blocker）|
| ALTER DATABASE OWNER | migration principal 执行 | ALTER DATABASE 成功 |
| Ownership after | `pg_database.datdba` + `has_*_privilege` | postgres；dbCREATE=f / schemaCREATE=f / pg_dbo_member=f |
| grants 落地 | `information_schema.role_table_grants` | SELECT=61 / INSERT/UPDATE/DELETE=60 / TRUNCATE=0 |
| alembic_version 收敛 | `has_table_privilege` + 应用角色写尝试 | SEL=t / 写全 DENIED |
| sequences | `role_usage_grants` | 60 |
| ADP | `pg_default_acl` + aclexplode | creator=postgres / grantee=auto_wechat / 无 TRUNCATE |
| /ready HTTP | 真实 HTTP curl（应用角色 DATABASE_URL 容器）| HTTP 200 / postgresql / 0034 |
| principal 证据 | 同连接 `current_user` | auto_wechat |
| 代表性 DML | 事务内 INSERT/UPDATE/SELECT/DELETE + ROLLBACK | PASS / residual=0 |
| sequence | nextval/currval | 1 / 1 |
| DDL 负向 | 应用角色 CREATE TABLE | DENIED (schema) |
| alembic 写负向 | 应用角色 UPDATE/INSERT/DELETE | DENIED ×3 |
| TRUNCATE 负向 | 应用角色 TRUNCATE douyin_leads | DENIED |
| Future object ADP | postgres 建临时对象→app 验证→drop | DML PASS / TRUNCATE DENIED / seq PASS / residual=0 |
| DB-BL 未重开 | alembic head + table count | 0034 / 61 不变 |

所有核验：只读 catalog inspection + 应用角色实测 + 真实 HTTP /ready + 事务内回滚 DML + 临时验证对象（已清理）。零业务污染，零迁移修改，零 DB-BL 重开。
