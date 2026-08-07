# M02 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| Lead create | COVERED | test_douyin_webhook.py:407（webhook 创建） |
| Lead update | COVERED | test_douyin_webhook.py（pending 更新 / 非 pending skip） |
| Lead dedupe | COVERED | test_douyin_webhook_atomic_idempotency.py（会话维度幂等） |
| cross-merchant isolation | COVERED | test_douyin_leads_session_isolation.py / test_douyin_workbench_tenant_isolation_r2.py |
| assignment | COVERED | test_leads_management.py（分配/转派） |
| transfer | COVERED | test_leads_management.py（is_reassign → record_type="reassign"） |
| recycle | MISSING | 无 /unassign 或 /recycle 测试（功能 NOT_IMPLEMENTED） |
| sales data scope | PARTIAL | 商户内全部可见已验证；无"仅本人"强制逻辑测试 |
| contact update | COVERED | test_douyin_webhook.py（best-effort 回填） |
| M01 integration | COVERED | test_douyin_webhook.py（webhook→Lead 写入完整） |
| M04 integration | PARTIAL | record_manual_reply 回写有测试；微信通知任务创建无集成测试（auto_notify_disabled） |
| feedback parse | COVERED | test_sales_feedback_parser.py（三类模板解析） |
| status transition | PARTIAL | pending→assigned→replied 有测试；timeout→? 无审计/无约束验证 |
| audit | PARTIAL | assign/reassign 有 LeadFollowupRecord；replied/timeout 状态变更无显式审计 |
| failure/retry | PARTIAL | 通知失败有 LeadNotification.send_status；Lead 操作失败无 retry 机制 |

## E2E 验真结果（2-M02.2 Docker，2026-08-07）

环境：docker compose dev（9000 + PG + 能力中心）

| E2E | 域 | 结果 | 证据 |
|---|---|---|---|
| 1 | Webhook Identity/Aggregation Matrix | **PASS** | Webhook create→created；同会话重复→duplicate_event；同客户新会话→created（新建）；Manual create→200 |
| 1 | Legacy sync identity | NOT_VERIFIED | sync-leads 未在 Docker E2E 中触发（dry_run=false 写库路径未测） |
| 1 | Manual create identity | PARTIAL | Manual create→200 成功，但未携带相同业务身份验证是否产生重复 Lead；ISSUE-M02-002 不升级 HIGH |
| 2 | Cross-merchant | **TEST_GAP** | list 只返回 dev-merchant，但测试库无第二 merchant fixture（mock auth 固定 dev-merchant），无法构造跨商户场景 |
| 3 | Assignment 真实算法 | **TEST_FIXTURE_GAP** | 0 staff（docker dev 无销售 fixture），无法验证轮询/少者优先；需补 staff fixture 重测 |
| 4 | Reassign | **TEST_FIXTURE_GAP** | 0 assigned lead + 0 staff，无法验证转派/reassign_count；需补 fixture 重测 |
| 5 | Feedback Parse | **TEST_INPUT_GAP** | POST /sales-feedback/parse 返回 400（feedback_no 格式或上下文问题）；需找到正式接受格式构造合法/非法输入 |
| 6 | Data Scope | **CODE_VERIFIED + PENDING_E2E** | 代码确认无"仅本人"强制（assigned_staff_id 可选过滤）；但未用两 Sales + 两 Lead 真实 API 验证 |
| 7 | Status 自由字符串 | **DB_VERIFIED + APPLICATION_PENDING** | DB 无约束已验证（models.py:164）；但 API/service 写入链对未知 status 的行为需 E2E |

### ISSUE-M02-002 升级条件检查

- Manual create（E2E-1）PARTIAL：不带 account_open_id/conversation_short_id 创建成功（200），但不会与 webhook 线索冲突（无相同业务身份）
- **不升级 HIGH**：未证明 Manual API 携带完全相同业务身份仍产生不可区分重复 Lead

### 仍 SKIP（需 staging/外部环境）

- 真实 webhook→Lead→M04→反馈回写全链路
- auto_notify 真实链路（当前 disabled）
- 销售数据范围真实行为（需真实商户上下文 + 多角色）
- Assignment + Reassign（需多销售数据）

**E2E 状态：`M02_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_FIXTURE_GAPS`**（无 BLOCKER，Webhook Identity PASS，Cross-merchant/Assignment/Reassign/Feedback/Data Scope/Status 有 fixture/input gap 待 R1 补）
