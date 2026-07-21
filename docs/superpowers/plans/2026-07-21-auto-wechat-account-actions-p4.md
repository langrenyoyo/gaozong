# auto_wechat 商户改密与外部系统切换退出修正实施计划 P4

> **给执行窗口：** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项施工。每个步骤使用复选框跟踪。

**目标：** 在不修改 `used-car` 的前提下，把商户自助改密、管理员切换 NewCar、普通商户退出 auto_wechat、管理员退出当前浏览器全部登录态统一接入并完成可验证的权限与状态清理闭环。

**架构：** 9000 继续作为 auto_wechat 的鉴权门面：商户改密由前端调用 9000 `/auth/password`，9000 只携带当前 Bearer 代理到 NewCar；管理员当前浏览器退出必须由浏览器直调 NewCar `/api/external-auth/logout-current-browser`，因为 9000 无法读取 NewCar 域 Cookie。管理员保留“切换到 NewCar”和新增独立“退出登录”两个动作，普通商户保留 auto_wechat 普通退出，并新增自助改密入口；退出或改密造成的本地状态变化都通过页面内状态屏处理，避免晚到 401 覆盖结果。

**技术栈：** FastAPI、`httpx`、React、TypeScript、Vite、现有 Radix Dialog、pytest、Node 静态合同脚本、Chrome CDP/DOM/网络断言。

---

## 阶段与治理冻结

- `Task-ID`：`P1-AUTO-WECHAT-ACCOUNT-ACTIONS-P4-1`
- `Plan-Revision`：`P4`
- `Plan-Identifier`：本文件路径
- `Target-Integration-Base`：`1b52412da2f0be9114ca81f736e687ba24403252`（包含 `137db8e...` 之后已落地的抖音 webhook 布尔/PostgreSQL 契约修正；该组文件不属于 P4 施工范围）
- `Previous-Candidate`：`d3e723da35d649d5403a4d5bdabd47e2147a9462`，因需求新增改密与管理员独立退出而废止，旧测试和批准不得转移。
- `Risk-Level`：`L3`
- `Workflow-Mode`：`full-three-authority`
- `Activation-Reasons`：鉴权、权限、跨服务接口合同、会话撤销、Cookie 清理和真实外部跳转同时变化；错误可能导致越权、残留登录态或错误退出其他设备。
- `Owner-Constraints`：只修改 `auto_wechat`；禁止修改 `E:\work\project\used-car`；不推送、不合并、不发布，直到审批窗口基于同一候选和独立测试证据另行批准。Owner 已于 2026-07-21 接受停用账号在 external 鉴权入口统一返回 401，并批准复用本计划列明的现有隔离执行/测试工作树。
- `执行工作树`：复用现有干净 `E:\work\project\auto_wechat\.worktrees\auto-wechat-admin-switch-logout-exec-p2`，仅允许快进到本计划提交；不新建工作树或分支。
- `测试工作树`：复用现有干净 `E:\work\project\auto_wechat\.worktrees\auto-wechat-admin-switch-logout-test-p2`；不得使用留有产物的 `test-p2-r1`，测试时从候选完整哈希重新 detached checkout。

本阶段目标是形成一个包含 P3 既有切换/普通退出修正和本 P4 改密/管理员退出修正的本地候选。禁止把上游账号管理、NewCar 内部 `/api/logout`、全设备退出、数据库迁移、权限码新增、部署和生产发布混入本阶段。

## 已核验事实与上游前置

1. `used-car` 当前提交为 `279f12896ca263a9bf403e2d2d0e5e5f7ea68b20`，工作树干净，已实现：
   - `POST /api/external-auth/password`：按 external token 定位用户，要求 `role=external_user`，校验旧密码，最短 8 位，更新哈希并撤销该用户全部 active 会话。
   - `POST /api/external-auth/logout-current-browser`：撤销当前 external 会话，读取 `new_car_internal_session`，仅在有效且同用户时撤销 internal 会话，并始终删除两个内部 Cookie，返回 `logged_out=1` 地址。
   - NewCar 前端识别 `logged_out=1`，清理 `new_car_auth_token` 并停留登录页。
