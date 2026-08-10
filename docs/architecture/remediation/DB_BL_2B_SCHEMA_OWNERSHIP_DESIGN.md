# DB-BL-2B — auto_wechat PostgreSQL Schema Ownership Design / Audit

> 设计日期：2026-08-10
> 阶段：P1 `COMPUTE-IDEMPOTENCY-001` Technical Closure / Blocker A（auto_wechat schema baseline）
> 模式：**DESIGN / AUDIT ONLY**（只读设计，不实施）
> 前置：`DB_BL_2A_MIGRATION_CHAIN_COMPLETENESS.md`（`COMPLETE / FROZEN`，5 项修正已 `CORRECTIONS_APPLIED`）+ `DB_BL_2A_APPROVAL.md`（`AUTHORIZED — DESIGN/AUDIT ONLY`）
> Source of Truth：运行代码 / 迁移文件 / env.py / alembic.ini / health.py / docker-compose > 冻结文档 > 历史假设

---

## 核心问题

> auto_wechat PostgreSQL Schema 的正式 Authority、Bootstrap Contract、Legacy `create_all` 边界，以及 DB-BL-2C 的目标 baseline 应如何定义？

本阶段不"把当前数据库修好"，而是**先定义以后什么才叫一个合法的 auto_wechat PostgreSQL schema**。

---

## 0. 2A 修正项回填确认

2A 审批要求 5 项文档证据修正应先完成并冻结。本 2B 在设计过程中**独立复核**这 5 项所依赖的代码事实，确认其前提仍然成立（未因任何代码改动而失效）：

| 2A 修正项 | 复核结论 |
|---|---|
| 1 显式证据分层标签 | `STATIC_CHAIN_VERIFIED` ≠ `PG_RUNTIME_VERIFIED`，本 2B 沿用该分层 |
| 2 Schema Authority 拆两层 | 代码意图 = Model A / dev DB 残骸 = Model B-C，本 2B §1/§2 据此设计 |
| 3 第 3 节流程图为 projected | 空 PG → upgrade head 仍仅为静态推演，本 2B 未实跑 |
| 4 init_db.py provenance | 仍为 `MOST PLAUSIBLE PROVENANCE` / `INFERRED`，未升级 |
| 5 根因步骤 provenance 降级 | create_all 快照来源仍为 hypothesis |

> 2A 修正项的**文字回填**属 2A 报告原位修订，**已于 2026-08-10 落地**（`CORRECTIONS_APPLIED` → 2A `COMPLETE / FROZEN`）。本 2B 在设计引用中遵循已修正的措辞与证据层标签。2A 冻结事实见 `DB_BL_2A_APPROVAL.md` §4 与 `DB_BL_2A_MIGRATION_CHAIN_COMPLETENESS.md` RESULT 区 FROZEN FACTS 表。

---

## 1. Technical Decision — Schema Authority 模型

### 1.1 候选模型

| 模型 | 定义 |
|---|---|
| Model A | Alembic = PostgreSQL schema 唯一 constructor / evolution authority |
| Model B | `create_all` = baseline constructor；Alembic = 增量 evolution authority |
| Model C | `create_all` + Alembic 无可靠正式契约地共存 |

### 1.2 当前代码事实（CODE_VERIFIED）

- `app/main.py:273-285` `ensure_runtime_schema()`：SQLite 分支 `create_all(bind=engine)` 后 return；**PostgreSQL 分支显式记 `startup_skip_create_all` 后 return，不调 create_all**。
- `migrations/postgres/auto_wechat/env.py`：`target_metadata=None`（纯执行器，未接 autogenerate），`_database_url()` 强制 `DATABASE_URL` 为 PostgreSQL，拒绝 SQLite URL。
- `app/routers/health.py:62` `/ready`：PG 下验证 `alembic_version == 代码 migration head` + database 名 + 关键表，失败返回 503；只读，不执行 alembic、不建表。
- `docker-compose.yml` healthcheck 已用 `/ready`，注释明确"部署前必须先执行 alembic upgrade head，否则 alembic_revision 检查失败导致 unhealthy"。
- `docker-compose.staging.yml:28`："部署前必须对两个 staging database 各执行一次 alembic upgrade head"。
- `scripts/init_db.py:16`：`Base.metadata.create_all(bind=engine)` **无条件**（无 backend 守卫），后接 CheckConfig seed。

**代码意图 = Model A**（PG 下 main.py skip create_all、env.py 强制 PG、`/ready` 强制 alembic head、docker-compose 强制部署前 upgrade head、CLAUDE.md 硬约束 #2"PostgreSQL 下禁止 create_all，必须先 Alembic"）。

**dev DB 残骸 = Model B/C mixed baseline**（dev PG 57 表 create_all 快照、无 `alembic_version`、不对应任何 revision——2A 冻结事实 #9）。

### 1.3 各方案优劣

