# DB-BL-2B — Schema Ownership Design 审批报告

> 审批日期：2026-08-10
> 审批窗口：DB-BL-2B Schema Ownership Design / Audit
> 审查对象：`docs/architecture/remediation/DB_BL_2B_SCHEMA_OWNERSHIP_DESIGN.md`
> 前置：`DB_BL_2A_APPROVAL.md`（`APPROVED_WITH_CORRECTIONS` → 5 项修正 `CORRECTIONS_APPLIED` → 2A `COMPLETE / FROZEN`）
> 审查方法：独立读取设计文档 + 对应代码/迁移/配置/文档，非复述探索窗口摘要
> 模式：**DESIGN / AUDIT ONLY**（不实施任何数据库修复或代码改动）

---

## 1. Technical Decision

```
APPROVED_WITH_CORRECTIONS
```

主方向成立：Schema Authority = Model A、PostgreSQL Bootstrap Contract = 空 PG → alembic upgrade head、`init_db.py` = RESTRICT、Documentation Drift 分类与处理原则、Drift Prevention 复用现有机制 + YAGNI 补强——均经独立代码核验为真，可直接冻结。

唯一必须修正项在 **§6 DB-BL-2C Target Baseline Contract**：设计报告只定义了 Canonical Final Target（0034）和单一对账（actual vs 0034），**遗漏了 Historical Reconciliation Anchor Candidate（0030）这一层及其三方独立比较**。这是 Q5 明确要求的最关键部分，不补入则 2C 无法判断 legacy dev PG 是否精确等价于合法 revision 0030，进而 2D 的 `stamp 0030 → upgrade 0032/33/34` 受控修复路径无证据基础。该修正为 Target Contract 的增补，不推翻设计的任何主结论，故为 `APPROVED_WITH_CORRECTIONS` 而非 `CHANGES_REQUIRED`。

> 审批窗口重申纪律：本报告只冻结设计、不实施。下列 2C 修正项是 2C 进入前必须先回写到 2B 设计文档的合同条款，不是 2C 执行时才补的细则。

---

## 2. Schema Authority Contract

逐环境冻结（核验依据见 §7 证据等级）：

| 环境 | Schema Owner | `create_all()` 许可 | Alembic 角色 | 核验依据 |
|---|---|---|---|---|
| **production PG** | Alembic | ❌ 禁止 | sole constructor + evolution | main.py:279-284 PG skip；env.py PG-only；/ready 强制 head；docker-compose /ready healthcheck；CLAUDE.md 硬约束 #2 |
| **staging PG** | Alembic | ❌ 禁止 | sole constructor + evolution | 同 production；docker-compose.staging.yml:28"部署前对两个 staging database 各执行一次 alembic upgrade head" |
| **development PG（新建）** | Alembic | ❌ 禁止 | sole constructor + evolution | 新 dev PG 一律空库 `alembic upgrade head`；main.py PG skip 对新库同样生效 |
| **development PG（legacy 57 表残骸）** | **无合法 owner（待治理残骸）** | ❌ 禁止（不得再 create_all） | 当前不对应任何 revision（无 `alembic_version`） | 2A 冻结事实 #9；属 2C 对账 + 2D 受控修复对象，**不作为模板** |
| **SQLite（dev/test 过渡库）** | `create_all`（runtime） | ✅ 允许 | 不适用（SQLite 不走 Alembic PG 链） | main.py:276-278 SQLite 分支；CLAUDE.md 硬约束 #2 |
| **automated tests** | test fixture | ✅ 允许（仅 SQLite engine） | 不适用 | tests/ 下 `create_all` 全部绑定 SQLite/内存 engine（grep 核实）；PG schema 测试走独立 dev PG + alembic upgrade head |

**关键边界（冻结）**：

