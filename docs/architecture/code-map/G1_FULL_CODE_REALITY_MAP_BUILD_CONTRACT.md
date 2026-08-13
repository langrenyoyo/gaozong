# G1 Full Code Reality Map — Build Contract

> **Task-ID**: `G1-CODE-REALITY-MAP-BUILD-SCOPE-1`
> **文档性质**：PRE-BUILD SCOPE / EXECUTION CONTRACT（执行合同，非 Full Build 产物）
> **授权范围**：READ / AUDIT / COUNT / CLASSIFY / DESIGN CONTRACT / AUTHOR GOVERNANCE / COMMIT CANDIDATE / STOP FOR OWNER REVIEW
> **不授权**：FULL_CODE_MAP_BUILD、任何源码/测试/迁移/路由/生成器改动、PUSH、RELEASE
> **状态**：`PENDING_OWNER_APPROVAL`（含 4 项 OD-G1-* 待决策，见 §23）
> **配套**：本文为执行合同；同目录 `code_index.schema.yaml`（DRAFT schema）与 `module_chain_template.md`（DRAFT 模板）为附件。

---

## 1. Purpose

定义 G1 Full Code Reality Map 的**执行合同**：在 Full Build 启动前，冻结扫描基线、文件级稳定 ID 规则、归属契约、状态/生命周期契约、依赖证据等级、证据格式、置信度模型、分批策略、覆盖分母、验收计数与校验策略。本文档**不生成任何 file-map 数据**（§20 仅允许 3–10 个代表性示例验证 schema）。

Full Build 启动 Gate 见 §22；在 Owner 批准本合同 + 解决 OD-G1-* 前，`FULL_CODE_MAP_BUILD = NOT AUTHORIZED`。

---

## 2. Frozen Inputs（上游已批准，本轮不得改写）

| 决策 | 冻结值 |
|---|---|
| 七模块分类 | M01 抖音AI小高客服 / M02 AI小高线索 / M03 AI小高智能体 / M04 AI小高微信助手 / M05 小高素材库 / M06 AI小高剪辑 / M07 AI小高算力（`APPROVED/FROZEN`，稳定 ID 不得新增 M08 / 合并 M05·M06 / 按菜单重编号） |
| 模块 Confidence | M01 HIGH / M02 HIGH / M03 HIGH / M04 HIGH / M05 MEDIUM / M06 MEDIUM / M07 HIGH |
| Platform 边界 | PLATFORM-AUTH / -DB / -GATE / -OUTBOX / -SCHED / -ISO / -RELEASE（7 项） |
| DOMAIN_SHARED | `contact_extraction*` 系列 → owner=M02，DOMAIN_SHARED，**非 PLATFORM** |
| WINDOWS_ONLY | feedback / lead_notifications 条件注册 → runtime 语义 `WINDOWS_ONLY`，非 owner_type、非 env-toggle |
| Alembic 双字段 | `REPOSITORY_HEAD != PRODUCTION_REVISION`，禁止合并为单一 `alembic_version` |
| 两层模型 | Layer 1 = `CODE_INDEX.yaml`（模块级，canonical，生成器维护，本轮 READ ONLY）；Layer 2 = `code-map/code_index.*`（文件级，DERIVED GOVERNANCE ARTIFACT） |
| Derived 硬边界 | `code-map/**` 禁止被 runtime 读取（startup/permission/route/feature/DB），禁止 `load_code_map()` 类依赖 |

### Boundary Conflict Registry（保留全部历史编号）

`BC-01 ACTIVE / BC-02 ACTIVE / BC-03 ACTIVE / BC-04 ACTIVE / BC-05 RESOLVED / BC-06 ACTIVE / BC-07 ACTIVE / BC-08 ACTIVE` —— 本轮仅 REGISTER/TRACE/LINK，不得 RESOLVE BY REFACTORING（BC-02/06/07/08 只记录不整改）。

### Unknown Registry