| 维度 | Model A | Model B | Model C |
|---|---|---|---|
| 单一真源 | ✅ Alembic 链是 PG schema 唯一事实源 | ❌ create_all 快照 vs Alembic 链两套 | ❌ 无契约 |
| 版本可追溯 | ✅ `alembic_version` 明确当前 revision | ❌ create_all 不写 `alembic_version` | ❌ 无版本跟踪 |
| 列级演进 | ✅ ALTER 走迁移，可审计/回滚 | ❌ create_all 不 ALTER 已存在表 | ❌ drift 无界 |
| 与 `/ready` 一致 | ✅ 已实现且强制 | ❌ `/ready` 会因无 `alembic_version` 返回 503 | ❌ 永远 not_ready |
| 历史教训 | — | ❌ **正是 Model B 的不受控快照导致当前 SCHEMA_BASELINE_MISMATCH** | ❌ 当前 dev PG 即此状态 |
| bootstrap 便利 | 需 `alembic upgrade head` 一步 | `create_all` 一步 | 两者混用 |

Model B 的"create_all 建 + Alembic 演进"正是 SQLite era（见 `14_DB_MIGRATION_PLAN.md`）的方案，在 SQLite 域可接受；但**移植到 PG 域正是当前 dev PG 57 表无 `alembic_version` 根因**——不可作为 PG 目标。

### 1.4 推荐模型

**`MODEL A` — Alembic = sole PostgreSQL schema constructor / evolution authority。**

理由：

1. 与代码运行时意图一致（main.py PG skip、env.py PG-only、`/ready` 强制 head）。
2. 与 CLAUDE.md 硬约束 #2 一致。
3. 与 docker-compose 生产/staging healthcheck 设计一致。
4. Model B 是当前 mismatch 的根因，不可重蹈。
5. `/ready` 已是该模型的 runtime enforcement（见 §7），落地成本已部分支付。

**不推荐 Model B 作为 PG 未来模型**；不推荐 Model C（无契约共存）。

---

## 2. Ownership Contract

按环境分别定义 schema owner 与 `create_all()` 调用许可。

| 环境 | Schema Owner | `create_all()` 许可 | Alembic 角色 | 说明 |
|---|---|---|---|---|
| **production PG** | Alembic | ❌ 禁止 | sole constructor + evolution | 部署前 `alembic upgrade head`；`/ready` 强制 head；main.py PG skip。`init_db.py` 不得用于 PG。 |
| **staging PG** | Alembic | ❌ 禁止 | sole constructor + evolution | 同 production；`docker-compose.staging.yml` 已要求部署前 upgrade head。 |
| **development PG** | Alembic | ❌ 禁止 | sole constructor + evolution | 新 dev PG 一律空库 `alembic upgrade head`。当前 57 表无 `alembic_version` 的 legacy dev PG 是**待治理残骸**，不作为模板。 |
| **SQLite（dev/test 过渡库）** | `create_all`（runtime） | ✅ 允许 | 不适用（SQLite 不走 Alembic PG 链） | `ensure_runtime_schema()` SQLite 分支 `create_all` 保留；SQLite 是过渡库非最终生产（CLAUDE.md 硬约束 #2）。 |
| **automated tests** | test fixture | ✅ 允许（仅 SQLite） | 不适用 | 测试用 SQLite drop_all+create_all 建表；PG schema 测试用独立 dev PG + alembic upgrade head（见现有 smoke 脚本模式）。 |

**关键边界**：

- `create_all()` 的合法范围 = **仅 SQLite backend**（runtime + test）。
- `create_all()` 在 **PostgreSQL backend 下禁止**，无论是 runtime、init_db.py、还是手工。
- Alembic 链 `migrations/postgres/auto_wechat/` 是 `auto_wechat` database 的唯一 PG schema authority；`migrations/postgres/xg_douyin_ai_cs/` 是 `xg_douyin_ai_cs` database 的唯一 PG schema authority（两链独立，env.py 分别读 `DATABASE_URL` / `RAG_DATABASE_URL`，见 `POSTGRESQL_MIGRATION_NOTES.md` §18 P3-A 设计）。

---

## 3. PostgreSQL Bootstrap Contract

### 3.1 候选方案

| 候选 | 流程 |
|---|---|
| A | `empty PG → alembic upgrade head → application` |
| B | `empty PG → create_all → Alembic baseline/stamp → application` |
| C | 其他代码事实支持的模型 |

### 3.2 各候选分析

**候选 A（推荐）**：
- 谁建业务表：Alembic 链（0002-0034 逐批 `create_table`，0001 空标记）。
- 谁建 `alembic_version`：Alembic 框架在首次 `upgrade` 时自动创建（非迁移职责，2A 冻结事实 #4）。
- 应用启动是否隐式补 schema：**否**。`ensure_runtime_schema()` PG 分支 skip create_all；schema readiness 由 `/ready` 在 traffic 接入前校验，缺失则 503 unhealthy，不隐式补。
- migration failure 如何暴露：`alembic upgrade head` 在部署步骤失败 → 容器不进入 healthy → 不接流量。`/ready` 二次校验 `alembic_version == head`。
- bootstrap 是否是 deployment responsibility：**是**。由部署/运维在应用启动前执行 `alembic upgrade head`（docker-compose 注释与 staging runbook 已要求）。

