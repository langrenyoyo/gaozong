# DB-BL-2D — Legacy PostgreSQL Baseline Repair Strategy 设计/审计报告

> 阶段：DB-BL-2D **Design / Audit Only**
> 日期：2026-08-10
> 窗口：DB-BL-2D Legacy PostgreSQL Baseline Repair Strategy 设计/审计窗口
> 前置冻结：2C `DB_BL_2C_RESUME_APPROVAL.md` = `EXACT_RECONCILIATION_VERIFIED` + `DB-BL-2D: AUTHORIZED — DESIGN / AUDIT ONLY`；2B `DB_BL_2B_APPROVAL.md` = `APPROVED_WITH_CORRECTIONS`（Schema Authority = MODEL A、init_db.py = RESTRICT、Bootstrap Contract、Doc Drift 登记）。
> 工作原则：事实 → 设计 → 审批 → 实施。本阶段只比较 repair strategy、设计数据保全与 rollback、定义 verification gates、给出 0032/0033/0034 解锁后续路径。**无数据库修复实施权限。**
> 实施状态：`DESIGN COMPLETE / FROZEN`；`CR-1~CR-8 = APPLIED`；`Implementation = AUTHORIZED`（详见 §16）

---

## 0. 本阶段核心问题

DB-BL-2C 已正式闭环「这个 legacy dev PG 是不是 0030」——结论 `NO`（`NOT_EQUIVALENT_TO_0030`，629 项无争议结构 drift）。

DB-BL-2D 不再回答该问题。2D 回答：

> **既然 legacy DB 没有可信 revision identity、存在 629 项结构漂移、数据又可处置（DISPOSABLE）、migration chain 已恢复可信（PG_RUNTIME_VERIFIED），哪一种恢复方式最简单、最安全、最符合 Model A？**

本报告比较三类策略并给出设计推荐，提交独立审批窗口。**不自行实施。**

---

## 1. Frozen Inputs（2C 冻结事实）

以下输入全部继承自 2C `EXACT_RECONCILIATION_VERIFIED` 与 2B 审批，本阶段不重新对账、不重复查询（2C 已有充分只读证据）：

| 输入 | 值 | 来源 |
|---|---|---|
| Revision Identity | `NOT_EQUIVALENT_TO_0030`（629 项无争议结构 drift，排除 576 comment 后仍成立） | 2C RESUME APPROVAL §7 |
| Stamp Eligibility | `REJECTED_AS_REPAIR_CANDIDATE`（不得 stamp 0030 → upgrade 0032/33/34） | 2C RESUME APPROVAL §12 |
| Legacy Data | `DISPOSABLE`（`READ_ONLY_PG_VERIFIED`，全库 5 行、无 PII，UNCHANGED） | 2C RESUME APPROVAL §11 / 原 2C §11 |
| Canonical Final Target | `Expected@0034`（head，`PG_RUNTIME_VERIFIED`，60 业务表 + 1 alembic_version） | 2C RESUME APPROVAL §2/§14 |
| Migration Chain | `PG_RUNTIME_VERIFIED / CONFORMANT`（EMPTY→0030、EMPTY→0034 均 PASS） | 2C RESUME APPROVAL §14 |
| Matrix A | legacy vs 0030：1205 semantic（含 576 comment→METADATA、629 结构）/ 9 name-only / 0 normalization | 2C RESUME APPROVAL §6 |
| Matrix B | 0030→0034：30 semantic（归属 0032/0033/0034，纯加法 delta）/ 0 / 0 | 2C RESUME APPROVAL §8 |
| Matrix C | legacy vs 0034：1235 semantic（A∪B）/ 9 / 0；集合一致性 VERIFIED | 2C RESUME APPROVAL §9 |
| 表名集合 | legacy 57 == 0030 57 同名；drift 全在列/约束/索引层 | 2C RESUME APPROVAL §6.2 |
| 主要结构 drift | 类型(238) / 默认(178) / 可空(93) / 索引(86) / 约束(26) / 缺列(8 业务) / 注释(576→METADATA) | 2C RESUME APPROVAL §6.3 |
| Schema Authority | MODEL A（PG：Alembic sole constructor + evolution；SQLite：create_all） | 2B APPROVAL §2 |
| Bootstrap Contract | EMPTY PG → alembic upgrade head → /ready verifies head | 2B APPROVAL §3 |
| init_db.py | `RESTRICT`（属 2D 或独立实施审批，本 2B 未实施） | 2B APPROVAL §4 |
| Documentation Drift | 登记清单（README:75 / RUNTIME_ENTRYPOINTS.md:242 / 历史 doc），回写随 RESTRICT 实施同步 | 2B APPROVAL §5 |

### 1.1 Legacy 环境标识（RB-0 输入）

| 维度 | 值 |
|---|---|
| 容器 | `auto-wechat-postgres-dev`（PG 16，本机 Docker） |
| 端口 | `127.0.0.1:5432` |
| 数据库 | `auto_wechat` |
| 数据卷 | `auto_wechat_postgres_data` |
| 业务表 | 57（无 `alembic_version`，从未经 Alembic 管理） |
| 环境分类 | **LOCAL DEVELOPMENT ONLY**（非 prod / 非 staging / 非 2C disposable） |

### 1.2 Legacy 数据可处置性精确证据（RB-1 输入）

