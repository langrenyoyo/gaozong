# Phase 3-E3 webhook / sync-leads 迁移方案评审

## 1. 本轮范围

本轮是 Phase 3-E3-A，只做 webhook ingest 与 sync-leads 迁移前方案评审，不迁移业务代码。

允许范围：

- 审计 `/webhook/douyin`、`/integrations/douyin/webhook`、`/integrations/douyin/sync-leads` 当前调用链。
- 审计 webhook 验签、授权企业号绑定、有效线索生成、原始事件审计、sync-leads 当前行为。
- 输出下一阶段 E3-B 可执行的迁移方案。

禁止范围：

- 不修改 webhook 验签。
- 不修改正式 webhook 路由。
- 不修改 sync-leads 路由。
- 不修改数据库模型或 migration。
- 不修改 19000 Local Agent、`input_writer`、微信 UI 自动化。
- 不修改抖音私信发送。
- 不放宽 `manual_confirmed=true` / `auto_send=false` 安全边界。

## 2. 当前调用链

### 2.1 正式 webhook 入口

当前有两个 9000 入口：

| 当前 path | 入口文件 | 说明 |
| --- | --- | --- |
| `POST /webhook/douyin` | `app/routers/integrations.py` | GMP 已配置的正式兼容回调地址 |
| `POST /integrations/douyin/webhook` | `app/routers/integrations.py` | 旧集成路径，与正式入口共用处理函数 |

两条路径都调用 `_handle_douyin_webhook()`，真实链路为：

```text
抖音/GMP
  -> 9000 /webhook/douyin 或 /integrations/douyin/webhook
  -> 读取原始 request body
  -> 根据 APP_ENV / DOUYIN_WEBHOOK_AUTH_REQUIRED 判断是否验签
  -> verify_signature(body, X-Auth-Timestamp, Authorization)
  -> JSON decode
  -> process_webhook_event(db, payload)
  -> 写 douyin_webhook_events
  -> 可能写 / 更新 douyin_leads
  -> commit
  -> im_receive_msg 非重复事件追加 AI 自动回复 dry-run 后台任务
```

关键事实：

- 原始 body 只在 9000 router 层读取。
- 签名校验依赖原始 body、`X-Auth-Timestamp`、`Authorization`。
- `/webhook/douyin` 与 `/integrations/douyin/webhook` 当前行为一致。
- `process_webhook_event()` 当前位于 `app/integrations/douyin_webhook.py`，它同时承担事件幂等、绑定反查、有效线索生成和原始事件写入。

### 2.2 sync-leads 入口

当前入口：

| 当前 path | 入口文件 | 当前 service |
| --- | --- | --- |
| `POST /integrations/douyin/sync-leads` | `app/routers/integrations.py` | `app/services/douyin_sync_service.py::preview_sync_leads()` |

当前链路为：

```text
前端/人工触发
  -> 9000 /integrations/douyin/sync-leads
  -> preview_sync_leads(db, request)
  -> fetch_leads(DOUYIN_API_BASE_URL)
  -> 映射 open_id / display_name / phone / wechat / content
  -> dry_run=true 时只预览
  -> dry_run=false 时写 douyin_leads
  -> 可选 auto_assign
  -> 可选 auto_notify / auto_create_wechat_task
```

关键事实：

- `dry_run=true` 是默认值。
- `auto_notify` 是旧通知链路，依赖 Windows 专用通知模块，当前不适合在能力服务拆分时扩大。
- `auto_create_wechat_task` 只创建任务，不调用 19000，也不执行微信自动化。
- 当前 sync-leads 从外部 douyinAPI 拉取，不是正式 webhook ingest 主链路。

## 3. 当前验签与绑定保护边界

### 3.1 验签边界

当前验签函数为 `app/integrations/douyin_webhook.py::verify_signature()`。

校验输入：

- 原始 `body: bytes`
- `X-Auth-Timestamp`
- `Authorization`
- 服务端配置 `DY_SECRET_KEY`