**候选 B**：
- 用 `create_all` 建表后 `alembic stamp` 标记 baseline。问题：`create_all` 产出是 ORM 当前快照，不对应任何具体 revision 的 expected schema（列定义可能 drift，2A 已登记列级未对账）；`stamp` 会伪造"已到 head"而实际 schema 来自 ORM 快照——**正是当前 dev PG 的错误状态**。否决。

**候选 C**：
- 当前代码无第三种 bootstrap 路径。`init_db.py` 是候选 B 的变体（create_all + seed，无 stamp，无 `alembic_version`），更糟。

### 3.3 冻结 Bootstrap Contract

**合法新 PostgreSQL database 创建流程（候选 A）**：

```text
1. 创建空 database（CREATE DATABASE auto_wechat / xg_douyin_ai_cs）
2. 设置 DATABASE_URL=postgresql+psycopg://...@host/auto_wechat
3. cd migrations/postgres/auto_wechat
4. alembic upgrade head
   → 框架自动建 alembic_version
   → 0001 pass（空标记）
   → 0002-0034 逐批建 60 业务表 + ALTER/索引/约束
   → 结果：60 业务表 + 1 alembic_version，revision=0034（projected，2A 未实跑）
5. 启动应用 → /ready 校验 alembic head + database 名 + 关键表 → 通过才接流量
```

**硬约束**：
- 步骤 4 必须在步骤 5（应用接流量）之前完成。
- 禁止用 `init_db.py` / `create_all` 替代步骤 4。
- 禁止 `alembic stamp` 跳过步骤 4（stamp 仅用于"已通过 2C 对账证明 schema 与某 revision 精确一致"的受控场景，见 §6）。
- 该路径当前为 `STATIC_CHAIN_VERIFIED` + `PROJECTED`，**尚未在真实空 PG 实跑验证**（2A 冻结事实：`PG_RUNTIME_NOT_VERIFIED`）。2C 列级对账 + 恢复 PG 连通后应补一次实跑。

---

## 4. init_db.py Ownership / Lifecycle

### 4.1 当前做什么（CODE_VERIFIED）

`scripts/init_db.py`：
1. `Base.metadata.create_all(bind=engine)`（第 16 行，**无条件，无 backend 守卫**）。
2. 插入 `DEFAULT_CONFIGS` 到 `CheckConfig`（仅当 key 不存在时）。
3. engine 来自 `app.database`，随 `DATABASE_URL` 决定后端——**若在 PG URL 下运行，会无守卫地对 PG 执行 create_all**。

### 4.2 引用面审计

| 引用位置 | 性质 | 风险 |
|---|---|---|
| `README.md:75` `python scripts/init_db.py` | 开发指引（CURRENT） | 若开发者照此在 PG URL 下初始化 dev 库，会再次产生无 `alembic_version` 的 create_all 快照 |
| `docs/architecture/RUNTIME_ENTRYPOINTS.md:242` | 登记 `ACTIVE / maintenance / manual_only / PLATFORM / DB 初始化` | lifecycle 标记需随决策同步 |
| `docs/ai/03_data_and_migration/ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md` | 设计文档引用 | HISTORICAL |
| `docs/ai/03_data_and_migration/14_DB_MIGRATION_PLAN.md:141,183` | SQLite era 诊断引用 | HISTORICAL |
| Dockerfile / docker-compose | **未引用**（grep 确认无 init_db 调用） | 无自动化风险 |
| CI | 未发现自动调用 | 无自动化风险 |
| 9100 `apps/xg_douyin_ai_cs/rag/database.py` | **不同函数**（9100 自有 `init_db()`，SQLite 兼容层，在 guard allowlist 内） | 不混淆，但同名易误读 |

### 4.3 当前是否仍有合法使用场景

- **SQLite dev 库初始化**：合法。SQLite 是过渡库，`create_all` + seed 在 SQLite 域可接受（Ownership Contract §2）。
- **PG 库初始化**：**不合法**。无条件 create_all 会绕过 Alembic、不写 `alembic_version`、产出 ORM 快照而非 revision schema——正是 dev PG 57 表残骸的成因。

### 4.4 是否存在再次创建"无 alembic_version PG"的风险

**存在**。`init_db.py` 无 backend 守卫，若任何人在 `DATABASE_URL=postgresql...` 下执行 `python scripts/init_db.py`，会再次产生无 `alembic_version` 的 PG create_all 快照，重蹈 dev PG 覆辙。README:75 当前未区分 backend，是一个现实触发点。

### 4.5 候选状态决策

| 候选 | 评估 |
|---|---|
| KEEP | ❌ 维持现状=保留无守卫 PG create_all 风险 |
| RESTRICT | ✅ 保留脚本但加 PG backend 守卫（PG 下拒绝 create_all，仅 SQLite 允许）+ seed 独立化 |
| DEPRECATE | ⚠️ 标记弃用但保留，仍需加守卫否则弃用期间仍可误触发 |
| REPLACE | ✅ 可作为 RESTRICT 的演进：seed 逻辑抽到独立 `seed_default_configs.py`，schema 完全交 Alembic |
| REMOVE_CANDIDATE | ❌ 过激——SQLite dev 仍有 create_all + seed 合法需求，seed 逻辑有业务价值 |

