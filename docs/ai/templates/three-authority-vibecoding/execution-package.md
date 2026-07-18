# EXECUTION_WINDOW_INSTRUCTION

## Identity

- Task-ID: {{TASK_ID}}
- Plan-Revision: {{PLAN_REVISION}}
- Plan-Identifier: {{PLAN_IDENTIFIER}}
- Plan-Hash: {{PLAN_HASH}}
- Base-Commit: {{FULL_BASE_COMMIT}}
- Candidate-Commit: NONE
- Target-Branch: {{TARGET_BRANCH}}
- Role: executor
- Risk-Level: {{L0_L1_L2_L3}}

## Goal

{{GOAL}}

## Known-Facts

{{KNOWN_FACTS_WITH_EVIDENCE}}

## Scope

- Allowed-Files:
  - {{ALLOWED_FILE}}
- Forbidden-Files:
  - {{FORBIDDEN_FILE}}

## Call-Chain

{{REAL_CALL_CHAIN}}

## Data-Contract

{{INPUT_OUTPUT_SCHEMA_AND_COMPATIBILITY}}

## Permission-Boundary

{{AUTHORIZATION_TENANT_SECURITY_BOUNDARY_OR_NONE}}

## Acceptance-Matrix

| ID | 场景 | 输入/操作 | 预期 | 证据 |
|---|---|---|---|---|
| {{ACCEPTANCE_ID}} | {{SCENARIO}} | {{ACTION}} | {{EXPECTED}} | {{EVIDENCE}} |

## Red-Test

{{FAILING_TEST_AND_EXPECTED_FAILURE}}

## Implementation-Steps

1. {{MINIMAL_IMPLEMENTATION_STEP}}

## Green-Test

{{TEST_COMMAND_AND_EXPECTED_PASS}}

## Regression-Test

{{REGRESSION_COMMANDS_AND_EXPECTATIONS}}

## Build-And-Lint

{{BUILD_LINT_SCHEMA_OR_DOC_COMMANDS}}

## Environment

{{REQUIRED_ENVIRONMENT_AND_DEPENDENCIES}}

## Residual-Risks

{{KNOWN_RISKS_BEFORE_IMPLEMENTATION_OR_NONE}}

## Forbidden-Commit-Items

- Forbidden-Files 中的内容；
- 密钥、真实凭据、本地环境文件；
- 缓存、日志、覆盖率、构建产物；
- 与任务无关的格式化或重构；
- {{PROJECT_SPECIFIC_FORBIDDEN_ITEM}}。

## Candidate-Commit-Rule

1. 只暂存 Allowed-Files，并核对 git diff --cached --name-only。
2. 完成规定自测后创建本地候选提交。
3. 用 git rev-parse HEAD 返回完整 Candidate-Commit。
4. 用 git merge-base --is-ancestor <Base-Commit> <Candidate-Commit> 验证基线祖先关系。
5. 用 git log --oneline 和 git rev-list --parents 记录 Base-Commit..Candidate-Commit 的提交来源。
6. 本地提交不代表允许推送、合并或发布。
7. CANDIDATE_READY 回传后候选冻结；任何变化必须创建新哈希。
8. 禁止 amend 后继续沿用旧哈希。

## Start-Format

强制预检通过后、任何施工写操作前输出：

~~~text
IMPLEMENTING <Task-ID> <Plan-Revision> <Base-Commit>
~~~

## Return-Format

使用 [execution-report](execution-report.md) 的全部字段，最后输出：

~~~text
CANDIDATE_READY <full-candidate-hash>
~~~

## Approval

~~~text
PLAN_APPROVED {{TASK_ID}} {{PLAN_REVISION}} {{FULL_BASE_COMMIT}}
~~~
