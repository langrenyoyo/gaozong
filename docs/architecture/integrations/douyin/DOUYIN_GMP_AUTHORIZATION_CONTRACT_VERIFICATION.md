# 抖音 GMP 授权生命周期官方契约验证报告（P0.5-DOUYIN-GMP-AUTHORIZATION-CONTRACT-VERIFICATION-1）

> 状态：CONTRACT_COMPLETE
> 角色：Contract Authority（仅确认官方事实）
> 背景：2026-08-20 生产事故——抖音 AI 自动回复真实发送失败（`/send_msg` 返回 `refresh_token 已过期，需要重新授权`），
> 需确认抖音官方授权契约事实，为后续 Decision Authority 决策提供依据。
> 禁止：修改代码 / 设计数据库 / 输出实施方案 / 提出架构。

## 0. 验证范围与方法

- 验证对象：抖音 GMP 授权生命周期（get-access-token / refresh-token / GMP agent 授权 / list_bind_info / 错误码）。
- 事实来源：**抖音开放平台官方开发者文档**（developer.open-douyin.com，2026-08-21 抓取）逐条提取 + 本项目代码契约核对。
- 口径说明：官方文档存在两套授权模型，本报告区分记录，避免混淆——
  1. **开放平台标准 OAuth 2.0**（open.douyin.com/oauth）：公开文档，本报告第 1/2/3/5 节以它为准。
  2. **GMP 商家 Agent API**（gmp.bytedanceapi.com/ai_chat_agent_api）：**封闭平台 API，无公开文档**，本报告第 3/4 节据代码契约 + 生产观测记录，并标注证据级别。

---

## 1. refresh-token 接口（官方名：刷新 refresh_token）

### 官方端点与请求参数

| 项 | 官方事实 |
|---|---|
| HTTP URL | `https://open.douyin.com/oauth/renew_refresh_token/` |
| HTTP Method | POST |
| 请求头 | Content-Type 固定 `application/json` |
| 请求参数 | `client_key`（必填，应用唯一标识）；`refresh_token`（必填，通过 `/oauth/access_token/` 获取到的 refresh_token） |
| 前置权限 | **client_key 必须拥有 `renew_refresh_token` 权限** |

### 核心契约事实

1. **是否需要 refresh_token**：需要，body 必传通过 `/oauth/access_token/` 获取的 `refresh_token`。
2. **refresh_token 有效期**：**新 refresh_token 有效期 30 天**；调用后旧 refresh_token 失效。
3. **是否支持自动续期**：**不支持无限自动续期**。官方原文：
   > 刷新操作需要在 refresh_token 过期前进行。通过旧的 refresh_token 获取新的 refresh_token，调用后旧 refresh_token 会失效，新 refresh_token 有 30 天有效期。
4. **刷新次数限制**：**最多只能获取 5 次新的 refresh_token，5 次过后需要用户重新授权**（官方原文）。
5. **过期前刷新**：必须在 refresh_token 过期前执行；过期后无刷新通道，只能重新授权。

### 返回字段

```json
{
  "data": {
    "error_code": 0,
    "expires_in": "86400",
    "refresh_token": "refresh_token"
  },
  "message": "success"
}
```

| 字段 | 含义 |
|---|---|
| `refresh_token` | 新的 refresh_token（30 天有效期） |
| `expires_in` | 新 refresh_token 超时时间（秒） |
| `error_code` | 0 成功；非 0 见错误码节 |

### 错误码

| error_code | 描述 | 处理 |
|---|---|---|
| 10005 | 缺少参数 | 检查 client_key / refresh_token |
| 10004 | 权限不足 | 申请 `renew_refresh_token` 权限 |
| **10010** | **refresh_token 过期** | **token 已过期，请让用户重新授权** |
| 10020 | 超过刷新次数限制 | 无法再刷新，请让用户重新授权 |

---

## 2. get-access-token 接口（官方名：获取 access_token）

### 官方端点与请求参数

| 项 | 官方事实 |
|---|---|
| HTTP URL | `https://open.douyin.com/oauth/access_token/` |
| HTTP Method | POST |
| 请求头 | Content-Type 固定 `application/x-www-form-urlencoded`（**非 json**） |
| 请求参数 | `client_key`（必填）；`client_secret`（必填）；`code`（必填，用户授权码）；`grant_type`（必填，固定 `authorization_code`） |

前置流程：`GET https://open.douyin.com/platform/oauth/connect/`（浏览器授权页）→ 用户扫码授权 → code 回调 `redirect_uri` → 用 code 换 access_token。**code 有效期 10 分钟且只能使用一次**（error 10007）。

