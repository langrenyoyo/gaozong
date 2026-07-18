# EXECUTION_REPORT

## Identity

- Task-ID: {{TASK_ID}}
- Plan-Revision: {{PLAN_REVISION}}
- Plan-Identifier: {{PLAN_IDENTIFIER}}
- Plan-Hash: {{PLAN_HASH}}
- Base-Commit: {{FULL_BASE_COMMIT}}
- Candidate-Commit: {{FULL_CANDIDATE_COMMIT}}
- Branch: {{BRANCH}}
- Role: executor

## Scope

- Allowed-Files: {{ALLOWED_FILES}}
- Forbidden-Files: {{FORBIDDEN_FILES}}
- Changed-Files: {{CHANGED_FILES}}
- Checked-But-Unchanged-Files: {{CHECKED_FILES}}

## Acceptance-Matrix

{{FROZEN_ACCEPTANCE_MATRIX_AND_EXECUTOR_SELF_TEST_MAPPING}}

## Environment

{{OS_RUNTIME_DEPENDENCIES_AND_TEST_CONFIGURATION}}

## Implementation

{{IMPLEMENTATION_SUMMARY}}

## Plan-Deviations

{{NONE_OR_EXACT_DEVIATION_AND_APPROVAL}}

## Evidence

- Test-Commands:
  - {{COMMAND}}
- Test-Results:
  - {{RESULT_WITH_EXIT_CODE}}
- Unexecuted-Tests:
  - {{NONE_OR_TEST_AND_REASON}}
- Environment-Blocks:
  - {{NONE_OR_BLOCK_WITH_EVIDENCE}}
- Residual-Risks:
  - {{NONE_OR_RISK}}

## Git Evidence

- git diff --stat:

~~~text
git diff --stat {{FULL_BASE_COMMIT}}..{{FULL_CANDIDATE_COMMIT}}
{{OUTPUT}}
~~~

- git diff --name-status:

~~~text
git diff --name-status {{FULL_BASE_COMMIT}}..{{FULL_CANDIDATE_COMMIT}}
{{OUTPUT}}
~~~

- git log / parent evidence:

~~~text
git log --oneline {{FULL_BASE_COMMIT}}..{{FULL_CANDIDATE_COMMIT}}
{{OUTPUT}}

git rev-list --parents {{FULL_BASE_COMMIT}}..{{FULL_CANDIDATE_COMMIT}}
{{OUTPUT}}
~~~

- git status --short:

~~~text
{{OUTPUT_OR_EMPTY}}
~~~

- Pushed: no
- Merged: no
- Released: no

## State

~~~text
CANDIDATE_READY {{FULL_CANDIDATE_COMMIT}}
~~~