| 维度 | 值 | 证据等级 |
|---|---|---|
| 全表总行数 | **5** | `READ_ONLY_PG_VERIFIED`（2C §11 精确 count） |
| 非空表 | `compute_transactions`(3)、`compute_accounts`(1)、`compute_markup_ratios`(1) | 全部为 P1 Consumer Migration 测试种子 |
| PII 表行数 | `douyin_leads`=0、`customer_profiles`=0、`sales_lead_feedbacks`=0、`wechat_tasks`=0 | 无手机号/微信号/客户资料/线索/销售反馈行 |
| 不可重建数据 | 无 | compute_* 可由测试 fixture/seed 重建 |

> `DISPOSABLE` 只允许 rebuild 进入 repair strategy 候选；**不等于本阶段已批准 DROP/rebuild**。本阶段不执行任何数据库操作。

---

## 2. Strategy A — Rebuild From Canonical Alembic Head（Replace Before Delete）

### 2.1 概念

```text
确认 legacy disposable（RB-1）
→ 保留 rollback artifact（RB-2：legacy DB 原地保留 + 轻量 pg_dump）
→ 停止使用 legacy DB（应用停连接）
→ 创建新的 empty PostgreSQL database（独立 database name，复用或独立容器）
→ alembic upgrade head（→ revision 0034）
→ verify revision = 0034
→ schema exactness verification（Actual New DB vs Expected@0034，STRUCTURAL_DIFF=0）
→ application readiness verification（/ready PASS + minimal smoke）
→ 切换 development connection（DATABASE_URL）
→ only later retire legacy DB（验证通过 + 观察期后）
```

### 2.2 优点

- **完全遵守 Model A**：新 schema 唯一来源是 Alembic 链，无 create_all / stamp / 手工 DDL / schema copy。
- **直接生成 canonical schema**：`EMPTY → alembic upgrade head` 已 `PG_RUNTIME_VERIFIED`（2C 证实 EMPTY→0034 PASS），无需重新证明链可跑。
- **无需维护 629 项 structural repair**：全部 drift 通过重建一次性消解，不存在逐项 ALTER 遗漏。
- **自动取得合法 `alembic_version=0034`**：alembic_version 由框架首次 upgrade 自动创建（2A 冻结事实 #4），revision identity 合法、无需 stamp 审批。
- **未来 migration history 干净**：新库从 head 起跑，无历史包袱，后续 upgrade/downgrade 正常。
- **数据丢失风险已被化解**：5 行 compute_* 测试种子可由 P1 测试 fixture/seed 重建，无 PII、无不可重建人工业务数据。

### 2.3 风险

| 风险 | 评估 | 缓解 |
|---|---|---|
| legacy 数据丢失 | 低（DISPOSABLE，5 行测试种子可重建，无 PII） | RB-1 实施前最终复核；RB-2 legacy DB 保留不删 + pg_dump |
| local env connection/config 切换 | 低（DATABASE_URL 一处） | replace-before-delete：rename 方案可零配置改动；new-db 方案改 DATABASE_URL 一处 |
| 是否存在未发现的开发数据 | 低（2C `READ_ONLY_PG_VERIFIED` 全库精确 count=5） | RB-1 实施前重新 count，与 2C 不一致则停止 |
| Docker volume / database naming | 低（用独立 database name 或独立容器/卷，不覆盖 legacy） | RB-0 明确环境标识；新 DB 与 legacy 名义隔离 |
| rollback 能力 | 高（legacy DB 原地保留为 backup） | RB-2 + §10 Rollback Contract |

### 2.4 实施方式选择（设计推荐，待审批）

两种 replace-before-delete 实施方式：

| 方式 | 操作 | 配置改动 | 隔离 | 推荐 |
|---|---|---|---|---|
| **A1（rename）** | `RENAME auto_wechat → auto_wechat_legacy_backup`；`CREATE DATABASE auto_wechat`（empty）；`alembic upgrade head` | 无（DATABASE_URL 不变，仍指向 `auto_wechat`） | 同容器同卷，DB 名隔离 | ★ 推荐（最小改动） |
| A2（new db） | `CREATE DATABASE auto_wechat_clean`（empty）；`alembic upgrade head`；改 `DATABASE_URL` 指向新库 | DATABASE_URL 一处 | 同容器同卷，DB 名隔离 | 备选 |

> 方式 A1 优势：`DATABASE_URL` **config value 不变**（database-name 部分仍为 `auto_wechat`，A1 rename 后同名新库），legacy 自动重命名为 `auto_wechat_legacy_backup` 保留为 rollback artifact，最小改动符合 YAGNI。
>
> **CR-3 修正（connection semantics 精确化）**：「config value 不变」仅指 `DATABASE_URL` 字面值不改；**既有 DB 连接不会自动迁移**——rename 不迁移活跃连接（既有连接指向的是旧库 backend pid），应用必须在验证通过后**重启/重连**建立到新 `auto_wechat` 的新连接。禁止使用「零切换」这种混淆 config value 与 connection semantics 的表述。
>
> 前提：rename 前必须 quiesce 所有持有 `auto_wechat` 连接的本地 consumer（见 RB-Q / §8a），避免活跃连接占库导致 `ALTER DATABASE ... RENAME` 失败。
>
> 两种方式均不 DROP legacy——legacy 以 backup 名义原地保留，验证失败可立即回切。

---

## 3. Strategy B — Targeted Schema Reconciliation

### 3.1 概念

```text
保留 current legacy DB
→ 根据 Matrix C（legacy vs 0034，1235 semantic）
逐项 ALTER / ADD COLUMN / DROP / REBUILD INDEX / REBUILD CONSTRAINT / SET COMMENT
→ 最终达到 Expected@0034
→ 再解决 Alembic revision identity（证明 == 0034 后 stamp 0034）
```

### 3.2 必须回答的 10 问

