# M07 真实运行链路

> source_baseline: c26ec227e70d | 所有链路附 file:line 证据

## 1. 算力全链路（record_usage → 计费 → 余额扣减）

```
业务调用方 record_usage(db, merchant_id, tokens, *, capability_key, source, model, ...)
  → apps/compute/services.py:537-622
  → get_or_create_account(db, merchant_id) (:554) — 一商户一行(UniqueConstraint)
  → 按 capability_key 查唯一上浮比例行 ComputeMarkupRatio (:585-591)
  → calculate_billed_tokens(tokens, ratio) (:598)
  → _write_transaction(db, account, delta_tokens=-billed_tokens, ...) (:600-604)
    → with_for_update() 行锁 (:178-183)
    → new_balance = locked.balance_tokens + delta_tokens (:186)
    → BIGINT 范围校验 (:187-188)
    → 负余额写 warning 不阻断 (:189-197)
    → 更新 balance_tokens (:198)
    → 写 ComputeTransaction(balance_after_tokens 快照) (:205)
  → db.commit() (:620) — 单次顶层 commit

Table: ComputeAccount + ComputeTransaction
```

## 2. 算力上报触发点清单（6 个）

| # | 触发事件 | 调用方 | capability_key | 证据 |
|---|---|---|---|---|
| 1 | 抖音线索私信入站 | douyin_webhook.py:1240-1253 | leads | source=other, tokens=字符数//2 估算 |
| 2 | 微信助手 paste_only 完成 | wechat_task_service.py:430 | wechat-assistant | |
| 3 | 微信助手 single_send sent 完成 | wechat_task_service.py:462 | wechat-assistant | |
| 4 | AI 剪辑素材分析 | material_analysis.py:251-264 | ai_edit | source=llm, 方舟多模态 |
| 5 | LAS 混剪归档成功 | ai_edit_las_service.py:186 | ai_edit | source=other, tokens=len(script)//2 |
| 6 | 9100 HTTP 上报 | compute_usage_client.py:199 → 9000 /internal/compute/usage → compute.py:467 | 由 9100 传入 | douyin-cs |

## 3. 充值（mock）

```
create_mock_recharge_order(db, merchant_id, tokens, pay_method)
  → apps/compute/services.py:669-719
  → 生成 order_no=CO{uuid}, pay_qr_code=mock://pay/{method}, status=mock_completed (:692,715-716)
  → 写一条 recharge 流水 (delta_tokens=+tokens) (:697-705)
  → commit → 余额立即增加 (:706)
  → 注意：docstring说"不实际到账不改余额"但实现实际改余额（矛盾）
```

## 4. 六能力上浮比例

```
ComputeMarkupRatio (models.py:1408-1429)
  → UniqueConstraint(capability_key) — 六能力每能力一行 (:1413)
  → consumption_mode: actual（按真实tokens计费）/ custom（固定tokens_per_call）(:1426-1427)
  → calculate_billed_tokens 按 mode 计算 (:598)
  → 六能力: douyin-cs/leads/agents/wechat-assistant/ai_edit/compute (apps/compute/services.py:41-49)
```