校验规则：

```text
sha256Hex(DY_SECRET_KEY + body.decode("utf-8") + "-" + timestamp)
```

迁移结论：

- 正式 webhook 入口必须继续留在 9000 gateway。
- 原始 body、timestamp、signature 必须在 9000 读取和校验。
- 9202 leads 不应直接暴露公网 webhook，也不应重新解释公网签名。
- 9000 验签成功后，才允许向 9202 传递已解析的内部事件请求。

原因：

- 只有网关层能可靠读取原始 body 并统一控制生产验签开关。
- 如果 9202 直接暴露公网 webhook，会复制验签、环境开关和日志边界，增加绕过风险。
- 能力服务拆分目标是内部职责收敛，不是扩大公网入口。

### 3.2 授权企业号绑定保护

当前 `process_webhook_event()` 对 `im_receive_msg` 进行企业号绑定反查：

```text
account_open_id = payload.to_user_id
DouyinAuthorizedAccount.open_id == account_open_id
DouyinAuthorizedAccount.bind_status == 1
DouyinAuthorizedAccount.merchant_id 非空
```

只有绑定状态为 `bound` 时，才会继续生成或更新有效线索。

迁移结论：

- `merchant_id` 来源必须继续是可信绑定记录或可信 RequestContext，不能来自前端、GMP payload、query 参数。
- `account_open_id` 必须来自 webhook 事件接收方 `to_user_id`。
- `conversation_short_id` 必须来自解析后的 content。
- 未绑定、无 merchant、缺会话 ID 都不得生成有效线索。

## 4. 当前有效线索生成条件

当前有效线索生成位于 `upsert_lead_from_webhook()`。

生成或更新 `douyin_leads` 的必要条件：

1. `event == "im_receive_msg"`。
2. content 是文本消息，`is_text_message(content)` 为 true。
3. `to_user_id` 能反查到 `bind_status == 1` 的 `DouyinAuthorizedAccount`。
4. 绑定记录有可信 `merchant_id`。
5. content 中有 `conversation_short_id`。
6. `from_user_id` 非空。

当前联系信息提取为 best-effort：

- `contact_extractor.extract_contacts_from_text()` 尝试提取手机号或微信号。
- 当前实现即使没有联系方式，也会按会话归并创建或更新线索，`customer_contact` 可为空。
- 这是既有行为，本轮评审不建议在 E3-B 同时修改。

有效线索归并键：

```text
(account_open_id, conversation_short_id)
```

幂等事件键：

```text
sha256(event | from_user_id | to_user_id | conversation_short_id | server_message_id | create_time)
```

## 5. 当前 unbound / invalid / duplicate 事件处理

| 类型 | 当前处理 | 是否生成有效线索 | 迁移要求 |
| --- | --- | --- | --- |
| `duplicate_event` | 写入 `douyin_webhook_events`，`is_duplicate=1`，不更新线索 | 否 | 继续只作为内部审计 |
| `unbound_account` | 写入原始事件，`lead_id=None` | 否 | 继续只作为内部审计，不进入商户端有效线索 |
| `merchant_unresolved` | 写入原始事件，`lead_id=None` | 否 | 继续只作为内部审计 |
| `missing_conversation` | 写入原始事件，`lead_id=None` | 否 | 继续只作为内部审计 |
| 非文本消息 | 写入原始事件，当前 action 为 `invalid_contact` | 否 | 继续只作为内部审计 |
| content 解析失败 | 写入原始事件，查询侧推断 invalid | 否 | 继续只作为内部审计 |
| 非 `im_receive_msg` | 写入原始事件，不生成线索 | 否 | 继续只作为内部审计 |

产品边界：

- 商户端 AI小高线索列表只展示 `douyin_leads` 有效线索。
- `webhook_events` 只作为内部调试 / 管理员审计能力。
- `unbound_account`、invalid event、duplicate event 不进入商户端主导航，不作为有效线索。

## 6. 推荐迁移方案

### 6.1 总体原则

