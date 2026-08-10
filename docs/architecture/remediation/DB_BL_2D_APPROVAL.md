# DB-BL-2D — Legacy PostgreSQL Baseline Repair Strategy 审批报告

> 阶段：DB-BL-2D **Approval Window**
> 日期：2026-08-10
> 审批窗口：DB-BL-2D Legacy PostgreSQL Baseline Repair Strategy 审批窗口
> 审查对象：`docs/architecture/remediation/DB_BL_2D_LEGACY_POSTGRES_BASELINE_REPAIR_STRATEGY.md`
> 审查范围：独立核验冻结输入合规性 / 三类 Repair Strategy 比较 / Strategy A 优劣 / Replace-Before-Delete 可行性 / 数据保全与 rollback / verification gates / init_db.py provenance 与 prevention / 0032-0034 解锁语义 / P1 边界 / 实施授权。
> 前置冻结：2C-RESUME `DB_BL_2C_RESUME_APPROVAL.md` = `APPROVED_WITH_CORRECTIONS` → `EXACT_RECONCILIATION_VERIFIED`（含 `NOT_EQUIVALENT_TO_0030` / `REJECTED_AS_REPAIR_CANDIDATE` / `DISPOSABLE`）；2B `DB_BL_2B_APPROVAL.md` = `APPROVED_WITH_CORRECTIONS`（Schema Authority = MODEL A / Bootstrap Contract / init_db.py = RESTRICT）。
> 工作原则：独立核验 → 不采信设计报告自述 → 对照 2C/2B 冻结事实逐项判定 → 只冻结策略与实施合同，不自行 rebuild / rename / stamp / 修改 init_db.py / 执行数据库修复。

---

## 1. Technical Decision

```
DB-BL-2D:
APPROVED_WITH_CORRECTIONS
```

Strategy A（Rebuild From Canonical Alembic Head，Replace Before Delete）核心成立，依据充分，可直接冻结为优选策略。Strategy B、C 的淘汰推理成立。2C 冻结输入未被违反，`STAMP_0030 = REJECTED` 仍为不可选项。

**修正项（不影响 Strategy A 核心结论，但实施合同必须先回写）**：

| # | 修正项 | 性质 |
|---|---|---|
| CR-1 | init_db.py provenance 表述过强（§7） | 措辞修正 |
| CR-2 | Service Quiescence 未作为显式 gate（§6） | 实施合同补强 |
| CR-3 | DATABASE_URL「零改动」未区分 config value 与既有连接（§6） | 表述精确化 |
| CR-4 | Database-Level Contract 缺失（owner/permission/extension）（§7） | 实施合同补强 |
| CR-5 | Verification Authority 未冻结为 2C 冻结 Expected@0034 快照（§9） | 验证口径冻结 |
| CR-6 | Seed/Bootstrap 运行时依赖未确认（§11） | 实施合同补强 |
| CR-7 | Rollback 执行顺序与原子停止点不完整（§8） | 实施合同补强 |
| CR-8 | 0032/0033/0034 解锁标签应精确为 `UNBLOCKED_FOR_PG_VERIFICATION`（§12） | 标签精确化 |

> 八项修正均为实施合同精度与闭环补强，不推翻 Strategy A 的策略判定。修正回写到 2D 设计文档后，实施授权生效。

---

## 2. Frozen Inputs

审批窗口独立核验 2D 设计 §1 冻结输入表，逐项与 2C-RESUME APPROVAL §14 + 2C 报告 §11 比对：

| 输入 | 2D 引用值 | 2C 冻结值 | 核对 |
|---|---|---|---|
| Revision Identity | `NOT_EQUIVALENT_TO_0030`（629 项无争议结构 drift，排除 576 comment） | `NOT_EQUIVALENT_TO_0030`（2C APPROVAL §7） | ✅ |
| Stamp Eligibility | `REJECTED_AS_REPAIR_CANDIDATE` | `REJECTED_AS_REPAIR_CANDIDATE`（2C APPROVAL §12） | ✅ |
| Legacy Data | `DISPOSABLE`（5 行、无 PII） | `DISPOSABLE`（2C APPROVAL §11） | ✅ |
| Canonical Final Target | `Expected@0034`（60 业务表 + 1 alembic_version） | `Expected@0034`（2C APPROVAL §2/§14） | ✅ |
| Migration Chain | `PG_RUNTIME_VERIFIED / CONFORMANT` | `PG_RUNTIME_VERIFIED`（2C APPROVAL §14） | ✅ |
| Matrix A | 1205 semantic（含 576 comment→METADATA、629 结构）/ 9 name-only / 0 | 1205/9/0（2C APPROVAL §6） | ✅ |
| Matrix B | 30 semantic（0032/0033/0034 纯加法 delta）/ 0 / 0 | 30/0/0（2C APPROVAL §8） | ✅ |
| Matrix C | 1235 semantic（A∪B）/ 9 / 0 | 1235/9/0（2C APPROVAL §9） | ✅ |
| 主要结构 drift | 类型(238)/默认(178)/可空(93)/索引(86)/约束(26)/缺列(8 业务) | 同（2C APPROVAL §6.3/§7） | ✅ |

