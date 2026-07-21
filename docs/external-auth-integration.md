# 外部系统登录接入说明

更新时间：2026-07-21

本文档提供给外部系统开发人员使用，用于接入当前内部商户系统维护的外部账号登录能力。

## 1. 接入边界

当前版本提供外部账号登录、一次性 code 换取外部 token、登录态校验、商户自助改密、管理员切换回内部系统、管理员当前浏览器退出、普通用户退出登录、权限回显和全局违禁词检查。

接入边界分为两层：

- NewCarProject 上游 `/api/external-auth/login`、`/api/external-auth/me` 负责账号、external token 和权限，本身不提供 auto_wechat 商户绑定；其响应中的 `merchant_id` 可以为 `null`。
- auto_wechat 9000 已通过本地 `external_merchant_bindings` 映射外部账号与商户，并由服务端 RequestContext 执行商户隔离、资源归属和权限校验。浏览器传入的 `merchant_id` 不可信，不能替代该服务端上下文。

NewCarProject 不负责 auto_wechat 的抖音账号、智能体、会话和线索资源归属；这些业务边界由 9000 校验。

外部账号和内部管理员共用 `users` 表，但通过 `account_scope` 隔离：

- `internal`：内部后台账号，只能登录当前内部管理系统。
- `external`：外部系统账号，只能通过外部登录接口获取外部 token。

登录会话共用 `user_sessions` 表，但通过 `session_scope` 显式隔离：

- `internal`：内部后台 token。
- `external`：外部系统 token。

## 2. 基础约定

### 2.1 Base URL

当前局域网联调环境：

```text
内部系统前端：http://192.168.110.19:5174
内部系统后端：http://192.168.110.19:8790
外部系统跳转地址：http://192.168.110.113:5173
外部系统跨域 Origin：http://192.168.110.113:9000
```

外部系统调用本项目接口时，当前联调 Base URL 使用：

```text
http://192.168.110.19:8790
```

线上环境请替换为内部系统后端的实际 HTTPS 域名。

### 2.2 CORS

如果外部系统前端直接从浏览器调用本后端，需要将外部系统域名加入后端 `CORS_ORIGINS`。

当前局域网联调已配置：

```text
CORS_ORIGINS=http://127.0.0.1:5174,http://localhost:5174,http://192.168.110.19:5174,http://192.168.110.113:5173,http://192.168.110.113:9000
EXTERNAL_APP_URL=http://192.168.110.113:5173
```

说明：

- `http://192.168.110.113:5173` 是外部账号登录成功后的跳转地址。
- `http://192.168.110.113:9000` 是外部系统浏览器请求来源，必须允许跨域。
- 如果外部系统实际由 `5173` 发起接口请求，`5173` 也必须保留在 `CORS_ORIGINS`。

线上示例：

```text
CORS_ORIGINS=https://internal.example.com,https://external.example.com
EXTERNAL_APP_URL=https://external.example.com
```

内部统一登录页识别到外部账号后，会返回并跳转到：

```text
http://192.168.110.113:5173?code=<one_time_code>&source=new_car_project
```

外部系统拿到 `code` 后，应立即调用 `POST /api/external-auth/exchange-code` 换取外部 token。

当前局域网联调可直接从以下 Origin 调用本项目后端：

```text
http://192.168.110.113:5173
http://192.168.110.113:9000
```

### 2.3 认证方式

外部系统登录成功后，后端返回 `token`。

后续请求统一带：

```http
Authorization: Bearer <token>
```

当前 auto_wechat 前端运行态使用浏览器 `sessionStorage` 保存 token，key 为：

```text
external_token
```

`external_auth_token` 是早期 E2E 指引中的误称，不作为当前运行态检查口径。

### 2.4 登录后回跳路径

auto_wechat 前端在跳转 NewCarProject 统一登录前，会把当前站内业务路径临时保存到浏览器 `sessionStorage`：

```text
newcar_redirect_path
newcar_redirect_path_saved_at
```

该路径只用于一次登录回跳，登录成功后会立即消费并删除。默认登录落点按当前账号实际权限计算，不固定到某个工作台：管理员进入第一个可访问的本地管理页或明确的归属提示页，普通用户进入第一个有权限的能力中心。

