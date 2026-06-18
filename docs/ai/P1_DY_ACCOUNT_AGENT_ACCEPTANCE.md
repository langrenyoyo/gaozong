# P1-DY-ACCOUNT-AGENT 抖音企业号绑定智能体一期验收收口

更新时间：2026-06-18

## 1. 阶段结论

`P1-DY-ACCOUNT-AGENT` 一期链路已完成并验收通过。

完整链路：

```text
前端企业号绑定控件
  → 9000 权威绑定表
  → 9000 读取真实 AiAgent
  → 9000 注入可信 agent_config
  → 9100 使用真实 agent_config 生成回复建议
```

一期行为：一个抖音企业号绑定一个 active 默认智能体。

## 2. 核心提交

| 提交 | 用途 |
|------|------|
| `d33620d78520ba743c4eeee3ef4158a27fa98513` | 实现抖音企业号绑定智能体后端基础能力 |
| `9dc3b2a2318cf890788ee44673ca6f16ac977d31` | 接入抖音企业号绑定智能体前端控件 |
| `8d4fc40f57b51121a5b86dcfa4195dbc138045b4` | 解除 9100 正式回复建议对 mock 绑定依赖 |
| `fc8c1bebc23901767bf3662c2d68e5787c716d63` | 代理注入真实智能体配置到 9100 |

## 3. 数据模型

`douyin_account_agent_bindings` 是正式绑定表。

数据语义：

1. 一个企业号同一时间只有一个 `active` 默认智能体。
2. `douyin_authorized_accounts.merchant_id` / `tenant_id` 用于账号归属。
3. `bind_status=1` 表示授权有效。
4. `bind_status=0` 表示本地取消授权。
5. `bind_status=4` 表示本地软删除。
6. 取消授权后 binding 标记为 `invalid`，`invalid_reason=account_unauthorized`。
7. 删除企业号后 binding 标记为 `deleted`，`invalid_reason=account_deleted`。

## 4. 接口契约

企业号与绑定接口：

1. `GET /integrations/douyin/accounts`
2. `PUT /integrations/douyin/accounts/{account_open_id}/agent-binding`
3. `DELETE /integrations/douyin/accounts/{account_open_id}/agent-binding`
4. `POST /integrations/douyin/accounts/{account_open_id}/cancel-authorization`
5. `DELETE /integrations/douyin/accounts/{account_open_id}`

回复建议接口：

1. `POST /integrations/douyin-ai-cs/conversations/{conversation_id}/reply-suggestion`

## 5. 9000 / 9100 边界

9000 负责：

1. 作为企业号绑定智能体的唯一权威源。
2. 校验企业号归属。
3. 校验企业号授权状态。
4. 校验 Agent 归属。
5. 校验 Agent active 状态。
6. 校验 `douyin_account_agent_bindings` active 绑定关系。
7. 校验通过后读取真实 `AiAgent`。
8. 向 9100 注入可信 `agent_id` / `agent_config`。

9000 不做：

1. 不信任前端传入的 `merchant_id`。
2. 不信任前端传入的 `agent_config`。
3. 不把前端临时选择值当成正式绑定。

9100 负责：

1. 消费 9000 注入的可信 `agent_id` / `agent_config`。
2. 使用真实 `agent_name`、`system_prompt`、`knowledge_base_text` 生成回复建议。
3. 在无 `agent_config` 但有 `agent_id` 时保留 `agent_config_missing_fallback`。

9100 不做：

1. 不直接读取 9000 数据库。
2. 不使用 mock `ACCOUNT_AGENT_BINDINGS` 拦截正式链路。
3. 不负责绑定校验。

`mock_workbench_service` 仅保留 demo 用途。

## 6. 安全边界

必须保持：

1. `auto_send=false`，9000 和 9100 双保险。
2. 不自动发送微信。
3. 不自动发送抖音私信。
4. 不引入 LangChain。
5. 不接 Agent tools。
6. 取消授权后不能继续生成建议。
7. 删除企业号后不能继续生成建议。
8. Agent disabled 或 deleted 后不能继续生成建议。

## 7. 测试汇总

已记录通过：

1. 前端 build 通过，仅有既有字体解析和 chunk 体积警告。
2. 9000 proxy 测试：`14 passed`。
3. 9100 app 测试：`12 passed`。
4. 9100 专项测试：`39 passed`。
5. 早期后端绑定、账号归属、取消授权、删除企业号、绑定生命周期相关测试均已通过。

## 8. 后置项

1. 真实上游取消授权能力暂未接入，当前 `upstream_cancel_supported=false`。
2. RAG scope 当前仍偏 `tenant_id + merchant_id + douyin_account_id`，后续可升级为 `merchant_id + account_open_id + agent_id`。
3. 真实联调需要有效授权企业号、真实 `AiAgent`、真实会话数据。
4. 需要在后续文档继续保持 9000 / 9100 边界说明。
5. 不建议在一期继续扩展 LangChain、Agent tools 或自动发送。
