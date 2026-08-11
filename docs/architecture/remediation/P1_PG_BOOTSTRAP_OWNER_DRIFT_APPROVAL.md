# P1-PG-BOOTSTRAP-OWNER-DRIFT-1 — Fresh Bootstrap Principal Reproducibility 独立设计审批报告

> 任务：`P1-PG-BOOTSTRAP-OWNER-DRIFT-1 — PostgreSQL Fresh Bootstrap Ownership Gap` 独立设计审批
> 审批窗口：P1-PG-BOOTSTRAP-OWNER-DRIFT-1 独立设计审批窗口
> 审查对象：`docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_DESIGN.md`（设计窗口 verdict = `DESIGN_READY_FOR_APPROVAL`）+ 真实代码事实
> 当前 checkpoint：`5d8b6ba`（验证：闭环RAG Query 0005 PostgreSQL幂等计费）
> 审批日期：2026-08-11
> Source of Truth：本窗口独立只读代码事实（init SQL / compose / alembic 调用链 / 现有脚本目录） > 设计报告 > 推测

---

## Technical Decision

```text
APPROVED_WITH_CORRECTIONS
```

两个 Gap 均经独立核验成立，Preferred Strategy（Candidate A owner→postgres + 新增 post-alembic permission bootstrap 脚本）完整且与冻结 contract 一致，**但实施前必须应用以下 correction，否则不得进入实施**：

- **C1**：Gap① + Gap② 必须作为一个 implementation unit（Option 2），不得拆分。
- **C2**：permission bootstrap 必须有明确的 post-alembic 调用入口（当前无自动化编排，设计报告仅提出 SQL 文件未明确 WHO/WHEN/HOW 调用——休眠文件 ≠ 可重复 bootstrap）。
- **C3**：新增 FB-11 Permission Bootstrap Idempotency。
- **C4**：新增 FB-12 Zero Manual Intervention。
- **C5**：`001_create_databases.sql` 的 dev-only 影响已独立核验为真（仅 `docker-compose.dev.yml:41` 引用，prod/staging 用各自 `init-prod`/`init-staging`），"dev-only" 描述准确，但实施窗口须在 commit 中保留该 environment 边界证据，不得后续被误改成共享脚本。

这些 correction 不改变核心方案，只补齐"可执行性"与"验收闭环"。

---

## Gap① Independent Verification

### 文件

`docker/postgres/init/001_create_databases.sql`（共 25 行）。

### 行为

第 20-21 行：

```sql
SELECT 'CREATE DATABASE auto_wechat OWNER auto_wechat'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

以 `postgres` superuser（dev `POSTGRES_USER` 默认值，docker-compose.dev.yml:36）执行，`OWNER auto_wechat` 使 app role 成为 `auto_wechat` database 的 owner → 隐式 `pg_database_owner` 成员 → public schema CREATE 泄漏 + ALTER/DROP DATABASE 行政能力。

### 所属 environment

- `docker/postgres/init/` 仅被 `docker-compose.dev.yml:41` 挂载到 `/docker-entrypoint-initdb.d:ro`。
- `docker-compose.yml:19`（prod）挂载 `docker/postgres/init-prod/`。
- `docker-compose.staging.yml:37`（staging）挂载 `docker/postgres/init-staging/`。

→ **001_create_databases.sql 是 dev 专属脚本，不与 staging/prod 共享。**

### init 调用路径

```text
empty PG data dir
  → docker-entrypoint-initdb.d 执行 001_create_databases.sql（仅首次，空 volume）
  → CREATE ROLE auto_wechat / xg_douyin_ai_cs（LOGIN，非 superuser）
  → CREATE DATABASE auto_wechat OWNER auto_wechat  ← ★ Gap ① 来源
  → PG ready
