# P1 — PostgreSQL Application Role Permission 实施 独立审批报告（Approval）

> 任务：`P1-PG-APP-ROLE-2 — LOCAL Permission Implementation 独立审批窗口`
> 审查对象：[P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md)
> 前置治理 checkpoint：`ea224a8`（C1-C4 corrections + blocked evidence + ownership approval，已提交）
> 审批日期：2026-08-10
> 审批窗口：P1-PG-APP-ROLE-2 Independent Approval Window
> Source of Truth：审批窗口独立只读 catalog inspection + 应用角色实测 + 真实 HTTP /ready（非采信执行窗口报告自述）
> 环境：LOCAL DEVELOPMENT ONLY（`auto-wechat-postgres-dev` @5432，db=`auto_wechat`，PG 16.14，head=0034）

---

## Technical Decision

```text
APPROVED
```

PR-1B～PR-13 全部由审批窗口独立复现通过；§11 Future Object Runtime 独立复现通过。当前运行库 runtime contract 成立，未发现影响权限正确性的修正项。Bootstrap ownership drift gap 登记为 OPEN，但不阻断当前 consumer PG verification。

**未采用 APPROVED_WITH_CORRECTIONS**：审批窗口在核验过程中发现的 2 处差异（`has_database_privilege` 2 参数误读、`role_usage_grants` 不报 sequence SELECT）均为**审批窗口自身的 inspection 方法误差**，经改用 3 参数形式 / `has_sequence_privilege` 后与执行窗口报告零偏差，不构成报告/文档修正项。

---

## Environment Identity（PR-0）

| 项 | 审批窗口独立实测 | 期望 |
|---|---|---|
| container/service | `auto-wechat-postgres-dev`（Up 6h, healthy）| auto-wechat-postgres-dev |
| host:port | 0.0.0.0:5432 | 5432 |
| current_database() | `auto_wechat` | auto_wechat |
| server_version | PostgreSQL 16.14 (x86_64-pc-linux-musl, Alpine) | 16.14 |
| alembic head | 0034 | 0034 |
| physical tables (public) | 61 | 61 |
| environment | LOCAL DEVELOPMENT ONLY | NOT STAGING / NOT PRODUCTION |

```text
PR-0 = PASS
```

---

## Ownership Correction Verification（PR-1B）

不采信报告自述，独立 catalog inspection：

| 验证项 | 审批窗口独立实测 | 期望 |
|---|---|---|
| database owner（`pg_database.datdba`）| **postgres** | postgres |
| `auto_wechat` is `pg_database_owner` member | **false** | false |
| 61 canonical tables owner 分布 | owner_postgres=61 / owner_auto_wechat=0 / owner_other=0 | 全 postgres |
| `auto_wechat` effective DATABASE CREATE | **false** | false |
| `auto_wechat` effective public SCHEMA CREATE | **false** | false |
| `auto_wechat` effective DATABASE CONNECT | true（PUBLIC）| true |
| `auto_wechat` effective public USAGE | true（PUBLIC + 显式 GRANT）| true |

> 核验方法注记：`has_database_privilege('auto_wechat','CREATE')`（2 参数）会把第一参数当**数据库名**、按当前连接用户(postgres superuser)判定，恒为 true——审批窗口首次误用此形式，已改用 3 参数形式 `has_database_privilege('auto_wechat','auto_wechat','CREATE')` 得到正确的 `false`。该偏差为审批窗口方法误差，非报告结论错误。

```text
PR-1B = PASS
APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER = RESOLVED
```

业务对象 owner 未被改成 Application Role，无残留 ownership-level 泄漏。

---

## Current Role Attributes（PR-1 / PR-6）

```text
auto_wechat:
  LOGIN       = true
  SUPERUSER   = false
  CREATEDB    = false
  CREATEROLE  = false
  BYPASSRLS   = false
  INHERIT     = true
  memberships = (none)
```

```text
PR-1 = PASS（应用角色存在性 + 属性）
PR-6 = PASS（无 superuser / DDL / ownership 残留）
```

---

## Existing ACL Verification（PR-3）

`information_schema.role_table_grants` 独立计数：

| 权限 | 计数 | 说明 |
|---|---|---|
| SELECT | **61** | 60 业务表 + alembic_version |
| INSERT | **60** | 60 业务表（alembic_version 已 REVOKE）|
| UPDATE | **60** | 60 业务表 |
| DELETE | **60** | 60 业务表 |
| TRUNCATE | **0** | 未授予，符合 contract |
| REFERENCES | **0** | 符合 contract |
| TRIGGER | **0** | 符合 contract |

