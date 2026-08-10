# DB-BL-2A — auto_wechat PostgreSQL Migration Chain Completeness Exploration

> 冻结日期：2026-08-10
> 阶段：P1 `COMPUTE-IDEMPOTENCY-001` Technical Closure / Blocker A（auto_wechat schema baseline）
> 模式：**READ-ONLY**（只读探索）
> 实施：**NOT AUTHORIZED**
> 前置检查点：`P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md`
> Source of truth：运行代码 / 迁移文件 / env.py / checkpoint 事实 > 历史文档

---

## 核心问题

> auto_wechat 的 Alembic migration chain 是否能够定义并构建一个完整、可信的新 PostgreSQL schema？

---

## DB-BL-2A RESULT

> **阶段状态（冻结）**：
> `APPROVED_WITH_CORRECTIONS` → `CORRECTIONS_APPLIED` → **`COMPLETE / FROZEN`**（2026-08-10）
>
> 审批窗口已独立技术审查（`DB_BL_2A_APPROVAL.md`），5 项证据等级 / 术语 / 因果表述修正已原位回写，不改变技术结论。本报告事实与证据等级可进入后续治理基线。
>
> **正式事实钉死（FROZEN FACTS）**：
>
> | 维度 | 冻结值 |
> |---|---|
> | Migration chain | `STATIC_CHAIN_VERIFIED`（链结构完整，无分支、无链外表引用） |
> | 空 PG `upgrade head` 实跑 | `PG_RUNTIME_NOT_VERIFIED`（未被任何已验证环境实际走过） |
> | 列级 / 约束级对账 | `NOT_DONE`（deferred to `DB-BL-2C`） |
> | PG code intent / runtime policy | `MODEL A`（Alembic-owned，main.py PG skip create_all） |
> | Legacy dev DB state | `MODEL B/C MIXED BASELINE`（create_all 快照 57 表、无 alembic_version） |
> | `scripts/init_db.py` provenance | `MOST PLAUSIBLE PROVENANCE`（`INFERRED`，非已证明事实） |
> | Empty DB → head 产出 | `PROJECTED` / `STATICALLY VERIFIED`（非 PG runtime verified） |
> | dev PG data disposability | `LIKELY_DISPOSABLE`（带验证缺口，销毁前独立确认 Gate） |
> | Root cause（直接事实） | dev PG 无 `alembic_version` + schema 落后 head → 无法安全推进 0032/0033/0034 |

### 1. Migration Chain Completeness

**`CONDITIONAL`**

> 证据分层标签（冻结）：
> - 链结构完整 = `STATIC_CHAIN_VERIFIED`
> - 空 PG `upgrade head` 实跑 = `PG_RUNTIME_NOT_VERIFIED`
> - 列级 / 约束级对账 = `NOT_DONE`（deferred to `DB-BL-2C`）
>
> **"静态 migration chain 结构完整" ≠ "已在真实空 PostgreSQL 执行 `upgrade head` 并验证成功"。本阶段不持有 PG runtime evidence。**

证据：

- Alembic 链 `0001_empty_baseline → 0034` 为**线性单链、无分支**。0031 源文件已删除，但 `0032.down_revision="0030"` 已正确重连，链无断裂（`versions/__pycache__/0031*.pyc` 仅为缓存残留，不影响链）。
- 链内共创建 **60 张业务表**（0001 不建表；0002-0034 逐批建表）。逐文件核对：0002(1) + 0003(4) + 0004(4) + 0005(2) + 0006(19) + 0008(15) + 0009(3) + 0010(1) + 0013(4) + 0015(1) + 0021(1) + 0026(1) + 0028(1) + 0032(1) + 0033(1) + 0034(1) = 60。
- ORM 模型 `app/models.py` 共定义 **60 个 `__tablename__`**。**集合完全一致**：链创建的 60 表 == ORM 定义的 60 表，无遗漏、无多余。
- **无链外表引用**：所有 `op.add_column` / `op.alter_column` / `op.create_foreign_key` / `op.create_index` / `op.create_unique_constraint` 的目标表，均在链内更早或同迁移中由 `op.create_table()` 创建。逐项验证通过（含 `sales_staff`/`douyin_leads`/`douyin_webhook_events` 等基础表由 0003 先建，0008/0009/0010/0032 等才 ALTER）。
- `env.py`：`target_metadata = None`（未接 autogenerate，纯迁移执行器）；强制要求 `DATABASE_URL` 为 PostgreSQL（非 SQLite）。