```
FROZEN_INPUT_COMPLIANCE: VERIFIED
```

2D 设计未重新对账、未重复查询（2C 已有充分只读证据），符合"事实→设计→审批"原则。

---

## 3. Provenance Correction（CR-1）

### 3.1 过强表述定位

2D 设计 §11.2 当前表述：

> **init_db.py 是 legacy 57 表残骸的根因之一**（2B §2：「SQLite 的合法 create_all 不得自动推导为 PostgreSQL 也允许 create_all——这是当前 dev PG 57 表残骸的根因」）。

该表述将「policy gap 的根因」（SQLite create_all 推导到 PG 的错误推理）与「legacy DB 确切成表 provenance」（已证明 init_db.py 创建了 legacy 57 表）混为一谈。

### 3.2 冻结事实对照

2B APPROVAL §7 证据等级表明确冻结：

```
dev PG 57 表确切成表路径（init_db.py vs 更早 main.py）:
INFERRED — 2A 修正项 5，MOST PLAUSIBLE PROVENANCE，未升级
```

即：init_db.py 是 `MOST PLAUSIBLE PROVENANCE / INFERRED`，**未升级为 PROVEN**。2D 不得将其表述为已证明的唯一历史根因。

### 3.3 正确理由（CR-1 修正要求）

2D 的 RESTRICT 判定应基于 **prevention closure**，而非 provenance 证明：

> `scripts/init_db.py:16` `Base.metadata.create_all(bind=engine)` 无条件、无 backend 守卫（CODE_VERIFIED），是当前仓库仍可能再次制造同类无 Alembic revision PG baseline 的已知风险入口。因此 RESTRICT 属于 prevention closure——消除 rebuild 后再次被污染的入口，而非"已证明 legacy 就是 init_db.py 创建的"。

### 3.4 修正裁定

```
CR-1: REQUIRED CORRECTION
provenance: MOST PLAUSIBLE PROVENANCE / CURRENT RISK ENTRY
NOT PROVEN AS SOLE HISTORICAL CREATOR
不影响 Strategy A 核心审批
```

---

## 4. Strategy Decision

### 4.1 Strategy A — Rebuild From Canonical Alembic Head

**Q1（Frozen Input Compliance）**：设计正确继承 `STAMP_0030 = REJECTED_AS_REPAIR_CANDIDATE`，未以任何别名重新引入 `targeted repair → stamp0030 → upgrade`。§3.3 明确禁止"先 stamp head → 再慢慢修"；§4 淘汰 Strategy C。✅

**Q2（Strategy A 是否优于 Targeted Repair）**：审批窗口独立复核 Matrix C 规模与类别。排除 576 comment 后，629 项无争议结构 drift，其中：
- **type_diff(238)** 含真实高风险转换：`integer↔bigint`、`text↔jsonb`、`timestamp without time zone ↔ with time zone`（2C APPROVAL §6.3 抽样 CODE_VERIFIED，与项目历史生产 500 / TypeError 根因吻合）——属真实 schema execution semantics 转换，非 metadata-only。
- default_diff(178)、nullable_diff(93)、index(86)、constraint(26)、missing columns(8 业务)。

综合判断：对一份 5 行 DISPOSABLE 本地开发库做 629 项含 238 项高风险 type 转换的 targeted reconciliation，data risk（type 转换破坏）、revision identity（repair 后仍需 stamp 0034 + 全量重对账）、verification burden（≈重做 2C）、future maintainability（手工 repair 不入 chain）、rollback（type 转换不可逆）五维均劣于 rebuild，且无相应业务收益。判断成立，非仅"629 很多"。✅

