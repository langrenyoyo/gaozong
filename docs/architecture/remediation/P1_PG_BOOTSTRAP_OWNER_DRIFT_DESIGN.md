# P1 — PostgreSQL Fresh Bootstrap Owner Drift 设计/审计报告

> 任务：`P1-PG-BOOTSTRAP-OWNER-DRIFT-1 — PostgreSQL Fresh Bootstrap Ownership Gap 设计/审计窗口`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的 fresh-bootstrap reproducibility blocker（A′）
> 当前 checkpoint：`5d8b6ba`
> 日期：2026-08-11
> 窗口性质：**设计 / 审计，不实施修改**
> Source of Truth：本窗口独立只读代码事实（init SQL / compose / alembic env / readiness / 前序审批冻结证据） > 冻结文档 > 推测
> 上游冻结契约：
> - [P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md)（Candidate A APPROVED / Candidate B REJECTED / postgres 冻结）
> - [P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md)（runtime GRANT/ADP 已 VERIFIED）
> - [P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md)（§24.1 登记 drift gap OPEN）

---

## 0. Verdict 速览

| 维度 | 结论 |
|---|---|
| 当前 canonical dev PG（运行中）| **COMPLIANT**（owner=postgres，GRANT/ADP 已落地并独立审批 VERIFIED）|
| Fresh bootstrap 路径（init SQL）| **NOT YET COMPLIANT** |
| Gap ① — Database Owner Drift | **OPEN**（已知，§24.1 冻结）|
| Gap ② — Application Role Grant Reproducibility | **OPEN**（本窗口新登记，§10）|
| 是否阻断当前 consumer PG verification | **NO**（当前运行库已合规）|
| 是否阻断 P1 final technical closure | **YES**（须在 final closure 前关闭）|
| Preferred Strategy | **Candidate A（init SQL owner→postgres）+ 新增 post-alembic permission bootstrap 脚本** |
| 本窗口是否实施 | **NO**（设计/审计窗口，交独立审批）|

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

本窗口**不修改任何文件、不执行任何 DB 写操作**。下方所有 SQL 均为设计候选，未落地。

---

## 1. Current Gap

### 1.1 已冻结的 Runtime Principal Contract

```text
Runtime Principal Model: SEPARATED MIGRATION / APPLICATION RESPONSIBILITY
  Migration / ownership principal = postgres   （FROZEN）
  Runtime application principal  = auto_wechat （非 superuser，非 DB owner）
```

来源：[P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md) §4/§6；[P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md) PR-1B~PR-13。

### 1.2 当前运行库 vs fresh bootstrap 路径

```text
CURRENT RUNNING LOCAL DB : COMPLIANT
  （runtime 已 ALTER DATABASE OWNER TO postgres + GRANT/ADP 落地，PR-1B~PR-13 PASS）

FRESH BOOTSTRAP PATH     : NOT YET COMPLIANT
  （init SQL 仍 OWNER auto_wechat；且 GRANT/ADP 无脚本重建）
```

### 1.3 双重 Gap

