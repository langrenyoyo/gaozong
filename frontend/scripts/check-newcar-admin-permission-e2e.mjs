import fs from "node:fs";
import path from "node:path";

const root = process.cwd();

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function assertIncludes(content, expected, label) {
  if (!content.includes(expected)) {
    throw new Error(`${label}: missing ${expected}`);
  }
}

function assertNotIncludes(content, unexpected, label) {
  if (content.includes(unexpected)) {
    throw new Error(`${label}: contains ${unexpected}`);
  }
}

function assertNotMatches(content, pattern, label) {
  if (pattern.test(content)) {
    throw new Error(`${label}: matched ${pattern}`);
  }
}

const app = read("src/App.tsx");
const capabilities = read("src/features/capabilities.ts");
const sideNav = read("src/components/SideNav.tsx");
const newcarRedirect = read("src/newcarRedirect.ts");
const authToken = read("src/authToken.ts");
const apiClient = read("src/api/client.ts");
const authApi = read("src/api/auth.ts");
const adminApi = read("src/api/adminAutoreplyRollout.ts");
const adminPage = read("src/pages/AdminAutoreplyRolloutPage.tsx");

assertIncludes(capabilities, 'adminAutoreply: "auto_wechat:admin:autoreply"', "权限常量包含自动回复灰度权限码");
assertIncludes(capabilities, 'adminReturnVisitPrompts: "auto_wechat:admin:return_visit_prompts"', "权限常量保留回访提示词权限码");
assertIncludes(capabilities, "code.startsWith(\"auto_wechat:admin:\")", "管理员身份识别使用 admin 权限前缀");
assertIncludes(app, "PERMISSIONS.adminAutoreply", "自动回复灰度历史路由仍使用专属权限");
assertNotIncludes(app, 'return "/admin/autoreply-rollout"', "管理员不再默认跳转到已隐藏的自动回复灰度页");
assertIncludes(app, "PERMISSIONS.adminAiReplyRecords", "AI 回复记录使用独立权限");
assertIncludes(app, "hasAnyNewCarOwnedAdminPermission", "NewCar 归属功能有独立提示路径");
assertIncludes(app, '"/admin/newcar-owned"', "NewCar 归属功能不会落到自动回复灰度页");
assertNotIncludes(app, 'return "/douyin-cs/workbench";', "管理员默认跳转不能固定到客服工作台");

assertIncludes(sideNav, "canViewAdminItem", "侧栏通过统一函数过滤管理员菜单");
assertIncludes(sideNav, "hasPermission(user, permission)", "侧栏按具体权限放行菜单");
assertNotIncludes(sideNav, 'id: "admin-autoreply-rollout"', "侧栏继续隐藏自动回复灰度入口");
assertNotIncludes(sideNav, "PERMISSIONS.adminAutoreply", "隐藏入口不再参与侧栏权限过滤");
assertNotIncludes(sideNav, '"admin-accounts"', "不展示 NewCarProject 归属的管理员账号管理入口");
assertNotIncludes(sideNav, '"forbidden"', "不展示 NewCarProject 归属的违禁词管理入口");
assertIncludes(sideNav, "isAdminUser ? (", "管理员与普通用户底部动作互斥");
assertIncludes(sideNav, "切换到内部系统", "管理员只显示切换动作");
// 退出动作经账号菜单包装函数调用 onLogout()，不再直接 onClick={onLogout}：
// 包装函数必须先关闭账号下拉菜单（setAccountMenuOpen(false)）再调用 onLogout()。
{
  const idx = sideNav.indexOf("onLogout()");
  if (idx === -1) {
    throw new Error("普通用户退出包装函数内调用 onLogout()");
  }
  // 包装函数体在 onLogout() 之前 120 字符内必须先关闭 accountMenuOpen。
  const wrap = sideNav.slice(Math.max(0, idx - 120), idx + 12);
  assertIncludes(wrap, "setAccountMenuOpen(false)", "退出包装函数调用 onLogout 前先关闭 accountMenuOpen");
  assertIncludes(wrap, "onLogout();", "退出包装函数调用 onLogout()");
}
assertNotIncludes(sideNav, "onClick={onLogout}", "退出动作不再直接绑定 onClick={onLogout}");

