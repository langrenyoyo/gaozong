# P1 — PostgreSQL Application Role Permission 实施报告

> 任务：`P1-PG-APP-ROLE-2 — LOCAL PostgreSQL Application Permission 实施`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的 PostgreSQL runtime prerequisite
> 实施授权：`AUTHORIZED — LOCAL DEVELOPMENT ONLY`（来自 [P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md) §16）
> 日期：2026-08-10
> 窗口：P1-PG-APP-ROLE-2 LOCAL PostgreSQL Application Permission 执行窗口
> Source of Truth：真实 PG runtime 证据（独立只读 catalog inspection + 应用角色实测） > 冻结文档 > 推测

---

## 结论速览

| 维度 | 结论 |
|---|---|
| C1-C4 Correction Doc-Sync | ✅ CORRECTIONS_APPLIED / FROZEN |
| PR-0 环境 Gate | ✅ PASS（LOCAL DEV ONLY）|
| PR-1 应用 Principal | ✅ PASS（无意外高危 attribute / membership）|
| PR-1B Database/Schema Ownership Hard Gate | ⛔ **BLOCKER — APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER: DETECTED** |
| PR-2 ~ PR-13 | ⛔ BLOCKED（在 PR-1B STOP，未执行任何 GRANT/REVOKE/ADP）|
| 运行时状态 | 未改变（独立核验：0 table grants / 0 seq grants / 0 default_acl / relacl null）|
| Permission Gap Verdict | ⛔ **STILL_OPEN** |
| 0032/0033/0034 Consumer Unlock | ⛔ NOT unlocked（仍 forbidden）|
| P1 | OPEN / TECHNICAL_CLOSURE=PENDING |

**本窗口在 PR-1B 命中硬 blocker 后立即 STOP，未越界执行任何 GRANT/REVOKE/ALTER DEFAULT PRIVILEGES/ALTER DATABASE OWNER/改 owner/改迁移。**

---

## 1. Corrections Applied（C1-C4）

按任务 §1，先完成 4 项审批 Correction Doc-Sync，修改对象 [P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md](P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md)（只同步审批冻结内容）：

| Correction | 内容 | 落地位置 |
|---|---|---|
| **C1 — Model 命名** | 废止易与 DB-BL `Schema Authority Model A` 混淆的 `Model A′`；正式冻结为 `Runtime Principal Model: SEPARATED MIGRATION / APPLICATION RESPONSIBILITY` | 设计 §2.2 标题/比较表/结论/理由、§14；保留 `Model A`/`Model B` 比较轴标签 |
| **C2 — PR-12 TRUNCATE 负向** | 新增 PR-12 `TRUNCATE` negative test：application role 对业务表 `TRUNCATE` → DENIED | 设计 §11 实施计划、§12 PR-* Gates 表 |
| **C3 — alembic_version 硬收敛** | existing-table 宽泛 DML 授权后 `alembic_version` MUST be explicitly reduced to SELECT-only；若未来 DROP/recreate，SELECT-only hardening MUST be reapplied，不得依赖当前对象永久存在 | 设计 §3.5、§6.4（从"接受残余"升级为 runbook 硬约束）|
| **C4 — Environment Evidence** | 冻结证据词汇：Dev=`LOCAL_PG_RUNTIME_VERIFIED`；Staging/Production=`CONFIG_VERIFIED` / `RUNTIME_UNKNOWN`；不得宣称 staging/prod 当前一定以 superuser 运行 | 设计 §1.4 现状总表 + 纪律冻结说明 |
| PR-11（审批 §14 提升为独立 gate，同步落地）| `alembic_version` 写负向 → DENIED（C3 硬收敛验证 gate） | 设计 §11、§12 |

```text
P1-PG-APP-ROLE-1:
CORRECTIONS_APPLIED / FROZEN
```