**Q3（Strategy B Revision Identity）**：设计 §3.2 #8/#9 + §3.3 正确坚持 `repair → 独立证明 == Expected@0034 → 才考虑 revision bookkeeping`，禁止 `stamp head first → repair later`。Strategy B 最终复杂度（629 ALTER + 576 comment + 全量重对账 + stamp 0034 审批）显著超过 rebuild。

**Q4（Strategy C）**：设计 §4 正确识别进入问题——legacy 无可信 revision identity，forward repair migration 必须先 stamp 一个未经证明的起点 revision；若 stamp 0030 违反 2C，若伪造起点则 migration 语义非法；塞入 canonical chain 还会污染未来所有合法空库 bootstrap。推理成立。

```
Strategy A (Rebuild, Replace Before Delete) = APPROVED
Strategy B (Targeted Reconciliation)        = REJECTED
Strategy C (Forward Repair Migration)       = REJECTED
```

### 4.2 实施方式

```
Preferred implementation:
REPLACE-BEFORE-DELETE  （A1 rename）
NOT DROP-FIRST REBUILD
```

A1（rename）`DATABASE_URL` config value 不变、legacy 自动保留为 rollback artifact，符合 YAGNI 与最小改动。禁止 DROP-FIRST 变体。

---

## 5. Replace-Before-Delete Contract

冻结原则（§十四 Q8）：

```
CREATE / VERIFY REPLACEMENT BEFORE PERMANENT RETIREMENT
```

- RENAME `auto_wechat → auto_wechat_legacy_backup` 为非破坏性 identity change（数据完整保留于新名下），构成主力 rollback artifact。
- 永久 DELETE 旧库为后续 cleanup gate（2D 设计 §8 RB-10），不是 rebuild 第一动作。
- 旧库在全部 DBR gate 通过 + 观察期前必须保持可恢复。

```
REPLACE_BEFORE_DELETE: APPROVED
legacy_retained_until: ALL DBR GATES PASS + OBSERVATION
DELETE_LEGACY: RB-10 ONLY (later cleanup gate, not authorized in this approval)
```

---

## 6. Service Quiescence / Connection Contract（CR-2 / CR-3）

### 6.1 CR-2：显式 Quiesce Gate

2D 设计 §2.4 脚注级提到"rename 前停应用连接"，§2.1 概念流提到"停止使用 legacy DB（应用停连接）"，但**未作为显式 gate**。PostgreSQL `ALTER DATABASE ... RENAME TO` 在存在活跃连接占用目标库时会失败；quiesce 不是可选项，是硬前置。

**修正要求**：实施合同必须补入显式 quiesce gate，置于 RB-2（rename）之前、RB-1 之后：

```text
RB-Q  quiesce local DB consumers:
      - stop auto-wechat-api (9000 主服务)
      - stop background workers / schedulers
      - stop migration processes / alembic 进程
      - stop 其他本地服务（19000 Local Agent 不直接持有 auto_wechat DB 连接，确认无连接）
      - confirm environment (RB-0 环境标识复核)
→ perform replacement (rename → create → bootstrap)
→ restart/reconnect after verification (DBR-6/7 PASS 后)
```

不得假设已有连接会自动切换到新 database。

### 6.2 CR-3：DATABASE_URL 表述精确化

2D 设计 §2.4「DATABASE_URL 零改动」混淆了两件事。冻结区分：

```text
DATABASE_URL CONFIG VALUE:   UNCHANGED  （database-name 部分仍为 auto_wechat，A1 rename 后同名新库）
EXISTING DB CONNECTIONS:     MUST BE RESTARTED / RECONNECTED  （既有连接指向的是旧库的 backend pid，rename 不迁移活跃连接）
```

"零改动"仅适用于配置值；既有连接必须重启重连。实施合同须明示两者不混为一句"零切换"。

```
CR-2: REQUIRED CORRECTION (add explicit quiesce gate)
CR-3: REQUIRED CORRECTION (distinguish config value vs existing connections)
```

---

## 7. Database-Level Contract（CR-4）

2D 设计未涉及数据库级前提（§十一 Q6）。`CREATE DATABASE auto_wechat` 后，新库须满足应用合法使用条件，不止"schema 正确"。