2. 上游实现使用现有 `db()` 事务，审计详情未写密码或 token 明文；CORS 开启 `allow_credentials=True`，生产要求显式 HTTPS `CORS_ORIGINS`。
3. 公共 external 鉴权先筛 `status='active'`，所以停用账号不会进入改密路由内的 `ACCOUNT_DISABLED` 分支，当前真实响应是 401。Owner 已接受停用账号统一 401，本计划以该语义验收；若上游未来显式返回 `ACCOUNT_DISABLED`，9000 仍兼容映射为 403。
4. 上游 `scripts/smoke_rbac.py` 已覆盖基本改密、旧 token 失效和当前 external 退出，但未覆盖同用户 internal Cookie、异用户 Cookie、其他设备会话保留、两个 `Set-Cookie` 删除头和所有建议错误码；这些必须由独立测试补齐或明确记录未完成项。

## 文件边界

允许修改或新增：

- `app/auth/newcar_client.py`：复用现有外部认证客户端，新增代理改密方法；不记录密码、token，不改变现有换码、查询、普通退出语义。
- `app/routers/auth.py`：新增 9000 `POST /auth/password` 门面，透传已约定错误码并统一脱敏异常。
- `tests/test_newcar_logout.py`：补充外部客户端新方法的请求、错误码、超时和敏感信息回归。
- `tests/test_newcar_password.py`：新增 9000 改密门面 API 集成测试。
- `frontend/src/api/auth.ts`：新增商户改密代理调用和管理员当前浏览器退出直调；保留现有切换、普通退出 URL 与超时语义。
- `frontend/src/api/client.ts`：保留并复用退出期间 401 重定向抑制；只在确有并发状态需要时补充可复用的状态接口。
- `frontend/src/App.tsx`：管理改密弹窗、管理员双动作、改密成功后的重新登录状态、管理员当前浏览器退出结果及本地清理。
- `frontend/src/components/SideNav.tsx`：按管理员/普通商户角色显示互斥或组合动作：管理员显示“切换到 NewCar”和“退出登录”，普通商户显示“修改密码”和“退出登录”。
- `frontend/src/components/ChangePasswordDialog.tsx`：新增最小可访问改密表单，复用现有 Dialog 组件，不引入依赖。
- `frontend/src/pages/Index.tsx`：向侧栏转发改密和管理员退出回调及状态。
- `frontend/scripts/check-newcar-account-actions.mjs`：新增静态合同检查，覆盖接口路径、凭据、角色互斥、无 user_id/merchant_id、状态抑制与 NewCar 回跳。
- `docs/external-auth-integration.md`：原位更新 auto_wechat 调用契约、管理员退出语义、改密门面和错误处理。
- `docs/ai/05_PROJECT_CONTEXT.md`：原位更新当前鉴权事实、管理员/商户侧栏动作及上游依赖状态。

禁止修改：

- `E:\work\project\used-car\**`；
- `app/models.py`、迁移、数据库、Docker、环境模板、部署文件、权限码定义；
- `frontend/package.json`、`frontend/package-lock.json`、TypeScript 配置；
- 微信自动化、`input_writer`、`contact_searcher`、Local Agent 代码；
- 任何未列出的源码、测试、文档和构建产物。

## 真实调用链与数据边界

### 商户修改密码

```text
SideNav“修改密码”
  -> App 中 ChangePasswordDialog
  -> frontend/src/api/auth.ts changeExternalPassword()
  -> 9000 POST /auth/password（Authorization: Bearer external_token）
  -> NewCarProjectAuthClient.change_external_password()
  -> NewCar POST /api/external-auth/password
  -> NewCar users.password_hash + user_sessions 全部 active 会话撤销
  -> 9000 脱敏返回
  -> 前端清 sessionStorage external_token、清 redirect 状态、停留本页显示重新登录
```

9000 不接受或转发 `user_id`、`merchant_id`，请求体只允许 `old_password`、`new_password`；9000 不保存密码，不记录密码/token。成功后 external token 已失效，前端不得继续访问受保护数据。

### 管理员切换到 NewCar

