# APPROVAL_RECORD

## Identity

- Task-ID: {{TASK_ID}}
- Plan-Revision: {{PLAN_REVISION}}
- Plan-Identifier: {{PLAN_IDENTIFIER}}
- Plan-Hash: {{PLAN_HASH}}
- Base-Commit: {{FULL_BASE_COMMIT}}
- Candidate-Commit: {{FULL_CANDIDATE_COMMIT}}
- Role: approver

## Scope

- Allowed-Files: {{ALLOWED_FILES}}
- Forbidden-Files: {{FORBIDDEN_FILES}}

## Acceptance-Matrix

{{FROZEN_ACCEPTANCE_MATRIX_AND_FINAL_DISPOSITION}}

## Environment

{{REVIEW_TEST_PUSH_AND_RELEASE_ENVIRONMENTS}}

## Residual-Risks

{{NONE_OR_ACCEPTED_UNACCEPTED_RISKS}}

## Decisions

- Code-Review-Decision: {{APPROVE_TEST_R1_R2_REPLAN_REJECT_SCOPE}}
- Test-Decision: {{PASS_CONDITIONAL_PASS_FAIL_TEST_BLOCKED_SPEC_GAP}}
- Push-Decision: {{APPROVE_PUSH_DENY_PENDING_NOT_APPLICABLE}}
- Push-Remote: {{REMOTE_OR_NOT_APPLICABLE}}
- Push-Ref: {{FULL_REF_OR_NOT_APPLICABLE}}
- Push-Mode: {{FAST_FORWARD_ONLY_OR_NOT_APPLICABLE}}
- Expected-Remote-Hash: {{FULL_HASH_NONE_OR_NOT_APPLICABLE}}
- Release-Decision: {{APPROVE_RELEASE_DENY_PENDING_NOT_APPLICABLE}}
- Release-Artifact-Digest: {{ALGORITHM_AND_DIGEST_OR_NOT_APPLICABLE}}
- Release-Artifact-Location: {{IMMUTABLE_LOCATION_OR_NOT_APPLICABLE}}
- Owner-Task-ID: {{TASK_ID}}
- Owner-Candidate-Commit: {{FULL_CANDIDATE_COMMIT}}
- Owner-Target-Environment: {{ENVIRONMENT_OR_NONE}}
- Owner-Artifact: {{VERSION_AND_DIGEST_OR_NONE}}
- Owner-Decision: {{APPROVED_DENIED_PENDING_NOT_REQUIRED}}
- Owner-Identity: {{HUMAN_OWNER_ID_OR_NONE}}
- Owner-Timestamp: {{ISO_8601_WITH_TIMEZONE_OR_NONE}}

## Evidence

- Plan-Evidence: {{LINK_OR_COMMAND_OUTPUT}}
- Diff-Evidence: {{BASE_TO_CANDIDATE_DIFF}}
- Test-Evidence: {{INDEPENDENT_TEST_REPORT_REFERENCE}}
- Risk-Acceptance: {{NONE_OR_ACCEPTED_RESIDUAL_RISKS}}
- Owner-Evidence: {{NONE_OR_REFERENCE_BINDING_ALL_OWNER_FIELDS_ABOVE}}

## Audit

- Timestamp: {{ISO_8601_WITH_TIMEZONE}}
- Approver: {{ROLE_OR_ID}}
- Target-Branch: {{BRANCH}}
- Target-Environment: {{ENVIRONMENT_OR_NONE}}
- Pushed-State: {{NOT_PUSHED_OR_PUSHED_EVIDENCE}}
- Released-State: {{NOT_RELEASED_OR_RELEASED_EVIDENCE}}

## State

~~~text
{{STATE}} {{FULL_CANDIDATE_COMMIT}}
~~~
