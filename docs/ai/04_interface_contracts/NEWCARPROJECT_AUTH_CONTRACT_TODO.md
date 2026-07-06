# NewCarProject 登录与权限契约待确认

更新时间：2026-06-18

本文档基于 P0-AUTH-CTX-1 只读探索结论整理，用于和 NewCarProject / 产品团队确认 auto_wechat 接入登录、权限、商户隔离与 9000 调用 9100 的可信上下文字段契约。

本轮仅固化待确认契约，不代表已经实现登录、鉴权、权限拦截、商户隔离或 9000 到 9100 的内部鉴权。

## 1. 当前现状

### 1.1 已确认现状

1. 当前前端登录仍是本地模拟，不是 NewCarProject 真实登录态。
2. 当前 9000 主服务没有真实用户认证 / RBAC。
3. 当前 9100 抖音 AI 客服服务不应继续信任前端直接传入的 `merchant_id` / `douyin_account_id` / `agent_id`。
4. 9000 应成为可信上下文生成方，并作为 9100 的可信代理。
5. 浏览器不应直接决定商户、抖音账号、智能体等高风险上下文。

### 1.2 目标边界

```text
NewCarProject 登录态
  -> 9000 auto_wechat 主服务校验
  -> 9000 生成 RequestContext
  -> 9000 校验权限和商户归属
  -> 9000 作为可信代理调用 9100
  -> 9100 使用 9000 传入的可信上下文
```

## 2. NewCarProject 待确认字段

| 字段 | 是否必需 | 说明 | 待确认点 |
|---|---|---|---|
| `token` / `cookie` / `code` | 是 | 登录态传递凭证 | 使用哪一种或是否组合使用 |
| `user_id` | 是 | NewCarProject 用户唯一标识 | 字段名、类型、是否全局唯一 |
| `username` | 是 | 登录账号名 | 是否等同 account |
| `display_name` | 建议 | 展示名称 | 是否一定返回 |
| `role_codes` | 是 | 角色编码列表 | 是否返回完整角色 |
| `permission_codes` | 是 | 展开后的权限编码列表 | 是否由 NewCarProject 直接返回 |
| `merchant_id` | 是 | 当前商户 ID | 是否为 NewCarProject 商户主键 |
| `merchant_ids` | 建议 | 用户可访问商户列表 | 多商户用户是否存在 |
| `default_merchant_id` | 建议 | 默认进入商户 | 多商户时默认规则 |
| `super_admin` | 是 | 是否超管 | 是否可跨商户切换 |
| `merchant_status` | 是 | 商户状态 | active / disabled / expired 等枚举 |
| `expires_at` | 是 | 登录态过期时间 | 时间格式、时区、续期规则 |

建议 NewCarProject 登录校验成功后返回：

```json
{
  "user_id": "u_10001",
  "username": "zhangsan",
  "display_name": "张三",
  "role_codes": ["merchant_admin"],
  "permission_codes": [
    "auto_wechat:use",
    "auto_wechat:leads",
    "auto_wechat:douyin_ai_cs"
  ],
  "merchant_id": "m_10001",
  "merchant_ids": ["m_10001"],
  "default_merchant_id": "m_10001",
  "super_admin": false,
  "merchant_status": "active",
  "expires_at": "2026-06-18T18:00:00+08:00"
}
```

## 3. 登录态传递建议

### 3.1 推荐正式方案

正式方案优先使用一次性 `code`，而不是在 URL 长期携带 `access_token`。

```text
NewCarProject
  -> 跳转 auto_wechat，携带一次性 code
  -> 9000 使用 code 调 NewCarProject 校验接口
  -> NewCarProject 返回用户、商户、角色、权限
  -> 9000 生成 auto_wechat RequestContext
  -> React 使用 9000 会话访问业务接口
```

建议跳转示例：

```text
https://auto-wechat.example.com/auth/callback?code=one_time_code&redirect=/leads
```

### 3.2 可兼容方案

如果 NewCarProject 已有 token / cookie 登录态，也可支持：

