# P1-AUTOREPLY-TEST-ACCOUNT-REHEARSAL-PRECHECK

## 1. 测试账号范围

本轮没有进入真实测试账号发送演练，只做演练前置检查、fake sender / dry-run 验证、配置可见性和回滚验证。

当前自动化测试使用 synthetic fixture：

| 项目 | 脱敏记录 |
|---|---|
| merchant_id | `merchant-test` |
| account_open_id | `acco...test` |
| 企业号名称 | `测试企业号` |
| customer_open_id | `cust...test` |
| conversation_short_id | `conv...test` |
| Agent 绑定 | 已绑定 synthetic active Agent |
| Agent RAG | 以已有 fake RAG / fake LLM 测试结果为准 |
| allowed_category_keys | 包含 `base` 的既有 RAG 测试覆盖 |
| 测试知识 | synthetic 非业务知识，不使用真实客户数据 |

真实测试对象尚未写入本文档。进入真实演练前，管理员只应在控制台或部署环境中查看完整 ID，报告中继续只使用脱敏摘要。

## 2. env fuse 状态

本轮建议状态：

| 配置 | 建议 | 本轮检查口径 |
|---|---|---|
| `DOUYIN_AUTO_REPLY_ENABLED` | 可按测试环境设为 true | 只输出布尔状态 |
| `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED` | 保持 false | 作为最高真实发送熔断 |
| `DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT` | 保持 false | 禁止全量放开 |
| env 企业号白名单 | 可配置测试账号 | 不输出原始值 |
| env 客户 / 会话白名单 | 可配置测试客户或会话 | 不输出原始值 |

自动化回归已覆盖：即使 DB 配置全开，只要 env 真实发送熔断关闭，真实发送 gate 仍返回 `global_real_send_disabled`。

## 3. DB rollout 状态

演练前 DB 管理层应满足：

| 项目 | 预期 |
|---|---|
| DB auto_reply_enabled | true |
| DB real_send_enabled | 可配置；本轮不要求真实发送 |
| DB allow_full_rollout | false |
| DB 企业号白名单 | 测试企业号命中 |
| DB 客户或会话白名单 | 测试客户或测试会话命中 |
| 企业号 enabled | true |
| 企业号 send_enabled | true |

自动化回归已覆盖 DB 白名单命中时 gate 可通过，也覆盖 DB 真实发送关闭、账号发送关闭、客户/会话白名单移除后的阻断结果。

## 4. 白名单命中状态

本轮 fake precheck fixture：

| 白名单类型 | 命中状态 |
|---|---|
| env 企业号白名单 | 命中 |
| env 客户白名单 | 命中 |
| DB 企业号白名单 | 命中 |
| DB 客户白名单 | 命中 |
| DB 会话白名单 | 未使用；客户白名单已满足 |

full rollout 保持 false。白名单命中只代表通过 rollout gate，不代表必发；后续仍需 account、Agent、RAG、post gate、人工接管、最新消息、send context 等门禁全部通过。

## 5. RAG 命中前置

本轮未连接真实 Milvus，不训练真实知识，不调用真实 LLM。

RAG 前置沿用已完成的 synthetic canary 和 fake workflow 验证：

| 检查项 | 状态 |
|---|---|
| Milvus synthetic canary E2E | 已在前置任务通过 |
| RAG workflow fake Milvus / fake LLM | 已在前置任务通过 |
| source_chunks_count > 0 | 由 dry-run 正向测试覆盖 |
| rag_used=true | 由 dry-run 正向测试覆盖 |
| fallback_reason 为空 | 由 dry-run 正向测试覆盖 |
| direct LLM fallback 当作 RAG 命中 | 禁止 |

真实演练前必须确认测试知识为 synthetic 非业务知识，并能在 dry-run 中命中 source_chunks。

## 6. dry-run 验证结果

本轮使用既有 dry-run 测试覆盖：

