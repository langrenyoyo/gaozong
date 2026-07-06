# Phase 3-E3-B 9202 Internal Webhook Events 说明

更新时间：2026-06-22

## 本轮范围

本轮只新增 9202 `apps/leads` internal webhook-events 能力：

```text
POST /api/leads/internal/webhook-events
```

该接口用于承接 9000 已完成验签、已 JSON decode 的抖音 webhook payload，并在 9202 侧复用现有事件解析、幂等、原始事件入库和有效线索生成逻辑。

## 未切正式流量

本轮没有修改正式 9000 webhook 入口：

- `POST /webhook/douyin`
- `POST /integrations/douyin/webhook`

`verify_signature()` 仍在 9000 执行。9202 不接公网 webhook，不接收原始 `Authorization` 签名，不接收 `DY_SECRET_KEY`，也不读取原始 body 做验签。

## Internal 鉴权

9202 internal 接口要求：

1. `X-Internal-Token` 必须与 `LEADS_INTERNAL_TOKEN` 匹配。
2. `X-Gateway-Source-System` 必须为 `auto_wechat_gateway`。
3. 请求体 `signature_verified` 必须为 `true`。

生产前必须配置真实 `LEADS_INTERNAL_TOKEN`，不得使用空 token 作为生产调用凭据。

## 数据与边界

`merchant_id` 不信任前端或 payload 传入，仍通过 `DouyinAuthorizedAccount.open_id == payload.to_user_id` 且 `bind_status=1` 反查得到。

`account_open_id` 仍来自 payload 的 `to_user_id`。

`conversation_short_id` 仍来自 `content.conversation_short_id`。

以下场景只写 `douyin_webhook_events` 内部审计，不生成有效线索：

- `unbound_account`
- 未解析到可信 `merchant_id`
- 缺少 `conversation_short_id`
- 非文本消息
- duplicate event

商户侧 `/api/leads` 仍只查询 `douyin_leads`，不会返回未绑定账号事件、invalid 事件或 duplicate event。

## 明确不做

本轮不触发 AI 自动回复 dry-run 后台任务。

本轮不迁移 `/integrations/douyin/sync-leads`，不迁移 sync-leads 写库，不迁移 `auto_notify`、`auto_create_wechat_task` 或微信任务联动。

本轮不修改 19000 Local Agent，不修改 `input_writer` / 微信 UI 自动化，不修改抖音私信发送，不放宽 `manual_confirmed=true` 和 `auto_send=false` 边界。

本轮不修改 DB model / migration。

## 回滚方式

回滚时停用或不调用 9202 internal route / `LeadsClient.create_internal_webhook_event()` 即可。

正式 9000 webhook 尚未切流，因此回滚不会影响现有 `/webhook/douyin` 与 `/integrations/douyin/webhook` 正式链路。