Active：`U-001`（lifecycle_candidates 定性）/ `U-002`（services 文件归属）/ `U-004`（M05/M06 G3 验收边界）/ `U-007`（剩余测试映射）。
已解决/转阶段（**不得再统计为 ACTIVE**）：`U-003 RESOLVED` / `U-005 SUBSTANTIALLY RESOLVED→detail` / `U-006 SUBSTANTIALLY RESOLVED→detail`。

---

## 3. Scan Baseline（本轮已执行只读冻结）

| 项 | 值 |
|---|---|
| Scan-Base-Commit | `88235b5bba363fd0dec4945b8e38aba1e82e2d9b`（G0_CANDIDATE_SHA） |
| Scan-Branch | `master` |
| Tracked Worktree | **CLEAN**（无 M/A/D 前缀 tracked changes） |
| Untracked | `docs/architecture/code-map/`（已知 G1 治理产物目录，非未知改动，不触发 STOP） |

> 若未来 Full Build 窗口检出未知 tracked changes → `STOP / OWNER_DECISION_REQUIRED`；禁止 reset/restore/clean/stash/rebase。

---

## 4. CODE_INDEX Baseline Drift（BC-03 精确重算）

| 项 | 值 |
|---|---|
| Code-Index-Baseline-Commit | `c26ec227e70d689e1b98f838253a36685aa6b0a6`（`CODE_INDEX.yaml:17`） |
| Scan-Base-Commit | `88235b5bba363fd0dec4945b8e38aba1e82e2d9b` |
| Commit Drift | **121** |
| Changed File Drift | **213**（+107050 / -100） |

> 与 Exploration 时刻 `121/213` 一致（基线未推进）。**本阶段仅 measure/record/design，禁止 refresh CODE_INDEX.yaml（属 Full Build/Index mutation，§22/§37）**。七模块纵向边界未变；新增执行实体与迁移留 Full Build 的 G1-M1 阶段登记。

---

## 5. Included / Excluded Scope

### 5.1 Included roots（Full Build 扫描根）

```
app/**          后端 9000 业务代码
apps/**         9100 子应用 + compute 子应用
packages/**     共享 clients/common（需映射，见 §11 DOMAIN_SHARED 处理参照）
frontend/**     React 前端（src 代码 + 运行配置）
tests/**        测试（一等公民，见 §21）
migrations/**   Alembic 迁移（schema 资产，见 §26）
scripts/**      部署/迁移/调试脚本
docker/** + 根 compose/Dockerfile/.env*.example/requirements/*.spec  运行时配置
docs/architecture/**  治理文档（DOCUMENT，轻量映射，不进 code-ownership 分母）
```

### 5.2 Excluded（不进 Coverage Denominator）

| 类别 | 实测 | 处理 |
|---|---|---|
| `docs/` 全部文档 | 379 | DOCUMENT 类型，不进 code-ownership 分母（架构治理文档轻量映射为 DOCUMENT entry，无 module owner 必填） |
| 静态资源（png/jpg/svg/ico/woff/ttf/eot/gif/webp） | 27 | ASSET，排除 |
| lock 文件（bun.lock / package-lock.json） | 2 | GENERATED/VENDOR，排除 |
| node_modules / .venv / dist / build / cache / logs / local data / 下载二进制 | 0 tracked | 未被 git 追踪，天然排除 |

### 5.3 Git-tracked generated 文件规则

仅 2 个 lock 文件被追踪 → 排除。若 Full Build 发现新 tracked generated 产物（如生成器输出）→ `artifact_type=GENERATED` + 标 `derived_from` 源，**进分母但 owner=GENERATOR**（不强配业务模块）。

---

## 6. Module / Platform Taxonomy（UNCHANGED，§2 冻结）

略——见 §2 Frozen Inputs。文件级 Map 通过 `owner_type=MODULE` + `owner_id=M01..M07` 关联模块级 `CODE_INDEX.yaml`。

---

## 7. Artifact Type Taxonomy

Full Build 按 `artifact_type` 分类，枚举（本轮收敛冻结）：

