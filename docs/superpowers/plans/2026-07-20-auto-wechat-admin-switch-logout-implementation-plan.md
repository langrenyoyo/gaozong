# Auto WeChat 管理员切换与退出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 仅修改 auto_wechat，使管理员侧栏只提供“切换到 NewCar”，普通用户退出仅注销 auto_wechat，并在失败时清理持久化本地状态、保留当前 URL 和提供重试。

**Architecture:** 管理员切换由浏览器携带现有 external token 直接调用 NewCar `POST /api/external-auth/switch-to-internal`，使用上游返回的 `redirect_url` 进入 NewCar 首页；切换不撤销或清理 auto_wechat external token。普通用户退出继续调用 9000 `POST /auth/logout`，不再跳 NewCar；失败时只在 React 页面内存保留本次 token 供“重试退出”，不得重新写入浏览器存储。

**Tech Stack:** React 19、TypeScript、Vite、lucide-react、sonner、Node 静态合同检查、pytest

---

## 冻结边界

- 风险等级：L3，完整三权分离。
- 只修改 auto_wechat；`E:\work\project\used-car` 全仓禁止修改。
- 管理员身份继续以 `isAdminLike(user)` 为唯一入口判断，不新增或改写权限码。
- 管理员没有 auto_wechat “退出登录”入口；只显示“切换到 NewCar”。
- 普通用户“退出登录”只注销 auto_wechat external session，不注销 NewCar internal session，不自动跳 NewCar。
- 切换成功不清理 `external_token`、React Query 缓存或 Local Agent token；该动作不是退出。
- 切换接口失败时保持当前登录页面并显示可读错误，不使用硬编码 NewCar 首页地址。
- 退出请求失败时清理 `external_token`、NewCar 回跳状态、React Query 缓存、Local Agent token 和受保护页面；浏览器 URL 不变；失败 token 只允许留在页面内存供重试。
- 不新增依赖，不修改 9000 后端、环境变量、数据库、迁移、权限或 used-car。

## 文件结构

- `frontend/src/api/auth.ts`：封装浏览器直调切换合同与 9000 退出请求；校验 `redirect_url`。
- `frontend/src/App.tsx`：协调切换、退出、内存重试和退出结果页。
- `frontend/src/pages/Index.tsx`：向侧栏透传切换处理器和加载状态。
- `frontend/src/components/SideNav.tsx`：管理员/普通用户互斥显示切换或退出按钮。
- `frontend/scripts/check-newcar-direct-auth.mjs`：冻结浏览器直调切换合同。
- `frontend/scripts/check-newcar-admin-entry-logout-route.mjs`：冻结管理员无退出及普通用户退出失败语义。
- `frontend/scripts/check-newcar-admin-permission-e2e.mjs`：同步管理员导航端到端静态合同，删除已失效的旧退出断言。
- `docs/external-auth-integration.md`：同步切回内部系统接口、权限码和退出边界。
- `docs/ai/05_PROJECT_CONTEXT.md`：原位更新当前鉴权事实。

### Task 1: 先冻结新的鉴权合同

**Files:**
- Modify: `frontend/scripts/check-newcar-direct-auth.mjs`
- Modify: `frontend/scripts/check-newcar-admin-entry-logout-route.mjs`
- Modify: `frontend/scripts/check-newcar-admin-permission-e2e.mjs`

- [ ] **Step 1: 在合同脚本中加入切换与退出断言**

三个脚本至少冻结以下事实：

```js
assertIncludes(authApi, "/api/external-auth/switch-to-internal", "管理员切换由浏览器直调 NewCar");
assertIncludes(authApi, "Authorization: `Bearer ${token}`", "切换请求携带 external token");
assertIncludes(authApi, 'protocol !== "http:" && protocol !== "https:"', "切换地址只允许 HTTP(S)");
assertIncludes(app, "window.location.assign(redirectUrl)", "切换使用上游 redirect_url");
assertIncludes(sideNav, "isAdminUser ?", "管理员与普通用户底部动作互斥");
assertIncludes(sideNav, "切换到 NewCar", "管理员显示切换入口");
assertIncludes(app, 'logoutAutoWechat(retryToken)', "退出和重试都走 9000");
assertIncludes(app, "logoutRetryTokenRef", "失败 token 只保留在页面内存");
assertNotIncludes(app, 'redirectToNewCarLogin({ message: "正在退出登录', "退出不再跳 NewCar");
```

