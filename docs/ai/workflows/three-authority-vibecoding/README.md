# Three-Authority VibeCoding Governance

VibeCoding 三权分离治理工作流是一套 Optional Advanced Workflow（可选高级治理工作流）。

> **默认关闭，仅在符合启用条件时使用。**

它解决的核心问题是：方案制定、代码施工、独立验收和最终批准如果都发生在同一个 AI 上下文中，主观结论、遗漏和范围漂移容易互相强化，最终形成无人独立复核的闭环。

核心原则：

~~~text
审批窗口负责规则和裁决；
执行窗口负责施工；
测试窗口负责独立验收；
任何单一窗口不得自行完成开发、测试、批准闭环。
~~~

## 为什么不是默认流程

完整三权分离需要独立上下文、隔离工作树、正式交接和多轮证据核对。对于文案、注释或不改变运行语义的格式修改，这些成本通常高于收益。因此工作流按风险启用，不按文件数量启用：

- L0 默认使用单窗口和最小有效验证。
- L1 可使用双窗口或轻量三窗口。
- L2 推荐完整三权分离。
- L3 必须完整三权分离，并保留人工 Owner 的生产发布批准权。

详细判定见 [启用规则](activation-rules.md)。

## 三个角色

| 角色 | 负责 | 不负责 |
|---|---|---|
| 审批窗口 | 需求冻结、风险分级、范围裁决、执行包、候选代码审查、测试请求、返工与推送/发布裁决 | 不修改业务代码，不替执行窗口修复，不代替测试窗口宣布通过 |
| 执行窗口 | 预检、按执行包施工、自测、创建本地候选提交、按批准执行推送或发布 | 不改变需求，不扩大范围，不修改验收标准，不自行批准或独立验收 |
| 测试窗口 | 对指定候选提交做隔离、独立、可复现的验收并报告风险 | 不修改业务代码，不替执行窗口修复，不降低标准，不批准推送或发布 |

同一种模型、不同模型或人工参与均可承担窗口职责；治理边界依赖角色、上下文和证据隔离，不依赖模型厂商。

## 标准流程

~~~text
PLAN_APPROVED <Task-ID> <Plan-Revision> <Base-Commit>
  -> 执行窗口完成强制预检
  -> IMPLEMENTING <Task-ID> <Plan-Revision> <Base-Commit>
  -> 执行窗口施工和自测
  -> 创建本地候选提交
  -> CANDIDATE_READY <full-hash>
  -> 审批窗口审查同一完整哈希
  -> APPROVE_TEST <full-hash>
  -> TEST_REQUEST <full-hash>
  -> PASS / CONDITIONAL_PASS（发布任务同时绑定已测试 Artifact-Digest）
  -> APPROVE_PUSH <full-hash>
  -> PUSHED <full-hash>
  -> OWNER_APPROVAL_REQUIRED <full-hash>（L3 生产发布）
  -> APPROVE_RELEASE <full-hash>
  -> RELEASED <full-hash>

失败分支：
  FAIL -> R1 / R2 / REPLAN / REJECT_SCOPE
  TEST_BLOCKED -> TEST_REQUEST / REPLAN / REJECT_SCOPE
  SPEC_GAP -> REPLAN / REJECT_SCOPE
~~~

本地候选提交只是不可变审查对象，不代表允许推送、合并或发布。完整状态与合法转换见 [状态机](state-machine.md)。

## Git 哈希证据链

审批窗口和测试窗口必须绑定同一个 Candidate-Commit 完整哈希。候选回传后立即冻结；任何代码变化都必须创建新候选提交。

审批窗口还必须确认 `git merge-base --is-ancestor <Base-Commit> <Candidate-Commit>` 成功。目标分支偏离冻结基线且计划未定义集成策略时必须 REPLAN，不得把无关历史或隐式合并纳入候选。

发布任务由测试窗口或隔离 CI 从冻结候选构建一次不可变制品并验证摘要。APPROVE_RELEASE 必须绑定该摘要；L3 或项目策略要求 Owner 时，人工 Owner 也必须批准同一摘要。执行窗口只提升该制品，不得在批准后重新构建。

amend、rebase、squash、merge、cherry-pick、冲突修复或其他代码变化产生新哈希后：

1. 原审批与测试证据仍只对旧哈希成立；
2. 旧结论不得转移到新哈希；
3. 新哈希必须重新进入 CANDIDATE_READY、代码审查和独立测试。

详细字段和失效条件见 [交接契约](handoff-contract.md)。

## 工作树隔离

- 审批窗口使用只读审查环境或不承担业务代码写入的独立工作树。
- 执行窗口使用独立功能分支和可写工作树。
- 测试窗口从 Candidate-Commit 创建隔离工作树，测试开始时 HEAD 必须等于该哈希。
- 三个窗口不得共享同一个可写工作区，也不得同时在主分支施工。
- 测试生成缓存或构建产物后，必须复核受 Git 管理的文件未变化。

## 与人工 Owner 的关系

AI 审批窗口不是项目所有者。人工 Owner 可以冻结需求、否决风险接受和撤销批准；L3 的生产发布必须记录 Owner-Decision。OWNER_APPROVAL_REQUIRED 不是批准，未取得人工证据不得输出 APPROVE_RELEASE。

## 启用

1. 先按 [启用规则](activation-rules.md)记录风险等级和启用理由。
2. 普通开发者可只使用审批/协调入口，由其动态生成执行窗口和测试窗口指令。
3. 专业用户可维护三个永久隔离窗口。
4. 从 [审批窗口 Prompt](../../prompts/three-authority-vibecoding/approver-window.md)开始，并使用对应[交接模板](../../templates/three-authority-vibecoding/README.md)。
5. 项目安装时可使用 Install-AICodingRule.ps1 的 IncludeThreeAuthorityWorkflow 开关复制完整模块；安装不等于启用。

## 退出或降级

- 在 PLAN_APPROVED 前，审批窗口可重新分级并记录改用轻量流程的理由。
- 在 CANDIDATE_READY 后，不得通过降级绕过已冻结的验收标准；需要改变范围或验收矩阵时进入 REPLAN。
- L3 不得降级以绕过独立测试或人工 Owner 的生产发布批准。
- 任务结束后可关闭三个窗口；审批记录和测试证据按项目文档治理规则保留，不把过程流水账写入当前项目事实。

## 导航

- [启用规则](activation-rules.md)
- [唯一状态机](state-machine.md)
- [交接契约](handoff-contract.md)
- [完整示例](examples.md)
- [角色 Prompt](../../prompts/three-authority-vibecoding/README.md)
- [交接模板](../../templates/three-authority-vibecoding/README.md)
