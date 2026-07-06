# P1-AUTOREPLY-ROLLOUT-WHITELIST-ACCEPTANCE

## 目标

本轮验收 9000 抖音 AI 客服自动回复真实发送前的配置链路，只确认配置、门禁、审计和回滚能力，不触发真实私信发送，不调用真实抖音发送上游，不调用真实 LLM。

前置任务 `P1-AUTOREPLY-DRYRUN-GATE-AUDIT-1` 已提交，提交为 `001166b fix: 收口自动回复dry-run与真实发送gate`。

## 配置项总表

| 配置项 | 默认值 | development 建议 | production 要求 | 风险 |
|---|---:|---|---|---|
| `DOUYIN_AUTO_REPLY_ENABLED` | `false` | 仅测试账号演练时显式设为 `true` | 必须经评审显式开启 | 总开关误开会让自动回复任务进入真实候选链路 |
| `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED` | `false` | 默认关闭；fake sender 测试不依赖真实上游 | 真实发送前必须显式开启，回滚时优先关闭 | 误开后如果其它 gate 也满足，可能触发真实发送 |
| `DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT` | `false` | 禁止开启，优先使用白名单 | 生产全量放开必须单独评审和变更记录 | 跳过全局白名单后影响面扩大 |
| `DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST` | 空 | 只填测试企业号 `open_id` | 非 full rollout 下必须显式配置目标账号 | 配错账号会阻断或误放行 |
| `DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST` | 空 | 只填测试客户 `open_id` | 非 full rollout 下需命中客户或会话白名单之一 | 配成全量或混入真实客户会扩大范围 |
| `DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST` | 空 | 只填测试会话 `short_id` | 非 full rollout 下需命中客户或会话白名单之一 | 会话 ID 丢失时无法进入真实候选 |
| 账号 `enabled` | `false` | 测试账号显式开启 | 仅允许托管账号开启 | 账号关闭时必须阻断 |
| 账号 `send_enabled` | `false` | fake sender 正向验收时显式开启 | 真实发送账号必须逐个开启 | 账号级最快细粒度回滚入口 |
| 账号客户/会话白名单 | 空 | 如需更窄范围再配置 | 配置后作为账号级收窄条件 | 命中全局白名单也不能绕过账号级收窄 |

## 默认安全性

未配置时，`DOUYIN_AUTO_REPLY_ENABLED=false`、`DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED=false`、`DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT=false`，全局白名单为空，账号 `enabled=false` 且 `send_enabled=false`。因此未显式配置不会真实发送。

`.env.example` 已提供安全默认值和空白名单示例，不包含真实 Douyin、NewCar、Milvus 凭据。

## Rollout 与白名单关系

`full rollout=false` 时必须同时满足：

1. 全局总开关开启。
2. 真实发送开关开启。
3. 企业号命中 `DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST`。
4. 客户命中 `DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST`，或会话命中 `DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST`。
5. 账号 `enabled=true` 且 `send_enabled=true`。
6. 账号绑定 active Agent。
7. RAG、LLM 后置 gate、人工接管、最新消息、send context 等安全门禁全部通过。

`full rollout=true` 时只跳过全局白名单要求，不跳过全局开关、真实发送开关、账号开关、Agent 绑定、账号级白名单收窄、RAG、人工接管、最新消息和 send context。

白名单命中只代表通过 rollout gate，不代表必发。

## 正向放行条件

正向 fake sender 测试覆盖以下条件：

- `rag_enabled=true`
- `allowed_category_keys=["base"]`
- RAG 命中 `source_chunks`
- `source_chunks_count > 0`
- fake 9100 返回 `auto_send=true`、`manual_required=false`
- 全局自动回复开关开启
- 全局真实发送开关开启
- 账号 `enabled=true`
- 账号 `send_enabled=true`
- rollout / whitelist 命中
- 会话未人工接管
- send context 合法
- `dry_run=false`
- 使用 mock 的抖音发送调用

验收结果：`run.mode=real_send_candidate`，`send_gate_passed=true`，`blocked_reason` 为空，mock sender 调用一次，未调用真实上游。

## 阻断条件