| # | 问题 | 评估 |
|---|---|---|
| 1 | 629 项 structural drift 是否需要逐项 repair | **是**。type(238)+default(178)+nullable(93)+index(86)+constraint(26)+column(8) 全部需 ALTER，无跳过空间 |
| 2 | 是否能安全自动修复 | **否**。238 项 type_diff 含高风险转换（见 #3），无法全自动 |
| 3 | type conversions 是否破坏数据 | **有破坏风险**。抽样（2C §6.3）：`text→jsonb`（request_body_json，需数据为合法 JSON）、`timestamp without tz → with tz`（created_at，reinterpret 会导致时间值偏移）、`integer→bigint`（id，相对安全但需锁表）。数据虽 DISPOSABLE，但 type 转换仍可能产生非法 schema 状态 |
| 4 | default / nullable 更改风险 | 178 default（多数 ADD DEFAULT 安全）+ 93 nullable（False→True 需 fill default 值，93 项中如 created_at 需回填 now()） |
| 5 | index / constraint rebuild | 86 索引 + 26 约束，可 REBUILD 但需拓扑排序（FK 依赖顺序），rebuild 期间锁表 |
| 6 | missing columns | 8 业务缺列（tenant_id/merchant_id 等），ADD COLUMN 安全，但需配合 default/nullable 决策 |
| 7 | comment metadata | 576 项 SET COMMENT，低风险但量大 |
| 8 | 最终如何合法获得 revision identity | **关键缺陷**。legacy 无 alembic_version，repair 完成后仍无合法 revision。需 stamp 0034，而 stamp 0034 前提是"证明 repair 后与 Expected@0034 exact equivalent"——这本身是完整全量对账（等于重做一次 2C） |
| 9 | 是否最终仍需 stamp | **是**。repair 后唯一合法获得 revision 的方式是 stamp 0034。虽然 stamp 0034（非 0030）在治理上未被 2C 直接否决，但其前提"证明 == 0034"的验证成本极高 |
| 10 | 怎样证明 repair 后与 Expected@0034 exact equivalent | 用 2C 同一套 snapshot 工具重新跑 Matrix，要求 `STRUCTURAL_DIFF=0`。这是一次完整 2C 级精确对账，验证成本≈重做 2C |

### 3.3 复杂度量化

| 维度 | Strategy B | 对比 Strategy A |
|---|---|---|
| 结构 repair 项 | 629 项 ALTER（含 238 高风险 type 转换） | 0 项（upgrade head 一次性） |
| metadata 项 | 576 项 SET COMMENT | 0 项（同链产物自带） |
| 验证成本 | 重新全量对账证明 == 0034（≈重做 2C） | 1 次同链自证（结构必然一致） |
| revision identity | 需 stamp 0034 + 独立审批 | 自动合法 0034 |
| 实施风险 | type 转换数据破坏、ALTER 顺序依赖、锁表 | 单次 upgrade（已验证 PASS） |

> **本方案不得偷偷变成「先 stamp head → 再慢慢修」**——那仍违反 2C 冻结原则（`REJECTED_AS_REPAIR_CANDIDATE` + 禁止 stamp-first + 禁止 reverse-inference）。必须 `repair → prove exact equivalence → only then consider revision bookkeeping`。

### 3.4 结论

Strategy B 复杂度**远超 rebuild 数个数量级**：629 项高风险 ALTER + 576 comment + 重新全量对账 + stamp 审批，且 238 项 type conversion（含 text→jsonb / timestamp 时区 reinterpret）有数据正确性风险。对一份 5 行 DISPOSABLE 的本地开发库，这是显著过度工程。

---

## 4. Strategy C — New Forward Reconciliation Migration

### 4.1 概念

```text
新增专门 repair migration（如 revision = repair_legacy_to_0034）
在 legacy DB 上运行
→ repair 至 Expected@0034
```

### 4.2 核心问题：怎样合法进入这条 forward migration？

> legacy DB 当前**没有可信 alembic_version**（2C `READ_ONLY_PG_VERIFIED`：`has_alembic_version_table=False`、`alembic_version=None`），怎样合法进入这条 forward migration？

Alembic 运行 migration 的前提是知道当前 revision。legacy 无 alembic_version 表 → **必须先 stamp 一个起点 revision** 才能让 repair migration 跑起来。

- 若 stamp 0030 作为起点：2C 已证明 `legacy != 0030`（629 项 drift），stamp 0030 是伪造 revision identity → **违反 2C `REJECTED_AS_REPAIR_CANDIDATE` + 禁止 reverse-inference**。
- 若 stamp 任意虚假起点再 repair：repair migration 必须 encode 全部 629 项 drift 修复逻辑，且其 `down_revision` 前提（legacy == 某 revision）不成立 → migration 语义非法。
- 若 repair migration `down_revision=0030` 但从非 0030 库起跑：等同于 Strategy B 的逐项 ALTER，只是包进 migration 文件；且 migration 入 chain 后会污染未来所有人（一份"修 legacy 残骸"的 migration 永久进入 canonical chain，对所有从空库 upgrade 的人产生幽灵对象）。

### 4.3 结论

**Strategy C 被淘汰（REJECTED）**。依据任务 §9：

> 如果仍然需要先伪造 revision identity：则该方案应被淘汰。

Strategy C 无法在不伪造 revision identity 的前提下合法进入 migration chain。不要为"所有修复都用 migration"而人为制造无法进入 chain 的方案。将 legacy 残骸修复塞进 canonical migration chain 还会污染未来所有合法空库 bootstrap。

---

## 5. Strategy Evaluation Matrix

