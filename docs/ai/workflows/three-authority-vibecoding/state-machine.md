# 唯一状态机

本文件是 Three-Authority VibeCoding Governance 的唯一状态定义。角色 Prompt、模板和示例不得创建平行状态或改变这里的含义。

## 主路径

~~~text
PLAN_DRAFT -> PLAN_APPROVED -> IMPLEMENTING -> CANDIDATE_READY
-> APPROVE_TEST -> TEST_REQUEST

PASS | CONDITIONAL_PASS
-> APPROVE_PUSH -> PUSHED
APPROVE_PUSH -> REPLAN
PUSHED -> OWNER_APPROVAL_REQUIRED（L3 生产发布）
-> APPROVE_RELEASE -> RELEASED
APPROVE_RELEASE -> TEST_REQUEST | REPLAN

FAIL -> R1 | R2 | REPLAN | REJECT_SCOPE
TEST_BLOCKED -> TEST_REQUEST | REPLAN | REJECT_SCOPE
SPEC_GAP -> REPLAN | REJECT_SCOPE
~~~

R1、R2、REPLAN 和 REJECT_SCOPE 是偏离主路径的裁决状态。

## 状态定义

| 状态 | 可输出角色 | 前置条件 | 必须携带 | 允许下一状态 |
|---|---|---|---|---|
| PLAN_DRAFT | 审批 | 需求已进入且开始探索 | Task-ID、Plan-Revision、Plan-Identifier/Hash、Base-Commit、风险等级、范围、验收矩阵 | PLAN_APPROVED、REPLAN、REJECT_SCOPE |
| PLAN_APPROVED | 审批 | 计划完整且基线/范围已核验 | 正式交接信封；Candidate-Commit 可空 | IMPLEMENTING、REPLAN、REJECT_SCOPE |
| IMPLEMENTING | 执行 | 执行预检通过 | Task-ID、Plan-Revision、Base-Commit、分支、允许/禁止文件 | CANDIDATE_READY、REPLAN、REJECT_SCOPE |
| CANDIDATE_READY | 执行 | 施工、自测、选择性暂存和本地提交完成 | 完整 Candidate-Commit、变更文件、测试证据、工作区状态、残余风险 | APPROVE_TEST、R1、R2、REPLAN、REJECT_SCOPE |
| APPROVE_TEST | 审批 | 已审查 CANDIDATE_READY 指定的同一哈希 | 完整 Candidate-Commit、代码审查证据、验收矩阵版本 | TEST_REQUEST |
| TEST_REQUEST | 审批 | APPROVE_TEST 已绑定候选哈希 | 完整测试交接信封；不得包含执行窗口主观结论；发布任务携带制品构建规则 | PASS、CONDITIONAL_PASS、FAIL、TEST_BLOCKED、SPEC_GAP |
| PASS | 测试 | 必测项和核心标准全部通过 | 完整 Candidate-Commit、实际 HEAD、测试证据、最终 Git 状态；发布任务携带已测试 Artifact-Digest | APPROVE_PUSH、OWNER_APPROVAL_REQUIRED、APPROVE_RELEASE |
| CONDITIONAL_PASS | 测试 | 核心/安全/权限/数据一致性通过，仅有可接受非核心限制且有替代证据；不得缺少发布制品证据 | 完整 Candidate-Commit、未执行项、替代证据、补测条件、残余风险；发布任务携带已测试 Artifact-Digest | APPROVE_PUSH、OWNER_APPROVAL_REQUIRED、APPROVE_RELEASE、R1、REPLAN |
| FAIL | 测试 | 任一核心、安全、权限、数据、回归或范围标准失败 | 完整 Candidate-Commit、可复现失败证据、影响范围 | R1、R2、REPLAN、REJECT_SCOPE |
| TEST_BLOCKED | 测试 | 环境/依赖不足且无充分替代证据，或哈希无法验证 | 请求的完整 Candidate-Commit；实际 HEAD/哈希无法解析时记为 UNKNOWN；原因码、证据、解阻条件 | TEST_REQUEST、REPLAN、REJECT_SCOPE |
| SPEC_GAP | 测试 | 验收标准冲突、缺失或无法判定 | 完整 Candidate-Commit、冲突条目、需要的裁决 | REPLAN、REJECT_SCOPE |
| R1 | 审批 | 有局部、明确、仍在原计划内的返工 | 旧 Candidate-Commit、问题、文件、预期、重测要求 | IMPLEMENTING |
| R2 | 审批 | 有较大但仍未改变冻结目标的返工 | 旧 Candidate-Commit、问题、影响、完整重测要求 | IMPLEMENTING、REPLAN |
| REPLAN | 审批 | 需求、范围、合同、基线或验收矩阵需要重写 | 原 Task-ID、原因、废止的 Plan-Revision/候选、待裁决项 | PLAN_DRAFT |
| REJECT_SCOPE | 审批 | 请求越权、不可接受或不属于当前任务 | Task-ID、拒绝原因、证据 | 终止；新范围需新 PLAN_DRAFT |
| APPROVE_PUSH | 审批 | 测试结论可接受且精确推送策略满足 | 完整 Candidate-Commit、Test-Decision、Push-Remote、Push-Ref、fast-forward-only、Expected-Remote-Hash | PUSHED、REPLAN |
| APPROVE_RELEASE | 审批 | 测试结论可接受；L3 Owner 证据绑定同一哈希/环境/已测试制品；发布前置满足 | 完整 Candidate-Commit、已测试 Artifact-Digest、目标环境、Owner-Evidence（如适用） | RELEASED、TEST_REQUEST、REPLAN |
| OWNER_APPROVAL_REQUIRED | 审批 | L3 生产发布或项目策略要求人工决定 | Task-ID、完整 Candidate-Commit、测试结论、环境、制品、风险、待 Owner 决策项 | APPROVE_RELEASE、R1、REPLAN、REJECT_SCOPE |
| PUSHED | 执行 | 收到匹配哈希的 APPROVE_PUSH 并完成精确 refspec 推送 | 完整 Candidate-Commit、远端、分支、远端实际哈希、推送结果 | OWNER_APPROVAL_REQUIRED、APPROVE_RELEASE、终止 |
| RELEASED | 执行或获授权发布者 | 收到匹配哈希/摘要的 APPROVE_RELEASE，并部署已测试制品且未重建 | 完整 Candidate-Commit、制品版本/摘要、环境、实际部署证据；每个目标的实际 Artifact-Digest 均与批准摘要一致且健康检查均通过 | 终止 |

