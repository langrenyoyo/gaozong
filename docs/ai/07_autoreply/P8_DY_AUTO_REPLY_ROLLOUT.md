# Phase 8-H 抖音自动回复上线与试点清单

## 阶段目标

Phase 8-H 的目标是把抖音自动回复从已完成的能力收口为一份可执行、可验收、可回滚的上线文档。

本阶段不改业务代码，不启动服务，不执行 migration，不触发 `send_msg`，只说明如何安全启用、如何试点、如何验收、如何回滚。

## 当前能力状态

当前 Phase 8 主链路已经具备以下能力：

- 多轮私信上下文进入 LLM prompt
- webhook 收到 `im_receive_msg` 后可进入 dry-run
- 自动回复配置与门禁已经落地
- `send_enabled=true` 后可进入真实自动发送候选
- 自动发送回调不会误判为人工接管
- 人工发送成功后会进入 manual takeover
- 前端不触发自动发送
- LLM 的 `auto_send` 不控制发送

## 架构链路

```text
im_receive_msg webhook
  -> douyin_webhook_events
  -> BackgroundTasks dry-run
  -> resolve webhook bound agent
  -> build conversation_history
  -> 9100 structured reply decision
  -> ai_reply_decision_logs
  -> ai_auto_reply_runs
  -> gates
  -> send_enabled=true?
  -> second-read gates
  -> send_msg
  -> douyin_private_message_sends
  -> im_send_msg callback matcher
  -> conversation_autopilot_state
```

## 迁移执行顺序

上线前 migration 必须按顺序执行：

1. `0015_ai_auto_reply_runs.sql`
2. `0016_douyin_account_autoreply_settings.sql`
3. `0017_conversation_autopilot_state.sql`
4. `0018_auto_reply_send_links.sql`

注意事项：

- `0018` 包含 `ALTER TABLE ADD COLUMN`
- SQLite 下重复执行会失败
- 上线前必须先备份数据库
- 先在测试库执行，再在生产库执行
- 本文档不执行 migration

## 配置开关语义

`douyin_account_autoreply_settings` 的推荐语义如下：

- `enabled`
- `dry_run_enabled`
- `send_enabled`
- `min_confidence`
- `require_rag`
- `require_rag_sources`
- `allowed_intents_json`
- `blocked_risk_flags_json`
- `max_replies_per_conversation_per_hour`
- `max_replies_per_account_per_hour`

明确约定：

- 无配置：`skipped/no_autoreply_settings`，不调用 9100
- `enabled=false`：`skipped/autoreply_disabled`
- `dry_run_enabled=false`：`skipped/dry_run_disabled`
- `send_enabled=false`：可 dry-run，不发送
- `send_enabled=true`：仅在全部门禁通过后才真实发送

## 推荐试点配置 SQL

### 第一阶段：dry-run

```sql
UPDATE douyin_account_autoreply_settings
SET
  enabled = 1,
  dry_run_enabled = 1,
  send_enabled = 0,
  min_confidence = 0.90,
  require_rag = 1,
  require_rag_sources = 1,
  allowed_intents_json = '["greeting","basic_info","business_scope_intro","lead_capture_soft_guide"]',
  blocked_risk_flags_json = '["price_commitment","inventory_commitment","finance_commitment","insurance_commitment","trade_in_commitment","contact_exchange","phone_or_wechat_detected","test_drive_or_visit","complaint_or_refund","prompt_injection","upstream_auto_send_requested"]',
  max_replies_per_conversation_per_hour = 1,
  max_replies_per_account_per_hour = 5,
  updated_at = CURRENT_TIMESTAMP
WHERE merchant_id = :merchant_id
  AND account_open_id = :account_open_id;
```

### 第二阶段：真实发送

```sql
UPDATE douyin_account_autoreply_settings
SET
  send_enabled = 1,
  updated_at = CURRENT_TIMESTAMP
WHERE merchant_id = :merchant_id
  AND account_open_id = :account_open_id;
```

## 推荐 allowed_intents / blocked_risk_flags

