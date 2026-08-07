# M04 真实运行链路

> source_baseline: c26ec227e70d | 所有链路附 file:line 证据

## 1. Lead → WeChat Task（M02→M04 通知链）

```
M02 Lead 创建/分配
  → 手动: POST /lead-notifications/send-to-staff (lead_notification_actions.py:42)
    → evaluate_lead_wechat_notify_eligibility（限频 429/Retry-After）
    → build_feedback_no(lead_id, staff_id) → "XGF-{lead_id}-{staff_id}" (notification_template.py:34)
    → compose_notification_text（含客户名/来源/内容/联系方式/反馈编号+【线索反馈】模板）
    → create_wechat_task(task_type="notify_sales", mode="single_send") (wechat_task_service.py:35)
    → _create_notification（同事务提交）
  → 自动: webhook _dispatch_lead_after_create (douyin_webhook.py:876)
    → auto_assign_next 分配销售
    → auto_notify_disabled (:1030) ← 当前禁用，不创建任务
```

## 2. 9000 → 19000 通信

```
19000 启动 → create_local_agent_app (local_agent_main.py:1537)
  → start_heartbeat_loop (:516) → POST {server_url}/agent/heartbeat (:504) 每 10s
    → payload: agent_client_id/agent_name/host_name/agent_status/wechat_status/current_task_id/version
  → 19000 不碰数据库（DATABASE_URL 从 Worker 环境剥离 :90-94）
  → 所有数据访问经 9000 HTTP 接口

19000 领取任务:
  → POST /agent/tasks/poll-and-execute (local_agent_main.py:1871)
    → GET {server_url}/wechat-tasks/pending?task_type=notify_sales&limit=1 (:1953)
      → 9000: get_pending_wechat_tasks(merchant_id=ctx.merchant_id) (wechat_task_service.py:115)
        → token→merchant_id 映射 (local_agent_auth.py:32-48)
        → 按 merchant_id 过滤 status==pending
    → 或指定 task_id: GET {server_url}/wechat-tasks/agent/{task_id} (:1921)
      → INNER JOIN + AND 双重商户过滤 (wechat_task_service.py:121-129)
    → 校验 task_type=="notify_sales" / target_nickname 非空 / mode ∈ {paste_only, single_send}
```

## 3. Task Poll → Execution → Result

```
19000 领取任务 (:1973-1986)
  → task_data: id/task_type/target_nickname/mode/lead_id/staff_id/message
  → 执行微信 UI 自动化:
    → verify_current_chat_contact(target_nickname) 检查当前聊天 (:2066)
    → 或 _open_and_verify_contact_with_candidates (target_nickname, wechat_id, remark, ...)
      → _build_search_candidate_entries (wechat_search_keyword→wechat_id→remark→search_alias)
      → open_chat_by_nickname + verify_current_chat_contact (OCR 验证)
      → partial_match/manual_review/未 verified → 硬门禁阻断
    → 文本发送（paste_only 粘贴不发送 / single_send 粘贴+发送）
    → 发送前检查: foreground guard / search_focus guard / search_text_verified
  → 结果回传: _write_back_task_result (local_agent_main.py:545-601)
    → POST {server_url}/wechat-tasks/{task_id}/result (:593)
    → 9000: submit_wechat_task_result (wechat_task_service.py:340-460)
      → require_local_agent_context (token→merchant_id)
      → task_belongs_to_merchant (lead.merchant_id + staff.merchant_id 双校验)
      → 状态流转:
        success=false → failed
        verified=false/partial_match/manual_review → blocked
        pasted && !sent && verified → pasted (+ auto_create_detect_reply_task)
        sent && verified → sent
```

## 4. Sales Feedback Collection

```
19000 detect_reply 任务:
  → POST /agent/tasks/poll-and-detect (local_agent_main.py:2246)
    → 拉取 task_type=detect_reply 任务
    → _detect_reply_for_task (:1220) 读取微信消息
    → find_self_messages / find_fallback_messages / find_effective_reply (reply_detector.py)
    → 结果回传: POST {server_url}/replies/agent-write-back (local_agent_main.py:1363)
  → 9000: agent_write_back_reply (wechat_ui_reply_service.py:280)
    → find_effective_reply 分析关键词/长度
    → is_effective → lead.status="replied" / ReplyCheck replied
    → !is_effective → lead.status="assigned" (回退)
    → 空号识别: analyze_contact_validity
      → invalid → mark_contact_invalid + create_followup_task (空号追问)
      → valid → recover_contact_valid
    → 自动解析销售反馈: _try_parse_sales_feedback_from_reply (wechat_task_service.py:957)
      → reply_text 含"【" → parse_and_persist_sales_feedback
      → raw_text = 销售回填的【线索反馈】模板原文
      → feedback_no = XGF-{lead_id}-{staff_id} (从文本提取+校验)
      → 上下文校验: lead 归属 merchant + staff 归属 merchant + feedback_no==build_feedback_no
      → upsert SalesLeadFeedback / SalesLeadUpdate / SalesDailySummary
```

## 5. M04 → M02 Feedback Persistence

```
_parse_and_persist_sales_feedback (进程内直接函数调用，非 HTTP)
  → parse_sales_feedback_text (首行精确匹配【线索反馈】/【线索更新】/【每日线索总结】)
  → _verify_lead_feedback_context (lead/staff 归属校验 + feedback_no 校验)
  → upsert SalesLeadFeedback (merchant_id + feedback_no)
  → 更新 ReplyCheck (reply_content/is_effective/check_status)
  → 更新 DouyinLead (status=replied/assigned)
  → 更新 CustomerProfile (mark_contact_invalid/recover_contact_valid)
```

## 6. Failure / Retry

- **notify_sales failed**：status=failed，无自动 requeue，需人工重新 send-to-staff
- **detect_reply 未命中**：回退 pending，下次 poll 重拉（最多 _MAX_DETECT_COUNT=30 次→completed）
- **Agent 崩溃**：任务停留在 pending/processing，无超时回收
- **无 lease/claim**：多 Agent 同商户理论上可能拉同一 pending 任务（Agent 端有 _wechat_task_lock 防并发，服务端无 lease）