```
BACKEND_ROUTER        后端 router 文件
BACKEND_SERVICE       后端 service 文件
BACKEND_MODEL         ORM 模型 / 数据访问
BACKEND_AUTH          认证/RBAC
BACKEND_WORKER        后台 worker / outbox
BACKEND_SCHEDULER     调度器
BACKEND_INTEGRATION   外部集成 client
BACKEND_ENTRY         main / lifespan / 启动入口
BACKEND_CODE          其它后端 .py
FRONTEND_PAGE         前端页面
FRONTEND_COMPONENT    前端组件
FRONTEND_API_CLIENT   前端 API 客户端
FRONTEND_HOOK         前端 hook/util
FRONTEND_CONFIG       vite/tsconfig/package.json
FRONTEND_CODE         其它前端代码
TEST                  测试文件
MIGRATION             Alembic 迁移脚本
SCRIPT                部署/迁移/调试脚本
CONFIG                运行时配置（compose/env/Dockerfile/ini/requirements）
AUTH                  鉴权资产（与 BACKEND_AUTH 区分：AUTH 指独立鉴权模块文件集）
DOCUMENT              治理/需求/计划文档（不进分母）
GENERATED             生成器产物
ASSET                 静态资源（排除）
GOVERNANCE            治理契约/索引本身（code-map/* 自身）
OTHER                 兜底（必须 notes 说明）
```

> `OTHER` 仅在无可归类型时使用；禁止用 OTHER 逃避归属分析（与 §11 UNKNOWN≠MISC 同理）。

---

## 8. Stable File ID Contract（本轮最重要产物）

### 8.1 格式

`FILE-000001` —— 前缀 `FILE-` + 6 位零填充递增序号。

### 8.2 分配规则

- **append-only sequence**：按 Full Build 分批首次扫描顺序分配，序号永不复用、永不回填。
- ID 绑定**逻辑制品**，而非物理路径（见 §8.3）。
- 生成器须保证：无重复 ID、无重复 path→ID 映射（验收计数见 §19）。

### 8.3 文件移动语义（OD-G1-02，见 §23）

**推荐规则**：ID 跟随逻辑制品。
- git 检测到 rename（`git log --follow` / rename detection）→ **保留原 ID**，`path` 更新，`path_history[]` 追加旧路径。
- git 无法检测（delete + add 不同内容）→ 视为**新制品**，分配新 ID；旧记录 `status=REMOVED` 保留。
- **重命名后改内容**：内容相似度 > 阈值（Full Build 用 `git log --follow` 判定，不做 AST）→ 保留 ID + `notes` 标注 rename-with-edit；否则新 ID。

> 该规则依赖 git rename 检测能力，非 AST 追踪——`ceiling: 纯 delete+add 无法判定时降级为新 ID`（标注已知上限）。

### 8.4 文件删除——生命周期

```
ACTIVE → MISSING（git 不再追踪但历史记录保留）→ REMOVED（Full Build 确认永久移除）
```

- 禁止删除历史记录条目。
- `LEGACY` 不是删除态；`LEGACY_CANDIDATE != SAFE_TO_DELETE`。

### 8.5 Path 规范化（Windows）

- **存储**：git canonical path 原样存储（不改大小写/不改斜杠）。
- **比较**：仅用于去重/查找时规范化——小写、正斜杠、去尾斜杠。规范化值不落库，仅作比较索引。
- 禁止：用规范化值覆盖 git 实际 path。

### 8.6 新文件如何分配 ID

Full Build 各 batch 首次扫描某文件即分配下一可用序号；跨 batch 由生成器维护全局计数器，不得回填或跳跃。

---

## 9. Ownership Contract

### 9.1 owner_type 枚举（冻结）

```
MODULE           → owner_id ∈ M01..M07
PLATFORM         → owner_id ∈ PLATFORM-AUTH/-DB/-GATE/-OUTBOX/-SCHED/-ISO/-RELEASE
COMPATIBILITY    → owner_id 为兼容层编号（COMPAT-*，见 §11）
UNKNOWN          → owner_id = null（必须 notes 写理由 + 缺什么证据 + follow-up）
```