- `create_all()` 合法范围 = **仅 SQLite backend**（runtime + test + 一次性 dev seed/smoke）。
- `create_all()` 在 **PostgreSQL backend 下禁止**，无论 runtime、`init_db.py`、还是手工。
- `migrations/postgres/auto_wechat/` 是 `auto_wechat` database 唯一 PG schema authority；`migrations/postgres/xg_douyin_ai_cs/` 是 `xg_douyin_ai_cs` database 唯一 PG schema authority（两链独立，env.py 分别读 `DATABASE_URL` / `RAG_DATABASE_URL`）。
- **SQLite 的合法 `create_all` 不得自动推导为 PostgreSQL 也允许 `create_all`**——这是当前 dev PG 57 表残骸的根因，禁止重蹈。

**两层不可混淆（冻结）**：

```
CURRENT CODE / RUNTIME POLICY = MODEL A
    （main.py PG skip + env.py PG-only + /ready 强制 head + docker-compose upgrade head + CLAUDE.md 硬约束）

LEGACY DEVELOPMENT DATABASE STATE = MODEL B/C MIXED BASELINE
    （dev PG 57 表 create_all 快照 + 无 alembic_version + 不对应任何 revision；待治理残骸）
```

审批报告任何位置禁止合并为一句"Current Schema Authority = Model C"。

---

## 3. Bootstrap Contract

**合法新 PostgreSQL database 创建流程（冻结，候选 A）**：

```text
1. 创建空 database（CREATE DATABASE auto_wechat / xg_douyin_ai_cs）
2. 设置 DATABASE_URL=postgresql+psycopg://...@host/auto_wechat
3. cd migrations/postgres/auto_wechat
4. alembic upgrade head
   → 框架自动建 alembic_version（非迁移职责，2A 冻结事实 #4）
   → 0001 pass（空标记，CODE_VERIFIED）
   → 0002-0034 逐批建 60 业务表 + ALTER/索引/约束
   → 结果：60 业务表 + 1 alembic_version，revision=0034
5. 启动应用 → /ready 校验 alembic head + database 名 + 关键表 → 通过才接流量
```

**硬约束（冻结）**：

- 步骤 4 必须在步骤 5（应用接流量）之前完成。
- 业务表全部由 Alembic 链创建（0002-0034 逐批 `create_table`），禁止 `create_all` 建业务表。
- `alembic_version` 由 Alembic 框架在首次 `upgrade` 时自动创建，非迁移职责。
- application startup 禁止隐式补 PG schema（`ensure_runtime_schema()` PG 分支 skip；缺失由 `/ready` 503 暴露，不隐式补）。
- migration 属 deployment/bootstrap responsibility，非 runtime；`/ready` 只验证不执行 migration。
- 禁止用 `init_db.py` / `create_all` 替代步骤 4。
- 禁止 `alembic stamp` 跳过步骤 4——stamp 仅用于"已通过 2C 对账证明 schema 与某 revision 精确一致"的受控场景，且须独立审批（2D）。

**证据等级**：该路径当前为 `STATIC_CHAIN_VERIFIED` + `PROJECTED`，**尚未在真实空 PG 实跑验证**（2A `PG_RUNTIME_NOT_VERIFIED`）。2C 恢复 PG 连通后须先实跑 `upgrade head` 取得 expected schema 快照，升格为 `PG_RUNTIME_VERIFIED`，再与 dev PG actual 对账。**本阶段冻结的是 Contract，不宣称该流程已完成真实 PG E2E 验证。**

---

## 4. init_db.py Decision

```
RESTRICT
```

（首选；可演进至 REPLACE，非本阶段强制。）

**核验事实（CODE_VERIFIED）**：

