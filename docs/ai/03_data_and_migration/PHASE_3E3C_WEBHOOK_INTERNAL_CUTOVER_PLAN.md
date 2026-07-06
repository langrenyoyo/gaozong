# Phase 3-E3-C 9000 调用 9202 Internal Webhook 切流方案

更新时间：2026-06-22

## 1. 本阶段范围

本阶段是 Phase 3-E3-C-Plan，只做只读方案细化，不修改代码、不提交、不改变正式 webhook 行为。

基线提交：`ae1f507 feat: 新增线索internal webhook事件处理接口`

已具备的基础能力：

- 9202 已新增 `POST /api/leads/internal/webhook-events`。
- 9202 internal 接口接收 9000 已验签、已 JSON decode 的 webhook payload。
- 9202 internal 响应字段与 9000 `WebhookResponse` 核心字段兼容。
- 9202 internal 只处理事件入库与有效线索生成，不触发 AI 自动回复 dry-run。
- 9000 正式入口 `/webhook/douyin` 与 `/integrations/douyin/webhook` 仍共用 `_handle_douyin_webhook()`。

本阶段明确不做：

- 不修改 `verify_signature()`。
- 不修改 `/webhook/douyin` 或 `/integrations/douyin/webhook` 当前行为。
- 不修改 `/integrations/douyin/sync-leads`。
- 不修改 DB model / migration。
- 不修改 19000 Local Agent、`input_writer`、微信 UI 自动化。
- 不修改抖音私信发送。
- 不放宽 `manual_confirmed=true` / `auto_send=false` 安全边界。

## 2. 当前真实调用链

当前 9000 正式 webhook 链路：

```text
抖音/GMP
  -> 9000 /webhook/douyin 或 /integrations/douyin/webhook
  -> app/routers/integrations.py::_handle_douyin_webhook()
  -> 读取原始 body
  -> 按 APP_ENV / DOUYIN_WEBHOOK_AUTH_REQUIRED 判断是否调用 verify_signature()
  -> JSON decode
  -> app.integrations.douyin_webhook.process_webhook_event(db, payload)
  -> db.commit()
  -> im_receive_msg + 非重复 + event_id 存在时，追加 run_ai_auto_reply_dry_run(event_id)
  -> 返回 app.schemas.WebhookResponse
```

当前 9202 internal 链路：

```text
9000 或测试 client
  -> 9202 POST /api/leads/internal/webhook-events
  -> 校验 X-Internal-Token
  -> 校验 X-Gateway-Source-System=auto_wechat_gateway
  -> 校验 request.signature_verified=true
  -> apps.leads.webhook_events.process_internal_webhook_event(db, payload)
  -> db.commit()
  -> 返回 InternalWebhookEventResponse
```

关键事实：

- `verify_signature()` 仍只适合放在 9000，因为它依赖原始 body、`X-Auth-Timestamp`、`Authorization` 和 9000 的 `DY_SECRET_KEY`。
- 9202 不接公网 webhook，不读取公网签名，不持有 `DY_SECRET_KEY`。
- 9202 当前明确不触发任何后置 dry-run。
- dry-run 当前由 9000 `_handle_douyin_webhook()` 调度，实际执行函数为 `app.services.ai_auto_reply_dry_run_service.run_ai_auto_reply_dry_run()`。

## 3. 需要新增哪些配置项？

建议沿用 Phase 3-E3-A 评审中已有配置口径，避免产生第二套开关。

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
LEADS_SERVICE_BASE_URL=http://127.0.0.1:9202
LEADS_INTERNAL_TOKEN=
LEADS_CLIENT_TIMEOUT_SECONDS=5
LEADS_WEBHOOK_FALLBACK_LOCAL=true
```

配置含义：

| 配置项 | 默认值 | 作用 |
| --- | --- | --- |
| `LEADS_WEBHOOK_INTERNAL_ENABLED` | `false` | 9000 webhook 是否在验签后调用 9202 internal。默认关闭，保证正式行为不变。 |
| `LEADS_SERVICE_BASE_URL` | `http://127.0.0.1:9202` | 9000 调用 9202 的服务地址，已被 `LeadsClient.from_env()` 使用。 |
| `LEADS_INTERNAL_TOKEN` | 空 | 9000 调用 9202 internal 的服务间凭据。生产必须配置非空真实值。 |
| `LEADS_CLIENT_TIMEOUT_SECONDS` | `5` | 9000 调用 9202 的超时时间，已被 `LeadsClient.from_env()` 使用。 |
| `LEADS_WEBHOOK_FALLBACK_LOCAL` | `true` | 9202 不可用或响应异常时，9000 是否回退本地 `process_webhook_event()`。灰度期建议开启。 |