推荐采用“9000 保持公网安全边界，9202 承接内部线索处理”的渐进迁移。

```text
抖音/GMP
  -> 9000 gateway
  -> 9000 读取原始 body
  -> 9000 验签
  -> 9000 JSON decode
  -> 9000 注入内部调用身份
  -> 9202 /api/leads/internal/webhook-events
  -> 9202 写原始事件 / 生成有效线索
  -> 9000 保持旧响应结构
```

### 6.2 9202 建议新增 internal API

建议 E3-B 新增但不接正式 webhook：

```text
POST /api/leads/internal/webhook-events
POST /api/leads/internal/sync-douyin-leads
```

`POST /api/leads/internal/webhook-events` 的定位：

- 只接收 9000 已验签、已解析后的内部 payload。
- 不接收公网原始 webhook。
- 不读取或校验抖音公网签名。
- 返回结构兼容 `WebhookResponse` 所需字段：`event_id`、`lead_id`、`is_new_lead`、`is_duplicate`、`lead_action`。

建议请求字段：

```json
{
  "source_path": "/webhook/douyin",
  "payload": {},
  "received_at": "2026-06-22T00:00:00",
  "signature_verified": true,
  "gateway_request_id": "optional",
  "gateway_app_env": "production"
}
```

允许转给 9202 的数据：

- JSON 解析后的 payload。
- `source_path`。
- `signature_verified=true`。
- 9000 生成的 request_id / trace_id。
- 网关环境摘要。

不建议转给 9202 的数据：

- 原始 `Authorization` 签名。
- `DY_SECRET_KEY`。
- 未脱敏的日志上下文。
- 前端可伪造的 merchant_id / tenant_id。

`POST /api/leads/internal/sync-douyin-leads` 的定位：

- 只供 9000 或内部运维调用。
- 承接当前 `preview_sync_leads()` 的 dry-run / 写入能力。
- E3-B 先可只支持 `dry_run=true`，降低外部拉取和写库风险。
- `auto_notify`、`auto_create_wechat_task` 在 E3-B 不建议迁入 9202。

### 6.3 9202 internal 鉴权

9202 必须补 internal token / gateway header 鉴权。

最低要求：

- `X-Internal-Token` 必须存在且与 `LEADS_INTERNAL_TOKEN` 匹配。
- `X-Gateway-Source-System` 必须为受信任来源，例如 `auto_wechat_gateway`。
- `X-Gateway-User-Id` 可为 `gateway` 或系统用户。
- internal webhook 接口不得使用普通商户权限码直接访问。

建议后续增强：

- 增加请求时间戳与短窗口校验。
- 增加请求 ID 幂等与审计日志。
- 增加 9000 到 9202 的网络层访问限制。

## 7. 不推荐方案及原因

### 7.1 不推荐：9202 直接暴露公网 webhook

原因：

- 会复制验签逻辑和生产开关，容易出现 9000 与 9202 行为不一致。
- 会扩大公网攻击面。
- 会让回滚变复杂，需要同时改反向代理和服务路由。
- 与“9000 gateway 负责登录态、RequestContext、权限校验、统一响应、反向代理或内部服务调用”的阶段目标冲突。

### 7.2 不推荐：把原始 body 和签名透传给 9202 再验签

原因：

- 原始 body 的字节级一致性是签名关键，跨服务透传时容易被编码、压缩或日志中间件影响。
- 需要在 9202 复制 `DY_SECRET_KEY`，扩大密钥暴露面。
- 9000 已经是公网边界，重复验签收益小于复杂度。

### 7.3 不推荐：E3-B 同时迁移 sync-leads 写库、auto_assign、auto_notify、微信任务联动

原因：

- sync-leads 不是正式 webhook ingest 主链路。
- `auto_notify` 触达微信通知链路，靠近 19000 / Windows UI 自动化安全边界。
- 同时迁移会混合外部拉取、写库、分配、通知任务，难以定位回归。

### 7.4 不推荐：把 unbound / invalid / duplicate 合并成商户端线索状态