- `scripts/init_db.py:16` `Base.metadata.create_all(bind=engine)` **无条件，无 backend 守卫**；engine 来自 `app.database`，随 `DATABASE_URL` 决定后端——若在 PG URL 下运行会无守卫对 PG 执行 create_all。
- `README.md:75` `python scripts/init_db.py` 为开发指引，**未区分 backend**——现实触发点。
- `RUNTIME_ENTRYPOINTS.md:242` 标 `ACTIVE / maintenance / manual_only / PLATFORM / DB 初始化`。
- Dockerfile / docker-compose / CI：**grep 核实无 `init_db` 调用**（无自动化风险）。
- 9100 `apps/xg_douyin_ai_cs/rag/database.py` 的 `init_db()` 是**不同函数**（SQLite 兼容层，PG 下主动报错指向 `get_rag_engine()`），不混淆但同名易误读。
- SQLite dev 库初始化（create_all + seed）仍合法（Ownership Contract §2）。

**RESTRICT 比 KEEP/DELETE 更符合最小改动原则**：

- KEEP = 保留无守卫 PG create_all 风险（否决）。
- DELETE/REMOVE_CANDIDATE = 过激——SQLite dev 仍有 create_all + seed 合法需求，seed 逻辑有业务价值。
- RESTRICT = 保留脚本 + 加 PG backend 守卫（PG 下拒绝 create_all 并 `sys.exit(1)`，仅 SQLite 允许）+ seed 独立化，最小 diff 且与 `ensure_runtime_schema()` PG skip 语义对齐，形成 runtime + bootstrap 工具双重 PG create_all 拦截。

**实施范围**：属 2D 或独立实施审批，**本 2B 阶段不实施**。实施时同步更新 README:75（区分 SQLite 用 init_db.py / PG 用 alembic upgrade head）与 RUNTIME_ENTRYPOINTS.md:242（加 `SQLite-only (PG refused)` 注记）。

---

## 5. Documentation Drift Decision

原则：**不删除历史证据**；任何可能误导判断"当前 PG runtime 仍 create_all"的 current-facing 文档必须最终得到纠正。本 2B 阶段仅登记清单与处理方案，实际回写属后续 doc-sync 任务或随 §4 RESTRICT 实施同步。

后续需回写项：

| 文档 | drift 表述 | 分类 | 处理 |
|---|---|---|---|
| `POSTGRESQL_CUTOVER_GAP_AUDIT.md` §1.2 / L10 | "app/main.py 导入 engine 后还会执行 create_all" | HISTORICAL + SUPERSEDED | §1 头部加"P3-Z0 审计基线快照"导航；该句加 inline `（SUPERSEDED — 见 §15.5 / 当前 ensure_runtime_schema() PG skip）`。保留不删。 |
| `POSTGRESQL_CUTOVER_GAP_AUDIT.md` §6.2 | "不应依赖 create_all，应改 Alembic readiness" | CURRENT（建议已实现） | 加注"已实现：ensure_runtime_schema() PG skip + /ready alembic head 校验"。 |
| `POSTGRESQL_MIGRATION_NOTES.md` L2392 | "app/main.py 又在启动阶段执行 create_all" | HISTORICAL | 加 inline `（HISTORICAL — 当前 ensure_runtime_schema() PG 分支已 skip create_all）`。 |
| `POSTGRESQL_MIGRATION_NOTES.md` L2477 | "create_all 风险仍需后续受控处理" | HISTORICAL → 已 resolved | 加注"（已 resolved：ensure_runtime_schema + /ready gate）"。 |
| `ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md` L27 | "app/main.py 仍会执行 create_all" | HISTORICAL + SUPERSEDED | 文档头部加"P3-A 设计快照"导航；L27 加 `（SUPERSEDED）`。 |
| `ALEMBIC_POSTGRESQL_MIGRATION_DESIGN.md` L141 | "建表唯一机制：create_all（行号 51）" | HISTORICAL + INCORRECT_CURRENT_DESCRIPTION | 加 `（HISTORICAL — 行号已失效[当前 273-285]，PG 建表机制现为 Alembic）`。 |
| `14_DB_MIGRATION_PLAN.md` L141/§Q1-Q2 | "建表唯一机制：create_all" + "create_all 建 + migration 共存" | HISTORICAL for PG / partly CURRENT for SQLite | 文档头部加"SQLite era 设计；PG 域已被 Alembic supersede"。保留不删。 |
| `README.md:75` | `python scripts/init_db.py` 无 backend 区分 | CURRENT（与 Model A 冲突） | 随 §4 RESTRICT 实施同步更新。**本 2B 不改 README，仅登记。** |
| `RUNTIME_ENTRYPOINTS.md:242` | `ACTIVE / maintenance / manual_only` | CURRENT（需随决策更新） | 随 §4 RESTRICT 实施同步加 `SQLite-only (PG refused)`。 |