**为什么是 CONDITIONAL 而非 COMPLETE**：

1. **表级覆盖完整**（60/60 ORM 表，自举链），但从空库 `alembic upgrade head` 能否得到"应用需要的完整 schema"，还取决于**列级 / 约束级**定义是否与 ORM 一致——该项明确属于后续 `DB-BL-2C Exact Reconciliation`，本阶段不做 60 表 × 列 × 约束全量 diff。
2. 历史文档（`ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md`）记录"SQLite 迁移 SQL 与 ORM 模型处于并行维护状态"，PG Alembic 链是独立手写翻译，存在已知 drift 风险，未经列级对账前不能声明 COMPLETE。

**结论**：链**结构上具备**从空 PG 自举到 60 表 schema 的能力（无链外表依赖、表级 100% 覆盖 ORM），证据等级 `STATIC_CHAIN_VERIFIED`；空 PG `upgrade head` 实跑证据等级 `PG_RUNTIME_NOT_VERIFIED`（未被任何已验证环境实际走过）。"完整可信"待 2C 列级对账后才能升格为 COMPLETE。

---

### 2. 0001 Baseline Semantics

`0001_empty_baseline` 真实语义：**empty-database bootstrap marker，非 existing-schema baseline marker。**

代码事实（`versions/0001_empty_baseline.py`）：

```python
revision = "0001_empty_baseline"
down_revision = None

def upgrade() -> None:
    pass            # 不创建任何表
```

回答 4 个子问题：

1. **0001 是否创建基础业务表？** 否。`upgrade()` 为 `pass`，不建表、不 seed、不建 `alembic_version`（`alembic_version` 由 Alembic 框架在首次 `upgrade` 时自动创建，非迁移职责）。
2. **是否假设库已由 ORM/create_all 建好？** 否。0001 假设的是"完全空的 PG"。0002 起才 `create_table`，链自举。
3. **后续 migration 是否依赖 Alembic 未创建的既有表？** 否。全部 ALTER/FK/INDEX 目标表均在链内更早迁移创建（见第 1 节）。
4. **0001 是 empty bootstrap 还是 existing-schema marker？** 前者——**真正的空库 bootstrap marker**。

> 与 checkpoint DB-BL-2 待回答清单中"0001_empty_baseline 假设"的隐含不确定性对齐：已验证 0001 不假设任何既有 schema。

**关键张力**：0001 虽是空库 bootstrap，但 dev PG **并非**经由 0001→head 链构建，而是由 `Base.metadata.create_all()` 一次性快照建成（无 `alembic_version`）。因此 dev PG 的"基线"是一个不受控的 create_all 快照，不对应任何 Alembic revision——这是 baseline mismatch 的根因（见第 7 节）。

---

### 3. Empty Database Bootstrap Model

> 证据等级：链结构 + docker-compose `/ready` healthcheck 设计 = `STATIC_CHAIN_VERIFIED` + `CODE_VERIFIED`；空库 `upgrade head` 实跑 = `PG_RUNTIME_NOT_VERIFIED`（projected outcome，非 runtime-verified）。

**理论上，一个完全空的 PostgreSQL 如何得到合法 auto_wechat schema：**

```
空 PG database（0 表）
  ↓  设置 DATABASE_URL=postgresql+psycopg://...@host/auto_wechat
  ↓  cd migrations/postgres/auto_wechat && alembic upgrade head
  ↓
Alembic 框架自动创建 alembic_version 表
  ↓ 0001 pass（空标记）
  ↓ 0002 create knowledge_categories
  ↓ 0003 create sales_staff / douyin_leads / douyin_webhook_events / wechat_tasks
  ↓ ... 0004 ~ 0030（建表 + ALTER 既有链内表）
  ↓ 0032 create daily_report_generations + add daily_report_jobs.current_generation_id
  ↓ 0033 create ai_edit_material_analysis_executions
  ↓ 0034 create ai_preview_executions
  ↓
结果（projected / 理论推演产出）：60 业务表 + 1 alembic_version = 61 表，revision=0034
```

> **该产出为静态链推演的 expected outcome，非 runtime-verified 结果**（`PG_RUNTIME_NOT_VERIFIED`，未被任何已验证环境实际走过；列级一致性属 2C）。

