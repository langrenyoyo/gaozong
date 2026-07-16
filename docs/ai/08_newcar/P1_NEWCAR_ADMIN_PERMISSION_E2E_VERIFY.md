# P1-NEWCAR-ADMIN-PERMISSION-E2E-VERIFY-1

> **状态注记（2026-07-16）**：本文为该轮 E2E 验证的历史记录。两处结论已变更：(1) `auto_wechat:admin:forbidden_words` 的违禁词管理已改为 9000 本地功能（前端页已挂载、接通 `/admin/forbidden-words`），不再跳"NewCar-owned"提示页；(2) "自动回复灰度"控制台入口已在前端隐藏，自动发送灰度门禁已放开。当前事实以 `docs/ai/05_PROJECT_CONTEXT.md` 第 8.2 节和 `docs/ai/08_newcar/P1_AUTH_PERMISSION_ROUTE_MATRIX.md` 为准。

## 1. 任务目标

验证 NewCarProject 新增管理员权限码后，auto_wechat 能识别 `auto_wechat:admin:autoreply` 并放行管理员自动回复灰度控制台。

本轮只做验证、诊断脚本和文档补充，不触发真实私信发送，不调用真实抖音发送上游、真实 LLM 或真实 Milvus。

## 2. NewCarProject 新增权限码

- `auto_wechat:admin:autoreply`：自动回复灰度与发送控制台权限，auto_wechat 本轮消费。
- `auto_wechat:admin:return_visit_prompts`：回访提示词管理权限，auto_wechat 当前不把它当作自动回复灰度权限。

不得把以下权限当作自动回复灰度控制台替代权限：

- `auto_wechat:admin:ai_reply_records`
- `auto_wechat:admin:compute_config`
- `auto_wechat:admin:accounts`
- `auto_wechat:admin:forbidden_words`
- `auto_wechat:admin:return_visit_prompts`

## 3. 验证账号类型

自动化测试使用 mock NewCar 上下文验证：

- 管理员权限账号：`permission_codes` 包含 `auto_wechat:admin:autoreply`，`super_admin=false`，`merchant_id=null` 可通过 `/auth/me`。
- 无自动回复灰度权限账号：只有其它 admin 权限或普通商户权限时，访问 `/admin/autoreply/rollout/summary` 返回 403。
- 未登录账号：访问管理员 API 返回 401。

真实 NewCar 浏览器 E2E 需要 fresh code/token 或浏览器登录态。本次未写入真实 token、cookie 或账号凭据。

## 4. /auth/me 脱敏预期结果

真实 NewCar 管理员账号通过后，`/auth/me` 应满足：

```text
source_system=new_car_project
permission_codes 包含 auto_wechat:admin:autoreply
super_admin 不要求 true
merchant_id 可为空
```

管理员权限账号不应因为本地 merchant binding 缺失被 403。普通商户账号仍必须命中本地商户绑定。

## 5. 默认跳转结果

前端默认跳转规则：

1. `auto_wechat:admin:autoreply` 命中时进入 `/admin/autoreply-rollout`。
2. `auto_wechat:admin:ai_reply_records` 命中时进入 `/admin/ai-reply-records`。
3. `admin:accounts` / `admin:forbidden_words` 等 NewCarProject 归属功能进入本地提示页。
4. 普通商户按已授权能力中心进入，不默认跳管理员页面。

redirect / next 路径必须经过 allowlist，不允许跳外部 URL、本地 mock login 或旧 `/auth/callback`。

## 6. Admin 菜单结果

侧栏只在具备 `auto_wechat:admin:autoreply` 时展示“自动回复灰度”。

只有 `auto_wechat:admin:ai_reply_records` 时展示“AI回复记录”，不展示“自动回复灰度”。

普通商户权限不展示 admin 菜单。NewCarProject 负责的本地“商户管理 / 违禁词管理 / 管理员账号管理”入口不在 auto_wechat 展示。

## 7. Admin Rollout 页面结果

页面路径：

```text
/admin/autoreply-rollout
```

页面加载 `GET /admin/autoreply/rollout/summary`，显示 env fuse、DB rollout、白名单、runs 等区域。DB 配置为空或 env fuse=false 时只显示阻断状态，不应报错。

页面和 API client 不提供以下危险能力：

```text
force_send
bypass
ignore_gate
set_final_auto_send
```

## 8. Admin API 权限结果

`GET /admin/autoreply/rollout/summary`：

- 未登录：401。
- `super_admin=true`：200。
- `permission_codes` 包含 `auto_wechat:admin:autoreply`：200。
- 只有 `auto_wechat:admin:return_visit_prompts` 或其它非 autoreply admin 权限：403。
- 普通商户权限：403。

## 9. Logout 跳转结果

NewCar 模式退出登录应：

1. 清理 `sessionStorage.external_token`。
2. 清理 NewCar redirect 本地状态。
3. 跳转 `VITE_NEWCAR_LOGIN_URL`。
4. 不回退 auto_wechat mock 登录页。
5. URL 不泄露 token 或 cookie。

当前 LAN 预期：

```text
http://192.168.110.19:5174/login
```

## 10. 本轮补充

- 后端测试补充 `auto_wechat:admin:return_visit_prompts` 不能单独访问自动回复灰度 API。
- 新增前端静态 E2E 检查脚本 `frontend/scripts/check-newcar-admin-permission-e2e.mjs`。
- 新增 npm 脚本 `newcar-admin:e2e-check`。

## 11. 测试结果

本轮已执行：

```text
python -m pytest tests/test_admin_autoreply_rollout_api.py -q
23 passed

python -m pytest tests/test_auth_context.py -q
28 passed

npm run newcar-auth:check
passed

npm run admin-autoreply:check
passed

npm run auth:check
passed

npm run newcar-admin:e2e-check
passed

npm run build
passed

python -m py_compile app\auth\context.py app\auth\dependencies.py app\routers\admin_autoreply_rollout.py app\main.py
passed
```

`npm run build` 保留既有 warning：

- `/fonts/Barlow-Regular_2.ttf` 构建期未解析，运行期保留。
- chunk size 超过 500 kB。

## 12. 真实 E2E 状态

本轮未执行真实 NewCar 浏览器 E2E，原因是当前任务环境未提供 fresh code/token 或可复用浏览器登录态。

允许用户侧补充执行的脱敏验收口径：

```text
/api/auth/me 200
source_system=new_car_project
permission_codes 包含 auto_wechat:admin:autoreply
super_admin 不要求 true
/api/admin/autoreply/rollout/summary 200
logout 跳 VITE_NEWCAR_LOGIN_URL
```

不得在报告中贴 token、cookie 或 secret。

## 13. 未改内容

本轮未修改：

- 真实自动回复发送 gate。
- 真实抖音发送上游。
- 真实 LLM。
- 真实 Milvus。
- NewCarProject 服务端。
- 9000 对外 schema。
- `/knowledge-training/ask` 和 `/feedback` schema。
- NewCar、live-check、Local Agent、19000。

## 14. 下一步

如果真实 NewCar 管理员账号或 fresh code/token 可用，可做一次人工 E2E：

1. 从 NewCarProject 登录。
2. 跳转 auto_wechat。
3. 确认默认进入 `/admin/autoreply-rollout`。
4. 确认 `/api/auth/me` 200，且 `permission_codes` 包含 `auto_wechat:admin:autoreply`。
5. 确认 `/api/admin/autoreply/rollout/summary` 200。
6. 点击退出登录，确认跳转 NewCarProject login。
7. 全程不输出 token、cookie 或 secret。