| 场景 | 预期 |
|---|---|
| dry_run_enabled=true | 生成 dry_run，不调用发送服务 |
| fake 9100 返回 RAG 命中 | 记录 rag_used、rag_sources/source_chunks |
| upstream auto_send=true 但 dry-run 模式 | 不调用发送服务 |
| RAG miss / fallback / manual_required | 阻断或保持非发送 |

结果口径：dry-run 只能作为候选决策与审计观察，不触发真实发送。

## 7. fake sender 正向验证结果

既有测试 `test_real_send_mode_all_gates_pass_calls_fake_sender_once` 覆盖正向路径：

| 条件 | 状态 |
|---|---|
| env / DB / account / whitelist 满足 | 是 |
| fake 9100 返回 auto_send=true | 是 |
| manual_required=false | 是 |
| RAG 命中且 source_chunks_count > 0 | 是 |
| fake sender 调用一次 | 是 |
| 真实上游发送 | 未触发 |
| run 状态 | `sent` 或等价 fake sent |
| send_gate_passed | true |

该测试只使用 mock 发送上游，不调用真实抖音发送接口。

## 8. 回滚验证结果

至少 3 个回滚入口已由本轮 precheck 测试或既有发送服务测试覆盖：

| 回滚入口 | 预期 blocked_reason |
|---|---|
| DB real_send_enabled=false | `db_real_send_disabled` |
| account send_enabled=false | `account_send_disabled` |
| 移除 DB 客户/会话白名单 | `db_customer_or_conversation_whitelist_missed` |
| env real send fuse=false | `global_real_send_disabled` |

最快回滚：关闭 env 真实发送熔断或 DB real_send_enabled。
最细粒度回滚：关闭单个企业号 send_enabled 或移除测试白名单。

## 9. 前端控制台可见性

控制台路径：

```text
/admin/autoreply-rollout
```

本轮检查点：

| 项目 | 状态 |
|---|---|
| summary 展示 env fuse 布尔状态 | 已有静态脚本覆盖 |
| DB config 展示 | 已有静态脚本覆盖 |
| whitelist 脱敏展示 | 后端 API 测试覆盖 |
| runs 展示 blocked_reason / send_gate_passed / rollout 快照 | 后端 API 测试覆盖 |
| 一键暂停 DB 真实发送入口 | 已有静态脚本覆盖 |
| full rollout 二次确认 | 已有静态脚本覆盖 |
| 危险发送绕过能力 | 未提供 |

前端控制台不调用真实发送入口，只写 DB 管理层配置和白名单。

## 10. 未触发真实发送确认

本轮确认：

- 未调用真实抖音发送上游。
- 未调用真实 LLM。
- 未连接真实 Milvus。
- 未触发 reply-suggestion 真实发送。
- 未触发 auto-reply 真实发送。
- 未改真实发送 gate。
- 真实发送演练：未进入。

## 11. 是否可以进入真实测试账号演练

当前结论：可以进入下一轮真实测试账号演练前的人工配置确认，但不建议直接放开真实发送。

进入下一任务前必须由人工确认：

1. 测试企业号、测试客户或测试会话均为甲方允许的测试范围。
2. 测试知识为 synthetic 非业务知识。
3. env 真实发送熔断开启时有明确回滚负责人。
4. 管理员控制台能看到目标账号、白名单、run 审计和 blocked_reason。
5. 真实发送演练只对单账号、单客户或单会话执行。

## 12. 真实演练建议步骤

建议下一轮 `P1-AUTOREPLY-TEST-ACCOUNT-REAL-SEND-REHEARSAL-1` 按以下顺序执行：

1. 使用控制台确认 DB real_send_enabled=false 时 sender 不调用。
2. 使用测试会话执行 dry-run，确认 RAG 命中、fallback_reason 为空。
3. 使用 fake sender 再跑一次正向候选，确认 send_gate_passed=true。
4. 人工确认测试账号和回滚入口。
5. 短时间开启 env 真实发送熔断和 DB real_send_enabled。
6. 只对单条 synthetic 测试消息执行真实发送演练。
7. 立即关闭 DB real_send_enabled，并检查 run、send record、blocked/sent 审计。
