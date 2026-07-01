# 外部系统登录接入说明

更新时间：2026-06-22

本文档提供给外部系统开发人员使用，用于接入当前内部商户系统维护的外部账号登录能力。

## 1. 接入边界

当前版本只提供外部账号登录、一次性 code 换取外部 token、登录态校验、退出登录、权限回显和全局违禁词检查。

当前版本不包含：

- 外部商户绑定。
- 外部商户隔离。
- 抖音账号、智能体、会话归属校验。
- 9000 到 9100 的内部服务鉴权。
- 外部商户绑定后的业务资源鉴权。

外部账号和内部管理员共用 `users` 表，但通过 `account_scope` 隔离：

- `internal`：内部后台账号，只能登录当前内部管理系统。
- `external`：外部系统账号，只能通过外部登录接口获取外部 token。

登录会话共用 `user_sessions` 表，但通过 `session_scope` 显式隔离：

- `internal`：内部后台 token。
- `external`：外部系统 token。

## 2. 基础约定

### 2.1 Base URL

开发环境示例：

```text
http://127.0.0.1:8790
```

线上环境请使用实际后端域名。

### 2.2 CORS

如果外部系统前端直接从浏览器调用本后端，需要将外部系统域名加入后端 `CORS_ORIGINS`，例如：

```text
CORS_ORIGINS=https://internal.example.com,https://auto-wechat.example.com
```

本地开发默认包含：

```text
http://127.0.0.1:5173
http://127.0.0.1:5174
http://localhost:5174
http://127.0.0.1:9000
```

### 2.3 认证方式

外部系统登录成功后，后端返回 `token`。

后续请求统一带：

```http
Authorization: Bearer <token>
```

### 2.4 Token 隔离

外部 token 只能访问 `/api/external-auth/*` 这类外部接口。

外部 token 不能访问内部后台接口，例如：

- `/api/me`
- `/api/merchants`
- `/api/admin-users`
- `/api/roles`

内部后台 token 也不能访问外部登录态接口 `/api/external-auth/me`。

## 3. 权限要求

外部账号必须拥有：

```text
auto_wechat:use
```

否则登录会返回 `403`。

当前可分配的外部权限包括：

| 权限码 | 说明 |
|---|---|
| `auto_wechat:use` | 进入外部系统 |
| `auto_wechat:douyin_ai_cs` | 抖音 AI 小高客服 |
| `auto_wechat:leads` | AI 小高线索 |
| `auto_wechat:agent` | 小高 AI 微信助手 |
| `auto_wechat:compute` | 小高算力 |
| `auto_wechat:admin:forbidden_words` | 外部违禁词管理 |
| `auto_wechat:admin:accounts` | 外部账号管理 |
| `auto_wechat:admin:ai_reply_records` | AI 回复记录 |
| `auto_wechat:admin:compute_config` | 算力配置管理 |

接口返回的 `permissions` 是当前账号实际拥有的外部权限列表，外部系统应以后端返回值为准控制页面和接口能力。

## 4. 登录接口

### 4.1 内部统一登录页跳转外部系统

内部后台当前仍使用同一个登录界面。用户在内部后台登录页输入外部账号密码时，`/api/login` 会识别 `account_scope=external`，不返回内部后台 token，而是返回短时一次性 `external_auth_code` 和带 code 的 `redirect_url`。

外部系统接收跳转后，应读取 URL 中的 `code`，立即调用 `POST /api/external-auth/exchange-code` 换取外部 token。code 只能使用一次，默认 120 秒过期。

内部登录页返回示例：

