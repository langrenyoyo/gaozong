# Phase 3-E3-D Webhook Internal 灰度验收记录

## 1. 基本信息

- 验收日期：2026-06-22
- 验收目标：只做 `36db461` 之后的 webhook internal 本地 / 准生产灰度运行态验收，不新增功能。
- 当前 HEAD：`36db461 feat: 支持webhook转发线索internal处理`
- 工作区状态：提交前仅新增本文档；验收前代码工作区无业务改动。
- 运行方式：本地 Docker 开发编排 `docker-compose.dev.yml`。
- 数据库：`docker-data/auto_wechat_9000` 挂载到容器 `/workspace/data`，9000 与 9202 共用本地开发 SQLite。

## 2. 阶段边界

本轮只执行运行态验收与记录。

未修改内容：

- 未修改业务代码。
- 未修改 `verify_signature()`。
- 未修改公网 webhook path。
- 未修改 `/integrations/douyin/sync-leads`。
- 未修改 9202 internal 事件处理业务语义。
- 未修改 DB model / migration。
- 未修改 19000 Local Agent。
- 未修改 `input_writer` / 微信 UI 自动化。
- 未修改抖音私信发送。
- 未放宽 `manual_confirmed=true`。
- 未放宽 `auto_send=false`。

## 3. 服务状态

验收开始时，以下服务已通过 `docker compose -f docker-compose.dev.yml ps` 确认运行：

- 9000：`auto-wechat-api`
- 9202：`leads-service`
- 9100：`xg-douyin-ai-cs`
- frontend：`auto-wechat-frontend`

健康检查：

- `GET http://127.0.0.1:9000/`：200
- `GET http://127.0.0.1:9202/health`：200
- `GET http://127.0.0.1:9202/openapi.json`：200
- `GET http://127.0.0.1:9100/health`：200
- `GET http://127.0.0.1:5173/`：200

验收结束后已恢复 compose 默认 9000 / 9202 容器。恢复后 9000 环境只显示：

```text
APP_ENV=development
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

未设置 `LEADS_WEBHOOK_INTERNAL_ENABLED`，因此回到代码默认关闭状态。

## 4. 默认关闭模式验收

配置：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
```

实际运行说明：`docker-compose.dev.yml` 未向 9000 注入 `LEADS_WEBHOOK_INTERNAL_ENABLED`，代码默认值为 `false`。

验收 payload 使用已绑定企业号：

```text
to_user_id=demo_account_bound_001
merchant_id=demo_merchant_001
```

结果：

- `/webhook/douyin` 返回 200。
- 9000 走本地 `process_webhook_event()`。
- `douyin_webhook_events` 正常写入。
- 有效线索正常进入 `douyin_leads`。
- `/integrations/douyin/webhook` 与 `/webhook/douyin` 共享处理逻辑，双入口均成功。
- `/api/leads` 商户端仍只基于有效线索表展示线索；无效 / 审计事件不进入有效线索列表。

证据摘要：

```text
run=phase3e3d_a_1782108007244
POST /webhook/douyin -> 200, lead_action=created, event_id=1, lead_id=11
POST /integrations/douyin/webhook -> 200, lead_action=updated, event_id=3, lead_id=11
event_count=3
lead_count=1
lead.merchant_id=demo_merchant_001
lead.account_open_id=demo_account_bound_001
```

duplicate 专项复测使用完全相同原始请求体重复发送：

```text
run=phase3e3d_a_dup_1782108029081
first -> 200, lead_action=created, is_duplicate=false, lead_id=12
second -> 200, lead_action=duplicate_event, is_duplicate=true, lead_id=12
event_count=2
lead_count=1
第二条 event.is_duplicate=1
```

结论：默认关闭模式保持旧行为，duplicate 不重复生成线索。

## 5. Internal 开启模式验收

