# P1 — PostgreSQL Application Role Permission Contract 设计/审计报告

> 任务：`P1-PG-APP-ROLE-1 — auto_wechat PostgreSQL Application Role Permission Contract 设计/审计`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL CLOSURE` 的 PostgreSQL runtime prerequisite
> 阶段：`DESIGN / AUDIT ONLY`
> 日期：2026-08-10
> 窗口：P1 PostgreSQL Application Role Permission Contract 设计/审计窗口
> Source of Truth：真实 PG runtime 证据（只读 catalog inspection + 应用角色实测） > 冻结文档 > 推测

---

## 0. 前置边界声明

- 本报告是**设计与审计**，不实施任何 GRANT / REVOKE / ALTER ROLE / ALTER DEFAULT PRIVILEGES / 改 owner / 改 DATABASE_URL / 改迁移 / 改 M07 Core。
- **不重新打开 DB-BL**。DB-BL 已冻结：`DB-BL = REPAIR_VERIFIED / COMPLETE`、`SCHEMA_BASELINE_MISMATCH = REMEDIATED`、`AUTO_WECHAT_DEV_PG = CANONICAL_ALEMBIC_BASELINE@0034`、checkpoint `cc9b11e`。Application permission gap 是**独立 runtime permission gap**，不是 DB-BL repair 失败。
- 审计方式：仓库静态审计（compose / env 模板 / init 脚本 / alembic env / readiness 实现 / database 工厂）+ 只读本地 PG catalog inspection + 以 `auto_wechat` 应用角色实际连接验证。

---

## 1. Current Principal Reality（Q1）

### 1.1 Development（canonical dev PG）

**CURRENT CONFIG FACT：**

9000 应用默认 `DATABASE_URL = sqlite:///./data/auto_wechat.db`（[app/config.py:166](app/config.py#L166)）。`docker-compose.dev.yml` 把 9000 / 9100 全部接到 SQLite，**不接 PG**（[docker-compose.dev.yml:92](docker-compose.dev.yml#L92)、[docker-compose.dev.yml:206](docker-compose.dev.yml#L206)）。dev 的 `postgres` service 是独立 profile（`profiles: ["postgres"]`），容器用 `POSTGRES_USER:-postgres`（[docker-compose.dev.yml:36-38](docker-compose.dev.yml#L36-L38)），但应用未指向它。

→ **dev 应用实际运行 principal = SQLite（无 PG principal）**。