```text
管理员点击“切换到 NewCar”
  -> 浏览器直调 NewCar POST /api/external-auth/switch-to-internal
  -> Authorization: Bearer external_token
  -> 返回一次性 internal_code + redirect_url
  -> 校验 redirect_url 为 HTTP(S) 后跳转
```

切换不清理 auto_wechat external token，不调用任何退出接口。

### 普通商户退出 auto_wechat

```text
普通商户点击“退出登录”
  -> 9000 POST /auth/logout
  -> 9000 调 NewCar 既有 POST /api/external-auth/logout
  -> 仅撤销当前 external 会话
  -> 前端清本地状态并留在当前 URL 的结果页；失败保留页面内存 token 供重试
```

### 管理员退出当前浏览器

```text
管理员点击“退出登录”
  -> 浏览器直调 NewCar POST /api/external-auth/logout-current-browser
     credentials: include
     Authorization: Bearer external_token
  -> NewCar 撤销当前 external 会话和同用户 internal session
  -> NewCar 删除 new_car_internal_session/new_car_internal_csrf
  -> 返回可信 redirect_url?logged_out=1
  -> 前端清 auto_wechat sessionStorage 状态并 replace 到 redirect_url
```

9000 不能读取 NewCar 域 Cookie，因此管理员退出禁止改成调用 9000 `/auth/logout` 或 9000 代理该接口。管理员“退出登录”不等同于其他设备全部退出；NewCar 上游只撤销当前浏览器 internal session。

## 任务分解

### 任务 1：先写后端失败测试，固定 NewCar 代理合同

文件：

- 新增 `tests/test_newcar_password.py`；
- 修改 `tests/test_newcar_logout.py`。

- [ ] 为 `NewCarProjectAuthClient.change_external_password()` 写失败测试：真实模式向 `/api/external-auth/password` 发 `POST`，只带 `Authorization` 与服务头，JSON 精确为两个密码字段，使用现有超时；401/403/400/5xx 转为无敏感明文的 `NewCarAuthError`；mock 模式不访问网络。
- [ ] 为 9000 `/auth/password` 写失败测试：上游成功返回 `ok/relogin_required/revoked_session_scope`；上游各约定错误码映射到 400/401/403；上游 5xx 映射 502；响应字符串不得出现 old/new password 或 Bearer token；请求体中伪造 `user_id`/`merchant_id` 不得被转发。
- [ ] 运行：

```powershell
py -m pytest -q tests/test_newcar_password.py tests/test_newcar_logout.py
```

预期：新增测试先失败，因为客户端门面和路由尚不存在；不允许跳过红灯记录。

### 任务 2：实现 9000 改密门面

文件：

- 修改 `app/auth/newcar_client.py`；
- 修改 `app/routers/auth.py`。

- [ ] 在客户端新增 `change_external_password(token, old_password, new_password)`，沿用 `logout_token()` 的同步 `httpx.post`、服务头和超时；mock 返回固定成功对象；真实模式只把两个密码字段发给上游，异常消息使用固定脱敏文案。
- [ ] 在 `/auth/password` 读取 Bearer token；缺 token 时返回已有统一 401 语义；调用客户端并返回上游成功 JSON；只允许约定字段；把 `OLD_PASSWORD_INVALID`、`PASSWORD_TOO_SHORT`、`PASSWORD_UNCHANGED` 映射为 400，把 `ACCOUNT_TYPE_NOT_ALLOWED`、`ACCOUNT_DISABLED` 映射为 403，把 token 错误映射为 401，不向响应写入密码/token。
- [ ] 在失败日志中只记录 `stage=external_password_proxy`、`token_present`、上游状态码/错误码和 `failure_stage`；禁止记录请求体、Authorization 值和密码。不要修改数据库或新增权限。
- [ ] 运行任务 1 测试，预期全部通过；再运行：

```powershell
py -m pytest -q tests/test_auth_context.py tests/test_newcar_password.py tests/test_newcar_logout.py
```

### 任务 3：前端 API 合同与管理员直连退出

文件：

- 修改 `frontend/src/api/auth.ts`；
- 必要时修改 `frontend/src/api/client.ts`。

