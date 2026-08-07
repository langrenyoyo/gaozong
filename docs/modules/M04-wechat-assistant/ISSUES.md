# M04 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## MEDIUM

### ISSUE-M04-001 无 lease/claim，多 Agent 同商户可能重复拉取

- **位置**：wechat_task_service.py（grep lease/claim 无匹配）
- **事实**：服务端无原子认领/锁标记，get_pending_wechat_tasks 按 merchant_id 过滤 status==pending 直接返回；Agent 端有 _wechat_task_lock 防并发（local_agent_main.py:2279），但服务端无 lease
- **影响**：多 Agent 同商户理论上可能拉同一 pending 任务
- **建议**：如多 Agent 部署需加服务端 lease/claim 机制

### ISSUE-M04-002 result report 非严格幂等，重复回写可能重复扣算力

- **位置**：wechat_task_service.py:348-352, 437-464, 462
- **事实**：submit_wechat_task_result 无幂等键/版本号校验，重复回写直接覆盖 status/raw_result；已 sent 任务再次回写 sent=true 会重复 _report_wechat_task_compute_usage（:462）
- **影响**：重复回写可能重复扣算力
- **建议**：加幂等校验（版本号/已处理标记）

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

## ISSUE-M02-007 专项结论

```
ISSUE-M02-007 Feedback parse-and-persist contract failure
最终结论: CONTRACT_MATCHES

M04 实际输出格式（_try_parse_sales_feedback_from_reply 传入 raw_text）:
  - 含【线索反馈】模板首行
  - 含 feedback_no: XGF-{lead_id}-{staff_id}
  - 进程内直接函数调用（非 HTTP），无序列化漂移

M02 parse_and_persist 接受格式:
  - 首行精确匹配【线索反馈】
  - feedback_no 正则 ^XGF-\d+-\d+$ 校验
  - 上下文校验: lead/staff 归属 + feedback_no==build_feedback_no

两端格式完全一致。ISSUE-M02-007 的 400 根因不在 M04→M02 合同不匹配，
而在 E2E 测试未携带完整上下文（需真实 lead_id+staff_id 关联的 DB 记录）。

升级条件: staging 证明 M04 生产反馈路径使用相同合同且合法反馈无法持久化 → HIGH
当前建议: 保持 MEDIUM，staging E2E 验证 parse_and_persist 真实调用路径
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
| HIGH | 0 |
| MEDIUM | 2（无 lease/claim / result report 非幂等） |
| LOW | 2（无崩溃恢复 / failed 无 requeue） |
| ARCHITECTURE_OBSERVATION | 1（M04 直接写 M02 DATA_COUPLING） |
| Legacy 建议 | 1（legacy_foreground_ok/diag UNKNOWN→ACTIVE） |