治理规则文件 01-04 不在本 drift 范围（较高修改门槛）。

---

## 6. DB-BL-2C Target Baseline Contract

**采用两层目标（冻结）。设计报告 §6 原本只定义 Layer 1，本审批补入 Layer 2 及三方比较——此为本审批的核心修正项。**

### 6.1 Layer 1 — Canonical Final Target

```
EMPTY PostgreSQL
  → alembic upgrade head
  → expected schema @ 0034（60 表 + 列 + 类型 + nullable + default + PK + FK + unique + CHECK + index）
```

用途：

- 定义最终合法 auto_wechat PostgreSQL schema。
- 证明 migration chain 的真实空库 bootstrap 能力（实跑后升格 `PG_RUNTIME_VERIFIED`）。
- 最终判断修复后的数据库是否达到当前 head。

**采用 0034 作为 canonical final target**：0032/0033/0034 是 P1 Consumer Migration 三条 billing identity 实体（`daily_report_generations` / `ai_edit_material_analysis_executions` / `ai_preview_executions`），是 Technical Closure Blocker A 要解锁的目标表；0034 是链 head（线性单链 0030→0032→0033→0034，0031 已删）。2C 必须对账到 0034 才能判断 dev PG 重建后能否通过 0032/0033/0034 PG verification。

### 6.2 Layer 2 — Historical Reconciliation Anchor Candidate（★ 本审批补入）

```
候选 = 0030
原则：0030 = reconciliation candidate
      NOT assumed current revision
```

理由（已独立核验）：

- 0032 的 `down_revision = "0030"`（CODE_VERIFIED，见 `0032_daily_report_generations.py:22`）。
- 0031 已删除（versions 目录无 0031 文件，Glob 核实；0032 文件头注释确认"revision 用 0032 而非 0031，避免与 SQLite 0031 编号语义混淆"）。
- legacy dev PG 当前缺少 0032/0033/0034 对应新结构（2A 冻结事实 #9）。
- 0030 是进入当前三条待验证 migrations 前最后一个 Alembic revision。

**冻结原则（不得违反）**：

> 不得因为"当前库少了 0032/33/34"就直接推断"当前库就是 0030"。
> 0030 是对账候选锚点，不是已认定 revision。
> 当前 dev PG 实际是否等价于 revision 0030，必须由 2C 独立对账证明，不得倒推。

### 6.3 2C 必须生成两份独立 expected schema（★ 本审批补入）

未来 DB-BL-2C 在 disposable local PostgreSQL 中分别生成：

```
Expected-A = empty PG → alembic upgrade 0030
Expected-B = empty PG → alembic upgrade head / 0034
```

两份都必须独立生成，不得用一份推导另一份。

### 6.4 2C 必须执行三种独立比较（★ 本审批补入 — 替换设计报告 §6.6 的单一对账矩阵）

设计报告 §6.6 原定义仅一种比较（expected@0034 vs actual + ORM-vs-chain）。**本审批要求 2C 执行三种比较，解决不同问题，不得混为一个 diff**：