- [ ] 新增 `changeExternalPassword(oldPassword, newPassword)`，调用 9000 `/auth/password`，不接受用户 ID 参数，不直接访问 NewCar，不在浏览器日志中输出请求体。
- [ ] 新增 `logoutCurrentBrowserOnNewCar(token)`，调用 `${NEWCAR_AUTH_BASE_URL}/api/external-auth/logout-current-browser`，请求方法 POST、JSON `{}`、`Authorization: Bearer <token>`、`credentials: "include"`、十秒 `AbortSignal.timeout`；解析 `redirect_url`，只接受绝对 HTTP(S) URL，拒绝空值、非 HTTP(S) 和异常 JSON。
- [ ] 保留 `switchToInternalSystem()` 的 endpoint、Bearer、HTTP(S) 校验和连续登录语义；保留 `logoutAutoWechat()` 的 9000 `/auth/logout` 语义，不把普通退出改成上游当前浏览器退出。
- [ ] 若改密或管理员退出共享全局 401 抑制，采用现有 `setNewCarAuthRedirectSuppressed()`，保证请求开始后在途 401 不会跳转 NewCar；400/403 业务失败恢复抑制，成功或结果未知时保持抑制直到结果页/显式重新登录。
- [ ] 运行静态合同脚本前先确认任务 4 的按钮和状态调用尚未实现，脚本应按计划红灯。

### 任务 4：角色化侧栏、改密弹窗和状态清理

文件：

- 新增 `frontend/src/components/ChangePasswordDialog.tsx`；
- 修改 `frontend/src/components/SideNav.tsx`、`frontend/src/pages/Index.tsx`、`frontend/src/App.tsx`。

- [ ] `ChangePasswordDialog` 使用现有 Dialog 组件，字段为原密码、新密码、确认新密码；前端只做空值、长度至少 8、新旧不同、两次新密码一致校验；提交中禁用按钮并显示可访问的 `aria-live` 状态；不得在错误消息中显示密码内容。
- [ ] `SideNav` 增加 `onChangePassword`、`onAdminLogout`、对应 loading 状态。普通商户底部显示“修改密码”和“退出登录”；管理员底部显示“切换到 NewCar”和独立“退出登录”；管理员不显示商户改密，普通商户不显示切换到 NewCar。折叠态使用现有图标并提供 `aria-label/title`。
- [ ] `Index.tsx` 原样转发上述回调和状态，不改变能力中心权限码、页面路由或管理员菜单过滤。
- [ ] `App.tsx` 持有改密弹窗开关和提交状态；改密开始时抑制全局 401。成功时清空 sessionStorage external token、NewCar redirect 状态和本机 Agent token，卸载受保护页面，显示“密码已修改，请重新登录”状态页；400/403 失败保留当前登录态并恢复 401 跳转；网络/5xx 结果未知时清理本地持久状态并停留当前页，页面内保留一次重试入口但不把密码保存在 ref/localStorage/sessionStorage。
- [ ] 普通退出沿用 P3 结果页、内存 token 重试和晚到 401 抑制。
- [ ] 管理员退出开始时抑制 401、卸载受保护页面并只把 external token 保存在页面内存 ref；成功后清本地状态，校验上游 `redirect_url` 后使用 `window.location.replace()` 跳转；失败清本地持久状态并停留当前页显示重试。管理员退出不得调用 9000 `/auth/logout`，不得调用 `switch-to-internal`。
- [ ] 显式“重新登录”动作先解除 401 抑制、清空内存 token/ref 和 redirect 状态，再走现有 `redirectToNewCarLogin()`；不得自动恢复旧 `cookie-session` 或旧 external token。

### 任务 5：补齐静态合同与回归测试

文件：

- 新增 `frontend/scripts/check-newcar-account-actions.mjs`。