删除或替换已经与主线事实冲突的断言，包括“管理员默认进入已隐藏的自动回复灰度页”和“退出后跳 NewCar 登录页”；不得降低其它权限、安全断言。

- [ ] **Step 2: 运行红灯检查并确认因缺少新行为失败**

Run:

```powershell
& 'C:\Program Files\nodejs\node.exe' scripts/check-newcar-direct-auth.mjs
& 'C:\Program Files\nodejs\node.exe' scripts/check-newcar-admin-entry-logout-route.mjs
& 'C:\Program Files\nodejs\node.exe' scripts/check-newcar-admin-permission-e2e.mjs
```

Expected: 至少一个脚本因缺少 `switch-to-internal`、管理员切换按钮或内存退出重试而失败；失败不得来自语法错误或文件路径错误。

### Task 2: 实现管理员切换和普通用户退出闭环

**Files:**
- Modify: `frontend/src/api/auth.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Index.tsx`
- Modify: `frontend/src/components/SideNav.tsx`

- [ ] **Step 1: 在 `auth.ts` 实现最小 API 合同**

实现等价于以下接口，不得硬编码 NewCar 首页：

```ts
export async function switchToInternalSystem(): Promise<string> {
  const token = getExternalToken();
  if (!NEWCAR_AUTH_BASE_URL || !token) throw new Error("登录已过期，请重新登录");
  const response = await fetch(`${NEWCAR_AUTH_BASE_URL}/api/external-auth/switch-to-internal`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) throw new Error(response.status === 403 ? "当前账号无法切换到 NewCar" : "切换到 NewCar 失败，请重试");
  const data = (await response.json()) as { redirect_url?: unknown };
  if (typeof data.redirect_url !== "string") throw new Error("NewCar 返回的切换地址无效");
  const redirectUrl = new URL(data.redirect_url);
  if (redirectUrl.protocol !== "http:" && redirectUrl.protocol !== "https:") throw new Error("NewCar 返回的切换地址无效");
  return redirectUrl.toString();
}

export async function logoutAutoWechat(token: string | null): Promise<void> {
  const response = await fetch(`${API_BASE_URL || ""}/auth/logout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: "{}",
  });
  if (!response.ok) throw new Error("退出失败，请重试");
}
```

错误不得包含 token、上游原始响应体或一次性 code。

- [ ] **Step 2: 在 `App.tsx` 实现互不混用的动作状态**

实现以下等价状态和流程：

```ts
type LogoutViewState = "idle" | "pending" | "success" | "failed";
const logoutRetryTokenRef = useRef<string | null>(null);

const performLogout = async (retryToken: string | null) => {
  setLogoutViewState("pending");
  try {
    await logoutAutoWechat(retryToken);
    logoutRetryTokenRef.current = null;
    setLogoutViewState("success");
  } catch {
    logoutRetryTokenRef.current = retryToken;
    setLogoutViewState("failed");
  } finally {
    queryClient.clear();
    clearExternalToken();
    clearNewCarRedirectState();
    clearAllAgentTokens();
    setUser(null);
    setAuthError(null);
  }
};

