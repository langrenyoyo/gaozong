# Phase 0-C 正式仓库集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已经审批通过的 Phase 0 / Phase 0-B worktree 改动安全进入正式仓库 `master`，并把一期总控计划与阶段执行包纳入正式仓库。

**Architecture:** 本阶段只做 Git 集成、合同测试复验、状态回传，不做业务实现。先在执行 worktree 提交已审批改动，再回到正式仓库合并本地分支，并在正式仓库复跑合同测试确认入口上下文没有倒退。

**Tech Stack:** Git worktree、PowerShell、pytest、已有合同测试。

---

## 阶段定位

阶段名称：`Phase 0-C 正式仓库集成`

执行窗口：独立执行窗口 / 子代理。

审批窗口：当前窗口只接收结果并审批，不直接执行合并。

风险等级：`MEDIUM`

原因：本阶段不改业务代码、不改数据库、不触发真实请求，但会产生正式仓库提交并修改 `master` 历史前进状态。

## 已知当前状态

正式仓库：

```text
路径：E:\work\project\auto_wechat
分支：master
当前状态：master...origin/master [ahead 17]
未跟踪计划文档：
docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
docs/superpowers/plans/2026-07-10-phase0-context-sync-execution-package.md
docs/superpowers/plans/2026-07-10-phase0b-entry-context-cleanup-execution-package.md
docs/superpowers/plans/2026-07-10-phase0c-formal-repo-integration-execution-package.md
```

执行 worktree：

```text
路径：E:\work\project\auto_wechat\.worktrees\phase0-context-sync
分支：phase0-context-sync
待提交文件：
AGENTS.md
CLAUDE.md
docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md
docs/ai/05_PROJECT_CONTEXT.md
frontend/src/features/capabilities.ts
tests/test_xiaogao_phase0b_entry_context_contract.py
tests/test_xiaogao_phase1_context_contract.py
```

## 允许范围

本阶段允许：

1. 在 `phase0-context-sync` worktree 提交 Phase 0 / Phase 0-B 已审批改动。
2. 在正式仓库 `master` 提交计划文档。
3. 将 `phase0-context-sync` 合并到正式仓库 `master`。
4. 在正式仓库复跑合同测试和格式检查。
5. 回传提交哈希、测试结果、剩余风险和评审结论。

本阶段禁止：

1. 禁止修改业务实现代码。
2. 禁止新增数据库迁移。
3. 禁止启动 9000 / 9100 / 19000 / 前端服务。
4. 禁止触发抖音、巨量、微信、LLM、支付等真实请求。
5. 禁止清理前端旧文案；该事项留到 Phase 13。
6. 禁止自动 `git pull`、`git push`、`git reset --hard`。
7. 禁止删除 worktree 或分支；保留到本窗口审批通过后再决定是否清理。

## Task 1: 执行前状态核对

**Files:**
- Read: `E:\work\project\auto_wechat`
- Read: `E:\work\project\auto_wechat\.worktrees\phase0-context-sync`

- [ ] **Step 1: 核对正式仓库状态**

```powershell
git status --short --branch
```

工作目录：`E:\work\project\auto_wechat`

预期：

```text
## master...origin/master [ahead 17]
?? docs/superpowers/plans/2026-07-10-phase0-context-sync-execution-package.md
?? docs/superpowers/plans/2026-07-10-phase0b-entry-context-cleanup-execution-package.md
?? docs/superpowers/plans/2026-07-10-phase0c-formal-repo-integration-execution-package.md
?? docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
```

如果出现其他已修改或未跟踪文件，停止并回传 `NEEDS_CONTEXT`。

- [ ] **Step 2: 核对执行 worktree 状态**

```powershell
git status --short --branch
```

工作目录：`E:\work\project\auto_wechat\.worktrees\phase0-context-sync`

预期只包含：

```text
## phase0-context-sync
 M AGENTS.md
 M CLAUDE.md
 M docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md
 M docs/ai/05_PROJECT_CONTEXT.md
 M frontend/src/features/capabilities.ts
 A tests/test_xiaogao_phase0b_entry_context_contract.py
 A tests/test_xiaogao_phase1_context_contract.py
```

如果出现其他文件，停止并回传 `NEEDS_CONTEXT`。

## Task 2: worktree 提交 Phase 0 / Phase 0-B 改动

**Files:**
- Modify committed state only: `AGENTS.md`
- Modify committed state only: `CLAUDE.md`
- Modify committed state only: `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md`
- Modify committed state only: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify committed state only: `frontend/src/features/capabilities.ts`
- Modify committed state only: `tests/test_xiaogao_phase0b_entry_context_contract.py`
- Modify committed state only: `tests/test_xiaogao_phase1_context_contract.py`