- [ ] 静态断言：改密只调用 `/auth/password`；管理员退出只调用 `/api/external-auth/logout-current-browser` 且含 `credentials: "include"`；普通退出仍为 `/auth/logout`；切换仍为 `/api/external-auth/switch-to-internal`；请求不出现 `user_id`/`merchant_id` 业务入参；所有外部 redirect 继续有 HTTP(S) 校验和十秒超时。
- [ ] 静态断言：管理员同时有切换和退出，普通商户有改密和退出；管理员/普通商户动作分支互斥；改密成功、管理员退出成功、普通退出失败和显式重新登录均经过本地状态清理与 401 抑制边界；`ChangePasswordDialog` 不把密码写入存储、日志或 URL。
- [ ] 脚本只读源文件，失败时返回非零，不创建构建产物。
- [ ] 运行：

```powershell
node frontend/scripts/check-newcar-account-actions.mjs
```

### 任务 6：文档原位更新

文件：

- `docs/external-auth-integration.md`；
- `docs/ai/05_PROJECT_CONTEXT.md`。

- [ ] 删除/替换旧的“管理员无退出、只能切换 NewCar”结论，明确管理员有“切换到 NewCar”和“退出当前浏览器全部登录态”两个动作。
- [ ] 写明商户改密走 9000 `/auth/password` 门面，管理员当前浏览器退出浏览器直调 NewCar 并携带 `credentials: include`，普通退出继续只撤销 auto_wechat external 会话。
- [ ] 写明上游固定提交，以及 Owner 已接受停用账号在 external 鉴权入口统一返回 401；不得继续把不可达的 `ACCOUNT_DISABLED` 写成本次强制响应。
- [ ] 写明本轮不修改 used-car、数据库、权限码和部署；文档只保留当前有效事实，不追加与旧结论并存的“补充”。

### 任务 7：完整本地验证与候选提交

- [ ] 在执行工作树核对工作树干净后，仅快进到本计划提交；记录 `git rev-parse HEAD`、`git merge-base --is-ancestor`、允许范围和禁止路径差异。
- [ ] 运行后端：

```powershell
py -m pytest -q tests/test_newcar_password.py tests/test_newcar_logout.py tests/test_auth_context.py
```

- [ ] 运行前端：

```powershell
node frontend/scripts/check-newcar-account-actions.mjs
npm run build
```

若 `npm` 不在 PATH，使用已核验的 Node/npm 绝对路径，但不得提交 `frontend/dist`、`node_modules`、测试结果和 lockfile 变化。

- [ ] 运行定向 ESLint：`App.tsx`、`api/auth.ts`、`api/client.ts`、`SideNav.tsx`、`Index.tsx`、`ChangePasswordDialog.tsx`；Index 既有 lint 必须与 Plan-Commit 基线对比，零新增才可接受。
- [ ] 运行 `git diff --check`，并核对受保护主线路径和 `used-car` 工作树均无变化。
- [ ] 只暂存允许文件，创建中文提交信息，例如：`鉴权：补齐商户改密与管理员当前浏览器退出`；候选提交后立即冻结，不 amend、不 rebase、不追加修改。
- [ ] 回传 `CANDIDATE_READY <完整哈希>`、父提交顺序、差异文件、每项测试结果、未执行项和残余风险。

## 独立测试验收矩阵

测试窗口不得修改业务代码；只使用候选完整哈希。没有图片识别要求，浏览器验收使用 Chrome CDP 的 DOM、网络请求、Cookie、localStorage/sessionStorage、URL 和控制台错误断言。