> **DOMAIN_SHARED 不是 owner_type**（修正 §11 候选清单）：领域共享用 `owner_type=MODULE` + `owner_id=M02` + `runtime_role=DOMAIN_SHARED` 表达（见 §12）。不引入 `owners[]` 多所有者模型（本阶段无此需求，避免复杂度）。

### 9.2 权威字段 vs 派生字段（消除双写漂移）

| 字段 | 角色 |
|---|---|
| `owner_type` + `owner_id` | **权威**（authoritative） |
| `module` | **派生/兼容**（= owner_id when owner_type=MODULE，否则 null；由生成器从 owner 字段计算，不人工双写） |

禁止 `module` 与 `owner_id` 同时人工维护不同值。schema 校验：`owner_type=MODULE` → `module == owner_id`。

---

## 10. Status / Legacy Contract

### 10.1 status 枚举

```
ACTIVE           现役，正式运行路径
COMPAT           仍被 runtime/route/import 使用，但主要服务向后兼容
LEGACY           有真实证据的历史方案（已被替代但仍有 env 控制/调用）
LEGACY_CANDIDATE 疑似历史但未证明可安全删除（≠ SAFE_TO_DELETE）
DEV_ONLY         仅开发/调试态
TEST             仅测试态
WINDOWS_ONLY     见 §18（runtime_role 表达，非 status）
UNKNOWN          证据不足
MIXED            单文件内多区域不同 status（见 §24，OD-G1-01）
```

### 10.2 判定证据要求

- `LEGACY` 必须有 env 开关/调用链/迁移替代证据，**不得仅凭"文件旧/命名差/看起来没人用"**。
- `COMPAT` 定义：仍被正式 runtime/route/import 使用，主要服务向后兼容（如 legacy_webhook_router、前端 redirects）。
- `LEGACY_CANDIDATE != SAFE_TO_DELETE`——删除属 G2，本轮不授权。

---

## 11. Compatibility Contract

`owner_type=COMPATIBILITY` 的条目登记：
- `compat_for`：替代了什么正式路径
- `purpose` / `current_caller` / `removal_prerequisite`

来源对照 `LEGACY_REGISTER.md` 的 COMPAT 5 项（004/006/008/011/012）+ BC-07 legacy_webhook + BC-08 前端 redirects。

---

## 12. Runtime Role Contract

```
HTTP_API          router 提供 HTTP 端点
WORKER            后台 worker / outbox consumer
SCHEDULER         定时调度器
STARTUP           lifespan / 启动钩子
SUBAPP            子应用（9100 / apps/compute）
SCRIPT            脚本入口
DOMAIN_SHARED     领域共享能力（contact_extraction*，owner=M02）
WINDOWS_ONLY      仅 Windows 平台运行（feedback/lead_notifications；与 owner 正交）
NONE              无 runtime 角色（文档/配置/资产）
```

> `WINDOWS_ONLY` 是 runtime_role，非 owner_type。`owner=M02 + runtime_role=WINDOWS_ONLY` 合法（如 feedback router）。禁止 `owner_type=WINDOWS`。

### DOMAIN_SHARED 表达（受控）

`contact_extraction*` → `owner_type=MODULE` + `owner_id=M02` + `runtime_role=DOMAIN_SHARED`。单 owner，不引入多 owner 模型（§2 已冻结，无需 STOP）。

---

## 13. Dependency Contract（证据等级，非伪精确调用图）

### 13.1 依赖证据类型

```
STATIC_IMPORT        import 语句
ROUTER_INCLUDE        main.py / 子应用 include_router
SERVICE_CALL         显式 service→service 调用
DB_TABLE             读写某表（ORM model / raw SQL）
HTTP_EXTERNAL        调用外部 HTTP 服务
CONFIG_REFERENCE     读 config 项
DYNAMIC_UNKNOWN      运行时动态调度，无法静态判定
```

### 13.2 规则