生产建议：

- `LEADS_INTERNAL_TOKEN` 生产不得为空。
- `LEADS_WEBHOOK_INTERNAL_ENABLED=true` 只能在 9202 健康检查、internal 鉴权和回归测试通过后开启。
- 灰度期保留 `LEADS_WEBHOOK_FALLBACK_LOCAL=true`。
- 稳定后如要关闭 fallback，应单独进入后续阶段评审，不在 E3-C 首次切流中关闭。

## 4. 9000 哪个函数中插入 internal client 调用最小风险？

最小风险插入点是 `app/routers/integrations.py::_handle_douyin_webhook()` 中 JSON decode 成功之后、当前 `process_webhook_event(db, payload)` 调用之前。

推荐位置：

```text
_handle_douyin_webhook()
  -> 完成 auth_required 判断
  -> 如需验签，完成 verify_signature()
  -> json.loads(body.decode("utf-8")) 得到 payload
  -> 记录 webhook 接收日志
  -> 根据 LEADS_WEBHOOK_INTERNAL_ENABLED 分支：
       true  -> 调用 LeadsClient.create_internal_webhook_event(...)
       false -> 调用本地 process_webhook_event(db, payload)
  -> 根据统一 result 构造 WebhookResponse
```

理由：

- 两个正式路径已经共用 `_handle_douyin_webhook()`，在这里插入可以天然保证 `/webhook/douyin` 与 `/integrations/douyin/webhook` 行为一致。
- 验签和 JSON decode 已完成，不需要 9202 接触原始 body 或公网签名。
- 返回 `WebhookResponse` 的现有位置不变，外部响应契约不变。
- dry-run 当前也在该函数内调度，切流后仍可集中控制，避免 9000 和 9202 双触发。

不建议的插入点：

- 不建议在两个路由函数 `douyin_webhook()` / `douyin_webhook_legacy()` 分别写分支，否则容易导致双入口行为漂移。
- 不建议在 `process_webhook_event()` 内部调用 9202，否则会让本地 fallback 和 internal 调用互相递归或边界混乱。
- 不建议让 9202 直接处理原始 request body 和签名。

## 5. 9202 返回结构如何映射回现有 WebhookResponse？

9202 `InternalWebhookEventResponse` 当前字段：

```text
code
msg
event_id
lead_id
is_new_lead
is_duplicate
lead_action
```

9000 `WebhookResponse` 当前字段：

```text
code
msg
event_id
lead_id
is_new_lead
is_duplicate
lead_action
```

建议一一映射：

| 9202 字段 | 9000 `WebhookResponse` 字段 | 说明 |
| --- | --- | --- |
| `code` | `code` | 默认 `0`。如 9202 返回非 2xx，9000 不直接透出 9202 原始错误，按 fallback 或 5xx 策略处理。 |
| `msg` | `msg` | 默认 `success`。 |
| `event_id` | `event_id` | 9202 写入 `douyin_webhook_events` 后生成的事件 ID。 |
| `lead_id` | `lead_id` | 有效线索生成或命中的线索 ID；无有效线索时为 `null`。 |
| `is_new_lead` | `is_new_lead` | 9202 `lead_action == created` 时通常为 `true`。 |
| `is_duplicate` | `is_duplicate` | duplicate event 为 `true`。 |
| `lead_action` | `lead_action` | 保留 9202 结果，如 `created`、`updated`、`skipped`、`duplicate_event`、`unbound_account`、`missing_conversation`。 |

