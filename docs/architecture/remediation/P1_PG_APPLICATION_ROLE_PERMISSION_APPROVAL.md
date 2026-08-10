# P1 — PostgreSQL Application Role Permission Contract 独立审批报告

> 审批窗口：`P1-PG-APP-ROLE-1 PostgreSQL Application Role Permission Contract`
> 审查对象：[P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md](P1_PG_APPLICATION_ROLE_PERMISSION_DESIGN.md)
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL CLOSURE` 的 PostgreSQL runtime prerequisite
> 日期：2026-08-10
> 审批结论：**APPROVED_WITH_CORRECTIONS**
> 实施授权：**AUTHORIZED — LOCAL DEVELOPMENT ONLY**
> Source of Truth：真实 PG runtime 证据（独立只读 catalog inspection + 应用角色实测） > 冻结文档 > 推测

---

## 审批结论速览

| 维度 | 结论 |
|---|---|
| Application Role Gap 是否真实存在 | ✅ RUNTIME_VERIFIED（本窗口独立复现，与设计报告 §1.1 逐项一致）|
| Application Principal 是否属 runtime contract | ✅ 是（prod/staging DATABASE_URL 显式用 `${PG_USER:-auto_wechat}`）|
| Target Principal Model 是否合理 | ✅ 主方向成立，命名需修正 |
| 最小权限 contract 是否完整 | ✅ 完整，不机械扩大 |
| existing-object + future-object 是否同时闭环 | ✅ 同时闭环 |
| alembic_version 是否 runtime 只读 | ✅ 设计层 SELECT-only 闭环，需 GRANT→REVOKE 顺序硬约束 |
| 是否授权 local permission implementation | ✅ AUTHORIZED — LOCAL DEVELOPMENT ONLY |
| 是否可进入 0032/0033/0034 consumer PG verification | ⏸ 否，须先完成 implementation + PR-* gates |

**主方向成立，但命名、TRUNCATE 负向测试、alembic_version 收敛顺序约束需作为 correction 落地。**

---

## 1. Technical Decision

**采用 Model A′（单应用角色、最小权限、非 superuser）+ Migration Authority 独立**，作为正式 runtime principal model。

技术方向判定：

- **least privilege**：应用角色非 superuser、仅 DML、无 DDL/无 role 管理，爆炸半径从"SQL 注入=全库+跨库+role 沦陷"收窄到"DML 行数据（可备份恢复）"——正确。
- **当前部署复杂度**：单团队单实例规模，Model B 的多 role IAM（Vault / rotation / external IAM）属过度建设（YAGNI），Model A′ 保留单应用角色低复杂度、去掉 superuser 放大，是 lazy-correct 折中。
- **Model A schema authority 兼容**：schema evolution 仍由 Alembic 代码权威 + migration principal（bootstrap superuser）执行，application principal 不 owner 对象、不持 DDL。
- **consumer PG verification 需求**：consumer 必须以真实 runtime principal 验证，Model A′ 让应用角色携带合法 DML 后可担此任。
- **dev 兼容**：与 dev 现有 init SQL"每库一 role"结构兼容，只需补 GRANT + ADP，不改 init 角色拓扑。

**Correction（命名，§29）**：`Model A′` 命名易与 DB-BL 的 `Schema Authority Model A` 混淆。正式冻结为：

```text
Runtime Principal Model:
SEPARATED MIGRATION / APPLICATION RESPONSIBILITY
```

- Migration principal = 执行 `alembic upgrade head` 的身份（bootstrap superuser，dev=`postgres`，prod=`PG_USER`），owner schema 对象、持 DDL。
- Application principal = 运行业务的身份（`auto_wechat`，非 superuser），仅 DML、不 owner 对象、不持 DDL。
- Alembic = 迁移代码权威（DDL 只能由迁移文件产出；执行身份是 migration principal，不是"固定单一管理员账户"）。

技术方向不变，仅文档精度修正。本 correction 不阻塞 implementation，但后续文档须统一采用新命名。

---

## 2. Runtime Gap Verdict

```text
APPLICATION_ROLE_PERMISSION_GAP:
RUNTIME_VERIFIED
```

本审批窗口以本地 canonical dev PG（`auto-wechat-postgres-dev` @ 5432，`auto_wechat` 库，head=0034）为对象，**独立复现**设计报告 §1.1 全部事实，零偏差：

### 2.1 应用角色 `auto_wechat` 实测（非 superuser 直连）

```text
CONNECT  (SELECT current_database())            → OK    → ('auto_wechat',)
SELECT version_num FROM alembic_version          → DENIED → permission denied for table alembic_version
SELECT 1 FROM douyin_leads LIMIT 1               → DENIED → permission denied for table douyin_leads
SELECT 1 FROM sales_staff LIMIT 1                → DENIED → permission denied for table sales_staff
UPDATE alembic_version SET ... WHERE FALSE       → DENIED → permission denied for table alembic_version
```

写权限负向测试用 `UPDATE ... WHERE FALSE`（零行风险，权限层先抛），等价安全 negative test，与设计报告"INSERT → DENIED"语义一致。

### 2.2 superuser 只读 catalog inspection

```text
role auto_wechat                    : EXISTS, LOGIN=true, SUPERUSER=false
table grants (auto_wechat)          = 0
usage/sequence grants (auto_wechat) = 0
pg_default_acl (auto_wechat creator)= 0
public schema 表 owner 分布         = [('postgres', 61)]
douyin_leads.relacl                 = None
database auto_wechat owner/datacl  = ('auto_wechat', None)
public schema owner/acl             = pg_database_owner, [pg_database_owner=UC/pg_database_owner, =U/pg_database_owner]
alembic head                        = 0034
physical tables (public)            = 61
```

→ **`auto_wechat` 应用角色当前能 CONNECT（经 PUBLIC 默认），但对任何业务表与 alembic_version 均无 SELECT/INSERT/UPDATE 权限。** 当前 `/ready` PASS 仅因以 `postgres` superuser 运行；若以应用角色运行必在 `alembic_revision` 检查步（[db_readiness.py:169](app/db_readiness.py#L169)）落入 `ERROR_DB_CONNECT` → 503。

### 2.3 DDL 泄漏点确认

public schema ACL `{pg_database_owner=UC, =U}` 中 `UC` 含 CREATE。`auto_wechat` 是 database `auto_wechat` 的 owner → 隐式属 `pg_database_owner` → 自动获得 public schema CREATE。**这是真实隐式 DDL 泄漏点**，设计报告 §3.2/§7 识别正确，须在 implementation 收回。

---

## 3. Dev / Staging / Production Principal Evidence

严格分层（与设计报告 §1.4 一致，本窗口复核配置证据）：

| 环境 | principal | 是否 superuser | 证据等级 | 证据来源 |
|---|---|---|---|---|
| Dev（SQLite）| 无 PG | — | KNOWN（config）| [docker-compose.dev.yml:92](docker-compose.dev.yml#L92) 9000 接 SQLite |
| Dev（canonical PG）| `auto_wechat` | **否** | **LOCAL_PG_RUNTIME_VERIFIED** | 本窗口独立实测 + catalog inspection |
| Staging | `auto_wechat_staging` | 是（配置模板）| **CONFIG_VERIFIED / RUNTIME_UNKNOWN** | [docker-compose.staging.yml:51](docker-compose.staging.yml#L51) DATABASE_URL 用 `${PG_USER:-auto_wechat_staging}` |
| Production | `PG_USER`（默认 `auto_wechat`）| 是（配置模板）| **CONFIG_VERIFIED / RUNTIME_UNKNOWN** | [docker-compose.yml:39](docker-compose.yml#L39)、[docker-compose.yml:72](docker-compose.yml#L72) |

**Evidence discipline 硬约束：**

- Dev canonical PG：本窗口已以 `auto_wechat` 角色真实连接实测，标 `LOCAL_PG_RUNTIME_VERIFIED`。
- Staging / Production：仅通过 compose / env 模板 / init 脚本推导，标 `CONFIG_VERIFIED`；实际部署 role attribute = `RUNTIME_UNKNOWN`（`PG_USER` 在 `.env.production.local` / `.env.staging.local`，不入库）。**不得因配置模板写 SUPERUSER 就宣称生产真实角色当前一定是 superuser**，也不得据此自动应用 local GRANT 设计。

---

## 4. Target Principal Contract

```text
MIGRATION_PRINCIPAL (dev)  = postgres (bootstrap superuser, 非 superuser 角色不可跑 alembic)
APPLICATION_PRINCIPAL     = auto_wechat (non-superuser, runtime DML)
两 principal 不得同一身份；application principal 不 owner schema 对象、不持 DDL
```

- dev 唯一 object creator = `postgres`（catalog 核实 61 表 owner=postgres）。
- prod object creator = `PG_USER`（实际名 UNKNOWN）。
- application principal 通过 GRANT 拿权限，不通过改 owner 绕过 GRANT。

contract 合理，批准。

---

## 5. Application Minimum Privileges

针对 `auto_wechat` 应用角色在 `auto_wechat` database：

| 对象类型 | 授予权限 | 依据 |
|---|---|---|
| Database | `CONNECT` | 应用连接必需（当前经 PUBLIC 默认，应显式 GRANT）|
| Schema public | `USAGE` | 访问对象前提 |
| Schema public | **禁止 CREATE** | application 不负责 schema evolution；收回 pg_database_owner 隐式 CREATE |
| 业务表（60 张）| `SELECT, INSERT, UPDATE, DELETE` | 9000 consumer 覆盖线索读写/销售回写/outbox 幂等消费/日报/M05/Preview/RAG ingest，均标准 CRUD |
| 业务表 | **禁止 TRUNCATE / REFERENCES / TRIGGER** | TRUNCATE 非 runtime；FK/trigger 是 DDL 归 migration principal |
| Sequences | `USAGE, SELECT` | SERIAL/identity `nextval` 需 USAGE，`currval` 需 SELECT；不需 UPDATE（setval 归运维）|
| alembic_version | `SELECT` 仅 | `/ready` 读 revision；禁止 INSERT/UPDATE/DELETE/TRUNCATE |

**判定：合理，不机械 `GRANT ALL`。** 四类 DML + 序列两权限 + alembic_version 单 SELECT，与代码实际 runtime behavior（[db_readiness.py:161-223](app/db_readiness.py#L161-L223) 只读 SELECT + consumer CRUD）对齐，未凭印象扩大。

---

## 6. alembic_version Special Contract

```text
alembic_version → SELECT ONLY（runtime 只读）
INSERT / UPDATE / DELETE / TRUNCATE → 禁止
```

设计 §5 落地方式：

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;  -- 含 alembic_version 四类
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;                    -- 收写，留 SELECT
```