`newcar_redirect_path` 具备以下安全规则：

- 带 TTL，当前为 10 分钟；过期后回退到当前账号的权限默认页。
- 只允许站内业务路径，当前允许已登记的管理员路径，以及 `/douyin-cs`、`/leads`、`/compute`、`/agents`、`/wechat-assistant` 及其子路径。
- 拒绝空路径、外部 URL、`//` 开头路径、`/login`、`/auth/callback` 和未知路径。
- 非法或过期路径只做安全日志记录并回退默认工作台，不向用户展示技术细节。
- token 缺失或过期时，前端会先显示轻量提示，再跳转 NewCarProject 统一登录页。

### 2.5 登录和鉴权异常提示

auto_wechat 前端按错误类型区分是否自动跳转统一登录：

- `TOKEN_MISSING`：显示“正在前往统一登录，请稍候…”后自动跳转 NewCarProject 统一登录页。
- `TOKEN_EXPIRED` / `TOKEN_INVALID`：清理本地 `external_token`，显示“登录已过期，正在重新登录…”后自动跳转 NewCarProject 统一登录页。
- `EXTERNAL_MERCHANT_NOT_BOUND`：显示“账号已登录，但暂未绑定商户，请联系管理员开通服务。”，不自动跳统一登录，避免反复登录。
- `PERMISSION_DENIED`：显示“当前账号暂无访问该功能权限，请联系管理员开通。”，不自动跳统一登录。
- `LOCAL_AGENT_*`：表示 Local Agent 机器认证错误，不清理浏览器 `external_token`，不自动跳 NewCarProject 统一登录页。
- 一次性 code 换 token 失败：清理 URL 中的 `code` / `source`，显示“登录凭证已失效，请重新登录。”，不展示上游完整错误体。

auto_wechat 前端全局 `401` 拦截器只处理 NewCar 浏览器登录态错误。`LOCAL_AGENT_TOKEN_MISSING`、`LOCAL_AGENT_TOKEN_INVALID`、`LOCAL_AGENT_TOKEN_REQUIRED`、`LOCAL_AGENT_TOKEN_REVOKED` 以及其它 `LOCAL_AGENT_` 前缀错误会继续抛给页面处理。普通用户开始退出后，该拦截器会在退出请求和成功/失败结果页期间抑制 NewCar 自动跳转，避免先前已发出的请求在 token 吊销后返回 `401` 并覆盖退出结果页；用户主动点击“重新登录”前才恢复正常跳转。

`/wechat-assistant` 页面如果遇到 Local Agent token 错误，应作为业务接口错误展示轻量提示，例如“Local Agent 尚未完成授权或当前任务接口需要 Agent token”，并保持本机 `19000` 健康检查、运行状态、销售配置等其它模块可见。

错误页提供的操作：

- “重新登录”：清理 `external_token` 和 NewCar 回跳状态，然后跳转 NewCarProject 统一登录页；该操作不把当前错误页保存为回跳路径，重新登录成功后进入当前账号的权限默认页。
- “返回工作台”：用于权限不足场景，进入当前账号的权限默认页。

### 2.6 Token 隔离

在 NewCarProject 后端 Origin 上，external token 只能访问 `/api/external-auth/*` 这类外部接口。

它不能访问 NewCarProject 内部后台接口，例如：

- `/api/me`
- `/api/merchants`
- `/api/admin-users`
- `/api/roles`

NewCarProject 内部后台 token 也不能访问外部登录态接口 `/api/external-auth/me`。

在 auto_wechat 9000 Origin 上，浏览器可以将同一个 external token 作为 Bearer 调用本地鉴权门面 `/auth/me`、`/auth/logout` 和 `/auth/password`；`/auth/logout` 由 9000 代理调用 NewCarProject `/api/external-auth/logout`，`/auth/password` 由 9000 代理调用 NewCarProject `/api/external-auth/password`。其它 auto_wechat 业务接口是否可访问，以 9000 的 RequestContext、商户隔离和权限 gate 为准。这不表示 external token 可以访问 NewCarProject 内部 `/api/me`。

## 3. 权限要求