- 该路径**不依赖** `create_all()`，链自举。
- 该路径**当前未被任何已验证环境实际走过**（dev PG 是 create_all 快照；staging/production 尚未 cutover）。
- `docker-compose.yml` healthcheck `/ready` 已要求"部署前必须先执行 alembic upgrade head，否则 alembic_revision 检查失败导致 unhealthy"——production 路径设计上就是空库→upgrade head，与本模型一致。
- **列级一致性未验证**：上述路径产出的列定义来自迁移文件，是否与 ORM 当前列定义逐列一致，属 2C。

---

### 4. create_all Current Role

全仓库 `Base.metadata.create_all(` 真实调用点分类（排除 `docs/` 引用与 `__pycache__`）：

| 调用点 | 分类 | PG 相关性 |
|---|---|---|
| `app/main.py:277` `ensure_runtime_schema()` | runtime startup | **SQLite-only**：`if backend=="sqlite": create_all; return`；PG 分支显式 `startup_skip_create_all` 后 return，**不调 create_all** |
| `scripts/init_db.py:16` `init_db()` | one-off bootstrap tooling | **无条件** create_all + seed CheckConfig。是 dev PG 57 表快照的 `MOST PLAUSIBLE PROVENANCE`（`INFERRED`：能证明该脚本具备在 PG backend 下建表的能力，无法证明它确实在 `DATABASE_URL=postgresql...` 下运行过） |
| `tests/helpers/outbox_restart_worker.py:280` | test helper | SQLite-only（`if backend=="sqlite"` 守卫） |
| `tests/helpers/p0_2_contact_trust_probe.py:287` | test helper | SQLite in-memory |
| `tests/test_agents_app.py` 等 ~10+ 测试 `setup_function` | test bootstrap | SQLite（drop_all + create_all） |
| `tests/test_ai_auto_reply_outbox_service.py` 等 | test bootstrap | SQLite in-memory / file |
| `tests/test_ai_edit_result_delivery.py` / `test_auth_context.py` | test bootstrap | SQLite |

**Q3 结论**：

> `create_all()` 当前**不承担** PostgreSQL 的正式 Schema Authority。

- PG runtime 路径（main.py）**显式跳过** create_all，设计上把 PG schema 交给 Alembic。
- create_all 在 PG 上的唯一非测试相关路径是 `scripts/init_db.py`（一次性 bootstrap 工具），它**历史上**建了 dev PG 的 57 表快照，但这是不受控的一次性产物，不是运行时 authority。
- create_all 的当前正式职责 = **SQLite dev/test 建表便利** + **init_db.py 一次性 bootstrap**。

> 纠正历史文档：`POSTGRESQL_CUTOVER_GAP_AUDIT.md` / `POSTGRESQL_MIGRATION_NOTES.md` 旧结论称"main.py 启动阶段仍执行 create_all"在 PG 下已**过期**——当前 `ensure_runtime_schema()` PG 分支已 skip。代码已演进，当前事实覆盖旧文档（drift 应在 2B/文档自治阶段回写）。

---

### 5. Current Development PG Data Disposability

**`LIKELY_DISPOSABLE`**（带验证缺口）

调查：

- **PG 当前不可达**：`Test-NetConnection 127.0.0.1:5432 → TcpOpen=False`；无运行中 docker 容器（`docker ps` 空）；本机无 `psql`。无法现场查行数。
- **无生产 env 指向该库**：`.env.lan.local`（当前 IDE 打开文件）为 `DATABASE_URL=sqlite:///./data/auto_wechat.db`；所有 `.env.*.example` 中仅 `.env.production.example` 用 PG（占位符）。无独立 `.env` / `.env.local` / `.env.production.local` 提交。
- **dev PG 来源**：create_all 快照（无 `alembic_version`），非 staging/production 数据库（staging 用 `docker-compose.staging.yml`，库名 `auto_wechat_staging`）。
- **表数 57 < 链 60**：dev PG 是旧 ORM 快照，缺 0032/0033/0034 三表，说明该库停留在 P1 Consumer Migration 之前的某个 dev 状态，不是生产数据沉淀。

归类理由：

- 全部间接证据（本地 dev、create_all 一次快照、无生产 env 指向、当前未运行、表数落后于链）指向 disposable 本地开发状态。
- **但未现场确认行数 / 是否含人工录入的测试商户或真实线索 PII**（LAN 联调可能写入真实留资手机号），故不声明 `DISPOSABLE`，留 `LIKELY_DISPOSABLE`。