未发现新事实冲突。设计文档已无 `READ_ONLY_PG_VERIFIED` / `STATIC_CONFIG_KNOWN` / 旧"残余可控，不为低概率路径增复杂度"等被废止措辞残留（仅 C1 说明中显式引用被废止名 `Model A′` 用于追溯）。

---

## 2. Environment Identity（PR-0）

独立核验（本窗口直接对本地 canonical dev PG 执行只读 inspection）：

```text
TARGET = LOCAL DEVELOPMENT ONLY

container / service = auto-wechat-postgres-dev (Up 6 hours, healthy)
host                = 0.0.0.0:5432 (映射自容器)
port                = 5432
database            = auto_wechat
current_database()  = auto_wechat
current_user (inspection) = postgres (migration principal / superuser，仅用于只读 catalog inspection)
server_version      = PostgreSQL 16.14 (x86_64-pc-linux-musl, Alpine 15.2.0)
alembic head        = 0034
physical tables (public) = 61

NOT PRODUCTION
NOT STAGING
```

**PR-0 = PASS。** 无环境歧义。此即 DB-BL-2D 冻结的 canonical local PG（`AUTO_WECHAT_DEV_PG = CANONICAL_ALEMBIC_BASELINE@0034`，checkpoint `cc9b11e`）。

---

## 3. Principal / Ownership Preflight（PR-1 / PR-1B）

### 3.1 PR-1 — Application Principal

```text
application principal = auto_wechat
LOGIN (rolcanlogin)  = true
SUPERUSER (rolsuper) = false
CREATEDB (rolcreatedb)   = false
CREATEROLE (rolcreaterole) = false
BYPASSRLS (rolbypassrls) = false
rolreplication       = false
rolinherit           = true
role memberships     = (none)
```

→ 无高危 role attribute，无意外 membership。**PR-1 = PASS。** 不存在 `UNEXPECTED_ROLE_CAPABILITY`。

### 3.2 PR-1B — Database / Schema Ownership Hard Gate（独立核验）

```text
database owner                                 = auto_wechat        ← ★ BLOCKER
database datacl                                 = (null)
public schema owner                             = pg_database_owner
public schema nspacl                            = {pg_database_owner=UC/pg_database_owner, =U/pg_database_owner}
table owners (public, 61 表)                    = postgres (61)      ← 对象 owner 留在 migration principal ✓
has_database_privilege(auto_wechat,auto_wechat,CREATE)  = true   ← ★ DDL 泄漏（ownership）
has_database_privilege(auto_wechat,auto_wechat,CONNECT)  = true
has_schema_privilege(auto_wechat,public,CREATE)           = true   ← ★ DDL 泄漏（pg_database_owner 成员）
has_schema_privilege(auto_wechat,public,USAGE)            = true
pg_has_role(auto_wechat, pg_database_owner, member)      = true   ← ownership → 隐式成员
```

#### Blocker 判定

```text
APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER:
DETECTED
```

**`auto_wechat` 仍是 `auto_wechat` database 的 owner。** database ownership 使其隐式成为 `pg_database_owner` 成员 → 自动获得 public schema 的 `UC`（含 CREATE）→ 隐式 DDL 泄漏点。

按执行窗口 §4 PR-1B 硬约束：

- **立即 STOP。** 不得通过 `REVOKE CREATE ON SCHEMA public` 等临时手段假装完成 principal separation——database/object ownership 本身拥有特殊控制语义，普通 GRANT/REVOKE 不能等价替代"非 owner runtime principal"的 Contract。
- **当前 P1-PG-APP-ROLE-2 授权范围没有包含 `ALTER DATABASE OWNER`，不得擅自执行。**
- 提交独立设计/审批窗口决定：是否授权将 database ownership 迁移给 migration principal（`ALTER DATABASE auto_wechat OWNER TO postgres;`）。

**PR-1B = BLOCKED（blocker DETECTED，STOP）。**

---

## 4. Migration Principal（PR-1B 之后，未进入）