配置：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=true
LEADS_WEBHOOK_FALLBACK_LOCAL=true
LEADS_SERVICE_BASE_URL=http://leads-service:9202
LEADS_INTERNAL_TOKEN=dev-only-token
```

说明：为避免修改 `docker-compose.dev.yml`，验收期间临时停止 compose 的 9000 / 9202 容器，用同一镜像、同一网络、同一数据卷启动带上述环境变量的临时容器。验收后已删除临时容器并恢复 compose 容器。

结果：

- 9000 验签开关仍按原规则运行，development 下本地免验签。
- 9000 JSON decode 后调用 9202 `POST /api/leads/internal/webhook-events`。
- 9202 写入 `douyin_webhook_events`。
- 9202 生成 `douyin_leads`。
- 9000 返回旧 `WebhookResponse` 结构。
- `/webhook/douyin` 与 `/integrations/douyin/webhook` 行为一致。

证据摘要：

```text
run=phase3e3d_b_1782108097086
/webhook/douyin first -> 200, lead_action=created, is_duplicate=false, event_id=6, lead_id=13
/webhook/douyin duplicate -> 200, lead_action=duplicate_event, is_duplicate=true, event_id=7, lead_id=13
/integrations/douyin/webhook -> 200, lead_action=created, event_id=8, lead_id=14
event_count=4
lead_count=2
```

9000 日志证据：

```text
leads_internal_webhook_forward stage=leads_internal_webhook_forward source_path=/webhook/douyin event=im_receive_msg event_id=6 lead_id=13 lead_action=created is_duplicate=False
leads_internal_webhook_forward stage=leads_internal_webhook_forward source_path=/webhook/douyin event=im_receive_msg event_id=7 lead_id=13 lead_action=duplicate_event is_duplicate=True
leads_internal_webhook_forward stage=leads_internal_webhook_forward source_path=/integrations/douyin/webhook event=im_receive_msg event_id=8 lead_id=14 lead_action=created is_duplicate=False
```

9202 日志证据：

```text
POST /api/leads/internal/webhook-events HTTP/1.1" 200 OK
```

结论：internal 开启后，9000 确认调用 9202，响应结构兼容旧 webhook 返回结构。

## 6. Fallback Enabled 验收

配置：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=true
LEADS_WEBHOOK_FALLBACK_LOCAL=true
LEADS_SERVICE_BASE_URL=http://127.0.0.1:9299
```

结果：

- 9000 调用 internal 失败。
- 9000 记录 fallback 日志。
- 9000 回退本地 `process_webhook_event()`。
- 响应仍为 200。
- 本地只写 1 条事件和 1 条有效线索，没有双写。

证据摘要：

```text
run=phase3e3d_fb_1782108145480
status=200
lead_action=created
event_id=10
lead_id=15
event_count=1
lead_count=1
```

日志证据：

```text
leads_internal_webhook_fallback stage=leads_internal_webhook_fallback failure_stage=leads_unavailable source_path=/webhook/douyin event=im_receive_msg error=<urlopen error [Errno 111] Connection refused>
webhook 新建线索(会话归并): lead_id=15
webhook 处理完成: event_id=10, event=im_receive_msg, is_duplicate=false, lead_action=created, lead_id=15
```

结论：fallback enabled 符合预期。

## 7. Fallback Disabled 验收

配置：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=true
LEADS_WEBHOOK_FALLBACK_LOCAL=false
LEADS_SERVICE_BASE_URL=http://127.0.0.1:9299
```

结果：

- 9000 返回 502。
- 不写本地 `douyin_webhook_events`。
- 不写本地 `douyin_leads`。
- 不触发 dry-run。

证据摘要：

```text
run=phase3e3d_fd_1782108196131
status=502
detail.code=LEADS_INTERNAL_WEBHOOK_UNAVAILABLE
detail.failure_stage=leads_unavailable
event_count=0
lead_count=0
```

日志证据：

```text
leads_internal_webhook_failed stage=leads_internal_webhook_failed failure_stage=leads_unavailable source_path=/webhook/douyin event=im_receive_msg error=<urlopen error [Errno 111] Connection refused>
```

结论：fallback disabled 符合预期，不写本地事件，不生成线索。

## 8. Duplicate / Unbound / Invalid 结果

duplicate：

- 默认关闭模式：相同原始请求体重复发送，第二次返回 `lead_action=duplicate_event`、`is_duplicate=true`，只保留 1 条有效线索。
- internal 开启模式：9202 返回 `lead_action=duplicate_event`、`is_duplicate=true`，9000 不 fallback。

unbound：

```text
run=phase3e3d_b_1782108097086
to_user_id=phase3e3d_unbound_account
status=200
lead_action=unbound_account
event_id=9
lead_id=null
```

结果：只写审计事件，不生成有效线索。

invalid：

- 自动化回归覆盖了 JSON 解析失败、验签失败、missing_conversation、非文本 / invalid_contact 等路径。
- JSON 解析失败不调用 9202、不 fallback。
- production 签名失败不调用 9202、不 fallback。

## 9. Dry-run 调度确认

dry-run 仍由 9000 `_handle_douyin_webhook()` 唯一调度。

当前条件保持：

```text
payload.event == "im_receive_msg"
result.is_duplicate is not True
result.event_id is not None
```

9202 `apps/leads/webhook_events.py::process_internal_webhook_event()` 不触发 dry-run。

运行态确认：

- internal duplicate 返回 `is_duplicate=true`。
- 9000 日志显示 duplicate 只记录 `leads_internal_webhook_forward`，未 fallback。
- fallback disabled 返回 502 且 `event_count=0`、`lead_count=0`，不满足 dry-run 调度条件。

自动化测试确认：

- `tests/test_douyin_webhook_internal_cutover.py` 覆盖 internal 成功调度 dry-run、duplicate 不调度 dry-run、fallback disabled 不写本地事件。

## 10. Sync-leads 与自动化边界

sync-leads：

- 本轮未修改 `/integrations/douyin/sync-leads`。
- 回归 `python -m pytest tests/test_douyin_sync.py -q` 通过。

19000 / input_writer / 微信 UI 自动化：

- 本轮未修改 19000 Local Agent。
- 未修改 `input_writer`。
- 未修改微信 UI 自动化。
- 未执行真机微信自动化。
- P0/P1 Local Agent 边界测试通过，保持 `sent=false`、只读检测、task_id 指定执行等门禁。

抖音私信发送：

- 本轮未修改抖音私信发送逻辑。
- 未放宽 `manual_confirmed=true`。
- 未放宽 `auto_send=false`。

## 11. 自动化回归结果

已执行并通过：

```text
python -m pytest tests/test_douyin_webhook_internal_cutover.py -q
9 passed

