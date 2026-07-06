# P1-LIVE-CHECK-CALLBACK-SAFETY-REVIEW-1

## 1. 背景和范围

本轮是 live-check / OAuth / callback / webhook-observe 相关入口的只读安全审计和文档记录，不修改业务代码，不触发真实私信发送，不调用真实上游写接口。

审计重点：

- 公网暴露入口是否合理。
- 浏览器业务接口是否接入 NewCar RequestContext 和权限门禁。
- OAuth callback / redirect 是否存在 state、回跳地址、日志泄露风险。
- webhook 与 webhook-observe 是否存在签名绕过、重放、误写库风险。
- 私信发送是否保持人工确认、24 小时窗口、send_context 边界。
- 资源下载 / 上传是否存在账号归属、任意 URL、文件类型和大小风险。
- 日志、错误响应、持久化记录是否可能包含敏感信息。

扫描范围包括：

- `app/routers/integrations.py`
- `app/routers/douyin_live_check.py`
- `app/routers/douyin_ai_cs_proxy.py`
- `app/services/douyin_private_message_send_service.py`
- `app/services/douyin_workbench_conversation_service.py`
- `app/services/douyin_resource_download_service.py`
- `app/services/douyin_image_upload_service.py`
- `app/services/douyin_openapi_client.py`
- `app/integrations/douyin_webhook.py`
- `app/auth/dependencies.py`
- `app/config.py`
- `tests/test_douyin_live_check.py`
- `tests/test_douyin_webhook.py`
- `tests/test_douyin_ai_cs_proxy.py`
- `frontend/src/api/douyinLiveCheck.ts`
- `frontend/src/api/douyinAiCsClient.ts`
- `frontend/src/features/douyin-cs/*`
- `frontend/src/pages/*Douyin*`
- `docs/ai/*`

## 2. 接口清单

### live-check 浏览器业务接口

| 接口 | 当前用途 | 当前审计结论 |
|---|---|---|
| `GET /integrations/douyin/live-check/accounts` | 查询抖音客服账号列表 | 已接入登录和权限门禁，但账号查询服务未显式传入当前商户上下文，存在后续归属校验加固空间 |
| `POST /integrations/douyin/live-check/accounts/sync-bind-info` | 同步绑定账号信息 | 已接入登录和权限门禁，并传入 RequestContext |
| `POST /integrations/douyin/live-check/messages/send` | 人工确认后发送私信 | 已接入登录和权限门禁，发送安全边界较完整；但服务层未显式按当前商户校验 conversation/account 归属 |
| `POST /integrations/douyin/live-check/resources/download` | 拉取私信资源下载地址 | 已接入登录和权限门禁；存在 URL 覆盖、账号归属和上游资源访问边界加固空间 |
| `POST /integrations/douyin/live-check/resources/upload-image` | 上传图片到抖音开放平台 | 已接入登录和权限门禁；文件类型和大小有限制，但 open_id 归属校验需加固 |

### OAuth / callback / redirect

| 接口 | 当前用途 | 当前审计结论 |
|---|---|---|
| `GET /integrations/douyin/live-check/auth-url` | 获取授权链接 | 只检查 live-check 开关，未要求浏览器登录 |
| `GET /integrations/douyin/live-check/oauth-callback` | 观察 OAuth callback 参数 | 只记录内存摘要，不写库；未发现 state 强校验闭环 |
| `GET /integrations/douyin/live-check/auth-redirect` | 授权回跳后同步账号并跳转前端 | 使用可选 RequestContext；未发现 state 强校验、state 绑定商户和可信回跳域名白名单闭环 |
| `POST /integrations/douyin/live-check/callback` | live-check 回调观察入口 | 默认记录观察态；转正式管线开关开启时会跳过签名校验进入正式 webhook 处理 |

### webhook / observe

| 接口 | 当前用途 | 当前审计结论 |
|---|---|---|
| `POST /integrations/douyin/webhook` | 正式抖音 webhook | production 强制签名校验，支持 timestamp 漂移检查和事件幂等 |
| `POST /webhook/douyin` | 正式抖音 webhook 兼容路径 | 与正式路径共用处理逻辑 |
| `POST /integrations/douyin/live-check/webhook-observe` | live-check webhook 观察入口 | 默认观察记录；转正式管线开关开启时存在签名绕过风险 |

## 3. 当前鉴权 / 签名 / state 现状

### 浏览器业务接口鉴权

