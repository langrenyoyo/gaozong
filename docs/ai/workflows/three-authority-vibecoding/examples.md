# 示例

示例哈希仅用于展示字段形态，均代表完整提交对象 ID。

## 1. L0 文档任务不启用完整流程

任务：修正文档中的拼写并检查链接，不改变规则语义。

裁决：

~~~text
Risk-Level: L0
Workflow-Mode: single
Reason: 纯文档、可直接 diff、可回滚
Verification: git diff --check + 相对链接检查
~~~

不创建三个窗口。执行者仍检查差异和工作区，但不为低风险改动承担完整交接成本。

## 2. L1 普通功能使用轻量流程

任务：给非核心 CRUD 页面增加一个可选筛选项。

- 审批/协调上下文冻结范围和验收矩阵。
- 执行上下文施工、自测并创建候选提交。
- 第二个上下文按缩减矩阵独立验证筛选、清空和回归。
- 不启用独立发布窗口；推送仍需要项目授权。

~~~text
PLAN_APPROVED TASK-102 P1 1111111111111111111111111111111111111111
IMPLEMENTING TASK-102 P1 1111111111111111111111111111111111111111
CANDIDATE_READY aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
APPROVE_TEST aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
TEST_REQUEST aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
PASS aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
APPROVE_PUSH aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
~~~

## 3. L3 数据库与鉴权任务使用完整流程

任务：增加租户级权限字段并迁移历史数据。

审批窗口将其判定为 L3，执行包冻结迁移、回滚、历史数据、越权测试和隔离测试。执行窗口在独立分支创建候选；测试窗口从该候选建立隔离工作树，验证升级/回滚、不同角色、跨租户拒绝和数据一致性。

~~~text
PLAN_APPROVED TASK-201 P1 2222222222222222222222222222222222222222
IMPLEMENTING TASK-201 P1 2222222222222222222222222222222222222222
CANDIDATE_READY bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
APPROVE_TEST bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
TEST_REQUEST bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
Artifact-Source-Commit: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
Artifact-Digest: sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
PASS bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
Push-Remote: origin
Push-Ref: refs/heads/main
Push-Mode: fast-forward-only
Expected-Remote-Hash: 2222222222222222222222222222222222222222
APPROVE_PUSH bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
PUSHED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
OWNER_APPROVAL_REQUIRED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
APPROVE_RELEASE bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
RELEASED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
~~~

APPROVE_RELEASE 必须引用绑定 TASK-201、候选 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb、生产环境、摘要 sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff、Owner 身份和时间戳的人工 Owner-Decision；审批窗口不能自行替代。执行窗口只提升这个已测试制品，不得重新构建。

## 4. R1 后创建新候选并重新测试

首个候选：

~~~text
CANDIDATE_READY cccccccccccccccccccccccccccccccccccccccc
R1 cccccccccccccccccccccccccccccccccccccccc
~~~

返工修复了一个边界条件。执行窗口不得改写旧提交并沿用旧哈希，而要创建新候选：

~~~text
IMPLEMENTING TASK-103 P1 3333333333333333333333333333333333333333
CANDIDATE_READY dddddddddddddddddddddddddddddddddddddddd
APPROVE_TEST dddddddddddddddddddddddddddddddddddddddd
TEST_REQUEST dddddddddddddddddddddddddddddddddddddddd
PASS dddddddddddddddddddddddddddddddddddddddd
~~~

对 cccccccccccccccccccccccccccccccccccccccc 的任何旧结论不能证明 dddddddddddddddddddddddddddddddddddddddd 已通过。

## 5. 环境阻塞不得标记通过

测试窗口无法取得必须的数据库迁移权限，也没有等价的临时数据库证据：

~~~text
TEST_BLOCKED eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee reason=BLOCKED_ENVIRONMENT
Environment-Blocks: 缺少迁移测试环境权限
Unexecuted-Items: 升级、回滚、历史数据兼容
Unblock-Condition: 提供隔离数据库并重新发出同一哈希的 TEST_REQUEST
~~~

此时不得输出 PASS 或 CONDITIONAL_PASS，也不得输出 APPROVE_PUSH/APPROVE_RELEASE。环境恢复后可以对同一冻结候选重新发出 TEST_REQUEST；若候选代码变化，则必须使用新哈希从 CANDIDATE_READY 重新开始。

## 6. 推送失败只回传证据，由审批窗口裁决

候选 `6666666666666666666666666666666666666666` 已取得 APPROVE_PUSH，但执行窗口在推送前发现精确 Push-Ref 已偏离 Expected-Remote-Hash：

~~~text
Candidate-Commit: 6666666666666666666666666666666666666666
Push-Ref: refs/heads/main
Expected-Remote-Hash: 5555555555555555555555555555555555555555
Actual-Remote-Hash: 7777777777777777777777777777777777777777
Reason-Code: REMOTE_DRIFT
~~~

执行窗口停止并只回传事实、命令结果和原因码，不输出 REPLAN。审批窗口核对证据后裁决：

~~~text
REPLAN 6666666666666666666666666666666666666666 reason=REMOTE_DRIFT
~~~

即使推送命令返回非零或异常，执行窗口也必须重新读取精确 Push-Ref；若远端实际哈希等于 Candidate-Commit，则说明远端已接受候选，应输出 `PUSHED 6666666666666666666666666666666666666666`，不得进入 REPLAN。

如果推送命令返回异常，重新读取精确 Push-Ref 后仍无法确认远端实际哈希，则执行窗口改为回传：

~~~text
Actual-Remote-Hash: UNKNOWN
Reason-Code: PUSH_OUTCOME_UNKNOWN
~~~

审批窗口输出 `REPLAN 6666666666666666666666666666666666666666 reason=PUSH_OUTCOME_UNKNOWN`。无论哪种失败，旧 APPROVE_PUSH 都不得重放、重试或升级为强制推送。

## 7. 发布失败按是否产生部署副作用分流

候选 `7777777777777777777777777777777777777777` 在发布开始前发现已批准制品缺失。Candidate-Commit 未变化，且尚无部署副作用：

~~~text
Candidate-Commit: 7777777777777777777777777777777777777777
Deployment-Side-Effects: NONE
Reason-Code: ARTIFACT_INVALIDATED
~~~

执行窗口只回传证据，不自行发出测试请求。旧测试结论、APPROVE_RELEASE 与 Owner-Evidence 立即失效，由审批窗口裁决：

~~~text
TEST_REQUEST 7777777777777777777777777777777777777777 reason=ARTIFACT_INVALIDATED
~~~

若发布已经开始，已知失败或部分成功统一使用 RELEASE_PARTIAL，包括 0 个目标成功。执行窗口回传每个目标的实际 Artifact-Digest、健康检查、已执行步骤和回滚情况，审批窗口输出：

~~~text
REPLAN 7777777777777777777777777777777777777777 reason=RELEASE_PARTIAL
~~~

若无法确认各目标的实际结果，则执行窗口回传同类证据并使用 RELEASE_OUTCOME_UNKNOWN，审批窗口输出：

~~~text
REPLAN 7777777777777777777777777777777777777777 reason=RELEASE_OUTCOME_UNKNOWN
~~~

发布已开始后的两条分支都不得重放旧 APPROVE_RELEASE 或 Owner-Evidence，必须重新规划、重新批准并在适用时取得新的 Owner 证据。ARTIFACT_INVALIDATED、RELEASE_PARTIAL 和 RELEASE_OUTCOME_UNKNOWN 都只是原因码，不是新增状态。