**推荐：`RESTRICT`（首选）→ 可演进至 `REPLACE`。**

### 4.6 设计方案（仅设计，不实施）

**RESTRICT 方案**（最小 diff）：

1. 在 `init_db()` 入口加 backend 守卫：
   - 读取 `get_database_runtime().backend`。
   - 若 `postgresql`：**拒绝执行 create_all**，打印明确错误并 `sys.exit(1)`，提示"PostgreSQL schema 必须由 `alembic upgrade head` 创建，参见 DB_BL_2B Ownership Contract"。
   - 若 `sqlite`：保持现有 `create_all` + seed 行为。
2. 该守卫与 `ensure_runtime_schema()` 的 PG skip 语义对齐，形成"runtime + bootstrap 工具"双重 PG create_all 拦截。
3. 同步更新 `README.md:75`：区分"SQLite 初始化用 init_db.py"与"PG 初始化用 alembic upgrade head"。
4. 同步更新 `RUNTIME_ENTRYPOINTS.md:242` lifecycle 注记：`ACTIVE / manual_only / SQLite-only (PG refused)`。

**REPLACE 方案**（RESTRICT 之后的可选演进，非本阶段强制）：

1. 将 `DEFAULT_CONFIGS` seed 逻辑抽到 `scripts/seed_default_configs.py`（backend 无关，仅 upsert CheckConfig）。
2. `init_db.py` 退化为 SQLite-only create_all 入口，或直接由 `ensure_runtime_schema()`（SQLite runtime）+ Alembic（PG）覆盖，`init_db.py` 可标 `DEPRECATED`。
3. 此方案引入新文件，遵循 YAGNI：仅当 RESTRICT 不足以满足时再走 REPLACE。当前 **RESTRICT 足够**。

**明确禁止**：本 2B 阶段不实施上述任何方案；属 2D 或独立实施审批。

---

## 5. Documentation Drift Plan

### 5.1 审计对象与分类

| 文档 | drift 表述 | 分类 | 处理 |
|---|---|---|---|
| `POSTGRESQL_CUTOVER_GAP_AUDIT.md` §1.2 | "app/main.py 导入 engine 后还会执行 `Base.metadata.create_all(bind=engine)`，因此直接切库大概率在启动阶段失败" | **HISTORICAL + SUPERSEDED**（P3-Z0 审计时间点事实；§15.5 P3-Z3 已记录"PG runtime 启动时不再执行 create_all"） | §1 头部加"以下为 P3-Z0 审计基线快照，部分结论已被后续阶段 supersede，见 §13/§15"；§1.2 该句加 inline 标记 `（SUPERSEDED — 见 §15.5 / 当前 ensure_runtime_schema() PG skip）`。保留历史不删除。 |
| `POSTGRESQL_CUTOVER_GAP_AUDIT.md` §6.2 | "app/main.py 不应在 production PG cutover 时依赖 create_all 自动建业务表；应改为 Alembic schema readiness 检查" | **CURRENT（建议已实现）** | 加注"已实现：`ensure_runtime_schema()` PG skip + `/ready` alembic head 校验"。 |
| `POSTGRESQL_MIGRATION_NOTES.md` L2392 | "app/main.py 又在启动阶段执行 `Base.metadata.create_all(bind=engine)`" | **HISTORICAL**（阶段快照） | 加 inline `（HISTORICAL — 当前 ensure_runtime_schema() PG 分支已 skip create_all，见 §39+）`。 |
| `POSTGRESQL_MIGRATION_NOTES.md` L2477 | "`Base.metadata.create_all` 风险仍需后续受控处理" | **HISTORICAL → 已 resolved** | 加注"（已 resolved：ensure_runtime_schema + /ready gate）"。 |
| `POSTGRESQL_MIGRATION_NOTES.md` L2560 | "ensure_runtime_schema() 保持 SQLite 自动建表，PG 下跳过 create_all" | **CURRENT** | 保持，作为该文档最新事实锚点。 |
| `POSTGRESQL_MIGRATION_NOTES.md` §1.6 | "head=0017（2026-07-28）" | **HISTORICAL**（已标注日期快照，当前 head=0034） | 已有日期标注，无需修改，仅需文档头部导航说明"各节为当时快照"。 |
| `ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md` L27 | "app/main.py 仍会执行 `create_all(bind=engine)`" | **HISTORICAL + SUPERSEDED**（P3-A 设计时的 SQLite 现状诊断） | 文档头部加"P3-A 设计快照，部分现状诊断已被后续实现 supersede"；L27 加 `（SUPERSEDED）`。 |
| `ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md` L141 | "建表唯一机制：create_all（app/database.py、app/main.py:51、scripts/init_db.py）" | **HISTORICAL + INCORRECT_CURRENT_DESCRIPTION**（行号 51 已失效，当前 273-285；PG 下 create_all 已非建表机制） | 加 `（HISTORICAL — 行号已失效，PG 建表机制现为 Alembic）`。 |
| `14_DB_MIGRATION_PLAN.md` L141/§Q1-Q2 | "建表唯一机制：create_all" + "create_all 建 + migration 演进共存" | **HISTORICAL for PG / partly CURRENT for SQLite** | 文档头部加"SQLite era 迁移方案设计；PG 域已被 Alembic 方案 supersede（见 ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md）；SQLite 过渡路径仍部分引用本设计"。保留不删。 |
| `README.md:75` | `python scripts/init_db.py` 开发指引 | **CURRENT（与 Model A 冲突）** | 随 §4 RESTRICT 实施同步更新：区分 SQLite（init_db.py）/ PG（alembic upgrade head）。**本 2B 不改 README，仅登记待更新。** |
| `RUNTIME_ENTRYPOINTS.md:242` | init_db.py = `ACTIVE / maintenance / manual_only` | **CURRENT（需随决策更新）** | 随 §4 RESTRICT 实施同步加 `SQLite-only (PG refused)` 注记。 |