- `accounts`、`sync-bind-info`、`messages/send`、`resources/download`、`resources/upload-image` 均接入 `get_request_context_required`。
- 上述接口均要求 `auto_wechat:douyin_ai_cs` 权限。
- 前端 live-check 私信发送、资源下载、图片上传请求未传 `merchant_id`，这是正向边界。
- 当前代码未看到服务层对 `messages/send`、`resources/download`、`resources/upload-image` 显式传入 `context.merchant_id` 后做账号 / 会话归属强校验。
- `accounts` 入口有权限门禁，但账号列表服务调用未显式带当前商户上下文，存在跨商户数据暴露的后续审计和加固点。

### OAuth callback / auth-redirect

- `oauth-callback` 当前更像观察入口：记录 callback 参数摘要到内存，不直接写库。
- `auth-redirect` 使用可选 RequestContext，随后同步授权账号并跳回前端。
- 本轮扫描未发现不可预测 `state` 的生成、校验、一次性消费、过期处理、商户绑定、redirect 目标绑定的完整闭环。
- 未确认回跳 URL 有可信前端域名白名单。该项需要后续按配置和部署反代一起复核。
- callback 记录中 code 只保留预览摘要，未发现完整 code / access token / refresh token 写日志的代码路径。

### webhook 签名与幂等

- 正式 webhook 共用 `_handle_douyin_webhook`。
- production 下 `config.is_douyin_webhook_auth_required()` 强制验签；非生产环境按 `DOUYIN_WEBHOOK_AUTH_REQUIRED` 配置。
- `verify_signature` 校验 timestamp、signature，并使用 HMAC 比较。
- 缺签名、签名错误、timestamp 过期会拒绝。
- 事件持久化使用 event_key 做幂等；重复事件不会重复调度自动回复。
- `webhook-observe` / `callback` 在默认观察模式下不进入正式处理；但当 `DY_LIVE_CHECK_FORWARD_TO_FORMAL=true` 时，会以 `skip_signature_verification=True` 调用正式处理管线，这是明确的加固风险点。

## 4. 风险矩阵

| 风险项 | 接口 | 当前状态 | 风险等级 | 建议任务 |
|---|---|---|---|---|
| webhook-observe 可绕过正式签名进入正式管线 | `/integrations/douyin/live-check/webhook-observe`、`/integrations/douyin/live-check/callback` | 开关开启时使用 `skip_signature_verification=True`，可能无签名写入正式事件处理流程 | 高 | `P1-LIVE-CHECK-WEBHOOK-OBSERVE-SIGNATURE-GUARD-1` |
| OAuth state 缺少完整强校验闭环 | `/integrations/douyin/live-check/oauth-callback`、`/integrations/douyin/live-check/auth-redirect` | 未发现 state 生成、校验、一次性消费、过期和商户绑定闭环 | 高 | `P1-LIVE-CHECK-OAUTH-STATE-HARDEN-1` |
| auth-redirect 回跳目标白名单需确认 | `/integrations/douyin/live-check/auth-redirect` | 未确认回跳 URL 被限制在可信前端域名 | 中 | `P1-LIVE-CHECK-OAUTH-REDIRECT-WHITELIST-1` |
| live-check 账号列表可能跨商户暴露 | `/integrations/douyin/live-check/accounts` | 入口有登录和权限，但查询服务未显式传入当前商户上下文 | 中 | `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` |
| 私信发送服务层缺少显式商户归属校验 | `/integrations/douyin/live-check/messages/send` | 入口有登录和权限，发送上下文边界完整；但服务层未按当前商户强校验 conversation/account 归属 | 中 | `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` |
| 资源下载允许请求体 URL 覆盖事件资源 URL | `/integrations/douyin/live-check/resources/download` | 请求体可传 `url`，未看到 URL 协议 / 域名白名单；风险主要是向上游传任意资源 URL | 中 | `P1-LIVE-CHECK-RESOURCE-SSRF-GUARD-1` |
| 资源下载缺少显式商户 / 账号归属校验 | `/integrations/douyin/live-check/resources/download` | 入口有登录和权限，但服务层未按当前商户强校验资源所属账号 | 中 | `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` |
| 图片上传缺少 open_id 归属校验 | `/integrations/douyin/live-check/resources/upload-image` | 文件类型和大小有限制，但未看到 open_id 归属当前商户的强校验 | 中 | `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` |
| 原始 webhook payload 持久化可能包含敏感字段 | 正式 webhook 事件表 | 会保存 raw_body，业务上便于追溯，但可能包含手机号、微信号、昵称或私信内容 | 中 | `P1-LIVE-CHECK-LOG-REDACTION-1` |
| 私信发送记录持久化明文内容 | `/integrations/douyin/live-check/messages/send` | 发送记录包含 content、请求 / 响应摘要字段，需确认是否符合隐私留存策略 | 中 | `P1-LIVE-CHECK-LOG-REDACTION-1` |
| 公网暴露面缺少路径级反代策略说明 | `/api/*` 反代假设下的 callback / observe / live-check 路径 | 正式 webhook 和 OAuth callback 公网可达有业务合理性；observe/debug 类入口不宜长期公网可达 | 中 | `P1-LIVE-CHECK-PUBLIC-EXPOSURE-GATE-1` |