| Dimension | Rebuild (A) | Targeted Repair (B) | Forward Repair (C) |
|---|---|---|---|
| Alembic Authority correctness | ✅ 高（Model A 直接，Alembic sole constructor） | ❌ 低（手工 ALTER 绕过 Alembic authority） | ❌ 低（需伪造起点，破坏 chain 语义） |
| Revision identity correctness | ✅ 高（框架自动建 alembic_version=0034，合法） | ❌ 低（repair 后仍需 stamp 0034 + 全量重对账证明） | ❌ 低（需伪造 revision identity 才能进入） |
| Structural drift coverage | ✅ 高（全量重建，drift 一次性消解） | ✅ 高（逐项 629） | ✅ 高（encode 629） |
| Data safety | ⚠️ 中（DISPOSABLE 5 行丢失，可重建） | ❌ 低（238 type conversion 含 text→jsonb / tz reinterpret 破坏风险） | ❌ 低（同 B） |
| Implementation complexity | ✅ 低（1 次 upgrade head，已 PG_RUNTIME_VERIFIED） | ❌ 极高（629 ALTER + 576 comment + 拓扑排序 + 锁表） | ❌ 极高（629 + migration 设计 + chain 污染） |
| Verification complexity | ✅ 低（同链自证 + 1 次对账） | ❌ 极高（重新全量对账证明 == 0034，≈重做 2C） | ❌ 极高（同 B + migration 合法性验证） |
| Rollback simplicity | ✅ 高（legacy DB 原地保留，回切瞬时） | ⚠️ 中（部分 ALTER 可 down，但 type 转换不可逆） | ⚠️ 中 |
| Future maintainability | ✅ 高（干净 migration history，从 head 起跑） | ❌ 低（手工 repair 不入 chain，drift 隐患留存） | ❌ 低（幽灵 repair migration 永久污染 chain） |
| Risk of hidden drift | ✅ 低（同链产物，理论必然一致） | ❌ 高（629 项逐项 repair 可能遗漏） | ❌ 高（同 B） |
| Production precedent risk | ✅ 低（dev only，明确不推广 prod） | ❌ 高（手工 ALTER 若成范式，prod 有误用风险） | ⚠️ 中（repair migration 若被误用到 prod） |
| Development downtime | ✅ 低（切换瞬时，rename 零配置） | ❌ 高（repair 期间库不可用 + 锁表） | ❌ 高 |
| YAGNI | ✅ 高（最简方案解 disposable 库） | ❌ 低（为 5 行 disposable 库做 629 项手术，过度工程） | ❌ 低（为 disposable 库造复杂 migration + 污染 chain） |

### 5.1 策略标记

```text
Strategy A (Rebuild, Replace Before Delete)  = PREFERRED
Strategy B (Targeted Reconciliation)          = REJECTED
Strategy C (Forward Repair Migration)         = REJECTED
```

---

## 6. Preferred Strategy

**推荐 Strategy A — Rebuild From Canonical Alembic Head，采用 Replace Before Delete 原则。**

### 6.1 推荐理由（三点收敛）

1. **数据风险已被冻结证据化解**：legacy `DISPOSABLE`（5 行 compute_* 测试种子、无 PII、可由 fixture 重建）。rebuild 唯一数据代价是 5 行可重建测试种子，无 PII、无不可重建人工业务数据。
2. **stamp 路径已淘汰、repair 路径复杂度不成比例**：2C `REJECTED_AS_REPAIR_CANDIDATE` 排除 stamp 0030→upgrade；Strategy B 629 项 ALTER（含 238 高风险 type 转换）+ 全量重对账 + stamp 0034 审批，复杂度远超 rebuild；Strategy C 无法合法进入 chain。三者中 rebuild 是唯一同时满足「合法 revision identity + 低复杂度 + 低风险」的方案。
3. **migration chain 已 PG_RUNTIME_VERIFIED**：`EMPTY → 0034` 在 2C 已实跑 PASS，rebuild 不是未验证假设，而是已验证路径的复用。

### 6.2 设计推荐（待审批）

- 实施方式：**A1（rename）** — `RENAME legacy auto_wechat → auto_wechat_legacy_backup`；`CREATE empty auto_wechat`；`alembic upgrade head`。`DATABASE_URL` **config value 不变**（CR-3：仅 config value 不改，既有连接须重启重连），legacy 自动保留为 rollback artifact。
- 不 DROP legacy：以 `auto_wechat_legacy_backup` 名义原地保留至验证通过 + 观察期。
- 本阶段只设计。**不得执行 DROP / CREATE / RENAME / connection switch / rebuild。**

---

## 7. Data Safety Contract

### 7.1 Disposability

- 冻结状态：`DISPOSABLE`（`READ_ONLY_PG_VERIFIED`，全库 5 行、无 PII，UNCHANGED）。
- `DISPOSABLE != authorized to rebuild`。本设计推荐 rebuild，但实施须独立审批 + RB-1 最终复核。

### 7.2 Backup（RB-2 — Rollback Artifact）

| Option | 内容 | 成本 | 选择 |
|---|---|---|---|
| A | 保留旧 DB / volume 不立即删除（rename 为 `auto_wechat_legacy_backup`） | 零额外操作 | ★ 主力 |
| B | schema-only dump + minimal data dump（5 行） | 秒级 pg_dump | ★ 附加保险 |
| C | 完整 local dump | 秒级（库极小） | 可选，非必要 |

**推荐 Option A + Option B**：legacy DB rename 保留（主力 rollback）+ pg_dump schema+5行 data（轻量额外保险，成本极低）。**不为一份 5 行 disposable 库设计生产级灾备平台**（YAGNI）。

### 7.3 Rollback 目标

> repair/rebuild 失败时恢复到原 development 状态进行调查，**不是做生产级灾备**。

