# Phase 3-E3 Webhook Internal 部署灰度开关清单

更新时间：2026-06-22

## 1. 当前代码基线

本清单基于以下已完成提交：

- `36db461 feat: 支持webhook转发线索internal处理`
- `9e4e8a8 docs: 补充webhook internal灰度验收`

当前结论：

- 9000 正式 webhook 默认仍走本地 `process_webhook_event()`。
- `LEADS_WEBHOOK_INTERNAL_ENABLED` 默认关闭。
- 9202 internal webhook 已通过本地灰度验收。
- fallback enabled / disabled 均已验证。
- `/integrations/douyin/sync-leads` 未迁移。
- 19000、`input_writer`、微信 UI 自动化、抖音私信发送、`auto_send`、`manual_confirmed` 均未触碰。

## 2. 默认生产配置

生产默认不要打开 internal 转发。

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
LEADS_WEBHOOK_FALLBACK_LOCAL=true
```

说明：

- `LEADS_WEBHOOK_INTERNAL_ENABLED=false` 时，9000 继续本地处理公网 webhook。
- `LEADS_WEBHOOK_FALLBACK_LOCAL=true` 保持灰度保护能力，即使后续临时开启 internal，也能在 9202 不可用时回退本地处理。

## 3. Staging 灰度配置

staging 环境可显式开启 internal 转发：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=true
LEADS_WEBHOOK_FALLBACK_LOCAL=true
LEADS_SERVICE_BASE_URL=http://auto-wechat-leads:9202
LEADS_INTERNAL_TOKEN=<staging-secret>
```

检查点：

- `LEADS_INTERNAL_TOKEN` 必须为非空真实密钥。
- 9000 与 9202 必须配置同一个 internal token。
- `LEADS_SERVICE_BASE_URL` 必须使用内网服务名或内网地址，不使用公网域名。
- 首轮 staging 灰度必须保持 `LEADS_WEBHOOK_FALLBACK_LOCAL=true`。

## 4. 生产灰度前置条件

生产开启 internal 前必须逐项确认：

- 9202 服务健康，`/health` 返回正常。
- 9000 能通过内网访问 9202。
- `LEADS_INTERNAL_TOKEN` 已配置且不为空。
- 9202 `/api/leads/internal/webhook-events` 不能公网暴露。
- GMP / 抖音公网 webhook 地址仍指向 9000。
- 9000 的 `/webhook/douyin` 仍是公网 webhook 接入口。
- `verify_signature()` 仍在 9000 执行，不迁移到 9202。
- 9202 不配置 `DY_SECRET_KEY`。
- fallback 保持开启：`LEADS_WEBHOOK_FALLBACK_LOCAL=true`。
- E3-C / E3-D 回归测试已通过。
- 观察日志具备以下关键字：
  - `leads_internal_webhook_forward`
  - `leads_internal_webhook_fallback`
  - `leads_internal_webhook_failed`

## 5. 灰度步骤

建议按以下顺序执行：

1. 先以默认关闭配置部署。

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
LEADS_WEBHOOK_FALLBACK_LOCAL=true
```

2. 验证 9000 本地 webhook 正常。

- `/webhook/douyin` 返回旧 `WebhookResponse` 结构。
- `douyin_webhook_events` 正常写入。
- 有效线索正常进入 `douyin_leads`。
- duplicate 不重复生成线索。

3. 在 staging 显式开启 internal。

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=true
LEADS_WEBHOOK_FALLBACK_LOCAL=true
LEADS_SERVICE_BASE_URL=http://auto-wechat-leads:9202
LEADS_INTERNAL_TOKEN=<staging-secret>
```

4. 重启 9000，使配置生效。

5. 发送测试 webhook 到 9000。

- 优先使用已绑定账号的 `im_receive_msg` payload。
- 同时覆盖 `/webhook/douyin` 与 `/integrations/douyin/webhook`。

6. 验证 `douyin_webhook_events`。