## 5. 已满足的安全边界

- 正式 webhook 在 production 下强制签名校验。
- 正式 webhook 签名校验包含 timestamp 漂移检查。
- 正式 webhook 使用 HMAC 比较，避免普通字符串比较问题。
- 正式 webhook 有 event_key 幂等逻辑，重复事件不会重复调度自动回复。
- `im_send_msg` 不会创建线索，不会作为自动回复调度来源。
- `messages/send` 要求 `manual_confirmed=true`。
- 私信发送上下文只允许 `im_receive_msg` / `im_enter_direct_msg`，拒绝 `im_send_msg` 作为发送上下文，保留 `28003082` 修复边界。
- 私信发送保留 24 小时上下文限制。
- `scene` 由后端根据发送上下文推导，不信任前端传入值。
- 前端人工发送只在人工接管模式下传 `manual_confirmed: true`。
- 前端图片上传成功后只展示 `image_id`，不会自动触发私信发送。
- 图片上传限制扩展名、文件头和 10MB 大小，不保存 `image_base64` 明文。
- OpenAPI 客户端已对 token、secret、base64 等敏感键做日志脱敏处理。
- OAuth callback 观察摘要未记录完整 code。

## 6. 发现的问题

### 6.1 webhook-observe 转正式管线时绕过签名

`webhook-observe` / `callback` 观察入口在默认模式下风险较低。但当 `DY_LIVE_CHECK_FORWARD_TO_FORMAL=true` 时，会跳过签名校验进入正式 webhook 管线。若该入口公网可达且开关误开，外部请求可能写入事件或线索，并触发后续自动回复 dry-run 相关流程。

建议后续将 observe 入口和正式入口分离：observe 只能只读记录或内存观察；任何进入正式管线的请求都必须复用正式签名校验。

### 6.2 OAuth state 缺少强绑定

当前未发现 OAuth state 的完整安全闭环。风险包括 CSRF、授权结果绑定错误商户、授权回跳目标被污染、用户在未登录上下文触发授权同步等。

建议后续 state 至少包含不可预测随机值、有效期、一次性消费、发起商户、发起账号、可信 redirect 目标，并在 callback / auth-redirect 中强制校验。

### 6.3 live-check 服务层商户归属校验不足

浏览器业务接口已经接入登录和权限门禁，这是关键进展。但账号查询、私信发送、资源下载、图片上传的服务层仍需要显式使用当前 `merchant_id` 校验 account / open_id / conversation / resource 归属。

`P1-LIVE-CHECK-MERCHANT-ISOLATION-1` 已完成最小修复：accounts、messages/send、resources/download、resources/upload-image 已接入当前商户归属校验。后续仍建议在数据模型中补齐更结构化的 account / conversation / resource 归属字段，减少从 raw event 解析的兼容逻辑。

### 6.4 资源下载 URL 边界不足

资源下载接口允许请求体中的 `url` 覆盖从事件中解析出的资源 URL。虽然当前服务不是直接下载任意 URL，而是调用上游 OpenAPI 获取下载地址，但仍可能变成“让后端代用户向上游提交任意资源 URL”的通道。

建议后续只允许使用已入库 webhook 事件里的资源 URL，或增加 URL 协议、域名、路径、大小、媒体类型白名单。

### 6.5 日志与持久化脱敏仍需产品级策略

当前日志层面已避免打印 token、secret、base64 明文；但数据库中的 raw_body、私信内容、发送请求 / 响应摘要仍可能含敏感信息。该问题不一定是代码错误，因为原始事件留存有排障和审计价值，但需要明确留存周期、访问权限、脱敏展示和导出策略。

## 7. 建议修复任务拆分