```json
{
  "account_scope": "external",
  "redirect_url": "http://127.0.0.1:9000?code=one_time_code&source=new_car_project",
  "external_auth_code": "one_time_code",
  "external_auth_code_expires_in": 120,
  "external_auth_code_expires_at": "2026-06-22T10:02:00+08:00",
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

| 状态码 | 场景 |
|---|---|
| `400` | code 为空 |
| `401` | code 无效、已使用或已过期 |
| `403` | 外部账号缺少 `auto_wechat:use` |

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

| 字段 | 必填 | 说明 |
|---|---|---|
| `account` | 是 | 外部账号登录名，通常是手机号 |
| `password` | 是 | 外部账号密码 |
| `platform` | 否 | 来源系统标识，建议传 `auto_wechat` |
| `device_name` | 否 | 设备或浏览器信息，用于审计 |

成功响应：

```json
{
  "ok": true,
  "token": "raw_token_string",
  "token_type": "Bearer",
  "expires_in": 604800,
  "expires_at": "2026-06-29T10:00:00+08:00",
  "account_scope": "external",
  "external_app_url": "http://127.0.0.1:9000",
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
- 当前版本没有外部商户绑定，所以 `merchant_id` 为 `null`，`merchant_ids` 为空数组。
- 不要从 URL 长期携带 token。

失败响应示例：

```json
{
  "detail": "外部账号或密码错误"
}
```

常见状态码：

| 状态码 | 场景 |
|---|---|
| `401` | 账号或密码错误 |
| `403` | 非外部账号、账号停用、缺少 `auto_wechat:use` |
| `429` | 短时间内失败次数过多 |

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
  "expires_at": "2026-06-29T10:00:00+08:00",
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

失败响应：

```json
{
  "detail": "外部登录已过期，请重新登录"
}
```

状态码：

| 状态码 | 场景 |
|---|---|
| `401` | token 缺失、无效、过期、账号不可用 |
| `403` | 账号缺少 `auto_wechat:use` |

## 6. 退出登录

### 6.1 POST `/api/external-auth/logout`

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
      "created_at": "2026-06-22T10:00:00",
      "updated_at": "2026-06-22T10:00:00"
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
async function exchangeExternalCode(code: string) {
  const res = await fetch("/api/external-auth/exchange-code", {
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
async function externalLogin(account: string, password: string) {
  const res = await fetch("/api/external-auth/login", {
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
  const res = await fetch("/api/external-auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}
```

## 9. 安全要求

外部系统必须遵守：

1. 从内部统一登录页跳转时，只使用一次性 code 调 `/api/external-auth/exchange-code` 换 token；不要在 URL 长期携带 token。
2. 不要把 token 长期放在 URL 参数里。
3. token 优先放 HttpOnly + Secure + SameSite Cookie；如果第一版只能放前端存储，建议用 sessionStorage，并做好 XSS 防护。
4. 生产环境必须配置强随机 `SESSION_SECRET`，不能使用默认开发密钥。
5. 后端返回的 `permissions` 是唯一可信权限来源。
6. 当前版本没有外部商户绑定，不要根据前端自填 `merchant_id` 做高风险查询。
7. 涉及抖音账号、智能体、客户会话、线索、库存等上下文时，后续必须由外部系统后端生成可信 RequestContext，不能信任浏览器自报字段。

## 10. 和内部后台登录的区别

| 能力 | 内部后台 `/api/login` | 外部登录 `/api/external-auth/login` |
|---|---|---|
| 面向对象 | 内部管理员 | 外部系统账号 |
| 账号范围 | `account_scope=internal` | `account_scope=external` |
| 返回 token | 内部 token | 外部 token；统一登录跳转场景先返回一次性 code |
| 可访问接口 | 内部后台接口 | 外部系统接口 |
| 角色来源 | 内部角色 RBAC | 外部账号直配权限 |
| 商户关系 | 内部 `merchants` / 分配范围 | 第一版无外部商户绑定 |

## 11. 当前版本接口清单

| 方法 | 路径 | 说明 | 认证 |
|---|---|---|---|
| `POST` | `/api/external-auth/login` | 外部账号登录 | 无 |
| `POST` | `/api/external-auth/exchange-code` | 一次性 code 换外部 token | 无 |
| `GET` | `/api/external-auth/me` | 查询当前外部登录态 | 外部 token |
| `POST` | `/api/external-auth/logout` | 退出外部登录 | 外部 token |
| `POST` | `/api/external-auth/forbidden-words/check` | 全局违禁词检查 | 外部 token |

## 12. 后续扩展建议

后续如果需要完整接入 auto_wechat 业务系统，建议按以下顺序扩展：

1. 一次性 code 登录，避免账号密码由多个系统直接处理。
2. 外部商户、抖音账号、智能体绑定关系。
3. 外部系统 RequestContext。
4. 9000 到 9100 的 service token 或签名鉴权。
5. 业务接口按外部商户、抖音账号、智能体做强隔离。