外部账号必须拥有：

```text
auto_wechat:use
```

否则登录会返回 `403`。

当前可分配的外部权限包括：

| 权限码                                      | 说明                         |
| ------------------------------------------- | ---------------------------- |
| `auto_wechat:use`                           | 进入外部系统                 |
| `auto_wechat:douyin_ai_cs`                  | 抖音 AI 小高客服             |
| `auto_wechat:leads`                         | AI 小高线索                  |
| `auto_wechat:agent`                         | 小高 AI 微信助手             |
| `auto_wechat:compute`                       | 小高算力                     |
| `auto_wechat:ai_edit`                       | AI 剪辑历史兼容权限          |
| `auto_wechat:admin:autoreply`                | 自动回复灰度历史兼容权限     |
| `auto_wechat:admin:ai_reply_records`        | AI 回复记录                  |
| `auto_wechat:admin:compute_config`           | 算力配置管理                 |
| `auto_wechat:admin:accounts`                 | 外部账号管理                 |
| `auto_wechat:admin:forbidden_words`          | 外部违禁词管理               |
| `auto_wechat:admin:return_visit_prompts`     | 回访提示词配置               |

接口返回的 `permissions` 是当前账号实际拥有的外部权限列表，外部系统应以后端返回值为准控制页面和接口能力。

## 4. 登录接口

### 4.1 内部统一登录页跳转外部系统

内部后台当前仍使用同一个登录界面。用户在内部后台登录页输入外部账号密码时，`/api/login` 会识别 `account_scope=external`，不返回内部后台 token，而是返回带短时一次性 code 的 `redirect_url`。code 只放在跳转地址中，不再作为独立 JSON 字段返回。

外部系统接收跳转后，应读取 URL 中的 `code`，立即调用 `POST /api/external-auth/exchange-code` 换取外部 token。code 只能使用一次，默认 120 秒过期。

重要限制：

- code 会绑定创建 code 时的客户端 IP 和 `User-Agent`。
- 推荐由接收跳转的外部系统前端页面，直接从浏览器调用 `exchange-code`。
- 如果由外部系统后端代为换 token，必须保证请求来源 IP 和 `User-Agent` 与创建 code 时一致；否则会返回 `401`。

内部登录页返回示例：

```json
{
  "account_scope": "external",
  "redirect_url": "http://192.168.110.113:5173?code=one_time_code&source=new_car_project",
  "external_auth_code_expires_in": 120,
  "external_auth_code_expires_at": "2026-07-01T10:02:00+08:00",
  "message": "外部账号登录成功，正在跳转外部系统",
  "permissions": ["auto_wechat:use"]
}
```

### 4.2 POST `/api/external-auth/exchange-code`

外部系统使用一次性 code 换取正式外部 token。

请求：

```http
POST /api/external-auth/exchange-code
Content-Type: application/json
```

```json
{
  "code": "one_time_code",
  "platform": "auto_wechat",
  "device_name": "Chrome 126 / Windows"
}
```

成功响应与 `POST /api/external-auth/login` 一致，包含 `token`、`user`、`permissions` 和 `permission_items`。

常见状态码：

| 状态码 | 场景                           |
| ------ | ------------------------------ |
| `400`  | code 为空                      |
| `401`  | code 无效、已使用或已过期      |
| `403`  | 外部账号缺少 `auto_wechat:use` |

### 4.3 POST `/api/external-auth/login`

外部系统使用账号密码登录。

该接口适用于外部系统自带账号密码登录页的场景。如果从内部统一登录页跳转，优先使用 `exchange-code`，不要让外部系统重复接收用户密码。

请求：

```http
POST /api/external-auth/login
Content-Type: application/json
```

```json
{
  "account": "13200000000",
  "password": "123456789",
  "platform": "auto_wechat",
  "device_name": "Chrome 126 / Windows"
}
```

字段说明：

| 字段          | 必填 | 说明                               |
| ------------- | ---- | ---------------------------------- |
| `account`     | 是   | 外部账号登录名，通常是手机号       |
| `password`    | 是   | 外部账号密码                       |
| `platform`    | 否   | 来源系统标识，建议传 `auto_wechat` |
| `device_name` | 否   | 设备或浏览器信息，用于审计         |