按执行窗口 §6 Migration Principal Gate，需在执行 ADP 前验证 migration principal = `postgres`。本窗口已在 PR-1B 只读 inspection 中独立确认：

```text
canonical objects owner = postgres (61 表 owner=postgres，独立核验) ✓
local Alembic verification 实际使用 postgres（env.py 读 DATABASE_URL，DB-BL 以来 alembic upgrade head 由 postgres superuser 执行）✓
LOCAL MIGRATION PRINCIPAL = postgres（候选成立）
```

但因 PR-1B blocker，**未执行** `ALTER DEFAULT PRIVILEGES FOR ROLE postgres ...`。ADP 仅在 PR-1B 解除后、随 §7 grants 一起落地。

---

## 5. Before Privilege Snapshot（PR-2，BLOCKED 前的当前状态独立核验）

PR-2 目的是"在任何 GRANT 前冻结当前权限快照"。本窗口在 STOP 前独立只读核验当前状态（用于证明"未应用任何 GRANT、状态未变"）：

```text
role auto_wechat
  LOGIN=true / SUPERUSER=false / CREATEDB=false / CREATEROLE=false / BYPASSRLS=false
  memberships = (none)

database auto_wechat
  CONNECT = true (经 PUBLIC 默认 + ownership)
  CREATE  = true (★ ownership 泄漏，非显式 GRANT)
  TEMP    = true (PUBLIC 默认)

public schema
  USAGE  = true
  CREATE = true (★ pg_database_owner 隐式，非显式 GRANT)
  owner  = pg_database_owner
  ACL    = {pg_database_owner=UC/pg_database_owner, =U/pg_database_owner}

tables (grants TO auto_wechat)
  SELECT / INSERT / UPDATE / DELETE / TRUNCATE / REFERENCES / TRIGGER = 0 显式 grants
  information_schema.role_table_grants WHERE grantee='auto_wechat' = 0

sequences (grants TO auto_wechat)
  USAGE / SELECT = 0 显式 grants

alembic_version effective privileges
  SELECT  = DENIED (应用角色实测：permission denied for table alembic_version)
  INSERT/UPDATE/DELETE = DENIED

default ACL
  pg_default_acl rows (grantee=auto_wechat, schema=public) = 0

douyin_leads.relacl = (null)

role auto_wechat has_password = true (仅记录布尔，未取 password hash)
```

→ 与设计报告 §1.1 / 审批报告 §2.2 逐项一致，**零偏差**。当前应用角色能 CONNECT，但对任何业务表与 alembic_version 均无 SELECT/INSERT 权限（gap 仍在）。

PR-2 gate 严格语义（"GRANT 前快照"）= **N/A**（因 PR-1B blocker，本窗口不会执行任何 GRANT，无 before/after diff 需求）。上述快照作为"未改动状态证据"留存。

---

## 6. Existing Object Grants（PR-3，BLOCKED）

```text
PR-3 = BLOCKED（未执行，PR-1B STOP）
```

未执行 §8 bootstrap：

```sql
-- 未执行（blocked）
GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;
GRANT USAGE ON SCHEMA public TO auto_wechat;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;
```

原因：PR-1B 硬 blocker 未解除前不得执行任何 GRANT（执行窗口 §7"只有前述 Gate 全部通过才执行"）。

---

## 7. alembic_version Hardening（BLOCKED）

```text
alembic_version 收敛 = BLOCKED（未执行，PR-1B STOP）
```

GRANT→REVOKE 顺序硬约束（C3）尚未进入执行阶段。当前 alembic_version 状态：application role SELECT = DENIED、WRITE = DENIED（因无任何 GRANT；非"已收敛到 SELECT-only"，而是"全无权限"）。

---

## 8. Future Default Privileges（PR-4，BLOCKED）

```text
PR-4 = BLOCKED（未执行，PR-1B STOP）
```

未执行 `ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public ...`。`pg_default_acl`（grantee=auto_wechat）= 0（未变）。

---

