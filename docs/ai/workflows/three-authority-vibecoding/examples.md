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
