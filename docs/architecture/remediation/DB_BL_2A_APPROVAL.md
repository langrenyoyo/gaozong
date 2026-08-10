# DB-BL-2A — 审批窗口技术审查与授权决定

> 审批日期：2026-08-10
> 角色：DB-BL-2A 数据库基线治理审批窗口
> 审查对象：`docs/architecture/remediation/DB_BL_2A_MIGRATION_CHAIN_COMPLETENESS.md`
> 模式：**独立技术审查**（不复述探索窗口摘要，逐项以运行代码 / 迁移文件为事实源重新核验）
> 前置：`P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md` Blocker A
> Source of Truth：运行代码 / 迁移文件 / env.py / checkpoint 事实 > 历史文档

---

## 1. Technical Decision

```
APPROVED_WITH_CORRECTIONS → CORRECTIONS_APPLIED → COMPLETE / FROZEN
```

**核心事实全部独立复核通过**（链结构、表数 60 vs ORM 60、集合精确一致、无链外表引用、0001 空标记、main.py PG skip create_all、init_db.py 无条件 create_all、历史文档 drift 真实）。证据等级、术语与因果表述存在 5 处需原位修正的措辞问题，不影响 2A 结论成立，不影响 2B/2C 路线。故非 `CHANGES_REQUIRED`，但必须在进入 2B 前回写修正。

**5 项修正已于 2026-08-10 原位回写至 `DB_BL_2A_MIGRATION_CHAIN_COMPLETENESS.md`**（doc-sync 收口，不重新探索、不改技术结论，修正过程中未发现新事实冲突）。2A 状态冻结为 `COMPLETE / FROZEN`，正式事实钉死见报告 RESULT 区。

---

## 2. Evidence Review

逐项给出证据等级。严格区分 `CODE_VERIFIED` / `STATIC_CHAIN_VERIFIED` / `PG_RUNTIME_VERIFIED` / `INFERRED` / `UNKNOWN`。

### 2.1 Migration Chain Completeness

证据等级：`STATIC_CHAIN_VERIFIED`（静态链结构核验通过）；`PG_RUNTIME_NOT_VERIFIED`（未在真实空 PG 执行 `upgrade head`）。

独立核验结果：

- 迁移目录共 33 个 `.py` 文件（0001–0034，缺 0031）；逐文件 `revision` / `down_revision` 提取，链为**线性单链、无分支**，0031 源文件已删除，`0032.down_revision="0030"` 正确重连。报告此项**事实成立**。
- 链内 `op.create_table` 共 60 次、去重后**唯一 60 表**；每迁移建表数与报告逐项一致（0002(1)+0003(4)+0004(4)+0005(2)+0006(19)+0008(15)+0009(3)+0010(1)+0013(4)+0015(1)+0021(1)+0026(1)+0028(1)+0032(1)+0033(1)+0034(1)=60）。报告此项**事实成立**。
- ORM `app/models.py` `__tablename__` 计数 = **60**。链表集合与 ORM 表集合做精确 diff（`Compare-Object` 返回空）= **集合完全一致，无遗漏、无多余**。报告此项**事实成立**。
- 所有 `op.add_column` / `op.alter_column` / `op.drop_column` 目标表（第一参）、`op.create_index` / `op.create_foreign_key` / `op.create_unique_constraint` / `op.create_check_constraint` 目标表（第二参）共 53 个 distinct 表名，**全部为链内更早迁移创建的表，无链外表引用**。报告此项**事实成立**。
- `op.execute` 仅用于对链内已建表的 INSERT/UPDATE/ALTER（0008 seed、0011 SET NOT NULL、0012/0014/0021/0023/0025 UPDATE），**无 raw DDL 建表**，无遗漏的动态/条件/helper 建表。报告此项**事实成立**。
- `env.py`：`target_metadata = None`（纯执行器，未接 autogenerate），`_database_url()` 强制 `DATABASE_URL` 为 PostgreSQL。报告此项**事实成立**。

`CONDITIONAL` 作为状态命名可保留，但**必须叠加显式证据分层标签**（见 §3 修正项 1）。当前报告以散文表达"结构上具备 / 未被环境走过"，语义正确但未使用规范证据层标签，易被误读为 `PG_RUNTIME_VERIFIED`。

### 2.2 0001 Baseline Semantics

证据等级：`CODE_VERIFIED`。

- `0001_empty_baseline.py`：`revision="0001_empty_baseline"`，`down_revision=None`，`upgrade()=pass`，`downgrade()=pass`。**确为空标记，不建任何表、不 seed、不建 `alembic_version`**。
- 报告正确区分了两个层面："`0001` itself creates nothing" 与 "the revision chain after 0001 bootstraps the schema"——0002 起逐批 `create_table`，链自举。**未把两者混成一句话**。