- 9202 能写入事件。
- event key 幂等逻辑正常。
- duplicate audit event 正常记录。

7. 验证 `douyin_leads`。

- 有效线索能创建或更新。
- `merchant_id`、`account_open_id`、`conversation_short_id` 等关键字段正常。
- 商户端 `/api/leads` 只展示有效线索。

8. 验证 duplicate。

- 重复发送同一原始请求体。
- 第二次返回 `is_duplicate=true`。
- 第二次不重复生成有效线索。
- 第二次不触发 dry-run。

9. 验证 unbound_account。

- 使用未绑定账号 payload。
- 返回 `lead_action=unbound_account`。
- 只写审计事件，不生成有效线索。
- 不 fallback 到本地处理。

10. 验证 dry-run 不重复。

- 非重复 `im_receive_msg` 且存在 `event_id` 时，仍由 9000 调度 dry-run。
- duplicate event 不调度 dry-run。
- 9202 不触发 dry-run。
- `auto_send=false` 后置门禁保持不变。

11. 观察 fallback 日志。

- internal 成功时只出现 `leads_internal_webhook_forward`。
- 9202 不可用且 fallback 开启时出现 `leads_internal_webhook_fallback`。
- fallback disabled 只允许在专门验证窗口使用，生产首轮灰度禁止关闭 fallback。

## 6. 回滚步骤

快速回滚只需要关闭 9000 internal 开关：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
重启 9000
保持 GMP webhook 地址不变
不修改 DB
不停止 9202
```

回滚后验证：

- `/webhook/douyin` 继续由 9000 本地 `process_webhook_event()` 处理。
- 9000 日志不再出现 `leads_internal_webhook_forward`。
- `douyin_webhook_events` 与 `douyin_leads` 本地写入正常。
- duplicate 幂等仍正常。
- dry-run 仍只由 9000 调度。

禁止在快速回滚中执行：

- 不修改 webhook 公网地址。
- 不删除数据。
- 不执行 DB migration。
- 不停止 9202。
- 不修改 `verify_signature()`。

## 7. 观察指标

灰度期间至少观察以下指标：

- webhook 2xx 比例。
- 9202 internal 成功次数。
- 9202 internal 失败次数。
- fallback 次数。
- duplicate 数量。
- unbound_account 数量。
- 有效线索创建数量。
- 有效线索更新数量。
- dry-run 创建数量。
- dry-run duplicate skip 数量。

建议按入口区分：

- `/webhook/douyin`
- `/integrations/douyin/webhook`

建议按结果区分：

- `created`
- `updated`
- `duplicate_event`
- `unbound_account`
- `missing_conversation`
- `not_lead_event`

## 8. 禁止事项

灰度和生产部署期间禁止：

- 不在生产直接关闭 fallback。
- 不让 9202 暴露公网 webhook。
- 不把 `DY_SECRET_KEY` 配到 9202。
- 不迁移 `/integrations/douyin/sync-leads`。
- 不修改 19000 Local Agent。
- 不修改 `input_writer`。
- 不修改微信 UI 自动化。
- 不开启任何自动发送能力。
- 不放宽 `manual_confirmed=true`。
- 不放宽 `auto_send=false`。
- 不迁移 `verify_signature()`。
- 不修改公网 webhook path。
- 不做 DB model / migration 变更。

## 9. 建议验证命令

部署清单变更只需要执行：

```bash
docker compose -f docker-compose.dev.yml config --quiet
git diff --name-only
```

如后续进入 staging 灰度，建议额外执行 E3-D 中记录的 webhook internal 回归测试集。

## 10. 结论

生产默认仍应保持：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
LEADS_WEBHOOK_FALLBACK_LOCAL=true
```

staging 可在满足前置条件后开启 internal。生产首轮灰度必须保留 fallback，并保持公网 webhook 入口、验签、sync-leads、19000、微信 UI 自动化和自动发送边界不变。