## 9. /ready as Application Role（PR-7/PR-6，BLOCKED）

```text
PR-6/PR-7 = BLOCKED（未执行，PR-1B STOP）
```

未以 application role `auto_wechat` 重跑 `/ready`。当前应用角色 SELECT alembic_version = DENIED，若以应用角色跑 `/ready` 必在 `alembic_revision` 检查步落入 `ERROR_DB_CONNECT` → 503（设计 §8.2、审批 §12 已论证）。当前 `/ready` PASS 仅因以 `postgres` superuser 运行，**不代表 application-role 路径通过**。

---

## 10. Representative DML（PR-8，BLOCKED）

```text
PR-8 = BLOCKED（未执行，PR-1B STOP）
```

未执行代表性行读写事务。应用角色当前对业务表无 INSERT/UPDATE/DELETE 权限（gap 仍在）。

---

## 11. Sequence Test（PR-9，BLOCKED）

```text
PR-9 = BLOCKED（未执行，PR-1B STOP）
```

未验证 sequence `nextval`。应用角色当前无 sequence USAGE/SELECT 权限。

---

## 12. Negative DDL Test（PR-10，BLOCKED）

```text
PR-10 = BLOCKED（未执行，PR-1B STOP）
```

注：当前应用角色 CREATE on public = true（经 ownership 隐式），**这正是 PR-1B blocker 要消除的 DDL 泄漏**。若现在跑 `CREATE TABLE` 负向测试，预期会**成功而非 DENIED**——这是 ownership 泄漏的直接表现，进一步印证 PR-1B blocker 真实存在。本窗口不在此状态下执行 DDL 负向测试（无意义，且违反"碰巧成功即 STOP"原则——blocker 已在更早的 PR-1B 命中并 STOP）。

---

## 13. alembic_version Negative Write（PR-11，BLOCKED）

```text
PR-11 = BLOCKED（未执行，PR-1B STOP）
```

当前应用角色对 alembic_version 无任何权限（SELECT/UPDATE 均 DENIED），非"已收敛到 SELECT-only"。负向写测试在 grants 落地后才有意义。

---

## 14. TRUNCATE Negative Test（PR-12，BLOCKED）

```text
PR-12 = BLOCKED（未执行，PR-1B STOP）
```

未执行。当前应用角色无 TRUNCATE 权限（因无 GRANT），但同 PR-12 须在 grants 落地后验证"有 DML 但无 TRUNCATE"。

---

## 15. Future Object Runtime Test（BLOCKED）

```text
Future Object Contract Runtime Test = BLOCKED（未执行，PR-1B STOP）
```

未由 migration principal 创建临时验证对象、未验证 creator-specific ADP 生效。

---

## 16. After Privilege Snapshot（PR-13，BLOCKED）

```text
PR-13 = BLOCKED（未执行，PR-1B STOP）
```

无 GRANT → 无 before/after diff。运行时状态未变（见 §5 独立核验：0 table grants / 0 seq grants / 0 default_acl / relacl null）。

---

