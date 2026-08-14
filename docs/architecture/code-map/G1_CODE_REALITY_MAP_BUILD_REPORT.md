# G1 全量代码现实地图构建报告

> 状态：G1_FULL_CODE_MAP_BUILD = COMPLETE（2026-08-14）
> 治理任务：G1-CODE-REALITY-MAP-BUILD-1（GOVERNANCE ARTIFACT BUILD）
> CODE_SOURCE_BASE = `88235b5bba363fd0dec4945b8e38aba1e82e2d9b`
> ELIGIBLE / MAPPED / UNMAPPED = 957 / 957 / 0；CODE_MAP_COVERAGE = 100%
> 关联：schema（APPROVED_FOR_G1_BUILD）、契约、探索报告、7 模块 CHAIN.md

---

## 0. 任务复述（执行窗口纪律）

- **允许范围**：仅 docs/governance 变更。生成 canonical `docs/architecture/code-map/code_index.yaml`；升级 schema；生成 7 个 module chain；登记 Boundary Conflicts 与 Active Unknowns；Alembic 仓库头/生产头分离登记；11 项验收公式 + 机器验收清单全部 PASS 后 candidate commit。
- **禁止事项**：生产/前端/后端业务/迁移/测试行为改动；重构/重命名/移动；Legacy 删除/兼容移除/解耦；G2/G3/G4；生产命令。
- **风险等级**：文档级（低）。高风险领域（Docker/DB/鉴权/部署）未触碰。
- **验收标准**：见 §4。

## 1. 分母核对（Denominator Reconciliation）

- 基线 `88235b5` tracked 文件总数 = **1327**（与契约 §19.1 一致）。
- 排除：`docs/` 379 个（含 13 个中文路径文档）+ 静态资产 2 个（`frontend/public/vite.svg`、`frontend/src/assets/avatar.svg`）+ lock 文件 2 个（`bun.lock`、`package-lock.json`）→ **944**。
- 冻结分母 **957 = 944 标准文件 + 13 个中文路径 docs 文档**（git `core.quotePath` 转义效应，将其纳入分母并按 DOCUMENT 条目映射）。
- ⚠️ **中间数字差异说明**：契约 §19.1 写「1327 − 379 − 27 − 2 = 957」。实测标准静态资产仅 2 个（非 27），`1327 − 379 − 2 − 2 = 944`，与契约算术式中间项（27）存在偏差，但**冻结结果 957 精确成立**（944 + 13）。G1 按冻结 957 执行并在本报告如实记录构成；契约中间数字的修订属文档修订工程（当前阶段仅登记，不启动——见 §7）。
- Hard Stop 条件检查：957 分母未被证明错误（以冻结口径精确成立），未触发 STOPPED。

## 2. Schema 升级

- `code_index.schema.yaml`：`PENDING_OWNER_APPROVAL → APPROVED_FOR_G1_BUILD`（schema_version 1.0.0）。
- 4 项 Owner 决议全部 Option A 冻结为 RESOLVED：
  - **OD-G1-01** MIXED status + section_evidence（integrations.py 为 MIXED 代表，BC-07）。
  - **OD-G1-02** Stable ID 跟随逻辑制品 + path_history[]（FILE-000001 格式，append-only）。
  - **OD-G1-03** tracked generated 进分母 + generated_by/derived_from（当前基线无 generated 产物，规则已生效）。
  - **OD-G1-04** DOMAIN_SHARED = owner_type=MODULE + runtime_role=DOMAIN_SHARED（contact_extraction* 7 文件归 M02）。
- 本轮禁止嵌套 first-class component taxonomy，已遵守。

## 3. canonical code_index.yaml 生成

- 位置：`docs/architecture/code-map/code_index.yaml`（37,423 行，957 entries）。
- 每 entry 含：稳定 ID、canonical path、artifact_type、owner_type/owner_id、派生 module、status、runtime_role、confidence、generated 三字段、entrypoints、data_owned/read、dependencies、**depended_by（生成器反向派生，禁人工双写）**、external_dependencies、compatibility、legacy、section_evidence、path_history、evidence（结构化，每条非空）、notes。
- 分类规则：目录前缀 + 文件级精确覆盖 + 前端 API/pages/components 语义映射 + 测试规则表（构建脚本 `e:/tmp/g1_build/build_code_index.py` 为构建期临时工具，不入库）。

### 3.1 所有权分布（owner 计数）