原因：

- 它们不是有效线索。
- `unbound_account` 是保护行为，不应被商户端误认为可跟进客户。
- 商户端 AI小高线索应以 `douyin_leads` 为主对象，原始事件只做内部审计。

## 8. 分阶段迁移计划

### E3-A：只读评审

当前阶段。

交付：

- 明确 9000 继续承接公网 webhook 并先验签。
- 明确 9202 不直接暴露公网 webhook。
- 明确 unbound / invalid / duplicate 不生成有效线索。
- 明确 E3-B internal API 设计。

### E3-B：新增 9202 internal 接口但不接正式 webhook

目标：

- 在 `apps/leads` 新增 internal router。
- 复制或承接当前 `process_webhook_event()` 所需的事件处理能力。
- 新增 client 方法，但 9000 正式 webhook 暂不切流。
- 用测试直接调用 9202 internal endpoint 验证行为。

建议迁移内容：

- `process_webhook_event()` 主体逻辑。
- `build_event_key()`、`persist_webhook_event()`、`persist_duplicate_webhook_event()`。
- `upsert_lead_from_webhook()`。
- `parse_content()`、`normalize_message_text()`、`is_text_message()`。
- 继续复用共享 `app.models` 和共享 DB，暂不拆库。

暂缓迁移内容：

- 正式 `/webhook/douyin` 路由。
- `verify_signature()`。
- AI 自动回复 dry-run 后台任务触发。
- sync-leads 的 `auto_notify` 和微信任务联动。

E3-B 测试重点：

- 9202 internal 创建有效线索。
- 9202 internal duplicate 只写重复事件，不更新线索。
- 9202 internal unbound_account 只写事件，不创建线索。
- 9202 internal 无 internal token 拒绝。
- 商户端 `/api/leads` 仍只看到有效线索。

### E3-C：9000 验签后调用 9202 internal

目标：

- 9000 保留两个旧公网入口。
- 9000 继续读取原始 body 并验签。
- 验签成功后，9000 调用 `LeadsClient.process_webhook_event()` 或等价 internal client。
- 9000 保持 `WebhookResponse` 响应结构不变。
- 出现 9202 不可用时，可配置回退到 9000 本地旧 service。

建议新增配置：

```text
LEADS_WEBHOOK_INTERNAL_ENABLED=false
LEADS_SERVICE_BASE_URL=http://127.0.0.1:9202
LEADS_INTERNAL_TOKEN=...
LEADS_WEBHOOK_FALLBACK_LOCAL=true
```

切流策略：

1. 默认关闭 internal 转发。
2. 开启后先在开发 / 测试环境验证。
3. 灰度期间保留本地 fallback。
4. 9202 响应与旧本地响应字段完全一致后再考虑删除 fallback。

### E3-D：回归与灰度

目标：

- 完成 webhook、原始事件审计、有效线索、商户隔离、sync-leads dry-run 回归。
- 对比 9000 本地处理与 9202 internal 处理结果。
- 观察重复事件、unbound_account、invalid event 统计。
- 保持旧接口可用。

灰度观察指标：

- webhook 响应 2xx 比例。
- 验签失败比例。
- `unbound_account` 数量。
- duplicate 数量。
- 有效线索创建 / 更新数量。
- 9202 internal 调用失败数量。
- fallback 次数。

## 9. sync-leads 迁移建议

结论：sync-leads 不建议先于 webhook internal 能力完全稳定前切正式流量。

推荐策略：

1. E3-B 可先在 9202 增加 `POST /api/leads/internal/sync-douyin-leads`，但默认只支持或只测试 `dry_run=true`。
2. E3-C 仍让 9000 旧 `/integrations/douyin/sync-leads` 保持现状。
3. sync-leads 写库能力应在 webhook internal 稳定后再迁移。
4. `auto_assign` 可在单独阶段迁移。
5. `auto_notify` 和 `auto_create_wechat_task` 应继续留在 9000 或微信助手能力边界内评审，不能跟 E3-B 混迁。