| Gap | 来源 | 性质 |
|---|---|---|
| ① `LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP` | [001_create_databases.sql:20-21](docker/postgres/init/001_create_databases.sql#L20-L21) `CREATE DATABASE auto_wechat OWNER auto_wechat` | FRESH BOOTSTRAP / REPRODUCIBILITY（非当前运行库漂移）|
| ② `FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP` | 无任何脚本重建 GRANT/ADP（§10） | FRESH BOOTSTRAP / REPRODUCIBILITY（新登记）|

---

## 2. Fresh Bootstrap Call Chain

本窗口独立追踪 dev canonical fresh bootstrap 完整链路（每步引用真实文件与责任主体）：

```text
[1] docker compose -f docker-compose.dev.yml --profile postgres up -d postgres
    文件：docker-compose.dev.yml:26-48
    责任：开发者
    产物：新空 named volume `postgres_data`
    身份：POSTGRES_USER=postgres（superuser，dev 默认值）
          POSTGRES_DB=postgres（dev 默认值，非 auto_wechat）
          POSTGRES_PASSWORD=change_me
          ↓

[2] PG entrypoint 检测空 data directory → 执行 /docker-entrypoint-initdb.d/*（一次性，仅首次）
    挂载：docker-compose.dev.yml:41  ./docker/postgres/init:/docker-entrypoint-initdb.d:ro
    脚本：docker/postgres/init/001_create_databases.sql（以 postgres superuser 执行）
    产物：
      - CREATE ROLE auto_wechat LOGIN PASSWORD 'change_me'（非 superuser）
      - CREATE ROLE xg_douyin_ai_cs LOGIN PASSWORD 'change_me'
      - CREATE DATABASE auto_wechat OWNER auto_wechat        ← ★ Gap ① 来源
      - CREATE DATABASE xg_douyin_ai_cs OWNER xg_douyin_ai_cs （9100，本任务不处理，§16/§18）
          ↓

[3] healthcheck pg_isready → container healthy
    文件：docker-compose.dev.yml:42-47
          ↓

[4] 人工 runbook：临时注入 DATABASE_URL=postgresql+psycopg://postgres:...@127.0.0.1:5432/auto_wechat（postgres superuser）
    执行：alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head
    文件：migrations/postgres/auto_wechat/env.py:27-35（读 DATABASE_URL，迁移代码无权限 DDL）
    产物：61 表 + alembic_version，对象 owner=postgres（因以 postgres 执行）
    责任：人工 runbook（P3-C8B §29.1 证据：一次性容器 + 临时 DATABASE_URL）
    自动化程度：**无自动化**，依赖 runbook
          ↓

[5] 人工 runbook：ALTER DATABASE auto_wechat OWNER TO postgres;
    来源：P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md §8 Candidate A（APPROVED — LOCAL DEV ONLY）
    产物：database owner=postgres，消除 ownership blocker
    自动化程度：**无脚本**，仅在治理文档记录
          ↓

[6] 人工 runbook：权限 bootstrap（GRANT/ADP/REVOKE）
    来源：P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md §6/§7/§9
    SQL（设计，未脚本化）：
      GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;
      GRANT USAGE ON SCHEMA public TO auto_wechat;
      GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;
      GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;
      REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;
      ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;
      ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
    产物：app role 携带最小 DML + alembic_version SELECT-only + 未来对象 ADP
    自动化程度：**无脚本**，仅在治理文档记录  ← ★ Gap ② 来源
          ↓

[7] 应用以 DATABASE_URL=postgresql+psycopg://auto_wechat:...@...:5432/auto_wechat 启动
    文件：app/main.py:89,273-283 ensure_runtime_schema()
          → backend=postgresql → startup_skip_create_all（不建表，schema 由 Alembic 负责）
    守卫：scripts/init_db.py:28-35 PG 下 sys.exit(1) 拒绝 create_all
          ↓

[8] /ready 校验
    文件：app/routers/health.py:62-88 + app/db_readiness.py:75-223
    校验：SELECT version_num FROM alembic_version → 0034 → HTTP 200
    失败条件：app role 无 SELECT alembic_version 权限 → permission denied → 503
```

**关键事实**：步骤 [5] 和 [6] 完全不在任何脚本中。`docker-entrypoint-initdb.d` 阶段（步骤 [2]）只能建 role/database，**不能做 `GRANT ON ALL TABLES`**——因为此时 alembic 还没跑，业务表不存在（0 表）。权限 bootstrap 必须**在步骤 [4] alembic 之后**执行，属独立 post-alembic 阶段。

---

## 3. Docker Init Semantics

### 3.1 一次性执行语义

PostgreSQL 官方镜像 `docker-entrypoint-initdb.d` 脚本**仅在 data directory 为空（首次初始化）时执行**；已有数据卷时**不执行**。

依据：[init-prod/010_create_rag_database.sh:4-5](docker/postgres/init-prod/010_create_rag_database.sh#L4-L5) 注释显式确认。

### 3.2 Gap 性质裁定

```text
Gap 性质 = FRESH BOOTSTRAP / REPRODUCIBILITY GAP
       ≠ CURRENT RUNNING DATABASE DRIFT
```

当前 canonical dev PG 已由前序窗口手工 `ALTER DATABASE OWNER` + GRANT/ADP 修正（PR-1B~PR-13 VERIFIED）。gap 只在"删除 volume 重新 bootstrap"时重现。**不得误读为"当前运行库漂移"。**

### 3.3 无额外 bootstrap wrapper

本窗口确认：dev 无额外 bootstrap wrapper。`docker-compose.dev.yml` postgres service 直接用 `postgres:16-alpine` + `init/` 挂载，无自定义 entrypoint、无 init 容器、无 sidecar。compose 不自动跑 alembic（`auto-wechat-sqlite-migrate` 只处理 SQLite，见 docker-compose.dev.yml:51-70）。

---

## 4. Role Creation Reality

独立确认 dev init 流程当前创建/依赖的 roles：

| Role | LOGIN | SUPERUSER | CREATEDB | CREATEROLE | 来源 | database ownership intent | 责任 |
|---|---|---|---|---|---|---|---|
| `postgres` | true | **true** | true | true | PostgreSQL 镜像 `POSTGRES_USER`（dev 默认）| migration/ownership principal | DDL / 迁移 / 对象 owner |
| `auto_wechat` | true | **false** | false | false | [001_create_databases.sql:4-10](docker/postgres/init/001_create_databases.sql#L4-L10) | runtime application principal | DML（最小权限）|
| `xg_douyin_ai_cs` | true | false | false | false | [001_create_databases.sql:12-18](docker/postgres/init/001_create_databases.sql#L12-L18) | 9100 RAG principal（本任务不处理，§18）| 9100 metadata |

**不得把当前 runtime grants 与 fresh bootstrap 脚本意图混为一谈**：
- 当前 runtime：`auto_wechat` 已有 60 表 DML + 60 seq + 2 ADP（手工执行状态，VERIFIED）。
- fresh bootstrap 脚本意图：`auto_wechat` 在 init SQL 执行后**只有 LOGIN，0 grants**（init SQL 不做任何 GRANT）。

---

## 5. Database Creation Reality

### 5.1 dev（本任务主体）

```sql
-- 001_create_databases.sql:20-21
SELECT 'CREATE DATABASE auto_wechat OWNER auto_wechat'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

执行身份：`postgres`（superuser，dev `POSTGRES_USER`）。`OWNER auto_wechat` 使 app role 成为 database owner → 隐式 `pg_database_owner` 成员 → public schema CREATE 泄漏（详见 [OWNERSHIP_APPROVAL §3](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md)）。

### 5.2 prod / staging（非本任务，仅静态确认）

prod/staging **不使用** `001_create_databases.sql`：

| 环境 | init 目录 | 挂载文件 | POSTGRES_USER | 主库 owner | RAG 库 owner | 模型 |
|---|---|---|---|---|---|---|
| dev | `docker/postgres/init/` | `001_create_databases.sql` | `postgres`（默认）| `auto_wechat`（init 脚本设）| `xg_douyin_ai_cs` | 分离 role |
| prod | `docker/postgres/init-prod/` | `010_create_rag_database.sh` | `auto_wechat`（默认）| `auto_wechat`（镜像 POSTGRES_DB 自动）| `auto_wechat`（createdb --owner）| **单 superuser role** |
| staging | `docker/postgres/init-staging/` | `010_create_rag_database.sh` | `auto_wechat`（继承 base）| `auto_wechat_staging` | `auto_wechat_staging` | 单 superuser role |

证据：[docker-compose.yml:14-19](docker-compose.yml#L14-L19)（prod 用 `init-prod`，`PG_USER:-auto_wechat`）；[docker-compose.staging.yml:37](docker-compose.staging.yml#L37)（staging 用 `init-staging`）；[init-prod/010_create_rag_database.sh:7-8,18,24](docker/postgres/init-prod/010_create_rag_database.sh#L7-L8)（"生产策略：单应用 role 同时 owner 两个 database"）。

**结论**：`001_create_databases.sql` 是 **dev 专属脚本**，不与 staging/prod 共享。修改它**只影响 local dev fresh bootstrap**，不影响 staging/prod contract。

---

## 6. Current Canonical vs Fresh Bootstrap Comparison

| 维度 | 当前 canonical dev PG（运行中）| fresh bootstrap（删 volume 重跑，不执行手工 runbook）|
|---|---|---|
| database owner | `postgres`（手工 ALTER 后）| `auto_wechat`（init SQL 设）|
| app role `pg_database_owner` 成员 | false | **true**（ownership 派生）|
| app role DATABASE CREATE | false | **true**（ownership 派生）|
| app role public CREATE | false | **true**（ownership 派生）|
| 61 业务表 owner | postgres | postgres（alembic 以 postgres 跑）|
| app role table grants | 61 SELECT / 60 IUD / 0 TRUNCATE | **0**（无脚本 GRANT）|
| app role sequence grants | 60（USAGE+SELECT）| **0** |
| alembic_version app 权限 | SELECT-only | **0**（SELECT 也无）|
| pg_default_acl（ADP）| 2 条（creator=postgres, grantee=auto_wechat）| **0** |
| `/ready` as app role | HTTP 200 | **503**（`SELECT version_num FROM alembic_version` → permission denied）|

→ fresh bootstrap 仅靠 init SQL + alembic，**到不了** VERIFIED 的 runtime contract。必须补 ownership 修正 + 权限 bootstrap。

---

## 7. Candidate A / B / C

### Candidate A — Fresh DB 直接归 migration principal

将 init SQL 收敛为：

```sql
SELECT 'CREATE DATABASE auto_wechat OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

**分析**：
- local 是否可直接成立：**是**。dev init 以 `postgres` superuser 执行，`OWNER postgres` 合法。
- role/init 执行身份：postgres superuser（dev `POSTGRES_USER` 默认值）。
- staging/prod 模板是否复用该 SQL：**否**（§5.2，prod/staging 用各自 010 shell，单 role 模型）。
- 是否误改变远端 principal contract：**否**（仅改 dev init SQL，staging/prod 不受影响）。
- 是否影响 Alembic：**否**（alembic 仍以 postgres 跑，表 owner 不变）。
- 是否影响 application connection：**否**（`DATABASE_URL` 指向 `auto_wechat` 库，库 owner 改 postgres 不影响 app role 连接）。
- 是否消除 ownership blocker：**是**。fresh 创建即 `owner=postgres`，步骤 [5] `ALTER DATABASE OWNER` 可省略。

**与 ownership 审批 §8 一致性**：[OWNERSHIP_APPROVAL §8](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md) 第 299 行明确"init SQL 是否同步修正由后续 runbook 审批另行裁定"——本窗口正是该设计。

**局限**：只解决 Gap ①（ownership），**不解决 Gap ②**（GRANT/ADP 仍无脚本）。

### Candidate B — 创建后显式转移 owner

```sql
CREATE DATABASE auto_wechat OWNER auto_wechat;  -- 或不指定 OWNER
ALTER DATABASE auto_wechat OWNER TO postgres;
```

**分析**：
- 必要性：**无**。Candidate A 可一步到位，无需先建后转。
- 复杂度：多一条 `ALTER DATABASE`，且 init SQL 阶段 `CREATE DATABASE` 不能在事务内（已用 `\gexec` 规避），多一步增加出错面。
- 幂等性：`ALTER DATABASE OWNER` 幂等（重复执行无副作用），但与 A 比无收益。
- **若 A 能直接满足，不应采用 B**（任务 §7 约束）。

### Candidate C — 保持 app owner，再 REVOKE CREATE

```text
REJECTED  （前序 ownership 审批 §5，本窗口不重新讨论）
```

依据：[OWNERSHIP_APPROVAL §3.4/§5](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md)——ownership 派生的 CREATE 不可经 REVOKE 移除，owner 可单方面恢复，且 ownership 还携带 ALTER/DROP DATABASE 等行政能力。**本窗口不得重新批准。**

---

## 8. Preferred Strategy

### 8.1 双 Gap 必须一起设计

任务 §11 硬约束：不得只修 owner 却让 fresh bootstrap 产生 `correct owner + 0 grants`。

```text
Preferred Strategy =
  Candidate A（init SQL owner→postgres，解决 Gap ①）
  +
  新增 post-alembic permission bootstrap 脚本（解决 Gap ②）
```

两者共同构成**可重复 fresh-bootstrap permission bootstrap**。

### 8.2 Ownership 修复（Gap ①）

```sql
-- 001_create_databases.sql:20 修改（1 行）
SELECT 'CREATE DATABASE auto_wechat OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auto_wechat')\gexec
```

`xg_douyin_ai_cs` 行（第 23 行）**不改**（§18：9100 不属本 gap 主体，另行登记）。

### 8.3 权限 bootstrap（Gap ②）

新建幂等 SQL 脚本（设计，未落地），在 **alembic upgrade head 之后**执行（post-alembic 阶段）：

```sql
-- 设计候选：scripts/pg/bootstrap_app_role_permissions.sql（幂等，GRANT/ADP 可重复执行）
-- 执行身份：postgres superuser
-- 执行时机：alembic upgrade head 之后、应用启动之前
-- 语义：等价于 P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT §6/§7/§9 的手工步骤

GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;
GRANT USAGE ON SCHEMA public TO auto_wechat;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;

-- C3 顺序硬约束：broad DML GRANT 之后立即收敛 alembic_version 写权限
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;

-- 未来对象 ADP（creator=postgres）
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
```

**幂等性**：`GRANT` / `REVOKE` / `ALTER DEFAULT PRIVILEGES` 均幂等，重复执行无副作用。`GRANT ON ALL TABLES` 在表集合不变时结果稳定；alembic 新增表后重跑会补授权新表（符合 ADP 已覆盖的未来对象语义，但对 alembic upgrade 后新增的既有对象需显式 GRANT，ADP 只覆盖"新建"对象）。

**为何不能放进 `docker-entrypoint-initdb.d`**：init 阶段业务表不存在（alembic 未跑），`GRANT ON ALL TABLES` 命中 0 表。权限 bootstrap 必须是 post-alembic 独立步骤。

**是否合并实施**：本窗口只设计。是否把"init SQL owner 修改 + permission bootstrap 脚本"作为一次连贯实施，由独立审批决定（任务 §12）。

### 8.4 与既有手工状态的关系

当前 canonical dev PG 已手工执行过等价 SQL（VERIFIED）。本设计**不要求**重新 bootstrap 当前库——当前库 COMPLIANT。设计目标是**未来 clean bootstrap 可重复性**（任务 §17）。

---

## 9. Local / Staging / Production Impact

### 9.1 Local（本设计主体）

- 修改 `001_create_databases.sql`（1 行 owner）+ 新增 permission bootstrap 脚本 → fresh bootstrap 可重复。
- 不影响当前运行库（不 ALTER 当前 DB）。

### 9.2 Staging / Production

```text
STAGING    = CONFIG_VERIFIED / RUNTIME_UNKNOWN   （继续冻结）
PRODUCTION = CONFIG_VERIFIED / RUNTIME_UNKNOWN   （继续冻结）
```

- staging/prod **不使用** `001_create_databases.sql`（§5.2），改 init SQL **不影响** staging/prod。
- staging/prod 用单 superuser role 模型（`POSTGRES_USER=auto_wechat` 同时 owner 两库），与分离 contract **本就不同**，属 [OWNERSHIP_APPROVAL §12](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md) 登记的 **accepted residual risk**。
- 本窗口 **NO REMOTE WRITE**，只静态检查配置。
- **不得宣称** "staging/prod ownership fixed"。
- prod 若要落实分离 contract，需在 init-prod 之外补建非 superuser 应用 role + 授权脚本 + ownership 治理，属**独立部署审批**，不在本设计范围。

### 9.3 CI / test

未发现独立 CI/test compose 使用 `001_create_databases.sql`。CI 若依赖 dev compose postgres profile，则受益于本修复（fresh bootstrap 可重复）。无负面回归风险。

---

## 10. Application Role Grant Reproducibility Audit

### 10.1 审计问题

当 fresh cluster 重新创建后，当前 runtime grants 从哪里恢复？

### 10.2 审计结论

```text
FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP = OPEN   （本窗口新登记）
```

**证据**：
- 本窗口 `grep "ALTER DEFAULT PRIVILEGES"` 全 repo 非 `.md` 文件 = **0 命中**（[Grep 结果]）。
- `grep "GRANT SELECT|GRANT INSERT|REVOKE.*alembic_version"` 仅命中 4 份治理 `.md` 文档（[IMPLEMENTATION_REPORT/DESIGN/APPROVAL/OWNERSHIP_APPROVAL]），**无任何 `.sql` / `.sh` / `.py` 脚本**。
- `docker/postgres/` 全目录仅 3 个文件：`init/001_create_databases.sql`、`init-prod/010_create_rag_database.sh`、`init-staging/010_create_rag_database.sh`。三者均**不做** app role GRANT/ADP（001 只建 role+db；010 只 createdb）。

→ 当前授权模型**只存在于手工已执行数据库状态**（canonical dev PG），fresh bootstrap **不会自动重建** GRANT/ADP。

### 10.3 影响链

fresh bootstrap（不执行手工 runbook [5][6]）→ app role 0 grants → `/ready` 第 3 步 `SELECT version_num FROM alembic_version` → `permission denied for table alembic_version` → 503 → 应用 unhealthy。

### 10.4 修复方向

新增 §8.3 post-alembic permission bootstrap 脚本，使 GRANT/ADP 可重复执行。

### 10.5 准确登记

```text
Gap ① LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP         = OPEN（init SQL OWNER auto_wechat）
Gap ② FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP           = OPEN（GRANT/ADP 无脚本）
两者同时存在 → fresh bootstrap 不可重复
修复须作为一个连贯 fresh-bootstrap permission bootstrap（§8）
是否合并实施 → 独立审批决定（本窗口不实施）
```

---

## 11. Alembic Contract

### 11.1 Fresh bootstrap 结束后必须满足

```text
empty PG
  → database created with correct owner (postgres)         [Candidate A]
  → alembic upgrade head (以 postgres superuser)           [runbook/自动化]
  → permission bootstrap (GRANT/ADP/REVOKE)                [Gap ② 修复]
  → application role connects (auto_wechat)
  → /ready succeeds
```

### 11.2 schema authority

```text
PostgreSQL schema authority = Alembic   （继续冻结，不得 create_all）
```

依据：[init_db.py:28-35](scripts/init_db.py#L28-L35) PG 守卫 sys.exit(1)；[app/main.py:279-283](app/main.py#L279-L283) `ensure_runtime_schema` PG 下 `startup_skip_create_all`。

### 11.3 alembic_version Contract

fresh bootstrap 结束后：

```text
app role:
  alembic_version SELECT = allowed   （/ready 读 revision）
  INSERT / UPDATE / DELETE / TRUNCATE = denied   （C3 顺序硬约束：broad DML GRANT → REVOKE alembic_version 写）
```

若 permission bootstrap 设计包含 wide table grants，**继续保持** `broad DML grant → explicit alembic_version write revoke` 硬顺序（[IMPLEMENTATION_REPORT §7/§10](P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_REPORT.md)）。

---

## 12. Default Privilege Contract

### 12.1 fresh bootstrap 后必须重建

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
```

当前 local 冻结 creator = `postgres`（[OWNERSHIP_APPROVAL §6](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md)）。

### 12.2 权限矩阵

| 对象类型 | 授予 auto_wechat | 禁止授予 |
|---|---|---|
| Future tables | SELECT / INSERT / UPDATE / DELETE | **TRUNCATE** / REFERENCES / TRIGGER |
| Future sequences | USAGE / SELECT | UPDATE / setval |

### 12.3 ADP reproducibility

当前 2 条 ADP 是手工执行状态（VERIFIED）。fresh bootstrap 不会重建（§10）。permission bootstrap 脚本（§8.3）须包含 ADP 重建。

---

## 13. Fresh Bootstrap Test Environment

### 13.1 隔离要求

在**全新、隔离、可删除的 PostgreSQL environment** 中验证。**不得**使用当前 canonical dev PG 作为 fresh-bootstrap 测试对象（任务 §15/§17）。

### 13.2 候选方式

- 临时 docker compose project（独立 project name + 独立 volume + 独立端口，如 `25433`），复用 dev `init/` + 修改后 init SQL。
- 或临时 PG 容器 + 独立 data volume。
- 验证完成后 `docker compose down -v` 删除临时 volume。

### 13.3 验证目标链

```text
new empty PG data volume
  → normal project bootstrap path（dev compose postgres profile + 修改后 init SQL）
  → database auto_wechat created (owner=postgres)
  → alembic upgrade head
  → permission bootstrap 脚本执行
  → application role runtime privileges restored
  → /ready as application principal (HTTP 200)
```

---

## 14. FB-0 ~ FB-10 Acceptance

### FB-0 Isolation

```text
全新临时 PG（独立 project / volume / 端口）
不得删除 canonical local DB
不得 rename 当前库
不得复用 legacy backup
```

### FB-1 Database Owner

```text
database owner = postgres（migration/admin principal）
app role is database owner = false
```

### FB-2 Schema Owner / CREATE

```text
app role DATABASE CREATE = false
app role public schema CREATE = false
```

### FB-3 Alembic

```text
empty → head（0034）完整成功
alembic_version 表存在，revision = head
```

### FB-4 Application Role DML

以真实 application principal `auto_wechat`：

```text
CONNECT = PASS
required table DML（SELECT/INSERT/UPDATE/DELETE）= PASS
sequence / identity（USAGE + SELECT）= PASS
```

### FB-5 alembic_version

```text
SELECT = PASS
INSERT / UPDATE / DELETE / TRUNCATE = DENIED
revision 不变
```

### FB-6 DDL

```text
CREATE TABLE（app role）→ DENIED（permission denied for schema public）
```

### FB-7 TRUNCATE

```text
TRUNCATE（app role，安全 fixture 表）→ DENIED
```

### FB-8 Future Object Contract

migration principal `postgres` 创建新 table/sequence：

```text
app role DML（新 table）= PASS
app role TRUNCATE（新 table）= DENIED
app role sequence（USAGE + SELECT）= PASS
```

（由 ADP 自动授权；验证后由 postgres 清理临时对象。）

### FB-9 /ready

application principal `auto_wechat`：

```text
HTTP 200
backend = postgresql
database = auto_wechat
alembic head = current（0034）
```

### FB-10 Cleanup

```text
临时 cluster / volume 删除
canonical local PG 无变化（table_count=61 / head=0034 / owner=postgres 不变）
```

---

## 15. Rollback / Safety

### 15.1 设计阶段（本窗口）

- 本窗口**不修改任何文件**，无 rollback 需求。
- 本报告为 candidate design diff，交独立审批。

### 15.2 实施阶段（未来独立审批后）

- init SQL 修改：1 行 `OWNER auto_wechat` → `OWNER postgres`。回滚 = revert 该 1 行。不影响已有数据卷（init SQL 只在空 volume 执行）。
- permission bootstrap 脚本：新增文件，回滚 = 删除文件。GRANT/ADP/REVOKE 幂等，无破坏性。
- **不触碰**当前 canonical dev PG（不 ALTER/GRANT/REVOKE 当前库）。
- **不触碰** staging/prod（NO REMOTE WRITE）。
- 验证在隔离临时环境（FB-0），失败不影响 canonical 库。

### 15.3 当前 canonical DB 不应被重新修

当前 canonical dev PG 已 VERIFIED（PR-1B~PR-13）。本任务是 future clean bootstrap reproducibility，**严禁**重复对当前库执行 `ALTER DATABASE OWNER` / `GRANT` / `REVOKE` / `ADP`，除非独立审批发现 current 状态真实漂移（未发现）。

---

## 16. Explicit Non-goals

本窗口**不处理**：

1. `xg_douyin_ai_cs` least privilege / 9100 role ownership / RAG Query 0005 PG verification（任务 §18；9100 principal 较宽，另行登记 future governance gap）。
2. `Global Active None Audit`（任务 §19；独立执行）。
3. `Final PostgreSQL Concurrent Closure Gate`（任务 §19；独立执行）。
4. staging / production ownership 治理（§9；独立部署审批）。
5. RB-10 cleanup（NOT AUTHORIZED）。
6. DB-BL reopen / schema baseline 变更（0034 / 61 表不动）。
7. 0032 / 0033 / 0034 consumer PG verification（本设计不开始）。
8. M07 Core / consumer 代码变更。
9. `init-prod/010` / `init-staging/010` 修改（不改 prod/staging contract）。
10. compose / env 文件修改（不改 POSTGRES_USER / DATABASE_URL 默认值）。

### 16.1 9100 owner drift 说明（仅登记，不处理）

`001_create_databases.sql:23` 的 `CREATE DATABASE xg_douyin_ai_cs OWNER xg_douyin_ai_cs` 存在与 9100 分离 contract 类似的 drift 风险。但：

- 当前 9100 dev 走 SQLite（[docker-compose.dev.yml:147](docker-compose.dev.yml#L147) `RAG_DATABASE_URL=sqlite:////data/xg_douyin_ai_cs.db`），init SQL 建的 `xg_douyin_ai_cs` PG 库在 dev 不被运行时使用。
- 任务 §18 明确 9100 不属本 gap 主体。

→ **本设计保留 `001_create_databases.sql:23` 不变**，9100 owner drift 登记为 future governance gap，由 9100 RAG principal 治理任务另行处理。

---

## 17. Implementation File Scope

### 17.1 PROPOSED MODIFY（实施需独立审批，本窗口不执行）

| 文件 | 改动 | 行数 | 影响 |
|---|---|---|---|
| [docker/postgres/init/001_create_databases.sql](docker/postgres/init/001_create_databases.sql) | 第 20 行 `OWNER auto_wechat` → `OWNER postgres` | 1 行 | dev fresh bootstrap owner 修正 |

### 17.2 PROPOSED CREATE（实施需独立审批，本窗口不执行）

| 文件 | 内容 | 责任阶段 |
|---|---|---|
| `scripts/pg/bootstrap_app_role_permissions.sql`（设计候选路径）| §8.3 幂等 GRANT/ADP/REVOKE | post-alembic，应用启动前 |

> 是否创建该脚本、是否与 init SQL 修改合并实施，由独立审批决定（任务 §12）。

### 17.3 READ ONLY / DO NOT MODIFY

| 文件 / 目录 | 理由 |
|---|---|
| [docker-compose.yml](docker-compose.yml) / [docker-compose.staging.yml](docker-compose.staging.yml) / [docker-compose.dev.yml](docker-compose.dev.yml) | 不改 compose / POSTGRES_USER 默认值 / 端口 / 挂载 |
| [docker/postgres/init-prod/010_create_rag_database.sh](docker/postgres/init-prod/010_create_rag_database.sh) / [init-staging/010_create_rag_database.sh](docker/postgres/init-staging/010_create_rag_database.sh) | 不改 prod/staging contract（单 superuser role，accepted residual risk）|
| [migrations/postgres/auto_wechat/](migrations/postgres/auto_wechat/)（alembic.ini / env.py / versions/）| 不改 migration / schema baseline（0034 不动）|
| [app/main.py](app/main.py) / [app/routers/health.py](app/routers/health.py) / [app/db_readiness.py](app/db_readiness.py) / [scripts/init_db.py](scripts/init_db.py) | 不改应用 startup guard / readiness / init_db 守卫 |
| [app/database.py](app/database.py) / DATABASE_URL 配置 | 不改 runtime 连接配置 |
| 当前 canonical dev PG（运行库）| 已 VERIFIED，不重新修（§15.3）|
| `.env*` 文件 | 不改 env |
| M07 Core / consumer 代码 / RB-10 / DB-BL | 不碰 |

### 17.4 runbook / docs（受影响需同步，按 AI 文档自治维护）

实施窗口落地后需同步：
- 本设计报告状态（`DESIGN_READY_FOR_APPROVAL` → 实施审批后状态流转）。
- `CLAUDE.md` / `05_PROJECT_CONTEXT.md` 中 `LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP` 状态（OPEN → 实施验证后 CLOSED）。
- 若新增 permission bootstrap 脚本，需在 runbook 文档化其执行时机（post-alembic）。

---

## 18. Verdict

```text
VERDICT: DESIGN_READY_FOR_APPROVAL
```

### 18.1 设计结论

1. **Gap ①（owner drift）**：`001_create_databases.sql:20` 的 `OWNER auto_wechat` 与冻结的分离 contract 冲突。修复 = Candidate A（`OWNER postgres`，1 行），仅 dev，不影响 staging/prod。
2. **Gap ②（grant reproducibility）**：所有 GRANT/ADP/REVOKE 仅存在于手工执行的 canonical DB 状态，无任何脚本。fresh bootstrap 后 app role 0 grants → `/ready` 失败。修复 = 新增 post-alembic permission bootstrap 脚本（§8.3）。
3. **双重 gap 必须一起设计**（任务 §11）：只修 owner 仍非可重复 bootstrap。
4. **当前 canonical dev PG 不需重新修**（已 VERIFIED）；本设计目标是 future clean bootstrap reproducibility。
5. **staging/prod 边界冻结**：NO REMOTE WRITE，单 superuser role = accepted residual risk，不得宣称 fixed。
6. **验证必须在隔离临时 PG**（FB-0~FB-10），不得用 canonical 库。

### 18.2 不实施

本窗口为设计/审计窗口：

```text
DO NOT COMMIT
DO NOT MODIFY init SQL
DO NOT MODIFY compose
DO NOT MODIFY permissions
DO NOT CREATE migration
DO NOT MODIFY 当前 DB
```

### 18.3 P1 状态（继续冻结）

```text
ACTIVE CONSUMER PG VERIFICATION = COMPLETE
COMPUTE-IDEMPOTENCY-001         = OPEN
TECHNICAL_CLOSURE                = PENDING

剩余 blockers:
  A′  Bootstrap Owner Drift（本设计）          → DESIGN_READY_FOR_APPROVAL
  B   RAG Query 0005 PG（Docker 恢复后独立补）
  C   Global Active None Audit
  D   Final PG Concurrent Closure Gate

RB-10 = NOT AUTHORIZED
```

### 18.4 下一步

```text
本设计报告交独立审批窗口。
审批通过后，由独立实施窗口在 LOCAL DEVELOPMENT ONLY 范围内：
  1. 修改 001_create_databases.sql（1 行 owner）
  2. （审批决定）新增 post-alembic permission bootstrap 脚本
  3. 在隔离临时 PG 执行 FB-0~FB-10 验收
  4. 验证通过后同步文档状态 + commit（中文 commit message）
不得借实施窗口顺手处理 9100 / staging-prod / Global None / Concurrent Closure（§16）。
```

---

## 审批窗口停止点

```text
P1-PG-BOOTSTRAP-OWNER-DRIFT-1:
DESIGN_READY_FOR_APPROVAL
  Gap ① LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = OPEN（Candidate A 设计）
  Gap ② FRESH_BOOTSTRAP_APPLICATION_ROLE_GRANT_GAP = OPEN（permission bootstrap 脚本设计）
  双 gap 须作为一个连贯 fresh-bootstrap permission bootstrap
  合并实施由独立审批决定
本窗口不实施修改，停止。
```