```

### 裁定

如果现在从全新 volume 执行 dev bootstrap（不执行人工 runbook），最终 `database owner = auto_wechat`——与冻结的分离 contract（owner=postgres）冲突。

```text
LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = VERIFIED（FRESH BOOTSTRAP / REPRODUCIBILITY，非当前运行库漂移）
```

当前 canonical dev PG（运行库）owner=postgres（前序窗口手工 ALTER 后，RAG Query 0005 审批已独立验证），**COMPLIANT**。Gap 只在"删除 volume 重新 bootstrap"时重现。

---

## Gap② Independent Verification

设计报告新增 `FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP`，声称 GRANT/REVOKE/ADP 只存在于手工 runtime 状态 / governance runbook，不存在可重复执行的 bootstrap 脚本。

### 独立搜索（非文档文件）

本窗口对全 repo 非 `.md` 文件搜索：

```text
grep "ALTER DEFAULT PRIVILEGES | GRANT SELECT, INSERT | GRANT USAGE ON SCHEMA | REVOKE.*alembic_version | GRANT.*ON ALL TABLES"（glob !*.md）
→ 0 命中
```

### 现有脚本目录核验

`scripts/` 下无任何 `pg/bootstrap_app_role*` 或 permission bootstrap 脚本。现有与 PG migration 相关的脚本均为 SQLite→PG cutover（`migrate_9000_sqlite_to_postgres_cutover.py` 等）或 smoke test，**均不做** GRANT/ADP。

### docker/postgres/ 全目录（3 文件）

| 文件 | 职责 | 是否做 GRANT/ADP |
|---|---|---|
| `init/001_create_databases.sql` | 建 role + 2 database（dev）| 否 |
| `init-prod/010_create_rag_database.sh` | createdb xg_douyin_ai_cs（prod，单 role）| 否 |
| `init-staging/010_create_rag_database.sh` | createdb xg_douyin_ai_cs（staging，单 role）| 否 |

三者均**不做** existing-object grants / alembic_version hardening / sequence privileges / future default privileges 的自动化恢复。

### 裁定

```text
FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP = VERIFIED（GRANT/ADP/REVOKE 无任何脚本，仅存于手工 canonical DB 状态）
```

→ 当前授权模型只存在于手工已执行数据库状态，fresh bootstrap **不会自动重建** GRANT/ADP。

---

## Fresh Bootstrap Principal Reproducibility（Gap② 阻断性裁定）

如果现在从全新 volume 执行当前正常项目 dev bootstrap，不执行任何人工 runbook：

```text
最终是否出现：
  database owner = auto_wechat           → 是（Gap①）
  auto_wechat table grants = 0           → 是（init SQL 不 GRANT，alembic 以 postgres 建表但不对 app role 授权）
  auto_wechat sequence grants = 0        → 是
  future ADP missing                     → 是（无脚本建 ADP）
```

任何一条成立即：

```text
FRESH BOOTSTRAP PRINCIPAL CONTRACT = NOT REPRODUCIBLE
```

影响链：fresh bootstrap → app role 0 grants → `/ready` 第 3 步 `SELECT version_num FROM alembic_version` → `permission denied for table alembic_version` → 503 → 应用 unhealthy。

---

## Fresh Bootstrap Timeline（独立追踪）

```text
[1] docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
    docker-compose.dev.yml:26-48
    产物：空 named volume postgres_data，POSTGRES_USER=postgres（superuser）
          ↓