const handleSwitchToNewCar = async () => {
  const redirectUrl = await switchToInternalSystem();
  window.location.assign(redirectUrl);
};
```

要求：

- 退出结果页在 BrowserRouter 之前渲染，所以 URL 保持不变且受保护页面卸载。
- 失败页提供“重试退出”，调用 `performLogout(logoutRetryTokenRef.current)`。
- 成功页明确显示已退出 auto_wechat，并可使用既有统一登录动作重新登录。
- 切换失败使用现有 `sonner` 提示并解除按钮加载态；不得清理 auto_wechat 登录态。

- [ ] **Step 3: 在 `Index.tsx` 和 `SideNav.tsx` 透传并渲染互斥按钮**

侧栏底部使用既有样式、lucide 图标和稳定尺寸：

```tsx
{isAdminUser ? (
  <button type="button" onClick={onSwitchToNewCar} disabled={switchingToNewCar} aria-label="切换到 NewCar" title="切换到 NewCar">
    <ExternalLinkIcon size={16} />
    {expanded ? <span>切换到 NewCar</span> : null}
  </button>
) : (
  <button type="button" onClick={onLogout} aria-label="退出登录">
    <LogOutIcon size={16} />
    {expanded ? <span className="truncate">{user.account} 退出</span> : null}
  </button>
)}
```

不得按具体管理员权限码重复判断，不得让管理员同时看到两个按钮。

- [ ] **Step 4: 运行绿灯与构建检查**

Run:

```powershell
& 'C:\Program Files\nodejs\node.exe' scripts/check-newcar-direct-auth.mjs
& 'C:\Program Files\nodejs\node.exe' scripts/check-newcar-admin-entry-logout-route.mjs
& 'C:\Program Files\nodejs\node.exe' scripts/check-newcar-admin-permission-e2e.mjs
$env:Path='C:\Program Files\nodejs;'+$env:Path
& 'C:\Program Files\nodejs\npm.cmd' run build
& 'C:\Program Files\nodejs\npm.cmd' run lint
```

Expected: 三个合同脚本退出码 0；build 退出码 0；lint 无新增错误。若全量 lint 受既有文件或环境阻塞，必须对四个修改的 TypeScript/TSX 文件运行定向 eslint，并如实记录全量阻塞。

### Task 3: 同步当前事实文档并做回归

**Files:**
- Modify: `docs/external-auth-integration.md`
- Modify: `docs/ai/05_PROJECT_CONTEXT.md`

- [ ] **Step 1: 原位更新鉴权事实**

文档必须明确：

```text
管理员：只显示“切换到 NewCar”；浏览器直调 /api/external-auth/switch-to-internal；成功使用上游 redirect_url；切换不是退出，不清 auto_wechat token。
普通用户：退出只针对 auto_wechat；调用 9000 /auth/logout；成功或失败均不自动跳 NewCar；失败清理持久化本地状态并允许页面内存重试。
权限：管理员入口由 isAdminLike 语义（super_admin 或 auto_wechat:admin:*）决定，具体页面权限仍分别校验。
```

`docs/external-auth-integration.md` 的权限码列表以 `frontend/src/features/capabilities.ts` 当前 `PERMISSIONS` 为准，并加入 `switch-to-internal` 请求/响应合同；不得将 used-car 配置地址硬编码为 auto_wechat 常量。

- [ ] **Step 2: 运行后端不变性与相关回归**

Run:

```powershell
py -m pytest -q tests/test_newcar_logout.py
py -m pytest -q tests/test_frontend_capability_navigation.py::test_frontend_app_and_sidenav_consume_feature_aggregation tests/test_env_profile_templates.py::test_frontend_static_checks_read_root_development_template
git diff --check
```

Expected: 6 个 NewCar logout 后端测试通过；两个定向前端/环境合同测试通过；`git diff --check` 无输出。

- [ ] **Step 3: 完成浏览器验收**

在隔离工作树启动 mock 9000 与 Vite，至少检查 1440x900 和 1024x768：

- 管理员：展开与折叠侧栏均只看到“切换到 NewCar”，无“退出登录”；失败时仍留在当前管理页并有错误提示。
- 普通用户：只看到“退出登录”；模拟 9000 logout 失败后 URL 不变、受保护内容卸载、出现“重试退出”；重试成功后显示退出成功态。
- 所有按钮文本无截断/重叠，折叠图标有可访问名称，控制台无新增错误。

保存截图为测试临时证据，不提交截图或构建产物。

- [ ] **Step 4: 创建本地候选提交**

只暂存本计划允许文件，提交信息使用简体中文，例如：

```text
修复：区分管理员切换与系统退出
```

不得推送、合并或发布。