| 任务 | 建议目标 |
|---|---|
| `P1-LIVE-CHECK-WEBHOOK-OBSERVE-SIGNATURE-GUARD-1` | 禁止 observe 入口跳过签名进入正式管线；如需转正式处理，必须复用正式 webhook 签名校验 |
| `P1-LIVE-CHECK-OAUTH-STATE-HARDEN-1` | 实现 OAuth state 的随机生成、服务端保存、过期、一次性消费、商户绑定和回跳目标绑定 |
| `P1-LIVE-CHECK-OAUTH-REDIRECT-WHITELIST-1` | 限制授权完成后的前端回跳 URL，只允许可信域名 / 固定路径 |
| `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` | 对 accounts、messages/send、resources/download、resources/upload-image 增加服务层 merchant/account/open_id/conversation 归属校验 |
| `P1-LIVE-CHECK-RESOURCE-SSRF-GUARD-1` | 禁止任意 URL 覆盖，或增加资源 URL 白名单、协议限制、事件来源校验和测试覆盖 |
| `P1-LIVE-CHECK-LOG-REDACTION-1` | 梳理 raw_body、私信内容、send_msg_context、错误响应的脱敏、留存周期和访问权限 |
| `P1-LIVE-CHECK-PUBLIC-EXPOSURE-GATE-1` | 给宝塔 / Nginx 反代提供路径级暴露建议，区分正式公网入口和仅内部观察入口 |

## 8. 测试覆盖现状

### 已覆盖

- live-check `accounts`、`sync-bind-info`、`messages/send`、`resources/download`、`resources/upload-image` 缺权限时返回 403，且不调用服务。
- `messages/send` 缺少 `manual_confirmed=true` 时拒绝。
- 私信发送上下文保留 `28003082` 边界，拒绝 `im_send_msg` 作为发送上下文。
- 资源下载、图片上传的基础输入校验和敏感字段不泄露。
- OAuth callback 观察摘要不暴露完整 code。
- auth status 按当前商户过滤。
- 正式 webhook 签名成功、缺头、错签、timestamp 过期。
- production 下正式 webhook 缺签名拒绝。
- `/webhook/douyin` 和 `/integrations/douyin/webhook` 共用正式行为。
- webhook duplicate event 幂等。
- `im_send_msg` 不创建 lead、不触发自动回复调度。
- 9000 可信代理相关测试覆盖不信任前端 `merchant_id`、账号归属等边界。

### 缺口

- OAuth state 生成、不可预测、过期、一次性消费、商户绑定、redirect 目标绑定测试。
- `webhook-observe` 开关误开时不能绕过签名进入正式管线的测试。
- live-check `accounts` 的商户隔离测试已在 `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` 补齐。
- `messages/send` 按当前商户校验 conversation/account/customer open_id 归属的测试已在 `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` 补齐。
- `resources/download` 按当前商户校验资源归属的测试已在 `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` 补齐。
- `resources/download` 禁止任意 URL / URL 白名单测试。
- `resources/upload-image` 按当前商户校验 open_id 归属的测试已在 `P1-LIVE-CHECK-MERCHANT-ISOLATION-1` 补齐。
- raw_body、私信内容、send_msg_context 的脱敏和留存策略测试。
- 公网路径暴露策略无法完全由单元测试覆盖，需要部署配置审计或集成验收清单。

## 9. 不改内容

本轮未修改以下内容：

- 不改业务代码。
- 不改 NewCar 登录。
- 不恢复 `/auth/callback`。
- 不改 RAG / 知识库。
- 不改 Local Agent。
- 不改 19000。
- 不改私信真实发送逻辑。
- 不改 webhook 状态机。
- 不改自动回复链路。
- 不触发真实私信发送。
- 不调用真实上游写接口。
- 不调整前端菜单和页面入口。
- 不修改宝塔 / Nginx 反代配置。

## 10. 待确认事项

- 生产环境是否会暴露完整 `/api/*` 到 9000，还是已有路径级 allowlist。
- `DY_LIVE_CHECK_FORWARD_TO_FORMAL` 在生产环境是否保证永远关闭。
- `auth-redirect` 的前端回跳 URL 当前配置来源和生产域名白名单。
- OAuth 授权发起时是否存在其他文件生成 state，本轮扫描未确认到完整闭环。
- `accounts` fallback 数据是否可能跨商户返回历史 webhook 事件中的账号。
- 私信发送、资源下载和图片上传的账号 / 会话 / open_id 是否有上游侧二次归属校验；即便上游有校验，本系统仍建议做本地显式校验。
- webhook raw_body 和私信内容的保留周期、访问权限、导出策略。
- observe 类入口是否仍需公网可达；若仅用于本地排障，建议从反代层下线或加内部访问限制。