### 返回字段

```json
{
  "data": {
    "access_token": "act....",
    "expires_in": 1296000,
    "refresh_token": "rft....",
    "refresh_expires_in": 2592000,
    "open_id": "b9b71865-...",
    "scope": "user_info",
    "error_code": 0,
    "description": "",
    "captcha": "",
    "desc_url": "",
    "log_id": "..."
  },
  "message": "success"
}
```

| 字段 | 含义 |
|---|---|
| `access_token` | 接口调用凭证 |
| `expires_in` | **access_token 超时时间（秒）**，官方示例 1296000 = **15 天** |
| `refresh_token` | **是否返回：是**。用户刷新 access_token 的凭证 |
| `refresh_expires_in` | **refresh_token 超时时间（秒）**，官方示例 2592000 = **30 天** |
| `open_id` | 授权用户唯一标识 |
| `scope` | 用户授权作用域（逗号分隔） |

注意事项（官方原文）：获取到 access_token 后，授权临时票据 (code) 不要再授权刷新，否则会导致上一次获取的 code 过期。

### 错误码

| error_code | 描述 |
|---|---|
| 10002 | 参数错误 |
| 10007 | 授权码过期（10 分钟有效，仅能用一次） |
| 10013 | client_key / client_secret 报错 |
| 10014 | client_key 不匹配 |
| 10001 | 系统异常 |
| 10003 | 密钥错误 |

---

## 3. GMP 授权生命周期

### 3.1 两套模型边界（关键澄清）

| 维度 | 开放平台 OAuth 2.0（官方文档） | 本项目 GMP Agent API |
|---|---|---|
| 域名/前缀 | `open.douyin.com/oauth/*` | `gmp.bytedanceapi.com/ai_chat_agent_api/v1/openapi` |
| 鉴权方式 | body 带 access_token / client_key+secret | **GMP 签名**：`Authorization = sha256Hex(DY_GMP_SECRET_KEY + json_body + "-" + timestamp)`，请求体**不含** access_token / refresh_token |
| 公开文档 | 有（本报告第 1/2 节） | **无公开文档（封闭平台 API）**，接口契约只能据生产观测 + 代码核对 |
| 已接入端点 | - | `get_aweme_auth_url` / `list_bind_info` / `send_msg` / `decode_msg_content` / `download_resource` / `upload_image_file` |

本项目全部 GMP 主动调用（[douyin_openapi_client.py:94-114](app/services/douyin_openapi_client.py)）走签名认证，`/send_msg` 请求体（[douyin_private_message_send_service.py:135-143](app/services/douyin_private_message_send_service.py)）仅含 `main_account_id/scene/content/msg_id/conversation_id/to_user_id/from_user_id`，**无 access_token / refresh_token**。`/decode_msg_content`（[douyin_resource_download_service.py:156](app/services/douyin_resource_download_service.py)）同样签名认证。

### 3.2 agent 授权有效期（官方规则 + 生产观测）

| 项 | 官方事实 / 观测 |
|---|---|
| access_token 有效期 | **15 天**（官方示例 expires_in=1296000s） |
| refresh_token 有效期 | **30 天**（官方示例 refresh_expires_in=2592000s） |
| refresh_token 续期 | 每次换新仍 30 天，**最多续 5 次后必须重新授权**（官方 renew_refresh_token 文档） |
| 过期刷新前提 | 必须**过期前**刷新；过期后报 10010，只能重新授权 |
| 主动失效 | 用户可在「抖音-我-设置-账号与安全-授权管理」取消授权，取消后 access_token 立即失效；平台会定期检查并取消不合规授权 |

### 3.3 失效条件（官方列举）

1. refresh_token 到期（30 天）未续期 → 重新授权；
2. 续期超过 5 次 → 重新授权；
3. 用户主动在抖音端取消授权 → 立即失效；
4. 平台定期合规检查取消不合规授权 → 立即失效。

### 3.4 重授权流程（官方 + 本项目现状）

- 官方重授权路径：重新走 `connect` 授权页 → 用户扫码 → 新 code → 新 access_token/refresh_token。
- 本项目现状：授权回跳 `/auth-redirect` → `/list_bind_info` 同步账号 → upsert `douyin_authorized_accounts`（[douyin_live_check.py:231](app/routers/douyin_live_check.py)）；**系统不保存 access_token/refresh_token**，无续期能力，故 30 天到期后**必须商户在 GMP 后台重新授权**，无程序化绕过。
- 生产观测（2026-08-20 事故）：主账号 2026-07-21 授权 + 30 天 = 2026-08-20 过期，与失败时刻吻合（单条失败，7 天内唯一 failed，非全面失效）。