**61 SELECT = 60 business tables + `alembic_version`**：`alembic_version` 仅 SELECT（供 `/ready` 读 revision），写权限由 §7 REVOKE 收敛，故 INSERT/UPDATE/DELETE=60。统计与报告一致。

代表性业务表 `douyin_leads` effective：`SEL=t INS=t UPD=t DEL=t TRUNC=f REF=f TRIG=f` ✅

```text
PR-3 = PASS
```

---

## alembic_version Contract（PR-5 / PR-11）

以 `auto_wechat` 应用角色真实连接独立复现：

```text
SELECT version_num FROM alembic_version;        → 0034        PASS
INSERT INTO alembic_version(version_num) ...      → DENIED (permission denied for table alembic_version)
UPDATE alembic_version SET version_num=... WHERE false; → DENIED
DELETE FROM alembic_version WHERE false;          → DENIED
TRUNCATE alembic_version;                         → DENIED
head after attempts                               → 0034（不变）
```

四路写均 `permission denied for table alembic_version`，revision 零修改。SELECT-only 收敛经实际写尝试反证。

```text
PR-5  = PASS（alembic_version 运行时 SELECT PASS / WRITE DENIED）
PR-11 = PASS（alembic_version 写负向三路 DENIED）
```

---

## Sequence Permissions（PR-9）

| 项 | 实测 |
|---|---|
| public sequences 实际数量 | **60** |
| `auto_wechat` effective USAGE（`has_sequence_privilege`）| **60** |
| `auto_wechat` effective SELECT（`has_sequence_privilege`）| **60** |

> 核验方法注记：`information_schema.role_usage_grants` 视图不报 sequence 的 SELECT（仅报 USAGE），首次误得 `seq_select=0`；改用 `has_sequence_privilege('auto_wechat', seq, 'SELECT')` 得到正确 `60`。该偏差为审批窗口方法误差，非报告结论错误。未授予 setval/UPDATE，未用 ALL PRIVILEGES。

代表性 SERIAL sequence `autoreply_admin_audit_logs_id_seq`：USAGE=true / SELECT=true ✅

```text
PR-9 = PASS（USAGE + SELECT，未机械获得无关高权限）
```

---

## Future ADP Verification（PR-4）

`pg_default_acl` + `aclexplode` 独立解码：

| objtype | creator | schema | grantee | privs |
|---|---|---|---|---|
| r（tables）| **postgres** | public | **auto_wechat** | DELETE, INSERT, SELECT, UPDATE（无 TRUNCATE/REFERENCES/TRIGGER）|
| S（sequences）| **postgres** | public | **auto_wechat** | SELECT, USAGE（无 UPDATE/setval）|

2 条 ADP，creator 严格为 `postgres`，`IN SCHEMA public`，grantee=`auto_wechat`，不含 TRUNCATE。未把其他 creator role 的 ACL 误认。

```text
PR-4 = PASS
```

---

## /ready As Application Role（PR-7）

显式以 `principal=auto_wechat` / `backend=PostgreSQL` / `database=auto_wechat` 运行应用 ready probe（一次性容器 `au-appr-ready-probe`，`DATABASE_URL=postgresql+psycopg://auto_wechat:***@auto-wechat-postgres-dev:5432/auto_wechat`，**未用 postgres superuser，未用 SQLite 默认配置**）。探测容器已停止移除。

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

principal 证据（同 DATABASE_URL 引擎 `current_user`）：

```text
current_user=auto_wechat / current_database=auto_wechat
```

> 注：`db_readiness.py` 的 /ready 响应体本身不含 `principal` 字段；principal 证据来自同一引擎连接的 `current_user` 打印，审批窗口已独立复现 `current_user=auto_wechat`。报告 §13 框架与此一致（HTTP body 与 principal 证据分列），非缺陷。

```text
backend  = PostgreSQL
database = auto_wechat
principal= auto_wechat（非 superuser）
revision = 0034
HTTP     = 200

PR-7 = PASS
```

---

## DML / Sequence Verification（PR-8 / PR-9）

以 `auto_wechat` 应用角色在事务内验证代表表 `autoreply_admin_audit_logs`（id bigserial / action NOT NULL / target_type NOT NULL / created_at default now() / 无 FK）：