**审批判定：正确，但升级为顺序硬约束：**

- GRANT 集合不含 TRUNCATE（只 SELECT/INSERT/UPDATE/DELETE），故 alembic_version 本就无 TRUNCATE。
- REVOKE 必须在 GRANT 之后对 alembic_version 单独执行，最终只留 SELECT。
- `SELECT, INSERT, UPDATE, DELETE` 四类中 REVOKE 掉三个写，残留 SELECT——**审批要求 implementation 不得跳过该 REVOKE**，并经负向测试证明 alembic_version 不可写。

**Negative verification 硬约束（§十）：** implementation 后必须以 application role 真实执行 `UPDATE alembic_version ...`（或等价 INSERT）→ 期望 DENIED；不得只看 `information_schema` 宣称成立。

**残余风险（§6.4，接受但显式记录）：** 若未来某 migration DROP + 重建 `alembic_version`，§6.2 的 ADP 会让重建后的 alembic_version 自动拿到 DML，违反 SELECT-only。设计接受此残余（alembic_version 仅空库首次 upgrade 建一次）。**Correction：将该残余处置升级为 implementation runbook 硬约束——若未来 DROP+重建 alembic_version，必须重新执行 §5 步骤4 REVOKE，不得依赖"低概率路径"。**

---

## 7. DDL / TRUNCATE Boundary