- **只有能提供 evidence 的依赖才记录为事实**。禁止凭文件名猜 `a.py probably depends on b.py`。
- `dependencies`（主动）与 `depended_by`（反向，生成器计算，不人工双写）。
- Scope 阶段不建完整调用图；Full Build 按 batch 逐文件标注可证据依赖；`DYNAMIC_UNKNOWN` 显式标记，不静默遗漏。
- `CROSS_MODULE_DATA_ACCESS`：`DB_TABLE` 类型跨模块读写须显式标记（登记不整改）。

---

## 14. Evidence Contract

每个 entry 必须能回答"为何归属此模块/平台/legacy/status"。evidence 为结构化列表：

```yaml
evidence:
  - type: IMPORT              # IMPORT/ROUTER/DB_MODEL/MIGRATION/TEST_REFERENCE/DOCUMENT/RUNTIME_REGISTRATION/MANUAL_OWNER_DECISION/GIT_COMMIT/FILE_PATH/LINE
    source: app/main.py
    line: 126
    note: "leads router 注册于此"
```

- 至少支持：`FILE_PATH / LINE|RANGE / GIT_COMMIT / RUNTIME_REGISTRATION / IMPORT / ROUTER / DB_MODEL / MIGRATION / TEST_REFERENCE / DOCUMENT / MANUAL_OWNER_DECISION`。
- **禁止 `evidence: "看代码判断"`**。
- LLM 分类不构成证据（§32）；最终结论须基于 repository/runtime/import/DB/test/governance evidence。

---

## 15. Confidence Contract

```
HIGH      直接 runtime/data ownership 证据（router 注册 + 表 owner）
MEDIUM    强结构/import 证据但未达 runtime 直接（如 service 被 import 但调用链间接）
LOW       间接证据 / 部分归属
UNKNOWN   证据不足
```

Full Build 不得为减少 UNKNOWN 人为提高 confidence。`confidence` 与 `status` 独立（一个 LEGACY 文件可 HIGH confidence 确认其 LEGACY 性质）。

---

## 16. Unknown Contract

- `UNKNOWN = EXPLICIT + FINITE + TRACEABLE`，**不要求 = 0**。
- 每个 `owner_type=UNKNOWN` entry：`notes` 写理由 + 缺什么证据 + follow-up registry 链接（关联 U-001..U-007）。
- 验收门槛（§19）：`Implicit UNKNOWN = 0`（即不得有未标注 UNKNOWN 的无主条目）；`Explicit UNKNOWN = allowed`。

---

## 17. Boundary Conflict Handling

- 本轮仅 REGISTER/TRACE/LINK evidence 到对应 file entry。
- BC-02（M05/M06 共置）/ BC-06（compute 兼容入口）/ BC-07（integrations 多职责）/ BC-08（前端 redirects）只记录不整改。
- file entry 通过 `notes` 或 `compatibility`/`legacy` 字段链接 BC-ID。

### M05/M06 共置（BC-02）处理

物理共置文件可出现 `owner=M05, dependencies=[M06]`（或反向）。若确无法单 owner → `owner_type=UNKNOWN + notes=BC-02 evidence`，**优先于强行分配**。禁止 `M05_M06` 第八伪模块。

---

## 18. WINDOWS_ONLY 表达（BC-05 已解决）

`runtime_role=WINDOWS_ONLY`（非 owner）。`feedback`/`lead_notifications` → `owner=M02, runtime_role=WINDOWS_ONLY, status=ACTIVE`。禁止 `owner_type=WINDOWS`。

---

## 19. Coverage Denominator + Acceptance Counts

### 19.1 Coverage Denominator（实测）

```
Coverage = mapped_eligible_files / eligible_files
eligible_files = total_tracked(1327) − docs(379) − static_assets(27) − lock_files(2)
               = 957
```

- `docs/` 排除（DOCUMENT，无 module owner 必填）。
- 资产/lock 排除。
- Git-tracked generated 进分母但 owner=GENERATOR。

### 19.2 Acceptance Counts（可脚本验证，Full Build 不得改公式让结果 PASS）