canonical dev PG（DB-BL 工作对象，`auto-wechat-postgres-dev` @ 5432）的 bootstrap 链：
- `docker/postgres/init/001_create_databases.sql` 创建 role `auto_wechat`（password `change_me`）+ database `auto_wechat OWNER auto_wechat`（[001_create_databases.sql:6-21](docker/postgres/init/001_create_databases.sql#L6-L21)）。
- Alembic `upgrade head` 由 `postgres` superuser 执行 → 61 表全部 owner=postgres（[migrations/postgres/auto_wechat/env.py:27-35](migrations/postgres/auto_wechat/env.py#L27-L35) 读 `DATABASE_URL`，迁移代码无任何权限 DDL）。

**只读 catalog inspection 证据（本报告独立核验，与 DB-BL-2D §9 一致）：**

```text
role auto_wechat        : EXISTS, LOGIN=true, SUPERUSER=false
table grants (auto_wechat)    = 0
sequence grants (auto_wechat) = 0
pg_default_acl (auto_wechat) = 0
public schema 表 owner 分布    = postgres=61
douyin_leads.relacl            = NULL
database auto_wechat owner     = auto_wechat
database auto_wechat datacl    = NULL
public schema owner            = pg_database_owner
public schema nspacl           = {pg_database_owner=UC/pg_database_owner, =U/pg_database_owner}
alembic_version                = 0034
physical tables                = 61
```

**应用角色实测（以 `auto_wechat` 角色直连，纯只读 SELECT + 一次 INSERT 拒绝验证）：**

```text
CONNECT  (SELECT current_database())   → OK   (auto_wechat@auto_wechat)   ← 经 PUBLIC 默认 CONNECT
SELECT version_num FROM alembic_version → ERROR: permission denied for table alembic_version
SELECT 1 FROM douyin_leads LIMIT 1      → ERROR: permission denied for table douyin_leads
INSERT INTO alembic_version(...)        → ERROR: permission denied for table alembic_version
```

→ **`auto_wechat` 应用角色当前能 CONNECT，但对任何业务表与 alembic_version 均无 SELECT/INSERT 权限。** 若 `/ready` 或任何 consumer 测试以该角色运行，必在 `alembic_revision` 检查步失败（permission denied）。当前 /ready PASS 仅因以 `postgres` superuser 运行（DB-BL-2D §14）。

**RECOMMENDED TARGET：** dev PG 应让 `auto_wechat` 应用角色携带正确最小权限，使 `/ready` 与 consumer PG verification 以**真实 runtime principal** 运行，而非 superuser。

### 1.2 Staging

**静态配置事实（不连接 staging）：**

`docker-compose.staging.yml` 覆盖 9000 `DATABASE_URL = postgresql+psycopg://${PG_USER:-auto_wechat_staging}:${PG_PASSWORD}@postgres:5432/${PG_DB:-auto_wechat_staging}`（[docker-compose.staging.yml:51](docker-compose.staging.yml#L51)）。PG 容器 `POSTGRES_USER` 来自 base `docker-compose.yml` 的 `${PG_USER:-auto_wechat}`（[docker-compose.yml:14](docker-compose.yml#L14)），staging 透过 `.env.staging.local` 设 `PG_USER=auto_wechat_staging`（staging override 注释 line 17-19 约定）。postgres:16-alpine entrypoint 使 `POSTGRES_USER` 成为 **bootstrap SUPERUSER**，并 `POSTGRES_DB=auto_wechat_staging`。

→ **staging runtime principal = `auto_wechat_staging` = bootstrap SUPERUSER。Model A，superuser。**
→ 实际部署 principal 名取决于 `.env.staging.local`（不在仓库）；contract 模式（单 superuser role）静态可知。

staging 第二库 `xg_douyin_ai_cs_staging` 由 `init-staging/010` 以 `createdb --owner "$DB_USER"` 创建，`DB_USER=${POSTGRES_USER:-auto_wechat_staging}`（[init-staging/010_create_rag_database.sh:18-24](docker/postgres/init-staging/010_create_rag_database.sh#L18-L24)）。9100 `RAG_DATABASE_URL` 同样用 `${PG_USER:-auto_wechat_staging}`（[docker-compose.staging.yml:66](docker-compose.staging.yml#L66)）。→ 9100 也是同一 superuser role。

### 1.3 Production

**静态配置事实（不连接 production）：**

`docker-compose.yml`（唯一生产主入口）：`POSTGRES_USER: ${PG_USER:-auto_wechat}`、`POSTGRES_DB: ${PG_DB:-auto_wechat}`（[docker-compose.yml:14-16](docker-compose.yml#L14-L16)）。9000 `DATABASE_URL = postgresql+psycopg://${PG_USER:-auto_wechat}:${PG_PASSWORD}@postgres:5432/${PG_DB:-auto_wechat}`（[docker-compose.yml:39](docker-compose.yml#L39)）。9100 `RAG_DATABASE_URL` 用同一 `${PG_USER:-auto_wechat}` 连 `xg_douyin_ai_cs`（[docker-compose.yml:72](docker-compose.yml#L72)）。`.env.production.example` 中 `PG_USER=<请填写生产PostgreSQL用户名>`（[.env.production.example:72](.env.production.example#L72)），真实值在 `.env.production.local`（不入库）。

postgres:16-alpine entrypoint 使 `POSTGRES_USER` 成为 **bootstrap SUPERUSER**。`init-prod/010` 注释明确写（[init-prod/010_create_rag_database.sh:7-8](docker/postgres/init-prod/010_create_rag_database.sh#L7-L8)）：

> 生产策略：单应用 role（`${POSTGRES_USER}`，即 compose POSTGRES_USER）同时 owner 两个 database，不为 9100 单独建 role（与 dev 的 001_create_databases.sql 独立 role 策略不同）。

→ **production runtime principal = `PG_USER`（默认 `auto_wechat`）= bootstrap SUPERUSER。Model A，superuser。**
→ 实际 principal 名 = UNKNOWN（在 `.env.production.local`）；contract 模式（单 superuser role 同时做 DDL+DML）静态可知且被 init-prod 注释显式确认。

### 1.4 现状总表

| 环境 | 应用 runtime principal | 是否 superuser | schema 对象 owner | 应用角色表权限 | 证据等级 |
|---|---|---|---|---|---|
| Dev（SQLite）| 无 PG | — | — | — | KNOWN（config） |
| Dev（canonical PG）| `auto_wechat` | **否** | postgres | **0（gap）** | **LOCAL_PG_RUNTIME_VERIFIED**（本报告实测）|
| Staging | `auto_wechat_staging` | 是（配置模板）| = 同一 superuser | 隐式全权（superuser 绕过 ACL）| **CONFIG_VERIFIED / RUNTIME_UNKNOWN** |
| Production | `PG_USER`（默认 `auto_wechat`）| 是（配置模板）| = 同一 superuser | 隐式全权（superuser 绕过 ACL）| **CONFIG_VERIFIED / RUNTIME_UNKNOWN** |

> **C4 Correction（证据纪律冻结）：** 正式冻结证据等级词汇——Dev canonical PG = `LOCAL_PG_RUNTIME_VERIFIED`（已以应用角色真实连接实测）；Staging / Production = `CONFIG_VERIFIED`（仅 compose/env 模板推导），实际部署 role attribute = `RUNTIME_UNKNOWN`（`PG_USER` 在 `.env.production.local` / `.env.staging.local`，不入库）。**不得因配置模板写 SUPERUSER 就宣称 staging/prod 当前一定以 superuser 运行**，也不得据此自动应用 local GRANT 设计。

---

## 2. Target Principal Model（Q2）

### 2.1 现状判定

dev init SQL 与 prod init-prod 采用**不同**策略，但两者都不是真正的 Model B（migration principal 与 application principal 分离）：

- **prod**：单 role（POSTGRES_USER superuser）既跑 Alembic 又做业务 DML → **Model A，且该 role 是 superuser**。
- **dev**：`001_create_databases.sql` 为 9000 / 9100 各建一个独立 role（auto_wechat / xg_douyin_ai_cs），每个 role 是对应 database 的 owner；但 Alembic 由 `postgres` superuser 运行 → **dev 的 role 与 migration principal 不一致，却不是有意设计**，而是 init SQL 与 alembic 运行身份脱节的结果，直接导致当前 gap（role 存在但无表权限）。

### 2.2 推荐：Runtime Principal Model — SEPARATED MIGRATION / APPLICATION RESPONSIBILITY（单应用角色，最小权限，非 superuser）+ Migration Authority 独立

> **C1 Correction（审批冻结命名）：** 废止易与 DB-BL `Schema Authority Model A` 混淆的 `Model A′` 命名。正式冻结为：
> `Runtime Principal Model: SEPARATED MIGRATION / APPLICATION RESPONSIBILITY`。后续文档须统一采用该命名。下方比较表中 `Model A`（现状 prod 单 superuser）与 `Model B`（完全分离）仅为比较轴标签，保留。

| 维度 | Model A（现状 prod）| Model B（完全分离）| **Runtime Principal Model（推荐）** |
|---|---|---|---|
| least privilege | ✗（superuser）| ✓ | ✓（应用角色非 superuser，仅 DML）|
| migration ownership | 同 role | 独立 migration admin role | migration principal = 运行 alembic 的 bootstrap superuser（postgres/PG_USER）|
| application blast radius | 大（superuser = SQL 注入即可改 role/跨库）| 小 | 小（应用角色无 DDL，无跨库，无 role 管理）|
| operational complexity | 低 | 高（多 role + 多凭据 + rotation）| 低（每库一个应用 role，复用现有 init 模式）|
| current deployment 兼容 | ✓ | ✗（prod 只建一个 role）| 部分（dev 可直接落地；prod 需补第二个非 superuser 应用 role 或接受残余风险）|
| development simplicity | ✓ | ✗ | ✓ |
| future migrations | 同 role 自动有权限 | 需 ADP | 需 ADP（见 §6）|

**结论：正式目标采用 Runtime Principal Model（SEPARATED MIGRATION / APPLICATION RESPONSIBILITY）**——每个 database 一个 application principal（非 superuser、最小权限 DML），schema evolution 仍由 Alembic 代码权威 + migration principal（bootstrap superuser）执行。对象 owner 留在 migration principal，application role 只拿 GRANT。

理由：项目为单团队单实例规模，Model B 的多 role IAM（Vault / rotation / external IAM）属过度建设（YAGNI，§13）；但 prod 当前让应用以 superuser 运行是安全反模式（应用 SQL 注入 = 全库 + 跨库 + role 管理沦陷），不可作为正式 contract。Runtime Principal Model 是 lazy-correct 折中：保留单应用角色的低复杂度，去掉 superuser 放大效应，且与 dev 现有 init SQL 的"每库一 role"结构兼容（只需补 GRANT + ADP，不改 init 角色拓扑）。

**重要澄清（对应 Q4）：** "Alembic 是唯一 schema evolution 权威" 指的是**迁移代码权威**（DDL 只能由 Alembic 迁移文件产出，禁止 create_all / 手改）；migration principal 是**执行 `alembic upgrade head` 的身份**（bootstrap superuser，本仓库即 `postgres` dev / `PG_USER` prod）。两者不是一句：代码权威 = Alembic 迁移文件；执行身份 = migration principal（superuser）。application principal ≠ migration principal，因此 application principal 不 owner schema 对象、不持 DDL。

---

## 3. Application Minimum Privilege Contract（Q3）

针对 `auto_wechat` 应用角色在 `auto_wechat` database（9000 主库）：

### 3.1 Database 级

- `CONNECT`：必需（应用连接）。当前经 PUBLIC 默认获得，但应显式 `GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;`。
- 不需要 `CREATE`（database 级创建 schema）、不需要 `TEMPORARY` 之外的其他 db 级权限。

### 3.2 Schema 级

- `USAGE ON SCHEMA public`：必需（访问对象的前提）。
- `CREATE ON SCHEMA public`：**禁止**。Application principal 不负责 schema evolution，不得拥有建表/建索引能力。`ponytail:` 当前 dev 因 `auto_wechat` 是 DB owner → 隐式 `pg_database_owner` 成员 → 自动获得 public schema 的 `UC`（含 CREATE），这是一个隐式 DDL 泄漏点，见 §7 处置。

### 3.3 Tables（DML）

- `SELECT, INSERT, UPDATE, DELETE`：四类全部需要——9000 业务覆盖线索读写、销售回写、outbox 幂等消费、日报生成、M05 分析、Preview、RAG ingest 等，均为标准 CRUD。
- `TRUNCATE`：不需要。
- `REFERENCES, TRIGGER`：不需要（建外键是 DDL，归 migration principal；运行时插入带 FK 的行只需 INSERT，不需 REFERENCES）。
- 不机械 `GRANT ALL`；只授 DML 四类。

### 3.4 Sequences

- `USAGE, SELECT`：必需。SERIAL/identity 列 `nextval` 需 `USAGE`，`currval` 需 `SELECT`。
- `UPDATE`：不需要（`setval` 是迁移/运维行为，归 migration principal）。

### 3.5 alembic_version

- `SELECT`：必需（`/ready` 读 revision，[db_readiness.py:169](app/db_readiness.py#L169)）。
- `INSERT, UPDATE, DELETE`：**禁止**。revision bookkeeping 是 Alembic 框架在 `alembic upgrade` 时维护的，由 migration principal 执行；application principal 不得改 revision。`ponytail:` 这是唯一需要从"全表 DML"中显式排除写权限的对象，见 §5 落地方式。**C3 硬收敛：** 宽泛 DML GRANT 后必须紧跟 `REVOKE INSERT, UPDATE, DELETE ON alembic_version`（GRANT→REVOKE 顺序硬约束），且若 `alembic_version` 未来被 DROP/recreate 必须重新收敛，见 §6.4。

---

## 4. DDL Capability Boundary（Q4）

正式冻结：application role **禁止** `CREATE TABLE / ALTER TABLE / DROP TABLE / CREATE INDEX / TRUNCATE / CREATE SCHEMA / DROP SCHEMA`。

依据：Schema Authority 已冻结为 `Alembic = sole PG schema evolution authority`（迁移代码权威），migration principal = 执行 Alembic 的 bootstrap superuser，对象 owner 留在 migration principal。application role 不 owner schema 对象 → 自然无 DDL；再叠加 schema `CREATE` 收回（§3.2 / §7）→ 双重保证。

**Alembic authority ≠ migration principal**（见 §2.2 澄清）：前者是迁移代码权威，后者是执行身份。本设计不要求"独立命名的 migration admin role"（那是 Model B 的过度建设），只要求 application principal 与 migration principal 不是同一身份，且 application principal 不持 DDL/不 owner 对象。

负向验证（§17、PR-9）：application role 尝试 `CREATE TABLE` 应 `permission denied`，证明"不只是能用，而且没拿到不该有的 schema authority"。

---

## 5. Existing Object Grant Contract（Q6）

对 canonical@0034 现有 61 表（60 业务 + alembic_version）的一次性 bootstrap（由 migration principal / superuser 执行，**当前阶段不执行**）：

```sql
-- 1. 库与 schema 基础访问
GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;
GRANT USAGE ON SCHEMA public TO auto_wechat;

-- 2. 业务表 DML（含 alembic_version 的 SELECT）
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;

-- 3. 序列
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;

-- 4. alembic_version 收回写权限，只留 SELECT（application 不得改 revision）
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;
```

说明：
- `GRANT ... ON ALL TABLES` 是一次性覆盖现有对象；`REVOKE` 只对 `alembic_version` 一个对象收写，保留 SELECT（`/ready` 需读 revision）。`ponytail:` 这是覆盖 + 一处收回的最短差，比枚举 60 张业务表 + 单独 SELECT alembic_version 更短且不易漏表。
- 幂等：`GRANT` / `REVOKE` 幂等，重复执行安全。
- 必须由 migration principal（superuser）执行——对象 owner 是 `postgres`，只有 owner 或 superuser 能 GRANT。

此 bootstrap **仅解决已有对象**；未来对象见 §6。两者必须同时具备，否则下一条 migration（0035+）新建的表会再次让 application role 失权。

---

## 6. Future Object / Default Privilege Contract（Q5）

当前 `pg_default_acl = empty`，因此"现在 GRANT ALL 60 表"不能覆盖未来 0035+ 新表。必须设计未来 contract。

### 6.1 方案比较

| 方案 | 优点 | 风险 |
|---|---|---|
| A. 每条 migration 内显式 GRANT | 显式 | 极易遗漏（每个 migration 作者都要记得）→ 新表静默失权；污染迁移代码（迁移应只管 schema DDL，不管授权策略）|
| **B. ALTER DEFAULT PRIVILEGES** | 自动覆盖未来对象；一次设置 | creator-role-specific，必须指定 `FOR ROLE <migration_principal>` |
| C. 部署后统一同步脚本 | 解耦 | 需每次 migration 后人工/CI 触发，漏触发则失权 |
| D. 仅 bootstrap + ADP（B 的补充）| 最小 | 同 B |

### 6.2 推荐：Option B + §5 一次性 bootstrap

`ALTER DEFAULT PRIVILEGES` **必须**显式三要素：`FOR ROLE <migration_principal>` + `IN SCHEMA public` + 对象类型（TABLES / SEQUENCES）。

```sql
-- migration principal 在 public schema 创建的未来表，自动授权 application role DML
ALTER DEFAULT PRIVILEGES
  FOR ROLE <migration_principal>      -- dev=postgres；prod=PG_USER（见 §6.3 注意）
  IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;

ALTER DEFAULT PRIVILEGES
  FOR ROLE <migration_principal>
  IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
```

### 6.3 关键注意：creator-role-specific

- ADP 只对**指定 FOR ROLE 之后由该 role 创建的对象**生效。dev：alembic 以 `postgres` 运行 → `FOR ROLE postgres`。prod：alembic 以 `PG_USER` 运行 → `FOR ROLE <PG_USER>`。
- **若 migration principal 是 superuser**：superuser 创建的对象 owner = 该 superuser 用户名，ADP `FOR ROLE <该 superuser 名>` 仍生效（ADP 按 creator 的 OID 匹配，superuser 不豁免 ADP 应用）。但若不同 migration 用不同 superuser 名创建对象，需对每个 creator role 各设一份 ADP。
- dev 当前唯一 creator = `postgres`，一份 ADP 即可覆盖未来。prod 需确认 `PG_USER` 实际名后对齐（属部署侧 runbook，不在本设计执行范围）。
- ADP 不溯及既往（只管设置后新建的对象），故 §5 的一次性 bootstrap 不可省。

### 6.4 alembic_version 的未来处置（C3 硬收敛）

alembic_version 由 Alembic 框架在首次 upgrade 自动创建（DB-BL-2D §12），creator = migration principal。若 §6.2 的 ADP 生效，未来重建 alembic_version 时 application role 会自动拿到 DML——这违反 §3.5（application 不得改 revision）。

> **C3 Correction（硬收敛，从"接受残余"升级为 runbook 硬约束）：**
> 1. **existing-table 宽泛 DML 授权后，`alembic_version` MUST be explicitly reduced to SELECT-only。** 即 §5 步骤 4 的 `REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;` 是 GRANT 之后的**强制顺序硬约束**，不得跳过（审批 §6 顺序硬约束）。
> 2. **若未来 `alembic_version` 被 DROP/recreate，SELECT-only hardening MUST be reapplied.** 不得依赖当前对象永久存在——重建后的 `alembic_version` 会经 §6.2 ADP 自动拿到 DML，必须在重建后立即重跑 §5 步骤 4 REVOKE。
>
> 不为该低频异常建立复杂 trigger 或权限平台（YAGNI），但"重建后必须重新收敛"是 implementation/部署 runbook 的硬约束，不是"可选提醒"。


---

## 7. Role / Grant Provisioning Ownership + Role Ownership Contract（Q7、Q12）

### 7.1 对象 owner 处置

当前：61 表 owner = `postgres`（migration principal）✓；database owner = `auto_wechat`（应用角色）✗（导致隐式 `pg_database_owner` → public schema `UC` 含 CREATE 的 DDL 泄漏）。

**推荐：Keep（迁移对象 owner 留 migration principal）+ 将 database ownership 迁移给 migration principal。**

> **所有权处置已由独立审批冻结（2026-08-10）：** 见 [P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md)。原"两条路径任一均可"的判断在现象层（是否消除当前 CREATE 泄漏）成立，但在语义层不成立——database ownership 是不可被 `REVOKE` 移除的持久行政能力（owner 可单方面恢复被收回的权限，且携带 ALTER/DROP DATABASE 等 ownership-level control）。故：

- **路径 1（保留 database owner + REVOKE CREATE）= REJECTED。** `auto_wechat` 的 public CREATE 经 `pg_database_owner` 隐式成员 → schema ownership 派生，nspacl 无 grantee=`auto_wechat` 条目，`REVOKE CREATE` 无可移除对象；且 owner 可自行 GRANT 恢复，不构成 principal separation。
- **路径 2（`ALTER DATABASE auto_wechat OWNER TO postgres`）= APPROVED（唯一推荐）。** application role 不再是 `pg_database_owner` 成员 → 自动失去 public schema CREATE 与 database 级行政能力；然后 §5 显式 `GRANT USAGE ON SCHEMA public`。

**不推荐**：把表 owner 转给 application role 以减少 GRANT 复杂度。理由：application role owner 对象即可 ALTER/DROP（DDL），直接破坏 §4 DDL 边界；且违背"application principal ≠ migration principal"。减少 GRANT 的收益不抵 DDL 泄漏风险。

> 为什么 application role 不应该成为 schema owner？因为它在运行时被业务请求路径持有，是 SQL 注入等攻击的最外层暴露面；若它同时 owner schema，一次注入即可 `DROP TABLE` / `ALTER` 破坏 schema，放大爆炸半径。owner 留 migration principal（仅迁移时短时持有）→ 运行时应用角色无 DDL → 注入最多影响 DML 行数据（可备份恢复），不触及 schema 结构与跨库。

### 7.2 Provisioning Ownership（谁建 role / 谁授权）

明确区分两件事：**ROLE CREATION**（cluster 级）vs **OBJECT GRANT POLICY**（database 级）。

| 职责 | 归属 | 理由 |
|---|---|---|
| ROLE CREATION（CREATE ROLE / 密码）| Docker/PostgreSQL bootstrap（entrypoint + init 脚本），**不进 Alembic** | role 是 cluster 级对象，跨 database；密码绝不能写进迁移历史（迁移文件入库，密码入库 = 泄漏）|
| OBJECT GRANT + ADP | 部署/bootstrap 脚本（post-alembic），**不进 Alembic 迁移文件** | 授权是部署关注点（随环境/角色名变化），写进迁移会污染迁移链且不可逆；GRANT/ADP 本身幂等，适合脚本 |
| SCHEMA DDL（建表/改表）| **Alembic 迁移文件**（唯一）| schema evolution 代码权威 |

落地方式（设计，不实施）：
- dev：`docker/postgres/init/001_create_databases.sql` 已负责 role + database 创建（保留）；新增一个**幂等授权脚本**（如 `scripts/pg_grant_app_role.sh`，读 `DATABASE_URL` / 角色），在 `alembic upgrade head` 之后执行 bootstrap GRANT + ADP。可同时挂进 `docker/postgres/init/` 作为 `002_grant_app_role.sql`（仅空卷首次起效，覆盖不了已有卷的 alembic 后授权，故仍需脚本侧）。
- prod/staging：复用现有 `scripts/production_pg_ensure_databases.sh` 模式，加一个 `--grant` 路径或独立 `production_pg_grant_app_role.sh`，在 cutover runbook "alembic upgrade head 之后、/ready 验证之前"执行。密码从 `.env.production.local` 读，不写脚本。

**Manual runbook 可接受**：prod 首次 cutover 由操作员执行一次授权脚本（幂等），属正常部署步骤；不要求自动化 CI 授权（YAGNI，§13）。

---

## 8. Readiness Contract（Q8）

### 8.1 `/ready` 实际权限需求（[app/db_readiness.py:161-223](app/db_readiness.py#L161-L223)）

| 检查步 | SQL | 所需权限 |
|---|---|---|
| db_connect | `SELECT 1`、`SELECT current_database()` | CONNECT |
| alembic_revision | `SELECT version_num FROM alembic_version` | SELECT on alembic_version |
| critical_tables | `SELECT 1 FROM "douyin_leads" LIMIT 1`、`SELECT 1 FROM "sales_staff" LIMIT 1` | SELECT on 关键业务表 |
| database_name | `current_database()` 返回值比对 | CONNECT（同 db_connect 连接）|

→ 全部是只读 SELECT。这些是 **legitimate application permission need**（应用读自身 schema revision + 关键表存在性），不是 readiness implementation bug。

### 8.2 当前应用角色实测

本报告以 `auto_wechat` 角色实测：`SELECT version_num FROM alembic_version` → `permission denied`（§1.1）。即若 `/ready` 以应用角色运行，当前会落入 `ERROR_DB_CONNECT`（同一 try 块内抛异常，[db_readiness.py:166-174](app/db_readiness.py#L166-L174)）→ 503。当前 /ready PASS 是 readiness implementation bug 吗？**不是**——是 application 角色缺 SELECT 权限（legitimate need 未满足）。修复方向是 §5 GRANT SELECT，不是放宽 /ready。

### 8.3 实施后重新验证

应用角色 implementation 完成后，必须以**应用角色 DATABASE_URL**（非 superuser）重新跑 `/ready`，证明：

- CONNECT ✓
- alembic_version SELECT ✓（revision=head=0034）
- 关键表 SELECT ✓
- database_name ✓

若 /ready 需要应用不该有的权限，区分 bug vs legitimate need；不得为过 /ready 盲目扩大 GRANT。当前四步均为 legitimate，无需扩大。

---

## 9. Consumer Verification Principal（Q9）

决定 0032 / 0033 / 0034 后续 PG verification 使用 **Application Role（`auto_wechat`）**。

理由：consumer verification 的目的是证明"consumer 不仅在 PG schema 上工作，而且以实际 runtime 权限工作"。若用 superuser 跑 consumer 测试，只能证明 schema 可用，不能证明应用角色路径可用——而 §1.1 已实测应用角色当前连 SELECT 都失败。用 superuser 静默完成然后宣称 application-role 路径已验证，是假阳性。

**前提**：必须先解决 APPLICATION_ROLE_PERMISSION_GAP（§5 + §6 落地），让 application role 拿到合法 DML，否则 consumer 测试会因 permission denied 污染结论。

**次选（若产品真实 runtime 明确使用 superuser）**：若未来审批确认 prod runtime 长期以 superuser 运行（即接受 §14 残余风险不建第二 role），则 consumer 可用 superuser，但必须在报告显式标注"以 superuser 验证，未覆盖 least-privilege application role 路径"，不得标 `E2E_VERIFIED_FIXED`。

---

## 10. Migration Verification Principal（Q10）

区分两类 contract：

| Contract | Principal | 用途 | 权限要求 |
|---|---|---|---|
| `MIGRATION_TEST_PRINCIPAL` | migration principal（superuser / postgres / PG_USER）| Alembic upgrade/downgrade 测试、schema DDL 验证 | DDL（CREATE/ALTER/DROP），owner 对象 |
| `APPLICATION_TEST_PRINCIPAL` | `auto_wechat`（application role）| consumer 行为验证、/ready、runtime DML | DML（SELECT/INSERT/UPDATE/DELETE），无 DDL |

Alembic migration verification 合法使用 migration principal（需 DDL）。Consumer 行为验证必须使用 application principal。当前 dev 两者混用 postgres superuser → 混淆了 schema 验证与 runtime 权限验证，是 gap 的成因之一。

---

## 11. Implementation Plan（仅设计，不实施）

```text
PR-0  target environment = LOCAL DEV ONLY（auto-wechat-postgres-dev @5432，auto_wechat 库）
PR-1  intended application principal verified   → role auto_wechat EXISTS, LOGIN, NON-superuser（§1.1 已核验）
PR-2  current privileges captured                → snapshot: 0 table/seq grants, 0 default_acl, relacl=NULL（§1.1 已核验）
PR-3  minimum privilege grants applied          → §5 bootstrap（GRANT CONNECT/USAGE/DML + REVOKE alembic_version 写）
PR-4  future-table/default privilege contract   → §6 ADP（FOR ROLE postgres IN SCHEMA public）
PR-5  no unintended DDL/superuser privilege     → §7 CREATE on public 收回；application role 非 superuser
PR-6  application-role /ready PASS             → 以 auto_wechat DATABASE_URL 跑 /ready，4 步全 pass
PR-7  representative read/write transaction PASS → §17 受控 CRUD（rollback 或隔离 fixture）
PR-8  sequence/identity insert PASS             → 对含 SERIAL/identity 的表 INSERT 验证 nextval
PR-9  unauthorized DDL negative test PASS       → application role CREATE TABLE → permission denied
PR-10 privilege snapshot documented             → grants/seq/default_acl/relacl 再 snapshot，对比 PR-2
PR-11 alembic_version write negative PASS       → application role UPDATE alembic_version ... WHERE FALSE → permission denied（C3 硬收敛验证 gate，从 §5 提升为独立 gate）
PR-12 TRUNCATE negative PASS                    → application role TRUNCATE 业务表 → permission denied（C2 新增 gate）
```

编号可与任务§十六候选对齐微调。当前阶段 `NOT STARTED / NOT AUTHORIZED`。

---

## 12. PR-* Verification Gates

| Gate | 验证内容 | 通过判据 | 证据 |
|---|---|---|---|
| PR-0 | 环境 | LOCAL DEV ONLY，非 prod/staging | docker inspect + DB-BL-2D 环境身份 |
| PR-1 | 应用角色存在性 | EXISTS / LOGIN / NON-superuser | `pg_roles` 只读 |
| PR-2 | 实施前权限快照 | 0 grants / 0 ADP / relacl NULL | `information_schema.role_table_grants`、`pg_default_acl`、`pg_class.relacl` |
| PR-3 | 最小权限落地 | DML on 60 业务表 + SELECT on alembic_version + alembic_version 无写 | `has_table_privilege()` / `has_sequence_privilege()` |
| PR-4 | 未来对象 policy | ADP 存在且 FOR ROLE 正确 | `pg_default_acl` non-zero，`pg_get_userbyid(defaclrole)`=postgres |
| PR-5 | 无意外 DDL/superuser | application role 无 CREATE on public；非 superuser | `has_schema_privilege('public','CREATE')`=false；`rolsuper`=false |
| PR-6 | /ready 以应用角色 PASS | HTTP 200，4 步 pass | 真实 HTTP /ready（auto_wechat DATABASE_URL）|
| PR-7 | 代表性读写事务 | INSERT/UPDATE/SELECT/DELETE 在事务内成功并 rollback | 受控测试，无业务污染 |
| PR-8 | sequence/identity | INSERT 含 SERIAL 表成功取 id | nextval 可用 |
| PR-9 | 负向 DDL | `CREATE TABLE` → permission denied | 应用角色会话执行 |
| PR-10 | 权限快照文档化 | 实施 vs 实施前对比，grants 增长符合预期 | snapshot diff |
| **PR-11** | **alembic_version 写负向** | `UPDATE alembic_version ...`（或等价 INSERT）→ **DENIED**（C3：从 §5 提升为独立 gate）| 应用角色会话执行 `UPDATE ... WHERE FALSE` |
| **PR-12** | **TRUNCATE 负向** | `TRUNCATE` 业务表 → **DENIED**（C2 新增）| 应用角色对隔离测试表执行 |

---

## 13. Security / YAGNI Boundary（Q11）

本任务只解决：当前 auto_wechat PostgreSQL 应用身份如何获得正确、最小、可持续的 runtime 权限。

**不建设**（YAGNI）：

- Vault / 动态密钥
- secret rotation 机制
- external IAM / 多 role 平台
- 复杂 production 凭据管理系统
- 独立命名的 migration admin role（Model B 过度建设）

密码仍走现有 `.env.*.local` 模式（已 gitignore，不入库不入日志）。授权脚本幂等，手动 runbook 可接受。

---

## 14. Production / Staging Unknowns（§十九）

- production/staging **实际运行 principal = UNKNOWN**（`PG_USER` 在 `.env.production.local` / `.env.staging.local`，不在仓库）。
- 静态配置可知的 contract 模式：单 superuser role（POSTGRES_USER）同时做 DDL+DML（init-prod 注释显式确认）。
- **不得将 local permission implementation 自动部署到 production/staging**。Local 验证通过只代表 `LOCAL DEVELOPMENT_PERMISSION_CONTRACT_VERIFIED`，生产需未来独立 deployment evidence。
- prod 若要落实 Runtime Principal Model（应用角色非 superuser），需在 init-prod 之外补建一个非 superuser 应用 role + 授权脚本，属独立部署审批，不在本设计执行范围。当前 prod 以 superuser 运行应用 = **已记录的残余风险**（accepted residual risk），不等于 `E2E_VERIFIED_FIXED`。

---

## 15. 0032 / 0033 / 0034 Impact（§二十）

当前 0032 / 0033 / 0034 = `UNBLOCKED_FOR_PG_VERIFICATION`。为避免 permission failure 污染 consumer 结论，推荐顺序：

```text
APPLICATION_ROLE_PERMISSION_GAP
  → resolve & verify（§5 + §6 + PR-* gates）
  → 0032 consumer PG verification（以 application role）
  → 0033 consumer PG verification（以 application role）
  → 0034 consumer PG verification（以 application role）
```

**本设计是否得出"application role 不是当前任何实际 runtime contract 的一部分"的意外结论？**

**否。** 静态审计证明：prod / staging 的 `DATABASE_URL` 显式使用 `${PG_USER:-auto_wechat}` 作为应用连接身份（[docker-compose.yml:39](docker-compose.yml#L39)、[docker-compose.staging.yml:51](docker-compose.staging.yml#L51)），application role（PG_USER）**是** runtime contract 的一部分。只是 prod/staging 该角色恰好是 superuser（隐式全权），dev 该角色是非 superuser 且无 GRANT（显式 gap）。

→ **结论：必须先 resolve & verify application role permission gap，再跑 0032/0033/0034。** 不允许跳过用 superuser 完成后宣称 application-role 路径已验证。

---

## 16. Recommended Next Stage

是否具备进入 Permission Implementation？

- 设计已完成（principal model / 最小权限 / DDL 边界 / bootstrap + ADP / provisioning ownership / readiness contract / 验证 gates）。
- 实施前置：需独立实施审批窗口授权 `GRANT / REVOKE / ALTER DEFAULT PRIVILEGES / 收回 CREATE`（本设计明确不授权执行）。
- 实施范围：LOCAL DEV ONLY（canonical dev PG @0034）。
- 实施后：PR-0~PR-10 gates 通过 → 应用角色 /ready PASS → 0032/0033/0034 以应用角色验证。

**具备进入 Permission Implementation 的设计前提，但实施需独立审批。**

---

## 17. Representative Runtime Verification + Negative Privilege Verification（§十七、§十八）

实施后不能只 `SELECT 1` 验证权限。设计受控测试（不污染业务状态，不触发真实发送/外部调用）：

**正向（覆盖 DML + sequence + FK）：**
在事务内对一张 representative 业务表（如 `douyin_leads` 或专用测试 fixture 表）执行 INSERT / UPDATE / SELECT / DELETE，最后 ROLLBACK（不留痕）：
- INSERT 一行带 SERIAL/identity id → 验证 sequence `nextval`（PR-8）+ FK 约束正常；
- UPDATE 该行某字段 → 验证 UPDATE；
- SELECT 该行 → 验证 SELECT；
- DELETE 该行 → 验证 DELETE；
- ROLLBACK → 无业务污染。

**负向（least privilege 反证，PR-9）：**
以 application role 会话执行 `CREATE TABLE perm_neg_test (...)` → 期望 `permission denied`。证明 application role 未获得 DDL，证明 §4 边界生效。

必要时用专门测试记录并清理；不运行真实业务发送/外部调用。

---

## 18. Implementation Status

```text
P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN
  DESIGN         = COMPLETE
  AUDIT          = COMPLETE（只读 catalog + 应用角色实测）
  APPROVAL       = APPROVED_WITH_CORRECTIONS（P1-PG-APP-ROLE-1 审批窗口，2026-08-10）
  CORRECTIONS    = APPLIED / FROZEN（C1 命名 / C2 PR-12 TRUNCATE负向 / C3 alembic_version硬收敛 / C4 环境证据纪律；PR-11 由审批 §14 提升为独立 gate 同步落地）
  IMPLEMENTATION = IN PROGRESS（P1-PG-APP-ROLE-2，LOCAL DEVELOPMENT ONLY）
```

> **P1-PG-APP-ROLE-1: CORRECTIONS_APPLIED / FROZEN**（2026-08-10 由 P1-PG-APP-ROLE-2 执行窗口同步审批冻结内容）。发现新事实冲突则 STOP。

本设计/审计窗口的原始设计/审计职责到此停止。Correction 同步由 P1-PG-APP-ROLE-2 执行窗口完成。执行窗口未越界：未执行 GRANT / REVOKE / ALTER ROLE / ALTER DEFAULT PRIVILEGES / 改 owner / 改 DATABASE_URL / 改迁移 / 改 M07 Core / 0032-0034 consumer PG verification / prod-staging DB 操作 / RB-10 cleanup。

---

## 附：审计事实来源索引

| 事实 | 来源 |
|---|---|
| 9000 DATABASE_URL 默认 SQLite | [app/config.py:166](app/config.py#L166) |
| dev compose 9000 接 SQLite | [docker-compose.dev.yml:92](docker-compose.dev.yml#L92) |
| dev PG profile POSTGRES_USER=postgres | [docker-compose.dev.yml:36-38](docker-compose.dev.yml#L36-L38) |
| dev init SQL 建 role auto_wechat + DB owner | [docker/postgres/init/001_create_databases.sql:6-21](docker/postgres/init/001_create_databases.sql#L6-L21) |
| prod POSTGRES_USER=PG_USER（superuser）| [docker-compose.yml:14](docker-compose.yml#L14) |
| prod app DATABASE_URL 用 PG_USER | [docker-compose.yml:39](docker-compose.yml#L39) |
| prod RAG_DATABASE_URL 用 PG_USER | [docker-compose.yml:72](docker-compose.yml#L72) |
| prod 单 role 策略（init-prod 注释）| [docker/postgres/init-prod/010_create_rag_database.sh:7-8](docker/postgres/init-prod/010_create_rag_database.sh#L7-L8) |
| staging DATABASE_URL 用 PG_USER | [docker-compose.staging.yml:51](docker-compose.staging.yml#L51) |
| Alembic env 读 DATABASE_URL，无权限 DDL | [migrations/postgres/auto_wechat/env.py:27-35](migrations/postgres/auto_wechat/env.py#L27-L35) |
| 迁移代码无 GRANT/REVOKE/CREATE ROLE/ALTER ROLE | grep `migrations/postgres/auto_wechat/versions/` = 0 命中 |
| /ready 4 步检查实现 | [app/db_readiness.py:161-223](app/db_readiness.py#L161-L223) |
| /ready 关键表 = douyin_leads / sales_staff | [app/routers/health.py:53](app/routers/health.py#L53) |
| DB-BL-2D §9 permission gap 冻结 | [docs/architecture/remediation/DB_BL_2D_IMPLEMENTATION_REPORT.md:175-184](docs/architecture/remediation/DB_BL_2D_IMPLEMENTATION_REPORT.md#L175-L184) |
| 应用角色实测：CONNECT OK / SELECT alembic_version DENIED / SELECT douyin_leads DENIED / INSERT DENIED | 本报告 §1.1 只读实测（auto_wechat 角色）|
