# 项目语言规范

请严格遵守以下规则：
1. 所有对话、解释、建议必须使用**简体中文**。
2. 代码注释必须使用中文。
3. 生成的 Commit Message 必须使用中文。
4. 严禁出现大段未翻译的英文技术名词。

# Ponytail, lazy senior dev mode



You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.

Before writing any code, stop at the first rung that holds:

1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the helper, util, or pattern that's already here, don't re-write it.
3. Does the standard library already do this? Use it.
4. Does a native platform feature cover it? Use it.
5. Does an already-installed dependency solve it? Use it.
6. Can this be one line? Make it one line.
7. Only then: write the minimum code that works.

The ladder runs after you understand the problem, not instead of it: read the task and the code it touches, trace the real flow end to end, then climb.

Bug fix = root cause, not symptom: a report names a symptom. Grep every caller of the function you touch and fix the shared function once — one guard there is a smaller diff than one per caller, and patching only the path the ticket names leaves a sibling caller still broken.

Rules:

- No abstractions that weren't explicitly requested.
- No new dependency if it can be avoided.
- No boilerplate nobody asked for.
- Deletion over addition. Boring over clever. Fewest files possible.
- Shortest working diff wins, but only once you understand the problem. The smallest change in the wrong place isn't lazy, it's a second bug.
- Question complex requests: "Do you actually need X, or does Y cover it?"
- Pick the edge-case-correct option when two stdlib approaches are the same size, lazy means less code, not the flimsier algorithm.
- Mark intentional simplifications with a comment. If the shortcut has a known ceiling (global lock, O(n²) scan, naive heuristic), the comment names the ceiling and the upgrade path.`ponytail:`

