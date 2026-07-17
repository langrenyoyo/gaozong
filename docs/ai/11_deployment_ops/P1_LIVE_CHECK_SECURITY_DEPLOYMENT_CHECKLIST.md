# P1 Live-Check Security Deployment Checklist

## 1. 范围

本文档用于收口 live-check 安全主线的最终复验和部署检查。范围仅覆盖抖音 live-check / webhook-observe / OAuth / 资源下载上传 / 私信发送的安全边界，不包含 NewCar 登录、Local Agent、19000、RAG / 知识库、自动发送链路。

## 2. 已完成任务

| 任务 | 提交 | 最终状态 |
|---|---|---|
| P1-LIVE-CHECK-WEBHOOK-OBSERVE-SIGNATURE-GUARD-1 | `158ddee fix: 防止live-check转正式管线绕过webhook验签` | 已完成 |
| P1-LIVE-CHECK-MERCHANT-ISOLATION-1 | `35d44a0 fix: 收口live-check商户归属校验` | 已完成 |
| P1-LIVE-CHECK-RESOURCE-SSRF-GUARD-1 | `0e63461 fix: 收口live-check资源下载URL安全校验` | 已完成 |
| P1-LIVE-CHECK-OAUTH-STATE-HARDEN-1 | `048091b fix: 强化抖音授权state校验` | 已完成 |
| P1-LIVE-CHECK-OAUTH-REDIRECT-WHITELIST-1 | `542fe78 fix: 收口抖音授权跳转白名单` | 已完成 |

## 3. 迁移要求

生产部署前必须确认目标运行库已应用迁移 `0024_douyin_oauth_states`。

本地 Docker 运行态库复验命令：

```bash
python migrations/migrate_sqlite.py --db-path docker-data/auto_wechat_9000/auto_wechat.db --status
```

本次复验结果：

```text
known_versions 包含 0024
applied_versions 包含 0024
pending_versions 为空
unknown_applied_versions 为空
```

如 `pending_versions` 包含 `0024`，不得继续上线，应先按既有迁移流程应用并备份数据库。

## 4. 部署配置清单

| 配置项 | development 建议 | production 要求 | 当前默认 | 风险 |
|---|---|---|---|---|
| `APP_ENV` | `development` | 必须设为 `production` | `development` | 未设为 production 会保留开发态兼容行为 |
| `DY_SECRET_KEY` | 可填测试密钥 | 必须配置真实 webhook 验签密钥 | 空 | 空值会导致生产 webhook 无法验签 |
| `DOUYIN_WEBHOOK_AUTH_REQUIRED` | 可为 `false` 便于本地联调 | 建议显式 `true`；production 下代码仍会强制验签 | `false` | 容易误解为生产可关闭，需结合 `APP_ENV=production` |
| `DY_ALLOWED_DRIFT_SECONDS` | 默认即可 | 按平台要求控制时间戳漂移窗口 | `300` | 过大增加重放窗口，过小可能误拒正常请求 |
| `DY_CALLBACK_URL` | 可指向测试回调地址 | 必须为公网可达且与抖音后台配置一致 | live-check observe 示例地址 | 配错会导致事件进错入口或收不到回调 |
| `DY_CALLBACK_EVENTS` | 按测试事件订阅 | 明确订阅所需事件，通常含 `im_receive_msg,im_send_msg,im_enter_direct_msg` | 三类私信事件 | 事件缺失会影响线索、发送上下文或观察数据 |
| `DY_LIVE_CHECK_FORWARD_TO_FORMAL` | 默认 `false`，只在联调时临时开启 | 默认应为 `false`；如开启必须保证签名头由可信上游传入 | `false` | 开启后会进入正式管线，必须保持验签和幂等边界 |
| `DY_OAUTH_STATE_TTL_SECONDS` | 默认 900 秒 | 默认 900 秒，按业务窗口评估后再改 | `900` | 过长增加重放窗口，过短影响扫码授权体验 |
| `DY_AUTH_REDIRECT_URL` | 指向创建 OAuth state 的同一套 9000 `/integrations/douyin/live-check/auth-redirect` | `https://merchant.xiaogaoai.cn/api/integrations/douyin/live-check/auth-redirect` | 空 | 指向其他服务器会导致 state 与账号同步分离，授权永久 pending；指向 `/oauth-callback` 只观察不写库 |
| `DY_AUTH_REDIRECT_FRONTEND_URL` | 配置本地或联调前端 origin | 配置生产可信前端 origin | 空，代码兜底固定安全 origin | 配错会导致授权完成后回不到前端 |
| `DY_AUTH_REDIRECT_ALLOWED_ORIGINS` | 显式列出本地和局域网 origin | 必须显式配置生产前端 origin；禁止 localhost、127.0.0.1、192.168.* | 空 | production 为空会拒绝跳转；误配内网地址会被拒绝 |
| `DOUYIN_RESOURCE_ALLOWED_HOSTS` | 可为空，至少拦截内网和危险 scheme | 上线前建议确认抖音真实资源域名后显式配置 | 空 | 为空时没有域名白名单，只做协议和内网拦截 |
| `DY_LIVE_CHECK_ENABLED` | 现场观察时临时 `true` | 默认应为 `false`，仅授权/观察窗口临时开启 | `false` | 长期开启会扩大公网可用入口 |