### 7.4 Database-Level Contract（CR-4 冻结）

`CREATE DATABASE auto_wechat` 后，新库须满足应用合法使用条件，不止「schema 正确」。实施时须核验项目实际依赖项（遵循 YAGNI，不建设数据库配置平台），区分：

```text
LEGACY DATABASE PROPERTY   （旧库 drift 属性，不得盲目复制）
PROJECT REQUIRED PROPERTY   （应用运行实际所需，须满足）
```

| 维度 | 要求 | 性质 |
|---|---|---|
| database owner | 新库 owner 须与 `DATABASE_URL` 中连接角色一致或被授权 | PROJECT REQUIRED |
| application role permissions | CONNECT / CREATE / USAGE（应用运行所需实际权限，实施时按 `DATABASE_URL` 角色核验） | PROJECT REQUIRED |
| encoding | 默认 UTF8，确认与应用一致 | PROJECT REQUIRED |
| required extensions | 核验 migration chain 是否依赖任何 PG extension（如 `pg_trgm` / `uuid-ossp`）；有则 CREATE EXTENSION 须在 alembic upgrade 前就绪 | PROJECT REQUIRED |
| schema / search_path | 若项目有显式 `public` 外约束则核验，否则默认 | 仅项目有显式约束时 |
| locale / collation | 仅当项目确有依赖时核验，否则默认 | YAGNI |

目的：确保 replacement DB 不仅 schema 正确，且可被当前应用合法使用。**不得因为旧库某个属性存在就盲目复制**（legacy drift 不得带进新库）。

---

## 8. Execution Plan（实施步骤）

> **CR-2 / CR-7 修正**：补入显式 quiesce gate（RB-Q），并冻结执行顺序为「dump → verify dump → quiesce → rename → create replacement」。任何 identity-changing operation（rename）前必须已有可核验 rollback evidence（pg_dump 验证成功）。rename 本身非破坏性（数据保留），但 dump 作为附加保险须先就位。

```text
RB-0   环境身份确认：host/port/container/volume = LOCAL DEVELOPMENT ONLY
RB-1   数据可处置性最终复核：count=5、PII 表=0、无可重建数据；与 2C 不一致则停止
RB-2a  pg_dump legacy（schema + 5 行 data，custom-format）
RB-2b  verify dump 成功（command success / file exists / size>0 / pg_restore --list 完整性读取）
RB-Q   quiesce local DB consumers（CR-2 显式 gate）：停止所有持有 auto_wechat PG 连接的本地 consumer
RB-2c  rename legacy → auto_wechat_legacy_backup（保留，不删）
RB-3   创建 empty database（A1：CREATE DATABASE auto_wechat）
RB-4   alembic upgrade head → revision 0034
RB-5   schema exactness：Actual New DB vs Frozen Expected@0034 → STRUCTURAL_DIFF=0
RB-6   alembic current/head = 0034；60 业务表 + 1 alembic_version
RB-7   /ready PASS
RB-8   local application smoke PASS
RB-9   prevention guard/doc sync（init_db RESTRICT + README:75 + RUNTIME_ENTRYPOINTS.md:242，同批）
--- 验证全部通过 + 观察期后 ---
RB-10  legacy retirement：DELETE_AFTER_VERIFICATION（删除 auto_wechat_legacy_backup，不在本轮授权范围）
```

### 8a. RB-Q — Service Quiescence Gate（CR-2 冻结）

PostgreSQL `ALTER DATABASE ... RENAME TO` 在存在活跃连接占用目标库时会失败；quiesce 不是可选项，是 rename 前的**硬前置**。

rename 前必须停止所有会持有 `auto_wechat` PostgreSQL connection 的本地 consumer，至少按实际 topology 检查：

- auto-wechat-api（9000 主服务）
- background workers / schedulers
- migration / alembic 进程
- local scripts（`python scripts/...`）
- local development server（宿主机 `uvicorn ... --reload`）
- 其他实际使用该 DB 的进程

确认 PostgreSQL 当前对目标 DB 不再存在会阻碍 rename 的业务连接（必要的 admin/self connection 除外）。

```text
DB_CONSUMERS_QUIESCED: VERIFIED  → 可进入 rename
```

如无法可靠清空活动连接 → STOP，不得强行 rename（除非既有 approved design 明确允许终止本地连接并确认仅为 LOCAL DEV）。

> 19000 Local Agent 不直接持有 `auto_wechat` DB 连接（其只操作本机微信，DB 交互经 9000），但仍须确认无连接。

### 8b. 原子停止点（CR-7 冻结）

```text
dump fail   → STOP（不 rename，legacy 仍为 auto_wechat 原状）
rename fail → STOP（不 create replacement，保留 rename 状态调查）
create fail → STOP（旧库已 rename 时保留 rename 状态，不现场半手工修建 DB 继续）
bootstrap fail → STOP（不 patch schema，keep legacy backup，按 rollback procedure 决定是否恢复旧库名）
```

原则：失败即停 + 保留现状调查。**禁止「失败后现场修新库直到能跑」。**

---

## 9. Verification Gates（DBR-*）