```
比较 1（Anchor 判定）:
    Legacy Dev PG Actual  vs  Expected-A @ 0030
    → 回答：当前遗留库是否精确等价于合法 revision 0030？

比较 2（合法增量 delta）:
    Expected-A @ 0030  vs  Expected-B @ 0034
    → 明确正常 Alembic 0032/0033/0034 应产生的 delta

比较 3（完整最终差异矩阵）:
    Legacy Actual  vs  Expected-B @ 0034
    → 生成完整最终差异矩阵（含缺失表/列/类型 drift/约束缺失）

附加（应用一致性，独立检查，不改变 target 定义）:
    ORM metadata（app/models.py 60 表）  vs  chain Expected-B @ 0034  列级对账
```

### 6.5 Stamp 门禁（★ 本审批补入）

只有当：

```
Actual Dev PG  ==  Expected Schema @ 0030
```

在 **表、列、类型、nullable、default、PK、FK、unique、CHECK、index** 等所需维度**全部得到证明**（比较 1 的结论），未来 DB-BL-2D 才有资格把：

```
legitimate stamp 0030 → upgrade 0032 → upgrade 0033 → upgrade 0034
```

作为候选 repair strategy。

如果比较 1 结论为**不等价**：

```
STAMP 0030  MUST BE REJECTED
```

不得"先 stamp 再修差异"。2D 须改走受控重建（空库 upgrade head）或其他独立审批的修复策略，且 2D 任何重建/删除前须独立数据确认 Gate（核查行数/PII，2A 冻结 #10 `LIKELY_DISPOSABLE`）。

### 6.6 2C 禁止倒推 revision（冻结）

必须：

```
generate expected 0030 independently
  → inspect actual independently
  → compare
  → decide equivalence
```

禁止：

```
看当前 DB 像 0030 → 决定 stamp 0030 → 再寻找证据证明它是 0030
```

### 6.7 target 基于 Alembic expected schema，不是 ORM metadata（确认设计报告 §6.1 正确）

2C 对账的"可信 baseline"必须是 authority（Alembic 链）产出的 schema。`env.py` `target_metadata=None`（无 autogenerate），Alembic 链是手写翻译，与 ORM 是两个独立维护源——ORM metadata 不是 PG schema 事实源。2A 已确认表级一致（链 60 == ORM 60），但列级/约束级未对账；以 ORM 为 target 等于默认 ORM 永远正确，而 ORM-vs-chain drift 正是 2C 要发现的。设计报告 §6.1 结论**成立，核准**。

### 6.8 0032/0033/0034 属 baseline 一部分（确认设计报告 §6.4 正确）

0032/0033/0034 是 chain head（0034）的正常组成迁移，不是"修复 migration"——是合法增量 billing identity 实体，已 MIGRATED（P1 11/11）。2C target baseline = 0034 expected schema（**含**三表 + `daily_report_jobs.current_generation_id` 列）。它们在 dev PG 上"如何落地"属 2D repair 范畴，不在 2C 定义 target 阶段。设计报告 §6.4 结论**成立，核准**。

---

## 7. Evidence Levels