成功响应：

```json
{
  "ok": true,
  "token": "raw_token_string",
  "token_type": "Bearer",
  "expires_in": 86400,
  "expires_at": "2026-07-02T10:00:00+08:00",
  "account_scope": "external",
  "external_app_url": "http://192.168.110.113:5173",
  "user": {
    "id": 12,
    "account": "13200000000",
    "name": "外部账号",
    "status": "active",
    "account_scope": "external"
  },
  "permissions": [
    "auto_wechat:use",
    "auto_wechat:leads"
  ],
  "permission_items": [
    {
      "code": "auto_wechat:use",
      "name": "进入外部系统",
      "module": "外部系统"
    }
  ],
  "merchant_id": null,
  "merchant_ids": []
}
```

说明：

- `token` 只返回一次，推荐由外部系统后端写入 HttpOnly Cookie；纯前端临时接入时可暂存在内存或 sessionStorage。
- `expires_in` 以接口实际返回为准，部署侧可通过 `EXTERNAL_SESSION_HOURS` 调整。
- 该示例是 NewCarProject 上游响应；上游本身不提供 auto_wechat 商户绑定，因此 `merchant_id` 为 `null`、`merchant_ids` 为空数组。auto_wechat 9000 会通过本地 `external_merchant_bindings` 解析实际商户上下文，不能使用浏览器自填字段替代。
- 不要从 URL 长期携带 token。

失败响应示例：

```json
{
  "detail": "外部账号或密码错误"
}
```

常见状态码：

| 状态码 | 场景                                         |
| ------ | -------------------------------------------- |
| `401`  | 账号或密码错误                               |
| `403`  | 非外部账号、账号停用、缺少 `auto_wechat:use` |
| `429`  | 短时间内失败次数过多                         |

## 5. 查询当前登录态

### 5.1 GET `/api/external-auth/me`

用于外部系统刷新页面后恢复登录态和权限。

请求：

```http
GET /api/external-auth/me
Authorization: Bearer <token>
```

成功响应：

```json
{
  "ok": true,
  "account_scope": "external",
  "expires_at": "2026-07-02T10:00:00+08:00",
  "user": {
    "id": 12,
    "account": "13200000000",
    "name": "外部账号",
    "status": "active",
    "account_scope": "external"
  },
  "permissions": [
    "auto_wechat:use",
    "auto_wechat:leads"
  ],
  "permission_items": [
    {
      "code": "auto_wechat:use",
      "name": "进入外部系统",
      "module": "外部系统"
    }
  ],
  "merchant_id": null,
  "merchant_ids": []
}
```

该示例同样是 NewCarProject 上游登录态响应。`merchant_id=null` 只表示上游未提供 auto_wechat 绑定信息，不表示 9000 没有商户绑定；进入 auto_wechat 后，以 9000 `/auth/me` 返回的可信上下文和 RequestContext 为准。

失败响应：

```json
{
  "detail": "外部登录已过期，请重新登录"
}
```

状态码：

| 状态码 | 场景                               |
| ------ | ---------------------------------- |
| `401`  | token 缺失、无效、过期、账号不可用 |
| `403`  | 账号缺少 `auto_wechat:use`         |

## 6. 管理员切换、商户改密与退出

auto_wechat 侧栏底部动作按身份互斥：

- 管理员（`super_admin` 或持有任一 `auto_wechat:admin:*` 权限）：显示「切换到 NewCar」和「退出登录」两个动作。退出登录指退出当前浏览器的全部登录态，浏览器直调 NewCar，不走 9000 注销门面。
- 普通商户：显示「修改密码」和「退出登录」两个动作。退出登录指退出 auto_wechat 当前 external 会话，走 9000 注销门面；修改密码走 9000 改密门面。

管理员不显示商户改密，普通商户不显示切换到 NewCar。

### 6.1 POST `/api/external-auth/switch-to-internal`

auto_wechat 使用既有管理员判定：`super_admin` 或持有任一 `auto_wechat:admin:*` 权限。

