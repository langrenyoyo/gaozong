# Auto WeChat 管理员切换与退出返修计划 P2

## 返修原因

旧候选 `3f85312a8b4e0f33ad1d7de822fdd88b4d902e0b` 的独立审查发现并发竞态：退出开始后，页面卸载前已经发出的 Axios 请求可能在上游注销完成后返回 `401`，`frontend/src/api/client.ts` 的全局拦截器仍会跳转 NewCar，覆盖退出结果页并改变浏览器 URL。这违反“退出成功或失败均停留当前 URL”的冻结要求。

该缺陷不能只在旧计划允许文件内可靠修复，因此旧候选废止，计划从 P1 重新规划为 P2。P2 不改变用户目标，只补齐全局鉴权重定向抑制边界。

## 冻结目标与边界

- 风险等级：L3，继续使用完整三权分离。
- 只修改 `auto_wechat`；`E:\work\project\used-car` 全仓禁止修改。
- 管理员仍按 `isAdminLike(user)` 只显示“切换到 NewCar”，不显示 auto_wechat 退出。
- 普通用户退出仍只调用 9000 `POST /auth/logout`；成功或失败都清理持久本地状态、卸载受保护页面、保持当前 URL，不自动跳 NewCar。
- 退出期间及退出结果页抑制全局 401 自动跳转；用户主动点击“重新登录”时恢复正常 NewCar 登录跳转。
- 切换仍由浏览器直调 NewCar `POST /api/external-auth/switch-to-internal`，不清理 auto_wechat 登录态。
- 不修改后端、数据库、环境变量、依赖、权限码、部署配置或 `used-car`。

## 允许修改文件

- `frontend/src/api/client.ts`：增加可控的鉴权重定向抑制接口，并在全局 401 拦截器读取。
- `frontend/src/api/auth.ts`
- `frontend/src/App.tsx`
- `frontend/src/pages/Index.tsx`
- `frontend/src/components/SideNav.tsx`
- `frontend/scripts/check-newcar-direct-auth.mjs`
- `frontend/scripts/check-newcar-admin-entry-logout-route.mjs`
- `frontend/scripts/check-newcar-admin-permission-e2e.mjs`
- `docs/external-auth-integration.md`
- `docs/ai/05_PROJECT_CONTEXT.md`

## 禁止修改文件

- `used-car/**`
- `app/**`
- `tests/**`
- `frontend/package.json`
- 环境、数据库、迁移、部署文件及其它未列出的路径

## 最小实现要求

1. `api/client.ts` 提供模块级的“鉴权重定向抑制”开关或等价接口；拦截器在开关开启时不得调用 `redirectToNewCarLogin`，也不得发出会改变 URL 的重定向。
2. `App.tsx` 在普通退出开始前开启抑制，在成功/失败状态页持续保持；主动重新登录前关闭抑制并清理本地状态。切换到 NewCar路径不使用该开关。
3. 增加可运行合同测试，覆盖：退出期间 Axios 401 不触发 NewCar 重定向；重新登录动作仍可触发正常重定向；管理员/普通用户动作互斥、失败重试和 token 生命周期保持旧合同。
4. 不回显 token、一次性 code、原始响应或异常；保留 HTTP(S) `redirect_url` 校验和十秒请求超时。

## 验收矩阵新增项

| 场景 | 预期 |
|---|---|
| 退出请求期间已有 Axios 请求返回 401 | 不写回跳路径、不调用 `location.replace`，退出结果页保持当前 URL |
| 退出失败后重试 | 仍使用页面内存 token，401 抑制仍有效，重试成功显示退出成功 |
| 成功退出后点击重新登录 | 关闭抑制并按既有流程跳转 NewCar 登录页 |

## 交接要求

- 新候选必须从旧计划提交 `d535fc537ff538e80447c283c2f71db1e6ed1af6` 派生，并记录旧候选已废止。
- 新候选需重新通过代码审查、自动测试和独立浏览器测试；旧候选的任何测试结论不得转移。
- 不推送、不合并、不发布。