**修正要求**：实施合同须至少核验项目实际依赖项（遵循 YAGNI，不建设数据库配置平台）：

| 维度 | 要求 |
|---|---|
| database owner | 新库 owner 须与 `DATABASE_URL` 中连接角色一致或授权 |
| application role permissions | CONNECT / CREATE / USAGE（应用运行所需实际权限，由实施时按 `DATABASE_URL` 角色核验） |
| encoding | 默认 UTF8，确认与应用一致 |
| locale / collation | 若项目有显式约束则核验，否则默认 |
| required extensions | 核验 migration chain 是否依赖任何 PG extension（如 `pg_trgm`/`uuid-ossp`）；有则 CREATE EXTENSION 须在 upgrade 前就绪 |
| schema / search_path | 若项目有显式 `public` 外约束则核验 |

实施时以最小核验确认"新 DB 不仅 schema 正确，且可被当前应用合法使用"。

```
CR-4: REQUIRED CORRECTION (database-level contract: owner/permission/extension minimum)
```

---

## 8. Data Safety / Rollback（CR-7）

### 8.1 双保险合理性

2D 设计 §7.2 推荐 Option A（rename 保留）+ Option B（pg_dump schema+5 行）。数据量极小（5 行），完整 local pg_dump 成本秒级，双保险合理，非过度。✅

### 8.2 CR-7：执行顺序与原子停止点补强

2D 设计 §8 执行顺序为 RB-0 → RB-1 → RB-2(rename+pg_dump) → RB-3。审批窗口要求：

**（a）执行顺序明确化**——`pg_dump` 须在 `rename` 前，且 dump 成功须先核验：

```text
RB-0  environment identity verified
RB-1  disposability reconfirmed (count=5, PII=0, 与 2C 不一致则停)
RB-2a pg_dump legacy (schema + 5 rows)
RB-2b verify dump success (可恢复性核验)
RB-Q  quiesce local DB consumers (CR-2)
RB-2c rename legacy → auto_wechat_legacy_backup
RB-3  create empty auto_wechat
```

原则：**在任何 identity-changing operation（rename）前，应已经有可核验 rollback evidence（pg_dump 验证成功）**。rename 本身非破坏性（数据保留），但 dump 作为附加保险须先就位。

**（b）原子停止点补强**（§二十三）——2D 设计 §10 覆盖了 bootstrap/schema/ready/RB-1 失败，但未显式覆盖：

| 失败点 | 停止规则（冻结） |
|---|---|
| pg_dump 失败（RB-2a/b） | STOP，不 rename |
| rename 失败（RB-2c） | STOP，不 create replacement |
| create new DB 失败（RB-3） | STOP，legacy 未受影响，保留 rename 状态调查 |
| bootstrap 失败（DBR-3） | STOP，不切应用；keep legacy，discard failed new DB |
| schema diff ≠ 0（DBR-4/5） | STOP，不切应用；keep legacy，keep new DB for inspection |
| readiness 失败（DBR-6/7） | rollback connection/database identity；keep new DB for inspection；STOP |
| prevention guard 测试失败（DBR-9） | 不得宣称 repair closure 完成 |

**（c）Rollback 不依赖"新库修到能用"**——2D 设计 §10 已正确禁止"失败后现场修新库直到能跑"（§十三）。冻结：

```text
ROLLBACK CONTRACT: STOP + 保留现状调查
禁止 manual ALTER new DB until application starts
```

```
CR-7: REQUIRED CORRECTION (explicit dump-before-rename ordering + dump-fail/rename-fail/create-fail stop points)
```

---

## 9. Verification Authority（CR-5）

### 9.1 主参考冻结

2D 设计 §8 RB-5 / §9 DBR-4 引用 `Expected@0034` 但未明确区分"2C 冻结快照"与"重新生成"。冻结：

```text
PRIMARY VERIFICATION REFERENCE:
2C 冻结并审批过的 Expected@0034 evidence snapshot
（docs/architecture/remediation/db_bl_2c_resume_evidence/expected_0034.json）
```

避免风险：修复后重新生成 Expected → 若 migration chain 意外同时改变 → Actual 与 Expected 一起漂移 → diff 仍为 0（假 PASS）。

### 9.2 Supplemental 运行时 sanity gate

可额外重新跑 `fresh empty → head` 作为 runtime sanity，但：

```text
新生成 Expected 不得覆盖 2C 冻结 canonical evidence，除非显式解释差异。
```

