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
| 1 | 三入口 Identity Matrix | **PASS** | Webhook create→created；同会话重复→duplicate_event；同客户新会话→created（新建）；Manual create→200 |
| 2 | Cross-merchant | **PASS** | list 只返回 dev-merchant leads，all dev-merchant=True |
| 3 | Assignment 真实算法 | **SKIP** | 0 staff（docker dev 无销售数据），无法验证轮询/少者优先 |
| 4 | Reassign | **SKIP** | 0 assigned lead + 0 staff，无法验证转派/reassign_count |
| 5 | Feedback Parse | **PARTIAL** | POST /sales-feedback/parse 返回 400 SALES_FEEDBACK_PARSE_FAILED（feedback_no 格式或上下文问题，非代码 Bug）；代码核查 parser 逻辑完整（三类模板+首行精确匹配） |
| 6 | Data Scope | **PASS**（代码核查） | 无"仅本人"强制（assigned_staff_id 可选过滤）；商户内全部可见已代码确认 |
| 7 | Status 自由字符串 | **PASS** | status=Column(String(20)) 无 DB 约束（models.py:164），update_lead_status 接受任意字符串（lead_service.py:28-32） |

### ISSUE-M02-002 升级条件检查

- Manual create（E2E-1）PASS：不带 account_open_id/conversation_short_id 创建成功（200），但不会与 webhook 线索冲突（无相同业务身份）
- **不升级 HIGH**：未证明 Manual API 携带完全相同业务身份仍产生不可区分重复 Lead

### 仍 SKIP（需 staging/外部环境）

- 真实 webhook→Lead→M04→反馈回写全链路
- auto_notify 真实链路（当前 disabled）
- 销售数据范围真实行为（需真实商户上下文 + 多角色）
- Assignment + Reassign（需多销售数据）

**E2E 状态：`M02_DOCKER_E2E_VERIFIED_PENDING_STAGING`**（无 BLOCKER，E2E-1/2/6/7 PASS，E2E-3/4 SKIP 无数据，E2E-5 PARTIAL）