报告此项无需修正，**通过**。

### 2.3 Empty PostgreSQL → Alembic Head 能力

证据等级：`STATIC_CHAIN_VERIFIED` + `CODE_VERIFIED`（链结构 + docker-compose `/ready` healthcheck 设计印证空库→upgrade head 路径）；**`PG_RUNTIME_NOT_VERIFIED`**（未实跑）。

报告已明确登记"该路径当前未被任何已验证环境实际走过"与"列级一致性未验证"。**未声称 `PG_VERIFIED`**。但第 3 节流程图末行"结果：60 业务表 + 1 alembic_version = 61 表，revision=0034"应标注为**projected/expected outcome**（理论推演结果），不得被读作 runtime-verified 结果（见 §3 修正项 3）。

### 2.4 create_all 运行时角色

证据等级：`CODE_VERIFIED`（调用点分类）；dev PG 57 表来源 = `INFERRED` / `MOST PLAUSIBLE PROVENANCE`。

独立核验：

- `app/main.py:273-285` `ensure_runtime_schema()`：SQLite 分支 `create_all(bind=engine)` 后 return；**PostgreSQL 分支显式记 `db_schema stage=startup_skip_create_all backend=postgresql` 后 return，不调 create_all**。报告此项**事实成立**。
- `scripts/init_db.py:16` `init_db()`：`Base.metadata.create_all(bind=engine)` **无条件**（无 backend 守卫），engine 来自 `app.database`（随 `DATABASE_URL` 决定后端），后接 CheckConfig seed。报告此项**事实成立**。

dev PG 57 表来源：报告用"最可能来源"措辞，属 `LIKELY` / `MOST PLAUSIBLE PROVENANCE`，**未升级为确定事实**——方向正确。但第 4 节表格内"曾在 `DATABASE_URL=postgresql...` 下运行"与第 7 节步骤 1 应一致标注为**推断**，不得读作已证明的运行史（见 §3 修正项 4、5）。

### 2.5 dev PG Provenance

证据等级：`INFERRED`（来源）；`UNKNOWN`（确切成表时间点 / 是否经更早 main.py 旧路径）。报告"create_all 快照 + 无 alembic_version + 非生产 env 指向 + 表数 57 落后于链 60"为间接证据链，结论保守合理。

### 2.6 dev PG Data Disposability

证据等级：`INFERRED` / `LIKELY_DISPOSABLE`（带验证缺口）；`UNKNOWN`（行数 / PII）。

报告保持 `LIKELY_DISPOSABLE`，**未升级为 `DISPOSABLE`**，并明确保留"数据销毁前独立确认 Gate"。这是足够保守的结论，**通过**。

### 2.7 Schema Authority

证据等级：`CODE_VERIFIED`（运行时策略 = Model A 意图）；`INFERRED`（遗留 dev DB 状态 = Model B/C 残骸）。

**报告此处存在过度合并**（见 §3 修正项 2）：第 6 节 headline `CURRENT FACT = MODEL C` 把"代码运行时策略意图（Model A）"与"遗留 dev PG 数据库状态（Model B/C 残骸）"两个不同层面压成一个标签。报告正文实际已分别讨论（"代码意图是 Model A" / "dev DB 现实是 Model B 残骸"），headline 仅需拆分对齐，无需推翻事实。

### 2.8 Root Cause

证据等级：直接事实（无 `alembic_version` + 57 表 ≠ head 60）= `CODE_VERIFIED`（与 checkpoint 8/9/10/11 一致）；provenance（init_db.py vs 更早 main.py）= `INFERRED`。

因果链中"dev PG 不对应任何 Alembic revision → upgrade 会撞已存在表 → stamp head 会伪造未验证等价 → `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH`"为**直接事实 + 合理推断**，足以解释当前 0032/0033/0034 PG-MID blocker。报告未把"最可能由 init_db.py 创建"写成已证明的唯一根因（用"或更早的 main.py"对冲），方向正确，仅需措辞一致化（见 §3 修正项 5）。

---

## 3. Required Corrections

以下 5 项需在 2A 报告内**原位修正**（不动结论、不改证据，仅修证据等级标签 / 术语 / 因果表述）。修正后方进入 2B。

### 修正项 1 — 显式证据分层标签（第 1、3 节）

在 `CONDITIONAL` 状态旁叠加规范证据层标签：

```
Migration Chain Completeness = CONDITIONAL
  evidence = STATIC_CHAIN_VERIFIED
  pg_runtime = PG_RUNTIME_NOT_VERIFIED
  column_level_reconciliation = NOT_DONE (deferred to 2C)
```