> 本阶段不删除、不修改任何数据。 disposal 决策属 2B/2D，须先恢复 PG 连通并核查行数/PII 后再定。

---

### 6. Current Schema Authority

**拆分两层（避免把代码意图与遗留 DB 状态压成一个标签）：**

- **`CODE INTENT / CURRENT RUNTIME POLICY = MODEL A`**（Alembic 为 PG 唯一 schema authority）
  - 证据：`main.py` PG 分支 `ensure_runtime_schema()` skip create_all、`env.py` 强制 PG、CLAUDE.md 硬约束 #2"PostgreSQL 下禁止 create_all，必须先 Alembic"。
- **`LEGACY DEV DATABASE STATE = MODEL B/C MIXED BASELINE`**（create_all 快照 + Alembic 跟踪缺失并存，无可靠正式契约）
  - 证据：dev PG 由 create_all 建表（57 表，`MOST PLAUSIBLE PROVENANCE` = `INFERRED`），Alembic 跟踪从未建立（无 `alembic_version`）。
  - dev PG 的 create_all 快照不对应任何 Alembic revision（57 表介于 0030-era 与 head 之间，且列定义可能 drift），无法 `stamp` 到任何 revision 而不撒谎。
  - create_all 仍在 SQLite 路径与 init_db.py 活跃，Alembic 链完整但未对 dev PG 生效——典型的"两套并存且无契约"。

> 禁止表述："当前代码仍然同时使用 create_all + Alembic 管理 PG"——代码运行时策略（Model A 意图）与遗留 dev DB 状态（Model B/C 残骸）是两个不同层面，不得合并。

**RECOMMENDED FUTURE MODEL：`MODEL A`**（Alembic = sole schema constructor/evolution authority for PostgreSQL）

- 与代码意图、CLAUDE.md 硬约束 #2、docker-compose `/ready` healthcheck 设计一致。
- 落地路径（属 2B 设计，不实施）：PG 正式禁用 `init_db.py` 的 create_all（或改为断言 alembic_version 存在）；SQLite 保留 create_all 作为 dev/test 便利（可接受）；新环境一律空库 `alembic upgrade head`。
- 不建议 Model B（create_all baseline + Alembic incremental）作为 PG 未来模型——正是 Model B 的不受控快照导致了当前 mismatch。

---

### 7. Root Cause

**`SCHEMA_BASELINE_MISMATCH` 的产生根因：dev PG 的实际 schema 状态不对应任何 Alembic revision。**

时间线推演（provenance 项标注证据等级，与直接事实分开）：

1. 某时间点，`Base.metadata.create_all()`（经 `scripts/init_db.py` 或更早的 main.py）在 `DATABASE_URL=postgresql...` 下对空 PG 执行，一次性建成当时 ORM 模型对应的全部表（**57 表**）。—— **`INFERRED`**（`MOST PLAUSIBLE PROVENANCE`：能证明该脚本具备 PG 建表能力，无法证明其确实运行过；hypothesis，非已证明的唯一根因）。
2. **未写 `alembic_version`**——create_all 不产生 Alembic 跟踪。—— **`CODE_VERIFIED`**（直接事实：create_all 按定义不写 Alembic 跟踪）。
3. 之后 ORM 模型与迁移继续演进：新增 0032（`daily_report_generations` + `daily_report_jobs.current_generation_id`）、0033（`ai_edit_material_analysis_executions`）、0034（`ai_preview_executions`）。dev PG 的旧快照不含这 3 表 + 1 列。—— **`STATIC_CHAIN_VERIFIED`**（链结构与 checkpoint 8/9/10/11 一致）。
4. 现要对 0032/0033/0034 做 PG verification，Alembic 需知道 dev PG 当前 revision——但无 `alembic_version`，Alembic 无法定位。—— **`CODE_VERIFIED`**（直接事实，与 checkpoint 一致）。
5. `alembic upgrade head` 会失败：0002 `create_table("knowledge_categories")` 命中已存在表报错。—— **合理推断**（基于步骤 1-4）。
6. `alembic stamp head` 被本任务禁止（且是错的——会谎称 dev PG 已到 head，而它实际缺 0032/0033/0034 结构）。—— **`CODE_VERIFIED`**（禁止为本轮治理决定；"stamp 会伪造未验证等价"为直接事实推论）。
7. dev PG 的 create_all 快照不等于任何 revision（表数 57，列定义可能 drift）→ **无法安全推进** → `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH`。—— **直接事实**（足以解释当前 PG-MID blocker，不依赖步骤 1 的 provenance 是否被证明）。