## 11. P1-LIVE-CHECK-WEBHOOK-OBSERVE-SIGNATURE-GUARD-1

本轮已修复 `webhook-observe` / `callback` 在开启 `DY_LIVE_CHECK_FORWARD_TO_FORMAL=true` 后绕过正式 webhook 签名校验的问题。

当前行为：

- 观察模式：`DY_LIVE_CHECK_FORWARD_TO_FORMAL=false` 时，只记录 live-check 观察摘要，不写入正式 `douyin_webhook_events` / `douyin_leads`。
- 转正式管线模式：`DY_LIVE_CHECK_FORWARD_TO_FORMAL=true` 时，复用正式 `_handle_douyin_webhook()` 入口，不再设置跳过签名校验。
- 缺少 `X-Auth-Timestamp` 或 `Authorization` 时，按正式 webhook 规则返回 401，不进入正式管线。
- 签名错误时，按正式 webhook 规则返回 401，不进入正式管线。
- 签名正确时，继续进入正式 webhook 处理流程，保留 timestamp 漂移检查、raw event 留存、event_key 幂等、线索写入和自动回复 dry-run 调度边界。
- 重复 event_key 仍按正式 webhook 幂等逻辑处理，不重复创建正式线索。

本轮未修改：

- OAuth state 加固。
- OAuth redirect 白名单。
- live-check merchant isolation。
- resource download SSRF 防护。
- raw_body / 私信内容脱敏和留存策略。
- NewCar 登录。
- RAG / 知识库。
- Local Agent / 19000。
- 私信真实发送逻辑和自动发送链路。

## 12. P1-LIVE-CHECK-MERCHANT-ISOLATION-1

本轮已对 live-check 浏览器业务接口补齐最小商户归属校验，目标是防止已登录 A 商户通过构造 `account_open_id`、`conversation_short_id`、`open_id` 或资源上下文读取、下载、上传或发送到 B 商户数据。

### 12.1 本轮发现的缺口

- `GET /integrations/douyin/live-check/accounts` 原先在已登录浏览器上下文下仍会混入无商户归属的内存账号 / webhook 事件兜底账号，存在跨商户账号可见风险。
- `POST /integrations/douyin/live-check/messages/send` 原先只依赖 `send_msg_context` 和 24 小时窗口，未显式确认该企业号属于当前 `RequestContext.merchant_id`。
- `POST /integrations/douyin/live-check/resources/download` 原先未在调用上游前确认资源事件对应企业号属于当前商户，也未拒绝请求体伪造不匹配的 `open_id`。
- `POST /integrations/douyin/live-check/resources/upload-image` 原先带 `open_id` 上传时未确认该客户 open_id 出现在当前商户授权企业号会话中。

### 12.2 修复范围

- `accounts`：只返回 `bind_status=1` 且 `merchant_id=context.merchant_id` 的持久化授权账号；登录态浏览器接口不再混入无归属 memory / event fallback。
- `messages/send`：继续要求 NewCar 登录和 `auto_wechat:douyin_ai_cs` 权限；发送前校验 send context 派生出的 `account_open_id` 属于当前商户；请求体伪造 `merchant_id` 不生效；请求体 `customer_open_id` 与会话上下文不匹配时返回 403。
- `resources/download`：从入库 webhook 事件解析企业号与客户 open_id；企业号不属于当前商户时返回 403；请求体 `open_id` 与事件客户不一致时返回 403。
- `resources/upload-image`：传入 `open_id` 时，必须能在当前商户授权企业号的会话事件中找到该客户；不传 `open_id` 的通用素材上传保持原行为。
- `sync-bind-info`：保持已有策略，继续使用 `RequestContext.merchant_id` 写入 / 回填账号归属，跨商户 owner conflict 不覆盖。

### 12.3 归属校验规则

| 对象 | 校验规则 | 失败策略 |
|---|---|---|
| merchant | 所有 live-check 浏览器业务接口使用 `RequestContext`，不信任请求体 `merchant_id` / `tenant_id` | 缺少可信商户上下文返回 403 |
| account_open_id | 必须存在于 `DouyinAuthorizedAccount`，`bind_status=1`，且 `merchant_id` 等于当前商户 | `DOUYIN_ACCOUNT_FORBIDDEN` 或 `DOUYIN_RESOURCE_FORBIDDEN` |
| conversation_short_id | 发送前只使用服务端入库的 `im_receive_msg` / `im_enter_direct_msg` 生成 send context | 不存在返回原有 send context 错误；客户不匹配返回 `DOUYIN_CONVERSATION_FORBIDDEN` |
| customer open_id | 必须与 send context 或当前商户授权企业号事件中的客户一致 | `DOUYIN_CONVERSATION_FORBIDDEN` 或 `DOUYIN_RESOURCE_FORBIDDEN` |
| resource | 必须来自可解析的入库事件，且事件企业号属于当前商户 | `DOUYIN_RESOURCE_FORBIDDEN` |