| Gate | 要求 | 失败处理 |
|---|---|---|
| DBR-0 | Strategy approved（独立审批） | 不实施 |
| DBR-1 | legacy disposability reconfirmed（count=5、PII=0、无可重建数据） | 与 2C 不一致 → 停止，不 rebuild |
| DBR-2 | rollback artifact ready（legacy renamed 保留 + pg_dump） | 无 backup → 停止 |
| DBR-3 | new empty DB bootstrap head PASS（EMPTY→0034） | bootstrap 失败 → keep legacy untouched, discard failed new DB, stop |
| DBR-4 | actual new schema == Expected@0034（STRUCTURAL_DIFF=0） | 不等 → do not switch, keep legacy, stop |
| DBR-5 | alembic current/head = 0034（单头） | 否 → stop |
| DBR-6 | /ready PASS | 失败 → restore old connection, keep new DB for inspection, stop |
| DBR-7 | local application smoke PASS | 失败 → restore old connection, keep new DB for inspection, stop |
| DBR-8 | legacy untouched until verification complete | 全程 legacy 只读/保留 |
| DBR-9 | prevention guard/doc sync applied（init_db RESTRICT + doc，若审批纳入） | 若同批则随实施落地 |

> 失败一律「停止 + 保留现状调查」，**不设计为"失败后现场修新库直到能跑"**。

### 9.1 Schema Exactness 口径（DBR-4 补充）

新 DB 由同一 Alembic 链创建，理论上与 Expected@0034 完全一致。DBR-4 要求：

```text
STRUCTURAL_DIFF = 0
METADATA_DIFF   = 0   (comment)
NAME_ONLY_DIFF  = 0   (约束/索引命名)
```

三者全 0（比 legacy 对账更严格，因为是同链产物应自然达成）。任一非 0 → 视为新 blocker，停止。

### 9.2 Verification Authority（CR-5 冻结）

```text
PRIMARY VERIFICATION REFERENCE:
2C 冻结并审批过的 Expected@0034 evidence snapshot
docs/architecture/remediation/db_bl_2c_resume_evidence/expected_0034.json
```

对新的 `auto_wechat` 使用与 2C 相同的 `scripts/db_bl_2c_resume_snapshot.py`（或冻结等价 inspection contract），比较 **New Actual vs FROZEN Expected@0034**。

- Fresh runtime `empty → head` bootstrap snapshot 可额外生成作为 **supplemental runtime sanity evidence**，但**不得替代 frozen canonical**，亦**不得覆盖 2C 冻结 canonical evidence**（除非显式解释差异）。
- 风险规避：修复后重新生成 Expected → 若 migration chain 意外同时改变 → Actual 与 Expected 一起漂移 → diff 仍为 0（假 PASS）。冻结 2C 已审批快照为主参考可堵此风险。
- 任一 diff ≠ 0 → STOP，不得 normalize away 未解释差异。

### 9.3 Seed / Bootstrap Runtime Gate（CR-6 冻结）

> **冻结事实（CODE_VERIFIED）**：migration `0006_create_runtime_cutover_gap_tables.py` 只 `create_table("check_configs")`，**不 seed `DEFAULT_CONFIGS`**。`DEFAULT_CONFIGS` 仅由 `scripts/init_db.py`（行 20-34）注入——而 init_db.py 正是被 RESTRICT 的入口。因此 rebuild 后新库 `check_configs` 为**空表**。

```text
空业务数据库  !=  可运行数据库  （须显式确认，不得默认）
schema=head   →  application 必然可运行（该假设禁止）
```

DBR-6（/ready PASS）前必须确认：

- canonical migrations 是否负责必要 seeds？（当前 `check_configs` 无 migration seed → 新库为空表）
- 若存在 migration 外必须人工初始化的 runtime-required data，必须登记处理方式（`RUNTIME_BOOTSTRAP_DATA_GAP`）。
- `check_scheduler.py:83` 等读取 config 行虽有默认回退（5 分钟 + try/except，CODE_VERIFIED），但须以 /ready 实跑确认空 `check_configs` 不阻断启动。
- **不得恢复那 5 条旧 compute_* 测试数据**（DISPOSABLE，无必要）。
- **禁止调用 `scripts/init_db.py` 给 PostgreSQL 补 seed**（init_db.py 在 PG 下被 RESTRICT 拒绝 create_all）。

如启动发现 required bootstrap data missing → 记录 `RUNTIME_BOOTSTRAP_DATA_GAP` → STOP，不得擅自 INSERT seed。该问题需独立设计/审批，除非已有现役已批准正规 bootstrap mechanism 可直接使用。

---

## 10. Failure / Rollback Plan

| 失败点 | 处理 |
|---|---|
| new DB bootstrap 失败（RB-4） | keep legacy untouched；discard failed new DB；stop。不修 migration、不 patch DB |
| schema verification 失败（DBR-4/5） | do not switch；keep legacy；keep new DB for inspection；stop |
| application readiness 失败（DBR-6/7） | restore old local connection（DATABASE_URL 回切，A1 rename 方案则 RENAME 回切）；keep new DB for inspection；stop |
| RB-1 与 2C 不一致 | 停止；不 rebuild；上报审批窗口复核 disposability |

> Rollback Contract 原则：失败即停 + 保留现状调查。**禁止"失败后现场修新库直到能跑"。**

---

## 11. init_db.py / Drift Prevention Integration

### 11.1 判断

**推荐 A — 与 baseline repair 同批实施**（init_db.py RESTRICT 守卫作为 rebuild 的 prevention guard，README:75 + RUNTIME_ENTRYPOINTS.md:242 doc sync 同步落地）。

### 11.2 依据（CR-1 修正：provenance = MOST PLAUSIBLE / CURRENT RISK ENTRY）

> **provenance 措辞修正（CR-1）**：init_db.py 的成表 provenance 为 `MOST PLAUSIBLE PROVENANCE / INFERRED`（2B APPROVAL §7 冻结，未升级为 PROVEN）。RESTRICT 判定基于 **prevention closure**，不得表述为「已证明 legacy 57 表就是 init_db.py 创建」。`scripts/init_db.py:16` `Base.metadata.create_all(bind=engine)` 无条件、无 backend 守卫（CODE_VERIFIED），是当前仓库仍可能再次制造同类无 Alembic revision PG baseline 的**已知风险入口（CURRENT RISK ENTRY）**——消除该入口即 prevention closure。