> **根因直接事实**（`CODE_VERIFIED`）：dev PG 无 `alembic_version` 且 schema 落后于 head → upgrade 撞已存在表 / stamp head 伪造未验证等价 → 无法安全推进 0032/0033/0034。provenance（init_db.py vs 更早 main.py，步骤 1）为 `INFERRED`，非此根因成立的必要条件——不把"最可能由 init_db.py 创建"写成已证明的唯一根因。

直接对应 checkpoint：0032/0033/0034 三条 PG verification 均 `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH`（Daily Report / M05 / Preview）。

---

### 8. Recommended Next Stage

**进入 `DB-BL-2B Schema Ownership Design/Audit`**（不先跳 2C）。

理由：

- 2A 已回答"链能否构建完整 schema"→ **CONDITIONAL（表级完整，列级待 2C）**。
- 在做 2C 列级精确对账之前，必须先**设计/审计 schema ownership 模型**：
  - 正式确立 Model A（Alembic 为 PG 唯一 authority）；
  - 审计并规划 `init_db.py` create_all 在 PG 下的退役 / 改造；
  - 定义 dev PG baseline 重建策略（受控空库 upgrade head vs. stamp-to-revision 政策）；
  - 回写已 drift 的历史文档（CUTOVER_GAP_AUDIT / MIGRATION_NOTES 中"main.py 仍执行 create_all"等过期结论）。
- 2C Exact Reconciliation 需在 ownership 模型确定后才有对账基线与判定标准；repair 策略（2D）依赖 2B 的所有权决策 + 2C 的精确 gap。checkpoint 既定顺序 `2A → 2B → 2C → 2D` 合理，遵循之。

---

### 9. Implementation Status

**实施动作：`NOT STARTED` / `NOT AUTHORIZED`**（本阶段只读探索已完成并冻结；实施未开始、未授权）

> 2A 探索与事实冻结 = `COMPLETE / FROZEN`；本节"NOT STARTED / NOT AUTHORIZED"仅指**数据库实施动作**——二者不冲突：2A 冻结的是事实与证据等级，不是修复结果。

本阶段仅完成只读探索与事实记录。未执行、且本阶段禁止执行：

- ❌ `alembic stamp`（任何 revision）
- ❌ 创建或手改 `alembic_version`
- ❌ 写 repair migration
- ❌ DROP / recreate 当前 `auto_wechat` PG
- ❌ 修改开发数据 / `.env`
- ❌ 修改 `Base.metadata.create_all()` 调用路径
- ❌ 执行 0032 / 0033 / 0034 upgrade
- ❌ 修改 P1 Consumer 实现 / M07 Core
- ❌ 部署 production/staging

报告已通过审批窗口核验，2A 状态 `COMPLETE / FROZEN`；`DB-BL-2B` 已授权（`DESIGN/AUDIT ONLY`），等待启动。

---

## 附：关键证据索引

| 事实 | 证据文件 |
|---|---|
| 0001 空标记 | `migrations/postgres/auto_wechat/versions/0001_empty_baseline.py` |
| 链线性无分支 | 各 revision `down_revision` 逐文件核对（0031 已删，0032→0030 重连） |
| 链建 60 表 / 无链外表引用 | 0003/0004/0005/0006/0008/0009/0010/0013/0015/0021/0026/0028/0032/0033/0034 + ALTER 目标表逐项验证 |
| ORM 60 表 | `app/models.py` `__tablename__` × 60 |
| main.py PG skip create_all | `app/main.py:273-285` `ensure_runtime_schema()` |
| init_db.py 无条件 create_all | `scripts/init_db.py:16` |
| env.py PG-only / 无 autogenerate | `migrations/postgres/auto_wechat/env.py`（`target_metadata=None`） |
| dev PG 57 表 + 无 alembic_version | `P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md` Blocker A |
| dev PG 不可达 | `Test-NetConnection 127.0.0.1:5432 TcpOpen=False`，`docker ps` 空 |