### 12.4 保持不变

- 不改 NewCar exchange-code。
- 不恢复 `/auth/callback`。
- 不改 webhook 签名。
- 不改 OAuth state。
- 不改 resource SSRF，本轮只做归属校验；URL 白名单仍留给 `P1-LIVE-CHECK-RESOURCE-SSRF-GUARD-1`。
- 不改真实私信发送业务语义，不触发真实私信发送。
- 不改 RAG / 知识库。
- 不改 Local Agent / 19000。
- 不改自动发送链路。

### 12.5 测试结果

- `python -m pytest tests/test_douyin_live_check.py -q`：99 passed。

## 13. P1-LIVE-CHECK-RESOURCE-SSRF-GUARD-1

本轮已收口 live-check 资源下载接口的 URL 来源和 SSRF 风险，重点防止浏览器请求体传入任意 URL 后，让 9000 代为向上游提交 localhost、内网、云 metadata 或非可信资源地址。

### 13.1 本轮发现的缺口

- `POST /integrations/douyin/live-check/resources/download` 原先会优先使用请求体 `url`，再回退到入库 webhook 事件里的资源 URL。
- 当前 9000 不直接 GET 该资源 URL，而是调用抖音 OpenAPI `/download_resource` 获取下载地址；但请求体 URL 覆盖仍会形成“浏览器让后端代提交任意资源 URL 给上游”的通道。
- `POST /integrations/douyin/live-check/resources/upload-image` 不接受 URL，只接受 `file_name`、`image_base64` 和可选 `open_id`；本轮未发现上传接口存在前端任意 URL 代请求路径。

### 13.2 修复范围

- `resources/download` 只使用入库 webhook 事件中解析出的资源 URL。
- 请求体 `url` 仅作为兼容字段保留；只有与事件 URL 完全一致时才允许通过，不允许覆盖事件 URL。
- 请求体提供 `url` 但事件中没有资源 URL 时，返回 403，不进入上游调用。
- URL 校验失败统一返回 `DOUYIN_RESOURCE_URL_FORBIDDEN`，错误响应不回显完整 URL，避免 query 中的 token 泄露。
- 保留上一轮 merchant/account/open_id 归属校验，不因 URL 校验改动放宽跨商户访问。

### 13.3 URL 安全校验规则

| 规则 | 当前策略 |
|---|---|
| URL 来源 | 只信任已入库 webhook 事件资源 URL；请求体 URL 不得覆盖 |
| scheme | 只允许 `http` / `https` |
| localhost | 拒绝 `localhost`、`localhost.localdomain`、`127.0.0.0/8`、`::1` |
| 内网 / 特殊地址 | 字面量 IP 使用 `ip.is_global` 校验，拒绝私网、link-local、loopback、unspecified、reserved、metadata 等非公网地址 |
| metadata | 拒绝 `169.254.169.254` 等 link-local metadata 地址 |
| 域名白名单 | 新增可选 `DOUYIN_RESOURCE_ALLOWED_HOSTS`；为空时先做 scheme 和非公网 IP 拦截，生产确认抖音资源域名后建议显式配置 |
| redirect | 9000 当前不直接下载资源 URL，不跟随该 URL 的重定向；如未来改为 9000 直连下载，需另开任务补 redirect 后 URL 复验、大小和 Content-Type 限制 |
| 响应大小 / 类型 | 当前资源 URL 不由 9000 直连下载，大小和类型由上游 OpenAPI 处理；upload-image 继续保留原有文件类型、文件头和 10MB 限制 |

### 13.4 新增配置

- `DOUYIN_RESOURCE_ALLOWED_HOSTS`

配置格式为逗号分隔域名列表，例如：

```text
DOUYIN_RESOURCE_ALLOWED_HOSTS=api-normal.amemv.com
```

留空时不启用域名白名单，只执行 scheme、localhost、私网、link-local、metadata 和非公网 IP 拦截。抖音资源真实域名仍需上游确认，生产环境建议确认后配置白名单。

### 13.5 保持不变