### 9.3 Schema Exactness Gate（§十六 Q10）

2D 设计 §9.1 要求 `STRUCTURAL_DIFF=0 / METADATA_DIFF=0 / NAME_ONLY_DIFF=0`，三者全 0（同链产物应自然达成）。任一非 0 → 视为新 blocker，停止，不得 normalize away unexplained differences。✅

```
CR-5: REQUIRED CORRECTION (freeze primary reference on 2C frozen Expected@0034 snapshot)
SCHEMA_EXACTNESS_GATE: APPROVED (structural=0, metadata=0, name_only=0)
```

---

## 10. DBR Gates

2D 设计 §9 DBR-0~DBR-9 语义覆盖审批要求（§二十二），逐项审批：

| Gate | 要求 | 审批 |
|---|---|---|
| DBR-0 | Strategy approved（独立审批） | ✅ APPROVED（本报告） |
| DBR-1 | legacy disposability reconfirmed（count=5、PII=0、无可重建数据）；与 2C 不一致则停 | ✅ APPROVED |
| DBR-2 | rollback artifact ready（legacy renamed 保留 + pg_dump 验证成功） | ✅ APPROVED（CR-7 补 dump 验证子步） |
| DBR-3 | new empty DB bootstrap head PASS（EMPTY→0034） | ✅ APPROVED |
| DBR-4 | New Actual == frozen Expected@0034（structural=0 / metadata=0 / name_only=0） | ✅ APPROVED（CR-5 冻结主参考） |
| DBR-5 | alembic current=head=0034（单头） | ✅ APPROVED |
| DBR-6 | /ready PASS | ✅ APPROVED（CR-6 补 seed 依赖确认） |
| DBR-7 | minimal application smoke PASS | ✅ APPROVED |
| DBR-8 | legacy retained and recoverable until all verification passes | ✅ APPROVED |
| DBR-9 | approved drift-prevention guard/doc-sync complete | ✅ APPROVED（CR-1 provenance 措辞 + same-batch 见 §11） |

```
DBR GATES: APPROVED (with CR corrections folded into DBR-2/DBR-4/DBR-6/DBR-9)
```

2D 设计另有 RB-0~RB-10 执行步骤编号（执行序列），与 DBR（验证 gate）语义不冲突，映射清晰，保留。

---

## 11. init_db.py Prevention Decision

### 11.1 同批裁定

```
init_db.py RESTRICT guard: SAME BATCH （与 rebuild 同批实施）
```

依据：
- rebuild 一个干净 0034 库却留无守卫的 `scripts/init_db.py:16`（无条件 create_all，CODE_VERIFIED），等于重建根因入口未除——开发者手工 `python scripts/init_db.py`（README:75 现实触发点）会再次 create_all 污染新库。
- 2B 已确认 Dockerfile / docker-compose / CI 无 init_db 调用（无自动化风险），触发仅限手工；但根因入口未除不符合 prevention closure 语义。
- 同批最小 guard 与 `ensure_runtime_schema()` PG skip 语义对齐，形成 runtime + bootstrap 工具双重 PG create_all 拦截，构成闭环。

### 11.2 scope 约束（不得顺手大改）

同批实施严格限定为 2B §4 冻结的 RESTRICT scope，**不得扩大**：

```text
- init_db.py 加 PG backend 守卫（PG 下 REFUSE create_all / sys.exit(1)，SQLite 保留当前 allowed 行为）
- seed 独立化（保留 SQLite dev 的 create_all + seed 合法需求）
- README:75 区分 SQLite 用 init_db.py / PG 用 alembic upgrade head
- RUNTIME_ENTRYPOINTS.md:242 加 SQLite-only (PG refused) 注记
- 不引入新依赖、不改治理规则文件 01-04
```

### 11.3 provenance 措辞（CR-1 适用）

RESTRICT 的实施注释 / doc sync 须基于 prevention framing（§3.3），不得写"已证明 legacy 就是 init_db.py 创建的"。

```
init_db.py: SAME BATCH (RESTRICT, minimal, 2B scope, no expansion)
provenance: MOST PLAUSIBLE / CURRENT RISK ENTRY
```

---

## 12. 0032 / 0033 / 0034 Unlock Semantics（CR-8）

2D 设计 §12.2 正确表达 `migration exists at head != consumer PG verification complete`，方向正确。但解锁标签须精确化（§二十）：

