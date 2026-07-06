# P1-NEWCAR-ADMIN-ENTRY-LOGOUT-ROUTE-FIX-1

## 1. 任务目标

修复 NewCarProject 登录态下 auto_wechat 的权限消费、管理员入口、默认跳转和退出登录逻辑。

本轮只处理：

- NewCar 权限码映射。
- 前端菜单与路由保护。
- 登录后默认跳转。
- NewCar 模式退出登录跳转。
- admin rollout API 权限兼容。

本轮不修改真实自动回复发送 gate，不触发真实发送。

## 2. NewCarProject 当前权限码

商户侧权限码：

- `auto_wechat:use`
- `auto_wechat:douyin_ai_cs`
- `auto_wechat:leads`
- `auto_wechat:agent`
- `auto_wechat:compute`
- `auto_wechat:ai_edit`

管理员侧当前已发放权限码：

- `auto_wechat:admin:forbidden_words`
- `auto_wechat:admin:accounts`
- `auto_wechat:admin:ai_reply_records`
- `auto_wechat:admin:compute_config`

后续需要 NewCarProject 补充：

- `auto_wechat:admin:autoreply`
- `auto_wechat:admin:return_visit_prompts`

其中本轮代码真正消费：

- `auto_wechat:admin:autoreply`

## 3. 最新权限边界

### 3.1 商户侧

`auto_wechat:douyin_ai_cs` 统一覆盖完整抖音 AI 客服自动回复服务，包括：

- 抖音 AI 小高客服。
- AI 小高智能体。
- 抖音企业号管理。
- 抖音企业号授权。
- 企业号绑定智能体。
- 抖音会话工作台。
- 商户自己的自动回复诊断。

`auto_wechat:agent` 不改名，继续代表：

- AI 小高助手。
- 微信代理 / 微信助手。

`auto_wechat:leads` 代表 AI 小高线索。

`auto_wechat:ai_edit` 代表 AI 小高剪辑。

`auto_wechat:compute` 代表小高算力。

### 3.2 管理员侧

auto_wechat 管理员端近期只保留：

- 自动回复灰度与发送控制：`auto_wechat:admin:autoreply`。
- 回访提示词管理：`auto_wechat:admin:return_visit_prompts`，后续实现。
- 管理员 AI 回复记录：`auto_wechat:admin:ai_reply_records`。
- 算力配置：`auto_wechat:admin:compute_config`，功能暂缓。

以下能力归 NewCarProject，不在 auto_wechat 本地实现：

- 商户管理。
- 违禁词管理。
- 管理员账号管理。

管理员 AI 回复记录与商户自动回复诊断不同：

- 商户自动回复诊断只能查看当前商户自己的 AI 回复记录，归属 `auto_wechat:douyin_ai_cs`。
- 管理员 AI 回复记录可跨商户筛选查看，归属 `auto_wechat:admin:ai_reply_records`。

## 4. 不新增权限码说明

本轮不新增也不消费以下权限码：

- `auto_wechat:ai_agents`
- `auto_wechat:douyin_accounts`
- `auto_wechat:admin:douyin_accounts`
- `auto_wechat:admin:knowledge_training`

代码中仍保留 `auto_wechat:ai_agents` 作为历史兼容别名，用于旧测试和旧授权数据迁移期兼容，不作为 NewCar 新权限口径。

## 5. 前端权限工具

统一权限工具位于：

```text
frontend/src/features/capabilities.ts
```

本轮新增或收口：

- `hasPermission(code)`
- `hasAnyPermission(codes)`
- `hasAdminPermission()`
- `isAdminLike`

管理员判断规则：

```text
super_admin=true
或 permission_codes 中存在 auto_wechat:admin:* 权限
```

具体页面仍必须校验具体权限码。`hasAdminPermission()` 只表示“管理员身份”，不能替代页面权限。

后端认证上下文同步支持该规则：