- 不改 NewCar 登录。
- 不恢复 `/auth/callback`。
- 不改 webhook 签名。
- 不改 OAuth state。
- 不改 live-check 商户归属校验语义，只复用上一轮已完成的边界。
- 不改 RAG / 知识库。
- 不改 Local Agent / 19000。
- 不改自动发送链路。
- 不改真实私信发送业务语义，不触发真实私信发送。
- 不调用真实上游写接口。

### 13.6 测试结果

- `python -m pytest tests/test_douyin_live_check.py::test_download_resource_rejects_unsafe_request_url_without_calling_upstream -q`：7 passed。
- `python -m pytest tests/test_douyin_live_check.py::test_download_resource_allows_request_url_when_it_matches_event_url tests/test_douyin_live_check.py::test_download_resource_success_uses_signed_openapi_body_and_persists_record tests/test_douyin_live_check.py::test_download_resource_rejects_other_merchant_account_without_calling_upstream tests/test_douyin_live_check.py::test_upload_image_rejects_invalid_inputs_without_calling_upstream -q`：4 passed。
- `python -m pytest tests/test_douyin_live_check.py::test_download_resource_rejects_event_url_outside_configured_allowed_hosts -q`：1 passed。
- `python -m pytest tests/test_douyin_live_check.py -q`：108 passed。

## 14. P1-LIVE-CHECK-OAUTH-STATE-HARDEN-1

本轮已收口抖音 live-check 授权发起与 `auth-redirect` 回跳的 OAuth state 安全边界，目标是防止伪造回调、跨商户绑定和重复回调重放。

### 14.1 原始问题

- `GET /integrations/douyin/live-check/auth-url` 原先不生成服务端 state，也不绑定当前商户上下文。
- `GET /integrations/douyin/live-check/auth-redirect` 原先使用可选浏览器登录态；如果回跳时没有登录态或上下文异常，仍可能继续同步授权账号。
- `auth-redirect` 原先没有校验 state 是否存在、是否过期、是否已消费，也不能证明本次回调来自当前商户发起的授权。
- 回调 query 中如出现 `merchant_id` / `redirect_url` 等字段，原实现没有明确用 state 固定可信归属和回跳目标。

### 14.2 新的 state 生成规则

- 发起授权时必须经过 NewCar `RequestContext`，并具备 `auto_wechat:douyin_ai_cs` 权限。
- 后端使用 `secrets.token_urlsafe(32)` 生成高熵随机 state。
- state 会追加到传给抖音上游的 `auth_redirect_url` 中，由抖音授权完成后带回。
- state 绑定字段包括：
  - `merchant_id`
  - `user_id`
  - `source_system`
  - `redirect_target`
  - `created_at`
  - `expires_at`
  - `consumed_at`

### 14.3 state 存储位置

新增持久化表：

```text
douyin_oauth_states
```

该表通过迁移 `migrations/versions/0024_douyin_oauth_states.sql` 创建。生产不依赖单进程内存，服务重启后仍可判断 state 是否存在、过期或已消费。

### 14.4 过期和一次性消费

- 新增配置：`DY_OAUTH_STATE_TTL_SECONDS`
- 默认值：`900` 秒，即 15 分钟。
- `auth-redirect` 收到回调后先校验并消费 state，再进入 `/list_bind_info` 同步绑定流程。
- 缺失 state：返回 `DOUYIN_OAUTH_STATE_MISSING`。
- state 不存在或 source_system 不匹配：返回 `DOUYIN_OAUTH_STATE_INVALID`。
- state 过期：返回 `DOUYIN_OAUTH_STATE_EXPIRED`。
- state 已消费：返回 `DOUYIN_OAUTH_STATE_REPLAYED`。
- 重放同一个 state 不会再次进入绑定流程。

### 14.5 merchant_id 归属来源

- `auth-redirect` 不信任 query/body 中的 `merchant_id`。
- 绑定账号时使用 `douyin_oauth_states.merchant_id` 还原可信 `RequestContext`。
- A 商户发起的 state 即使被带上 `merchant_id=B` 的 query 参数，也只能按 A 商户上下文处理；若 state 已消费则直接拒绝。

### 14.6 callback redirect 安全规则

- 最终回跳前端地址来自发起授权时写入 state 的 `redirect_target`。
- 请求 query 中的 `redirect_url` 不参与回跳决策，避免开放重定向。
- 当前 `redirect_target` 来源为后端配置 `DY_AUTH_REDIRECT_FRONTEND_URL`，未配置时按既有 `PUBLIC_BASE_URL` 兜底；生产建议显式配置可信前端域名。

### 14.7 保持不变