一次性切换 code 绑定浏览器来源，因此必须由 auto_wechat 浏览器直接调用 NewCarProject，不能由 9000 代调。

请求：

```http
POST /api/external-auth/switch-to-internal
Authorization: Bearer <external_token>
Content-Type: application/json
```

```json
{}
```

成功响应：

```json
{
  "ok": true,
  "redirect_url": "https://internal.example.com/?internal_code=<one_time_code>&source=auto_wechat",
  "internal_auth_code_expires_in": 120,
  "internal_auth_code_expires_at": "2026-07-20T10:02:00+08:00"
}
```

前端只读取字符串 `redirect_url`，使用标准 URL 解析，并且只允许 `http:` / `https:` 协议。前端不硬编码目标地址，不记录或展示 `internal_code`，也不在切换前清理 auto_wechat 的 external token、回跳状态或 Local Agent token。请求失败、响应不是合法 JSON 或 URL 协议非法时，保持当前页面和登录态，显示固定可读错误并允许重试。

### 6.2 商户自助改密（`POST /auth/password`）

普通商户侧栏显示「修改密码」。改密由前端调用 auto_wechat 9000 门面，9000 只携带当前 Bearer 代理到 NewCarProject，不保存或记录密码：

```http
POST /auth/password
Authorization: Bearer <external_token>
Content-Type: application/json
```

```json
{
  "old_password": "原密码",
  "new_password": "新密码"
}
```

9000 不接受或转发 `user_id`、`merchant_id`；请求体只允许 `old_password`、`new_password`。9000 不保存密码，不在日志或响应中记录密码、token。成功后 NewCarProject 会撤销该用户全部 active 会话，external token 立即失效。

成功响应：

```json
{
  "ok": true,
  "relogin_required": true,
  "revoked_session_scope": "all"
}
```

错误码映射：

| 状态码 | 上游错误码 | 场景 |
| ------ | ---------- | ---- |
| `400` | `OLD_PASSWORD_INVALID` | 原密码错误 |
| `400` | `PASSWORD_TOO_SHORT` | 新密码不足 8 位 |
| `400` | `PASSWORD_UNCHANGED` | 新旧密码相同 |
| `401` | `TOKEN_INVALID` / `TOKEN_EXPIRED` / `TOKEN_MISSING` | token 缺失或失效 |
| `403` | `ACCOUNT_TYPE_NOT_ALLOWED` | 账号类型不允许改密（如管理员 token） |
| `403` | `ACCOUNT_DISABLED` | 账号停用 |
| `502` | `NEWCAR_PASSWORD_UNAVAILABLE` | 上游 5xx 或超时 |

停用账号在公共 external 鉴权入口统一返回 `401`（Owner 已于 2026-07-21 接受该语义）；9000 仍兼容把可达的 `ACCOUNT_DISABLED` 映射为 `403`。响应字符串不得出现 `old_password` / `new_password` 明文或 Bearer token。

前端改密结果按四态分流（`success` / `relogin` / `unknown` / `null`，取代旧布尔 `passwordReloginView`）：

- `success`：严格匹配 `ok===true && relogin_required===true && revoked_session_scope==="all"`，其他 `2xx` 一律不当作成功；清本地持久状态、卸载受保护页，进入状态页展示「密码已修改，请重新登录」。只有此态可展示「密码已修改」。
- `relogin`（`401`）：登录已失效，清本地持久状态、卸载受保护页，进入状态页展示「登录已失效，请重新登录」，不得声称密码已修改。
- `unknown`（超时 / 网络中断 / `5xx` / 异常 JSON / `2xx` 非白名单）：清本地持久状态、卸载受保护页，进入状态页展示「密码修改结果未知，请重新登录确认」，不得声称成功或失败，不恢复旧会话。
- `business`（`400` / `403`）：保留登录态、恢复 401 跳转，弹窗内提示错误供重试，不进入结果状态页。

改密期间前端启用并发 401 跳转抑制；`business` 恢复 401 跳转并保留登录态，`success` / `relogin` / `unknown` 则清本地持久状态并进入对应结果状态页，均不恢复 401 跳转、不恢复旧会话；`handleRelogin` 将结果状态恢复为 `null`。

### 6.3 普通用户退出 auto_wechat