1. 9000 从请求中读取 `code` / `token` / `cookie`。
2. 9000 调 NewCarProject 校验接口。
3. 校验成功后，9000 不直接信任前端传入的商户字段，而是使用 NewCarProject 返回值生成 RequestContext。
4. 校验失败时，未登录应跳回 NewCarProject 登录页；已登录但缺权限应显示无权限。

### 3.3 不建议方案

1. 不建议 URL 长期携带 `access_token`。
2. 不建议 React 解 token 后自行决定 `merchant_id`。
3. 不建议浏览器直接向 9100 传 `merchant_id` / `douyin_account_id` / `agent_id`。

## 4. 权限码建议

建议 NewCarProject 至少确认以下权限码：

| 权限码 | 说明 |
|---|---|
| `auto_wechat:use` | 是否允许进入 auto_wechat |
| `auto_wechat:douyin_ai_cs` | 是否允许使用抖音 AI 小高客服 |
| `auto_wechat:leads` | 是否允许使用 AI 小高线索 |
| `auto_wechat:agent` | 是否允许使用小高 AI 微信助手 |
| `auto_wechat:compute` | 是否允许查看小高算力 |
| `auto_wechat:admin:merchant` | 是否允许管理商户 |
| `auto_wechat:admin:forbidden_words` | 是否允许管理违禁词 |
| `auto_wechat:admin:followup_prompts` | 是否允许管理回访提示词 |
| `auto_wechat:admin:ai_reply_records` | 是否允许查看 AI 回复记录 |
| `auto_wechat:admin:compute_config` | 是否允许管理算力配置 |
| `auto_wechat:admin:accounts` | 是否允许管理账号 |

需要确认：

1. 权限是否按角色返回，还是直接返回展开后的 `permission_codes`。
2. 商户账号和 `super_admin` 是否使用同一套登录接口。
3. 前端隐藏菜单只能作为体验优化，后端必须拒绝无权限接口访问。
4. `auto_wechat:use` 是否作为进入系统的总开关。

## 5. 9000 RequestContext 草案

9000 校验 NewCarProject 登录态成功后，建议生成内部 RequestContext：

| 字段 | 类型建议 | 说明 |
|---|---|---|
| `user_id` | `str` | NewCarProject 用户 ID |
| `username` | `str` | 登录账号名 |
| `merchant_id` | `str | None` | 当前商户 ID |
| `merchant_ids` | `list[str]` | 可访问商户列表 |
| `role_codes` | `list[str]` | 角色编码 |
| `permission_codes` | `list[str]` | 权限编码 |
| `super_admin` | `bool` | 是否超管 |
| `session_id` | `str | None` | NewCarProject session 或 auto_wechat session |
| `source_system` | `str` | 固定标识，如 `new_car_project` |
| `request_id` | `str` | 请求追踪 ID |

示例：

```json
{
  "user_id": "u_10001",
  "username": "zhangsan",
  "merchant_id": "m_10001",
  "merchant_ids": ["m_10001"],
  "role_codes": ["merchant_admin"],
  "permission_codes": [
    "auto_wechat:use",
    "auto_wechat:douyin_ai_cs"
  ],
  "super_admin": false,
  "session_id": "sess_abc",
  "source_system": "new_car_project",
  "request_id": "req_20260618_0001"
}
```

## 6. 9000 / 9100 服务边界

### 6.1 推荐生产链路

```text
浏览器
  -> 9000 auto_wechat 主服务
  -> 9100 抖音 AI 客服服务
```

### 6.2 边界原则

1. 浏览器不应直接决定 `merchant_id` / `douyin_account_id` / `agent_id`。
2. 9000 作为可信代理调用 9100。
3. 9100 接收的上下文必须由 9000 校验后传入。
4. 9000 调 9100 还需要内部服务鉴权。

### 6.3 内部服务鉴权方式待确认

可选方案包括：

1. service token。
2. 请求签名。
3. 内网白名单。
4. mTLS。

P0 建议先确认一种最小可落地方案，并明确密钥配置、轮换方式、超时和失败处理。

## 7. 抖音账号与智能体绑定

### 7.1 必须校验的绑定关系

1. `merchant_id + douyin_account_id` 必须绑定校验。
2. `agent_id` 必须属于 `merchant_id + douyin_account_id`。
3. `conversation_id` 只能作为会话定位符，不能作为授权依据。
4. `customer_open_id` 等客户标识必须在账号和商户上下文内使用。

