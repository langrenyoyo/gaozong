# 交接契约

所有正式交接使用结构化信封。状态行不能替代字段、差异或测试证据。

## 最小字段

~~~text
Task-ID:
Plan-Revision:
Plan-Identifier:
Plan-Hash:
Base-Commit:
Candidate-Commit:
Role:
Allowed-Files:
Forbidden-Files:
Acceptance-Matrix:
Environment:
Residual-Risks:
~~~

Plan-Identifier 与 Plan-Hash 至少提供一项。Candidate-Commit 在 PLAN_DRAFT、PLAN_APPROVED 和 IMPLEMENTING 阶段可以为空；进入 CANDIDATE_READY、代码审查和测试后必须是完整 Git 提交哈希。

## 完整哈希

完整哈希是当前仓库对象格式下由 Git 返回的未缩写提交对象 ID，必须满足：

1. 可由 git rev-parse --verify <value>^{commit} 唯一解析；
2. 回传值与 Git 输出逐字符一致；
3. 测试工作树的 git rev-parse HEAD 与 Candidate-Commit 一致；
4. 不使用分支名、标签、HEAD、相对引用或自然语言代称。

SHA-1 仓库通常为 40 位十六进制，SHA-256 仓库通常为 64 位；协议不把完整哈希错误地固定为某一种对象格式。

## 不可变候选提交

Candidate-Commit 是审批和测试共同引用的不可变审查对象。执行窗口回传 CANDIDATE_READY 后：

- 不再改变该提交；
- 不在同一候选上追加未提交业务代码；
- 本地提交不授予推送、合并或发布权限；
- 审批窗口核对 Base-Commit 到 Candidate-Commit 的实际差异；
- 测试窗口只检出并测试该 Candidate-Commit。

## 基线与候选关系

进入 APPROVE_TEST 前必须同时证明：

1. Base-Commit 和 Candidate-Commit 都能解析为完整提交对象；
2. `git merge-base --is-ancestor <Base-Commit> <Candidate-Commit>` 返回成功；
3. 目标分支仍符合冻结计划中的基线或集成策略；
4. 审查范围是明确的 `<Base-Commit>..<Candidate-Commit>`；
5. `git log --oneline <Base-Commit>..<Candidate-Commit>` 和 `git rev-list --parents <Base-Commit>..<Candidate-Commit>` 已记录，合并提交和旁支历史都在计划内。

未被冻结集成策略覆盖的目标分支漂移、祖先关系不成立、未声明的合并/旁支历史或集成策略缺失时必须 REPLAN，不得进入测试。

## 结果失效

以下任一动作产生新提交对象后，旧审批、测试与 Owner 结论不得用于新哈希：

- amend、rebase、squash、merge、cherry-pick；
- 冲突修复；
- 源码、规则、配置、迁移或测试代码变化；
- 构建/发布过程改变被验收的受控内容；
- 测试时 Actual-HEAD 与 Candidate-Commit 不一致。

推送同一个提交对象本身不改变哈希；但合并提交、发布制品或部署内容必须能追溯到被批准的 Candidate-Commit。

## 推送、发布与 Owner 证据

- APPROVE_PUSH 的正式信封必须包含 Push-Remote、Push-Ref、Push-Mode=fast-forward-only 和 Expected-Remote-Hash。推送前后都核对远端实际哈希，并使用完整 Candidate-Commit 的显式 refspec。
- 本工作流禁止强制推送。远端偏离 Expected-Remote-Hash 或普通推送失败时停止并 REPLAN，不得改用 `--force`、`--force-with-lease` 或删除远端引用。
- 需要发布时，TEST_REQUEST 必须声明 Release-Artifact-Required、构建命令和制品位置。测试窗口或隔离 CI 从完整 Candidate-Commit 的干净工作树构建一次不可变制品，计算 Artifact-Digest，并在独立测试报告中记录 Artifact-Source-Commit、构建证据和制品测试结果。
- APPROVE_RELEASE 必须绑定 Task-ID、完整 Candidate-Commit、目标环境和同一制品版本/Artifact-Digest；L3 或项目策略要求 Owner 时，还必须绑定决定、Owner 身份和带时区时间戳。
- 发布动作只能提升或部署已测试、已批准的同一制品，不得重新构建。制品缺失、重建或摘要变化时，旧测试、发布批准和 Owner-Evidence 立即失效，必须对新制品重新测试和批准。
- 任一绑定字段变化都会使旧 Owner-Evidence 失效；批准推送不隐含批准发布，批准发布也不隐含推送。

## 必须 REPLAN

出现以下情况不能由执行或测试窗口自行解释：

- 目标、范围或验收标准需要变化；
- Base-Commit 漂移导致计划假设失效；
- 数据合同、权限边界或迁移策略与计划冲突；
- Allowed-Files 不足以完成目标；
- 测试发现的是需求矛盾而非实现缺陷；
- R2 无法在冻结计划内完成。

REPLAN 必须废止旧 Plan-Revision；已有候选不能跨计划复用。

## CONDITIONAL_PASS

只有同时满足下列条件才允许：

- 核心功能已验证；
- 权限、安全、隔离和数据一致性已验证；
- 未执行项仅受非核心环境限制；
- 存在充分、可审计的替代证据；
- 报告列出补测条件、责任人和残余风险。

它不得掩盖失败、哈希不一致、权限/安全缺测或数据库迁移未验证。审批窗口可以拒绝该结论并返回 R1、R2 或 REPLAN。

## 原因码

原因码用于补充状态，不创建新的平行状态。例如：

~~~text
TEST_BLOCKED <full-hash> reason=BLOCKED_ENVIRONMENT
REPLAN <Task-ID> <Plan-Revision> <Base-Commit> reason=BASE_DRIFT
REJECT_SCOPE <Task-ID> <Plan-Revision> <Base-Commit> reason=SCOPE_CONFLICT
~~~

原因码永远不能替代状态或被解释为 PASS。