Not lazy about: understanding the problem (read it fully and trace the real flow before picking a rung, a small diff you don't understand is just laziness dressed up as efficiency), input validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs (the platform is never the spec ideal, a clock drifts, a sensor reads off), anything explicitly requested. Lazy code without its check is unfinished: non-trivial logic leaves ONE runnable check behind, the smallest thing that fails if the logic breaks (an assert-based demo/self-check or one small test file; no frameworks, no fixtures). Trivial one-liners need no test.

(Yes, this file also applies to agents working on the ponytail repo itself. Especially to them.)

# Project AI Entry Protocol

AGENTS.md 与 CLAUDE.md 是等效的项目入口文件（CLAUDE.md 面向 Claude Code，AGENTS.md 面向其他 AI Coding 工具）。

开始任何任务前，必须第一步阅读 CLAUDE.md；随后再按 Required Reading Order 阅读 docs/ai 规则文件。

当前涉及 PostgreSQL、RAG、Milvus、NewCar 鉴权或知识训练任务时，必须额外阅读：

```text
docs/ai/05_PROJECT_CONTEXT.md
docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md
```

不得跳过 CLAUDE.md 直接进入代码、测试、日志或业务实现。

你正在参与一个真实项目开发。

本项目遵循分层 AI 协作规范。

本文件与 `CLAUDE.md` 是等效入口，两者的硬约束必须保持语义一致；修改任一文件的约束时必须同步另一份。

------

# 可选三权分离治理

本项目已接入审批、执行、测试三权分离模块，但模块安装不等于任务启用。每项任务仍须按 L0～L3 逐项判定；启用条件和降级边界以 `docs/ai/workflows/three-authority-vibecoding/activation-rules.md` 为准。

该模块默认关闭，不改变 Required Reading。只有任务决定启用后，才按需阅读 `docs/ai/workflows/three-authority-vibecoding/README.md` 及对应角色 Prompt；不得把三份角色 Prompt 加入默认 Required Reading。

------

# AI 文档自治维护要求

`docs/ai` 活动文档（本文件、AGENTS.md、README.md、01~05 规则与上下文文件）由 AI 自主维护，开发者只审阅 Git diff 和高风险业务结论。

1. 每轮任务和每个大阶段完成后，必须执行文档影响检查：本轮改动使哪些文档结论过期？受影响的同轮更新，不受影响的明确说明"无文档影响"。
2. 更新前必须先探索事实：以运行证据、当前代码、迁移、配置、测试为准，禁止仅凭对话摘要或旧文档下结论。
3. 旧结论失效时必须**原位替换或删除**；禁止只追加"最新补充"，禁止保留旧错误结论并注明"以新内容为准"。
4. 只更新受影响的文件；日常事实更新写 `05_PROJECT_CONTEXT.md` 和专题文档，治理规则文件（01~04）有较高修改门槛。
5. 重复出现的问题和严重风险应升级为长期规则。
6. 历史过程有追溯价值时移入专题目录或 `docs/ai/archive/`，归档文件头部注明"非当前事实"。

详细规则以 `docs/ai/01_READING_RULES.md` 第 18 节"AI 文档自治维护规则"为准。

------

# Rule Priority

AGENTS.md 与 CLAUDE.md 同为入口规则和项目级约束汇总文件。

docs/ai 根目录保留入口规则与项目上下文；专题文档已按阶段和业务域归档到 docs/ai 子目录。

完整索引见：`docs/ai/README.md`。

优先级如下：

P-1 CLAUDE.md Entry Protocol
P0 Reading Rules
P1 Project Context
P2 Execution Rules
P3 Testing Rules
P4 Output Rules

发生冲突时：

CLAUDE.md Entry Protocol
>
Reading Rules
>
Project Context
>
Execution Rules
>
Testing Rules
>
Output Rules

------

# Current Hard Constraints（2026-07）

以下约束用于防止后续 VibeCoding / Codex 基于旧假设误改：

1. PostgreSQL 目标方案已确认：方案 A，一个 PostgreSQL 实例，两个 database。
   - `auto_wechat`：9000 主服务数据库，生产使用 `DATABASE_URL`。
   - `xg_douyin_ai_cs`：9100 RAG / AI 客服 metadata 数据库，生产使用 `RAG_DATABASE_URL`。
2. SQLite 只是开发和过渡数据库，不是最终生产数据库；新增代码不得继续扩散 SQLite 专属写法，不要基于旧 SQLite-only 假设修改 RAG、训练、反馈或迁移逻辑。PostgreSQL 下禁止 create_all，必须先 Alembic。
3. Milvus 是 embedding + 向量检索副本，不是 documents、chunks、feedback、training_run 或状态字段的 metadata 真源。
4. RAG `ask` 在 `RAG_VECTOR_BACKEND=milvus` 时，不能因为 SQLite active count 为 0 就跳过 Milvus 检索；`search-preview` 能命中 Milvus 时，`ask` 也必须执行 Milvus RAG。
5. 统一小高知识库训练和检索 scope：`tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=0`、`category_key=base`（tenant/merchant 为 env 可覆盖默认值）。
6. 前端不得持有 internal token，不得直连 9100 / Milvus，不得把前端传入的 tenant_id / merchant_id / douyin_account_id 当可信上下文。
7. 一期已放开旧的自动发送硬门禁；抖音私信、AI 自动回复和微信派单真实发送仍必须通过后端 gate 与运行保护，不得绕过违禁词替换、人工接管、限频、失败回写、幂等、紧急停止。
8. NewCar 真实鉴权本地联调必须显式设置：`NEWCAR_AUTH_ENABLED=true`、`NEWCAR_AUTH_MOCK_ENABLED=false`（代码默认值是 mock 开发态）。
9. 退出登录必须走 `POST /auth/logout`，由 9000 调用 NewCarProject `POST /api/external-auth/logout`，不能只清理前端本地 token。
10. **worktree 偏好声明（针对 superpowers skill 链）**：执行 `docs/superpowers/plans/*.md` 等 implementation plan 时，本项目声明固定偏好——**原地执行，不开 git worktree、不新建分支、不切目录**。`superpowers:using-git-worktrees` 检测到本指令即视为已声明偏好，跳过 Step 1 创建，直接在当前工作区执行；`superpowers:executing-plans` / `subagent-driven-development` 不得因"不在 worktree"而强制创建分支。此偏好覆盖 plan 文档开头 `REQUIRED SUB-SKILL` 段落隐含的隔离假设，但**不豁免**各 plan 自身的"允许范围 / 禁止事项"与发送安全、迁移、鉴权等 gate。如某高风险阶段确需隔离，必须由用户当轮显式批准后才可临时开 worktree。
11. **执行窗口协作纪律（2026-07-28 用户硬约束）**：以下四条对执行窗口、测试窗口及所有子 agent 等效生效，与三权分离或 plan 文档的允许范围叠加，不得因任何理由放宽：
    1. **禁止范围外发散**：未经用户当轮显式允许，不得对当前任务"允许范围"之外的文件、模块、能力做任何修改或"顺手实现"；遇到范围外问题只记录回传，不顺带改。
    2. **文档影响同步**：本轮改动使 `docs/` 下哪份文档结论过期的，必须在任务结束前按"AI 文档自治维护要求"受影响同轮更新；不得只改代码、留下过期文档结论。治理规则文件（01~04）的较高修改门槛不变。
    3. **不确认即停**：对需求、调用链、数据流、权限校验、影响面或方案中任一不确定的，必须先向用户/审批窗口确认后再动手，禁止凭假设推进；满足不了 Reading Completion Gate 时按其规则继续阅读而非编码。
    4. **任务展开先复述**：每个新需求或新任务（含 plan 内每个 Task）展开前，必须先复述该任务的允许范围、调用链、数据来源与去向、权限校验点、风险等级、最小修改方案与验收标准，经确认后再进入实现。
12. **Release Governance G0 硬化（2026-08-13 审批 APPROVED_WITH_4_CONSTRAINTS，R1 返工完成）**：
    1. **生产鉴权 fail-closed 已代码强制（P0-1）**：`APP_ENV=production` 时必须 `NEWCAR_AUTH_ENABLED=true` 且 `NEWCAR_AUTH_MOCK_ENABLED=false`，否则 `validate_production_auth_config()` 抛 RuntimeError（startup 拒启动 + `NewCarProjectAuthClient.from_env()` 请求路径双重防线），production 下 `build_mock_context()` 一律拒绝；GET /auth/me 绝不返回 HTTP200 mock。不做 import-time raise（避免阻断 alembic/维护/诊断脚本）。
    2. **生产部署只允许 canonical runner**（`scripts/release_9000_s10b.py`，P0-3）：命令必须显式 `-p xg_ai_system`（C2，命令行优先级高于 COMPOSE_PROJECT_NAME env）+ `up -d --no-deps --no-build auto-wechat-api`；禁止新建并行部署框架。
    3. **release identity env 与 runtime secrets env 分离（C4 + R1-1）**：release identity env（root-only release-exec.env，非敏感）除 `AUTO_WECHAT_API_IMAGE`/`XG_DOUYIN_AI_CS_IMAGE` 外必须含 `AUTO_WECHAT_API_EXPECTED_REVISION`/`XG_DOUYIN_AI_CS_EXPECTED_REVISION`（expected revision canonical source，缺失 → PREFLIGHT FAIL）；`.env.production.local` 只放业务运行配置，由 `--runtime-env-file` 消费，两者不得混写、不得含 expected revision 键；`.env.production.example` 不再提供 `:latest` 默认值（compose 回落 `:latest` 会被 preflight 拒绝）。
    4. **统一 preflight 覆盖 4 类 identity + R1 三方 gate（P0-4 + R1-1/2/3）**：Image（P1~P6 拒 missing/empty/:latest/相同共享 mutable/expected mismatch）、Project（P7 宿主 COMPOSE_PROJECT_NAME 污染）、Runtime（P8 存在性 + P9 APP_ENV/auth/DATABASE_URL）、DB compat（P10 target image 迁移 head ↔ release env expected revision，C3：不拿 master head 作 release target；CLI 仅作显式断言且必须等于 release env）、P11（R1-3 actual runtime env binding：runner 生成临时 `!override` env_file 绑定显式 runtime env，required:true、只写 path、mode 600、不落 secret，最终 service env 必须含显式 runtime 关键值）、P12（R1-2 DB actual revision：compose up 前只读 `SELECT version_num FROM alembic_version`，TARGET_IMAGE_HEAD == RELEASE_EXPECTED == ACTUAL_DB 三方一致，0028 image + DB0034 组合在 preflight 层拒绝，DB 连接用显式 --runtime-env-file 的 DATABASE_URL/RAG_DATABASE_URL，日志不落 secrets）。
    - 详见 `docs/architecture/remediation/G0_RELEASE_GOVERNANCE_P0_HARDENING_EXPLORATION_1.md` 与 `tests/test_auth_fail_closed.py` / `tests/test_release_g0_hardening.py`（含 T-R1-1~T-R1-10）。

## 小高AI系统一期确认范围（2026-07-10 确认，2026-07-18 勘误）

如 `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md` 与旧文档冲突，以该一期确认文档为准。

1. **AI剪辑已于 2026-07-31 按甲方书面授权恢复开发（原 2026-07-18 FROZEN_BY_CUSTOMER 已解除）**。已放弃原有 FFmpeg/9100规划/19000本地执行面三段架构，改为纯 LAS 云端方案（火山引擎 LAS `las_video_remix` 算子 `speech_auto` 模式）：9000 组装参数→LAS submit→后台轮询→存产物；前端新工作台 LasRemixWorkbench。旧冻结代码（worker/pipeline/stabilizer/9100规划/19000执行面/旧 AiVideoEditor/Task 11 测试包）已删除，数据模型 7 表+迁移保留复用。设计文档 `docs/superpowers/plans/2026-07-31-ai-edit-las-remix-redesign.md`。生产验证仍需另行审批；TOS/LAS 凭证从环境变量注入，前端不持有 LAS_API_KEY。
2. **一键过审已于 2026-07-13 被客户取消（CANCELLED_BY_CUSTOMER）**，不再是一期范围；不删除历史记录、不回退已落地代码和兼容字段。
3. `auto_wechat:ai_edit` 为 AI剪辑入口权限（2026-07-31 已恢复，承载 LAS 混剪工作台 + 素材库）；仍不新增 `auto_wechat:ai_video` 或 `auto_wechat:ad_review`。
4. 微信助手规则字段为 5 项：线索分配、短视频/直播留资管理表、每日线索销售反馈表、线索溯源表、销售单车成本表。
5. 留资口径为 `extracted_phone`、`extracted_wechat`、`all_extracted_contacts` 任一存在。
6. 旧的"只建议不实发""只粘贴不实发"硬门禁已废止；真实发送必须经联系人验证、前台焦点、违禁词替换、人工接管、限频、失败回写、幂等、紧急停止等 gate。
7. 商户管理、管理员账号、登录、功能授权仍归 NewCarProject / used-car。
8. 微信自动化底线继续有效：不读取微信数据库、不 DLL 注入、不微信协议逆向；Local Agent 默认只监听 `127.0.0.1:19000`。

------

# 项目定位与系统边界

项目名称：小高AI系统（auto_wechat）。当前系统组件、端口、环境与部署边界、数据库与阶段状态的完整当前事实见 `docs/ai/05_PROJECT_CONTEXT.md`，此处只保留边界红线：

- 组件：9000 主服务、9100 抖音AI客服（RAG/LLM）、19000 Local Agent（小高AI微信助手.exe，微信所在 Windows 电脑运行）、5173 React 前端（已并入 `auto_wechat/frontend`，**不存在独立的 `E:\work\project\react` 项目**）、外部 Milvus（仅向量副本）、外部 NewCarProject（商户/账号/权限/套餐权威系统）。
- douyinAPI（8081）定位为 demo / 参考实现 / 历史沉淀，不是生产运行依赖；webhook 事件已由 9000 直收。
- 系统之间通过 HTTP API 通信：禁止数据库直读、SQLite 文件共享、手工复制数据库；开发阶段禁止直连生产数据库，必须支持 Mock / dry_run / 本地测试库。
- 9000 是抖音企业号 / Agent / 分类绑定的权威数据源；`agent_config`、`allowed_category_keys` 只能由 9000 注入。
- "Local Agent"（19000 微信自动化进程）与"智能体 Agent"（9100 LLM 客服配置）是两个概念，禁止混用。
- Local Agent 名称为**小高AI微信助手**（exe：小高AI微信助手.exe），禁止使用"萌猫微信助手"。

------

# 微信自动化与发送安全底线

以下底线适用于所有微信自动化任务，除非用户明确批准，不得放宽：

1. 禁止微信数据库解密、DLL 注入、微信协议逆向；优先 UI Automation、视觉识别、OCR。
2. 不允许绕过 foreground_guard、search_focus guard、search_text_verified；未经联系人验证不得粘贴或发送。
3. partial_match、manual_review_required、hidden/minimized、foreground guard 失败时必须阻断并回写原因；ESC 不允许业务路径使用后继续；OCR/截图失败不能伪造成功。
4. 真实发送必须有联系人验证、前台焦点、违禁词替换、人工接管、限频、失败回写、幂等和紧急停止保护。
5. Local Agent 只操作客户本机微信，9000 不直接操作微信；检测链路保持只读，不写输入框、不发送。
6. 小高AI微信助手.exe 不应监听 0.0.0.0，默认只监听 127.0.0.1:19000。
7. React 本机 Agent 面板必须调用浏览器所在电脑的 127.0.0.1:19000，不走 VITE_API_BASE_URL。
8. 测试电脑/虚拟机默认无源码，不得要求运行 python 命令作为验收；不能操作开发主机微信作为测试电脑结果。
9. 禁止绕过 task_id 指定执行机制，新建任务后必须按 task_id 执行当前任务。
10. 诊断接口（search-debug 等）不得返回原始 UIA 对象，必须安全 JSON 序列化。

------

# Critical Reminders

每次开始新任务前，必须先阅读 docs/ai/05_PROJECT_CONTEXT.md 中的当前事实和强制注意事项。

必须遵守阶段最终目标与边界总控。每个阶段开始前复述目标、允许范围、禁止事项、验收标准；每个阶段结束后检查是否越界、是否提前实现后续阶段能力。不得把多个阶段混在同一轮完成，不得用"顺便完成了某功能"替代阶段验收。

1. 修改微信自动化相关代码前必读 `docs/ai/05_acceptance/P1_END_1_ACCEPTANCE.md`。
2. Bug 修复必须先做代码探索和根因确认，禁止仅凭现象就编写修复方案（详见 02_EXECUTION_RULES.md #17 BUG 修复前置探索原则）。
3. 高风险逻辑必须强制写诊断日志，包含 stage、输入摘要、failure_stage，禁止只写"失败了"（详见 02_EXECUTION_RULES.md #19 高风险代码日志原则）。
4. React 离线提示应使用："未检测到本机微信 Agent，请先在当前电脑启动 小高AI微信助手"。
5. React TS 配置约束（ignoreDeprecations=5.0 / composite / emitDeclarationOnly）禁止改动，详见 05_PROJECT_CONTEXT.md 第 10 节。
6. LAN 演示与 CORS 规则见 05_PROJECT_CONTEXT.md 第 4.3 节；`VITE_AUTO_WECHAT_API_BASE_URL` 不能用 127.0.0.1。

------

# Mandatory Workflow

任何任务必须遵循：

理解需求
↓
阅读项目
↓
建立上下文
↓
分析影响面
↓
输出方案
↓
获得确认（如果需要）
↓
实现
↓
测试
↓
总结
↓
文档影响检查（见"AI 文档自治维护要求"）

禁止跳过阅读阶段直接编码。

------

# Required Reading Order

开始任务后按顺序阅读：

1. CLAUDE.md（或本文件 AGENTS.md，两者等效）
2. docs/ai/01_READING_RULES.md
3. docs/ai/05_PROJECT_CONTEXT.md
4. docs/ai/02_EXECUTION_RULES.md
5. docs/ai/03_TESTING_RULES.md
6. docs/ai/04_OUTPUT_RULES.md

专题文档按需从 `docs/ai/README.md` 进入，不再默认遍历整个 `docs/ai` 目录。

## 阶段 1 Reality Map（AICoding Governance Wiring）

阶段 1 已冻结项目现实地图，VibeCoding 默认使用它们，不绕过重新搜索。治理文件负责导航和约束，Reality Map 负责事实——**不把 SYSTEM_MAP 内容复制进 AGENTS.md**。

### Reality Map Required Reading 顺序

完成上述基础阅读后，按任务涉及范围阅读：

1. `docs/architecture/SYSTEM_MAP.md` — 系统组成（7 组件 / 7 模块 / 公共底座 / 外部系统 / 数据域）
2. `docs/architecture/CODE_INDEX.yaml` — 机器索引唯一事实源（`.md` 是派生视图，禁止手工编辑）
3. `docs/architecture/RUNTIME_ENTRYPOINTS.md` — 9 类运行入口（区分定义存在与运行可达）
4. `docs/architecture/DEPENDENCY_MATRIX.md` — 7×7 模块依赖（Canonical Edge 事实源）
5. `docs/architecture/LEGACY_REGISTER.md` — Legacy 定性登记簿
6. 当前模块文档 / 当前任务 SPEC

### Source of Truth 层级

```
真实运行代码 / 数据库 / 部署配置
  ↓
已冻结 Reality Map（SYSTEM_MAP / CODE_INDEX / RUNTIME_ENTRYPOINTS / DEPENDENCY_MATRIX / LEGACY_REGISTER）
  ↓
模块验真基线
  ↓
任务 SPEC
  ↓
推测
```

**文档与代码冲突时，不允许偷偷按文档改代码"让两边一致"，先报告 drift。**

### Lifecycle 规则（引用 LEGACY_REGISTER 定义）

5 种生命周期：`ACTIVE` / `COMPAT` / `LEGACY` / `DEAD_CANDIDATE` / `UNKNOWN`（G1 维度，对应 code_index status；**G2-LEGACY-CONSOLIDATION-1 起 Legacy 登记簿升级为 G2 五分类**：`ACTIVE` / `COMPATIBILITY` / `LEGACY_KEEP` / `LEGACY_MIGRATE` / `DELETE_CANDIDATE`，以 `docs/architecture/LEGACY_REGISTER.md` 为准，G1 标签保留为追溯维度）

- `COMPAT ≠ 可删除`（兼容路径，GMP/外部已配置，不得顺手删）
- `LEGACY ≠ 可删除`（已被替代但仍有调用/env 控制，默认关）
- `DEAD_CANDIDATE ≠ DELETION_READY`（满足删除前置后才能进 DELETION_READY）
- `UNKNOWN → 禁止无证据删除或重构`（优先于推测，直到补充证据）
- `TECH_DEBT ≠ LEGACY`（是 `quality_flags` 不是 `lifecycle`，标了 TECH_DEBT 仍是 ACTIVE 正式运行能力）

状态机：`UNKNOWN → LEGACY/COMPAT/ACTIVE → DEAD_CANDIDATE → DELETION_READY → REMOVED`

`Lifecycle ≠ Deletion Eligibility`——两个独立维度。

### 修改前必须定位模块和依赖

修改代码前必须先确定 M01-M07 模块归属，并查询 `CODE_INDEX.yaml` 和 `DEPENDENCY_MATRIX.md`：

- 属于哪个模块？
- 数据 Owner 是谁？Consumer 是谁？
- 是否跨模块？是否碰到 COMPAT / LEGACY / DEAD_CANDIDATE？
- 碰到 COMPAT/LEGACY 时不得在普通业务任务中顺手删除或重构。

### 标准工作流

```
Reality Map → Module Verification → Behavior Baseline → Approved Change Scope → Implementation → Regression → Update Index/Map if topology changed
```

**未完成模块验真、未冻结行为基线前，不进行该模块的大规模结构重构。**

### 当前治理状态（2026-08-11）

```
PHASE 1   Reality Map              ✅ COMPLETE
PHASE 1B  Governance Wiring         ✅ COMPLETE
PHASE 2A  Current Reality          ✅ COMPLETE（7/7 模块验真）
PHASE 2B  Controlled E2E + Candidate ✅ COMPLETE（7/7 BASELINE_CANDIDATE + CROSS_MODULE_RISK_REGISTER 冻结）
PHASE 2C  External Gate            ⏸ OPEN（26 Gate Records：Staging 16 / Windows 6 / External 6）
PHASE 3A  Production Safety Stabilization ⬜ IN PROGRESS（P1 Consumer Migration 11/11 COMPLETE，进入 Technical Closure；检查点 `P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md`）
```

- 7 模块全部 `BASELINE_CANDIDATE`（非 `MODULE_BASELINE_APPROVED`，外部环境 Gate 未闭环）
- 4 个 HIGH 生产安全风险 + 5 个 STRUCTURAL 架构风险（分队列）
- Consumer 证据四级：`E2E_VERIFIED_IMPACTED` / `CODE_VERIFIED_EXPOSED` / `CALL_SITE_IDENTIFIED` / `NOT_VERIFIED`
- 阶段 3A 优先级：P1 Compute Idempotency → P2 M04 Claim/Lease → P3a M05 Reference → P3b M05 URL
- **P1 当前状态：CONSUMER_MIGRATION=COMPLETE + PG_VERIFICATION_COMPLETE(4/4) + F-1 RESOLVED + GLOBAL_AUDIT_VERIFIED + FC-F1 RESOLVED（Candidate B atomic UPDATE RETURNING，closure commit eb9f182）→ Final Concurrent Closure=VERIFIED（Final Closure-2 全量重跑全 PASS + 独立最终审批 APPROVED，`P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2.md` + `P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2_APPROVAL.md`）；TECHNICAL_CLOSURE=VERIFIED；COMPUTE-IDEMPOTENCY-001=CLOSED**
  - ★ Consumer Migration Complete ≠ Technical Closure Complete（≠ E2E_VERIFIED_FIXED）
  - Consumer 层工作完成，进入 Technical Closure（schema baseline + PG evidence + global audit + concurrency closure）
- **P1 关键产出**：
  - `docs/architecture/remediation/P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md` — 11/11 Consumer Migration 里程碑检查点（charge path matrix + identity contract + evidence level + Technical Closure blockers）
  - `docs/architecture/remediation/P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` — 技术方案（APPROVED）+ Charge Path Migration Register（11 条唯一事实源，RAG 按 query/ingest 拆分）
  - M07 Core（record_usage + DB migration 0030 + atomic ownership + IntegrityError replay/conflict）+ PG_CORE_GATE PASS
  - 11 consumer 迁移完成：M04 / M06 / M01 Auto Reply / M02 / Return Visit / Daily Report / Training / RAG Ingest / M05 / M01 Preview / RAG Query
  - PG Closure Gate 三态冻结：PASS / FAIL / WAIVED_WITH_ACCEPTED_RESIDUAL_RISK（WAIVED≠PASS，risk-accept 不得标 E2E_VERIFIED_FIXED）
  - PG Verification：M07 Core PG_VERIFIED / Training 0004 + RAG Ingest 事务边界 PG_VERIFIED_MIDPOINT / RAG Query 0005 = PG_RUNTIME_VERIFIED @5d8b6ba（原 BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT 已解除）/ Daily Report 0032 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（2026-08-10 独立审批 APPROVED）/ M05 0033 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（2026-08-11 独立审批 APPROVED；进程内 consumer 无 HTTP hop）/ Preview 0034 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED（2026-08-11 独立审批 APPROVED，`P1_PG_0034_PREVIEW_CONSUMER_APPROVAL.md`；9000→9100→9000 双 HTTP hop + 余额门禁真实路径 + P-A replay NO_DOUBLE_CHARGE + P-B distinct + P-R primary/retry_combined stage separation 全 PASS）—— **P1 ACTIVE CONSUMER PG VERIFICATION = COMPLETE（4/4：0032/0033/0034/RAG Query 0005）**
  - 7 个 Reliability Gap 均 OUT_OF_P1：DAILY_REPORT/TRAINING/RAG_INGEST_RUN/RAG_INGEST_REQUEST/M05_ANALYSIS_USAGE_REPORT/PREVIEW_REQUEST（含 Trusted Reply-Suggestion，C4 扩展覆盖）/RAG_QUERY_REQUEST
  - **Technical Closure Blockers**：A. ~~schema baseline~~ REMEDIATED / A′. bootstrap RESOLVED / B. ~~RAG Query 0005~~ PG_RUNTIME_VERIFIED / C. ~~Global Audit~~ VERIFIED / D. ~~Final PG Concurrent Closure~~ = VERIFIED（Final Closure-2 全量重跑全 PASS FC-0~FC-12+FC-R1/R2 + 独立最终审批 APPROVED，`P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2.md` + `P1_FINAL_POSTGRESQL_CONCURRENT_CLOSURE_2_APPROVAL.md`）→ **TECHNICAL_CLOSURE = VERIFIED**（P1 技术收口完成，COMPUTE-IDEMPOTENCY-001=CLOSED）
- 跨模块根因不重复统计：一个 Root Cause → 多个 impacted/exposed consumers

**关键产出文件**（修改前必读）：
- `docs/architecture/CROSS_MODULE_RISK_REGISTER.md` — 跨模块风险排序（冻结）
- `docs/architecture/SYSTEM_MAP.md` — 系统现实地图
- `docs/architecture/CODE_INDEX.yaml` — 机器代码索引（唯一事实源）
- `docs/modules/M01-M07/` — 7 模块验真文档（每模块 6 份）
- `docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml` — **G3 七模块关键链验证矩阵（唯一 SSOT，G3-SEVEN-MODULE-VERIFICATION-1）**；报告见 `G3_SEVEN_MODULE_VERIFICATION_REPORT.md`
- `docs/architecture/coupling/G4_COUPLING_REGISTRY.yaml` — **G4 跨模块耦合治理总账（唯一 SSOT，G4-CONTROLLED-DECOUPLING-1）**；报告见 `G4_CONTROLLED_DECOUPLING_REPORT.md`
- `docs/architecture/STAGING_E2E_READINESS.md` + `WINDOWS_E2E_READINESS.md` — 共享环境准备

### Governance Baseline（GC-GOVERNANCE-BASELINE-CLOSURE-1 闭合）

```text
GOVERNANCE_BASELINE = CLOSED_AND_VALIDATED / DEVELOPMENT_MODE = GOVERNED_FEATURE_DEVELOPMENT
```

- Manifest（治理入口 SSOT）：`docs/architecture/governance/GOVERNANCE_BASELINE.yaml`
- 开放问题索引（7 bucket）：`docs/architecture/governance/GOVERNANCE_BACKLOG.yaml`
- 工作流模型（L1/L2/L3）：`docs/architecture/governance/DEVELOPMENT_WORKFLOW.md`
- G1 Code Map：`docs/architecture/code-map/code_index.yaml` ｜ G2 Legacy：`docs/architecture/LEGACY_REGISTER.md`
- G3 Verification：`docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml` ｜ G4 Coupling：`docs/architecture/coupling/G4_COUPLING_REGISTRY.yaml`

**任务分级（默认 L1，治理存在本身不构成升级理由）**：
- **L1 普通任务**（单模块/无 schema/API/coupling/legacy/副作用）：最小流程——Owner确认 → 最小实现 → 相关测试；首轮 10~20 行短输出，不要求完整 Impact Contract。
- **L2 受控任务**（跨模块/Legacy/Coupling/CHAIN/ownership 变化）：简版 Impact Contract（LEGACY_IMPACT/COUPLING_IMPACT/VERIFICATION/MINIMAL_SCOPE/OUT_OF_SCOPE）。
- **L3 高风险任务**（DB/Auth/merchant 隔离/真实发送/扣费/outbox/生产数据删除/API breaking/发布机制）：完整 Impact Contract + 严格审批 + 独立测试验收；可读各 SSOT，但只读与任务有关的事实。
- 分级细则与典型场景（Case A~G）见 `DEVELOPMENT_WORKFLOW.md`。

**Governance Delta = 触发式（NO FACT CHANGE → NO GOVERNANCE DELTA）**：
- 代码/owner 事实变化 → G1 delta；Legacy 变化 → G2 delta；关键 CHAIN/verification 变化 → G3 delta；跨 owner 依赖变化 → G4 delta。
- 普通单模块修改（owner/CHAIN/Legacy/Coupling/Verification 均未变）：`GOVERNANCE_DELTA = NONE`，只运行相关 G3 测试。

**保留**：Owner 确认门（分析 → Owner确认 → 执行，禁止"用户提需求即自动改"）；三权分离按风险启用（L1 同窗口 / L2 视风险 / L3 默认分离）；治理阶段不可自动重开（变化走触发式 delta，不是阶段重做）。

------

# Reading Completion Gate

在完成以下问题之前禁止编码：

1. 当前需求属于哪个模块？
2. 当前调用链是什么？
3. 当前数据从哪里来？
4. 当前数据写到哪里去？
5. 当前权限在哪里校验？
6. 当前影响哪些模块？
7. 当前风险等级是什么？
8. 最小修改方案是什么？

如果无法回答：

继续阅读。

------

# High Risk Areas

以下区域属于高风险：

- Docker
- Docker Compose
- Nginx
- Environment Variables
- Database Migration
- Authentication
- RBAC
- File Storage
- Background Worker
- Deployment Scripts
- CI/CD

涉及以上区域：

必须先完成风险分析。

禁止直接修改。

------

# Coding Entry Condition

只有满足以下条件才能编码：

- 已完成项目阅读
- 已完成调用链分析
- 已完成影响面分析
- 已完成方案设计
- 已明确验证方案

否则继续阅读。

------

# Project Philosophy

AI 的首要职责不是写代码。

AI 的首要职责是理解项目。

理解错误：

后续全部错误。

理解正确：

编码只是执行。

因此：

Reading First.
Coding Later.

------

# 历史记录说明

2026-07-14 之前本文件包含的历史阶段详情与任务完成记录（P7/P8/P0-3/P0-4、P0-API-1 ~ P0-DEV-E1 等）已随文档基线重构移除，等价内容见 `docs/ai/archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md`。