### 7.2 二期 Agent tools 约束

二期 Agent tools 只能使用可信上下文查询：

1. 商户库存。
2. 车型价格。
3. 金融方案。
4. 客户历史跟进记录。
5. 商户知识库。
6. 违禁词 / 合规规则。

所有 tools 必须以 `merchant_id`、`douyin_account_id`、`agent_id` 作为隔离边界，不能接受前端自报上下文直接查询。

## 8. 风险点

| 风险 | 说明 | 建议 |
|---|---|---|
| 前端伪造 `merchant_id` | 可越权访问其他商户数据 | `merchant_id` 只能来自 9000 可信上下文 |
| 商户越权查询抖音号 | 修改 `douyin_account_id` 访问其他账号 | 9000 / 9100 都应校验账号归属 |
| 商户越权查询库存 / 客户历史 | 二期 tools 风险更高 | tools 必须强制商户隔离 |
| `super_admin` 切换商户缺少审计 | 操作不可追踪 | 切换商户、代操作必须记录审计日志 |
| token 放 URL 泄露 | 浏览器历史、日志、Referer 泄露 | 正式方案优先一次性 code |
| 9100 被绕过直接调用 | 前端可伪造上下文 | 9100 增加内部服务鉴权和来源限制 |

## 9. 待 NewCarProject / 产品确认问题清单

### 9.1 登录态

1. NewCarProject 跳转 auto_wechat 时使用 `token`、`cookie`、`code`，还是组合使用？
2. 字段名分别是什么？
3. `token` 是否为 JWT？
4. 如果是 JWT，claims 示例是什么？
5. 登录态过期时间是多少？
6. 是否支持一次性 code 换取用户上下文？

### 9.2 校验接口

1. 9000 应调用哪个 NewCarProject 接口校验登录态？
2. 校验接口请求头、请求体、签名方式是什么？
3. 校验失败、过期、无权限的错误码是什么？
4. 商户禁用、过期、套餐不足的错误码是什么？

### 9.3 返回 JSON 示例

需要 NewCarProject 提供：

1. 登录成功返回 JSON 示例。
2. token / cookie / code 校验成功返回 JSON 示例。
3. 权限字典返回 JSON 示例。
4. 商户信息返回 JSON 示例。
5. 无权限 / token 过期 / 商户禁用 / 套餐不足错误示例。

### 9.4 权限与商户

1. 权限字典最终以哪些权限码为准？
2. `merchant_id` 是否为 NewCarProject 商户主键？
3. 一个用户是否可能属于多个商户？
4. 多商户用户进入 auto_wechat 时默认选哪个商户？
5. `super_admin` 是否可以切换查看所有商户？
6. `super_admin` 切换商户是否需要 NewCarProject 返回授权范围？

### 9.5 9000 / 9100 边界

1. 生产环境是否确认 9000 是浏览器访问 9100 能力的唯一可信入口？
2. 9000 调 9100 的内部鉴权方式使用 service token、签名、内网白名单还是 mTLS？
3. 9100 是否需要拒绝浏览器直接携带 `merchant_id` 调用核心接口？
4. 9100 是否需要在自身侧二次校验 `douyin_account_id` / `agent_id` 归属？

## 10. P0 最小确认范围

P0 阶段最少需要 NewCarProject 确认：

1. 登录态传递方式和字段名。
2. 登录态校验接口。
3. 登录成功返回的 `user_id`、`merchant_id`、`merchant_ids`、`permission_codes`、`super_admin`。
4. `merchant_id` 是否为 NewCarProject 商户主键。
5. 商户状态字段和错误码。
6. `auto_wechat:use` 与核心功能权限码。
7. 9000 是否为调用 9100 的唯一可信入口。
8. 9000 调 9100 的内部鉴权方式。

## 11. 本文档不包含的内容

1. 不实现 NewCarProject 登录接入。
2. 不实现 9000 RBAC。
3. 不修改 9100 调用链。
4. 不新增数据库字段。
5. 不执行数据库迁移。
6. 不安装依赖。
7. 不接入 LangChain。
