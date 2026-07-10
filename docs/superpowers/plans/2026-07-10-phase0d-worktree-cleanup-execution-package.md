# Phase 0-D Worktree 清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 0-C 已通过审批后，安全清理已合并的 `phase0-context-sync` worktree 和本地分支。

**Architecture:** 本阶段只做 Git 工作区清理，不改代码、不提交业务改动、不触发服务。执行窗口必须先证明 `phase0-context-sync` 已合并到 `master` 且 worktree 干净，再使用 `git worktree remove` 和 `git branch -d` 做可回滚风险最低的清理。

**Tech Stack:** Git worktree、PowerShell。

---

## 阶段定位

阶段名称：`Phase 0-D worktree / 分支清理`

执行窗口：独立执行窗口 / 子代理。

审批窗口：当前窗口只接收结果并审批，不直接执行清理。

风险等级：`MEDIUM`

原因：本阶段不改业务代码、不改数据库、不触发真实请求，但会删除本地 worktree 目录和本地分支引用。

## 已知当前状态

正式仓库：

```text
路径：E:\work\project\auto_wechat
分支：master
状态：master...origin/master [ahead 21]
工作区：干净
```

待清理 worktree：

```text
路径：E:\work\project\auto_wechat\.worktrees\phase0-context-sync
分支：phase0-context-sync
提交：048b96a
状态：干净
合并状态：phase0-context-sync 已合并到 master
```

必须保留的无关 worktree：

```text
E:\work\project\auto_wechat\.worktrees\douyin-cs-training-feedback-rag
```

## 允许范围

本阶段允许：

1. 只读检查 `master`、`phase0-context-sync`、worktree 列表和合并关系。
2. 移除 `E:\work\project\auto_wechat\.worktrees\phase0-context-sync`。
3. 删除本地分支 `phase0-context-sync`。
4. 运行 `git worktree prune` 清理 Git worktree 元数据。
5. 回传清理结果。

本阶段禁止：

1. 禁止修改业务文件。
2. 禁止提交 commit。
3. 禁止 `git push`。
4. 禁止 `git pull`。
5. 禁止 `git reset --hard`。
6. 禁止删除或触碰 `douyin-cs-training-feedback-rag` worktree。
7. 禁止使用 `Remove-Item -Recurse`、`rmdir /s`、`del` 等文件系统递归删除命令清理 worktree。
8. 禁止启动 9000 / 9100 / 19000 / 前端服务。
9. 禁止触发抖音、巨量、微信、LLM、支付等真实请求。

## Task 1: 执行前安全核验

**Files:**
- Read: `E:\work\project\auto_wechat`
- Read: `E:\work\project\auto_wechat\.worktrees\phase0-context-sync`

- [ ] **Step 1: 确认正式仓库在 master 且干净**

```powershell
git status --short --branch
```

工作目录：`E:\work\project\auto_wechat`

预期：

```text
## master...origin/master [ahead 21]
```

不应有 `M`、`A`、`D`、`??` 等未提交文件。若存在任何未提交文件，停止并回传 `NEEDS_CONTEXT`。

- [ ] **Step 2: 确认 worktree 列表**

```powershell
git worktree list
```

工作目录：`E:\work\project\auto_wechat`

预期至少包含：

```text
E:/work/project/auto_wechat                                e04d4a4 [master]
E:/work/project/auto_wechat/.worktrees/phase0-context-sync 048b96a [phase0-context-sync]
```

允许存在其他 worktree，但本阶段只能清理 `phase0-context-sync`。

- [ ] **Step 3: 确认待清理 worktree 干净**

```powershell
git status --short --branch
```

工作目录：`E:\work\project\auto_wechat\.worktrees\phase0-context-sync`

预期：

```text
## phase0-context-sync
```

若存在任何未提交文件，停止并回传 `NEEDS_CONTEXT`。

- [ ] **Step 4: 确认分支已合并到 master**

```powershell
git merge-base --is-ancestor phase0-context-sync master; if ($LASTEXITCODE -eq 0) { "MERGED" } else { "NOT_MERGED" }
```

工作目录：`E:\work\project\auto_wechat`

预期：

```text
MERGED
```

若输出 `NOT_MERGED`，停止并回传 `BLOCKED`。

- [ ] **Step 5: 确认目标路径在预期目录内**

```powershell
(Resolve-Path -LiteralPath "E:\work\project\auto_wechat\.worktrees\phase0-context-sync").Path
```

预期：

```text
E:\work\project\auto_wechat\.worktrees\phase0-context-sync
```

如果解析结果不是上述完整路径，停止并回传 `BLOCKED`。

## Task 2: 清理 Phase 0 worktree

**Files:**
- Remove via Git: `E:\work\project\auto_wechat\.worktrees\phase0-context-sync`

- [ ] **Step 1: 从正式仓库根目录移除 worktree**

```powershell
git worktree remove "E:\work\project\auto_wechat\.worktrees\phase0-context-sync"
```

工作目录：`E:\work\project\auto_wechat`

预期：命令退出码为 0。

如果失败，不要使用文件系统删除命令兜底，停止并回传错误输出。

- [ ] **Step 2: 清理 Git worktree 元数据**