[2] PG entrypoint 检测空 data dir → 执行 /docker-entrypoint-initdb.d/*（一次性，仅首次）
    挂载：docker-compose.dev.yml:41 ./docker/postgres/init → /docker-entrypoint-initdb.d:ro
    脚本：001_create_databases.sql（postgres superuser 执行）
    产物：role auto_wechat/xg_douyin_ai_cs + database auto_wechat(owner=auto_wechat) + xg_douyin_ai_cs
          ↓

[3] healthcheck pg_isready → container healthy
    docker-compose.dev.yml:42-47
          ↓

[4] ★ 人工 runbook：alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head
    （以 postgres superuser，临时 DATABASE_URL=postgres）
    产物：61 表 + alembic_version，对象 owner=postgres
    自动化程度：无自动化（dev compose 无 PG alembic service，见下）
          ↓

[5] ★ 人工 runbook：ALTER DATABASE auto_wechat OWNER TO postgres
    自动化程度：无脚本
          ↓

[6] ★ 人工 runbook：GRANT/ADP/REVOKE permission bootstrap
    自动化程度：无脚本  ← Gap ②
          ↓

[7] 应用以 DATABASE_URL=postgresql+psycopg://auto_wechat:...@...:5432/auto_wechat 启动
    app/main.py ensure_runtime_schema → startup_skip_create_all（PG 不建表）
    守卫：scripts/init_db.py:28-35 PG 下 sys.exit(1) 拒绝 create_all
          ↓

[8] /ready 校验 SELECT version_num FROM alembic_version → HTTP 200
```

**步骤 [5][6] 完全不在任何脚本中**，步骤 [4] 依赖人工 runbook。

---

## Docker Init Semantics

### 一次性执行语义

PostgreSQL 官方镜像 `docker-entrypoint-initdb.d` 脚本**仅在 data directory 为空（首次初始化）时执行**；已有数据卷时不执行。

证据：`init-prod/010_create_rag_database.sh:4-5` 注释显式确认"只在数据卷为空时执行"。

### init 阶段业务表不存在

init 阶段（步骤 [2]）只能建 role/database，**不能做 `GRANT ON ALL TABLES`**——因为此时 alembic 还没跑，业务表不存在（0 表）。

→ permission bootstrap 必须是 **post-alembic 独立阶段**，不能塞进最早 init SQL。

```text
POST-ALEMBIC permission bootstrap stage = REQUIRED
```

### dev compose 不自动跑 PG alembic

`docker-compose.dev.yml:50-70` 的 `auto-wechat-sqlite-migrate` service 命令是 `migrations/migrate_sqlite.py --startup`，**只处理 SQLite**，不碰 PG。dev compose 无 PG alembic 自动化 service。所有 PG alembic 执行都是 smoke/test 脚本或人工 runbook。

`docker-compose.yml:54`（prod）注释"部署前必须先执行 alembic upgrade head"——prod/staging 也是人工/runbook 跑 alembic，无统一 orchestrator。

→ **无统一 post-alembic 编排入口可挂 permission bootstrap**（C2 的根因）。

---

## Role Reality

独立确认 dev init 流程创建/依赖的 roles：

| Role | LOGIN | SUPERUSER | CREATEDB | CREATEROLE | 来源 | 责任 |
|---|---|---|---|---|---|---|
| `postgres` | true | **true** | true | true | PG 镜像 POSTGRES_USER（dev 默认）| migration/ownership principal |
| `auto_wechat` | true | **false** | false | false | 001:4-10 | runtime application principal（DML 最小权限）|
| `xg_douyin_ai_cs` | true | false | false | false | 001:12-18 | 9100 RAG principal（本任务不处理）|

**fresh bootstrap 脚本意图**：`auto_wechat` 在 init SQL 执行后**只有 LOGIN，0 grants**（init SQL 不做任何 GRANT）。当前 runtime grants 是手工执行状态（VERIFIED），与 fresh bootstrap 脚本意图不得混为一谈。

---

## Environment Impact of 001（独立核验）

设计报告声称 `001_create_databases.sql` 第 20 行修改 = only dev。

独立核验：

```text
docker/postgres/init/       → 仅 docker-compose.dev.yml:41 引用（dev）
docker/postgres/init-prod/  → docker-compose.yml:19 引用（prod）
docker/postgres/init-staging/ → docker-compose.staging.yml:37 引用（staging）
```

三个环境用各自独立的 init 目录，**不共享**。prod/staging 用单 superuser role 模型（`POSTGRES_USER=auto_wechat` 同时 owner 两库，`init-prod/010` 只 createdb xg_douyin_ai_cs），与 dev 分离 contract 本就不同，属前序 ownership 审批登记的 accepted residual risk。

**裁定**：`001_create_databases.sql` 是 dev 专属脚本，修改它**只影响 local dev fresh bootstrap**，不影响 staging/prod contract。设计报告"dev-only"声明**准确**。

但：不得把修改描述成"无远端影响"就放松——实施窗口须在 commit message + 文档中保留该 environment 边界证据（prod/staging 仍 CONFIG_VERIFIED / RUNTIME_UNKNOWN / NO WRITE）。

---

## Candidate A / B / C

### Candidate A — Fresh DB 直接归 migration principal（APPROVED）

```sql
SELECT 'CREATE DATABASE auto_wechat OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

独立核验：

```text
LOCAL MIGRATION / OWNERSHIP PRINCIPAL = postgres（FROZEN，与 ownership 审批一致）
```

- current canonical object owner = postgres（RAG Query 0005 审批独立验证 61 表 owner=postgres）✅
- Alembic execution identity = postgres（dev runbook 以 postgres superuser 跑 alembic）✅
- approved ADP creator = postgres（ownership 审批 §6 冻结 creator=postgres）✅
- local bootstrap execution context = dev compose postgres profile，POSTGRES_USER=postgres（superuser）✅

dev init 以 `postgres` superuser 执行，`OWNER postgres` 合法。fresh 创建即 `owner=postgres`，步骤 [5] `ALTER DATABASE OWNER` 可省略。

→ **Candidate A = APPROVED**。

### Candidate B — CREATE 后 ALTER OWNER（REJECTED AS UNNECESSARY）

```sql
CREATE DATABASE auto_wechat OWNER auto_wechat;
ALTER DATABASE auto_wechat OWNER TO postgres;
```

Candidate A 可一步到位（`OWNER postgres` 直接生效），无需先建后转。多一条 `ALTER DATABASE` 增加出错面，无收益。

→ **Candidate B = REJECTED AS UNNECESSARY**（符合审批指令 §10）。

### Candidate C — App Role 继续 DB Owner（REJECTED，继续冻结）

```text
REJECTED（前序 ownership 审批 §5，本窗口不重新讨论）
```

ownership 派生的 CREATE 不可经 REVOKE 移除，owner 可单方面恢复，且 ownership 还携带 ALTER/DROP DATABASE 行政能力。**本窗口不得重新批准。**

---

## Combined Implementation Unit Decision

### Option 1 — Independent Fixes（先只修 owner，grants 以后修）

```text
REJECTED
```

只修 owner 仍非可重复 bootstrap：fresh bootstrap 会产生 `correct owner + 0 grants` → `/ready` 503。fresh bootstrap 成功合同不是"database owner correct"，而是"correct ownership + usable runtime principal + least-privilege boundary + future object reproducibility"。

### Option 2 — One Coherent Implementation Unit（一次实施 owner + grants + alembic_version + sequence + ADP + clean bootstrap E2E）

```text
APPROVED / REQUIRED
```

```text
database ownership
+ existing object runtime privileges
+ alembic_version hardening
+ sequence privileges
+ future default privileges
→ 一个 clean bootstrap E2E 验收（FB-0~FB-12）
```

→ **必须作为一个 implementation unit**（C1）。

---

## Permission Bootstrap Script

### 脚本形式

`scripts/pg/bootstrap_app_role_permissions.sql`（设计候选路径）。

**形式合适**：纯 SQL 脚本，幂等，由 postgres superuser 执行。不引入大型 bootstrap 平台 / 复杂权限服务 / FastAPI startup 提权。

### Existing business tables Contract

```text
授予 auto_wechat：
  SELECT / INSERT / UPDATE / DELETE

不得授予：
  TRUNCATE / REFERENCES / TRIGGER
```

设计报告 §8.3 `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat` 符合。

### alembic_version Hardening Contract

硬顺序：

```text
broad existing-table DML grant
  → explicit alembic_version write REVOKE
```

最终：

```text
alembic_version:
  SELECT = PASS
  INSERT = DENIED
  UPDATE = DENIED
  DELETE = DENIED
  TRUNCATE = DENIED
```

设计报告 §8.3 `REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat` 符合（broad GRANT 之后）。

**注意**：`GRANT ... ON ALL TABLES` 会包含 `alembic_version` 表，故 REVOKE 必须在 GRANT 之后、且须覆盖 INSERT/UPDATE/DELETE。TRUNCATE 因 broad GRANT 未授予 TRUNCATE，app role 本就无 TRUNCATE on alembic_version（但为显式边界，实施窗口可加 `REVOKE TRUNCATE` 收敛——非硬要求，因 broad GRANT 不含 TRUNCATE）。不依赖"alembic_version 永远不会被 recreate"。

### Sequence Contract

```text
Existing sequences：
  USAGE / SELECT

不得：
  ALL PRIVILEGES
```

设计报告 §8.3 `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat` 符合，自动覆盖 schema 所有序列。

### ADP Contract（Future Objects）

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
```

| 对象类型 | 授予 | 禁止 |
|---|---|---|
| Future tables | SELECT/INSERT/UPDATE/DELETE | TRUNCATE/REFERENCES/TRIGGER |
| Future sequences | USAGE/SELECT | UPDATE/setval |

设计报告 §8.3 符合，creator=postgres（FROZEN）。

### Script Idempotency（硬要求）

```text
run once  = PASS
run twice = PASS
final ACL unchanged
final ADP unchanged
no duplicate / error
```

`GRANT` / `REVOKE` / `ALTER DEFAULT PRIVILEGES` 均幂等，重复执行无副作用。`GRANT ON ALL TABLES` 在表集合不变时结果稳定；alembic 新增表后重跑会补授权新表（符合语义）。

→ 实施验收必须包含 **FB-11 Permission Bootstrap Idempotency**（C3）。

### Script Execution Identity

```text
permission bootstrap executor = postgres（migration/admin principal）
```

需要：grant existing objects / alter default privileges FOR ROLE postgres / harden alembic_version。

```text
不得使用 auto_wechat application principal 执行自身提权 bootstrap
```

---

## Post-Alembic Caller（★ 核心 correction C2）

### 问题

设计报告 §8.3 提出 `scripts/pg/bootstrap_app_role_permissions.sql`，但**未明确**：

```text
WHO CALLS bootstrap_app_role_permissions.sql?
WHEN?
HOW?
ON WHICH ENVIRONMENT?
WITH WHICH PRINCIPAL?
```

本窗口独立确认：**当前项目无统一 post-alembic 编排入口**（dev compose 不自动跑 PG alembic，无 init container/sidecar/bootstrap wrapper）。如果只新增 SQL 文件却无人调用，等于休眠文件，不能称可重复 bootstrap。

### 裁定

```text
若设计报告只提出新增 SQL 文件却没有明确执行入口 → CHANGES_REQUIRED
```

但本窗口不直接判 CHANGES_REQUIRED，而是作为 **correction C2** 授权实施窗口在冻结 scope 内补一个最小调用入口。

### 授权的最小调用入口

实施窗口须在实施 scope 增加**一个最小 bootstrap orchestration entry**（不得扩大为通用部署平台）。候选形式（实施窗口按既有模式选择）：

```text
existing local migration/bootstrap helper
  → alembic upgrade head
  → psql -U postgres -d auto_wechat -f scripts/pg/bootstrap_app_role_permissions.sql
```

或最小新增 helper（文件名由实施时独立代码审计确定，审批窗口不凭空发明）。

### 禁止

- 引入大型 bootstrap 平台
- 新建复杂权限服务
- 修改 application runtime 自动提权
- 让 FastAPI startup 执行 admin GRANT（**特别冻结**：FastAPI application startup DOES NOT execute admin GRANT/REVOKE/ADP；权限 bootstrap 属 deployment/migration administration，非 runtime 业务进程职责）

### 正常 bootstrap orchestration 必须保证

```text
Alembic COMPLETE
  → Permission Bootstrap COMPLETE
  → Application /ready
```

应用 service 不得在 permission bootstrap 完成前进入 ready。

---

## Existing vs Future Object Boundary（ADP 时序）

当前设计若 `Alembic head → ADP`：

```text
existing objects（alembic head 前已创建）= explicit GRANT ON ALL TABLES/SEQUENCES 授权
future objects（ADP 建立后由 postgres 新建）= ADP 自动授权
```

**ADP 不反向覆盖已存在的对象**——这是 PG 语义事实（ADP 只对"新建"对象生效）。permission bootstrap 脚本须同时包含：

1. `GRANT ... ON ALL TABLES/SEQUENCES`（覆盖 existing，alembic head 时的对象）
2. `ALTER DEFAULT PRIVILEGES`（覆盖 future，ADP 建立后新建对象）

执行顺序必须是 `alembic upgrade head → permission bootstrap`（不能 permissions → alembic），否则 migration 创建的新对象可能不满足 existing-object contract（ADP 若未建，新对象 0 grants；即使 ADP 已建，alembic 以 postgres 创建的对象享受 ADP，但若 ADP 未建则漏）。

设计报告 §8.3/§11.1 顺序正确。

---

## FB-0 ~ FB-12 Acceptance（独立复核 + 新增）

### FB-0 Isolation（保留）

```text
全新临时 PG（独立 project / volume / 端口，如 25433）
不得删除 canonical local DB
不得 rename 当前库
不得复用 legacy backup
```

### FB-1 Database Owner（保留）

```text
database owner = postgres（migration/admin principal）
app role is database owner = false
```

### FB-2 Schema Owner / CREATE（保留）

```text
app role DATABASE CREATE = false
app role public schema CREATE = false
```

### FB-3 Alembic（保留）

```text
empty → head（0034）完整成功
alembic_version 表存在，revision = head
```

### FB-4 Application Role DML（保留）

```text
CONNECT = PASS
SELECT/INSERT/UPDATE/DELETE = PASS
sequence USAGE + SELECT = PASS
```

### FB-5 alembic_version（保留）

```text
SELECT = PASS
INSERT/UPDATE/DELETE/TRUNCATE = DENIED
revision 不变
```

### FB-6 DDL（保留）

```text
CREATE TABLE（app role）→ DENIED
```

### FB-7 TRUNCATE（保留）

```text
TRUNCATE（app role，安全 fixture 表）→ DENIED
```

### FB-8 Future Object Contract（保留）

```text
migration principal postgres 创建新 table/sequence：
  app role DML（新 table）= PASS
  app role TRUNCATE（新 table）= DENIED
  app role sequence（USAGE + SELECT）= PASS
```

验证后由 postgres 清理临时对象。

### FB-9 /ready（保留）

```text
application principal auto_wechat：
  HTTP 200
  backend = postgresql
  database = auto_wechat
  alembic head = current（0034）
```

### FB-10 Cleanup（保留）

```text
临时 cluster / volume 删除
canonical local PG 无变化（table_count=61 / head=0034 / owner=postgres 不变）
```

### FB-11 Permission Bootstrap Idempotency（★ 新增，C3）

```text
执行 permission bootstrap：
  run #1 → PASS
  run #2 → PASS

第二次执行后：
  ACL unchanged
  ADP unchanged
  no duplicate / error
```

### FB-12 Zero Manual Intervention（★ 新增，C4）

从 empty isolated PG 开始，使用批准后的 normal bootstrap chain：

```text
role/database init（001_create_databases.sql，修改后 owner=postgres）
  → Alembic upgrade head
  → permission bootstrap（bootstrap_app_role_permissions.sql）
  → /ready
```

过程中不得：

```text
人工执行临时 GRANT
人工 ALTER OWNER
人工修 schema
blind stamp
```

最终必须自动满足全部 contract。否则仍不能称 REPRODUCIBLE。

---

## Canonical DB Safety

```text
current canonical local auto_wechat DB = READ ONLY / NO MUTATION
```

实施和验证必须保证：

- 不得重复 ALTER OWNER / GRANT / REVOKE / ADP 到当前 canonical 库（已 VERIFIED，PR-1B~PR-13）
- 所有 fresh-bootstrap E2E（FB-0~FB-12）使用独立临时 PG（FB-0 isolation）
- 不把 canonical DB 状态作为 rollback 试验场

---

## Staging / Production Boundary

```text
STAGING    = CONFIG_VERIFIED / RUNTIME_UNKNOWN   NO WRITE（继续冻结）
PRODUCTION = CONFIG_VERIFIED / RUNTIME_UNKNOWN   NO WRITE（继续冻结）
```

- staging/prod 不使用 `001_create_databases.sql`（独立核验：prod 用 init-prod，staging 用 init-staging），改 init SQL 不影响 staging/prod
- staging/prod 用单 superuser role 模型，与分离 contract 本就不同，属 accepted residual risk
- 本审批 NO REMOTE WRITE
- 不得宣称"staging/prod ownership fixed"
- prod 若要落实分离 contract，属独立部署审批，不在本设计范围

---

## Implementation File Scope（冻结）

### PROPOSED MODIFY

| 文件 | 改动 | 行数 | 影响 |
|---|---|---|---|
| `docker/postgres/init/001_create_databases.sql` | 第 20 行 `OWNER auto_wechat` → `OWNER postgres` | 1 行 | dev fresh bootstrap owner 修正（dev-only，已核验）|

第 23 行 `xg_douyin_ai_cs` **不改**（9100 不属本 gap 主体，§9100 boundary）。

### PROPOSED CREATE

| 文件 | 内容 | 责任阶段 |
|---|---|---|
| `scripts/pg/bootstrap_app_role_permissions.sql` | §Permission Bootstrap 的幂等 GRANT/ADP/REVOKE | post-alembic，应用启动前 |

### PROPOSED CREATE（★ correction C2 — 最小调用入口）

| 文件 | 内容 | 责任 |
|---|---|---|
| **一个最小 bootstrap orchestration entry**（文件名由实施时独立代码审计确定）| `alembic upgrade head → psql bootstrap_app_role_permissions.sql` 编排 | post-alembic 调用入口 |

实施窗口按既有项目模式选择具体形式（复用现有 local migration helper 或最小新增 helper），但**必须明确调用入口**，不得只留休眠 SQL 文件。

### READ ONLY / DO NOT MODIFY

| 文件 / 目录 | 理由 |
|---|---|
| `docker-compose.yml` / `docker-compose.staging.yml` / `docker-compose.dev.yml` | 不改 compose / POSTGRES_USER / 端口 / 挂载 |
| `docker/postgres/init-prod/010_create_rag_database.sh` / `init-staging/010_create_rag_database.sh` | 不改 prod/staging contract |
| `migrations/postgres/auto_wechat/`（alembic.ini / env.py / versions/）| 不改 migration / schema baseline（0034 不动）|
| `app/main.py` / `app/routers/health.py` / `app/db_readiness.py` / `scripts/init_db.py` | 不改 startup guard / readiness / init_db 守卫；**禁止 FastAPI startup 自行修权限** |
| `app/database.py` / DATABASE_URL 配置 | 不改 runtime 连接配置 |
| 当前 canonical dev PG（运行库）| 已 VERIFIED，不重新修 |
| `.env*` 文件 | 不改 env |
| M07 Core / consumer 代码 / RB-10 / DB-BL / 9100 principal / 9100 Alembic | 不碰 |

---

## 9100 Boundary

本任务只处理 `auto_wechat` local PostgreSQL。

不得顺手修改：

- `xg_douyin_ai_cs` DB owner（001:23 保留不变）
- 9100 principal（`xg_douyin_ai_cs` 角色权限较宽，前序 RAG Query 0005 审批已登记 future least-privilege governance gap）
- 9100 least privilege
- 9100 Alembic

这些继续作为独立 future governance 事项。

---

## Rollback

实施主要是 code/bootstrap contract 修改（init SQL 1 行 + 新增脚本 + 最小调用入口）：

```text
rollback = git revert + discard isolated verification cluster
```

- init SQL 修改：1 行 `OWNER auto_wechat` → `OWNER postgres`，回滚 = revert 该 1 行。不影响已有数据卷（init SQL 只在空 volume 执行）。
- permission bootstrap 脚本：新增文件，回滚 = 删除文件。GRANT/ADP/REVOKE 幂等，无破坏性。
- 最小调用入口：新增 helper，回滚 = 删除。

**不把 canonical DB 状态作为 rollback 试验场**。失败用 isolated 临时 PG 重试。

---

## Implementation Authorization

### 授权目标

```text
FRESH BOOTSTRAP PRINCIPAL REPRODUCIBILITY
```

最终从 empty isolated PG 自然得到：

```text
DB owner = postgres（migration principal）

application principal auto_wechat:
  CONNECT = PASS
  DML = PASS
  sequence = PASS

  DATABASE CREATE = DENIED
  SCHEMA CREATE = DENIED
  TRUNCATE = DENIED
  DDL = DENIED

  alembic_version:
    SELECT only

  future tables/sequences:
    correct default privileges

  /ready:
    PASS as application principal
```

全程：

```text
ZERO MANUAL PRIVILEGE REPAIR
```

### 授权范围

```text
LOCAL DEVELOPMENT + isolated clean-bootstrap verification environment
```

### 不授权事项（即使设计批准）

- staging/prod write（NO WRITE）
- 当前 canonical DB 权限修改（READ ONLY）
- 9100 principal 整改
- migration 修改
- business code 修改
- FastAPI startup 提权
- Global Active None Audit
- Final Concurrent Closure
- RB-10 cleanup
- 9100 Alembic / 9100 owner

---

## Corrections 清单（实施前必须应用）

```text
C1: Gap① + Gap② 作为一个 implementation unit（Option 2 REQUIRED，Option 1 REJECTED）
C2: permission bootstrap 须有明确 post-alembic 调用入口（最小 bootstrap orchestration entry），
    不得只留休眠 SQL 文件；禁止 FastAPI startup 自行 GRANT/REVOKE/ADP
C3: 新增 FB-11 Permission Bootstrap Idempotency（run #1/#2 均 PASS，ACL/ADP 不变）
C4: 新增 FB-12 Zero Manual Intervention（normal bootstrap chain 自动满足全部 contract）
C5: 001_create_databases.sql dev-only 已独立核验为真，实施窗口须在 commit + 文档保留
    environment 边界证据，不得后续误改成共享脚本
```

这些 correction 不改变核心方案（Candidate A + permission bootstrap 脚本），只补齐可执行性与验收闭环。

---

## Git Authorization

审批通过（APPROVED_WITH_CORRECTIONS），授权独立实施窗口在 LOCAL DEVELOPMENT ONLY 范围内：

1. 修改 `docker/postgres/init/001_create_databases.sql`（第 20 行 owner→postgres）
2. 新增 `scripts/pg/bootstrap_app_role_permissions.sql`（幂等 GRANT/ADP/REVOKE）
3. 新增/扩展一个最小 post-alembic 调用入口（C2）
4. 在隔离临时 PG 执行 FB-0~FB-12 验收（含新增 FB-11/FB-12）
5. 验证通过后同步文档状态 + commit（中文 commit message）

建议 commit message：

```text
修复：本地PG fresh bootstrap owner drift + 应用角色权限可重复 bootstrap
```

允许同步更新的治理文档：

```text
docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_DESIGN.md（状态流转）
docs/architecture/remediation/P1_PG_BOOTSTRAP_OWNER_DRIFT_APPROVAL.md（本审批报告）
docs/architecture/remediation/P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md（Blocker A′ 状态）
docs/ai/05_PROJECT_CONTEXT.md
CLAUDE.md（若 LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP 状态变化）
```

不得混入：业务代码 / migration 修改 / 9100 整改 / staging-prod write / Global None Audit / Final Concurrent Closure / RB-10。

---

## 审批窗口纪律遵守

- ✅ 独立核验 Gap①（001:20 OWNER auto_wechat，文件/行为/environment/init 路径）
- ✅ 独立核验 Gap②（全 repo 非文档搜索 GRANT/ADP/REVOKE = 0 命中；scripts/ 无 permission bootstrap）
- ✅ 独立核验 001 dev-only（仅 docker-compose.dev.yml:41 引用，prod/staging 用各自 init 目录）
- ✅ 独立核验 Docker init 时序（init 阶段业务表不存在，permission bootstrap 必须 post-alembic）
- ✅ 独立核验无统一 post-alembic 编排入口（dev compose 不自动跑 PG alembic，sqlite-migrate 只碰 SQLite）
- ✅ 独立核验 Candidate A 与冻结 contract 一致（postgres 为 migration/ownership principal）
- ✅ 不自行修改 init SQL / permission script / compose / 数据库 / migration（设计审批窗口，不实施）
- ✅ 9100 boundary 保持（001:23 xg_douyin_ai_cs 不改）
- ✅ canonical DB safety（不触碰当前运行库）

---

> 审批完成。按指令 §39：完成后停止。
> 不自行实施。交独立实施窗口在 LOCAL DEVELOPMENT ONLY 范围内按 Corrections C1~C5 执行。
