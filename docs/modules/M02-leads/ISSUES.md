# M02 问题登记

> source_baseline: c26ec227e70d | 本轮只登记不修复

## HIGH

### ISSUE-M02-001 聚合键双轨制（webhook 会话归并 vs sync source_id）

- **位置**：douyin_webhook.py:589（find_lead_by_session 用 account_open_id+conversation_short_id）vs douyin_sync_service.py:52（_find_existing_lead 用 source_id）
- **事实**：两条链路对同一客户可能产生不同 Lead，去重口径不一致
- **影响**：sync-leads 仍可写库时按旧 source_id 逻辑，与 webhook 会话归并并存，同一客户可能产生重复 Lead
- **建议**：sync-leads 完全停用后风险消除；当前 COMPAT 但非完全停用

## POLICY_PENDING / CONTRACT_GAP

### ISSUE-M02-002 手工 create 绕过会话归并（POLICY_PENDING / CONTRACT_GAP）

- **位置**：app/services/lead_service.py:8 create_lead
- **事实**：POST /leads 不经 find_lead_by_session，无租户冲突检测
- **当前定性**：POLICY_PENDING / CONTRACT_GAP — Manual Create 是否应走与 webhook 相同的归并逻辑取决于 Lead Identity Contract 设计（DATA_MODEL.md 明确"M02 整体尚无统一 Lead Identity Contract"）
- **升级条件**：Docker E2E 证明 Manual API 携带完全相同业务身份仍产生不可区分重复 Lead → 升级 HIGH

## ARCHITECTURE_OBSERVATION + PRODUCT_POLICY_PENDING

### ISSUE-M02-003 同客户多会话 = 多条 Lead

- **位置**：find_lead_by_session 聚合键是会话维度
- **事实**：同一客户 from_user_id 在不同 conversation_short_id 下创建独立 Lead，无手机号归并、无 CustomerProfile 自动合并
- **当前定性**：ARCHITECTURE_OBSERVATION + PRODUCT_POLICY_PENDING — Lead 是否应 customer-unique 是产品语义问题，未明确前不是 Bug
- **影响**：客户身份分散，跨会话/跨平台身份不打通
- **处理**：等产品确认是否需要跨会话合并

## LOW

### ISSUE-M02-004 状态自由字符串无 DB 约束

- **位置**：models.py:164 status = Column(String(20))，无 CHECK/Enum
- **事实**：lead_service.update_lead_status 接受任意字符串，无校验无审计
- **影响**：可能写入非法状态值
- **建议**：加 DB CHECK 约束或代码层枚举校验

### ISSUE-M02-007 Feedback parse-and-persist 合同失败（已关闭）

- **位置**：app/routers/sales_feedback.py:37 + app/services/sales_feedback_parser.py
- **事实**：即使使用测试文件的正式字段格式，POST /sales-feedback/parse 仍返回 400。单元测试 parse_sales_feedback_text 直接调用 PASS，但 API 层 parse_and_persist_sales_feedback 失败。
- **关闭证据**：2-M04.2R2 Gate 6 进程内调用 parse_and_persist_sales_feedback（完整上下文: lead_id=11 + staff_id=1 + feedback_no=XGF-11-1 + 正式模板）→ parse_status=success, kind=lead_feedback, error=None
- **root cause**：earlier E2E fixture lacked DB/task context（API 层需要真实 lead_id+staff_id 关联的 DB 记录做上下文校验）
- **production contract defect**: NO
- **关闭位置**：M04 ACCEPTANCE.md + M04 ISSUES.md（引用同一证据）

### ISSUE-M02-005 状态变更无显式审计

- **位置**：reply_checker.py:45,102 改 status 但不写 LeadFollowupRecord
- **事实**：replied/timeout/closed 变更不写审计行，只能从 ReplyCheck 间接推断
- **影响**：无法直接追溯"谁在什么时候改了状态"
- **建议**：状态变更应统一写 LeadFollowupRecord

### ISSUE-M02-006 reassign_count 字段从未自增

- **位置**：models.py:173 reassign_count = Column(Integer, default=0)
- **事实**：全代码无任何自增操作；超时线索进 timeout 不触发重分配
- **影响**：无法统计线索被重分配次数；回收/重分配 NOT_IMPLEMENTED
- **建议**：如需回收重分配，需实现 reassign_count 自增 + 超时回收逻辑

## PLANNED_NOT_IMPLEMENTED

### PLANNED-M02-001 分配算法未实现项

| 算法维度 | 状态 |
|---|---|
| 权重分配 | NOT_IMPLEMENTED（无权重字段） |
| 优先级（高意向优先） | NOT_IMPLEMENTED（无优先级字段） |
| 每日上限 | NOT_IMPLEMENTED（无 daily limit 校验） |
| 超时自动回收/重分配 | NOT_IMPLEMENTED |
| 全员满额后权重随机 | NOT_IMPLEMENTED |

已实现：轮询 / 同级少者优先 / 商户隔离 / 跳过关闭分配 / 首次不重复

### PLANNED-M02-002 Lead 和 CustomerProfile 自动合并

- NOT_IMPLEMENTED（无 FK 关系、无自动同步写入）

## LEGACY（引用 LEGACY_REGISTER，不重新定性）

### LEGACY-M02-001 sync-leads 仍可写库

- **位置**：douyin_sync_service.py:190 _execute_create/_execute_update
- **Lifecycle**：LEGACY（引用 LEGACY_REGISTER LEGACY-005）
- **Runtime state**：still writable/reachable（dry_run=false 时按旧 source_id 逻辑写 Lead）
- **处理**：保持 LEGACY + still writable，不混用 DRIFT

## DRIFT（仅与正式文档/基线冲突时才加）

### DRIFT-M02-001 webhook 自动通知已禁用

- **位置**：douyin_webhook.py:1030 auto_notify_disabled
- **Runtime state**：DISABLED
- **事实**：webhook 自动建微信通知任务已阶段性禁用，只保留手动 send-to-staff
- **处理**：Runtime State=DISABLED，不标 LEGACY（auto_notify 是当前设计决策非旧方案替代）

## 总结

| 级别 | 数量 |
|---|---|
| BLOCKER | 0 |
| HIGH | 1（聚合键双轨制） |
| MEDIUM | 0 |
| 已关闭 | 1（ISSUE-M02-007 Feedback parse-and-persist，2-M04.2R2 Gate 6 E2E PASS） |
| POLICY_PENDING / CONTRACT_GAP | 1（手工 create 绕归并，待 E2E 升级条件） |
| ARCHITECTURE_OBSERVATION + PRODUCT_POLICY_PENDING | 1（同客户多会话多条 Lead） |
| LOW | 3（状态无约束 / 状态变更无审计 / reassign_count 未自增） |
| PLANNED_NOT_IMPLEMENTED | 2（分配算法未实现项 / Lead-CustomerProfile 合并） |
| LEGACY | 1（sync-leads 仍可写库，引用 LEGACY-005） |
| DRIFT | 1（webhook 自动通知已禁用，Runtime State=DISABLED） |