### 3.5 证据级别

| 事实 | 证据级别 |
|---|---|
| access_token 15 天 / refresh_token 30 天 / 续 5 次 / 重新授权 | **OFFICIAL_DOC_VERIFIED**（官方文档原文） |
| GMP Agent API 签名认证、请求体无 token | **CODE_VERIFIED**（douyin_openapi_client.py:94-114 + send payload） |
| 生产 30 天过期与事故吻合 | **PRODUCTION_OBSERVED**（2026-08-20 事故，见探索报告） |
| GMP agent 授权在 GMP 后台的管理入口（重授权操作路径） | **UNKNOWN**（封闭平台，运维/NewCar 侧管理界面未核实） |

---

## 4. list_bind_info

### 4.1 官方文档状态

`/list_bind_info` 属于 **GMP 封闭平台 API**（gmp.bytedanceapi.com/ai_chat_agent_api），**无公开官方文档**。2026-08-21 多引擎检索确认该端点与 `get_aweme_auth_url`、`ai_chat_agent_api` 前缀均不在公开索引；开放平台公开文档仅覆盖 open.douyin.com/oauth 标准授权接口。

### 4.2 代码契约已消费字段（本项目核对）

项目在 upsert `douyin_authorized_accounts` 时读取的 list_bind_info item 字段（[douyin_live_check_service.py:492-547](app/services/douyin_live_check_service.py)）：

| 字段 | 用途 |
|---|---|
| `open_id` | 账号主键（全局唯一） |
| `user_id` / `union_id` | 身份标识 |
| `account_name` / `avatar_url` | 展示 |
| `bind_status` | 状态（0 unbound / 1 success / 2 failed / 3 unbound） |
| `account_type` | 账号类型 |
| `bind_time` / `unbind_time` / `created_at` | 绑定/解绑/创建时间（无时区字符串，按 Asia/Shanghai 解析转 UTC） |

### 4.3 待确认字段（token / expire_time / authorized_at）

| 问题 | 结论 | 证据级别 |
|---|---|---|
| 是否返回 `token` / `access_token` / `refresh_token` | **无法从官方文档确认**；`SENSITIVE_KEYS`（[douyin_live_check_service.py:29-35](app/services/douyin_live_check_service.py)）含 access_token/refresh_token 仅用于日志脱敏，不表示上游必返回 | **UNVERIFIED_FROM_OFFICIAL_DOCS** |
| 是否返回 `expire_time` / `authorized_at` 类字段 | **无法从官方文档确认**；`authorized_at` 工作台展示值由 `bind_time`/`created_at` 派生（[douyin_live_check_service.py:742](app/services/douyin_live_check_service.py)），**不是 token 过期时间** | **CODE_VERIFIED（派生逻辑）/ UNVERIFIED_FROM_OFFICIAL_DOCS（上游字段）** |
| 是否返回状态字段 | **是**：`bind_status`（0/1/2/3）被代码消费 | **CODE_VERIFIED** |

> 证据缺口：确认 list_bind_info 是否返回 token/expire 字段，唯一可靠途径是**生产抽样 `douyin_authorized_accounts.raw_body_json`**（原始 item 已入库）。本任务为文档验证任务，未触碰生产；该证据留待后续授权操作。

---

## 5. 错误码：refresh_token expired

### 5.1 官方错误码定义

| error_code | 接口 | 官方描述 | 处理建议 |
|---|---|---|---|
| **10010** | 刷新 access_token（/oauth/refresh_token/） | **refresh_token 已过期** | 检查 refresh_token 参数是否正确，若正确**请引导用户重新授权** |
| **10010** | 刷新 refresh_token（/oauth/renew_refresh_token/） | **refresh_token 过期** | **token 已过期，请让用户重新授权** |
| 10020 | 刷新 refresh_token | 超过刷新次数限制 | 无法再刷新，请让用户重新授权 |

### 5.2 生产事故观测与本项目记录

- 生产日志（2026-08-20）：`douyin_openapi_call path=/send_msg success=False upstream_code=400 error_code=upstream_business_error`。
- DB `douyin_private_message_sends.err_msg` 逐字一致：**`refresh_token 已过期，需要重新授权`**。
- 记录路径：`call_douyin_openapi` 将 `code != 0` 归为 `upstream_business_error`（[douyin_openapi_client.py:182-194](app/services/douyin_openapi_client.py)），`upstream_code = body.code`、`upstream_msg = body.msg`；`send_msg` 失败回写 `error_code/error_message`（[douyin_private_message_send_service.py:191-198](app/services/douyin_private_message_send_service.py)）。

