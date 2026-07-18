# TEST_WINDOW_INSTRUCTION

## Identity

- Task-ID: {{TASK_ID}}
- Plan-Revision: {{PLAN_REVISION}}
- Plan-Identifier: {{PLAN_IDENTIFIER}}
- Plan-Hash: {{PLAN_HASH}}
- Base-Commit: {{FULL_BASE_COMMIT}}
- Candidate-Commit: {{FULL_CANDIDATE_COMMIT}}
- Role: tester

## Frozen-Requirements

{{FROZEN_REQUIREMENTS_WITHOUT_EXECUTOR_OPINIONS}}

## Acceptance-Matrix

| ID | 场景 | 输入/操作 | 预期 | 必须证据 |
|---|---|---|---|---|
| {{ACCEPTANCE_ID}} | {{SCENARIO}} | {{ACTION}} | {{EXPECTED}} | {{EVIDENCE}} |

## Scope

- Allowed-Files: NONE（测试窗口不得修改业务代码）
- Forbidden-Files: {{ALL_CONTROLLED_SOURCE_AND_PROJECT_FORBIDDEN_FILES}}

## Test-Environment

{{ISOLATED_WORKTREE_RUNTIME_AND_DEPENDENCIES}}

## Test-Data

{{SAFE_TEST_DATA_ACCOUNTS_ROLES_TENANTS}}

## Required-Tests

1. {{REQUIRED_TEST}}

## Release-Artifact

- Release-Artifact-Required: {{YES_NO}}
- Artifact-Build-Command: {{COMMAND_OR_NOT_APPLICABLE}}
- Artifact-Format: {{FORMAT_OR_NOT_APPLICABLE}}
- Artifact-Location: {{IMMUTABLE_LOCATION_OR_NOT_APPLICABLE}}
- Artifact-Provenance-Rule: source commit must equal Candidate-Commit; report version and digest
- Artifact-Required-Tests: {{TESTS_OR_NOT_APPLICABLE}}

## Known-Constraints

{{OBJECTIVE_CONSTRAINTS_ONLY}}

## Residual-Risks

{{KNOWN_RISKS_WITHOUT_PREJUDGING_RESULT}}

## State

~~~text
APPROVE_TEST {{FULL_CANDIDATE_COMMIT}}
TEST_REQUEST {{FULL_CANDIDATE_COMMIT}}
~~~