```text
application role 禁止：CREATE TABLE / ALTER TABLE / DROP TABLE / CREATE INDEX / TRUNCATE / CREATE SCHEMA / DROP SCHEMA
```

- schema CREATE privilege：通过 §5/§7 收回（显式 `REVOKE CREATE ON SCHEMA public`，并处理 pg_database_owner 隐式 UC）。
- object ownership：application role 不 owner 对象 → 自然无 ALTER/DROP。
- role attributes：application role rolsuper=false（catalog 核实）→ 无 superuser 绕过。

**Negative test（PR-10/§十七）：** application role `CREATE TABLE perm_neg_test (...)` → DENIED。

**Correction — TRUNCATE 负向测试：** 设计 §3.3 禁止 TRUNCATE，但 PR-* gate 列表（§11/§12）只含 CREATE TABLE（PR-9）与 alembic_version write 负向，未显式含 TRUNCATE 负向。虽然 GRANT 四类不含 TRUNCATE，应用角色本就无 TRUNCATE，但审批任务 §十二/§二十二要求"若禁止 TRUNCATE 应有 negative test"。**Correction：新增 PR-12 TRUNCATE negative test**（`TRUNCATE douyin_leads` → DENIED），作为最小 negative set 的显式 gate。

---

## 8. Existing Object Grant Contract