```text
baseline repair 通过后:
0032 / 0033 / 0034:
  BLOCKED_BY_SCHEMA_BASELINE_MISMATCH
  → UNBLOCKED_FOR_PG_VERIFICATION   （仅此一档，不跳级）
  → NOT PG_VERIFIED
```

- 新 DB 是 `empty → head 0034`，仅证明三条 migration 能在链中正常落地（结构性可达）。
- P1 对三个 consumer 的 PG verification 仍有各自 runtime 要求（write/read、idempotency、schema behavior），属各自 consumer 技术设计范围。
- `UNBLOCKED_FOR_PG_VERIFICATION ≠ PG_VERIFIED`。consumer-level verification 仍未执行。

```
CR-8: REQUIRED CORRECTION (label = UNBLOCKED_FOR_PG_VERIFICATION, not generic UNBLOCKED)
UNLOCK_SEMANTICS: APPROVED (with precision label)
```

---

## 13. Implementation Authorization

### 13.1 实施授权

```text
DB-BL-2D-IMPLEMENTATION:
AUTHORIZED  (CONDITIONAL ON CR-1~CR-8 APPLIED TO DESIGN DOC)
```

授权在 CR-1~CR-8 八项修正回写到 `DB_BL_2D_LEGACY_POSTGRES_BASELINE_REPAIR_STRATEGY.md` 后生效（同 2B "进入 2C 前必须完成回写"模式）。修正均为实施合同补强，不推翻 Strategy A。

### 13.2 授权范围（只允许 local development baseline remediation）

```text
ALLOWED:
- R1/R2 已批准 doc corrections 如仍有遗留
- final environment/disposability checks (RB-0/RB-1)
- rollback dump (RB-2a/2b, 验证成功)
- quiesce local DB consumers (RB-Q, CR-2)
- rename legacy DB → auto_wechat_legacy_backup (RB-2c)
- create canonical empty DB (RB-3)
- Alembic head bootstrap (RB-4)
- frozen Expected@0034 comparison (RB-5, CR-5 主参考)
- application reconnect/readiness (RB-6/7/8, CR-3 重连)
- approved init_db.py PostgreSQL guard (same batch, RESTRICT minimal scope, CR-1)
- approved current-facing documentation sync (README:75 / RUNTIME_ENTRYPOINTS:242)
```

### 13.3 明确禁止（§二十五 / §二十六）

```text
FORBIDDEN:
- production / staging DB 操作
- P1 consumer 业务修改
- M07 Core 修改
- consumer PG closure tests 本身（0032/0033/0034 consumer PG verification 属后续独立阶段）
- alembic stamp（任何 revision，legacy / disposable / prod / staging）
- DROP legacy（RB-10 永久删除不在本授权范围，须后续 cleanup gate）
- create_all / schema copy / manual CREATE TABLE / manual schema patch
- init_db.py 超出 2B RESTRICT scope 的改动
- 用新生成 Expected 覆盖 2C 冻结 canonical evidence（不解释差异时）
```

---

## 14. P1 Boundary

继续冻结（§二十一）：

```text
DB-BL closure  !=  P1 Technical Closure
DB-BL-2D 完成  !=  COMPUTE-IDEMPOTENCY-001 关闭
```

DB-BL-2D 完成后，P1 Technical Closure 仍至少包括：

| Blocker | 当前状态 | 说明 |
|---|---|---|
| A. auto_wechat schema baseline | 本 2D 解决（DBR-* 全 PASS 后） | 解锁 0032/0033/0034 → UNBLOCKED_FOR_PG_VERIFICATION |
| B. RAG Query 0005 PG（xg_douyin_ai_cs） | `BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT` | 不在本 2D 范围，Docker 恢复后独立补 |
| C. Global Active None Audit | PENDING | 重新全局搜索 active=None |
| D. Final PG Concurrent Closure Gate | PENDING | 并发闭包门禁 |
| + Daily Report 0032 consumer PG verification | UNBLOCKED 后独立执行 | 非 2D 范围 |
| + M05 0033 consumer PG verification | 同 | 非 2D 范围 |
| + Preview 0034 consumer PG verification | 同 | 非 2D 范围 |

Consumer Migration Complete（11/11）≠ Technical Closure Complete（≠ E2E_VERIFIED_FIXED）。本审批不过度宣称。

