# 抖音自动回复会话历史测试夹具基线文档闭环实施计划

> **执行窗口：** REQUIRED SUB-SKILL: 使用 `superpowers:executing-plans` 按任务逐项执行。本项目固定原地执行，不创建 worktree、不新建分支；步骤使用复选框跟踪。

**目标：** 原位纠正活动文档对 dry-run 历史基线失败的错误根因，记录已推送的测试夹具返修与独立测试事实，同时保留历史测试当时的真实失败数字。

**架构：** 文档候选只修改项目当前事实和测试计划两份活动文档。旧报告的数字不倒改；错误的“服务根因”替换为后续确认的“测试夹具缺失事件商户/租户归属”，并增加独立验收第 31 节。

**技术栈：** Markdown、Git、PowerShell 文本检查。

---

## 0. 执行合同

- Task-ID：`DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1-DOC-CLOSE-1`
- Plan-Revision：`R1`
- Specification-Commit：`d15155d0083ff3020c3bbb6e5d0b09c03c7d6189`
- Execution-Base：`d15155d0083ff3020c3bbb6e5d0b09c03c7d6189`
- 关联业务候选：`7011828ee73a2aa0bab88cb9c75c823a2336ec84`
- 关联独立测试：`R1-T1 / PASS`
- 风险等级：`LOW`
- 文档候选允许文件：
  - `docs/ai/05_PROJECT_CONTEXT.md`
  - `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

既有治理计划必须保持暂存且不进入文档候选：

- `docs/superpowers/plans/2026-07-28-douyin-conversation-history-test-fixture-baseline.md`
- `docs/superpowers/plans/2026-07-28-douyin-conversation-history-test-fixture-doc-close.md`

禁止修改：任何代码、测试、迁移、模型、配置、`POSTGRESQL_MIGRATION_NOTES.md`、历史规格/计划、webhook 签名头结论、外部 TODO。不得推送、部署、连接生产或真实发送。不得 amend、rebase、squash、merge、cherry-pick 或 force push。

## 1. 文件结构

| 文件 | 责任 | 本次操作 |
|---|---|---|
| `docs/ai/05_PROJECT_CONTEXT.md` | 当前有效项目事实 | 更新顶部摘要、原位纠正三处归因、增加当前闭环事实 |
| `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md` | 测试验收记录 | 原位纠正历史归因、保留历史数字、增加第 31 节 |
| 两份 `docs/superpowers/plans/2026-07-28-*.md` | 治理合同 | 继续暂存，不提交到文档候选 |

### Task 1：文档预检与历史事实定位

**Files：**
- Read: `docs/ai/05_PROJECT_CONTEXT.md:11-15,220-226`
- Read: `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md:680-748`

- [ ] **Step 1：确认文档基线、关联业务提交与工作区**

运行：

```powershell
git rev-parse HEAD
git merge-base --is-ancestor d15155d0083ff3020c3bbb6e5d0b09c03c7d6189 HEAD
git show -s --format='%H%n%P%n%s' 7011828ee73a2aa0bab88cb9c75c823a2336ec84
git status --short
git diff --check
```

预期：HEAD 精确等于 `d15155d0083ff3020c3bbb6e5d0b09c03c7d6189`；业务候选的父提交为 `dc6c9f4...`；工作区只保留两份治理计划暂存；无空白错误。

- [ ] **Step 2：定位每一处历史错误归因和数字**

运行：

```powershell
rg -n "根因在 `douyin_conversation_history_service.py`|test_active_binding_calls_9100_with_history_and_records_decision_log|149 passed \+ 1" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
```

预期：定位项目上下文中的 outbox、重启恢复、PostgreSQL/MVCC 三处，以及测试计划第 27、28、29、30 节的对应历史记录。记录这些行的原文；不得删除历史测试数字。

### Task 2：更新当前项目事实文档

**Files：**
- Modify: `docs/ai/05_PROJECT_CONTEXT.md:11-15`
- Modify: `docs/ai/05_PROJECT_CONTEXT.md:220-226`

- [ ] **Step 1：更新顶部时间和摘要**

将顶部时间更新为 `2026-07-28`。在同一摘要句内新增以下当前事实，不删除既有有效事实：

```markdown
会话历史测试夹具基线返修 R1-T1 已通过独立测试并快进集成至 `master@7011828ee73a2aa0bab88cb9c75c823a2336ec84`
```

不得写“已上线”“已部署”“生产验证通过”“全仓测试全绿”或“全部测试通过”。

- [ ] **Step 2：原位纠正三处历史服务根因**

在 outbox 持久化、outbox 重启恢复、outbox PostgreSQL/MVCC 三段中，把以下错误归因：

```markdown
（IndexError，conversation_history 为空，根因在 `douyin_conversation_history_service.py`，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域）
```

替换为以下事实口径，保留每段原有的历史测试数量：

```markdown
（IndexError，conversation_history 为空；后续确认根因是旧 dry-run 测试夹具未写事件 `merchant_id/tenant_id`，不是 `douyin_conversation_history_service.py` 业务服务缺陷，已由 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的 R1-T1 闭合；该历史报告当时仅能判为范围外基线，不在本任务 Allowed-Files，属 TENANT-ISOLATION-READ-1 子任务域）
```

不得把历史 `248 passed + 1` 或 `149 passed + 1` 改写为当时的全绿结果。

- [ ] **Step 3：补齐 JSONB 历史基线的后续闭合事实**

在 JSONB/ORM 段的 `149 passed + 1` 历史记录之后加入一句：

```markdown
其中 `test_active_binding_calls_9100_with_history_and_records_decision_log` 基线已由后续测试夹具返修 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的独立测试 R1-T1 闭合；该后续任务未倒改本段独立测试当时的 `149 passed + 1` 结果。
```

- [ ] **Step 4：增加当前闭环事实**

在自动回复当前事实区、JSONB/ORM 段之后新增一个普通项目符号，使用以下完整事实：

```markdown
- **会话历史测试夹具基线返修（DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1/R1）候选 `7011828ee73a2aa0bab88cb9c75c823a2336ec84`（父提交 `dc6c9f47311e8d61448ab247ac54d1356a188abf`）已通过独立测试 R1-T1 并快进集成至远端 `master@7011828ee73a2aa0bab88cb9c75c823a2336ec84`**（2026-07-28）：修复对象仅为 `tests/test_ai_auto_reply_dry_run.py` 的旧夹具；三条历史事件显式写入 `merchant-1/tenant-1`，夹具默认值仍为 `None`，未修改任何业务服务或商户过滤。此前 IndexError 的根因是 `merchant_id=NULL` 事件被正确隔离而历史为空，随后测试下标访问失败，不是会话历史服务缺陷。独立测试：目标历史用例 `1 passed`、NULL 商户历史隔离 `1 passed`、dry-run/会话历史/代理/商户隔离相邻回归 `138 passed, 0 failed`、outbox/send/dry-run 组合 `149 passed, 0 failed`、`py_compile` 通过；未连接 PostgreSQL/staging/production，未调用真实 LLM/9100/抖音/微信，未真实发送，未运行全仓测试。
```

### Task 3：更新测试验收计划

**Files：**
- Modify: `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md:704,714,728,746`
- Modify: `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`（末尾新增第 31 节）

- [ ] **Step 1：原位纠正第 27、28、29 节错误归因**

分别替换第 27、28、29 节中“根因在 `douyin_conversation_history_service.py`”的短语为：

```markdown
后续确认根因是旧 dry-run 测试夹具未写事件 `merchant_id/tenant_id`，不是 `douyin_conversation_history_service.py` 业务服务缺陷，已由 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 的 R1-T1 闭合
```

保留每一节的历史失败数字、Allowed-Files 和当时 Candidate 新增失败结论。

- [ ] **Step 2：保留第 30 节历史数字并增加闭合注记**

第 30 节必须继续写为：

```markdown
outbox/send/dry-run `149 passed + 1` 个范围外基线失败
```

紧接其后加入：

```markdown
该 `+1` 是当时同环境 Base/Candidate 对照的历史结果；后续 `7011828ee73a2aa0bab88cb9c75c823a2336ec84` 已确认其为测试夹具缺失事件商户/租户归属并通过 R1-T1 闭合，不倒改本节当时的测试数字。
```

- [ ] **Step 3：在末尾新增第 31 节**

追加以下小节，内容必须完整保留：

```markdown
## 31. 会话历史测试夹具基线返修（DY-CS-CONVERSATION-HISTORY-TEST-FIXTURE-BASELINE-1）