### 5.2 doc-sync 原则

1. **不删除历史证据**：上述文档多为阶段累积流水账（P2-A → P3-D5+），有追溯价值，不删历史节。
2. **原位标注 superseded-by**：drift 表述加 inline 标记指向当前事实锚点，不"追加最新补充"式双写。
3. **文档头部加导航说明**：长篇流水账文档头部加"本文档为阶段累积记录，各节为当时快照，最新事实以 CLAUDE.md 治理状态 + SYSTEM_MAP 为准"。
4. **治理规则文件门槛**：01-04 规则文件不在本 drift 范围（较高修改门槛）。
5. **本 2B 阶段不实施 doc-sync**：仅登记 drift 清单与处理方案，实际回写属后续 doc-sync 任务或随 §4 实施同步。

---

## 6. DB-BL-2C Exact Reconciliation Target Baseline Contract

这是本阶段必须冻结的核心合同。

### 6.0 两层目标框架（审批回填）

> 本节经 `DB_BL_2B_APPROVAL.md` 审批 `APPROVED_WITH_CORRECTIONS` 后回填：原设计仅有 Layer 1（Canonical Final Target=0034）+ 单一对账，审批补入 Layer 2（Historical Reconciliation Anchor Candidate=0030）及三方独立比较。以下 §6.1–6.4 论证 Layer 1；§6.5–6.6 为执行纪律（含 Layer 2 的 0030 anchor 与 stamp 门禁）。

2C target 必须分**两层**定义，不得混为一个 target：

| 层 | 定义 | 用途 |
|---|---|---|
| **Layer 1 — Canonical Final Target** | 空 PG `alembic upgrade head`(→0034) 的 expected schema | 定义最终合法 schema；证明空库 bootstrap 能力；判断修复后是否达 head |
| **Layer 2 — Historical Reconciliation Anchor Candidate** | **0030**（候选，非已认定 revision） | 判断 legacy dev PG 是否精确等价于合法 revision 0030，决定 2D 是否有资格 `stamp 0030 → upgrade 0032/33/34` |

**Layer 2 选 0030 的理由（CODE_VERIFIED）**：0032 的 `down_revision = "0030"`；0031 已删（versions 目录无 0031 文件，Glob 核实）；0030 是进入当前三条待验证 migrations（0032/0033/0034）前最后一个 Alembic revision。

**Layer 2 冻结原则（不得违反）**：

> 不得因为"当前库少了 0032/33/34"就直接推断"当前库就是 0030"。
> 0030 是对账候选锚点，不是已认定 revision。
> 当前 dev PG 实际是否等价于 revision 0030，必须由 2C 三方比较中的"比较 1"独立证明，不得倒推。

### 6.1 Q5.1 — target 基于 ORM metadata 还是 Alembic revision expected schema？

**基于 Alembic revision expected schema**（即从空库 `alembic upgrade head` 产出的 schema），**不是 ORM metadata**。

理由：

1. Model A 下 **Alembic 链是 PG schema 唯一 authority**（§1.4）。2C 对账的"可信 baseline"必须是 authority 产出的 schema，而非另一来源。
2. `env.py` `target_metadata=None`（无 autogenerate），意味着 Alembic 链是**手写翻译**，与 ORM 是两个独立维护源——ORM metadata 不是 PG schema 的事实源。
3. 2A 已确认表级一致（链 60 表 == ORM 60 表，集合精确一致），但**列级/约束级未对账**（2A 留作 `column_level_reconciliation = NOT_DONE`）。若以 ORM 为 target，等于默认 ORM 永远正确——但 ORM 与链的 drift 正是 2C 要发现的。
4. 应用实际访问的 schema 由 Alembic 链构建（main.py PG skip create_all，依赖链建表），故"应用需要的 PG schema" = 链 expected schema。

### 6.2 Q5.2 — 对账到哪个 revision？

**`0034`（链 head）。**