```text
INSERT (action,target_type) VALUES('perm_appr_probe','perm_test') RETURNING id → id=2, INSERT 0 1   PASS
UPDATE ... SET action='perm_appr_probe_upd' WHERE action='perm_appr_probe'      → UPDATE 1          PASS
SELECT count(*) WHERE action='perm_appr_probe_upd'                              → 1 row             PASS
SELECT currval('autoreply_admin_audit_logs_id_seq')                            → 2                 PASS (sequence SELECT)
DELETE ... WHERE action='perm_appr_probe_upd' RETURNING id                      → DELETE 1          PASS
ROLLBACK                                                                                          → no pollution
residual (action LIKE 'perm_appr_probe%') after rollback                        → 0                 PASS
```

INSERT 触发 `nextval`（sequence USAGE），`currval` 验证 sequence SELECT，事务 ROLLBACK 后 residual=0。未发抖音/微信/外部 API。

```text
PR-8 = PASS（INSERT/UPDATE/SELECT/DELETE 事务内成功 + ROLLBACK，residual=0）
PR-9 = PASS（nextval + currval）
```

---

## DDL / TRUNCATE Negative Verification（PR-10 / PR-12）

**PR-10 DDL 负向**（应用角色）：

```sql
CREATE TABLE perm_neg_probe_au(id bigint);
→ ERROR: permission denied for schema public   DENIED
residual probe table = 0
```

**PR-12 TRUNCATE 负向**（应用角色，安全 fixture）：

```sql
TRUNCATE douyin_leads;
→ ERROR: permission denied for table douyin_leads   DENIED
douyin_leads 行数保留（未被截断）
```

```text
PR-10 = PASS（CREATE TABLE → DENIED，无残留）
PR-12 = PASS（TRUNCATE → DENIED）
```

---

## Future Object Runtime Verification（§11）

不只看 `pg_default_acl`，由 `postgres` 创建专门临时验证对象（verification-only，非业务 schema，不动 Alembic revision），`auto_wechat` 验证 creator-specific ADP 真实生效，事后由 `postgres` 清理：

```text
postgres: CREATE TABLE appr_adp_vt(id bigserial PK, note text, created_at timestamptz DEFAULT now()); CREATE SEQUENCE appr_adp_vs;
app role future table:  INSERT→id=1 PASS / UPDATE 1 PASS / SELECT 1 PASS / DELETE 1 PASS（事务 ROLLBACK，residual=0）
app role future seq:    currval('appr_adp_vt_id_seq')→1 PASS（owned sequence，ADP 生效）
app role future table:  TRUNCATE appr_adp_vt → DENIED（ADP 未授予 TRUNCATE）✅
app role standalone seq: nextval('appr_adp_vs')→1 PASS（ADP sequence 分支）
postgres: DROP TABLE appr_adp_vt; DROP SEQUENCE appr_adp_vs;
residual appr_adp objects = 0；table_count=61（不变）；head=0034（不变）
```

同时核验执行窗口 §20 的 `perm_adp_*` 临时对象确已清理：`perm_adp_residual=0`。

```text
§11 Future Object Runtime = PASS（ADP 真实生效，cleanup verified，residual=0，无 Alembic revision 变化，无业务数据）
```

---

## PR-0 ~ PR-13 逐项裁定

| Gate | 验证内容 | 裁定 | 证据 |
|---|---|---|---|
| PR-0 | 环境 LOCAL DEV ONLY | **PASS** | auto-wechat-postgres-dev@5432，db=auto_wechat，PG 16.14，head=0034，61 表 |
| PR-1 | 应用角色存在性 + 属性 | **PASS** | LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f / memberships=none |
| PR-1B | Database/Schema Ownership Hard Gate | **PASS** | db owner=postgres，dbCREATE=f，schemaCREATE=f，pg_dbo_member=f，61 表 owner=postgres |
| PR-2 | 实施前权限快照 | **PASS** | post-transfer pre-GRANT 状态由执行窗口冻结（pre-GRANT 不可复现，after-state 经 PR-3/PR-13 充分验证）|
| PR-3 | 最小权限落地 | **PASS** | SELECT=61 / INSERT/UPDATE/DELETE=60 / TRUNCATE/REFS/TRIG=0 / sequences=60 |
| PR-4 | 未来对象 ADP | **PASS** | 2 ADP，creator=postgres，grantee=auto_wechat，无 TRUNCATE |
| PR-5 | alembic_version 运行时 | **PASS** | SELECT→0034 PASS；4 路写 DENIED；revision 不变 |
| PR-6 | 无意外 DDL/superuser | **PASS** | superuser/createdb/createrole/bypassrls=f；schema/db CREATE=f；非对象 owner |
| PR-7 | /ready 以应用角色 PASS | **PASS** | HTTP 200，backend=postgresql，db=auto_wechat，head=0034，principal=auto_wechat |
| PR-8 | 代表性读写事务 | **PASS** | INSERT/UPDATE/SELECT/DELETE 事务内成功 + ROLLBACK，residual=0 |
| PR-9 | sequence/identity | **PASS** | nextval→2 / currval→2；60 seq USAGE+SELECT |
| PR-10 | 负向 DDL | **PASS** | CREATE TABLE→permission denied for schema public，无残留 |
| PR-11 | alembic_version 写负向 | **PASS** | UPDATE/INSERT/DELETE/TRUNCATE→DENIED ×4 |
| PR-12 | TRUNCATE 负向 | **PASS** | TRUNCATE douyin_leads→DENIED |
| PR-13 | 实施后快照对比 | **PASS** | after snapshot 符合目标 contract（见下）|
| §11 | Future Object Runtime | **PASS** | postgres 建临时对象→app DML PASS / TRUNCATE DENIED / seq PASS→清理 / residual=0 |

