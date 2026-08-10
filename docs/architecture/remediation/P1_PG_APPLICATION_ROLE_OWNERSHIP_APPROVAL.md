# P1 — PostgreSQL Application Role Ownership Blocker 独立审批报告

> 审批窗口：`P1-PG-APP-ROLE-1R PostgreSQL Database Ownership Blocker 独立审批`
> 审查对象：`P1-PG-APP-ROLE-2 — LOCAL Permission Implementation` 在 PR-1B 命中的 `APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER`
> 上游设计：[P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md](P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md)（APPROVED_WITH_CORRECTIONS / FROZEN）
> 上游审批：[P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md)（§10 给出两条路径任一均可，但执行窗口 PR-1B 更严并 STOP）
> 上游实施：[P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md)（PR-1B blocker DETECTED，正确 STOP，零写操作）
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的 PostgreSQL runtime prerequisite
> 日期：2026-08-10
> Source of Truth：真实 PG runtime 证据（本窗口独立只读 catalog inspection） > 冻结文档 > 推测

---

## 审批结论速览

| 维度 | 结论 |
|---|---|
| Approval Question A — Application Principal 保持 database owner 是否仍满足分离 contract | **NO** |
| Candidate A — Transfer ownership to postgres | **APPROVED** |
| Candidate B — Keep application role as DB owner | **REJECTED** |
| Preferred Path | **Candidate A（唯一推荐）** |
| Local Migration Principal | **postgres（冻结）** |
| Ownership Correction 授权 | **AUTHORIZED — LOCAL DEVELOPMENT ONLY** |
| P1-PG-APP-ROLE-2 续作 | **AUTHORIZED → RESUME FROM PR-1B**（通过 Hard Verification 后）|
| Production / Staging | **NO WRITE / RUNTIME_UNKNOWN** |
| Git Commit | **HOLD → 审批完成后作为治理 checkpoint 一次提交** |

唯一推荐路径：**Candidate A**——执行 `ALTER DATABASE auto_wechat OWNER TO postgres;`，将 database ownership 迁移给已冻结的 local migration principal `postgres`，使 Application Principal `auto_wechat` 不再持有 ownership-level control，然后从 PR-1B 续跑，不得重开 DB-BL。

---

## 1. Technical Decision

### 1.1 裁定

```text
Approval Question A — Application Principal 能否在保持 database owner 的同时满足
已冻结的 SEPARATED MIGRATION / APPLICATION RESPONSIBILITY contract？

Answer: NO
```

Application Principal `auto_wechat` 不得继续作为 `auto_wechat` database 的 owner。database ownership 是 ownership-level administrative control，其能力来源不是 `pg_database.datacl` 的 ACL 条目，而是 ownership 本身——不可被 `REVOKE` 移除，且可被 owner 单方面恢复。这与已冻结 contract「application principal 不 owner 对象、不持 DDL、不持 ownership-level control」直接冲突。因此 Candidate B（保持 owner + REVOKE CREATE）不能成立。

### 1.2 与上游两份文档的差异裁定

- DESIGN §7.1 提出"路径1（保留 DB owner + REVOKE CREATE）或路径2（ALTER DATABASE OWNER）任一均可"，**本窗口否决路径1**。
- APPROVAL §10 表示"两路径任一均可，implementation 选其一，只要消除 CREATE 泄漏"，**本窗口收紧为只允许路径2**。

收紧依据是 PostgreSQL 的 ownership 语义事实（§3）+ 本窗口独立 catalog 核验（§2）。上游"任一均可"的判断在「是否消除当前 CREATE 泄漏」这一**现象层**成立，但未充分覆盖「ownership 本身的不可 REVOKE 的持久行政能力」这一**语义层**。执行窗口 PR-1B 的更严判定（"database/object ownership 本身拥有特殊控制语义；普通 GRANT/REVOKE 不能等价替代非 owner runtime principal 的 Contract"）方向正确，**本窗口确认 PR-1B 判定成立**。

---

## 2. Blocker Independent Verification

本窗口以 `postgres` superuser 对本地 canonical dev PG（`auto-wechat-postgres-dev` @ 5432，`auto_wechat` 库）执行**纯只读 catalog inspection**，零写操作。结论与 IMPLEMENTATION_REPORT §3.2 / §5 逐项一致，零偏差。

### 2.1 环境身份（PR-0 复核）