理由：

- 0032/0033/0034 是 P1 Consumer Migration 三条 billing identity 实体（`daily_report_generations` / `ai_edit_material_analysis_executions` / `ai_preview_executions`），是 Technical Closure Blocker A 要解锁的目标表。
- dev PG 缺这三表 + `daily_report_jobs.current_generation_id` 列（2A 冻结事实 #9）。
- 2C 必须对账到 0034 才能判断"dev PG 重建后能否通过 0032/0033/0034 PG verification"。
- 链线性单链 0030→0032→0033→0034（0031 已删，避免与 SQLite 0031 编号混淆，见 0032 文件头注释），head=0034。

### 6.3 Q5.3 — 为什么是 Alembic expected schema + revision 0034？

综合 6.1 + 6.2：**2C target = 从空库 `alembic upgrade head`（→0034）产出的 expected schema（60 表 + 列 + 约束 + 索引）**。该 target 当前为 `STATIC_CHAIN_VERIFIED` + `PROJECTED`（2A 未实跑）；2C 需先在恢复连通的空 PG 上实跑 `upgrade head` 取得 expected schema 快照（`PG_RUNTIME_VERIFIED`），再与 dev PG actual schema 对账。

### 6.4 Q5.4 — 0032/0033/0034 在 2C 中属于 baseline 一部分，还是 baseline 修复后的后续正常 migrations？

**属于 baseline 一部分。**

- 0032/0033/0034 是 chain head（0034）的正常组成迁移，不是"修复 migration"——它们是合法的增量 billing identity 实体，已 MIGRATED（P1 11/11 Consumer Migration Complete）。
- 2C target baseline = 0034 expected schema（**含** 0032/0033/0034 三表 + current_generation_id 列）。
- 它们在 dev PG 上"如何落地"属于 **2D repair** 范畴（受控重建或受控 stamp-to-revision），不在 2C 定义 target 阶段。
- 区分：2C 定义"目标应该是什么"（含 0032/0033/0034 的 0034 baseline）；2D 决定"怎么让 dev PG 达到目标"。

### 6.5 禁止倒推 revision + Stamp 门禁

**禁止倒推原则**：不能先决定 stamp 哪个 revision，再反向证明 schema 与它一致。必须独立生成 expected schema → 独立 inspect actual → compare → decide equivalence。

**Stamp 门禁（冻结）**：

- 2C 对账完成前禁止 `alembic stamp` 任何 revision（含 0030 / 0034）。
- 仅当三方比较中的"比较 1"（Legacy Actual vs Expected@0030）在表、列、类型、nullable、default、PK、FK、unique、CHECK、index 等所需维度**全部证明等价**，未来 DB-BL-2D 才有资格把 `legitimate stamp 0030 → upgrade 0032 → upgrade 0033 → upgrade 0034` 作为候选 repair strategy。
- 若比较 1 结论为**不等价**：`STAMP 0030 MUST BE REJECTED`，禁止"先 stamp 0030 再修差异"。2D 须改走受控重建（空库 upgrade head）或其他独立审批的修复策略。
- stamp 仅用于 2D 受控 repair 后"schema 已被证明与某 revision 精确一致"的确认，须独立审批（2D），不在 2C 范围。
- 禁止为了让 dev PG"看起来一致"而调整 expected schema 或选择较低 revision 凑数。

### 6.6 2C 两份 expected + 三方独立比较矩阵

2C 必须在 disposable local PostgreSQL 中分别生成**两份独立 expected schema**（不得用一份推导另一份）：

```text
Expected-A = empty PG → alembic upgrade 0030
Expected-B = empty PG → alembic upgrade head / 0034
```

2C 必须执行**三种独立比较，不得混为一个 diff**（解决不同问题）：

```text
比较 1（Anchor 判定）:
    Legacy Dev PG Actual  vs  Expected-A @ 0030
    → 回答：当前遗留库是否精确等价于合法 revision 0030？
      （决定 2D 是否有资格 stamp 0030，见 §6.5 Stamp 门禁）

比较 2（合法增量 delta）:
    Expected-A @ 0030  vs  Expected-B @ 0034
    → 明确正常 Alembic 0032/0033/0034 应产生的 delta

比较 3（完整最终差异矩阵）:
    Legacy Actual  vs  Expected-B @ 0034
    → 完整差异矩阵（缺表/缺列/类型 drift/约束缺失/索引缺失）
```

**附加对账（应用一致性，独立检查，不改变 2C target 定义）**：

```text
ORM metadata（app/models.py 60 表）  vs  chain Expected-B @ 0034  列级对账
    → 验证 env.py target_metadata=None 的手写翻译无 drift
```

**2C 执行顺序（设计，不实施）**：