- 不改 NewCar 登录协议。
- 不恢复或修改 NewCar `/auth/callback`。
- 不改 webhook 签名。
- 不改资源 SSRF 逻辑。
- 不改 merchant isolation 已有语义。
- 不改 RAG / 知识库。
- 不改 Local Agent / 19000。
- 不改自动发送链路。
- 不触发真实私信发送，不调用真实上游写接口；测试均使用 mock。

### 14.8 测试结果

- `python -m pytest tests/test_douyin_live_check.py -q`：115 passed。
- `python -m pytest tests/test_db_migration_runner.py::test_0024_douyin_oauth_states_creates_table_and_indexes -q`：1 passed。
- `python -m pytest tests/test_auth_context.py -q`：27 passed。

## 15. P1-LIVE-CHECK-OAUTH-REDIRECT-WHITELIST-1

本轮继续收口抖音 live-check OAuth 授权完成后的前端跳转地址，防止配置错误、历史脏 state 或恶意回调参数造成开放重定向。

### 15.1 原 redirect 风险点

- `auth-url` 发起授权时，原实现会把 `DY_AUTH_REDIRECT_FRONTEND_URL`、`PUBLIC_BASE_URL` 或历史兜底值作为 `redirect_target` 写入 state，未做显式 origin 白名单校验。
- `auth-redirect` 回跳时，原实现优先使用 state 中保存的 `redirect_target`，未对历史脏数据做二次校验。
- callback query 中的 `redirect_url` 已不参与决策，本轮继续保持该边界。

### 15.2 新增配置项

- `DY_AUTH_REDIRECT_ALLOWED_ORIGINS`

该配置为逗号分隔的可信前端 origin 白名单，例如：

```text
DY_AUTH_REDIRECT_ALLOWED_ORIGINS=https://douyinapi.misanduo.com,http://127.0.0.1:5173,http://192.168.110.113:5173
```

### 15.3 allowed origins 规则

- 只允许 `http` / `https`。
- origin 必须精确命中 `DY_AUTH_REDIRECT_ALLOWED_ORIGINS`。
- 禁止 scheme-relative URL，例如 `//evil.example.com`。
- 禁止 `javascript:`、`data:`、`file:`、`ftp:` 等非 http(s) scheme。
- 禁止带用户名密码的 URL，例如 `https://user:pass@example.com`。
- production 下未配置白名单返回 `DOUYIN_OAUTH_REDIRECT_CONFIG_INVALID`，不静默放开。
- production 下即使显式配置，也拒绝 localhost、127.0.0.1、私网和非公网 IP。

### 15.4 allowed paths 规则

当前授权结果页固定跳转到 `/douyin-ai-cs`。如果配置或历史 state 中携带路径，只接受明确站内路径：

- `/douyin-ai-cs`
- `/douyin-cs/workbench`
- `/settings/douyin`
- `/wechat-assistant`

最终实际回跳仍由后端拼接为可信 origin + `/douyin-ai-cs` + 安全结果 query，不使用外部传入路径覆盖最终结果页。

### 15.5 development / production 差异

- development：可以使用 localhost、127.0.0.1 或局域网前端地址，但必须显式加入 `DY_AUTH_REDIRECT_ALLOWED_ORIGINS`。
- production：必须显式配置 `DY_AUTH_REDIRECT_ALLOWED_ORIGINS`，且不允许 localhost / 127.0.0.1 / 私网地址作为回跳 origin。

### 15.6 成功、失败、取消授权的跳转策略

- 成功授权：使用校验后的 state redirect origin，跳转 `/douyin-ai-cs?auth=success...`。
- 授权失败或取消：同样使用校验后的 state redirect origin，跳转 `/douyin-ai-cs?auth=failed...`。
- state 缺失、无效、过期、重放：使用当前配置校验后的安全 origin，跳转失败结果页。
- 历史 state 中的非法 `redirect_target`：不进入绑定同步，回退到当前配置的安全 origin，并返回 `DOUYIN_OAUTH_REDIRECT_FORBIDDEN`。
- 错误跳转不携带完整 code、token、secret 或 state 原文。

### 15.7 未改内容

- 不改 NewCar 登录。
- 不恢复或修改 NewCar `/auth/callback`。
- 不改 webhook 签名。
- 不改资源 SSRF。
- 不改 merchant isolation。
- 不改 RAG / 知识库。
- 不改 Local Agent / 19000。
- 不改自动发送链路。
- 不触发真实私信发送。
- 不调用真实上游写接口；测试使用 mock。

### 15.8 测试结果

- `python -m pytest tests/test_douyin_live_check.py -q`：128 passed。