```
Eligible Tracked Files        = 957 (baseline; Full Build 以实扫重算为准)
Mapped files                  = N (Full Build 产出)
Missing mappings              = 0
Duplicate path mappings       = 0
Duplicate stable IDs          = 0
Invalid owner IDs             = 0   (owner_id ∈ M01..M07 ∪ PLATFORM-* ∪ COMPAT-* ∪ null)
Unknown without reason        = 0   (explicit UNKNOWN 须带 notes + follow-up)
Missing evidence              = 0
Invalid module IDs            = 0
Invalid platform IDs          = 0
Schema errors                 = 0
Implicit UNKNOWN              = 0   (无主条目必须显式标 UNKNOWN)
```

### 19.3 当前 baseline 计数（§40 报告输入）

| 桶 | 数 | 说明 |
|---|---|---|
| Eligible Tracked Files | 957 | 1327 − 379 docs − 27 assets − 2 locks |
| Backend Production Files | 267 | app/ 159 + apps/ 100 + packages/ 8 |
| Frontend Files | 167 | frontend/src 非 asset 代码（总 201） |
| Service Files | 78 | app/services/ .py（修正此前 83 估值） |
| Test Files | 282 | tests/（修正此前 280 估值） |
| Migration Files | 96 | migrations/ 含 versions/env/ini/downgrades（revision 脚本 ~45） |
| Script Files | 79 | scripts/ |
| Governance/Config Files | 131 | docs/architecture 98 + 根配置 33（DOCUMENT/CONFIG，部分不进分母） |

---

## 20. Validation Strategy

Full Build 每批结束须产出 Review Gate（§22 batch），并跑 schema 校验脚本校验 §19.2 计数。校验由生成器家族扩展（`scripts/generate_code_index.py` 同族，Full Build 授权后方可新增），**本轮不新增校验脚本**（属生成器改动，未授权）。

### 代表性示例（本阶段允许 ≤10）

仅验证 schema 而非生产数据，3–10 个 representative entries 优先放文档示例，**不生成生产级 map**（§33）。

---

## 21. Tests as First-Class Citizen（U-007）

- 测试不简单标 `TEST` 完事；每条 `test_*` entry 须建立 `test file → owner module/platform → tested production area`。
- 允许 `owner_type=UNKNOWN`（须理由 + follow-up）。
- 当前实测 **282** test files（非 180 残差、非 280 估值——Full Build 须全扫，分母纳入 282）。

---

## 22. Batch Strategy + Review Gate

### 分批（deterministic / finite / repeatable / auditable）

```
Batch A: Platform + entrypoints + routers
Batch B: M01（客服 + 9100）
Batch C: M02（线索 + contact_extraction domain_shared）
Batch D: M03（智能体）
Batch E: M04（微信助手 + 19000 + WINDOWS_ONLY）
Batch F: M05/M06（共置，BC-02 处理）
Batch G: M07（算力 + apps/compute）
Batch H: tests（282，一等公民）
Batch I: scripts/config/migrations/compat/governance
Batch J: cross-reference / unknown closure / consistency
```

### 每批 Review Gate 产出

```
Files scanned / Files mapped
HIGH/MEDIUM/LOW/UNKNOWN counts
New BC / Resolved BC / New Unknown / Resolved Unknown
Unexpected files / Schema violations
```

不得全部完成才第一次 review。

---

## 23. Owner Decisions（OD-G1-*，集中待批）

### OD-G1-01：integrations.py 单文件多 status 表达

- **Question**：`integrations.py`（BC-07）内部 webhook=ACTIVE / legacy=COMPAT / sync-leads=LEGACY，文件级 Map 如何表达？
- **Option A（推荐）**：文件 entry `status=MIXED` + `evidence[]` 记录各 section status（line range + section status）。
- **Option B**：引入有限 `components[]` 局部结构。
- **Recommendation**：A（避免 AST/symbol database 复杂度）。
- **Impact**：schema 是否新增 `status=MIXED` 枚举值 + section-level evidence 块。
- **Blocking**：Blocking（schema 需此决策定稿）。

### OD-G1-02：Stable ID 重命名语义