1. 恢复 PG 连通（Docker / 本地 PG）；不可用则 `AUTHORIZED_BUT_ENVIRONMENT_BLOCKED`，禁用 prod/staging。
2. 独立生成 Expected-A（空 PG upgrade 0030）+ Expected-B（空 PG upgrade head 0034），升格为 `PG_RUNTIME_VERIFIED`。
3. 独立导出 Legacy Dev PG Actual schema（只读）。
4. 执行三方比较 + 附加 ORM-vs-chain 列级对账。
5. 产出 gap 矩阵 + anchor 判定结论（是否精确等价 0030）。
6. 2C 完成后提交独立审批 DB-BL-2D（受控 repair，依据比较 1 结论决定 stamp-to-revision 或受控重建）。

---

## 7. Schema Authority Drift Prevention Design

设计未来如何防止再次出现 `create_all-built PG + no alembic_version`。遵循 YAGNI——只给最小必要机制。

### 7.1 现有机制（已实现，复用）

| 机制 | 状态 | 作用 |
|---|---|---|
| `ensure_runtime_schema()` PG skip create_all | ✅ 已实现（main.py:279-284） | runtime 不隐式建 PG 表 |
| `/ready` 校验 alembic_version == head | ✅ 已实现（health.py:62 + db_readiness） | PG 缺 `alembic_version` / 非 head → 503 unhealthy → 不接流量 |
| docker-compose healthcheck 用 /ready | ✅ 已实现 | 部署前未 upgrade head → unhealthy |
| env.py 强制 PG URL | ✅ 已实现 | 防止误对 SQLite 执行 PG 迁移 |

**结论**：生产/staging 路径已有 runtime + readiness 双重 gate，drift prevention 已基本落地。**缺口在 dev bootstrap 与 init_db.py**。

### 7.2 最小补强（仅设计，不实施）

| 机制 | 设计 | 优先级 | 归属 |
|---|---|---|---|
| `init_db.py` PG backend 守卫 | PG 下拒绝 create_all 并退出（§4.6 RESTRICT） | 高 | 2D / 独立实施 |
| README bootstrap 指引区分 backend | SQLite 用 init_db.py / PG 用 alembic upgrade head | 高 | 随 §4 实施同步 |
| 新 DB provisioning 文档 | 一页 bootstrap runbook：空库→upgrade head→/ready | 中 | doc-sync |
| CI 静态检查（可选） | grep 检查 `create_all(` 调用点不含 PG backend 路径 | 低 | YAGNI——当前 create_all 调用点已分类清楚（2A §4），无新增风险；仅当未来 create_all 调用点扩散再加 |

### 7.3 不建设的机制（YAGNI）

- 不建复杂数库平台 / schema 审批系统。
- 不引入额外 schema 版本表（Alembic `alembic_version` 已是唯一版本源）。
- 不为 SQLite 引入 Alembic（SQLite 是过渡库，create_all + schema_migrations 现状可接受）。
- 不在应用启动时自动执行 `alembic upgrade`（migration 是 deployment responsibility，非 runtime；`/ready` 只校验不执行）。

---

## 8. Risks / Open Questions

无法静态证明的事项，明确保留：

1. **空 PG → upgrade head 实跑未验证**（`PG_RUNTIME_NOT_VERIFIED`，2A 冻结）。当前 dev PG 不可达（2A §5）。2C 需恢复 PG 连通后实跑取得 expected schema。
2. **列级/约束级 ORM-vs-chain drift 未对账**（2A 留作 2C）。表级一致已确认，列级未做。
3. **dev PG 57 表确切成表路径** = `INFERRED`（init_db.py vs 更早 main.py，2A 修正项 5）。不影响 2B 设计结论。
4. **dev PG 数据可处置性** = `LIKELY_DISPOSABLE`（带验证缺口，2A 冻结 #10）。2D 任何重建/删除前须独立数据确认 Gate（核查行数/PII）。
5. **0032/0033/0034 在 dev PG 的落地路径**待 2D 决策（受控重建 vs 受控 stamp-to-revision），本 2B 不决策。
6. **2A 五项文字修正是否已原位回填**：若 2A 报告原位修正未落地，应在进 2C 前由 2A 窗口补齐；不阻塞本 2B 设计结论，但 2C 须以修正后事实为准。
7. **xg_douyin_ai_cs（9100）库**：本 2B 聚焦 `auto_wechat` 库；9100 库的 schema ownership 同理（Model A，独立 Alembic 链），但其 baseline 治理不在 P1 Blocker A 范围，按需独立推进。

---

## 9. Recommended Next Stage

**具备进入 `DB-BL-2C Exact Reconciliation` 的条件吗？**

**条件性具备 — CONDITIONAL READY**（审批已落地：`DB_BL_2B_APPROVAL.md` = `APPROVED_WITH_CORRECTIONS`，2C = `AUTHORIZED`，legacy dev PG `READ-ONLY`）。