- Execution-Base：`dc6c9f47311e8d61448ab247ac54d1356a188abf`；最终候选 `7011828ee73a2aa0bab88cb9c75c823a2336ec84`，直接父提交为 Execution-Base，候选仅修改 `tests/test_ai_auto_reply_dry_run.py`。
- 独立测试 R1-T1：目标历史用例 `1 passed`；NULL 商户历史隔离合同 `1 passed`；dry-run、会话历史、代理和商户隔离相邻回归 `138 passed, 0 failed`；outbox、发送和 dry-run 组合 `149 passed, 0 failed`；`py_compile` 通过。
- 红灯根因：旧测试夹具的三条 `DouyinWebhookEvent` 未写 `merchant_id/tenant_id`；现有商户隔离正确排除 NULL 归属事件，导致历史为空，旧期望值对空数组下标访问而触发 `IndexError`。返修仅给夹具增加默认 `None` 的可选归属参数，并在该用例显式写入 `merchant-1/tenant-1`；未修改 `douyin_conversation_history_service.py`、会话查询或商户过滤。
- 安全边界：`merchant_id=NULL` 历史事件对普通商户继续不可见；FakeAiCsClient 仅作本地替身，无真实 LLM/9100/抖音/微信调用，无真实发送、生产连接或部署，未运行全仓测试。
- 候选已通过普通快进集成至远端 `master@7011828ee73a2aa0bab88cb9c75c823a2336ec84`。
```

### Task 4：文档静态验收、提交与冻结

**Files：**
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify: `docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md`

- [ ] **Step 1：检查事实、错误口径和禁止表述**

运行：

```powershell
rg -n "7011828ee73a2aa0bab88cb9c75c823a2336ec84" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
rg -n "根因在 `douyin_conversation_history_service.py`" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
rg -nE "已上线|已部署|生产验证通过|全仓测试全绿|全部测试通过" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
```

预期：完整候选哈希在两份文档均存在；第二条命令无输出；第三条命令无输出。

- [ ] **Step 2：检查历史数字、范围和差异**

运行：

```powershell
rg -n "149 passed \+ 1|138 passed, 0 failed|会话历史测试夹具基线返修" docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
git diff --check
git diff --name-status
```

预期：第 30 节仍含 `149 passed + 1`，两份文档均有当前闭环事实；差异只包含两份允许文档和暂存治理计划。

- [ ] **Step 3：提交唯一文档候选**

运行：

```powershell
git add -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
git diff --cached --check
git commit --only docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md -m "文档：闭合会话历史测试夹具基线"
```

预期：产生一个单父文档提交；两份治理计划继续暂存，未进入候选。

- [ ] **Step 4：冻结文档候选并回传**

运行：

```powershell
$candidate = git rev-parse HEAD
git merge-base --is-ancestor d15155d0083ff3020c3bbb6e5d0b09c03c7d6189 $candidate
git rev-list --parents d15155d0083ff3020c3bbb6e5d0b09c03c7d6189..$candidate
git diff --check d15155d0083ff3020c3bbb6e5d0b09c03c7d6189..$candidate
git diff --name-status d15155d0083ff3020c3bbb6e5d0b09c03c7d6189..$candidate
git status --short
```

预期：Base..Candidate 仅包含两份允许活动文档；提交链只有一个业务无关的单父文档提交；工作区只保留两份治理计划暂存。回传 `CANDIDATE_READY`，不得推送。

## 2. 独立文档测试与外部 TODO

独立文档测试窗口只读复验：HEAD、Base、单父线性、两文件范围、错误归因零命中、候选哈希、`149 passed + 1` 历史数字保留、R1-T1 数字、禁止表述、生产限制和治理计划隔离。PASS 后由审批窗口单独授权普通快进推送。

仓库文档推送完成后，外部 TODO 才可执行独立同步：先校验 `E:\work\2026-07-22 auto_wechat 今日 TODO.md` 的 SHA256 为 `D0B2F6971D8E4F541AAFE42C53B0AB242684D952AE4DB56C4F0F07D3528ACC7E`，不匹配立即停止；匹配后原位纠正第 121 行根因，并新增第 124 行前的本任务闭合事实。外部 TODO 不提交、不推送，不触碰仓库文件。