已覆盖的主要阻断原因：

| 场景 | 阻断原因 |
|---|---|
| 全局自动回复关闭 | `global_auto_reply_disabled` |
| 全局真实发送关闭 | `global_real_send_disabled` |
| 企业号未命中全局白名单 | `global_account_whitelist_missed` |
| 客户和会话均未命中全局白名单 | `global_customer_or_conversation_whitelist_missed` |
| 账号配置缺失 | `no_autoreply_settings` |
| 账号 `enabled=false` | `account_settings_disabled` |
| 账号 `send_enabled=false` | `account_send_disabled` |
| 未绑定 active Agent | `no_bound_agent` / dry-run 前置链路为 `agent_not_bound` |
| LLM 要求人工 | `manual_required` |
| 风险标记存在 | `risk_flags` |
| RAG 未使用 | `rag_not_used` |
| RAG 来源为空 | `rag_sources_empty` |
| fallback / direct LLM 降级 | `fallback_reason` 或对应 post gate 阻断 |
| 置信度不足 | `confidence_low` |
| 人工接管 | `manual_takeover_blocked` |
| 最新消息不是客户消息 | `latest_message_not_customer` |
| send context 不可用 | `send_context_unavailable` |

## 审计可观测性

运行记录和决策日志可观察：

- `run.mode`：`dry_run` / `real_send_candidate`
- `run.status`：`decided` / `blocked` / `send_skipped` / `sent` / `send_failed`
- `run.block_reason`
- `gate_results.post_llm.final_auto_send`
- `gate_results.post_llm.fallback_reason`
- `gate_results.post_llm.rag_used`
- `gate_results.post_llm.rag_sources_count`
- `gate_results.post_llm.source_chunks_count`
- `gate_results.real_send.send_gate_passed`
- `gate_results.real_send.blocked_reason`
- `gate_results.real_send.global.allow_full_rollout`
- `gate_results.real_send.global.account_whitelist_hit`
- `gate_results.real_send.global.customer_whitelist_hit`
- `gate_results.real_send.global.conversation_whitelist_hit`
- `gate_results.real_send.settings.enabled`
- `gate_results.real_send.settings.send_enabled`

本轮补充：真实发送 gate 阻断时也会把 `real_send` 审计快照写入 `gate_results_json`，便于区分全局开关、白名单、账号开关、Agent 绑定等阻断点。

## 回滚方案

最快回滚：

1. 将 `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED=false`，立即阻断真实发送调用。
2. 将目标账号 `send_enabled=false`，只关闭单个企业号真实发送。
3. 将会话切为人工接管，阻断该会话继续自动发送。

更稳妥回滚：

1. 将 `DOUYIN_AUTO_REPLY_ENABLED=false`，关闭自动回复总链路。
2. 清空 `DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST` / `DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST` / `DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST`。
3. 将 `DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT=false`。
4. 将账号 `enabled=false`，关闭账号托管。

推荐顺序：先关真实发送总开关，再关账号 `send_enabled`，最后清理白名单和 full rollout。

## 验收测试结果

已执行：

```bash
python -m pytest tests/test_ai_auto_reply_dry_run.py tests/test_ai_auto_reply_send_service.py tests/test_douyin_autoreply_settings_api.py tests/test_douyin_autoreply_settings_service.py -q
```

结果：`100 passed`。存在 FastAPI / Starlette 既有弃用警告，不影响本轮验收。

## 未改内容

- 未触发真实私信发送。
- 未调用真实抖音发送上游。
- 未调用真实 LLM。
- 未连接真实 Milvus 做训练或检索。
- 未修改 9000 对外接口 schema。
- 未修改 NewCar、live-check、Local Agent、19000。
- 未放宽现有 dry-run / real-send gate。

## 下一步真实演练

可以进入真实测试账号演练的前提：

1. 仅使用甲方确认的测试企业号、测试客户或测试会话。
2. 显式配置全局开关、真实发送开关和对应白名单。
3. 账号 `enabled=true` 且 `send_enabled=true`。
4. 使用已验证的测试账号绑定 Agent 和知识范围。
5. 演练前确认最快回滚入口可操作。