### 5.3 结论

| 问题 | 结论 |
|---|---|
| 对应官方码 | **10010**（官方「刷新 access_token」与「刷新 refresh_token」两个接口一致：refresh_token 过期 → 重新授权）；GMP 上游以 code=400 返回同一语义 |
| 是否稳定 | **是**。官方 10010 语义固定且两处一致；本系统 generic 归为 `upstream_business_error` 不区分具体码 |
| 是否代表必须人工重新授权 | **是，且无程序化绕过**。官方原文：若 refresh_token 过期，获取 access_token 会报错（error_code=10010），此时需要重新引导用户授权；续期须过期前、最多 5 次 |

---

## 6. 验证结论汇总

| # | 问题 | 官方结论 | 证据级别 |
|---|---|---|---|
| 1 | refresh-token 请求参数 | `client_key` + `refresh_token`（POST /oauth/renew_refresh_token/，需 renew_refresh_token 权限） | OFFICIAL_DOC_VERIFIED |
| 1 | 是否需要 refresh_token | **需要** | OFFICIAL_DOC_VERIFIED |
| 1 | refresh_token 有效期 | **30 天**，每次换新仍 30 天，旧 token 失效 | OFFICIAL_DOC_VERIFIED |
| 1 | 是否自动续期 | **不自动**；须过期前手动刷新，**最多 5 次后必须重新授权** | OFFICIAL_DOC_VERIFIED |
| 2 | get-access-token 返回字段 | access_token + expires_in(15天) + refresh_token + refresh_expires_in(30天) + open_id + scope | OFFICIAL_DOC_VERIFIED |
| 2 | access_token 有效期 | **15 天** | OFFICIAL_DOC_VERIFIED |
| 2 | 是否返回 refresh_token | **是** | OFFICIAL_DOC_VERIFIED |
| 3 | GMP agent 授权有效期 | access_token 15 天 / refresh_token 30 天 / 续 5 次 / 用户可主动取消 / 平台合规检查 | OFFICIAL_DOC_VERIFIED（OAuth 侧）+ PRODUCTION_OBSERVED（GMP 侧 30 天吻合） |
| 3 | 失效条件 | 到期未续 / 超 5 次 / 用户取消 / 平台取消 | OFFICIAL_DOC_VERIFIED |
| 3 | 重授权流程 | 重新扫码授权（connect → code → access_token）；本项目须商户在 GMP 后台重新授权 | OFFICIAL_DOC_VERIFIED + CODE_VERIFIED |
| 4 | list_bind_info 是否返回 token/expire_time/authorized_at | **官方无法确认（封闭 API）**；代码仅消费 open_id/bind_status/bind_time 等；raw_body_json 已存原始 item，待生产抽样 | UNVERIFIED_FROM_OFFICIAL_DOCS |
| 4 | 是否返回状态字段 | **是**（bind_status 0/1/2/3） | CODE_VERIFIED |
| 5 | refresh_token expired 错误码 | **10010**（官方两个接口一致），语义稳定，**必须人工重新授权** | OFFICIAL_DOC_VERIFIED |
| 5 | upstream_code | 生产观测 GMP 上游 code=400（对应官方 10010 语义），非全面失效（单条失败） | PRODUCTION_OBSERVED |

---

## 7. 关键官方文档引用

| 文档 | URL | 抓取日期 |
|---|---|---|
| 抖音获取授权码 | https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/account-permission/douyin-get-permission-code | 2026-08-21 |
| 获取 access_token | https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/account-permission/get-access-token | 2026-08-21 |
| 刷新 refresh_token | https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/account-permission/refresh-token | 2026-08-21 |
| 刷新 access_token | https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/account-permission/refresh-access-token | 2026-08-21 |

## 8. UNKNOWN / 待补证

1. **list_bind_info 上游实际返回字段**（token / expire_time / authorized_at 是否真实存在）——封闭 API，唯一可靠证据为生产 `raw_body_json` 抽样（未触碰生产）。
2. **GMP 后台重授权操作入口**（运维 / NewCar 侧管理界面路径）——封闭平台，未核实。
3. **GMP agent 授权是否独立于 OAuth 15/30 天规则**——生产观测与官方规则吻合，但 GMP 自身无公开文档，不排除 agent 绑定另有独立有效期（证据缺）。

---

CONTRACT_STATUS = COMPLETE
CODE_CHANGE=0 / DB_CHANGE=0 / MIGRATION=0 / IMPLEMENTATION=0
等待 Decision Authority 基于上述官方契约做下一步决策