生产特别注意：

1. `DY_AUTH_REDIRECT_URL` 必须回到创建 OAuth state 的同一套 9000；当前生产值为 `https://merchant.xiaogaoai.cn/api/integrations/douyin/live-check/auth-redirect`。不得指向不同服务器上的 `callback.misanduo.com`，也不得指向只观察不写库的 `/oauth-callback`。
2. `DY_AUTH_REDIRECT_ALLOWED_ORIGINS` 必须显式配置真实可信前端 origin。
3. `DY_AUTH_REDIRECT_ALLOWED_ORIGINS` 不得包含 `localhost`、`127.0.0.1`、`192.168.*`、`10.*`、`172.16.*` 到 `172.31.*` 等内网地址。
4. `DOUYIN_RESOURCE_ALLOWED_HOSTS` 当前可为空，但上线前建议向抖音官方或实际回调样本确认资源域名后配置。
5. 生产必须从 `.env.production.example` 复制为 `.env.production.local` 后填写真实值，不得把 development / LAN 示例复制到生产。

## 5. 安全边界最终状态

### 5.1 Webhook

| 边界 | 当前状态 | 证据 |
|---|---|---|
| formal webhook 仍要求签名 | production 下强制验签 | `app/config.py::is_douyin_webhook_auth_required`、`app/routers/integrations.py::_handle_douyin_webhook` |
| webhook-observe / callback 转正式管线不绕过签名 | 开启 forward 时复用 `_handle_douyin_webhook` | `app/routers/douyin_live_check.py::_maybe_forward_to_formal` |
| 错误签名不能吞成 200 | `WebhookSignatureError` 转为 HTTP 错误 | `tests/test_douyin_live_check.py` 中 forward 签名错误用例 |
| 幂等仍生效 | 复用正式 webhook 的 `event_key` 查询和重复事件记录 | `app/integrations/douyin_webhook.py::find_existing_event` |

### 5.2 私信发送

| 边界 | 当前状态 | 证据 |
|---|---|---|
| `messages/send` 要求 NewCar 登录和权限 | 使用 `get_request_context_required` 与 `auto_wechat:douyin_ai_cs` | `app/routers/douyin_live_check.py` |
| `manual_confirmed=false` 拒绝发送 | 发送服务入口直接拒绝 | `app/services/douyin_private_message_send_service.py::send_private_message` |
| send context 只允许客户消息上下文 | 优先 `im_receive_msg` / `im_enter_direct_msg` | `tests/test_douyin_live_check.py` 28003082 回归用例 |
| `im_send_msg` 不能作为发送上下文 | 只有企业号发出消息时不调用上游 | `test_send_message_does_not_call_upstream_when_only_im_send_msg_exists` |
| scene 不信任前端 | 后端从命中事件推导 | `test_send_message_ignores_frontend_scene_and_derives_from_event_type` |
| 28003082 边界未破坏 | 混合会话取客户消息 `msg_id` | `test_send_message_picks_im_receive_msg_over_im_send_msg_for_reply_msg_id` |

### 5.3 商户归属

| 边界 | 当前状态 | 证据 |
|---|---|---|
| accounts 只返回当前商户账号 | 账号查询按 `RequestContext.merchant_id` 过滤 | `tests/test_douyin_live_check.py` accounts 跨商户用例 |
| send 校验账号归属 | 发送前校验 `account_open_id` 属于当前商户 | `app/services/douyin_merchant_isolation.py` |
| send 校验会话和客户归属 | `conversation_short_id` / `customer_open_id` 必须来自当前商户事件 | `test_send_message_rejects_cross_merchant_conversation` 等用例 |
| download 校验事件账号和客户归属 | 只允许当前商户事件资源 | `app/services/douyin_resource_download_service.py` |
| upload-image 校验客户归属 | `open_id` 必须属于当前商户授权企业号会话 | `app/services/douyin_image_upload_service.py` |
| 请求体 `merchant_id` / `tenant_id` 不被信任 | 后端使用 `RequestContext` | `test_send_message_ignores_forged_payload_merchant_id`、绑定伪造商户用例 |