```text
container / service = auto-wechat-postgres-dev (Up 6 hours, healthy)
host                = 0.0.0.0:5432
database            = auto_wechat
current_database()  = auto_wechat
current_user        = postgres（仅用于只读 inspection）
server_version      = PostgreSQL 16.14 (x86_64-pc-linux-musl, Alpine)
alembic head        = 0034
physical tables (public) = 61

NOT PRODUCTION / NOT STAGING
```

即 DB-BL-2D 冻结的 canonical local PG（`AUTO_WECHAT_DEV_PG = CANONICAL_ALEMBIC_BASELINE@0034`，checkpoint `cc9b11e`）。

### 2.2 Blocker 事实（独立核验）

```text
database auto_wechat owner           = auto_wechat          ← ★ BLOCKER（datdba → auto_wechat）
database datacl                       = NULL（无显式 ACL；owner 权限不依赖 ACL）
auto_wechat role attributes           = LOGIN=t / SUPERUSER=f / CREATEDB=f / CREATEROLE=f / BYPASSRLS=f / INHERIT=t
auto_wechat explicit memberships      = (none)（pg_auth_members 查询 = 0 行）
auto_wechat = pg_database_owner member = TRUE（隐式成员，非 pg_auth_members 授予，不可 REVOKE）

public schema owner                   = pg_database_owner
public schema nspacl                  = {pg_database_owner=UC/pg_database_owner, =U/pg_database_owner}

auto_wechat effective DATABASE CREATE = TRUE  ← ★ ownership 派生（非显式 GRANT）
auto_wechat effective DATABASE CONNECT= TRUE
auto_wechat effective public USAGE    = TRUE  （经 PUBLIC =U）
auto_wechat effective public CREATE  = TRUE  ← ★ ownership 派生（pg_database_owner → schema ownership）

table owners (public, 61 表)           = postgres (61)  ← 对象 owner 留在 migration principal ✓
table grants TO auto_wechat           = 0
usage/sequence grants TO auto_wechat  = 0
pg_default_acl (public)               = 0
douyin_leads.relacl                   = NULL
```

```text
APPLICATION_ROLE_DATABASE_OWNERSHIP_BLOCKER:
DETECTED  （本窗口独立复现确认）
```

### 2.3 根因

