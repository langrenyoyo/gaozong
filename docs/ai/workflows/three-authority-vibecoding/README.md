# Three-Authority VibeCoding Governance

VibeCoding 三权分离治理工作流是一套 Optional Advanced Workflow（可选高级治理工作流）。

> **默认关闭，仅在符合启用条件时使用。**

它解决的核心问题是：需求决策、代码实施、独立验收和最终接受如果都由同一个权力主体完整掌握，主观结论、遗漏和范围漂移容易互相强化，最终形成无人独立复核的闭环。

核心原则：

~~~text
Decision Authority（决策权）控制意图、范围、规格、风险和最终接受；
Implementation Authority（实施权）控制批准边界内的系统变更；
Verification Authority（验收权）控制独立证据、质疑和通过/否决；
任何单一 AI 在中高风险任务中不得完整掌握三权。
~~~

窗口、Agent、模型和人工节点只是 Authority 的承载方式，不是 Authority 本身。一个窗口可以在低风险任务中承载多个不冲突的 Authority，也可以由多个窗口共同承载一种 Authority；独立性由权力边界、上下文、候选哈希和证据隔离保证，不由窗口数量或模型厂商保证。

Verification 与 Acceptance 必须分开：Verification 回答“实现是否满足批准合同”，Acceptance 回答“证据和残余风险是否允许正式接受”。`VERIFY_PASS` 不等于 `ACCEPTED`，`ACCEPTED` 也只有在适用 Gate 全部闭合后才能进入 `DONE`。

## 为什么不是默认流程

完整三权分离需要独立上下文、隔离工作树、正式交接和多轮证据核对。对于文案、注释或不改变运行语义的格式修改，这些成本通常高于收益。因此工作流按风险启用，不按文件数量启用：

- L0 默认使用单节点和最小有效验证。
- L1 可由两个节点承载三权，或使用轻量 Authority 分离。
- L2 推荐完整三权分离。
- L3 必须完整三权分离，并保留人工 Owner 的生产发布批准权。

详细判定见 [启用规则](activation-rules.md)。

## 三种权力主体

| Authority | 负责 | 不负责 |
|---|---|---|
| Decision Authority | DISCOVER、需求解释、Spec/Scope/Invariants/AC、L0-L3 风险裁定、Safety Gates、Plan 批准、Drift 裁决、最终 ACCEPT/DONE | 不承担其最终接受候选的业务代码实施；不得绕过 Verification；不得因实施困难降低 AC |
| Implementation Authority | 阅读 Approved Spec/Plan、在批准范围内修改和自测、形成不可变候选与 Implementation Evidence、报告 PLAN_DEVIATION/SPEC_DRIFT | 不改变需求、Scope、AC、API/DB/安全边界；不宣布 VERIFY PASS、ACCEPTED 或 DONE |
| Verification Authority | 独立读取 Spec/Plan/diff、逐条验证 AC、设计反例、检查回归/越界/兼容/安全、输出 VERIFY_PASS/FAIL/BLOCKED | 不修改业务代码或 Spec；不降低断言；不顺手修复；不单独最终 ACCEPT |

Implementation 内可以设置 Senior Engineering Tier，但它不是第四权。Human Production Approval 是额外 Safety Gate，也不是第四权。

模型选择只属于调度建议：Decision 优先使用强推理模型，Implementation 可按复杂度使用普通或 Senior Engineering Tier，Verification 优先使用不同模型家族。治理有效性不得依赖具体厂商或型号。

## 标准流程

~~~text
PLAN_APPROVED <Task-ID> <Plan-Revision> <Base-Commit>
  -> Implementation Authority 完成强制预检
  -> IMPLEMENTING <Task-ID> <Plan-Revision> <Base-Commit>
  -> Implementation Authority 施工和自测
  -> 创建本地候选提交
  -> CANDIDATE_READY <full-hash>
  -> Decision Authority 审查同一完整哈希并授权验证
  -> APPROVE_TEST <full-hash>
  -> TEST_REQUEST <full-hash>
  -> VERIFY_PASS / CONDITIONAL_PASS（兼容旧输出 PASS；发布任务同时绑定已测试 Artifact-Digest）
  -> ACCEPTED（Decision Authority 接受 Verification Evidence 与残余风险）
  -> APPROVE_PUSH <full-hash>
  -> PUSHED <full-hash>
  -> OWNER_APPROVAL_REQUIRED <full-hash>（L3 生产发布）
  -> APPROVE_RELEASE <full-hash>
  -> RELEASED <full-hash>
  -> DONE <full-hash>

失败分支：
  VERIFY_FAIL / FAIL -> R1 / R2 / REPLAN / REJECT_SCOPE
  TEST_BLOCKED -> TEST_REQUEST / REPLAN / REJECT_SCOPE
  SPEC_GAP -> REPLAN / REJECT_SCOPE
  APPROVE_PUSH -> REPLAN
  APPROVE_RELEASE -> TEST_REQUEST
  APPROVE_RELEASE -> REPLAN
~~~

本地候选提交只是不可变审查对象，不代表允许推送、合并或发布。完整状态与合法转换见 [状态机](state-machine.md)。