普通商户侧栏显示「退出登录」。退出时浏览器调用 auto_wechat 9000：

```http
POST /auth/logout
Authorization: Bearer <external_token>
Content-Type: application/json
```

```json
{}
```

9000 再调用 NewCarProject `POST /api/external-auth/logout`。前端使用直接 `fetch`，并在发起退出前开启模块级鉴权重定向抑制，避免注销请求本身或其它已在途请求返回 `401` 后跳转 NewCar。该抑制在退出失败、重试和成功结果页持续有效，用户主动点击“重新登录”前关闭；管理员“切换到 NewCar”不读取或修改该状态。

无论 9000 注销成功或失败，前端都会卸载受保护页面，并清理 React Query 缓存、`external_token`、NewCar 回跳状态、Local Agent token 和当前用户状态；浏览器 URL 保持不变，也不会自动跳转 NewCar。成功时显示“已退出”；失败时显示“退出失败，请重试”和页面内重试按钮。失败请求使用的 token 只保留在当前 React 页面实例的 `useRef` 内存中，不写回 `sessionStorage`、`localStorage`、URL 或日志。

### 6.4 POST `/api/external-auth/logout`

该接口由 auto_wechat 9000 注销门面调用；外部系统若直接接入上游，也可按以下合同调用。

请求：

```http
POST /api/external-auth/logout
Authorization: Bearer <token>
Content-Type: application/json
```

请求体可为空对象：

```json
{}
```

成功响应：

```json
{
  "ok": true
}
```

退出后，该 token 会被吊销，再调用 `/api/external-auth/me` 会返回 `401`。

### 6.5 管理员当前浏览器退出（`POST /api/external-auth/logout-current-browser`）

管理员侧栏显示「退出登录」。因 9000 无法读取 NewCarProject 域 Cookie，管理员退出当前浏览器必须由浏览器直调 NewCarProject，不能由 9000 代调，也不等价于全设备退出。上游撤销当前 external 会话与同用户 internal session，并删除 `new_car_internal_session` / `new_car_internal_csrf` 两个 Cookie，返回可信 `redirect_url?logged_out=1`。

请求：

```http
POST /api/external-auth/logout-current-browser
Authorization: Bearer <external_token>
Content-Type: application/json
Cookie: new_car_internal_session=<internal_session>
```

请求体可为空对象 `{}`。浏览器必须携带 `credentials: "include"`，使 NewCar 域 Cookie 随请求发出；异用户 Cookie、无效 Cookie 和其他设备会话均不得被撤销，但响应始终返回删除两个 Cookie 的 `Set-Cookie` 头。

成功响应：

```json
{
  "logged_out": 1,
  "redirect_url": "https://internal.example.com/login?logged_out=1"
}
```

前端只接受绝对 HTTP(S) `redirect_url`，校验后使用 `window.location.replace()` 跳转，并清理 auto_wechat 的 sessionStorage external token、NewCar 回跳状态、Local Agent token 与 React Query 缓存。退出开始时启用并发 401 跳转抑制并卸载受保护页面；external token 只保留在页面内存 `useRef` 供重试，不写入 sessionStorage/localStorage/URL/日志。失败（503、超时、缺 redirect_url、晚到 401）时清本地持久状态、停留当前 URL 提示重试，不自动跳错系统、不显示 token 或响应原文。管理员退出不调用 9000 `/auth/logout`，也不调用 `switch-to-internal`。

## 7. 全局违禁词检查

### 7.1 POST `/api/external-auth/forbidden-words/check`

外部系统可用该接口检查待发送内容是否命中全局违禁词。

请求：

```http
POST /api/external-auth/forbidden-words/check
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "text": "需要检查的一段回复内容"
}
```

成功响应：

```json
{
  "text": "需要检查的一段回复内容",
  "matched": true,
  "matches": [
    {
      "id": 1,
      "word": "示例违禁词",
      "category": "合规",
      "match_type": "contains",
      "severity": "high",
      "replacement": "",
      "description": "不要在回复中使用",
      "status": "active",
      "created_by": 1,
      "created_at": "2026-07-01T10:00:00",
      "updated_at": "2026-07-01T10:00:00"
    }
  ]
}
```

