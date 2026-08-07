# M04 数据模型

> source_baseline: c26ec227e70d

## WechatTask（OWNER: M04）

定义：`app/models.py:290-336`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| task_type | String(30) default notify_sales | notify_sales / detect_reply / send_report_attachment |
| lead_id | FK→douyin_leads.id | 永久绑定，创建后不可变 |
| staff_id | FK→sales_staff.id | |
| reply_check_id | FK→reply_checks.id | |
| target_nickname | String(100) | 销售微信昵称（执行时定位联系人） |
| message | Text | 通知内容（含反馈编号+模板） |
| mode | String(20) default paste_only | paste_only / single_send |
| status | String(20) default pending | pending/running/pasted/sent/failed/blocked/cancelled |
| failure_stage | String(100) | |
| raw_result | _JSONStringJSONB | 执行结果 JSON |
| agent_hostname | String(100) | 事后审计（非领取前绑定） |
| agent_pid | Integer | 事后审计 |
| pasted_at / sent_at | DateTime | |
| Phase 8-B 附件投递字段 | 多个 | execution_token_hash/download_ticket_hash/send_nonce_hash 等（令牌仅存 SHA-256） |

**无 merchant_id 列**：商户归属继承自 lead_id/staff_id 反查（wechat_task_service.py:106-129, 143-180）
**无 agent_id 列**：Local Agent 身份仅 agent_hostname+agent_pid 事后审计

## 任务状态机

### notify_sales
```
pending → (success=false) → failed
pending → (verified=false/partial_match/manual_review) → blocked
pending → (pasted && !sent && verified) → pasted (+ auto_create_detect_reply_task)
pending → (sent && verified) → sent
pending → (paste_mode + sent=true) → blocked (task_mode_send_mismatch)
```

### detect_reply
```
pending → (replied) → completed
pending → (manual_review) → completed
pending → (未命中) → pending (回退，下次 poll 重拉)
pending → (failed) → failed
pending → (detect_count >= 30) → completed (max_retries_exceeded)
```

## 相关表

| 表 | OWNER | 说明 |
|---|---|---|
| SalesStaff | M02/M04 共享 | name/wechat_id/wechat_nickname/status/merchant_id + enable_lead_assignment |
| ReplyCheck | M04 | lead_id/staff_id/reply_deadline/is_effective/check_status/reply_content |
| LeadNotification | M04 | lead_id/send_status/sent_at/error_message |
| SalesLeadFeedback | M04 | feedback_no/lead_id/staff_id/intention_level；唯一(merchant_id, feedback_no) |
| SalesLeadUpdate | M04 | feedback_no/visit_status/deal_status |
| SalesDailySummary | M04 | staff_id/summary_date |

## 商户隔离

- **双层隔离**：token→merchant_id（local_agent_auth.py:32-48）+ lead/staff FK 反查商户（wechat_task_service.py:121-129, 179-180）
- poll：get_pending_wechat_tasks 按 merchant_id 过滤
- result：task_belongs_to_merchant 双校验（lead.merchant_id + staff.merchant_id）
- 跨商户 task_id → 404（不泄露存在性）
- 通用 HTTP 创建已 410 关闭（wechat_tasks.py:35-48），仅服务端内部 create_wechat_task

### 隔离能力拆分

| 层面 | 状态 | 说明 |
|---|---|---|
| Merchant boundary | CODE_VERIFIED | token→merchant_id + lead/staff FK 反查 |
| Lead/staff consistency | CODE_VERIFIED | task.lead_id + task.staff_id 创建时固化，商户归属继承 |
| Device-level task ownership | NOT_VERIFIED / POSSIBLY_ABSENT | 无 agent_id 列，仅 agent_hostname+agent_pid 事后审计；无领取前设备绑定 |
| Sender WeChat identity | NOT_VERIFIED | 哪个微信账号发（本机微信进程），待 Windows E2E |

> **区分**：Recipient Identity（target_nickname 防护完整，CODE_VERIFIED）vs Sender Identity（哪个微信账号发，NOT_VERIFIED 待 Windows E2E）

### 持久/恢复能力拆分

| 能力 | 状态 | 说明 |
|---|---|---|
| Durable persistence | VERIFIED | WechatTask 表持久化 |
| Claim/lease | ABSENT | 无原子认领/锁标记 |
| Automatic retry/requeue | ABSENT | failed 无自动重入队 |
| Crash recovery | NOT_VERIFIED / likely limited | Agent 崩溃任务停留 pending/processing，无超时回收 |
| Manual recovery | 按代码记录 | notify_sales failed 需人工重新 send-to-staff；detect_reply 未命中回退 pending |