| 编号 | 场景 | 操作 | 必须结果 |
|---|---|---|---|
| A1 | 商户改密成功 | 商户打开改密弹窗，提交旧密码和新密码 | 9000 收到仅两个密码字段；NewCar 改密成功；全部旧 external token 失效；前端清本地状态并停留重登录状态 |
| A2 | 改密错误码 | 旧密码错误、少于 8 位、新旧相同、无效 token、管理员 token、停用账号 | 业务校验得到约定 400，管理员 token 得到 403，无效/过期 token 与停用账号统一得到 401；不泄露密码/token |
| A3 | 改密会话范围 | 同用户建立多个 external/internal 会话后改密 | 全部 active 会话撤销；成功响应要求重新登录；没有遗留可用旧 token |
| A4 | 普通退出 | 普通商户点击退出 | 只调用 9000 `/auth/logout`；不直调 NewCar 当前浏览器退出；清本地状态；成功/失败停留当前 URL；失败可用内存 token 重试 |
| A5 | 管理员侧栏 | 管理员登录管理页 | 同时显示“切换到 NewCar”和“退出登录”；不显示商户改密；普通商户不显示切换按钮 |
| A6 | 管理员切换 | 点击切换 | 只直调 `/api/external-auth/switch-to-internal`，Bearer 匹配当前 external token，跳转合法 `redirect_url`；auto_wechat token 未清理 |
| A7 | 管理员当前浏览器退出 | 管理员点击退出，浏览器存在同用户 NewCar internal Cookie | 直调 `/api/external-auth/logout-current-browser`，`credentials=include`，Bearer 匹配；上游撤销 external + 同用户 internal；返回 `logged_out=1` 并跳转 NewCar 登录页 |
| A8 | Cookie 隔离 | 异用户 internal Cookie、无效 Cookie、其他设备 internal session | 不得撤销异用户或其他设备；无论 Cookie 有效性均返回删除两个 Cookie 的 `Set-Cookie` |
| A9 | 管理员退出异常 | 503、超时、响应缺 redirect_url、晚到 401 | 不自动跳错系统；清本地持久状态并停留当前 URL 提示重试；控制台无未处理错误；不显示 token/响应原文 |
| A10 | NewCar logged_out | 在 NewCar 登录地址带 `logged_out=1` | 删除当前域 `new_car_auth_token`，不恢复旧 cookie-session，删除 URL 参数并停留登录页 |
| A11 | 权限越权 | 直接调用 9000 改密并伪造 `user_id`/`merchant_id`，普通商户调用管理员动作 | 后端不信任伪造字段；管理员/普通动作按身份分支，后端 external token 和 NewCar 响应为准 |
| A12 | 回归 | 既有 NewCar direct-auth、admin-permission、admin-entry-logout、后端 logout/auth_context | 全部通过；修改文件范围无越界；构建无新增错误 |

## 上游联调交接要求

交给负责 `used-car` 的同事：

1. 保持 `/api/external-auth/password` 与 `/api/external-auth/logout-current-browser` 请求和响应语义不变；不得要求 auto_wechat 传 `user_id`、`merchant_id`。
2. 补充真实测试并同步文档：停用账号在公共 external 鉴权入口统一返回 401；若未来改为可达的 `ACCOUNT_DISABLED` 403，必须作为新的接口合同变更另行通知 auto_wechat。
3. 补充当前浏览器退出的同用户、异用户、无效 Cookie、其他设备会话和两个 Cookie 删除头测试；确认 CORS 对 auto_wechat 实际 Origin 返回精确 `Access-Control-Allow-Origin` 与 `Access-Control-Allow-Credentials: true`。
4. 确认 `redirect_url` 只来自服务端固定 HTTPS 配置，响应不会把 token、密码或内部 Cookie 值写入正文/审计。
5. NewCar 前端继续处理 `logged_out=1`：清理 `new_car_auth_token`、移除参数、停留登录页，不恢复旧 `cookie-session`。

## 失败处理与回滚

- 任一鉴权、权限、Cookie 隔离或会话撤销核心项失败：测试窗口输出 `FAIL`，审批窗口返回 `R1/R2`，新候选必须重新测试。
- 上游实际错误码若偏离本计划已接受的“停用账号统一 401”，且无法由 auto_wechat 兼容：输出 `SPEC_GAP` 后由审批窗口 `REPLAN`，不得由执行或测试窗口自行改变合同。
- 候选提交产生任何新对象后，旧 `CANDIDATE_READY`、`APPROVE_TEST` 和测试结论全部失效。
- 业务回滚只允许审批窗口基于候选哈希决定；本计划不执行 `git reset --hard`、强推、生产部署或数据库回滚。

## 文档影响检查

本轮必受影响文档为 `docs/external-auth-integration.md` 与 `docs/ai/05_PROJECT_CONTEXT.md`，必须原位更新管理员动作、改密门面和上游合同状态。`CLAUDE.md`、`AGENTS.md`、01~04 规则、PostgreSQL 迁移文档和微信自动化专题不受本轮事实影响，执行窗口不得修改。