| 事实 | 证据等级 | 说明 |
|---|---|---|
| main.py PG skip create_all | `CODE_VERIFIED` | main.py:279-284 直接读取 |
| env.py `target_metadata=None` + PG-only | `CODE_VERIFIED` | env.py:24, 27-35 直接读取 |
| /ready 校验 alembic_version == head | `CODE_VERIFIED` | health.py:62 + db_readiness.py:186-193（actual_revs == expected_heads，expected_heads 来自 ScriptDirectory.get_heads()，只读不执行 upgrade/create） |
| docker-compose /ready healthcheck | `CODE_VERIFIED` | docker-compose.yml:51-59、staging:28 |
| init_db.py 无条件 create_all | `CODE_VERIFIED` | init_db.py:16 直接读取 |
| init_db.py 引用面（README/RUNTIME_ENTRYPOINTS，Docker/CI 无引用） | `CODE_VERIFIED` | grep 核实 |
| 0001 空标记（upgrade=pass, down_revision=None） | `CODE_VERIFIED` | 0001_empty_baseline.py:6-13 |
| 链 0030→0032→0033→0034 线性单链 | `CODE_VERIFIED` | 0030:down=0029；0032:down=0030；0033:down=0032；0034:down=0033 |
| 0031 已删 | `CODE_VERIFIED` | versions 目录无 0031 文件（Glob 核实）+ 0032 文件头注释 |
| ORM 60 表 == 链 60 表（集合精确一致） | `STATIC_CHAIN_VERIFIED` | 2A 冻结，本 2B 沿用未重验 |
| 空 PG → upgrade head → 0034 expected schema | `STATIC_CHAIN_VERIFIED` + `PROJECTED` | 链静态可推演，但 2A 未实跑；2C 实跑前不得升格 |
| dev PG 57 表无 alembic_version / 不对应任何 revision | 2A `CODE_VERIFIED` | 2A 冻结事实 #9（dev PG 当前不可达，2C 恢复连通后复核） |
| dev PG 57 表确切成表路径（init_db.py vs 更早 main.py） | `INFERRED` | 2A 修正项 5，`MOST PLAUSIBLE PROVENANCE`，未升级 |
| dev PG 数据可处置性 | `LIKELY_DISPOSABLE` | 2A 冻结 #10，带验证缺口 |
| Bootstrap Contract 真实空 PG 实跑 | `PG_RUNTIME_NOT_VERIFIED` | 2A 冻结；2C 恢复连通后实跑升格 |
| Historical Anchor 0030 是否等价于 legacy actual | `UNKNOWN` | 2C 比较 1 后才有结论；本阶段禁止假设 |

---

## 8. DB-BL-2C Authorization

```
DB-BL-2C Exact Reconciliation
AUTHORIZED
```

**条件**：

- 本 2B 的 §6 修正项（Layer 2 / 0030 anchor / 三方比较 / stamp 门禁 / 禁止倒推）必须先回写到 `DB_BL_2B_SCHEMA_OWNERSHIP_DESIGN.md` §6，冻结为 2C 合同，再进入 2C 执行。
- 2C 实际执行时须恢复 PG 连通（Docker / 本地 PG）。若当前环境不可用：

```
DB-BL-2C = AUTHORIZED_BUT_ENVIRONMENT_BLOCKED
```

不得自行改用生产或 staging。

**权限边界**：

```
LEGACY DEV PG:           READ-ONLY
DISPOSABLE VERIFICATION PG: CONTROLLED CREATE / ALEMBIC UPGRADE ALLOWED
```

**允许**：

- 创建独立 disposable local PostgreSQL database。
- 在 disposable DB 上运行 Alembic 到指定 revision（0030 / head 0034）。
- dump / inspect schema。
- 对比 expected vs actual。
- 查询 legacy dev PG schema 和必要的数据统计（行数/PII 核查，只读）。

**禁止**：

- 修改 legacy dev PG schema。
- stamp legacy DB。
- 创建 / 修改 legacy DB 的 `alembic_version`。
- repair migration。
- DROP / recreate legacy DB。
- 修改 legacy DB 数据。
- 执行 legacy DB 的 0032 / 0033 / 0034 upgrade。
- production / staging 操作。

---

## 9. Explicitly Forbidden

```
NO STAMP            — 2C 对账完成前禁止 alembic stamp 任何 revision（含 0030 / 0034）
NO REPAIR           — 2C 不得执行任何 repair migration
NO LEGACY UPGRADE    — 2C 不得对 legacy dev PG 执行 0032/0033/0034 upgrade
NO REBUILD          — 2C 不得 DROP/recreate legacy dev PG（重建属 2D，须独立审批）
NO STAMP-FIRST       — 禁止"先 stamp 0030 再修差异"；stamp 须比较 1 证明等价后由 2D 独立审批
NO REVERSE-INFERENCE — 禁止"看 DB 像 0030 → stamp → 找证据"；须独立生成 expected → 独立 inspect → compare
NO LEGACY WRITE      — legacy dev PG 只读
NO PROD/STAGING      — 2C 不得操作生产/staging；环境不可用则 AUTHORIZED_BUT_ENVIRONMENT_BLOCKED
NO CODE CHANGE       — 本 2B/2C 不改 init_db.py / main.py / 迁移文件（init_db RESTRICT 守卫属 2D/独立实施）
NO DOC REWRITE NOW   — §5 doc-sync 回写属后续任务，本审批不实施
```