对 canonical@0034 现有 61 表（60 业务 + alembic_version）一次性 bootstrap（由 migration principal / superuser 执行，**本审批不执行**）：

```sql
GRANT CONNECT ON DATABASE auto_wechat TO auto_wechat;
GRANT USAGE ON SCHEMA public TO auto_wechat;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO auto_wechat;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO auto_wechat;
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM auto_wechat;
```

**审批判定：正确。**

- `ON ALL TABLES` / `ON ALL SEQUENCES` 一次性覆盖现有全部对象，**不漏表**（审批任务 §十三："一次性 bootstrap 不能只修一张测试表"——本设计满足）。
- `GRANT`/`REVOKE` 幂等，重复执行安全。
- 必须由 migration principal（superuser）执行——对象 owner=postgres，只有 owner 或 superuser 能 GRANT。
- "覆盖 + 一处 REVOKE" 是比"枚举 60 表 + 单独 SELECT alembic_version"更短且不易漏表的最短差，符合 ponytail 原则。

---

## 9. Future Object Default Privilege Contract

```sql
ALTER DEFAULT PRIVILEGES
  FOR ROLE postgres              -- dev 唯一 migration principal
  IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auto_wechat;

ALTER DEFAULT PRIVILEGES
  FOR ROLE postgres
  IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO auto_wechat;
```

**审批判定：正确，creator-role-specific 三要素齐备。**

- `FOR ROLE postgres`：dev 唯一 creator=postgres（catalog 核实 61 表 owner=postgres），一份 ADP 覆盖未来 0035+ 新表。**不得写抽象 `ALTER DEFAULT PRIVILEGES` 不带 FOR ROLE。**
- `IN SCHEMA public` + 对象类型 TABLES/SEQUENCES：齐备。
- ADP 不溯及既往 → §8 bootstrap 不可省。**两者同时闭环（审批任务 §十五）：✅ 满足。**
- prod：`FOR ROLE <PG_USER>`，实际名待部署侧确认（runbook，不在本设计执行范围）。

---

## 10. Ownership Contract

```text
现有对象 owner 留在 migration principal（postgres）
application role 只收 GRANT，不改 owner
```

**审批判定：正确。** 不推荐把表 owner 转给 application role——application role owner 对象即可 ALTER/DROP（DDL），直接破坏 §7 边界，且违背 principal 分离。减少 GRANT 的收益不抵 DDL 泄漏风险。

DB owner 处置：当前 database `auto_wechat` owner=`auto_wechat` → 隐式 `pg_database_owner` → public schema CREATE 泄漏。设计原提供两路径（路径1 保留 DB owner + REVOKE CREATE；路径2 DB owner 转 postgres）。