理由：

- sync-leads 依赖外部 douyinAPI 拉取，不是当前正式事件回调主链路。
- 其中包含可选分配、旧通知、微信任务创建，风险高于只迁 webhook 有效线索生成。
- 微信任务联动靠近 19000 安全边界，应单独评审。

## 10. merchant_id / account_open_id / conversation_short_id 隔离

迁移必须保持以下隔离规则：

| 字段 | 当前可信来源 | 迁移后规则 |
| --- | --- | --- |
| `merchant_id` | `DouyinAuthorizedAccount.merchant_id` 或 RequestContext | webhook ingest 只能来自绑定反查；商户 API 只能来自 RequestContext |
| `account_open_id` | webhook `to_user_id` | 不信任前端传入；用于反查企业号绑定 |
| `conversation_short_id` | webhook content | 缺失时不生成有效线索 |
| `source_id` | webhook `from_user_id` | 作为客户 open_id 记录，不作为跨账号唯一主键 |
| 有效线索归并 | `(account_open_id, conversation_short_id)` | 保持不变 |

跨商户保护：

- 9202 internal webhook 生成线索前必须反查授权企业号绑定。
- 同一个 `conversation_short_id` 在不同 `account_open_id` 下不能混淆。
- 商户端查询继续通过 RequestContext / gateway header 过滤 `merchant_id`。
- 旧 legacy NULL merchant_id 策略不得扩大可见范围。

## 11. 必须保留的安全测试

### webhook 验签

- `APP_ENV=production` 时，即使 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 也必须强制验签。
- 缺少 `DY_SECRET_KEY` 时拒绝请求。
- 缺少签名头拒绝。
- 错误签名拒绝。
- 过期 timestamp 拒绝。
- `/webhook/douyin` 与 `/integrations/douyin/webhook` 行为一致。

### 绑定保护

- 已绑定企业号可生成有效线索。
- `unbound_account` 只写原始事件，不写 `douyin_leads`。
- 绑定记录缺 merchant_id 不写有效线索。
- 前端或 payload 伪造 merchant_id 不生效。

### 事件幂等

- 首次事件创建 / 更新线索。
- 重复事件写 `is_duplicate=1` 原始事件。
- 重复事件不重复创建线索。
- 重复事件不重复触发后置 dry-run。

### 有效线索和审计分离

- 商户端 `/api/leads` 只返回有效线索。
- `webhook_events` 能查询 duplicate / invalid / unbound 作为内部审计。
- `unbound_account` 不作为商户端线索状态。

### 19000 / 自动发送安全边界

- webhook 迁移不调用 19000。
- webhook 迁移不调用 `input_writer`。
- 不改变 `manual_confirmed=true`。
- 不改变 `auto_send=false`。
- AI 自动回复仍只能 dry-run 或人工确认，不真实自动发送。

## 12. 建议验证命令

E3-A 文档评审后建议执行：

```bash
python -m pytest tests/test_douyin_webhook.py tests/test_webhook_events.py tests/test_douyin_sync.py -q
python -m pytest tests/test_leads_management.py tests/test_leads_app.py tests/test_leads_client.py -q
python -m pytest tests/test_auth_context.py -q
docker compose -f docker-compose.dev.yml config --quiet
```

E3-B 实施后建议新增并执行：

```bash
python -m pytest tests/test_leads_internal_webhook_app.py -q
python -m pytest tests/test_leads_client.py tests/test_douyin_webhook.py tests/test_webhook_events.py -q
```

## 13. 回滚方案

### E3-B 回滚

E3-B 不接正式 webhook，回滚简单：

- 停止使用 9202 internal webhook 测试入口。
- 保留或删除 internal router 均不影响正式流量。
- 9000 `/webhook/douyin` 与 `/integrations/douyin/webhook` 不受影响。

### E3-C 回滚

E3-C 如果切到 9202 internal 后出现问题：