| 2C 前置条件 | 状态 |
|---|---|
| Schema Authority 模型冻结（Model A） | ✅ 本 2B §1 冻结 |
| Ownership Contract 冻结 | ✅ 本 2B §2 冻结 |
| Bootstrap Contract 冻结 | ✅ 本 2B §3 冻结 |
| 2C target baseline 定义 | ✅ 本 2B §6 冻结（两层：Layer 1 canonical=0034 / Layer 2 anchor 候选=0030；三方比较；对账前禁止 stamp） |
| init_db.py 决策 | ✅ 本 2B §4 设计（RESTRICT，实施属 2D） |
| doc drift 清单 | ✅ 本 2B §5 登记（回写属后续） |
| 恢复 PG 连通 | ❌ 待 2C 实际执行时恢复（Docker / 本地 PG）；不可用则 `AUTHORIZED_BUT_ENVIRONMENT_BLOCKED`，禁用 prod/staging |
| 2A 五项文字修正回填 | ⚠️ 应在进 2C 前由 2A 窗口确认 |

**建议**：

1. 本 2B 设计报告审批已落地（`APPROVED_WITH_CORRECTIONS`）。
2. 进入 `DB-BL-2C Exact Reconciliation`（2C = AUTHORIZED，legacy dev PG READ-ONLY）：恢复 PG 连通 → 独立生成 Expected-A（空 PG upgrade 0030）+ Expected-B（空 PG upgrade head 0034）→ 三方比较（Actual vs 0030 / 0030 vs 0034 / Actual vs 0034）+ ORM-vs-chain 列级对账 → 产出 gap 矩阵 + anchor 判定。
3. 2C 完成后，独立审批 `DB-BL-2D`（受控 repair：dev PG 重建为空库 upgrade head，或受控 stamp-to-revision；恢复 PG 连通后补 0032/0033/0034 PG evidence）。
4. §4 init_db.py RESTRICT 与 §5 doc-sync 可作为独立小任务并行推进，不阻塞 2C（2C 是只读对账，init_db.py 守卫不影响对账）。

---

## 10. Implementation Status

```
DESIGN APPROVED (APPROVED_WITH_CORRECTIONS) — 2C AUTHORIZED (LEGACY DB READ-ONLY)
```

本 2B 阶段设计/审计已完成并经审批（`DB_BL_2B_APPROVAL.md` = `APPROVED_WITH_CORRECTIONS`）。本 2B 阶段仍不实施任何修复——未执行、且本阶段禁止执行：

- ❌ `alembic stamp`（任何 revision）
- ❌ 创建/修改 `alembic_version` 表
- ❌ repair migration
- ❌ DROP / recreate dev PG
- ❌ 删除或修改开发数据
- ❌ 修改 `scripts/init_db.py`（含 §4.6 RESTRICT 守卫——仅设计）
- ❌ 修改 `app/main.py` / `ensure_runtime_schema()` / create_all runtime behavior
- ❌ 执行 0032 / 0033 / 0034 upgrade
- ❌ 开始 57-table column/constraint/index exact diff（属 2C）
- ❌ 修改 P1 Consumer implementation / M07 Core
- ❌ production / staging deployment
- ❌ 回写 §5 文档 drift（属后续 doc-sync 任务）
- ❌ 自行进入 DB-BL-2C 实施或任何修复实施

审批已落地（见 `DB_BL_2B_APPROVAL.md`：`APPROVED_WITH_CORRECTIONS`，2C = `AUTHORIZED`，legacy dev PG `READ-ONLY`，disposable PG 可 controlled create/upgrade；环境不可用 = `AUTHORIZED_BUT_ENVIRONMENT_BLOCKED`）。进 2C 执行前须确认本 §6 修正项（Layer 2 / 0030 anchor / 三方比较 / stamp 门禁 / 禁止倒推）已回填冻结——本回填已完成。

---

## 附：关键证据索引

| 事实 | 证据文件 |
|---|---|
| 2A 冻结事实 11 条 | `docs/architecture/remediation/DB_BL_2A_APPROVAL.md` §4 |
| 2A 探索报告 | `docs/architecture/remediation/DB_BL_2A_MIGRATION_CHAIN_COMPLETENESS.md` |
| main.py PG skip create_all | `app/main.py:273-285` `ensure_runtime_schema()` |
| init_db.py 无条件 create_all | `scripts/init_db.py:16` |
| env.py PG-only / 无 autogenerate | `migrations/postgres/auto_wechat/env.py`（`target_metadata=None`） |
| /ready 校验 alembic head | `app/routers/health.py:62` + `app/db_readiness.py` |
| docker-compose /ready healthcheck | `docker-compose.yml:52-55`、`docker-compose.staging.yml:28` |
| 0001 空标记 | `migrations/postgres/auto_wechat/versions/0001_empty_baseline.py` |
| 链 head=0034 | `0030→0032→0033→0034`（0031 已删，线性单链） |
| 0032/0033/0034 billing identity | 三迁移文件头注释（P1 Stage 5C-4 / 5F-3 / 5G-2） |
| init_db.py 引用面 | `README.md:75`、`RUNTIME_ENTRYPOINTS.md:242`（Docker/CI 未引用） |
| 文档 drift 定位 | `POSTGRESQL_CUTOVER_GAP_AUDIT.md` §1.2/§6.2、`POSTGRESQL_MIGRATION_NOTES.md` L2392/L2477/L2560、`ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md` L27/L141、`14_DB_MIGRATION_PLAN.md` L141 |