- **init_db.py 是 legacy 57 表残骸的 MOST PLAUSIBLE provenance**（2B §2：「SQLite 的合法 create_all 不得自动推导为 PostgreSQL 也允许 create_all」），但**未被证明为唯一历史根因**；RESTRICT 理由是 prevention closure（消除已知风险入口），非 provenance 证明。
- **直接防止 rebuild 后再次被 init_db.py 污染**：rebuild 一个干净 0034 库却留无守卫的 init_db.py（`scripts/init_db.py:16` 无条件 create_all，无 backend 守卫），等于已知风险入口未除——开发者一旦手工 `python scripts/init_db.py`（README:75 现实触发点）会再次 create_all 污染新库。
- **属修复闭环必要 guard**：RESTRICT 守卫与 `ensure_runtime_schema()` PG skip 语义对齐，形成 runtime + bootstrap 工具双重 PG create_all 拦截。
- **scope 可控**：最小 diff（init_db.py 加 PG backend 守卫 `sys.exit(1)` + seed 独立化）+ README/RUNTIME_ENTRYPOINTS 原位标注，不引入新依赖、不改治理规则文件 01-04。

### 11.3 备选 B（拆为独立后置小任务）的取舍

B 风险：rebuild 后到 init_db guard 落地之间存在窗口，新库可能被手工 init_db.py 污染。2B 已确认 Dockerfile/docker-compose/CI 无 init_db 调用（无自动化风险），触发仅限手工——dev 环境低频，但根因未除不符合「修复闭环」语义。故推荐 A。

> 最终是否同批由审批决定；本设计推荐 A，实施时若审批判 scope 过大可降级为 B（但须显式记录 init_db guard 待办，不得遗忘）。

---

## 12. 0032 / 0033 / 0034 Unlock Plan

### 12.1 baseline 修复后状态

新 DB 在 head=0034，包含三张 P1 billing identity 实体表：

| revision | 新表 | 对应 consumer |
|---|---|---|
| 0032 | `daily_report_generations` + `daily_report_jobs.current_generation_id` 列 + PK/FK/CHECK/index | Daily Report |
| 0033 | `ai_edit_material_analysis_executions` | M05 Material Analysis |
| 0034 | `ai_preview_executions` | M01 Preview |

### 12.2 解锁 ≠ consumer PG verification complete

```text
migration exists at head  !=  consumer PG verification complete
```

- 新 DB 是 `empty → head 0034`，**证明三条 migration 能在链中正常落地**（结构性可达）。
- 但 P1 对三个 consumer 的 PG verification 还有各自 runtime 要求：write/read、idempotency、schema behavior（各 consumer 技术设计已定义）。
- baseline 修复使三者从 `BLOCKED_BY_SCHEMA_BASELINE_MISMATCH` → `UNBLOCKED_FOR_PG_VERIFICATION`（**仅此一档，不跳级**），**进入各自 consumer PG verification**，不等于 PASS。
- **CR-8 精确标签**：`UNBLOCKED_FOR_PG_VERIFICATION ≠ PG_VERIFIED`。本轮（DB-BL-2D）未执行 consumer-level PG verification（write/read、idempotency、schema behavior 属各 consumer 技术设计范围），不得写 `PG_VERIFIED`。

### 12.3 解锁后续路径

```text
DBR-* 全 PASS（baseline = 0034 canonical）
→ 0032 Daily Report PG verification（runtime write/read + idempotency）
→ 0033 M05 Material Analysis PG verification
→ 0034 Preview PG verification
→ 各自三态闭环（PASS / FAIL / WAIVED_WITH_ACCEPTED_RESIDUAL_RISK）
```

---

## 13. P1 Impact

```text
DB-BL Complete  !=  P1 Complete
```

baseline repair 解决的是 `auto_wechat PG baseline blocker`（P1 Technical Closure Blocker A）。完成后解锁 0032/0033/0034 PG verification，但 P1 Technical Closure 仍有以下冻结任务：

| Blocker | 当前状态 | 说明 |
|---|---|---|
| A. auto_wechat schema baseline | 本设计解决（DBR-* 全 PASS 后） | 解锁 0032/0033/0034 |
| B. RAG Query 0005 PG（xg_douyin_ai_cs） | `BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT` | Docker 恢复后独立补，不在本 2D 范围 |
| C. Global Active None Audit | PENDING | 重新全局搜索 active=None |
| D. Final PG Concurrent Closure Gate | PENDING | 并发闭包门禁 |

> Consumer Migration Complete（11/11）≠ Technical Closure Complete（≠ E2E_VERIFIED_FIXED）。本设计不过度宣称。

---

## 14. Risks / Unknowns

| 风险/未知 | 评估 | 处理 |
|---|---|---|
| **production/staging revision = UNKNOWN** | 不得将本 local dev repair 推广为「prod 也应 rebuild」 | 本设计对象仅 LOCAL DEVELOPMENT LEGACY PG；prod/staging 须各自真实 evidence |
| rebuild 后是否仍有未发现开发数据 | 低（2C READ_ONLY_PG_VERIFIED count=5） | RB-1 实施前最终复核 |
| Docker volume / connection switch 细节 | 低（A1 rename 零配置） | RB-0 环境标识确认 |
| Alembic 链非确定性（如无幂等 op） | 极低 | DBR-4 同链自证兜底；如不一致视为新 blocker |
| init_db guard 是否同批 | 待审批 | 推荐 A（同批），审批可降级 B（须显式记录待办） |
| 2C `comment_diff` 分类修正（C1）尚未回写 | 文档精度修正，不影响 Revision Identity | 执行窗口文档更新，与本设计独立 |