明确："静态 migration chain 结构完整"**不等于**"已在真实空 PostgreSQL 执行 `upgrade head` 并验证成功"。当前 2A 不持有 PG runtime evidence。

### 修正项 2 — Schema Authority 拆分两层（第 6 节 headline）

将单一 headline 拆为：

```
CODE INTENT / CURRENT RUNTIME POLICY = MODEL A
  （main.py PG skip create_all、env.py 强制 PG、CLAUDE.md 硬约束 #2）

LEGACY DEV DATABASE STATE = MODEL B/C MIXED BASELINE
  （dev PG create_all 快照 57 表、无 alembic_version、不对应任何 revision）
```

`RECOMMENDED FUTURE = MODEL A` 保留。禁止出现"当前代码仍然同时使用 create_all + Alembic 管理 PG"这种代码事实不支持的表述（报告正文未犯此错，仅 headline 需对齐）。

### 修正项 3 — 第 3 节流程图结果行标注

"结果：60 业务表 + 1 alembic_version = 61 表，revision=0034"改为**projected outcome**（理论推演产出），并注明"未被任何已验证环境实际走过；列级一致性属 2C"。避免被读作 runtime-verified 结果。

### 修正项 4 — init_db.py provenance 措辞统一（第 4 节表格）

"是 dev PG 57 表快照的最可能来源（曾在 `DATABASE_URL=postgresql...` 下运行）"中，括号内"曾在…下运行"标注为**推断**，统一为 `MOST PLAUSIBLE PROVENANCE`（无法证明该脚本确实在 PG URL 下运行过，仅能证明它具备该能力）。

### 修正项 5 — 第 7 节根因步骤 provenance 降级

步骤 1"经 `scripts/init_db.py` 或更早的 main.py"保留为 hypothesis；将其标注为 `INFERRED`，与直接事实（步骤 2 无 alembic_version、步骤 3 缺 0032/0033/0034）分开。不得让因果链读起来比证据更强。

---

## 4. DB-BL-2A Frozen Facts

以下为允许进入后续治理基线的正式事实（仅限证据等级 `CODE_VERIFIED` / `STATIC_CHAIN_VERIFIED` 项，推断项不冻结为事实）：

1. Alembic 链 `0001 → 0034` 为线性单链、无分支；0031 已删除，0032 正确 reconnect 到 0030（无断裂）。`STATIC_CHAIN_VERIFIED`。
2. 链静态创建 60 张业务表（0001 不建表）；ORM `app/models.py` 定义 60 个 `__tablename__`；**两集合精确一致**（无遗漏、无多余）。`STATIC_CHAIN_VERIFIED`。
3. 所有 ALTER / FK / INDEX / UNIQUE / CHECK 目标表均由链内更早迁移创建；无链外表引用；无 raw DDL 建表（`op.execute` 仅 INSERT/UPDATE/ALTER）。`STATIC_CHAIN_VERIFIED`。
4. `0001_empty_baseline` 是真正的空库 bootstrap marker（`upgrade()=pass`，不建表、不 seed、不建 `alembic_version`）；schema 由 0002 起的链自举。`CODE_VERIFIED`。
5. `env.py`：`target_metadata=None`（纯执行器），强制 `DATABASE_URL` 为 PostgreSQL。`CODE_VERIFIED`。
6. `app/main.py` `ensure_runtime_schema()` 在 PostgreSQL 分支**显式 skip `create_all`**；`create_all` 在 runtime 仅 SQLite 路径生效。`CODE_VERIFIED`。
7. `scripts/init_db.py` **无条件**调用 `create_all`（无 backend 守卫），是 dev PG 57 表快照的 `MOST PLAUSIBLE PROVENANCE`（推断，非已证明）。`INFERRED`。
8. 历史 `POSTGRESQL_MIGRATION_NOTES.md` / `POSTGRESQL_CUTOVER_GAP_AUDIT.md` 中"main.py 启动阶段执行 create_all"描述为**已 drift 的旧结论**（代码已演进为 PG skip）。drift 真实存在，待 2B 回写。`CODE_VERIFIED`。
9. dev PG 状态：57 表、无 `alembic_version`、不对应任何 Alembic revision；表数落后于链 head（缺 0032/0033/0034 三表）。`CODE_VERIFIED`（与 checkpoint 8/9/10/11 一致）。
10. dev PG 数据可处置性 = `LIKELY_DISPOSABLE`（带验证缺口，未现场确认行数/PII）；**销毁前必须独立确认 Gate**。`INFERRED`。
11. 当前 `SCHEMA_BASELINE_MISMATCH` 根因（直接事实）：dev PG 无 `alembic_version` 且 schema 落后于 head → `upgrade head` 会撞已存在表、`stamp head` 会伪造未验证等价 → 无法安全推进 0032/0033/0034。`CODE_VERIFIED`。