### PR-13 After Snapshot（与 before 同一 inspection contract）

```text
auto_wechat role   : LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f
memberships        : (none)
database           : owner=postgres / CONNECT=t / CREATE=f / TEMP=t
public schema      : USAGE=t / CREATE=f
tables grants      : SELECT=61 / INSERT=60 / UPDATE=60 / DELETE=60 / TRUNCATE=0 / REFERENCES=0 / TRIGGER=0
douyin_leads       : SEL=t INS=t UPD=t DEL=t TRUNC=f
alembic_version    : SEL=t INS=f UPD=f DEL=f TRUNC=f
sequence grants    : 60（USAGE+SELECT）
default ACL        : creator=postgres / schema=public / grantee=auto_wechat
                      tables  → DELETE,INSERT,SELECT,UPDATE
                      sequences→ SELECT,USAGE
```

Existing + Future Contract **同时成立**——既有对象一次性 GRANT + 未来对象 `FOR ROLE postgres` ADP 两层均独立核验通过（非仅验证其一）。

---

## Permission Gap Final Verdict

```text
APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER = RESOLVED
APPLICATION_ROLE_PERMISSION_GAP            = RESOLVED
```

PR-1B～PR-13 全部独立成立，alembic_version 硬契约 SELECT-only 成立，`/ready` 以非 superuser 应用角色 PASS。本轮 DB 写操作均发生在 LOCAL DEV canonical PG（DB-BL 未重开：table_count=61 / head=0034 不变）。

---

## Bootstrap Ownership Recurrence Gap（§18/§19/§21）

审批窗口独立确认 `docker/postgres/init/001_create_databases.sql` 当前逻辑仍为：

```sql
CREATE DATABASE auto_wechat OWNER auto_wechat
```

与已审批冻结的 Runtime Principal Contract（Migration/ownership=postgres，Application=auto_wechat）相悖。

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = OPEN
```

**分层裁定**：

- 当前实际运行 canonical dev DB ownership 已修正为 `postgres`，runtime app-role contract 已独立验证通过（PR-1B~PR-13 PASS），故 **当前运行库权限实现不失败**——`APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER` / `APPLICATION_ROLE_PERMISSION_GAP` 均 RESOLVED 成立。
- 该 init SQL 的 stale contract **不倒推当前运行库权限实现失败**；它作为 **PREVENTION / REPRODUCIBILITY GAP** 保持 OPEN。
- 不得写"all PostgreSQL bootstrap ownership paths are now compliant"。
- 关闭节点：`before next clean local PG rebuild/bootstrap`，建议最迟 `before P1 final technical closure`。
- 本审批窗口**不授权**修改 `001_create_databases.sql`（须另有独立批准）。

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP:
DOES NOT BLOCK CURRENT CONSUMER PG VERIFICATION  （但 remain OPEN）
```

---

## 0032 / 0033 / 0034 Unlock（§20）

当前权限实现全部通过，consumer PG verification 恢复正式状态：

```text
0032 Daily Report PG verification : UNBLOCKED_FOR_PG_VERIFICATION
0033 M05 PG verification          : UNBLOCKED_FOR_PG_VERIFICATION
0034 Preview PG verification     : UNBLOCKED_FOR_PG_VERIFICATION

APPLICATION_ROLE_PREREQUISITE = VERIFIED
```

> 未写 `PG_VERIFIED`。下一阶段 consumer verification 必须以 `auto_wechat` Application Principal 为主要 runtime 验证身份。Bootstrap drift gap 不阻断当前 consumer PG verification（理由见上节）。

---

## P1 Status（§23）

```text
P1 COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE           = PENDING
```

本轮 Permission Implementation 正式通过，但 P1 仍 OPEN，Technical Closure 仍 PENDING，后续仍包括：