assertIncludes(newcarRedirect, '"/admin/autoreply-rollout"', "redirect allowlist 包含自动回复灰度路径");
assertIncludes(newcarRedirect, "isAllowedRedirectPath", "redirect 使用安全 allowlist");
assertIncludes(newcarRedirect, 'url.origin !== window.location.origin', "redirect 拒绝外部域名");
assertIncludes(newcarRedirect, 'url.pathname === "/login"', "redirect 拒绝本地 mock 登录页");
assertIncludes(newcarRedirect, "NEWCAR_LOGIN_URL", "登录过期和重新登录使用 NewCar 登录地址");
assertIncludes(app, "clearExternalToken()", "退出登录清理 external_token");
assertIncludes(app, "clearNewCarRedirectState()", "退出登录清理 NewCar redirect 状态");
assertIncludes(app, "logoutRetryTokenRef", "退出失败 token 只保留在 useRef 内存");
assertIncludes(app, "logoutAutoWechat(retryToken)", "重试退出仍调用 9000");
assertIncludes(app, 'const succeeded = state === "succeeded"', "成功退出状态有独立视图");
assertIncludes(app, "onRetry, onRelogin", "退出状态页接收重新登录回调");
assertIncludes(app, "onRelogin={handleRelogin}", "成功退出复用既有重新登录逻辑");
assertIncludes(app, "重新登录", "成功退出显示重新登录按钮");
assertIncludes(app, 'setLogoutViewState("idle")', "重新登录解除 logout 提前返回");
assertIncludes(app, "logoutRetryTokenRef.current = null", "重新登录清空页面内存 token");
assertIncludes(app, "setNewCarAuthRedirectSuppressed(true)", "普通退出抑制在途请求的 401 跳转");
assertIncludes(app, "setNewCarAuthRedirectSuppressed(false)", "主动重新登录恢复正常 401 跳转");
assertNotIncludes(app, 'redirectToNewCarLogin({ message: "正在退出登录', "退出登录不跳 NewCar");
assertIncludes(authToken, 'EXTERNAL_TOKEN_KEY = "external_token"', "登录态使用 sessionStorage.external_token");
assertNotIncludes(authToken, "localStorage", "登录态不落 localStorage");

assertIncludes(apiClient, "Authorization = `Bearer ${token}`", "9000 API 使用 Bearer token");
assertIncludes(apiClient, "!newCarAuthRedirectSuppressed && shouldRedirectToNewCarLogin(error)", "9000 API 的 401 跳转受退出门禁保护");
assertIncludes(authApi, "/api/external-auth/exchange-code", "前端通过 NewCar code 换 token");
assertIncludes(authApi, "/api/external-auth/switch-to-internal", "管理员切换由浏览器直调 NewCar");
assertIncludes(authApi, "headers.Authorization = `Bearer ${token}`", "管理员切换携带 external Bearer token");
assertIncludes(authApi, 'redirectUrl.protocol !== "http:"', "管理员切换拒绝非 HTTP(S) redirect_url");
assertIncludes(authApi, 'fetch(`${baseUrl}/auth/logout`', "普通退出直接调用 9000 避免全局 401 跳转");
assertIncludes(authApi, "AUTH_REQUEST_TIMEOUT_MS = 10_000", "管理员切换与普通退出使用十秒超时");
assertIncludes(authApi, "AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS)", "管理员切换与普通退出携带中止信号");
assertIncludes(app, "window.location.assign(redirectUrl)", "管理员切换使用上游返回的 redirect_url");
assertIncludes(adminApi, '"/admin/autoreply/rollout/summary"', "summary API 指向管理员自动回复控制台接口");
assertIncludes(adminPage, "getAutoreplyRolloutSummary", "页面加载 summary API");
assertIncludes(adminPage, "系统级真实发送熔断中", "页面展示 env 熔断状态");

for (const forbidden of ["force_send", "bypass", "ignore_gate", "set_final_auto_send"]) {
  assertNotIncludes(app, forbidden, `App 不包含危险字段 ${forbidden}`);
  assertNotIncludes(sideNav, forbidden, `SideNav 不包含危险字段 ${forbidden}`);
  assertNotIncludes(adminPage, forbidden, `控制台页面不包含危险字段 ${forbidden}`);
  assertNotIncludes(adminApi, forbidden, `控制台 API client 不包含危险字段 ${forbidden}`);
}

console.log("NewCar admin permission E2E static check passed.");