- [ ] **Step 1: 复跑合同测试**

```powershell
pytest tests/test_xiaogao_phase1_context_contract.py tests/test_xiaogao_phase0b_entry_context_contract.py -v
```

工作目录：`E:\work\project\auto_wechat\.worktrees\phase0-context-sync`

预期：

```text
7 passed
```

失败时停止，不提交。

- [ ] **Step 2: 运行 diff 空白检查**

```powershell
git diff --check -- AGENTS.md CLAUDE.md "docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md" docs/ai/05_PROJECT_CONTEXT.md frontend/src/features/capabilities.ts tests/test_xiaogao_phase1_context_contract.py tests/test_xiaogao_phase0b_entry_context_contract.py
```

预期：无输出，退出码为 0。

- [ ] **Step 3: 暂存允许范围内文件**

```powershell
git add -- AGENTS.md CLAUDE.md "docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md" docs/ai/05_PROJECT_CONTEXT.md frontend/src/features/capabilities.ts tests/test_xiaogao_phase1_context_contract.py tests/test_xiaogao_phase0b_entry_context_contract.py
```

- [ ] **Step 4: 提交 worktree 改动**

```powershell
git commit -m "文档：同步小高AI一期入口上下文"
```

- [ ] **Step 5: 记录分支提交哈希**

```powershell
git rev-parse --short HEAD
```

回传时填写为 `phase0_commit`。

## Task 3: 正式仓库提交计划文档

**Files:**
- Add: `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`
- Add: `docs/superpowers/plans/2026-07-10-phase0-context-sync-execution-package.md`
- Add: `docs/superpowers/plans/2026-07-10-phase0b-entry-context-cleanup-execution-package.md`
- Add: `docs/superpowers/plans/2026-07-10-phase0c-formal-repo-integration-execution-package.md`

- [ ] **Step 1: 回到正式仓库并确认分支**

```powershell
git branch --show-current
```

工作目录：`E:\work\project\auto_wechat`

预期：

```text
master
```

- [ ] **Step 2: 暂存计划文档**

```powershell
git add -- docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md docs/superpowers/plans/2026-07-10-phase0-context-sync-execution-package.md docs/superpowers/plans/2026-07-10-phase0b-entry-context-cleanup-execution-package.md docs/superpowers/plans/2026-07-10-phase0c-formal-repo-integration-execution-package.md
```

- [ ] **Step 3: 检查暂存内容**

```powershell
git diff --cached --name-only
```

预期只包含上述 4 个计划文档。

- [ ] **Step 4: 检查计划文档空白问题**

```powershell
git diff --cached --check -- docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md docs/superpowers/plans/2026-07-10-phase0-context-sync-execution-package.md docs/superpowers/plans/2026-07-10-phase0b-entry-context-cleanup-execution-package.md docs/superpowers/plans/2026-07-10-phase0c-formal-repo-integration-execution-package.md
```

预期：无输出，退出码为 0。

- [ ] **Step 5: 提交计划文档**

```powershell
git commit -m "文档：补充小高AI一期计划与阶段执行包"
```

- [ ] **Step 6: 记录计划提交哈希**

```powershell
git rev-parse --short HEAD
```

回传时填写为 `plans_commit`。

## Task 4: 合并 Phase 0 / Phase 0-B 到 master

**Files:**
- Merge from branch: `phase0-context-sync`

- [ ] **Step 1: 在正式仓库执行本地合并**

```powershell
git merge --no-ff phase0-context-sync -m "集成：合并Phase 0入口上下文同步"
```

工作目录：`E:\work\project\auto_wechat`

预期：合并成功，无冲突。

如果出现冲突，执行：

```powershell
git merge --abort
```

然后停止并回传 `NEEDS_CONTEXT`，不要自行解决冲突。

- [ ] **Step 2: 记录合并提交哈希**

```powershell
git rev-parse --short HEAD
```

回传时填写为 `merge_commit`。

## Task 5: 正式仓库复验

**Files:**
- Test: `tests/test_xiaogao_phase1_context_contract.py`
- Test: `tests/test_xiaogao_phase0b_entry_context_contract.py`

- [ ] **Step 1: 在 master 复跑合同测试**

```powershell
pytest tests/test_xiaogao_phase1_context_contract.py tests/test_xiaogao_phase0b_entry_context_contract.py -v
```

工作目录：`E:\work\project\auto_wechat`

预期：

```text
7 passed
```

失败时停止并回传 `BLOCKED`。不要继续修复，不要扩大范围。

- [ ] **Step 2: 检查合并后工作区**

```powershell
git status --short --branch
```

预期：

```text
## master...origin/master [ahead N]
```