---

## 15. Recommended Next Stage

### 15.1 是否具备进入 DB-BL-2D Implementation 的条件？

| 条件 | 状态 |
|---|---|
| 2C 冻结事实完整 | ✅ `EXACT_RECONCILIATION_VERIFIED` |
| Preferred strategy 明确 | ✅ Strategy A（Rebuild, Replace Before Delete） |
| 安全 gate 设计完整 | ✅ RB-0~RB-2 + DBR-0~DBR-9 |
| Rollback contract 完整 | ✅ §10 逐失败点处理 |
| init_db / drift 集成判断 | ✅ 推荐同批（A） |
| 0032/0033/0034 解锁路径清晰 | ✅ §12 |

**结论：具备进入 `DB-BL-2D Implementation` 的设计条件。**

但实施须独立审批窗口授权，本报告不授权实施。

### 15.2 建议下一阶段

```text
DB-BL-2D Implementation（独立审批授权后）
  → 按 RB-0~RB-2 / DBR-0~DBR-9 执行
  → replace-before-delete（A1 rename）
  → init_db RESTRICT guard + doc sync 同批
  → 验证全 PASS 后解锁 0032/0033/0034 consumer PG verification
```

---

## 16. Implementation Status

```text
DB-BL-2D Design / Audit:
COMPLETE / FROZEN

CR-1 ~ CR-8 Corrections:
APPLIED  （2026-08-10，原位回写本设计文档 §2.4 / §6.2 / §7.4 / §8 / §8a / §8b / §9.2 / §9.3 / §11.2 / §12.2）

DB-BL-2D Implementation:
AUTHORIZED  （CONDITIONAL ON CR-1~CR-8 APPLIED — 已满足）
```

设计/审计阶段为 Design / Audit Only，已完成。CR-1~CR-8 八项修正已原位回写本设计文档（provenance 措辞 / 显式 quiesce gate / DATABASE_URL config-vs-connection 精确化 / database-level contract / frozen verification authority / seed-bootstrap gate / rollback 顺序与原子停止点 / 解锁标签精确化），实施授权据此生效。实施由独立执行窗口按 RB-Q / RB-0~RB-10 + DBR-0~DBR-9 执行。

> 设计阶段（本报告 §0–§15）保留的「Design / Audit Only」「无数据库修复实施权限」表述反映**回写前**的设计阶段状态；回写后以本节 Implementation Status 为准。

---

## 17. Explicitly Forbidden（本阶段）

- ❌ DROP legacy DB
- ❌ rebuild / create replacement DB（实施）
- ❌ RENAME legacy DB（实施）
- ❌ alembic stamp（任何 revision，legacy / disposable / prod / staging）
- ❌ legacy upgrade / downgrade / repair
- ❌ legacy schema repair（逐项 ALTER）
- ❌ local connection switch（DATABASE_URL）
- ❌ modify init_db.py（本阶段）
- ❌ production / staging DB 操作
- ❌ 0032 / 0033 / 0034 consumer PG verification（实施）
- ❌ P1 Consumer 修改
- ❌ M07 Core 修改

允许的数据库访问（如确有必要）：**READ-ONLY ONLY**。但 2C 已有充分冻结证据，优先复用，不重复查询。

---

## 18. 文档影响检查（AI 文档自治维护）

- 本报告为**新增设计文档**，不修改任何已冻结文档结论。
- 2C `EXACT_RECONCILIATION_VERIFIED`、2B `APPROVED_WITH_CORRECTIONS`、2C RESUME APPROVAL `APPROVED_WITH_CORRECTIONS` 结论均不受影响。
- 2C 修正项 C1（comment_diff 单列为 METADATA_DIFF）、C2（双口径表述）属执行窗口文档更新，与本设计独立，不影响本报告结论。
- CLAUDE.md PHASE 3A 治理状态：本设计为 DESIGN ONLY 未实施，`P1 Technical Closure = PENDING` 状态不变，无需更新。待 DB-BL-2D Implementation 全 PASS 后再按事实更新。
- init_db.py / README:75 / RUNTIME_ENTRYPOINTS.md:242 的 drift 回写属实施阶段（若审批纳入同批），本设计阶段不回写。

---

## 审批窗口声明

本设计/审计窗口已完成：2C 冻结输入复核、三类 repair strategy 比较、Strategy Evaluation Matrix、Preferred strategy（A Rebuild Replace-Before-Delete）推荐、数据保全与 rollback 设计、verification gates（RB-0~RB-2 / DBR-0~DBR-9）、failure/rollback plan、init_db/drift 集成判断、0032/0033/0034 解锁路径、P1 impact 边界。

核心结论：

```text
Strategy A (Rebuild, Replace Before Delete) = APPROVED (PREFERRED)
Strategy B (Targeted Reconciliation)        = REJECTED
Strategy C (Forward Repair Migration)       = REJECTED

CR-1 ~ CR-8 Corrections = APPLIED
DB-BL-2D Implementation   = AUTHORIZED (CONDITIONAL ON CR-1~CR-8 APPLIED — 已满足)
```

设计/审计窗口已完成，CR-1~CR-8 修正已原位回写本设计文档，实施授权生效。实施由独立执行窗口按 RB-Q / RB-0~RB-10 + DBR-0~DBR-9 执行，完成后提交独立审批窗口复核。