**未冻结（保留为推断 / 待验证）：**

- 链在真实空 PG `upgrade head` 是否产出与应用一致的可运行 schema = `PG_RUNTIME_NOT_VERIFIED`（待 2C 列级对账 + 恢复 PG 连通后验证）。
- 57 表 dev PG 的确切成表路径（init_db.py vs 更早 main.py）= `INFERRED`。

---

## 5. DB-BL-2B Authorization

```
AUTHORIZED — DESIGN / AUDIT ONLY
```

**2A 核心事实已独立复核通过，批准进入 `DB-BL-2B — Schema Ownership Design/Audit`。**

### 2B 授权目标范围（只读设计 / 审计）

1. 冻结 PostgreSQL Schema Authority 的正式目标模型（Model A：Alembic 为 PG 唯一 schema constructor/evolution authority）。
2. 明确 Alembic 与 `create_all` 的职责边界（PG = Alembic sole；SQLite = create_all dev/test 便利；init_db.py 一次性 bootstrap 的未来角色）。
3. 审计并设计 `scripts/init_db.py` 在 PG 下的退役 / 改造方案（如改为断言 `alembic_version` 存在、或拒绝 PG backend），**仅出方案不实施**。
4. 登记并设计修正已 drift 的历史 PostgreSQL 文档（`POSTGRESQL_MIGRATION_NOTES.md` / `POSTGRESQL_CUTOVER_GAP_AUDIT.md` 中"main.py 仍执行 create_all"等过期结论）——本 2A 已确认 drift 真实，2B 可提出文档回写 proposal。
5. 明确新开发 PostgreSQL 数据库的正式 bootstrap contract（空库 → `alembic upgrade head`）。
6. 为后续 `DB-BL-2C Exact Reconciliation` 定义"目标 schema / baseline"的判定标准（即以 Alembic head 列级定义为对账基线）。
7. 产出 dev PG baseline 重建策略选项（受控空库 upgrade head vs. stamp-to-revision 政策），**仅设计，不执行**。

### 2B 允许

- READ-ONLY code audit
- design / ownership contract / bootstrap contract
- documentation proposal
- deprecation proposal
- repair 策略选项设计（不实施）

---

## 6. Explicitly Forbidden

2A 与 2B 阶段均**禁止**以下动作，必须等待后续独立审批：

```
NO alembic stamp（任何 revision）
NO 修改 alembic_version 表
NO repair migration
NO DROP / recreate dev PG
NO 删除现有数据
NO 修改 / 退役 init_db.py
NO 修改 create_all runtime 行为
NO 执行 0032 / 0033 / 0034 upgrade
NO 直接进入 57-table exact reconciliation（属 2C，须 2B ownership 模型先冻结）
NO production / staging deployment
```

---

## 7. Technical Closure Impact

DB-BL-2A 对 P1 Technical Closure 的影响：

- **Daily Report 0032 / M05 0033 / Preview 0034**：三条 PG verification 仍维持 `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH`。2A **未解除**该 blocker——2A 只读探索完成、事实已冻结，但 dev PG 既无 `alembic_version` 又缺目标表/列，0032/0033/0034 无法在当前 dev PG 上验证。
- **解除路径**：须经 `DB-BL-2B`（ownership 设计）→ `DB-BL-2C`（列级精确对账 + 目标 baseline 定义）→ 独立审批的 `DB-BL-2D`（受控 repair：dev PG 重建为空库 upgrade head 或受控 stamp-to-revision，恢复 PG 连通后补 0032/0033/0034 PG evidence）。2A 不是解除路径，是事实冻结。
- **P1 Technical Closure**：`CONSUMER_MIGRATION = 11/11 COMPLETE` 不受影响；`TECHNICAL_CLOSURE = PENDING` 不变；`COMPUTE-IDEMPOTENCY-001` Root Issue 仍 `OPEN`。Technical Closure 四个 Blocker 中 Blocker A（auto_wechat schema baseline）从"未探索"推进到"事实已冻结 + 2B 已授权"，但**未关闭**。
- **RAG Query 0005**（Blocker B，`BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT`）与本 2A 无关，独立推进。

> 2A 冻结的是事实与证据等级，不是修复结果。Technical Closure 的解除依赖后续 2B/2C/2D 与独立实施审批，本轮不产生任何 runtime 修复。

---

**审批结论**：`APPROVED_WITH_CORRECTIONS` → 回写 §3 五项修正 → `DB-BL-2B AUTHORIZED (DESIGN/AUDIT ONLY)`。

完成审批报告，停止。不自行开始 2B，不输出可直接执行的数据库修复命令。