权限要求：

- 当前接口要求登录外部账号拥有 `auto_wechat:use`。
- 违禁词维护仍在内部后台完成，外部系统第一版只做检查，不做管理。

## 8. 推荐前端接入流程

### 8.1 从内部统一登录页跳转

```text
用户在内部登录页输入外部账号密码
  -> 内部后台 POST /api/login
  -> 返回 redirect_url，URL 中携带一次性 code
  -> 外部系统读取 code
  -> POST /api/external-auth/exchange-code
  -> 保存 token
  -> GET /api/external-auth/me
  -> 根据 permissions 渲染菜单和功能
```

伪代码：

```ts
const NEWCAR_API_BASE = "http://192.168.110.19:8790";

async function exchangeExternalCode(code: string) {
  const res = await fetch(`${NEWCAR_API_BASE}/api/external-auth/exchange-code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code,
      platform: "auto_wechat",
      device_name: navigator.userAgent.slice(0, 80),
    }),
  });

  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  sessionStorage.setItem("external_token", data.token);
  return data;
}
```

### 8.2 外部系统自带账号密码登录

```text
用户输入账号密码
  -> POST /api/external-auth/login
  -> 保存 token
  -> GET /api/external-auth/me
  -> 根据 permissions 渲染菜单和功能
  -> 业务请求统一带 Authorization: Bearer <token>
  -> 退出时 POST /api/external-auth/logout
```

伪代码：

```ts
const NEWCAR_API_BASE = "http://192.168.110.19:8790";