第一批只允许低风险意图：

- `greeting`
- `basic_info`
- `business_scope_intro`
- `lead_capture_soft_guide`

至少阻断以下高风险标记：

- `price_commitment`
- `inventory_commitment`
- `finance_commitment`
- `insurance_commitment`
- `trade_in_commitment`
- `contact_exchange`
- `phone_or_wechat_detected`
- `test_drive_or_visit`
- `complaint_or_refund`
- `prompt_injection`
- `upstream_auto_send_requested`

## 试点验收步骤

1. 确认企业号授权状态为 `bind_status=1`
2. 确认企业号已绑定 active Agent
3. 确认 Agent 分类与 RAG 生效
4. 先把 `send_enabled=0`
5. 发一条低风险私信
6. 查询 `ai_auto_reply_runs`
7. 查询 `ai_reply_decision_logs`
8. 确认 `gate_results_json`
9. 再开启 `send_enabled=1`
10. 再发一条低风险私信
11. 查询 `douyin_private_message_sends`
12. 确认 `manual_confirmed=0`、`auto_send=1`、`send_source=ai_auto`
13. 确认同一个 `trigger_event_key` 只跑一次
14. 确认同一个 `auto_reply_run_id` 只发一次
15. 确认 `im_send_msg` 回调没有进入 manual takeover
16. 确认人工发送会进入 manual takeover

## 验收 SQL

### 查 settings

```sql
SELECT *
FROM douyin_account_autoreply_settings
WHERE merchant_id = :merchant_id
  AND account_open_id = :account_open_id;
```

### 查最新 runs

```sql
SELECT *
FROM ai_auto_reply_runs
WHERE merchant_id = :merchant_id
  AND account_open_id = :account_open_id
ORDER BY created_at DESC
LIMIT 20;
```

### 查对应决策日志

```sql
SELECT *
FROM ai_reply_decision_logs
WHERE id = :decision_log_id;
```

### 查自动发送流水

```sql
SELECT *
FROM douyin_private_message_sends
WHERE auto_reply_run_id = :run_id
ORDER BY created_at DESC;
```

### 查会话接管状态

```sql
SELECT *
FROM conversation_autopilot_state
WHERE merchant_id = :merchant_id
  AND account_open_id = :account_open_id
ORDER BY updated_at DESC;
```

## 回滚策略

最快回滚：

```sql
UPDATE douyin_account_autoreply_settings
SET send_enabled = 0, updated_at = CURRENT_TIMESTAMP
WHERE merchant_id = :merchant_id
  AND account_open_id = :account_open_id;
```

更彻底的回滚：

```sql
UPDATE douyin_account_autoreply_settings
SET
  dry_run_enabled = 0,
  enabled = 0,
  updated_at = CURRENT_TIMESTAMP
WHERE merchant_id = :merchant_id
  AND account_open_id = :account_open_id;
```

说明：

- 不需要改代码即可关闭自动发送
- 已发送消息无法撤回，只能停止后续发送
- 不建议删除审计记录
- 不建议直接删表

## 风险边界

必须保持以下边界：

- 不自动重试
- 不批量发送
- 不绕过 24 小时窗口
- 不绕过最新消息二次读取
- 不绕过人工接管
- 不由 LLM `auto_send` 控制发送
- 前端没有自动发送入口
- 失败记录为 `send_failed`，不自动重试

## 常见问题

### 为什么配置后没有调用 9100？

可能是以下原因之一：

- 没有配置
- `enabled=false`
- `dry_run_enabled=false`

### 为什么 decided 但没发送？

可能是以下原因之一：

- `send_enabled=false`
- 二次门禁失败

### 为什么 blocked？

查看 `block_reason` 和 `gate_results_json`。

### 为什么人工发送后不自动回？

这是 `manual takeover` 生效的结果。

### 为什么 `im_send_msg` 没触发 dry-run？

这是设计要求。

## 提交建议

建议 commit message：

```text
docs: add Douyin auto reply rollout guide
```