---

## 10. Technical Closure Impact

本设计如何解锁后续 P1 Technical Closure（Blocker A：auto_wechat schema baseline）：

| 受阻项 | 当前状态 | 本设计如何解锁 |
|---|---|---|
| **0032 PG verification** | `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH` | 2C 三方对账后，2D 受控修复（若比较 1 证明 == 0030 则 stamp 0030 → upgrade 0032；否则受控重建），使 dev PG 达到含 `daily_report_generations` 的 0034 baseline，解锁 0032 PG evidence。 |
| **0033 PG verification** | `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH` | 同上路径，达 0034 baseline 后解锁 `ai_edit_material_analysis_executions` PG evidence。 |
| **0034 PG verification** | `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH` | 同上路径，达 0034 baseline 后解锁 `ai_preview_executions` PG evidence。 |
| **P1 Technical Closure** | `PENDING`（COMPUTE-IDEMPOTENCY-001 OPEN） | schema baseline 修复 → 0032/33/34 PG verification 三态闭环（PASS/FAIL/WAIVED_WITH_ACCEPTED_RESIDUAL_RISK）→ 配合 RAG Query 0005 PG（Docker 恢复后独立补）+ Global Active None Audit + Final PG Concurrent Closure Gate → Technical Closure。 |

**关键区分（不得混淆）**：

- Consumer Migration Complete（11/11）≠ Technical Closure Complete（≠ E2E_VERIFIED_FIXED）。
- 本 2B 冻结的是"什么才叫合法 schema"（Contract），不修库。
- 2C 只读对账（产出 gap 矩阵 + anchor 判定），不修库。
- 2D 才是受控修复（stamp-to-revision 或重建），须独立审批。
- WAIVED_WITH_ACCEPTED_RESIDUAL_RISK ≠ PASS；risk-accept 不得标 E2E_VERIFIED_FIXED。

**xg_douyin_ai_cs（9100）库**：本 2B 聚焦 `auto_wechat` 库；9100 库 schema ownership 同理（Model A，独立 Alembic 链），但其 baseline 治理不在 P1 Blocker A 范围，按需独立推进。

---

## 审批结论

```
Technical Decision        = APPROVED_WITH_CORRECTIONS
Schema Authority          = MODEL A (PG: Alembic sole; SQLite: create_all)
Bootstrap Contract        = EMPTY PG → alembic upgrade head → /ready verifies head (STATIC_CHAIN_VERIFIED, not runtime verified)
init_db.py                = RESTRICT
Documentation Drift       = 登记 + 原位标注 SUPERSEDED，保留历史不删
2C Target Contract        = Layer 1 Canonical Final Target = 0034
                            + Layer 2 Historical Anchor Candidate = 0030（本审批补入）
                            + 三方独立比较 + stamp 门禁 + 禁止倒推（本审批补入）
2C Authorization          = AUTHORIZED (LEGACY DB READ-ONLY; disposable PG controlled create/upgrade)
                            环境不可用 = AUTHORIZED_BUT_ENVIRONMENT_BLOCKED
Forbidden                 = NO STAMP / NO REPAIR / NO LEGACY UPGRADE / NO REBUILD / NO STAMP-FIRST / NO REVERSE-INFERENCE
```

**进入 2C 前必须完成**：将本报告 §6 的修正项（Layer 2 / 0030 anchor / 三方比较 / stamp 门禁 / 禁止倒推）回写到 `DB_BL_2B_SCHEMA_OWNERSHIP_DESIGN.md` §6，冻结为 2C 合同。

**完成后停止。不得自行进入 DB-BL-2C。**