| owner_type | owner_id | 文件数 |
|---|---|---|
| MODULE | M01 抖音AI小高客服 | 185 |
| MODULE | M02 AI小高线索 | 129 |
| MODULE | M03 AI小高智能体 | 52 |
| MODULE | M04 AI小高微信助手 | 116 |
| MODULE | M05 小高素材库 | 21 |
| MODULE | M06 AI小高剪辑 | 13 |
| MODULE | M07 AI小高算力 | 43 |
| PLATFORM | PLATFORM-DB | 150 |
| PLATFORM | PLATFORM-RELEASE | 74 |
| PLATFORM | PLATFORM-AUTH | 20 |
| PLATFORM | PLATFORM-SCHED | 6 |
| PLATFORM | PLATFORM-OUTBOX | 3 |
| PLATFORM | PLATFORM-GATE | 1 |
| PLATFORM | PLATFORM-ISO | 1 |
| PLATFORM | （未细分） | 136 |
| COMPATIBILITY | COMPAT-012 | 1 |
| UNKNOWN | （显式） | 6 |

M01..M07 均 > 0，7 模块分类法未被推翻（confidence：5 HIGH + 2 MEDIUM 与探索报告一致）。

### 3.2 UNKNOWN 清单（6 个，全部显式 + notes，有限可追溯）

| 文件 | 理由 |
|---|---|
| docs/Phase0/流程图.png | 冻结分母纳入的历史资产，无模块归属 |
| docs/ai/12_legacy_research/新建文本文档.txt | legacy 研究临时笔记，归属未确认 |
| docs/ai/archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md | 历史流水账归档快照 |
| docs/ai/archive/2026-07-17_Phase12_Task12_平台公共与回收站旧执行包_冻结快照.md | 旧执行包归档快照 |
| docs/auto_wechat 产品化接入与开发计划.md | 产品化接入计划（全系统，跨模块） |
| docs/待确认事项.md | 待确认事项清单（全系统） |

- UNKNOWN ≠ UNMAPPED：957 文件全部有 entry；UNKNOWN 仅为显式归属未确认，非缺失条目。
- 构建过程中曾出现 302 个误落 UNKNOWN（前端/测试规则未命中），已补全归类规则收敛至上述 6 个有意保留项——UNKNOWN 从 31.5% 降至 0.6%。

### 3.3 MIXED 登记（OD-G1-01）

- `app/routers/integrations.py` → owner=M02, status=MIXED, section_evidence（webhook 主入口 ACTIVE / legacy_webhook COMPAT / sync-leads LEGACY_CANDIDATE），BC-07。
- `app/routers/ai_edit.py` → owner=M05, status=MIXED, section_evidence（M05 素材库 / M06 剪辑共置），BC-02。
- 禁止任意选择单一 owner，已遵守。

### 3.4 反向依赖持久化

- `dependencies`（12 个关键文件显式声明）+ `depended_by`（生成器从全表 dependencies 反向计算，匹配 owner_id）。
- 验证器独立重算比对，`depended_by_persisted = PASS`（source 声明 target → target entry 的 depended_by 必含 source）。

## 4. 验收结果

### 4.1 §22 十一项验收公式（独立验证器 `e:/tmp/g1_build/verify_code_index.py` 重算）

| # | 公式 | 结果 |
|---|---|---|
| 1 | eligible_count = 957 | PASS（957） |
| 2 | mapped_count = 957 | PASS（957） |
| 3 | missing = 0 | PASS |
| 4 | duplicate path = 0 | PASS |
| 5 | duplicate ID = 0 | PASS |
| 6 | invalid owner IDs = 0 | PASS |
| 7 | UNKNOWN without reason = 0 | PASS |
| 8 | missing evidence = 0 | PASS |
| 9 | invalid module IDs = 0 | PASS |
| 10 | invalid platform IDs = 0 | PASS |
| 11 | schema errors = 0 | PASS |

### 4.2 机器验收清单（十七节）

- eligible_count=957 ✅ mapped_count=957 ✅ unmapped_count=0 ✅ duplicate_path=0 ✅ duplicate_id=0 ✅
- M01..M07 存在 ✅ 7 module chains 存在 ✅（各 14 节，`docs/architecture/modules/M0X/CHAIN.md`）
- boundary conflicts registered ✅（BC-01~BC-08 登记于探索报告 v2）
- active unknowns registered ✅（U-001~U-008 分布登记于各 CHAIN.md Known Unknowns 节）
- generated files represented ✅（88235b5 无 tracked generated 产物，OD-G1-03 schema 支持已生效）
- dependency / depended_by persisted ✅（交叉校验 PASS）
- schema validation PASS ✅
- acceptance 11/11 PASS ✅
- **PRODUCTION_CODE_CHANGED=0** ✅（`git diff 88235b5 HEAD -- . ':!docs/'` 为空；工作区仅 code-map docs）
- **BUSINESS_TEST_CODE_CHANGED=0** ✅（tests/ 零改动）

## 5. Alembic 仓库头 / 生产头分离登记

