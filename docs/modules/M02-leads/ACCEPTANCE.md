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

## E2E 验收清单（待 2-M02.2）

### DOCKER_TESTABLE
1. **Lead CRUD**：webhook 创建→读取→分配→转派→状态变更
2. **Dedup**：同一会话重复消息不重复创建
3. **Cross-merchant**：A 商户不能读 B 商户 Lead
4. **Assignment algorithm**：同级少者优先验证
5. **Feedback parse**：三类模板解析→落库

### EXTERNAL_ENV_REQUIRED
6. **webhook→Lead→M04 通知→销售反馈→状态回写**：需真实 webhook + 微信环境
7. **auto_notify 真实链路**：需启用 auto_notify（当前 disabled）
8. **销售数据范围真实行为**：需真实商户上下文

### POLICY_PENDING
9. super_admin 数据范围行为