1. 将 `LEADS_WEBHOOK_INTERNAL_ENABLED=false`。
2. 保持 9000 原始 webhook 路由继续本地调用 `process_webhook_event()`。
3. 如 9202 不可用且 `LEADS_WEBHOOK_FALLBACK_LOCAL=true`，自动回退本地处理。
4. 不修改反向代理，不修改 GMP webhook 地址。
5. 不执行数据库回滚，因为本阶段仍共享 DB、共享模型、不做 migration。

### 数据回滚

本阶段不做 DB 拆库、不做 migration，因此不设计结构回滚。

如灰度期间出现重复写入：

- 以 `douyin_webhook_events.event_key` 和 `is_duplicate` 审计。
- 以 `(account_open_id, conversation_short_id)` 归并键检查 `douyin_leads`。
- 通过配置回退到 9000 本地处理后，再单独定界数据修复，不在迁移回滚中自动删除数据。

## 14. 多视角评审结论

### 技术视角

推荐将 9202 的 first step 定义为 internal-only 事件处理能力，而不是公网入口。`process_webhook_event()` 可以成为最小迁移单元，但 `verify_signature()` 和原始 body 读取必须留在 9000。sync-leads 涉及外部拉取和可选微信任务联动，不应与 webhook internal 处理在同一小步切流。

### 产品视角

AI小高线索的商户端主对象应继续是有效线索，而不是原始事件。`unbound_account`、invalid event、duplicate event 对商户不可操作，进入主线索列表会造成误解；它们只适合内部排障和管理员审计。

### 安全视角

最大风险是把公网 webhook 暴露面扩大到 9202，或让 9202 信任来自外部的 merchant_id / tenant_id。迁移必须保持“9000 先验签、9202 只信任 internal token 和 gateway header、有效线索 merchant_id 来自授权账号绑定”的三层边界。

## 15. 最终回答用户的 10 个问题

1. 正式 webhook 入口是否继续留在 9000 gateway 先验签？
   - 是。正式 `/webhook/douyin` 必须继续由 9000 先读取原始 body 并验签。

2. 原始 body、timestamp、signature 应在哪一层读取和校验？
   - 在 9000 gateway router 层读取和校验。9202 不处理公网签名。

3. 验签成功后，哪些数据可以转给 9202 leads？
   - 已解析 payload、source_path、signature_verified、gateway_request_id、网关来源摘要。不得传密钥，不信任外部 merchant_id。

4. `unbound_account`、invalid event、duplicate event 是否仍只进入内部审计，不成为有效线索？
   - 是。它们只写原始事件审计，不写 `douyin_leads`，不进入商户端主线索列表。

5. `douyin_leads` 有效线索生成应该在哪一层执行？
   - E3-B 起可在 9202 internal 执行；E3-C 由 9000 验签后调用 9202。9000 保留 fallback。

6. `sync-leads` 是否适合先迁，还是继续留在 9000？
   - 不适合先迁正式写库。建议先留在 9000；E3-B 最多新增 9202 dry-run internal 能力。

7. 迁移时如何保持 merchant_id / account_open_id / conversation_short_id 隔离？
   - `merchant_id` 只来自授权企业号绑定或 RequestContext；`account_open_id` 来自 webhook `to_user_id`；`conversation_short_id` 来自 content；有效线索继续按 `(account_open_id, conversation_short_id)` 归并。

8. 是否需要新增 internal API？
   - 需要。建议新增 `POST /api/leads/internal/webhook-events`，sync-leads 可后置新增 `POST /api/leads/internal/sync-douyin-leads`。

9. 9202 是否需要 internal token / gateway header 鉴权？
   - 需要。至少要求 `X-Internal-Token`，并校验 `X-Gateway-Source-System` 等网关注入头。

10. 回滚方案是什么？
    - E3-B 不切流，无正式回滚压力；E3-C 通过 `LEADS_WEBHOOK_INTERNAL_ENABLED=false` 回退 9000 本地处理，保留旧路由和共享 DB，不改反向代理。