---

## 15. Seed / Bootstrap Runtime Dependency（CR-6）

### 15.1 冻结事实（CODE_VERIFIED）

审批窗口独立核验：

- migration `0006_create_runtime_cutover_gap_tables.py` 只 `create_table("check_configs")`，**不 seed `DEFAULT_CONFIGS`**。
- `DEFAULT_CONFIGS` 仅由 `scripts/init_db.py`（行 20-34）注入——而 init_db.py 正是被 RESTRICT 的入口，rebuild 后新库为空 `check_configs`。
- 多处 scheduler/service 读取 `check_configs`：`check_scheduler.py:83`（读 `check_interval_minutes`，**有默认回退 5 分钟 + try/except**）、`wechat_auto_detect_scheduler.py`（多处，部分自动创建缺失行）、`notification_service.py:386`、`lead_notifications.py:52`（部分自动创建）。

### 15.2 CR-6 修正要求

2D 设计未确认应用是否依赖 migration 外 seed/bootstrap records 才能启动。冻结：

```text
空业务数据库  !=  可运行数据库  （须显式确认，不得默认）
```

实施合同须在 DBR-6（/ready PASS）前确认：
- canonical migrations 是否负责必要 seeds？（当前 `check_configs` 无 migration seed）
- 若存在 migration 外必须人工初始化的 runtime-required data，必须登记处理方式。
- `check_scheduler.py` 等读取 config 行虽有默认回退（CODE_VERIFIED），但须以 /ready 实跑确认空 `check_configs` 不阻断启动。
- **不得恢复那 5 条旧 compute_* 测试数据**，除非有明确必要（无必要，DISPOSABLE）。

```
CR-6: REQUIRED CORRECTION (confirm empty 0034 DB runnable without seed; register any runtime-required data outside migrations)
```

---

## 16. Application Readiness（Q11）

2D 设计 §8 RB-7/8 + §9 DBR-6/7 定义最小 smoke（/ready PASS + 不塞完整 E2E）。✅

DBR-6 须验证：
- DB revision gate PASS（alembic current=head=0034）
- application connects to new DB
- required DB permissions 正常（CR-4）
- startup 无 schema bootstrap / create_all
- seed 依赖不阻断（CR-6）

不把完整业务 E2E 塞进 2D。✅

---

## 审批结论

```text
Technical Decision           = APPROVED_WITH_CORRECTIONS
Strategy A (Rebuild)         = APPROVED  (Replace-Before-Delete, A1 rename)
Strategy B                   = REJECTED
Strategy C                   = REJECTED
Frozen Input Compliance      = VERIFIED
Provenance (init_db.py)      = MOST PLAUSIBLE / CURRENT RISK ENTRY (CR-1)
Replace-Before-Delete        = APPROVED
Service Quiescence           = REQUIRED EXPLICIT GATE (CR-2)
DATABASE_URL                 = config value unchanged ≠ existing connections (CR-3)
Database-Level Contract      = REQUIRED owner/permission/extension minimum (CR-4)
Data Safety / Rollback       = APPROVED (dump-before-rename + stop points, CR-7)
Verification Authority       = frozen 2C Expected@0034 primary (CR-5)
Schema Exactness Gate        = structural=0 / metadata=0 / name_only=0
DBR Gates                    = APPROVED (CR folded in)
init_db.py Prevention        = SAME BATCH (RESTRICT minimal, 2B scope, no expansion)
0032/0033/0034 Unlock        = UNBLOCKED_FOR_PG_VERIFICATION only (CR-8)
Seed/Bootstrap Dependency    = REQUIRED confirm empty DB runnable (CR-6)
Implementation Authorization = AUTHORIZED (CONDITIONAL ON CR-1~CR-8 APPLIED)
P1 Boundary                  = DB-BL closure != P1 Technical Closure
```

**进入 DB-BL-2D Implementation 前必须完成**：将 CR-1~CR-8 八项修正回写到 `DB_BL_2D_LEGACY_POSTGRES_BASELINE_REPAIR_STRATEGY.md`，冻结为实施合同。

审批窗口到此停止。**不 rebuild、不 rename、不 stamp、不切换连接、不修改 init_db.py、不执行任何数据库修复。** 实施须在 CR 修正回写后、由独立实施窗口按 RB-Q/RB-0~RB-10 + DBR-0~DBR-9 执行。