建议 9000 内部统一成一个 `result` 字典后再构造 `WebhookResponse`：

```text
result = internal_result 或 local_result
WebhookResponse(
    code=result.get("code", 0),
    msg=result.get("msg", "success"),
    event_id=result.get("event_id"),
    lead_id=result.get("lead_id"),
    is_new_lead=bool(result.get("is_new_lead")),
    is_duplicate=bool(result.get("is_duplicate")),
    lead_action=result.get("lead_action") or "not_lead_event",
)
```

注意：

- 9202 返回业务成功但 `lead_id=None` 是合法情况，例如 `unbound_account`、`missing_conversation`、非线索事件。
- 9202 返回 `is_duplicate=true` 仍应给抖音/GMP 返回 200 成功，保持 webhook 幂等语义。

## 6. 9202 不可用时如何 fallback 到本地 process_webhook_event？

推荐 fallback 策略：

```text
if LEADS_WEBHOOK_INTERNAL_ENABLED=false:
    result = process_webhook_event(db, payload)
    db.commit()
else:
    try:
        result = LeadsClient.from_env().create_internal_webhook_event(...)
    except LeadsClientError / TimeoutError / OSError / invalid response:
        if LEADS_WEBHOOK_FALLBACK_LOCAL=true:
            result = process_webhook_event(db, payload)
            db.commit()
        else:
            raise HTTPException(status_code=502, detail="leads internal webhook unavailable")
```

fallback 触发条件建议包含：

- 连接失败。
- 超时。
- 9202 返回非 2xx。
- 9202 返回非法 JSON。
- 9202 响应缺少核心字段，无法映射 `WebhookResponse`。

日志要求：

- internal 调用成功：记录 `stage=leads_internal_webhook_forward`、`source_path`、`event`、`event_id`、`lead_id`、`lead_action`、`is_duplicate`。
- internal 调用失败且 fallback：记录 `stage=leads_internal_webhook_fallback`、`failure_stage`、错误类型、`source_path`、`event`。
- internal 调用失败且不 fallback：记录 `stage=leads_internal_webhook_failed`、`failure_stage`、错误类型。

事务边界：

- 9000 调用 9202 成功时，事件和线索写入发生在 9202 的 DB 会话中，9000 不应再执行本地 `db.commit()`。
- fallback 到本地时，保持当前行为：本地 `process_webhook_event(db, payload)` 后 `db.commit()`。
- 由于当前阶段仍共享 DB / model，不做 migration，fallback 不涉及结构回滚。

灰度期建议：

- 默认开启 fallback。
- 观察 fallback 次数，一旦出现持续 fallback，不应继续扩大流量。
- 禁止在一次请求中先由 9202 成功写库后又 fallback 本地写库。只有在 internal 调用明确失败或无有效响应时才 fallback。

## 7. AI 自动回复 dry-run 后台任务现在在哪里触发？

当前触发点在 `app/routers/integrations.py::_handle_douyin_webhook()`：

```text
result = process_webhook_event(db, payload)
db.commit()
if (
    background_tasks is not None
    and payload.get("event") == "im_receive_msg"
    and result.get("is_duplicate") is not True
    and result.get("event_id") is not None
):
    background_tasks.add_task(run_ai_auto_reply_dry_run, result["event_id"])
```

实际 dry-run 编排函数是：

```text
app.services.ai_auto_reply_dry_run_service.run_ai_auto_reply_dry_run(event_id)
```

该服务内部还有第二层去重：

```text
AiAutoReplyRun.trigger_event_key == DouyinWebhookEvent.event_key
```

如果同一事件已经有 run，会记录 duplicate 并返回。

切到 internal 后的建议：

- dry-run 调度仍保留在 9000 `_handle_douyin_webhook()`。
- 9202 继续不触发 dry-run。
- 9000 使用 internal 返回的 `event_id`、`is_duplicate` 判断是否调度 dry-run。
- 条件保持不变：`payload.event == im_receive_msg`、`is_duplicate is not true`、`event_id` 存在。

## 8. 切到 internal 后如何避免 duplicate event 重复触发 dry-run？

