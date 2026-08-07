# M04 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## MEDIUM

### ISSUE-M04-001 无 lease/claim，多 Agent 同商户可能重复拉取（HIGH / DUPLICATE_EXECUTION_RISK）

- **位置**：wechat_task_service.py（grep lease/claim 无匹配）
- **事实**：服务端无原子认领/锁标记，get_pending_wechat_tasks 按 merchant_id 过滤 status==pending 直接返回
- **E2E 证据**：2-M04.2R2 Gate 2 Concurrent Poll 证明两客户端同时 GET pending → A1=1 A2=1 same=True（拿到同一 Task）
- **影响**：多 Agent 同商户会拉同一 pending 任务，导致重复执行
- **升级**：MEDIUM → HIGH（Docker E2E 证明 DUPLICATE_EXECUTION_RISK）
- **建议**：加服务端 lease/claim 机制（原子 UPDATE SET status=processing WHERE status=pending RETURNING）

### ISSUE-M04-002 Result duplicate side-effect coverage incomplete

- **Category**: MEDIUM
- **位置**：wechat_task_service.py:348-352, 437-464, 462
- **Business persistence duplicate**: E2E NOT REPRODUCED（Gate 4 重复提交未产生重复业务写入）
- **detect_reply duplicate**: DEDUP VERIFIED（Gate 4 detect_reply=1 去重正确，不重复创建）
- **_compute_usage / financial side effect**: NOT VERIFIED（重复回写可能重复调用 _report_wechat_task_compute_usage :462，但 Docker E2E 未观察到实际算力副作用）
- **Close condition**: M07 proves compute also dedup → close
- **不继续笼统称 "result report 非幂等"**

## LOW

### ISSUE-M04-003 无崩溃恢复，任务永久停留

- **位置**：wechat_task_service.py（grep recover/expire 无匹配）
- **事实**：Agent 执行中崩溃，任务停留在 pending/processing，无超时回收；return_visit 有独立启动恢复但与 WechatTask 无关
- **影响**：崩溃后任务无法自动恢复
- **建议**：加任务超时回收机制

### ISSUE-M04-004 notify_sales failed 无自动 requeue

- **位置**：wechat_task_service.py
- **事实**：failed 后无自动重入队，需人工重新 send-to-staff
- **影响**：发送失败需人工干预
- **建议**：如需自动重试需加 requeue 逻辑

## ARCHITECTURE_OBSERVATION

### ARCH-M04-001 M04 直接写 M02 Lead 数据（DATA_COUPLING）

- **位置**：wechat_ui_reply_service.py:332 / reply_checker.py:15
- **事实**：agent_write_back_reply / record_manual_reply 直接更新 ReplyCheck + DouyinLead + LeadNotification + CustomerProfile
- **影响**：M04 直接操作 M02 ORM，不经正式 M02 service
- **处理**：登记 DATA_COUPLING，不重构（天然业务依赖）

## 已关闭

### ISSUE-M02-007 Feedback parse-and-persist 合同失败（已关闭）

```
ISSUE-M02-007 Feedback parse-and-persist contract failure
最终结论: CLOSED

Contract shape: CODE_VERIFIED_MATCH
M04 call path: CODE_VERIFIED
Parse-and-persist runtime success: E2E VERIFIED (2-M04.2R2 Gate 6)

2-M04.2R2 Gate 6 证据:
  - parse_and_persist_sales_feedback 进程内调用成功
  - parse_status=success, kind=lead_feedback, error=None
  - 完整上下文: lead_id=11 + staff_id=1 + feedback_no=XGF-11-1 + 正式模板
  - root cause: earlier E2E fixture lacked DB/task context
  - production contract defect: NO
```

## Legacy 补充

### LEGACY-M04-001 legacy_foreground_ok/diag 从 UNKNOWN 建议→ACTIVE

- **位置**：contact_searcher.py:2569-2648
- **事实**：legacy_foreground_ok/diag 是 _click_left_button 的诊断字段参数，仅在 debug dict 中记录旧 _ensure_wechat_foreground 结果；正式执行链仍使用 _ensure_wechat_foreground 作为前台 guard（多处调用）；非"已被 19000 新 guard 替代"
- **建议**：LEGACY_REGISTER LEGACY-010 从 UNKNOWN→ACTIVE（诊断字段，非独立 guard）
- **处理**：报告给审批，不直接修改 LEGACY_REGISTER

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 1（无 lease/claim → DUPLICATE_EXECUTION_RISK，E2E 证明） |
| MEDIUM | 1（result report 非幂等，重复扣费风险未消除但 Gate 4 未证明重复副作用） |
| LOW | 2（无崩溃恢复 / failed 无 requeue） |
| ARCHITECTURE_OBSERVATION | 1（M04 直接写 M02 DATA_COUPLING） |
| 已关闭 | 1（ISSUE-M02-007 parse-and-persist 合同，Gate 6 E2E PASS） |
| Legacy 建议 | 1（legacy_foreground_ok/diag UNKNOWN→ACTIVE） |