### 5.4 资源 SSRF

| 边界 | 当前状态 | 证据 |
|---|---|---|
| download 只信任入库事件资源 URL | 从事件内容提取资源 URL | `app/services/douyin_resource_download_service.py::_resource_url_from_content` |
| 请求体 URL 不能覆盖事件 URL | 请求体只用于定位会话资源 | `tests/test_douyin_live_check.py` |
| 非 http/https 拒绝 | URL 校验拒绝危险 scheme | `_validate_resource_url` |
| localhost / 127.0.0.1 / ::1 拒绝 | 字面量 host 和 IP 校验 | `_validate_resource_url` |
| 私网 / link-local / metadata / reserved / unspecified IP 拒绝 | `ip_address(...).is_global` 判断 | `_validate_resource_url` |
| 错误响应不回显完整 URL | 返回固定错误码和短消息 | `DOUYIN_RESOURCE_URL_FORBIDDEN` |
| upload-image 保持类型和大小限制 | 仅图片 base64，最大 10MB | `app/services/douyin_image_upload_service.py` |

### 5.5 OAuth State

| 边界 | 当前状态 | 证据 |
|---|---|---|
| `/auth-url` 生成高熵 state | `secrets.token_urlsafe(32)` | `app/services/douyin_live_check_service.py::create_oauth_state` |
| state 持久化 | 表 `douyin_oauth_states` | `app/models.py::DouyinOAuthState`、`migrations/versions/0024_douyin_oauth_states.sql` |
| state 绑定商户 / 用户 / 来源 / 跳转目标 | 写入 `merchant_id`、`external_user_id`、`source_system`、`redirect_target` | `create_oauth_state` |
| state 有 TTL | 默认 900 秒 | `DY_OAUTH_STATE_TTL_SECONDS` |
| callback 校验存在、未过期、未消费 | `consume_oauth_state` | `tests/test_douyin_live_check.py` OAuth state 用例 |
| 成功后一次性消费 | 写入 `consumed_at` | `consume_oauth_state` |
| query `merchant_id` 不参与绑定 | 使用 state 还原 `RequestContext` | `test_auth_redirect_uses_state_merchant_and_ignores_forged_merchant_id_and_redirect` |
| 重放 state 拒绝 | 已消费返回 `DOUYIN_OAUTH_STATE_REPLAYED` | `test_auth_redirect_consumed_state_rejects_replay` |
| 商户前端状态按本次 state 轮询 | 仅查询同商户、state 创建后同步的有效账号；历史账号和全局回调不参与本次成功判定 | `test_auth_status_for_new_state_ignores_existing_account_until_current_attempt_syncs` |
| 跨商户 state 拒绝 | 当前登录商户与 state 归属不一致时返回 `DOUYIN_OAUTH_STATE_INVALID` | `test_auth_status_rejects_state_owned_by_other_merchant` |
| 弹窗关闭前验证正式账号列表 | 只有本次 open_id 已出现在 `/integrations/douyin/accounts` 后才允许关闭 | `test_frontend_douyin_authorization_is_scoped_to_current_state_and_verified_account` |

### 5.6 OAuth Redirect

| 边界 | 当前状态 | 证据 |
|---|---|---|
| 写入 state 前校验 redirect target | `/auth-url` 调用 `_auth_redirect_frontend_base` | `app/routers/douyin_live_check.py` |
| 使用 state.redirect_target 前二次校验 | `/auth-redirect` 调用 `_validate_auth_redirect_target` | `app/routers/douyin_live_check.py` |
| query `redirect_url` / `next` / `return_to` 不能覆盖 | callback 只使用 state 中的 redirect target | OAuth redirect 回归用例 |
| 只允许白名单 origin | `DY_AUTH_REDIRECT_ALLOWED_ORIGINS` 精确匹配 | `_auth_redirect_allowed_origins` |
| 只允许 http / https | scheme 校验 | `_normalize_auth_redirect_origin` / `_validate_auth_redirect_target` |
| 拒绝 `//evil.com`、`javascript:`、`data:`、`file:`、`ftp:` | 覆盖测试已加入 | redirect 白名单测试 |
| 拒绝 userinfo | `parts.username` / `parts.password` 拒绝 | redirect 白名单测试 |
| 最终进入安全站内路径 | 固定拼接 `/douyin-ai-cs` | `_auth_redirect_url` |