推荐采用“三层防重”：

第一层：9202 事件幂等。

```text
apps.leads.webhook_events.process_internal_webhook_event()
  -> build_event_key(payload)
  -> 查找 is_duplicate=0 的同 event_key
  -> 命中则写 duplicate audit event
  -> 返回 is_duplicate=true、lead_action=duplicate_event
```

第二层：9000 dry-run 调度条件。

```text
payload.event == "im_receive_msg"
and result.is_duplicate is not True
and result.event_id is not None
```

因此 duplicate event 不进入 `background_tasks.add_task(...)`。

第三层：dry-run 服务自身幂等。

```text
run_ai_auto_reply_dry_run(event_id)
  -> 读取 DouyinWebhookEvent.event_key
  -> 查询 AiAutoReplyRun.trigger_event_key
  -> 已存在则跳过
```

关键约束：

- 9202 不得新增 dry-run 调度。
- 9000 不得在 internal 成功后再本地执行 `process_webhook_event()`。
- fallback 只在 internal 失败时发生，不能在 internal 成功但业务字段为 `duplicate_event`、`unbound_account`、`missing_conversation` 时发生。
- duplicate event 虽然会写一条 `is_duplicate=1` 审计事件，但 9000 应根据 `is_duplicate=true` 跳过 dry-run。

## 9. 如何保证 /webhook/douyin 与 /integrations/douyin/webhook 行为一致？

当前两条路径已经共用 `_handle_douyin_webhook()`：

- `POST /integrations/douyin/webhook` 传入 `source_path="/integrations/douyin/webhook"`。
- `POST /webhook/douyin` 传入 `source_path="/webhook/douyin"`。

E3-C 切流必须继续保持：

- 两个路由函数只负责读取 `request.body()`，然后调用同一个 `_handle_douyin_webhook()`。
- internal 开关、fallback 开关、LeadsClient 调用、dry-run 调度都只写在 `_handle_douyin_webhook()`。
- `source_path` 只用于日志和传给 9202 的审计字段，不参与业务分支。
- 两个路径使用同一套验签规则、同一套 JSON decode、同一套响应映射、同一套 fallback 和 dry-run 条件。

需要新增或保留的测试：

- 两个路径在 internal 关闭时行为一致。
- 两个路径在 internal 开启且 9202 成功时行为一致。
- 两个路径在 internal 开启但 9202 不可用且 fallback 开启时行为一致。
- 两个路径在 production 强制验签时都不能绕过签名。

## 10. 需要哪些测试覆盖？

### 10.1 配置与开关

| 场景 | 输入 / 操作 | 预期 |
| --- | --- | --- |
| internal 默认关闭 | `LEADS_WEBHOOK_INTERNAL_ENABLED=false` | 9000 走本地 `process_webhook_event()`，正式行为不变。 |
| internal 开启 | `LEADS_WEBHOOK_INTERNAL_ENABLED=true` | 验签和 JSON decode 后调用 9202。 |
| fallback 开启 | 9202 超时或不可用，`LEADS_WEBHOOK_FALLBACK_LOCAL=true` | 9000 回退本地处理并返回成功响应。 |
| fallback 关闭 | 9202 超时或不可用，`LEADS_WEBHOOK_FALLBACK_LOCAL=false` | 9000 返回可诊断的 502，不写本地事件。 |

### 10.2 webhook 验签