> **所有权处置已由独立审批冻结（2026-08-10），收紧本节原"两路径任一均可"判断：** 见 [P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md](P1_PG_APPLICATION_ROLE_OWNERSHIP_APPROVAL.md)。database ownership 是不可被 `REVOKE` 移除的持久行政能力（owner 可单方面恢复被收回的权限，且携带 ALTER/DROP DATABASE 等 ownership-level control），**路径1（保留 owner + REVOKE CREATE）= REJECTED**，**路径2（`ALTER DATABASE auto_wechat OWNER TO postgres`）= APPROVED（唯一推荐）**。现象层"消除 CREATE 泄漏"不足，须在语义层消除 ownership-level control。

---

## 11. Provisioning Ownership

| 职责 | 归属 | 边界 |
|---|---|---|
| ROLE CREATION（CREATE ROLE / 密码）| Docker/PostgreSQL bootstrap（entrypoint + init 脚本）| **不进 Alembic**；密码绝不写进迁移历史 |
| OBJECT GRANT + ADP | 部署/bootstrap 脚本（post-alembic）| **不进 Alembic 迁移文件**；GRANT/ADP 幂等适合脚本 |
| SCHEMA DDL | Alembic 迁移文件（唯一）| schema evolution 代码权威 |

**审批判定：contract 清楚。** cluster 级与 database/object 级职责区分明确，不要求建设统一 secret/IAM 系统（YAGNI）。local role `auto_wechat` 已存在（init SQL），本轮 implementation 原则上只处理 object/database privileges，不重建 role、不碰密码。

---

## 12. Readiness Verification Principal