[docker/postgres/init/001_create_databases.sql:20-21](docker/postgres/init/001_create_databases.sql#L20-L21)：

```sql
SELECT 'CREATE DATABASE auto_wechat OWNER auto_wechat'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

init SQL 以 `OWNER auto_wechat` 建库，使 Application Principal 同时成为 database owner → 隐式 `pg_database_owner` 成员 → public schema CREATE 泄漏。Alembic 随后以 `postgres` superuser 执行 → 61 表 owner=postgres，但 database owner 未随迁移改变，仍停留 `auto_wechat`。

> **注：** 本窗口只裁定是否授权 ownership 迁移；**不裁定是否修改 init SQL**（init SQL 改动属 PR-1B 解除后的部署 runbook 范围，不在本审批授权内，见 §8）。

---

## 3. Database Owner Semantics

PostgreSQL 16 下，database ownership 的语义事实（本窗口据 catalog 证据 + PostgreSQL 官方语义判定）：

### 3.1 database owner 的不可 REVOKE 能力

database owner 持有**所有权行政能力**，其来源是 ownership 本身，不是 `pg_database.datacl`：

1. `ALTER DATABASE`（rename / set configuration parameters / change tablespace）；
2. `DROP DATABASE`；
3. 在自身拥有的 schema 中创建/drop 对象的隐式 owner 权限；
4. 控制自身拥有的 schema 的 ACL（GRANT/REVOKE 给他人）。

这些能力**不存储在 datacl**（当前 `datacl = NULL` 即证明 owner 权限独立于 ACL 存在），**不可被 `REVOKE` 移除**。

### 3.2 pg_database_owner 是不可 REVOKE 的隐式成员关系

`pg_database_owner` 是 PG 15+ 内置 pseudo-role，其唯一成员是"当前 database 的 owner"。成员关系是**结构性隐式**的：

- 本窗口核验：`pg_auth_members` 中 `auto_wechat` 的显式成员关系 = 0 行；
- 但 `pg_has_role('auto_wechat','pg_database_owner','member') = TRUE`。

→ 该成员关系**不是通过 GRANT 授予的，因此无法通过 REVOKE 移除**。唯一消除方式是改变 database owner 本身。

### 3.3 public schema ownership 链

PG 15+ 起 `public` schema owner = `pg_database_owner`（核验确认 `schema_owner = pg_database_owner`）：

```text
auto_wechat (DB owner)
  → 隐式成员 pg_database_owner
    → pg_database_owner owns public schema
      → auto_wechat 获得 public schema 的 owner 权限（USAGE + CREATE）
```

`has_schema_privilege('auto_wechat','public','CREATE') = TRUE` 即来自此链。该权限是**ownership 派生**，不是 `nspacl` 中 grantee=`auto_wechat` 的显式条目（nspacl 里根本没有 grantee=auto_wechat 的条目，只有 `pg_database_owner=UC` 与 PUBLIC `=U`）→ **`REVOKE CREATE ON SCHEMA public FROM auto_wechat` 没有可移除的 ACL 条目，移除不了 ownership 派生的 CREATE**。

### 3.4 为什么 REVOKE CREATE（Candidate B）在语义层失败

即使退一步假设能通过某种 ACL 操作把 `pg_database_owner=UC` 改写为只 `U`：

1. **owner 可单方面恢复被收回的权限。** schema owner 拥有 GRANT/REVOKE 该 schema 权限的行政能力。被 REVOKE 的 CREATE 可被 owner（即 auto_wechat 自身）随时重新 GRANT 给自己。即"被保护对象可自行恢复保护"，属 security theater，不构成 separation。
2. **ownership 还携带与 CREATE 无关的行政能力。** ALTER DATABASE / DROP DATABASE / 控制 schema ACL——这些能力与"能不能 CREATE TABLE"无关，但全是 ownership-level control，恰是 contract 要求 application principal 必须不持有的。
3. **contract 要求的是"零 ownership-level control"，不是"CREATE 当前失败"。** 上游"任一均可，只要消除 CREATE 泄漏"只在现象层成立；语义层 ownership 仍在 application principal 手中。

→ **database ownership 不能被 GRANT/REVOKE 等价替代为"非 owner runtime principal"的 Contract。** PR-1B 判定成立。

---

## 4. Candidate A Verdict

```text
Candidate A — Transfer ownership to postgres:
APPROVED
```

执行 `ALTER DATABASE auto_wechat OWNER TO postgres;`，将 database ownership 迁移给已冻结的 local migration principal `postgres`。

判定依据：

1. **消除 ownership-level control。** 迁移后 `auto_wechat` 不再是 DB owner → 不再隐式 `pg_database_owner` 成员 → 不再拥有 public schema 的 owner 权限与 database 级 ALTER/DROP 行政能力。这是从语义层满足 `SEPARATED MIGRATION / APPLICATION RESPONSIBILITY` 的唯一方式。
2. **消除 CREATE 泄漏的根因而非症状。** `has_schema_privilege('auto_wechat','public','CREATE')` 与 `has_database_privilege('auto_wechat','auto_wechat','CREATE')` 预期均变为 `false`（当前唯一 CREATE 来源是 ownership 链；显式 grants=0、default_acl=0、relacl=NULL，无其他来源）。
3. **与对象 owner 一致。** 61 表 owner 已是 `postgres`（核验确认）；database owner 迁移到 `postgres` 后，database 与其内 schema/对象的 owner 对齐到同一 migration principal，不再有"对象 owner=postgres 但 database owner=auto_wechat"的脱节。
4. **不破坏 DB-BL。** DB-BL 冻结的是 schema baseline（revision=0034 / 61 表），不是 database owner。`ALTER DATABASE OWNER` 不改任何 schema 对象、不改 revision、不改表 owner，DB-BL = REPAIR_VERIFIED 不受影响。
5. **影响面最小、可逆性低风险。** 仅改 `auto_wechat` 库 owner；不改角色属性、不改密码、不改迁移、不动 staging/prod。owner 迁移后 `auto_wechat` 失去对自身库的 owner 控制——这正是 principal separation 的目标，不是副作用。

---

## 5. Candidate B Verdict

```text
Candidate B — Keep application role as DB owner:
REJECTED
```

保持 `database owner = auto_wechat` 并尝试通过 `REVOKE CREATE` 限制 DDL capability 的路径不成立。

判定依据：

1. **CREATE 经 ownership 链派生，无可 REVOKE 的 ACL 条目。** §3.3 已证：`auto_wechat` 的 public CREATE 来自 `pg_database_owner` 隐式成员 → schema ownership，nspacl 中无 grantee=`auto_wechat` 条目，`REVOKE CREATE ON SCHEMA public FROM auto_wechat` 无可移除对象。
2. **即使收 `pg_database_owner=UC`，owner 可自行恢复。** §3.4-1：schema owner 持有 GRANT/REVOKE 行政能力，被收回的 CREATE 可被 auto_wechat 随时 GRANT 回自身。被保护对象可自行恢复保护 = 无效 separation。
3. **ownership 行政能力超出 CREATE 范畴。** §3.4-2：ALTER DATABASE / DROP DATABASE / schema ACL 控制 等所有权能力与 CREATE 无关，却全是 contract 要求 application principal 不持有的 ownership-level control。
4. **不满足 Approval Question A。** §1.1 已答 NO：保持 database owner 即保留 ownership-level administrative capability，违反 `SEPARATED MIGRATION / APPLICATION RESPONSIBILITY`。Candidate B 无法证明"保留 ownership 仍属合法 runtime principal 边界"，因为 PostgreSQL ownership 语义本身否定该命题。

Candidate B 的"REVOKE CREATE makes CREATE TABLE fail"既不充分（owner 可恢复）也不必要（ownership 还有其他行政能力），按 §10 审批标准 REJECTED。

---

## 6. Local Migration Principal Verification

```text
LOCAL MIGRATION PRINCIPAL:
postgres   （冻结）
```

本窗口独立核验 `postgres` 当前确实承担 local migration/admin responsibility：

| 核验项 | 证据 | 结论 |
|---|---|---|
| canonical objects ownership | 61 表 owner = postgres（catalog GROUP BY 核验）| ✓ migration principal owns schema objects |
| DB-BL Alembic bootstrap identity | DB-BL-2D 以来 `alembic upgrade head` 由 postgres superuser 执行（IMPLEMENTATION_REPORT §4、DESIGN §1.1）| ✓ 历史迁移执行身份 = postgres |
| current local Alembic execution config | [migrations/postgres/auto_wechat/env.py:27-35](migrations/postgres/auto_wechat/env.py#L27-L35) 读 `DATABASE_URL`，迁移代码无权限 DDL；dev PG profile `POSTGRES_USER:-postgres`（[docker-compose.dev.yml:36-38](docker-compose.dev.yml#L36-L38)）| ✓ 当前 Alembic 执行身份 = postgres |
| postgres role attributes | rolname=postgres / rolcanlogin=t / rolsuper=t / rolcreatedb=t（本窗口核验）| ✓ 存在且具备 migration principal 所需 DDL 能力 |
| future ADP design 已冻结 `FOR ROLE postgres` | DESIGN §6.2 / APPROVAL §9 冻结 `ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public ...` | ✓ 与 creator 一致 |

→ `LOCAL MIGRATION PRINCIPAL = postgres` 与 canonical objects ownership / Alembic bootstrap identity / 当前 Alembic 执行配置 / 未来 ADP 设计**全部一致**，可冻结。

> **一致性前提成立才允许 ownership transfer：** §5 核验通过，故 §4 Candidate A 的目标 owner = `postgres` 与现有对象 owner / ADP creator 对齐，迁移后无"database owner 与对象 owner 脱节"残留。

---

## 7. public Schema Ownership / CREATE Contract

### 7.1 当前 public schema 状态

```text
public schema owner = pg_database_owner
public schema nspacl = {pg_database_owner=UC/pg_database_owner, =U/pg_database_owner}
```

`pg_database_owner=UC`：DB owner（当前 auto_wechat）有 USAGE+CREATE；`=U`：PUBLIC 有 USAGE。

### 7.2 ownership transfer 后的 pg_database_owner 语义

`pg_database_owner` 是"当前 database owner"的 pseudo-role。`ALTER DATABASE auto_wechat OWNER TO postgres` 后：

- `pg_database_owner` 成员从 `auto_wechat` 切换到 `postgres`；
- `public` schema 的 owner 仍为 `pg_database_owner`，但其成员现在解析为 `postgres`；
- `pg_database_owner=UC` 不变，但受益者变为 `postgres`（与 61 表 owner 一致）；
- PUBLIC `=U` 不变，`auto_wechat` 经 PUBLIC 仍获 `USAGE`。

### 7.3 预期 transfer 后 auto_wechat 的 public schema 权限

```text
auto_wechat effective public USAGE  = true   （经 PUBLIC =U，USAGE 属 application 合法边界）
auto_wechat effective public CREATE = false  （不再是 pg_database_owner 成员；无显式 GRANT；无 ownership）
```

目标不是"application role can no longer connect"，而是：

```text
auto_wechat:
USAGE  eventually allowed（经 PUBLIC，后续 PR-3 显式 GRANT USAGE 为 belt-and-suspenders）
CREATE denied
```

USAGE 属后续 PR-3 minimum permission implementation 范围（见 DESIGN §3.2），本审批不实施 USAGE GRANT。

### 7.4 database-level CREATE 预期

```text
auto_wechat effective DATABASE CREATE = false  （owner 权利转移给 postgres；datacl=NULL，无显式 GRANT）
auto_wechat effective DATABASE CONNECT = true  （PUBLIC 默认 CONNECT，后续 PR-3 显式 GRANT）
```

---

## 8. Ownership Correction Scope

```text
P1-PG-APP-ROLE-1R OWNERSHIP CORRECTION:
AUTHORIZED — LOCAL DEVELOPMENT ONLY
```

未来实施**只允许**：

```sql
ALTER DATABASE auto_wechat OWNER TO postgres;
```

或实际安全执行所需的等价数据库管理操作。

**禁止同时**：

- 改 table owner（当前 61 表 owner 已是 postgres，不得动）；
- 改 application role 属性（rolsuper / rolcreatedb / rolcreaterole / rolbypassrls 保持 false）；
- `GRANT SUPERUSER` / `GRANT CREATEDB` / `GRANT CREATEROLE`；
- 修改 migration（0034 baseline 不动）；
- 修改 DB-BL schema baseline；
- 修改 staging / production；
- 修改 [001_create_databases.sql](docker/postgres/init/001_create_databases.sql)（init SQL 的 `OWNER auto_wechat` 改动属部署 runbook 范围，**不在本审批授权内**；本审批仅授权对当前 canonical dev PG 的单条 `ALTER DATABASE OWNER`。init SQL 是否同步修正由后续 runbook 审批另行裁定，不得借本审批顺手改）；
- 改 DATABASE_URL / 改 M07 Core / RB-10 cleanup / 0032-0034 consumer PG verification。

---

## 9. PR-1B Reverification Contract

实施 `ALTER DATABASE OWNER` 后**不能仅看** `database owner = postgres`，必须重新跑 PR-1B Hard Gate。

### 9.1 Transfer 前 Evidence（实施前必须再次确认）

```text
environment            = LOCAL DEVELOPMENT ONLY（auto-wechat-postgres-dev @5432，auto_wechat 库）
current_database owner = auto_wechat
target owner role postgres EXISTS（rolname=postgres, rolsuper=true）
```

并记录 before snapshot（即 §2.2 已冻结事实）。

### 9.2 Transfer 后 Hard Verification（必须全 PASS 才可进入 PR-2）

```text
database owner                         = postgres
auto_wechat is database owner          = false
auto_wechat effective DATABASE CREATE  = false
auto_wechat effective public SCHEMA CREATE = false
auto_wechat SUPERUSER / CREATEDB / CREATEROLE / BYPASSRLS = false / false / false / false
```

### 9.3 若 transfer 后仍有 CREATE capability

```text
STOP
```

不得直接进入权限 GRANT。必须找出真实来源：

- PUBLIC grant（如 `REVOKE CREATE ON SCHEMA public FROM PUBLIC`——但当前 nspacl 只有 `pg_database_owner=UC` + PUBLIC `=U`，PUBLIC 无 CREATE，预期不需）；
- direct grant（当前 grants=0，预期无）；
- role membership（`auto_wechat` 显式 membership=0，预期无）；
- schema ACL（transfer 后 nspacl 仍是 `{pg_database_owner=UC, =U}`，但 `pg_database_owner` 已解析为 postgres，auto_wechat 不再受益 UC）。

按当前 §2.2 证据，`auto_wechat` CREATE 的**唯一来源**是 ownership 链，无其他 grant/default_acl/membership 残留。故 transfer 后 CREATE 预期为 false；若不为 false，说明存在未发现的来源，必须 STOP 排查，不得碰运气扩大 GRANT。

---

## 10. P1-PG-APP-ROLE-2 Resume Authorization

```text
P1-PG-APP-ROLE-2 RESUME AUTHORIZATION:
AUTHORIZED — RESUME FROM PR-1B
```

### 10.1 Resume Contract

```text
Ownership correction（ALTER DATABASE auto_wechat OWNER TO postgres）
  → §9 Transfer 后 Hard Verification（重跑 PR-1B）
```

PR-1B PASS：

```text
→ PR-2  before privilege snapshot
→ PR-3  existing object grants（GRANT CONNECT/USAGE/DML + REVOKE alembic_version 写，C3 顺序硬约束）
→ PR-4  future ADP（FOR ROLE postgres IN SCHEMA public）
→ PR-5  无意外 DDL/superuser
→ PR-6  /ready 以应用角色 PASS
→ PR-7  代表性读写事务
→ PR-8  sequence/identity
→ PR-9  负向 DDL（CREATE TABLE → DENIED）
→ PR-10 权限快照对比
→ PR-11 alembic_version 写负向 → DENIED
→ PR-12 TRUNCATE 负向 → DENIED
→ PR-13 after snapshot
```

PR-1B 仍失败：

```text
STOP
```

不得扩大权限修改范围，不得用 superuser 替代 app role 续跑 consumer，不得改成 superuser，不得临时增加 ALL PRIVILEGES。

### 10.2 不得重开 DB-BL

```text
DB-BL = REPAIR_VERIFIED / COMPLETE  （不重开）
```

ownership correction 不重开 DB-BL、不重做 schema baseline。`ALTER DATABASE OWNER` 与 DB-BL 冻结的 schema baseline（revision=0034 / 61 表）正交。Resume 从 PR-1B 续跑，不从 DB-BL 重做。

---

## 11. Git Commit Hold/Authorization

```text
COMMIT DECISION:
ownership blocker 审批完成前  = HOLD
ownership blocker 审批完成后  = AUTHORIZED（作为治理 checkpoint 一次提交）
```

### 11.1 当前未提交文档

当前 git status 未提交三份文档：

- corrected [P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md](P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md)（C1-C4 corrections 已 FROZEN）；
- [P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md)（PR-1B blocker evidence + blocked implementation evidence）；
- [P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_APPROVAL.md)（上游审批 APPROVED_WITH_CORRECTIONS）；
- 本报告 [P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md)（ownership approval）。

### 11.2 提交策略

审批完成（本报告落地）后，可将：

```text
C1-C4 corrections
  + blocked implementation evidence（PR-1B blocker DETECTED + STOP）
  + ownership approval（Candidate A APPROVED / Candidate B REJECTED / postgres 冻结 / Resume from PR-1B）
```

作为一个治理 checkpoint 提交。Commit Message 使用中文。

### 11.3 不并入本次提交

`ALTER DATABASE auto_wechat OWNER TO postgres` 的**实施结果**（transfer 前/后 snapshot、Hard Verification 证据、PR-1B 重跑结果）应由后续 `P1-PG-APP-ROLE-2` 实施报告**再独立提交/冻结**，不得借本次治理 checkpoint 审批提前夹带实施结果。本审批窗口不实施 ownership transfer，故本次提交不含任何 DB 写操作证据。

---

## 12. Production/Staging Boundary

```text
PRODUCTION / STAGING:
NO WRITE
RUNTIME_UNKNOWN
```

- production / staging 实际运行 principal = `RUNTIME_UNKNOWN`（`PG_USER` 在 `.env.production.local` / `.env.staging.local`，不入库）。
- 静态配置可知的 contract 模式：单 superuser role（`POSTGRES_USER`）同时做 DDL+DML（[init-prod/010](docker/postgres/init-prod/010_create_rag_database.sh) 注释显式确认）。
- 本审批的 `ALTER DATABASE OWNER` 授权**仅限 LOCAL DEVELOPMENT ONLY**（canonical dev PG @5432，auto_wechat 库）。
- **不得将 local ownership correction 自动部署到 production/staging。** Local 验证通过只代表 `LOCAL_DEVELOPMENT_OWNERSHIP_CONTRACT_VERIFIED`，生产需未来独立 deployment evidence。
- prod 若要落实 `SEPARATED MIGRATION / APPLICATION RESPONSIBILITY`（应用角色非 superuser、非 DB owner），需在 init-prod 之外补建非 superuser 应用 role + 授权脚本 + ownership 治理，属独立部署审批，不在本审批执行范围。
- 当前 prod 以 superuser 运行应用 = **已记录的残余风险（accepted residual risk）**，不等于 `E2E_VERIFIED_FIXED`。

---

## 13. Explicitly Forbidden（本审批窗口）

本审批窗口**不自行实施**，且明确禁止：

- `ALTER DATABASE OWNER`（授权给后续实施窗口，本窗口只裁定）；
- `GRANT` / `REVOKE` / `ALTER ROLE` / `ALTER DEFAULT PRIVILEGES`；
- 改 schema owner / table owner；
- 修改 migration / DB-BL schema baseline；
- staging / production 任何 DB 操作；
- 0032 / 0033 / 0034 consumer PG verification；
- RB-10 cleanup；
- DB-BL reopen；
- 修改 [001_create_databases.sql](docker/postgres/init/001_create_databases.sql) init SQL；
- 改 DATABASE_URL / 改 M07 Core。

---

## 附：本审批窗口独立核验证据索引

| 核验项 | 方法 | 结论 | 与上游一致性 |
|---|---|---|---|
| 容器健康 | `docker ps` | auto-wechat-postgres-dev Up 6h (healthy) @5432 | ✅ |
| 环境身份 | `psql current_database/current_user/version` | auto_wechat / postgres / PG 16.14 / head=0034 / 61 表 | ✅ |
| database owner | `pg_database.datdba` | **auto_wechat**（blocker）| ✅ |
| database datacl | `pg_database.datacl` | NULL | ✅ |
| role 属性 | `pg_roles` 只读 | auto_wechat: LOGIN/SUPERUSER=f/CREATEDB=f/CREATEROLE=f/BYPASSRLS=f/INHERIT=t | ✅ |
| 显式 membership | `pg_auth_members` | 0 行 | ✅ |
| pg_database_owner 隐式成员 | `pg_has_role(...,member)` | **TRUE**（不可 REVOKE）| ✅ |
| public schema owner/ACL | `pg_namespace` | pg_database_owner / `{pg_database_owner=UC, =U}` | ✅ |
| effective db CREATE | `has_database_privilege` | **true**（ownership 派生）| ✅ |
| effective public CREATE | `has_schema_privilege` | **true**（ownership 派生）| ✅ |
| 表 owner 分布 | `pg_class` GROUP BY | postgres=61 | ✅ |
| table grants=0 | `information_schema.role_table_grants` | 0 | ✅ |
| seq/usage grants=0 | `information_schema.role_usage_grants` | 0 | ✅ |
| default_acl=0 | `pg_default_acl` | 0 | ✅ |
| douyin_leads.relacl | `pg_class.relacl` | NULL | ✅ |
| postgres 候选 principal | `pg_roles` | EXISTS / LOGIN / SUPERUSER | ✅ |
| 根因 init SQL | [001_create_databases.sql:20-21](docker/postgres/init/001_create_databases.sql#L20-L21) | `CREATE DATABASE auto_wechat OWNER auto_wechat` | ✅ |

所有核验均为只读 catalog inspection，零写操作。

---

## 审批窗口停止点

审批完成。本窗口**不自行执行** `ALTER DATABASE OWNER` / GRANT / REVOKE / ALTER ROLE / ALTER DEFAULT PRIVILEGES / 改 owner / 改 schema / 改 migration / staging-prod 操作 / 0032-0034 consumer verification。

下一步：交由 `P1-PG-APP-ROLE-2` 实施窗口在 LOCAL DEVELOPMENT ONLY 范围内执行 §8 单条 `ALTER DATABASE auto_wechat OWNER TO postgres;`，通过 §9 Hard Verification（重跑 PR-1B）后按 §10 Resume Contract 从 PR-1B 续跑 PR-2~PR-13。实施结果由后续实施报告独立提交/冻结。

```text
P1-PG-APP-ROLE-1R:
OWNERSHIP CORRECTION AUTHORIZED — LOCAL DEVELOPMENT ONLY
Candidate A APPROVED / Candidate B REJECTED
LOCAL MIGRATION PRINCIPAL = postgres (FROZEN)
P1-PG-APP-ROLE-2 RESUME FROM PR-1B (AUTHORIZED, post Hard Verification)
```

审批完成，停止。