批准动作失败时，Implementation Authority 或获授权发布者只回传事实、实际证据和原因码，TEST_REQUEST、REPLAN、REJECT_SCOPE 由 Decision Authority 裁决。推送后只有精确 Push-Ref 的远端实际哈希等于 Candidate-Commit 才可输出 PUSHED；REMOTE_DRIFT 或 PUSH_OUTCOME_UNKNOWN 均由 Decision Authority 转入 REPLAN，旧 APPROVE_PUSH 不得重放。

发布前且没有部署副作用、Candidate-Commit 未变化时，制品缺失、需要重建或摘要变化使用 ARTIFACT_INVALIDATED，由 Decision Authority 重新输出 TEST_REQUEST，旧验收、批准和 Owner 证据失效。发布开始前，若部署策略、目标环境或其他发布前提变化或失效，Implementation Authority 或获授权发布者只回传证据，由 Decision Authority 输出 `REPLAN <full-candidate-hash>`；旧 APPROVE_RELEASE 和 Owner-Evidence 均失效且不得重放。发布已经开始后的已知失败或部分成功使用 RELEASE_PARTIAL（包括 0 个目标成功），结果未知使用 RELEASE_OUTCOME_UNKNOWN，由 Decision Authority 转入 REPLAN；旧批准和 Owner 证据不得重放。只有全部目标的实际 Artifact-Digest 均逐一等于批准摘要，且健康检查均通过，才可输出 RELEASED。

## Git 哈希证据链

Decision Authority 和 Verification Authority 必须绑定同一个 Candidate-Commit 完整哈希。候选回传后立即冻结；任何代码变化都必须创建新候选提交。

Decision Authority 还必须确认 `git merge-base --is-ancestor <Base-Commit> <Candidate-Commit>` 成功。目标分支偏离冻结基线且计划未定义集成策略时必须 REPLAN，不得把无关历史或隐式合并纳入候选。

发布任务由 Verification Authority 或隔离 CI 从冻结候选构建一次不可变制品并验证摘要。APPROVE_RELEASE 必须绑定该摘要；L3 或项目策略要求 Owner 时，人工 Owner 也必须批准同一摘要。Implementation Authority 只提升该制品，不得在批准后重新构建。

amend、rebase、squash、merge、cherry-pick、冲突修复或其他代码变化产生新哈希后：

1. 原审批与测试证据仍只对旧哈希成立；
2. 旧结论不得转移到新哈希；
3. 新哈希必须重新进入 CANDIDATE_READY、代码审查和独立测试。

详细字段和失效条件见 [交接契约](handoff-contract.md)。

## 承载方式与隔离

- Decision Authority 使用只读审查环境或不承担业务代码写入的上下文。
- Implementation Authority 使用获批准的可写工作区；是否使用 worktree 服从项目级偏好。
- Verification Authority 从 Candidate-Commit 建立独立验证上下文，测试开始时 HEAD 必须等于该哈希。
- 中高风险任务中，承担某个 Candidate 实施的承载主体不得对同一 Candidate 输出 `ACCEPTED` 或 `DONE`，也不得承担该 Candidate 的独立 Verification。
- 测试生成缓存或构建产物后，必须复核受 Git 管理的文件未变化。

## 与人工 Owner 的关系

Decision Authority 不等于项目所有者。人工 Owner 可以冻结需求、否决风险接受和撤销批准；L3 的生产发布必须记录 Owner-Decision。OWNER_APPROVAL_REQUIRED 不是批准，未取得人工证据不得输出 APPROVE_RELEASE。

## 启用

1. 先按 [启用规则](activation-rules.md)记录风险等级和启用理由。
2. 普通开发者可只操作 Decision Authority 入口，由其生成 Implementation 和 Verification 指令。
3. 一个任务可以用两个、三个或更多节点承载三权；节点数量不改变 Authority 数量。
4. 从 [Decision Authority Prompt](../../prompts/three-authority-vibecoding/decision-authority.md)开始，并使用对应[交接模板](../../templates/three-authority-vibecoding/README.md)。
5. 项目安装时可使用 Install-AICodingRule.ps1 的 IncludeThreeAuthorityWorkflow 开关复制完整模块；安装不等于启用。

## 退出或降级

- 在 PLAN_APPROVED 前，Decision Authority 可重新分级并记录改用轻量流程的理由。
- 在 CANDIDATE_READY 后，不得通过降级绕过已冻结的验收标准；需要改变范围或验收矩阵时进入 REPLAN。
- L3 不得降级以绕过独立测试或人工 Owner 的生产发布批准。
- 任务进入 DONE 后可释放 Authority 承载上下文；决策、实施和验收证据按项目文档治理规则保留，不把过程流水账写入当前项目事实。

## 导航

- [启用规则](activation-rules.md)
- [唯一状态机](state-machine.md)
- [交接契约](handoff-contract.md)
- [完整示例](examples.md)
- [角色 Prompt](../../prompts/three-authority-vibecoding/README.md)
- [交接模板](../../templates/three-authority-vibecoding/README.md)