- 0032 Daily Report PG verification
- 0033 M05 PG verification
- 0034 Preview PG verification
- RAG Query 0005 PG verification（Docker 恢复后独立补）
- Global Active None Audit（重新全局搜索）
- Final PostgreSQL Concurrent Closure Gate
- LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP（建议 final closure 前关闭）

---

## RB-10（§24）

```text
RB-10 CLEANUP = NOT AUTHORIZED
```

legacy backup 与 dump 保持，本轮不触碰。

---

## Git / Documentation Authorization（§25）

### Git Candidate Scope 独立核验

```text
git status --short：
 M docs/architecture/remediation/P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md
git diff --name-only：
 docs/architecture/remediation/P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md
未跟踪文件：无（无 dump / snapshot / 凭据误提交）
```

独立确认：

- migration 没有变化；
- consumer 代码没有变化；
- M07 Core 没有变化；
- DB-BL 没有重开（table_count=61 / head=0034）；
- docker init SQL（`001_create_databases.sql`）没有被本实施窗口修改；
- 没有凭据；
- 没有 dump/snapshot 误提交。

实际 scope 与执行窗口声明一致。

### Commit Authorization

Implementation 被批准（APPROVED）。授权执行窗口做**一次文档状态同步 + commit**：

允许同步：

- `P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md`（candidate diff，已在工作区）
- 本审批报告 `P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md`
- 当前面向治理状态：`CLAUDE.md` / `05_PROJECT_CONTEXT.md` 等受影响文档

必须使用精确表述：

```text
LOCAL DEV application-role permission = VERIFIED
STAGING / PRODUCTION                  = RUNTIME_UNKNOWN
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = OPEN
```

不得：

- 修改 `001_create_databases.sql`（须另有独立批准）；
- 写 staging/prod permissions fixed；
- 写 all PostgreSQL bootstrap ownership paths compliant；
- 0032/0033/0034 写 `PG_VERIFIED`；
- 越权开始 0032/0033/0034 consumer PG verification。

---

## 附：审批窗口独立核验方法索引

| 核验项 | 方法 | 结论 |
|---|---|---|
| Git scope | `git status/diff --name-only` + 未跟踪检查 | 仅报告文件，无凭据/dump |
| 环境身份 | `current_database()`/`version()`/`pg_tables` | auto_wechat / PG 16.14 / 0034 / 61 表 |
| Ownership | `pg_database.datdba` + `pg_auth_members`(pg_database_owner) | postgres / member=false |
| effective CREATE | `has_database_privilege(user,db,priv)` 3 参数 + `has_schema_privilege` | dbCREATE=f / schemaCREATE=f |
| 表 owner 分布 | `pg_class.relowner` 聚合 | 61 全 postgres |
| ACL 计数 | `information_schema.role_table_grants` | 61/60/60/60/0/0/0 |
| alembic_version | 应用角色写尝试 ×4 | DENIED ×4 / revision 不变 |
| sequences | `has_sequence_privilege`（非 role_usage_grants）| 60 USAGE + 60 SELECT |
| ADP | `pg_default_acl` + `aclexplode` | creator=postgres / 无 TRUNCATE |
| /ready HTTP | 真实 curl（应用角色 DATABASE_URL 容器）| HTTP 200 / postgresql / 0034 |
| principal | 同引擎 `current_user` | auto_wechat |
| 代表性 DML | 事务内 INSERT/UPDATE/SELECT/DELETE + ROLLBACK | PASS / residual=0 |
| sequence | nextval(INSERT) + currval | PASS |
| DDL 负向 | 应用角色 CREATE TABLE | DENIED / 无残留 |
| alembic 写负向 | 应用角色 UPDATE/INSERT/DELETE/TRUNCATE | DENIED ×4 |
| TRUNCATE 负向 | 应用角色 TRUNCATE douyin_leads | DENIED |
| Future object ADP | postgres 建临时对象→app 验证→drop | DML PASS / TRUNCATE DENIED / seq PASS / residual=0 |
| DB-BL 未重开 | table_count + head | 61 / 0034 不变 |

所有核验：只读 catalog inspection + 应用角色实测 + 真实 HTTP /ready + 事务内回滚 DML + 临时验证对象（已清理）。零业务污染，零迁移修改，零 DB-BL 重开，零 bootstrap 越权修改。

---

**审批结论：APPROVED。PR-1B～PR-13 + §11 全部独立通过。Permission Gap = RESOLVED。**

审批窗口完成，停止。不自行开始 0032/0033/0034 consumer PG verification。