```powershell
git worktree prune
```

工作目录：`E:\work\project\auto_wechat`

预期：命令退出码为 0。

- [ ] **Step 3: 确认 worktree 已消失**

```powershell
git worktree list
```

预期不再包含：

```text
E:/work/project/auto_wechat/.worktrees/phase0-context-sync
```

仍应保留无关 worktree：

```text
E:/work/project/auto_wechat/.worktrees/douyin-cs-training-feedback-rag
```

## Task 3: 删除已合并本地分支

**Files:**
- Remove local branch ref: `phase0-context-sync`

- [ ] **Step 1: 删除本地分支**

```powershell
git branch -d phase0-context-sync
```

工作目录：`E:\work\project\auto_wechat`

预期：删除成功。

如果 `git branch -d` 拒绝删除，不要使用 `git branch -D`，停止并回传 `BLOCKED`。

- [ ] **Step 2: 确认本地分支不存在**

```powershell
git branch --list phase0-context-sync
```

预期：无输出。

## Task 4: 清理后核验

**Files:**
- No file changes.

- [ ] **Step 1: 确认正式仓库仍干净**

```powershell
git status --short --branch
```

预期：

```text
## master...origin/master [ahead 21]
```

不应出现未提交文件。

- [ ] **Step 2: 确认最近提交未变化**

```powershell
git log --oneline -3
```

预期仍为：

```text
e04d4a4 集成：合并Phase 0入口上下文同步
39e7e2f 文档：补充小高AI一期计划与阶段执行包
048b96a 文档：同步小高AI一期入口上下文
```

## Task 5: 回传结果

**Files:**
- No file changes.

- [ ] **Step 1: 按固定格式回传**

```text
阶段：Phase 0-D worktree / 分支清理
状态：DONE / NEEDS_CONTEXT / BLOCKED

正式仓库：
- 路径：E:\work\project\auto_wechat
- 分支：master
- 当前 HEAD：e04d4a4
- git status：

清理内容：
- 已移除 worktree：E:\work\project\auto_wechat\.worktrees\phase0-context-sync，是 / 否
- 已删除本地分支：phase0-context-sync，是 / 否
- 已保留无关 worktree：douyin-cs-training-feedback-rag，是 / 否

执行命令与结果：
- git merge-base --is-ancestor phase0-context-sync master：MERGED / NOT_MERGED
- git worktree remove ...：成功 / 失败摘要
- git worktree prune：成功 / 失败摘要
- git branch -d phase0-context-sync：成功 / 失败摘要
- git worktree list：清理后摘要
- git status --short --branch：清理后摘要

数据库迁移：无
业务逻辑改动：无
服务启动 / 真实请求：无
提交 commit：无
push：无
未触碰：input_writer、contact_searcher、微信 UI 自动化、前端交互、发送链路、douyin-cs-training-feedback-rag worktree

Implementer 自审结论：
- 是否只做清理：是 / 否
- 是否只清理 phase0-context-sync：是 / 否
- 是否使用 git worktree remove 而非文件系统递归删除：是 / 否
- 是否存在未提交文件：是 / 否

Spec Reviewer 结论：Approved / Changes Required
Code Quality Reviewer 结论：Approved / Changes Required

剩余风险：
- master 当前仍 ahead origin，未 push。
- Phase 0-D 只代表本地已清理 Phase 0 worktree / 分支，不代表远端同步。
```

## Spec Reviewer 清单

Spec Reviewer 只检查阶段目标与边界：

1. 只清理 `phase0-context-sync` worktree。
2. 只删除 `phase0-context-sync` 本地分支。
3. 清理前已证明分支合并到 `master`。
4. 未触碰 `douyin-cs-training-feedback-rag` worktree。
5. 未修改业务代码。
6. 未新增 commit。
7. 未 push。

结论格式：

```text
Spec Reviewer 结论：Approved / Changes Required
问题列表：
是否允许进入 Code Quality Reviewer：是 / 否
```

## Code Quality Reviewer 清单

Code Quality Reviewer 在 Spec Approved 后执行：

1. 使用 `git worktree remove` 清理 worktree。
2. 没有使用文件系统递归删除命令。
3. `git branch -d` 成功，未使用强制删除。
4. 清理后 `git status --short --branch` 干净。
5. 清理后最近提交未变化。
6. 清理后无关 worktree 仍存在。

结论格式：

```text
Code Quality Reviewer 结论：Approved / Changes Required
问题列表：
剩余风险：
```

## 本窗口审批清单

收到执行结果后，本窗口只做审批：

1. 回传信息是否完整。
2. 是否已清理 `phase0-context-sync` worktree。
3. 是否已删除 `phase0-context-sync` 本地分支。
4. 是否保留无关 worktree。
5. 是否没有新增 commit、push、业务改动、服务启动或真实请求。
6. 是否可以宣布 Phase 0 系列上下文同步收尾完成。
7. 是否可以进入 Phase 1 执行包制定。

审批结论只能是：

```text
通过：Phase 0 系列本地收尾完成，可制定 Phase 1 执行包。
有条件通过：清理目标完成，但需补充指定状态说明。
不通过：返回执行窗口修复后重新评审。
```