- **Question**：文件移动/重命名后，ID 跟随逻辑制品还是 path 即新 ID？
- **Option A（推荐）**：ID 跟随逻辑制品（git rename detection 保留 ID + path_history[]；delete+add 降级为新 ID，标注 ceiling）。
- **Option B**：path 即身份，新 path = 新 ID。
- **Recommendation**：A（稳定性优先）。
- **Impact**：生成器须实现 rename detection + path_history。
- **Blocking**：Blocking（ID 规则核心）。

### OD-G1-03：tracked generated artifacts 分母处理

- **Question**：git-tracked 生成产物（当前仅 2 lock 文件已排除；未来若出现生成器输出）进分母否？
- **Option A（推荐）**：进分母，`artifact_type=GENERATED` + `owner=GENERATOR` + `derived_from` 源。
- **Option B**：排除（与 vendor 同）。
- **Recommendation**：A（保留可追溯性，但不强配业务模块）。
- **Impact**：分母定义。
- **Blocking**：Non-blocking（当前无此类文件，规则先行）。

### OD-G1-04：DOMAIN_SHARED 表达方式

- **Question**：`contact_extraction*` 用 `owner_type=DOMAIN_SHARED` 还是 `owner_type=MODULE + runtime_role=DOMAIN_SHARED`？
- **Option A（推荐）**：`owner_type=MODULE, owner_id=M02, runtime_role=DOMAIN_SHARED`（不新增 owner_type 值，不引入多 owner）。
- **Option B**：`owner_type=DOMAIN_SHARED`（新 owner_type，需 owner_id 规则）。
- **Recommendation**：A（最小复杂度，§2 已冻结单 owner）。
- **Impact**：schema owner_type 枚举（A 移除 DOMAIN_SHARED 作为 owner_type，仅保留 runtime_role 值）。
- **Blocking**：Blocking（schema 定稿）。

> 4 项 OD 均**不涉及代码改动**，仅 schema/契约定稿。已给出推荐；Owner 批准后 schema 升版 `PENDING_OWNER_APPROVAL → APPROVED`。

---

## 24. integrations.py / Frontend Redirects 特殊规则（依赖 OD-G1-01）

### integrations.py（BC-07）

依 OD-G1-01：若 A 通过 → 文件 `status=MIXED` + section evidence；不得强迫整文件 `status=LEGACY`。若无法在 Scope 安全决定 → `SCHEMA_DECISION_REQUIRED`（已转为 OD-G1-01，不擅自扩复杂度）。

### 前端 legacy redirects（BC-08）

- **route compatibility ≠ file lifecycle**：21 条 redirect（`routes.ts:18-41`）是路由兼容，**不等于对应 React 页面是 COMPAT**。
- schema 避免单一 `legacy: true` bool 承载所有概念。
- `routes.ts` 文件本身 `status=ACTIVE`（现役重定向逻辑）+ `compatibility.redirects[]` 列 21 条；被重定向的页面按各自生命周期独立判定。

---

## 25. Migration / Alembic Contract（§2/§5 双字段冻结）

文件级 migration entry 须支持：

```
repository_head_relation      指向 REPOSITORY_HEAD 迁移
production_revision_relation   指向 production/runtime revision
```

Code Map summary 须同时输出：

```
Repository Head          9000=0035 / 9100=0005
Production Revision      9000=0034(merchant.xiaogaoai.cn) / 9100=0003 / legacy callback=SQLite/0033
Gap                      9000: 0035(repo) vs 0034(prod), 0035 production_verified=NO
Verification Source      git ls-files / G0 执行链 / production-dual-instance-reality
```

冻结事实（§5）：

```
0035 production_verified = NO
0035 release_identity    = NO
Cutover                  = CUTOVER_NOT_READY
```

**禁止 `Latest Migration = Production Revision`**。

---

## 26. Schema Review（字段收敛）