## 6. 上线前人工检查项

1. 确认生产 `.env` 设置 `APP_ENV=production`。
2. 确认 `DY_SECRET_KEY` 与抖音 webhook 签名密钥一致，且未提交到仓库。
3. 确认 `DY_AUTH_REDIRECT_ALLOWED_ORIGINS` 只包含生产可信前端 origin。
4. 确认 `DY_AUTH_REDIRECT_FRONTEND_URL` 命中 `DY_AUTH_REDIRECT_ALLOWED_ORIGINS`。
5. 确认 `DY_AUTH_REDIRECT_URL` 为 `https://merchant.xiaogaoai.cn/api/integrations/douyin/live-check/auth-redirect`，并与创建 OAuth state 的商户站 9000 使用同一数据库。
6. 确认生产 `DY_CALLBACK_URL` 指向预期正式入口或观察入口，不混用历史调试地址。
7. 确认 `DY_LIVE_CHECK_FORWARD_TO_FORMAL=false`，除非现场需要临时观察并已确认签名头可用。
8. 确认迁移 `0024_douyin_oauth_states` 已应用到目标库。
9. 确认 `DOUYIN_RESOURCE_ALLOWED_HOSTS` 是否需要按抖音官方资源域名显式配置。
10. 确认宝塔 / Nginx 反代只暴露必要 `/api/*`、webhook、OAuth callback 路径。
11. 确认不在生产保留 localhost / 127.0.0.1 / 局域网地址作为授权跳转白名单。

## 7. 回滚注意事项

1. 回滚代码前先确认是否已有授权 state 写入 `douyin_oauth_states`。旧代码可能不理解新 state 边界，回滚后不要继续使用旧授权回调。
2. 不建议回滚 `0024` 表结构；该表是 OAuth state 安全边界的一部分，删除会导致正在进行的授权回调失效。
3. 如必须回滚到 OAuth state 之前版本，应先关闭 live-check 授权入口，等待现有授权 state 过期，再回滚服务。
4. 如资源域名白名单配置导致误拒，可先清空 `DOUYIN_RESOURCE_ALLOWED_HOSTS` 回退到“协议 + 内网拦截”模式，但上线后仍应尽快确认官方资源域名。
5. 如 redirect 白名单误配导致授权无法回前端，应修正 `DY_AUTH_REDIRECT_ALLOWED_ORIGINS` 和 `DY_AUTH_REDIRECT_FRONTEND_URL`，不要临时放开外部域名。

## 8. 未纳入本轮事项

1. 不改 NewCar 登录和 `/auth/callback`。
2. 不改 webhook 签名算法。
3. 不改 live-check 商户隔离、资源 SSRF、OAuth state、OAuth redirect 的业务逻辑。
4. 不改 RAG / 知识库。
5. 不改 Local Agent / 19000。
6. 不改自动发送链路。
7. 不触发真实私信发送。
8. 不调用真实上游写接口。

## 9. 本次最终复验命令

```bash
git status --short
git log --oneline -n 8
python migrations/migrate_sqlite.py --db-path docker-data/auto_wechat_9000/auto_wechat.db --status
python -m pytest tests/test_douyin_live_check.py -q
python -m pytest tests/test_auth_context.py -q
python -m pytest tests/test_db_migration_runner.py -q
python -m pytest tests/test_douyin_ai_cs_proxy.py -q
git diff --check
```

本次复验结果：

| 命令 | 结果 |
|---|---|
| `git status --short` | 初始工作区干净 |
| `git log --oneline -n 8` | 包含 redirect 白名单、OAuth state、资源 SSRF、商户归属相关提交；webhook observe 签名提交在扩展 grep 中确认 |
| `migrate_sqlite.py --status` | `known_versions` / `applied_versions` 均包含 `0024`，`pending_versions=[]` |
| `python -m pytest tests/test_douyin_live_check.py -q` | 128 passed |
| `python -m pytest tests/test_auth_context.py -q` | 27 passed |
| `python -m pytest tests/test_db_migration_runner.py -q` | 11 passed |
| `python -m pytest tests/test_douyin_ai_cs_proxy.py -q` | 50 passed |
| `git diff --check` | passed |