async function externalLogin(account: string, password: string) {
  const res = await fetch(`${NEWCAR_API_BASE}/api/external-auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account,
      password,
      platform: "auto_wechat",
      device_name: navigator.userAgent.slice(0, 80),
    }),
  });

  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  sessionStorage.setItem("external_token", data.token);
  return data;
}

async function externalMe() {
  const token = sessionStorage.getItem("external_token");
  const res = await fetch(`${NEWCAR_API_BASE}/api/external-auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}
```

### 8.3 auto_wechat 管理员切换、商户改密与退出

```text
管理员点击“切换到 NewCar”
  -> 浏览器直接 POST /api/external-auth/switch-to-internal
  -> 校验 redirect_url 为 HTTP(S)
  -> 使用返回地址进入 NewCar（不清理 auto_wechat token）

普通商户点击“修改密码”
  -> 开启全局 401 NewCar 跳转抑制
  -> 浏览器 POST auto_wechat 9000 /auth/password（仅两个密码字段）
  -> 9000 代理 NewCar /api/external-auth/password
  -> success（严格匹配 ok+relogin_required+revoked_session_scope="all"）：清本地持久状态，进入“密码已修改，请重新登录”状态页
  -> business（400/403）：保留登录态，恢复 401 跳转，弹窗内提示重试，不进结果状态页
  -> relogin（401）：清本地持久状态，进入“登录已失效，请重新登录”状态页（不得声称密码已修改）
  -> unknown（超时/网络/5xx/异常 JSON/2xx 非白名单）：清本地持久状态，进入“密码修改结果未知，请重新登录确认”状态页（不得声称成功或失败，不恢复旧会话）
  -> handleRelogin：将结果状态恢复为 null

普通用户点击“退出登录”
  -> 开启全局 401 NewCar 跳转抑制
  -> 浏览器 POST auto_wechat 9000 /auth/logout
  -> 9000 注销 NewCar external session
  -> 前端无条件清理本地持久状态并保持当前 URL
  -> 失败时仅用页面内存 token 重试
  -> 主动点击“重新登录”前关闭抑制并跳 NewCar 登录页

管理员点击“退出登录”（退出当前浏览器全部登录态）
  -> 开启全局 401 NewCar 跳转抑制，卸载受保护页面
  -> 浏览器直调 NewCar POST /api/external-auth/logout-current-browser（credentials include）
  -> NewCar 撤销当前 external + 同用户 internal session，删除两个内部 Cookie
  -> 校验 redirect_url 为 HTTP(S) 后 window.location.replace 跳转
  -> 失败：清本地持久状态，停留当前 URL 提示重试，不跳错系统
```

## 9. 安全要求

外部系统必须遵守：

1. 从内部统一登录页跳转时，只使用一次性 code 调 `/api/external-auth/exchange-code` 换 token；不要在 URL 长期携带 token。
2. 不要把 token 长期放在 URL 参数里。
3. token 优先放 HttpOnly + Secure + SameSite Cookie；如果第一版只能放前端存储，建议用 sessionStorage，并做好 XSS 防护。
4. 生产环境必须配置强随机 `SESSION_SECRET`，不能使用默认开发密钥。
5. 后端返回的 `permissions` 是唯一可信权限来源。
6. NewCarProject `/api/external-auth/login`、`/api/external-auth/me` 不提供 auto_wechat 商户绑定；其示例 `merchant_id=null` 是上游字段语义。
7. auto_wechat 9000 已通过 `external_merchant_bindings` 和服务端 RequestContext 执行商户隔离；浏览器自填的 `merchant_id`、抖音账号、智能体或会话归属一律不可信。
8. external token 在 NewCarProject Origin 上不能访问内部 `/api/me`；在 auto_wechat 9000 Origin 上可作为 Bearer 调用本地 `/auth/me`、`/auth/logout`，其它业务访问继续受 9000 权限和隔离 gate 约束。
9. `switch-to-internal` 返回地址可能携带一次性 `internal_code`，不得写入日志、错误提示或持久化存储；跳转前必须校验协议为 HTTP(S)。

## 10. 和内部后台登录的区别

| 能力       | NewCar 内部后台 `/api/login` | NewCar 外部登录 `/api/external-auth/login`                             |
| ---------- | ---------------------------- | ---------------------------------------------------------------------- |
| 面向对象   | 内部管理员                   | 外部系统账号                                                           |
| 账号范围   | `account_scope=internal`     | `account_scope=external`                                               |
| 返回 token | 内部 token                   | 外部 token；统一登录跳转场景先返回一次性 code                          |
| 可访问接口 | NewCar 内部后台接口          | NewCar `/api/external-auth/*`；auto_wechat 访问另由 9000 门面校验      |
| 角色来源   | 内部角色 RBAC                | 外部账号直配权限                                                       |
| 商户关系   | 内部 `merchants` / 分配范围  | 上游不提供 auto_wechat 绑定；9000 通过 `external_merchant_bindings` 映射 |

## 11. 当前版本接口清单

| 方法   | 路径                                            | 说明                         | 认证       |
| ------ | ----------------------------------------------- | ---------------------------- | ---------- |
| `POST` | `/api/external-auth/login`                      | 外部账号登录                 | 无         |
| `POST` | `/api/external-auth/exchange-code`              | 一次性 code 换外部 token      | 无         |
| `GET`  | `/api/external-auth/me`                         | 查询当前外部登录态           | 外部 token |
| `POST` | `/api/external-auth/switch-to-internal`        | 切换回内部 NewCar 系统        | 外部 token |
| `POST` | `/api/external-auth/logout`                    | 退出外部登录（9000 注销门面） | 外部 token |
| `POST` | `/api/external-auth/logout-current-browser`    | 管理员退出当前浏览器全部登录态 | 外部 token + NewCar 域 Cookie |
| `POST` | `/api/external-auth/password`                  | 商户改密（上游，9000 代理）   | 外部 token |
| `POST` | `/auth/password`                               | 商户改密 9000 门面            | 外部 token |
| `POST` | `/auth/logout`                                 | 普通退出 9000 注销门面        | 外部 token |
| `POST` | `/api/external-auth/forbidden-words/check`     | 全局违禁词检查                | 外部 token |

## 12. 后续扩展边界

一次性 code 登录、auto_wechat 本地外部商户绑定和服务端 RequestContext 已落地。后续扩展必须继续遵守：NewCarProject 负责账号、Token 和权限；9000 负责 auto_wechat 商户映射、资源归属和业务隔离；浏览器字段不得替代可信服务端上下文。9000 到 9100 的内部鉴权或其它跨服务能力应按独立接口合同推进，不得通过前端 token 或数据库直读绕过现有边界。