| 场景 | 输入 / 操作 | 预期 |
| --- | --- | --- |
| development 免验签 | `APP_ENV=development` 且 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` | 合法 JSON 可进入后续处理。 |
| production 强制验签 | `APP_ENV=production` | 两个 webhook 路径都必须校验签名。 |
| 缺少签名头 | production 无 `Authorization` 或 `X-Auth-Timestamp` | 返回 401，不调用 9202，不 fallback。 |
| 错误签名 | production 错误签名 | 返回 401，不调用 9202，不 fallback。 |
| JSON 解析失败 | body 非合法 JSON | 返回 400，不调用 9202，不 fallback。 |

### 10.3 internal 成功路径

| 场景 | 输入 / 操作 | 预期 |
| --- | --- | --- |
| 首次 `im_receive_msg` | 9202 返回 `created` | 9000 返回 `WebhookResponse`，`is_new_lead=true`，调度一次 dry-run。 |
| 已有 pending 会话 | 9202 返回 `updated` | 9000 返回 `lead_action=updated`，非重复时可调度 dry-run。 |
| 非线索事件 | 9202 返回 `not_lead_event` | 9000 返回成功，不调度 dry-run。 |
| 未绑定账号 | 9202 返回 `unbound_account` | 9000 返回成功，不生成线索；是否 dry-run 由 event_id 和业务策略决定，建议保持当前条件仅看 `im_receive_msg + 非重复 + event_id`，但 dry-run 内部绑定门禁会跳过。 |
| 缺会话 ID | 9202 返回 `missing_conversation` | 9000 返回成功；dry-run 服务会因 conversation missing 跳过。 |

### 10.4 duplicate 与 dry-run

| 场景 | 输入 / 操作 | 预期 |
| --- | --- | --- |
| 重复 webhook | 9202 返回 `is_duplicate=true` | 9000 不添加 dry-run 后台任务。 |
| dry-run 重复执行 | 对同 event_key 再次调用 `run_ai_auto_reply_dry_run` | `AiAutoReplyRun` 不重复创建。 |
| internal 成功后不 fallback | 9202 返回 `duplicate_event` 或 `unbound_account` | 9000 不再本地调用 `process_webhook_event()`。 |

### 10.5 双入口一致性

| 场景 | 输入 / 操作 | 预期 |
| --- | --- | --- |
| `/webhook/douyin` internal 成功 | 同 payload | 响应字段与 `/integrations/douyin/webhook` 等价。 |
| `/integrations/douyin/webhook` internal 成功 | 同 payload | 响应字段与 `/webhook/douyin` 等价。 |
| 两个路径顺序收到同一事件 | 第一路径创建，第二路径重复 | 第二次返回 `is_duplicate=true`，不重复 dry-run。 |

### 10.6 9202 internal 鉴权

| 场景 | 输入 / 操作 | 预期 |
| --- | --- | --- |
| 缺少 `X-Internal-Token` | 直接请求 9202 | 401。 |
| token 错误 | 直接请求 9202 | 401。 |
| 缺少 `X-Gateway-Source-System` | 直接请求 9202 | 401。 |
| `signature_verified=false` | 直接请求 9202 | 400，错误码 `WEBHOOK_SIGNATURE_NOT_VERIFIED`。 |

### 10.7 回归套件建议

E3-C 实施后建议执行：

```bash
python -m pytest tests/test_leads_internal_webhook_app.py -q
python -m pytest tests/test_leads_client.py -q
python -m pytest tests/test_douyin_webhook.py tests/test_webhook_events.py -q
python -m pytest tests/test_leads_management.py tests/test_leads_app.py tests/test_leads_client.py -q
python -m pytest tests/test_auth_context.py -q
python -m pytest tests/test_capability_service_boundaries.py tests/test_xg_douyin_ai_cs_app.py -q
docker compose -f docker-compose.dev.yml config --quiet
```

如 E3-C 修改 `app/routers/integrations.py`，还应至少新增专门测试覆盖：

- internal enabled 成功转发。
- internal enabled + fallback local。
- internal enabled + fallback disabled 返回 502。
- duplicate 不触发 dry-run。
- 双路径行为一致。

## 11. 回滚步骤是什么？

### 11.1 灰度期快速回滚

1. 将 9000 环境变量改为：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
```

2. 重启 9000 服务，使配置生效。
3. 保持 9202 可继续运行，但 9000 不再调用它。
4. 不修改宝塔反向代理，不修改 GMP webhook 地址。
5. 不修改 `/webhook/douyin` 和 `/integrations/douyin/webhook` 路由。

结果：

```text
抖音/GMP -> 9000 -> 本地 process_webhook_event()
```

正式 webhook 回到 E3-C 前行为。

### 11.2 9202 临时不可用时自动降级

如果 `LEADS_WEBHOOK_FALLBACK_LOCAL=true`：

