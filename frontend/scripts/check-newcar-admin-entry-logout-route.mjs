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
    throw new Error(`${label}: still contains ${unexpected}`);
  }
}

const app = read("src/App.tsx");
const authApi = read("src/api/auth.ts");
const apiClient = read("src/api/client.ts");
const capabilities = read("src/features/capabilities.ts");
const sideNav = read("src/components/SideNav.tsx");
const newcarRedirect = read("src/newcarRedirect.ts");
const envExample = read("../.env.lan.example");
const adminCheck = read("scripts/check-admin-autoreply-rollout-page.mjs");

assertIncludes(capabilities, "adminAutoreply", "权限常量包含自动回复灰度权限");
assertIncludes(capabilities, "hasAdminPermission", "统一权限工具包含管理员判断");
assertIncludes(capabilities, "isAdminLike", "统一权限工具包含 admin-like 判断");
assertIncludes(capabilities, 'code.startsWith("auto_wechat:admin:")', "管理员判断基于 admin 权限前缀");
assertIncludes(capabilities, "auto_wechat:douyin_ai_cs", "抖音 AI 客服使用统一 NewCar 权限码");
assertNotIncludes(capabilities, "auto_wechat:douyin_accounts", "不新增抖音账号独立权限码");
assertNotIncludes(capabilities, "auto_wechat:admin:douyin_accounts", "不新增管理员抖音账号权限码");
assertNotIncludes(capabilities, "auto_wechat:admin:knowledge_training", "不新增管理员知识训练权限码");

assertIncludes(app, "admin: hasAdminPermission", "App 用户模型保留 admin 判断结果");
assertIncludes(app, "adminLike", "App 根据 NewCar admin 权限识别管理员身份");
assertIncludes(app, "defaultPathForUser", "App 统一处理登录后默认跳转");
assertIncludes(app, "PERMISSIONS.adminAiReplyRecords", "默认跳转识别当前可见的 AI 回复记录权限");
assertIncludes(app, '"/admin/autoreply-rollout"', "自动回复灰度历史路由保持兼容");
assertNotIncludes(
  app,
  'if (hasPermission(user, PERMISSIONS.adminAutoreply)) return "/admin/autoreply-rollout";',
  "管理员不再默认进入已隐藏的自动回复灰度页",
);
assertIncludes(app, "暂无可访问管理员功能", "管理员无本地可访问功能时显示明确提示");
assertIncludes(app, "该管理功能请在 NewCarProject 操作", "NewCar 管理功能显示归属提示");
assertIncludes(app, "logoutRetryTokenRef", "logout 失败 token 只保留在页面内存");
assertIncludes(app, "logoutAutoWechat(retryToken)", "logout 重试继续调用 9000 /auth/logout");
assertIncludes(app, "退出失败，请重试", "logout 失败显示固定可读文案");
assertIncludes(app, 'const succeeded = state === "succeeded"', "成功退出状态单独渲染");
assertIncludes(app, "onRetry, onRelogin", "退出状态页接收重新登录动作");
assertIncludes(app, "onRelogin={handleRelogin}", "成功退出状态页复用既有重新登录处理器");
assertIncludes(app, "重新登录", "成功退出状态页提供重新登录按钮");
assertIncludes(app, 'setLogoutViewState("idle")', "重新登录先离开退出状态页");
assertIncludes(app, "logoutRetryTokenRef.current = null", "重新登录清理内存重试 token");
assertIncludes(app, "setNewCarAuthRedirectSuppressed(true)", "logout 开始前抑制并发 401 跳转");
assertIncludes(app, "setNewCarAuthRedirectSuppressed(false)", "主动重新登录前恢复 401 跳转");
assertNotIncludes(app, 'redirectToNewCarLogin({ message: "正在退出登录', "logout 不再跳 NewCar 登录页");
assertIncludes(authApi, 'fetch(`${baseUrl}/auth/logout`', "logout 使用直接 fetch 调用 9000");
assertIncludes(authApi, "headers.Authorization = `Bearer ${token}`", "logout 显式透传 Bearer token");
assertIncludes(authApi, "body: JSON.stringify({})", "logout 使用空对象请求体");
assertIncludes(authApi, "AUTH_REQUEST_TIMEOUT_MS = 10_000", "切换与退出请求使用十秒超时");
assertIncludes(authApi, "AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS)", "切换与退出请求携带中止信号");
assertIncludes(apiClient, "!newCarAuthRedirectSuppressed && shouldRedirectToNewCarLogin(error)", "并发 401 遵守退出抑制门禁");
assertNotIncludes(app, 'return "/douyin-cs/workbench";', "登录后默认跳转不能固定到客服工作台");

assertIncludes(sideNav, "canViewAdminItem", "侧栏按具体权限过滤 admin 菜单");
assertIncludes(sideNav, "PERMISSIONS.adminReturnVisitPrompts", "侧栏管理员菜单继续使用具体权限");
assertIncludes(capabilities, "auto_wechat:admin:autoreply", "权限常量保留 NewCar 自动回复灰度权限码");
assertNotIncludes(sideNav, 'user.role === "super_admin")', "侧栏自动回复灰度不能只认 super_admin");
assertNotIncludes(sideNav, '"admin-accounts"', "不展示 auto_wechat 本地管理员账号管理入口");
assertIncludes(sideNav, "isAdminUser ? (", "管理员与普通用户底部动作互斥");
assertIncludes(sideNav, "onSwitchToNewCar", "管理员侧栏提供切换到 NewCar 动作");
assertIncludes(sideNav, "切换到 NewCar", "管理员侧栏显示切换到 NewCar 文案");
assertIncludes(sideNav, "onClick={onLogout}", "普通用户侧栏保留退出动作");

assertIncludes(authApi, "/api/external-auth/switch-to-internal", "切换由浏览器直调 NewCar");
assertIncludes(authApi, 'redirectUrl.protocol !== "http:"', "切换只允许 HTTP(S) redirect_url");
assertIncludes(app, "window.location.assign(redirectUrl)", "切换使用上游返回的 redirect_url");

assertIncludes(newcarRedirect, '"/admin/autoreply-rollout"', "redirect allowlist 包含自动回复灰度");
assertIncludes(newcarRedirect, "isAllowedRedirectPath", "redirect 使用安全 allowlist");
assertIncludes(newcarRedirect, 'url.origin !== window.location.origin', "redirect 拒绝外部 URL");
assertIncludes(newcarRedirect, 'url.pathname === "/login"', "redirect 拒绝本地 mock 登录页");
assertIncludes(newcarRedirect, "NEWCAR_LOGIN_URL", "登录过期和重新登录仍使用 NewCar 登录 URL");

assertIncludes(envExample, "VITE_NEWCAR_LOGIN_URL=http://192.168.110.19:5174/login", "env 示例记录 NewCar 登录页");
assertIncludes(adminCheck, "auto_wechat:admin:autoreply", "admin 静态检查覆盖自动回复灰度权限码");
assertIncludes(adminCheck, "hasAdminPermission", "admin 静态检查覆盖统一管理员权限工具");

for (const forbidden of ["force_send", "bypass", "ignore_gate", "set_final_auto_send"]) {
  assertNotIncludes(app, forbidden, `App 不包含危险字段 ${forbidden}`);
  assertNotIncludes(sideNav, forbidden, `SideNav 不包含危险字段 ${forbidden}`);
}

console.log("NewCar admin entry/logout route check passed.");