`/ready` 实际权限需求（[db_readiness.py:161-223](app/db_readiness.py#L161-L223)）：

| 检查步 | SQL | 所需权限 |
|---|---|---|
| db_connect | `SELECT 1` / `SELECT current_database()` | CONNECT |
| alembic_revision | `SELECT version_num FROM alembic_version` | SELECT on alembic_version |
| critical_tables | `SELECT 1 FROM "douyin_leads"/"sales_staff" LIMIT 1` | SELECT on 关键业务表 |
| database_name | `current_database()` 比对 | CONNECT |

全部只读 SELECT，是 legitimate application permission need，非 readiness bug。`/ready` 实现层 `has_schema_privilege` 等不要求危险权限，无需为过 /ready 扩大 GRANT。

**implementation 后必须以 application role DATABASE_URL（非 superuser）重跑 `/ready`，证明：**

```text
backend       = PostgreSQL
database      = auto_wechat
role/principal= auto_wechat（非 superuser）
alembic head  = 0034
HTTP          = 200
```

若 `/ready` 需要应用不该有的权限，应检查 readiness 实现，不得直接扩大 GRANT。

---

## 13. Consumer PG Verification Principal

```text
0032 / 0033 / 0034 consumer PG verification 必须以 Application Role（auto_wechat）为主验证身份
不得以 superuser 静默通过后宣称 application-role 路径已验证
```

正式区分两类 principal（§10 of design）：

| Contract | Principal | 用途 |
|---|---|---|
| `MIGRATION_TEST_PRINCIPAL` | migration principal（superuser）| Alembic upgrade/downgrade、schema DDL 验证 |
| `APPLICATION_TEST_PRINCIPAL` | `auto_wechat` | consumer 行为验证、/ready、runtime DML |

**审批判定：正确。** consumer verification 目的是证明"实际 runtime consumer 在 PG 上以真实权限工作"。本窗口 §2 已实测应用角色当前连 SELECT 都 DENIED——若用 superuser 完成 consumer 测试是假阳性。**superuser 通过只证明 schema/consumer works with admin privilege，不证明 production-like application permission path works。**

**前置硬约束：** 必须先 resolve APPLICATION_ROLE_PERMISSION_GAP（implementation 通过 + PR-* gates）→ 再跑 0032/0033/0034 以 application role 验证。**审批窗口明确：本审批授权的是 design + local implementation，不授权开始 0032/0033/0034 consumer verification 本身。**

---

## 14. PR-* Gates

冻结 implementation gates（含 correction 新增 PR-12）：

| Gate | 验证内容 | 通过判据 |
|---|---|---|
| PR-0 | 环境 | LOCAL DEV ONLY（auto-wechat-postgres-dev @5432，auto_wechat 库），非 prod/staging |
| PR-1 | 应用角色存在性 | EXISTS / LOGIN / NON-superuser（`pg_roles` 只读）|
| PR-2 | 实施前权限快照 | 0 table grants / 0 seq grants / 0 ADP / relacl NULL |
| PR-3 | 最小权限落地 | DML on 60 业务表 + SELECT on alembic_version + alembic_version 无写（`has_table_privilege()`）|
| PR-4 | 未来对象 policy | ADP 存在且 `FOR ROLE postgres` 正确（`pg_default_acl` non-zero，creator=postgres）|
| PR-5 | 无意外 DDL/superuser | application role 无 CREATE on public（`has_schema_privilege('public','CREATE')`=false）；rolsuper=false |
| PR-6 | /ready 以应用角色 PASS | HTTP 200，4 步 pass（真实 HTTP /ready，auto_wechat DATABASE_URL）|
| PR-7 | 代表性读写事务 | INSERT/UPDATE/SELECT/DELETE 事务内成功并 ROLLBACK，无业务污染 |
| PR-8 | sequence/identity | INSERT 含 SERIAL 表成功取 id（nextval 可用）|
| PR-9 | 负向 DDL | `CREATE TABLE` → permission denied |
| PR-10 | 权限快照文档化 | 实施 vs 实施前对比，grants 增长符合预期 |
| **PR-11** | **alembic_version 写负向** | `UPDATE alembic_version ...`（或等价 INSERT）→ **DENIED**（Correction：从设计 §5 提升为独立 gate）|
| **PR-12** | **TRUNCATE 负向** | `TRUNCATE douyin_leads` → **DENIED**（Correction 新增）|

PR-2/PR-10 快照须在 GRANT 前后分别冻结；PR-6 须用真实 HTTP /ready 而非 `SELECT 1`；PR-7/PR-8 须触发真实 sequence/identity path 与 FK，不污染业务状态（事务 ROLLBACK 或隔离 fixture）。

---

## 15. Production / Staging Boundary

```text
PRODUCTION / STAGING: NO WRITE AUTHORIZED
```

- production/staging 实际运行 principal = `RUNTIME_UNKNOWN`（`PG_USER` 在 `.env.production.local` / `.env.staging.local`，不入库）。
- 静态配置可知的 contract 模式：单 superuser role（POSTGRES_USER）同时做 DDL+DML（[init-prod/010](docker/postgres/init-prod/010_create_rag_database.sh) 注释显式确认）。
- **不得将 local permission implementation 自动部署到 production/staging。** Local 验证通过只代表 `LOCAL_DEVELOPMENT_PERMISSION_CONTRACT_VERIFIED`，生产需未来独立 deployment evidence。
- prod 若要落实 Model A′（应用角色非 superuser），需在 init-prod 之外补建一个非 superuser 应用 role + 授权脚本，属独立部署审批，不在本设计执行范围。
- 当前 prod 以 superuser 运行应用 = **已记录的残余风险（accepted residual risk）**，不等于 `E2E_VERIFIED_FIXED`。

---

## 16. Implementation Authorization

```text
AUTHORIZED — LOCAL DEVELOPMENT ONLY
```

授权进入 `P1-PG-APP-ROLE-2 — LOCAL Permission Implementation`，**仅允许**：

- local development PG（auto-wechat-postgres-dev @5432，auto_wechat 库）；
- existing-object grants（§8）；
- future-object default privileges（§9，`FOR ROLE postgres`）；
- alembic_version 只读收敛（§6，GRANT→REVOKE 顺序硬约束）；
- application-role runtime 测试（PR-6/7/8 正向 + PR-9/11/12 负向）；
- documentation sync（含命名 correction：统一采用 `Runtime Principal Model: SEPARATED MIGRATION / APPLICATION RESPONSIBILITY`）。

**实施失败规则（§二十八）：** 若任何 GRANT 后出现 unintended DDL capability / application 仍无法 runtime DML / default privileges 绑定错误 creator / alembic_version 仍可写 / readiness 只能靠 superuser 通过——**STOP**，记录 gap，必要时回滚本轮 grants 再提交新设计，不得扩大权限碰运气。

---

## 17. Explicitly Forbidden

本审批**继续禁止**：

- prod / staging 任何 DB 变更（GRANT/REVOKE/ALTER ROLE/改 owner）；
- consumer 业务代码修改（0032/0033/0034 业务逻辑）；
- M07 Core 修改（record_usage / 0030 migration / atomic ownership / IntegrityError replay）；
- DB-BL 重开（DB-BL = REPAIR_VERIFIED / COMPLETE，不得重新打开）；
- Alembic 迁移重写（迁移文件不得加 GRANT/REVOKE/CREATE ROLE/ALTER ROLE/ADP）；
- RB-10 cleanup；
- 0032 / 0033 / 0034 consumer PG verification 本身（须先完成 implementation + PR-* gates）；
- 在 repo 写真实 password / production secret；
- 把 role creation 与 credential management 塞进 Alembic。

---

## 附：审批窗口独立核验证据索引

| 核验项 | 证据 | 与设计报告一致性 |
|---|---|---|
| prod POSTGRES_USER=PG_USER(superuser) | [docker-compose.yml:14](docker-compose.yml#L14) | ✅ |
| prod app DATABASE_URL 用 PG_USER | [docker-compose.yml:39](docker-compose.yml#L39) | ✅ |
| prod RAG_DATABASE_URL 用 PG_USER | [docker-compose.yml:72](docker-compose.yml#L72) | ✅ |
| staging DATABASE_URL 用 PG_USER | [docker-compose.staging.yml:51](docker-compose.staging.yml#L51) | ✅ |
| dev 9000 接 SQLite，不接 PG | [docker-compose.dev.yml:92](docker-compose.dev.yml#L92) | ✅ |
| dev PG profile POSTGRES_USER=postgres | [docker-compose.dev.yml:36-38](docker-compose.dev.yml#L36-L38) | ✅ |
| dev init SQL 建 role auto_wechat + DB owner | [docker/postgres/init/001_create_databases.sql:6-21](docker/postgres/init/001_create_databases.sql#L6-L21) | ✅ |
| config 默认 SQLite | [app/config.py:166](app/config.py#L166) | ✅ |
| alembic env 读 DATABASE_URL 无权限 DDL | [migrations/postgres/auto_wechat/env.py:27-35](migrations/postgres/auto_wechat/env.py#L27-L35) | ✅ |
| 迁移文件无 GRANT/REVOKE/CREATE ROLE/ALTER ROLE/ADP | grep `migrations/postgres/auto_wechat/versions/` = 0 命中（本窗口复核）| ✅ |
| /ready 4 步实现 | [app/db_readiness.py:161-223](app/db_readiness.py#L161-L223) | ✅ |
| /ready 关键表 = douyin_leads / sales_staff | [app/routers/health.py:53](app/routers/health.py#L53) | ✅ |
| 应用角色实测：CONNECT OK / SELECT DENIED / WRITE DENIED | 本窗口独立复现（§2.1）| ✅ 逐项一致 |
| catalog：role 属性/grants=0/default_acl=0/owner=postgres×61/relacl=None/head=0034/tables=61 | 本窗口独立复现（§2.2）| ✅ 逐项一致 |

---

## 审批窗口停止点

审批完成。本窗口**不自行执行**任何 GRANT / REVOKE / ALTER ROLE / ALTER DEFAULT PRIVILEGES，**不开始** 0032/0033/0034 consumer PG verification。

下一步交由独立 implementation 窗口（`P1-PG-APP-ROLE-2`）在 LOCAL DEVELOPMENT ONLY 范围内落地 §8/§9/§6 + PR-* gates，通过后再回到本窗口或消费方窗口启动 consumer PG verification。