1. 9000 调用 9202 失败。
2. 9000 记录 fallback 日志。
3. 9000 自动执行本地 `process_webhook_event(db, payload)`。
4. 9000 返回原 `WebhookResponse`。

该方式适合灰度期短时保护，但不能替代配置回滚。若 fallback 次数持续上升，应主动关闭 `LEADS_WEBHOOK_INTERNAL_ENABLED`。

### 11.3 fallback 关闭后的回滚

如果 `LEADS_WEBHOOK_FALLBACK_LOCAL=false` 且 9202 故障：

1. 9000 webhook 会返回 502 或等价服务不可用错误。
2. 立即将 `LEADS_WEBHOOK_INTERNAL_ENABLED=false`。
3. 重启 9000。
4. 验证 `/webhook/douyin` 本地处理恢复。

### 11.4 数据回滚

本阶段不做 DB model / migration，不设计结构回滚。

如果灰度期出现重复写入或异常事件：

- 先通过 `douyin_webhook_events.event_key`、`is_duplicate`、`lead_id` 定界影响范围。
- 再通过 `(account_open_id, conversation_short_id)` 检查 `douyin_leads` 归并结果。
- 不在自动回滚步骤中删除数据。
- 数据修复必须单独开阶段评审并备份。

## 12. 风险分析

风险等级：HIGH。

原因：

- 涉及 webhook 正式入口。
- 涉及配置开关。
- 涉及 9000 到 9202 的内部服务调用。
- 涉及 AI 自动回复 dry-run 后台任务调度边界。

主要风险与控制：

| 风险 | 控制方案 |
| --- | --- |
| 9202 不可用导致 webhook 失败 | 灰度期开启 `LEADS_WEBHOOK_FALLBACK_LOCAL=true`，并设置超时。 |
| 双入口行为不一致 | 只在 `_handle_douyin_webhook()` 插入分支，不在两个路由分别实现。 |
| duplicate 重复触发 dry-run | 9202 返回 `is_duplicate=true`，9000 按现有条件跳过，dry-run 服务按 event_key 再去重。 |
| 9202 被外部绕过调用 | 校验 `X-Internal-Token`、`X-Gateway-Source-System`、`signature_verified=true`。 |
| internal 成功后又 fallback 造成双写 | 只在网络/状态/JSON 失败时 fallback；业务成功响应不 fallback。 |
| 验签边界被迁移 | 明确 `verify_signature()` 留在 9000，9202 不持有 `DY_SECRET_KEY`。 |
| 自动发送边界被误放开 | 本方案不修改抖音私信发送；9202 不触发 dry-run；9000 dry-run 仍保持 `auto_send=false` 后置门禁。 |

## 13. 下一阶段执行建议

E3-C 实施时建议按以下最小步执行：

1. 在 `app/config.py` 增加 internal webhook 开关读取，不改变默认行为。
2. 在 `app/routers/integrations.py::_handle_douyin_webhook()` 中增加 internal 调用分支。
3. 保留本地 `process_webhook_event()` fallback。
4. 将 internal 返回结果统一映射到 `WebhookResponse`。
5. 保持 dry-run 调度位于 9000，条件沿用 `im_receive_msg + 非重复 + event_id`。
6. 新增测试覆盖 internal 成功、fallback、fallback disabled、duplicate dry-run、双路径一致性。
7. 先在 `LEADS_WEBHOOK_INTERNAL_ENABLED=false` 下跑完整回归，再开启测试环境 internal 开关验证。

## 14. 结论

推荐 E3-C 采用“9000 保持公网验签与响应边界，9202 承接 internal 事件处理，9000 保留本地 fallback 和 dry-run 唯一调度权”的方案。

这样可以：

- 不改变 GMP webhook 地址。
- 不迁移 `verify_signature()`。
- 不扩大 9202 公网攻击面。
- 保持两个正式入口行为一致。
- 保留快速回滚能力。
- 避免 duplicate event 重复触发 dry-run。
- 不触碰 19000、`input_writer`、微信 UI 自动化、抖音私信发送和 DB/migration。