python -m pytest tests/test_leads_internal_webhook_app.py -q
5 passed

python -m pytest tests/test_leads_client.py -q
6 passed

python -m pytest tests/test_douyin_webhook.py tests/test_webhook_events.py -q
67 passed

python -m pytest tests/test_douyin_sync.py -q
20 passed

python -m pytest tests/test_leads_management.py tests/test_leads_app.py tests/test_leads_client.py -q
19 passed

python -m pytest tests/test_auth_context.py -q
17 passed

python -m pytest tests/test_capability_service_boundaries.py tests/test_xg_douyin_ai_cs_app.py -q
30 passed

python -m pytest tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_p1_auto_1d_fix4_safe_json.py -q
80 passed

docker compose -f docker-compose.dev.yml config --quiet
PASS
```

说明：测试输出中存在既有 `DeprecationWarning` / `StarletteDeprecationWarning`，不影响本轮验收结论。

## 12. 是否建议进入 Staging 灰度

建议进入 staging 灰度，但不要直接在生产打开 internal。

进入 staging 前建议：

1. 在 staging 环境显式配置 9000：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=true
LEADS_WEBHOOK_FALLBACK_LOCAL=true
LEADS_SERVICE_BASE_URL=http://<staging-leads-service>:9202
LEADS_INTERNAL_TOKEN=<staging-internal-token>
LEADS_CLIENT_TIMEOUT_SECONDS=5
```

2. 在 9202 配置相同 `LEADS_INTERNAL_TOKEN`。
3. 首轮灰度保留 `LEADS_WEBHOOK_FALLBACK_LOCAL=true`。
4. 观察 9000 日志：

```text
leads_internal_webhook_forward
leads_internal_webhook_fallback
leads_internal_webhook_failed
```

5. 观察 9202 `POST /api/leads/internal/webhook-events` 2xx 率。
6. 对比 `douyin_webhook_events`、`douyin_leads` 写入量和 duplicate 比例。

## 13. 生产配置建议

生产默认仍不要打开 internal：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
LEADS_WEBHOOK_FALLBACK_LOCAL=true
```

生产灰度时才显式打开：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=true
LEADS_WEBHOOK_FALLBACK_LOCAL=true
LEADS_SERVICE_BASE_URL=http://<prod-leads-service>:9202
LEADS_INTERNAL_TOKEN=<prod-internal-token>
LEADS_CLIENT_TIMEOUT_SECONDS=5
```

不建议首轮生产灰度使用：

```text
LEADS_WEBHOOK_FALLBACK_LOCAL=false
```

只有在 9202 稳定性、日志、告警、回滚流程完成后，才考虑关闭 fallback。

## 14. 回滚步骤

推荐回滚：

1. 将 9000 配置恢复为：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
LEADS_WEBHOOK_FALLBACK_LOCAL=true
```

2. 重启 9000。
3. 发送一条测试 webhook payload 到 `/webhook/douyin`。
4. 确认 9000 日志不再出现 `leads_internal_webhook_forward`。
5. 确认本地 `douyin_webhook_events` 和 `douyin_leads` 正常写入。

紧急回滚：

1. 只关闭 9000 的 `LEADS_WEBHOOK_INTERNAL_ENABLED`。
2. 不需要修改 9202。
3. 不需要迁移数据库。
4. 不需要修改 webhook path。
5. 不需要修改验签配置。

## 15. 结论

Phase 3-E3-D 本地 / 准生产灰度验收通过。

结论：

- 默认关闭模式保持旧行为。
- internal 开启后 9000 能调用 9202。
- 9202 能写事件和有效线索。
- 9000 返回结构保持旧 `WebhookResponse`。
- duplicate 不重复生成线索。
- unbound 只写审计事件。
- fallback enabled 可回退本地并成功响应。
- fallback disabled 返回 502 且不写本地事件 / 线索。
- dry-run 仍由 9000 唯一调度。
- sync-leads、19000、input_writer、微信 UI 自动化、抖音私信发送、安全发送门禁均未触碰。