## 17. PR-0 ~ PR-13 逐项

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| PR-0 | 环境 LOCAL DEV ONLY | ✅ PASS | container `auto-wechat-postgres-dev` @5432，db=auto_wechat，PG 16.14，head=0034 |
| PR-1 | 应用角色存在性 | ✅ PASS | auto_wechat: LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f / memberships=(none) |
| PR-1B | Database/Schema Ownership Hard Gate | ⛔ BLOCKED | database owner=auto_wechat → **APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER: DETECTED** |
| PR-2 | 实施前权限快照 | N/A（blocker 前已独立核验当前状态未变）| 0 table grants / 0 seq grants / 0 default_acl / relacl null |
| PR-3 | 最小权限落地 | ⛔ BLOCKED | 未执行 GRANT（PR-1B STOP）|
| PR-4 | 未来对象 ADP | ⛔ BLOCKED | 未执行 ALTER DEFAULT PRIVILEGES |
| PR-5 | alembic_version SELECT-only | ⛔ BLOCKED | 未执行 GRANT→REVOKE 收敛 |
| PR-6 | 无意外 DDL/superuser | ⛔ BLOCKED | CREATE on public 仍 true（ownership 泄漏，PR-1B blocker 未消除）|
| PR-7 | /ready 以应用角色 PASS | ⛔ BLOCKED | 未以应用角色跑 /ready |
| PR-8 | 代表性读写事务 | ⛔ BLOCKED | 未执行 |
| PR-9 | sequence/identity | ⛔ BLOCKED | 未执行 |
| PR-10 | 负向 DDL | ⛔ BLOCKED | 未执行（当前 CREATE 仍成功，blocker 未消除）|
| PR-11 | alembic_version 写负向 | ⛔ BLOCKED | 未执行 |
| PR-12 | TRUNCATE 负向 | ⛔ BLOCKED | 未执行 |
| PR-13 | 实施后快照对比 | ⛔ BLOCKED | 未执行 GRANT，无 after 快照 |

---

## 18. Permission Gap Verdict

```text
APPLICATION_ROLE_PERMISSION_GAP:
STILL_OPEN
```

blocker 未解除，application role 仍无业务表 DML 权限，`/ready` 仍只能以 superuser 通过。本轮**未**宣称 `RESOLVED_PENDING_APPROVAL`。

### 18.1 Blocker 根因与冲突说明

- **根因：** dev init SQL `docker/postgres/init/001_create_databases.sql:20-21` 以 `CREATE DATABASE auto_wechat OWNER auto_wechat` 创建库，使应用角色 `auto_wechat` 成为 database owner → 隐式 `pg_database_owner` 成员 → public schema CREATE 泄漏。
- **审批与执行窗口的张力：** 审批报告 §10 曾表示"路径1（保留 DB owner + REVOKE CREATE）或路径2（ALTER DATABASE OWNER）任一均可，implementation 选其一"。但**执行窗口 §4 PR-1B 明确更严**：若 `auto_wechat` 仍是 database owner → 立即 STOP，不得用 `REVOKE CREATE` 等临时手段假装完成 principal separation（"database/object ownership 本身拥有特殊控制语义；普通 GRANT/REVOKE 不能等价替代'非 owner runtime principal'的 Contract"），且**本窗口授权范围不含 `ALTER DATABASE OWNER`**。执行窗口为权威执行指令，以其为准。

### 18.2 解除 blocker 的候选路径（需独立设计/审批，本窗口不执行）

需新开独立设计/审批窗口授权以下之一（**不属于当前 P1-PG-APP-ROLE-2 授权范围**）：

- **候选 A（推荐，对齐设计 §7.1 路径2）：** `ALTER DATABASE auto_wechat OWNER TO postgres;`——将 database ownership 迁移给 migration principal `postgres`，application role 不再是 `pg_database_owner` 成员 → 自动失去 public schema CREATE 泄漏；随后正常走 PR-2~PR-13。
  - 影响面：仅改 `auto_wechat` 库 owner（不改表 owner，表 owner 已是 postgres）；不改角色、不改密码、不改迁移、不动 DB-BL（DB-BL 冻结的是 schema baseline，非 database owner）。
  - 风险：低；owner 迁移后 `auto_wechat` 失去对自身库的 owner 控制（这正是 principal separation 的目标）。
- **候选 B：** 重新审视执行窗口 PR-1B 是否接受"路径1（保留 owner + 显式 REVOKE CREATE）"作为 principal separation 的等价契约——若审批窗口经评估认为 ownership 的"特殊控制语义"在当前 dev 单库场景下风险可接受，可放宽 PR-1B。但本窗口无权自行放宽。

建议新审批窗口在候选 A / B 间裁定；裁定后由 P1-PG-APP-ROLE-2 续作（或新开 R2 窗口）从 PR-1B 续跑。