其中 `N` 比执行前增加 3；不应存在未提交文件。

- [ ] **Step 3: 检查最近提交**

```powershell
git log --oneline -3
```

预期能看到：

```text
集成：合并Phase 0入口上下文同步
文档：补充小高AI一期计划与阶段执行包
文档：同步小高AI一期入口上下文
```

## Task 6: 回传结果

**Files:**
- No file changes.

- [ ] **Step 1: 按固定格式回传**

```text
阶段：Phase 0-C 正式仓库集成
状态：DONE / NEEDS_CONTEXT / BLOCKED

正式仓库：
- 路径：E:\work\project\auto_wechat
- 分支：master
- phase0_commit：
- plans_commit：
- merge_commit：

执行内容：
- 已在 worktree 提交 Phase 0 / Phase 0-B 改动：是 / 否
- 已将计划文档提交到 master：是 / 否
- 已将 phase0-context-sync 合并到 master：是 / 否
- 是否删除 worktree / 分支：否

变更文件：
- AGENTS.md
- CLAUDE.md
- docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md
- docs/ai/05_PROJECT_CONTEXT.md
- frontend/src/features/capabilities.ts
- tests/test_xiaogao_phase0b_entry_context_contract.py
- tests/test_xiaogao_phase1_context_contract.py
- docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
- docs/superpowers/plans/2026-07-10-phase0-context-sync-execution-package.md
- docs/superpowers/plans/2026-07-10-phase0b-entry-context-cleanup-execution-package.md
- docs/superpowers/plans/2026-07-10-phase0c-formal-repo-integration-execution-package.md

数据库迁移：无
业务逻辑改动：无
服务启动 / 真实请求：无
未触碰：input_writer、contact_searcher、微信 UI 自动化、前端交互、发送链路

测试命令与结果：
- pytest tests/test_xiaogao_phase1_context_contract.py tests/test_xiaogao_phase0b_entry_context_contract.py -v：7 passed / 失败摘要
- git diff --check ...：通过 / 失败摘要
- git status --short --branch：干净 / 异常摘要

Implementer 自审结论：
- 是否只做集成：是 / 否
- 是否保留 worktree 和分支等待审批：是 / 否
- 是否存在未提交文件：是 / 否

Spec Reviewer 结论：Approved / Changes Required
Code Quality Reviewer 结论：Approved / Changes Required

剩余风险：
- master 当前仍 ahead origin，未 push。
- Phase 0-C 只代表正式仓库已集成上下文与合同测试，不代表自动发送业务代码已完成。
- worktree / 分支保留，等待审批窗口决定清理。
```

## Spec Reviewer 清单

Spec Reviewer 只检查阶段目标与需求一致性：

1. Phase 0 / Phase 0-B 已审批的 7 个文件进入 `master`。
2. 4 个计划文档进入 `master`。
3. 没有新增权限码。
4. 没有恢复旧“只建议不实发 / sent=false / auto_send=false”硬门禁入口口径。
5. 没有把前端旧文案清理提前到本阶段。
6. 没有新增数据库迁移或业务发送代码。
7. `master` 上合同测试为绿灯。

结论格式：

```text
Spec Reviewer 结论：Approved / Changes Required
问题列表：
是否允许进入 Code Quality Reviewer：是 / 否
```

## Code Quality Reviewer 清单

Code Quality Reviewer 在 Spec Approved 后执行：

1. 提交文件集合只包含执行包允许范围。
2. 合并提交来源为 `phase0-context-sync`。
3. `git status --short --branch` 无未提交文件。
4. 测试只运行合同测试，不启动服务。
5. 没有 `git pull`、`git push`、`git reset --hard`。
6. 没有删除 worktree 或分支。
7. commit message 使用中文。

结论格式：

```text
Code Quality Reviewer 结论：Approved / Changes Required
问题列表：
剩余风险：
```

## 本窗口审批清单

收到执行结果后，本窗口只做审批：

1. 回传信息是否完整。
2. `phase0_commit`、`plans_commit`、`merge_commit` 是否存在。
3. `master` 是否完成集成并保持工作区干净。
4. 合同测试是否在正式仓库通过。
5. 是否越界触碰业务代码、数据库迁移、服务启动或真实请求。
6. 是否可以宣布 Phase 0 / Phase 0-B 已进入正式仓库。
7. 是否需要单独制定 Phase 0-D worktree 清理执行包。

审批结论只能是：

```text
通过：Phase 0 / Phase 0-B 已进入正式仓库，可制定 Phase 1 执行包。
有条件通过：已进入正式仓库，但需补充指定状态说明或清理步骤。
不通过：返回执行窗口修复后重新评审。
```