批准动作失败时，执行窗口或获授权发布者只回传实际证据和原因码，不得自行输出 TEST_REQUEST、REPLAN 或 REJECT_SCOPE；下一状态由审批窗口裁决。APPROVE_RELEASE 仅在发布前、尚无部署副作用、Candidate-Commit 未变化且发生制品缺失、重建或摘要变化等失效时可回到 TEST_REQUEST。发布开始前，若部署策略、目标环境或其他发布前提变化或失效，执行窗口或获授权发布者只回传证据，由审批窗口输出 REPLAN <full-candidate-hash>；旧 APPROVE_RELEASE 和 Owner-Evidence 均失效且不得重放。发布已开始后发生失败、部分成功或结果未知时必须 REPLAN。

## 不代表通过的状态

- PLAN_APPROVED 只代表允许施工。
- CANDIDATE_READY 只代表本地候选已冻结。
- APPROVE_TEST 只代表代码审查允许进入独立测试。
- TEST_REQUEST 只代表测试包已发出。
- CONDITIONAL_PASS 不是无条件通过，审批窗口必须显式接受残余风险。
- OWNER_APPROVAL_REQUIRED 是等待人工裁决。
- BLOCKED_ENVIRONMENT 是原因码；TEST_BLOCKED 是工作流状态。二者都不等于 PASS。
- PUSHED 不代表已发布，APPROVE_RELEASE 也不代表发布已执行。

## 返工和哈希失效

R1 或 R2 返回执行窗口后必须创建新的候选提交。旧哈希不得再次获得测试请求。任何改变提交对象的操作都使旧审批和测试结论不能用于新哈希；新候选从 CANDIDATE_READY 重新进入流程。

## 状态输出格式

状态行必须位于完整交接信封内。Candidate-Commit 已存在时：

~~~text
<STATE> <full-candidate-hash>
REPLAN <full-candidate-hash>
REJECT_SCOPE <full-candidate-hash>
~~~

候选存在后的 REPLAN 和 REJECT_SCOPE 必须绑定完整候选哈希；Task-ID、Plan-Revision、Base-Commit 留在信封字段中。

Candidate-Commit 尚不存在时：

~~~text
<STATE> <Task-ID> <Plan-Revision> <Base-Commit>
~~~