---

## 19. Consumer Unlock

```text
0032 Daily Report PG verification   = STILL FORBIDDEN
0033 M05 PG verification             = STILL FORBIDDEN
0034 Preview PG verification        = STILL FORBIDDEN
```

不得写 `READY_FOR_APPLICATION_ROLE_PG_VERIFICATION`，更不得写 `PG_VERIFIED`。Permission gap 仍 OPEN，consumer 须先 resolve & verify application role permission（执行窗口 §24）。

---

## 20. P1 Status

```text
P1 COMPUTE-IDEMPOTENCY-001
  = OPEN
  TECHNICAL_CLOSURE = PENDING
```

本窗口成果：
- C1-C4 Correction 已落地、design 文档与审批冻结内容对齐；
- 独立复现并冻结 PR-0/PR-1 事实、PR-1B blocker 证据；
- 运行时状态未变（未执行任何写操作）。

P1 Technical Closure 仍阻塞在：
- A. `APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER`（本报告 §3.2 / §18）——新增 blocker，需独立审批授权 `ALTER DATABASE OWNER` 或放宽 PR-1B。
- B. RAG Query 0005 PG（Docker 恢复后独立补，与 DB-BL 一致）。
- C. Global Active None Audit。
- D. Final PG Concurrent Closure Gate。

---

## 21. 执行窗口停止点

本窗口在 PR-1B 命中 `APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER` 后**立即 STOP**，按执行窗口 §22 Failure Rules 与 §4 PR-1B 硬约束处置：

- ✅ 未临时增加 ALL PRIVILEGES；
- ✅ 未改成 superuser；
- ✅ 未转 owner（未执行 ALTER DATABASE OWNER / ALTER SCHEMA OWNER）；
- ✅ 未修改迁移；
- ✅ 未用 postgres 替代 app role 续跑 consumer；
- ✅ 未执行任何 GRANT / REVOKE / ALTER DEFAULT PRIVILEGES / ALTER ROLE；
- ✅ 未开始 0032/0033/0034 consumer PG verification；
- ✅ 未触碰 staging / production；
- ✅ 未改 DB-BL、未改 M07 Core、未改 RB-10。

提交独立审批窗口复核：是否授权 database ownership 迁移（`ALTER DATABASE auto_wechat OWNER TO postgres;`）或放宽 PR-1B。裁定后续作。

---

## 附：本窗口独立核验证据索引

| 核验项 | 方法 | 结论 |
|---|---|---|
| 容器健康 | `docker ps` | auto-wechat-postgres-dev Up 6 hours (healthy) @5432 |
| 环境身份 | `psql -c current_database/current_user/version` | auto_wechat / postgres / PG 16.14 |
| role 属性 | `pg_roles` 只读 | auto_wechat: LOGIN/SUPERUSER=f/CREATEDB=f/CREATEROLE=f/BYPASSRLS=f/membership=none |
| DB owner | `pg_database.datdba` | **auto_wechat**（blocker）|
| public schema owner/ACL | `pg_namespace` | pg_database_owner / {pg_database_owner=UC, =U} |
| 表 owner 分布 | `pg_class` GROUP BY | postgres=61 |
| effective CREATE | `has_database_privilege`/`has_schema_privilege` | db CREATE=true / public CREATE=true（ownership 泄漏）|
| pg_database_owner 成员 | `pg_has_role` | true |
| alembic head / 表数 | `alembic_version` / `pg_class` count | 0034 / 61 |
| table grants=0 | `information_schema.role_table_grants` | 0 |
| seq grants=0 | `information_schema.role_usage_grants` | 0 |
| default_acl=0 | `pg_default_acl` | 0 |
| douyin_leads.relacl | `pg_class.relacl` | (null) |
| password 未泄漏 | `rolpassword IS NOT NULL`（仅布尔）| true（未取 hash）|

所有核验均为只读 catalog inspection + 应用角色实测，零写操作。