- 商户侧请求仍必须命中本地商户绑定。
- 管理员权限账号不强制绑定本地商户，避免 NewCar 管理员账号在 `/auth/me` 阶段被误拦截。
- 管理员具体 API 仍由后端路由做二次权限校验。

## 6. 管理员入口与路由保护

页面：

```text
/admin/autoreply-rollout
```

访问规则：

- 未登录：跳 NewCarProject 登录页。
- `super_admin=true`：允许访问。
- 有 `auto_wechat:admin:autoreply`：允许访问。
- 只有 `auto_wechat:admin:ai_reply_records`、`auto_wechat:admin:compute_config`、`auto_wechat:admin:accounts`、`auto_wechat:admin:forbidden_words`、`auto_wechat:douyin_ai_cs`：不允许访问自动回复灰度控制台。

前端侧栏只展示 auto_wechat 本地负责的管理员入口，不展示本地“管理员账号管理”入口。

## 7. 登录默认跳转规则

NewCar 登录成功后不再固定跳 `/douyin-cs/workbench`。

默认跳转优先级：

1. 有 `auto_wechat:admin:autoreply`：跳 `/admin/autoreply-rollout`。
2. 有 `auto_wechat:admin:ai_reply_records`：跳 `/admin/ai-reply-records`。
3. 只有 `auto_wechat:admin:accounts` 或 `auto_wechat:admin:forbidden_words`：跳本地提示页，提示该管理功能请在 NewCarProject 操作。
4. 其它管理员权限暂无本地页面时：跳本地提示页，提示暂无可访问管理员功能。
5. 商户侧按已授权能力进入第一个可访问能力中心：
   - `auto_wechat:douyin_ai_cs`
   - `auto_wechat:leads`
   - `auto_wechat:agent`
   - `auto_wechat:compute`

redirect / next 类路径仍必须经过前端 allowlist，不允许跳外部 URL、本地 mock login 或旧 `/auth/callback`。

## 8. Logout 规则

NewCar 模式下点击退出登录：

- 清理 `sessionStorage.external_token`。
- 清理 NewCar redirect 本地状态。
- 清理前端用户状态。
- 跳转 `VITE_NEWCAR_LOGIN_URL`。

默认示例：

```text
VITE_NEWCAR_LOGIN_URL=http://192.168.110.19:5174/login
```

logout 不回退到 auto_wechat mock 登录页，不输出 token / cookie。

## 9. Admin API 权限规则

后端文件：

```text
app/routers/admin_autoreply_rollout.py
```

`/admin/autoreply/*` 权限规则：

- 未登录：401。
- `super_admin=true`：允许访问。
- `permission_codes` 包含 `auto_wechat:admin:autoreply`：允许访问。
- 其它权限：403。

不把以下权限当作自动回复灰度控制权限：

- `auto_wechat:admin:ai_reply_records`
- `auto_wechat:admin:compute_config`
- `auto_wechat:admin:accounts`
- `auto_wechat:admin:forbidden_words`
- `auto_wechat:douyin_ai_cs`

## 10. 测试结果

本轮验证命令：

```text
python -m pytest tests/test_admin_autoreply_rollout_api.py -q
22 passed

python -m pytest tests/test_auth_context.py -q
28 passed

npm run newcar-auth:check
passed

npm run admin-autoreply:check
passed

npm run auth:check
passed

npm run build
passed

python -m py_compile app\routers\admin_autoreply_rollout.py app\auth\dependencies.py app\main.py
passed
```

`npm run build` 仍有既有 warning：

- `/fonts/Barlow-Regular_2.ttf` 构建期未解析，运行期保留。
- chunk size 超过 500 kB。

## 11. 未改内容

本轮未修改：

- 真实自动回复发送 gate。
- `send_ai_auto_reply_for_run`。
- 真实抖音发送上游。
- 真实 LLM。
- 真实 Milvus。
- NewCarProject 服务端。
- NewCar 商户管理 / 违禁词管理 / 管理员账号管理页面。
- NewCar、live-check、Local Agent、19000。
- `/knowledge-training/ask` 和 `/feedback` schema。