当前候选字段分类：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | REQUIRED | 稳定 ID（§8） |
| path | REQUIRED | git canonical path |
| artifact_type | REQUIRED·ENUM | §7 |
| owner_type | REQUIRED·ENUM | §9（MODULE/PLATFORM/COMPATIBILITY/UNKNOWN） |
| owner_id | REQUIRED·条件 | owner_type 非 UNKNOWN 时必填 |
| module | DERIVED | = owner_id when MODULE（生成器计算，禁双写） |
| status | REQUIRED·ENUM | §10 |
| runtime_role | OPTIONAL·ENUM | §12 |
| confidence | REQUIRED·ENUM | §15 |
| entrypoints | OPTIONAL | 入口（HTTP/函数） |
| data_owned | OPTIONAL | 写/拥有的表 |
| data_read | OPTIONAL | 只读的表 |
| dependencies | OPTIONAL | §13 主动依赖（带 evidence type） |
| depended_by | DERIVED | 反向依赖（生成器计算） |
| external_dependencies | OPTIONAL | NewCar/GMP/Milvus/LLM/LAS/TOS/19000 |
| compatibility | OPTIONAL | COMPAT 层（comp_for/purpose/removal_prerequisite/redirects[]） |
| legacy | OPTIONAL | legacy_id/historical_purpose/evidence/risk |
| evidence | REQUIRED·LIST | §14，不得空、不得"看代码判断" |
| path_history | DERIVED·OPTIONAL | rename 历史（OD-G1-02 A 通过后） |
| notes | OPTIONAL·FREE TEXT | BC 链接 / UNKNOWN 理由 |

**权威 vs 派生**：`owner_type`+`owner_id` 权威；`module`/`depended_by`/`path_history` 派生（生成器计算）。禁人工双写派生字段。

---

## 27. Forbidden Actions

```
FULL_CODE_MAP_BUILD（未授权）
PRODUCTION/SOURCE/TEST/MIGRATION/ROUTE/API/RUNTIME 任何改动
FILE MOVE / DELETE / LEGACY CLEANUP / MODULE SPLIT-MERGE
CODE_INDEX 生成器改动（本轮 READ ONLY，不写回 CODE_INDEX.yaml）
refresh CODE_INDEX.yaml（属 Full Build mutation，BC-03 仅 measure/record）
load_code_map() 类 runtime 依赖
凭文件名猜依赖
LLM 分类作为唯一证据
本阶段创建 >10 个 file-map entries（生产级数据）
amend / squash / push / release
```

---

## 28. Full Build Entry Gate

Full Build（G1-M1..M6）启动须同时满足：

1. 本合同 Owner APPROVED；
2. OD-G1-01 ~ OD-G1-04 全部决议（4 项 Blocking/Non-blocking 收敛）；
3. schema 升版 `PENDING_OWNER_APPROVAL → APPROVED`；
4. Scan Baseline 重冻结（Full Build 窗口 git status CLEAN）；
5. 校验脚本设计完成（生成器家族扩展，Full Build 授权后方可实现）。

满足前 `FULL_CODE_MAP_BUILD = NOT AUTHORIZED`。

---

## 29. Changed Paths（本轮写入）

```
新增 docs/architecture/code-map/G1_FULL_CODE_REALITY_MAP_BUILD_CONTRACT.md   （本文，执行合同）
可能小调 docs/architecture/code-map/code_index.schema.yaml                    （仅 OD-G1-04 决议后收敛 owner_type 枚举；本轮若未决议则保持 DRAFT 不动）
```

（`G1_CODE_REALITY_MAP_EXPLORATION_1.md` / `module_chain_template.md` 为上轮产物，本轮不改）

---

## 30. 最终状态

```
Production Code Changed:  0
Business Test Code Changed: 0
CODE_INDEX.yaml Changed:  NO（READ ONLY）
Full File Map Generated:  NO
Refactoring:              NO
Deletion:                 NO
Push:                     NO

G1_FULL_CODE_REALITY_MAP_BUILD_SCOPE = PENDING_OWNER_APPROVAL
（4 项 OD-G1-* 待决议 → PENDING_OWNER_DECISIONS）
FULL_CODE_MAP_BUILD                  = NOT AUTHORIZED
```

**STOP。不得自行进入 FULL_CODE_MAP_BUILD。**