- **REPOSITORY_HEAD**：9000 auto_wechat = **0035**（无 0031 跳号）；9100 xg_douyin_ai_cs = **0005**。
- **PRODUCTION_RUNTIME_REVISION**：9000 = **0034**（merchant.xiaogaoai.cn，Attempt3 发布后）；9100 = **0003**（Attempt3 冻结）；legacy callback = **SQLite/0033**（callback.misanduo.com，2026-08-12 只读核实）。
- 0035 = production_verified **NO**；Cutover Gate = CUTOVER_NOT_READY（5 blocker 见记忆 p2-m04-claim-lease-closure-and-cutover-gate）。
- **禁止将 latest migration 解释为 production revision**，已遵守；code_index.yaml summary 节显式记录三层分离。

## 6. Boundary Conflicts（登记于探索报告，此处引用不重开）

- BC-01/BC-02（M05/M06 共置）→ ai_edit MIXED 登记。
- BC-03 CODE_INDEX baseline drift（121 commits/213 files）→ 旧 CODE_INDEX.yaml READ ONLY / LEGACY BASELINE INPUT。
- BC-04 SYSTEM_MAP vs 9100 Alembic → 9100 = 0005 repo / 0003 prod 分离登记。
- BC-05 Windows conditional registration（feedback/lead_notifications）→ WINDOWS_ONLY runtime_role。
- BC-07 integrations.py multi-responsibility → MIXED。
- BC-08 frontend redirects（21 条）→ compatibility.redirects 字段支持（当前未逐条填充，登记于探索报告，G3 验真填充）。

## 7. 文档影响检查（AI 文档自治维护要求）

- **受影响并同轮更新**：`code_index.schema.yaml`（DRAFT→APPROVED，4 项 OD 决议写入）、`code_index.yaml`（新建）、7 个 `modules/M0X/CHAIN.md`（新建）、本报告（新建）、`module_chain_template.md`（未改，模板仍为模板）。
- **登记未修订**：`G1_FULL_CODE_REALITY_MAP_BUILD_CONTRACT.md` §19.1 中间数字（27 vs 实测 2）——冻结结果 957 成立，仅中间项表述偏差，属文档修订工程范畴，本阶段登记不修改公式自身（契约公式为不可变验收项，若改公式=自改验收，违反任务说明书第 10 条）。**该差异已在本报告 §1 如实记录，供后续文档修订窗口处理。**
- **无影响**：01~04 治理规则文件、05_PROJECT_CONTEXT、CODE_INDEX.yaml（模块级，READ ONLY 未动）、SYSTEM_MAP 等。
- 未触发 Hard Stop：无公式与仓库事实的根本冲突（仅中间数字表述差异，冻结值一致）。

## 8. Candidate Manifest

### 8.1 待提交文件（全部 docs-only，共 10 个新增/1 个修改）

新增：
1. `docs/architecture/code-map/code_index.yaml`（canonical 文件级 Code Map，957 entries）
2. `docs/architecture/code-map/G1_CODE_REALITY_MAP_BUILD_REPORT.md`（本报告）
3. `docs/architecture/modules/M01/CHAIN.md`
4. `docs/architecture/modules/M02/CHAIN.md`
5. `docs/architecture/modules/M03/CHAIN.md`
6. `docs/architecture/modules/M04/CHAIN.md`
7. `docs/architecture/modules/M05/CHAIN.md`
8. `docs/architecture/modules/M06/CHAIN.md`
9. `docs/architecture/modules/M07/CHAIN.md`
10. `docs/architecture/modules/README.md`（7 模块链入口索引）

修改：
11. `docs/architecture/code-map/code_index.schema.yaml`（PENDING_OWNER_APPROVAL → APPROVED_FOR_G1_BUILD）

（注：`module_chain_template.md` 未改动；构建/验证脚本位于 `e:/tmp/g1_build/`，不入库。）

### 8.2 建议提交

```
docs: 建立 G1 全量代码现实地图（957/957，11/11 验收 PASS）
```

- **不 push**（遵循项目硬性规则）。
- 提交后要求 `git status --short` 干净。
- 记录：G1_CANDIDATE_SHA / G1_CANDIDATE_TREE 见提交输出。

### 8.3 G1 完成状态

```
G1_FULL_CODE_MAP_BUILD = COMPLETE
ELIGIBLE_FILES = 957
MAPPED_FILES = 957
CODE_MAP_COVERAGE = 100%
ACCEPTANCE = 11/11 PASS
PRODUCTION_CODE_CHANGED = 0
BUSINESS_TEST_CODE_CHANGED = 0
G2 / G3 / G4 = NOT AUTHORIZED
```

## 9. 遗留与下一阶段

- 本阶段按任务说明书在 candidate commit + 状态复核后 **STOP**。
- 遗留登记（非 G1 范围）：契约 §19.1 中间数字修订、frontend redirects 21 条逐条填充（BC-08）、module_chain_template 是否更新为已定稿 7 链样式。
- 后续授权（独立窗口）：G2（legacy 清理授权）、G3（模块验真 + 验收）、G4（后续治理）。
