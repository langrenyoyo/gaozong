# M02 真实运行链路

> source_baseline: c26ec227e70d | 所有链路附 file:line 证据

## 1. Lead Creation（webhook 主入口）

```
GMP webhook → _handle_douyin_webhook (integrations.py:459)
  → process_webhook_event (douyin_webhook.py:1043)
    → claim_webhook_event 原子占位 (idempotency_service.py:54)
    → extract_contacts_from_text 提取联系方式
    → upsert_lead_from_webhook (douyin_webhook.py:678)
      → find_lead_by_session (douyin_webhook.py:589)
        聚合键: (account_open_id, conversation_short_id, merchant_id) 三元过滤 (:604-608)
        merchant_id 必填 (:602-603)
      → 不存在 → DouyinLead(status="pending") (:765-839)
        跨租户防御: _detect_tenant_scope_conflict (:612)
        SAVEPOINT 隔离: (:787-790)
      → 已存在且 pending → 更新 customer_name/content/raw_data/extracted_* (:841-861)
        联系方式 best-effort 回填: 有则覆盖无则保留 (:844-854)
      → 已存在且非 pending → skipped 不改业务状态 (:863-870)
      → _dispatch_lead_after_create (douyin_webhook.py:876)
        → auto_assign_next (assign_service.py:90) 自动分配
        → auto_notify_disabled (:1030) 当前禁用自动微信通知
    → enqueue_auto_reply_run (douyin_webhook.py:1224)
```

## 2. Lead Update（webhook 路径）

同一会话后续消息 → find_lead_by_session 命中 → pending 更新 / 非 pending skip。
联系方式后补：`customer_contact = customer_contact or existing` / `extracted_phone = contact_result.phone or existing`（:844-854）。

## 3. Dedup / Merge

- **会话维度去重**：(account_open_id, conversation_short_id) 唯一约束（models.py:145-148）
- **同一客户重复发私信**：不会生成多条 Lead（会话维度）
- **跨会话**：同一客户不同 conversation_short_id = 多条 Lead（无跨会话合并）
- **手机号归并**：NOT_IMPLEMENTED（webhook upsert 不按手机号查询）
- **CustomerProfile 自动合并**：NOT_IMPLEMENTED（无 FK 关系、无自动同步）
- **sync-leads 聚合键不一致**：sync 用 source_id（douyin_sync_service.py:52），webhook 用会话维度

## 4. Assignment（自动分配）

```
_dispatch_lead_after_create (douyin_webhook.py:876)
  → auto_assign_next (assign_service.py:90)
    → 查 SalesStaff: merchant_id 匹配 + enable_lead_assignment!=False + status="active" (:114-117)
    → 按 ID 排序遍历 (:118)
    → 统计每个销售 assigned/pending 状态线索数 (:123-132)
    → 取 min(staff_counts) → 同级少者优先 (:132)
    → assign_lead (assign_service.py:23) → lead.status="assigned" (:60)
    → LeadFollowupRecord record_type="assign" (:74-81)
```

已实现：轮询 / 同级少者优先 / 商户隔离 / 跳过关闭分配 / 首次不重复
未实现：权重 / 优先级 / 每日上限 / 超时回收重分配 / reassign_count 从不自增

## 5. Transfer / Recycle

- **转派**：复用 POST /leads/{id}/assign（leads.py:136），assign_service 内判断 is_reassign（:55），写 record_type="reassign"（:78）
- **回收**：NOT_IMPLEMENTED（无 /unassign 或 /recycle API；超时线索进 timeout 不重分配）

## 6. M01 → M02

- webhook upsert DouyinLead（douyin_webhook.py:678）
- webhook recover_contact_valid（douyin_webhook.py:1194）
- 客服工作台读 customer_profiles（douyin_workbench_conversation_service.py:28）
- M01 直接操作 M02 ORM/table：**是**（douyin_webhook.py 直接 `DouyinLead(...)` + `db.add`，不经正式 M02 service）

## 7. M02 → M04（Lead→微信通知）

- webhook 自动路径：**CONFIG_DISABLED**（auto_notify_disabled，douyin_webhook.py:1030）
- 手动路径：POST /lead-notifications/send-to-staff（lead_notification_actions.py:42）→ create_wechat_task（wechat_task_service.py:35）
- 通知内容：compose_notification_text（notification_template.py:83）含客户名/来源/内容/联系方式/反馈编号
- 任务持久化：WechatTask 表

## 8. M04 → M02（销售反馈）

```
销售微信回复 → M04 detect_reply 任务
  → record_manual_reply (reply_checker.py:11)
    → lead.status = "replied"（有效）或 "assigned"（无效）(:45)
    → 联动 contact_state: mark_contact_invalid / recover_contact_valid (:48-75)
  → 自动解析销售反馈: _try_parse_sales_feedback_from_reply (wechat_task_service.py:957)
    → sales_feedback_parser.parse_and_persist_sales_feedback
    → SalesLeadFeedback / SalesLeadUpdate / SalesDailySummary 落库
  → _update_check_and_notification_on_replied (wechat_task_service.py:882)
    → 更新 ReplyCheck + LeadNotification
```

- A/B/C 反馈解析：三类固定模板（【线索反馈】/【线索更新】/【每日线索总结】），首行精确匹配，不接 LLM
- 解析失败：返回 skipped 不写库
- 手动纠正：POST /sales-feedback/parse（sales_feedback.py:24）
