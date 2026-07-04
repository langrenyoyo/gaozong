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

function blockFrom(content, marker, endMarker) {
  const start = content.indexOf(marker);
  if (start < 0) {
    throw new Error(`missing marker ${marker}`);
  }
  const end = content.indexOf(endMarker, start);
  if (end < 0) {
    throw new Error(`missing end marker ${endMarker}`);
  }
  return content.slice(start, end);
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
assertIncludes(app, "PERMISSIONS.adminAutoreply", "默认跳转使用自动回复灰度专属权限");
assertIncludes(app, 'return "/admin/autoreply-rollout"', "自动回复灰度管理员默认跳转到控制台");
assertIncludes(app, "PERMISSIONS.adminAiReplyRecords", "AI 回复记录使用独立权限");
assertIncludes(app, "hasAnyNewCarOwnedAdminPermission", "NewCar 归属功能有独立提示路径");
assertIncludes(app, '"/admin/newcar-owned"', "NewCar 归属功能不会落到自动回复灰度页");
assertNotIncludes(app, 'return "/douyin-cs/workbench";', "管理员默认跳转不能固定到客服工作台");

assertIncludes(sideNav, "PERMISSIONS.adminAutoreply", "侧栏自动回复灰度使用专属权限");
assertIncludes(sideNav, "canViewAdminItem", "侧栏通过统一函数过滤管理员菜单");
assertIncludes(sideNav, "hasPermission(user, permission)", "侧栏按具体权限放行菜单");
const autoreplyMenuItem = blockFrom(sideNav, 'id: "admin-autoreply-rollout"', "},");
assertIncludes(autoreplyMenuItem, "PERMISSIONS.adminAutoreply", "自动回复灰度菜单项绑定 adminAutoreply");
assertNotIncludes(autoreplyMenuItem, "PERMISSIONS.adminAiReplyRecords", "AI 回复记录权限不能替代自动回复灰度权限");
assertNotIncludes(autoreplyMenuItem, "PERMISSIONS.adminReturnVisitPrompts", "回访提示词权限不能替代自动回复灰度权限");
assertNotIncludes(sideNav, '"admin-accounts"', "不展示 NewCarProject 归属的管理员账号管理入口");
assertNotIncludes(sideNav, '"forbidden"', "不展示 NewCarProject 归属的违禁词管理入口");

assertIncludes(newcarRedirect, '"/admin/autoreply-rollout"', "redirect allowlist 包含自动回复灰度路径");
assertIncludes(newcarRedirect, "isAllowedRedirectPath", "redirect 使用安全 allowlist");
assertIncludes(newcarRedirect, 'url.origin !== window.location.origin', "redirect 拒绝外部域名");
assertIncludes(newcarRedirect, 'url.pathname === "/login"', "redirect 拒绝本地 mock 登录页");
assertIncludes(newcarRedirect, "NEWCAR_LOGIN_URL", "退出登录使用 NewCar 登录地址");
assertIncludes(app, "clearExternalToken()", "退出登录清理 external_token");
assertIncludes(app, "clearNewCarRedirectState()", "退出登录清理 NewCar redirect 状态");
assertIncludes(app, "redirectToNewCarLogin({ message: \"正在退出登录", "退出登录跳 NewCar 登录页");
assertIncludes(authToken, 'EXTERNAL_TOKEN_KEY = "external_token"', "登录态使用 sessionStorage.external_token");
assertNotIncludes(authToken, "localStorage", "登录态不落 localStorage");

assertIncludes(apiClient, "Authorization = `Bearer ${token}`", "9000 API 使用 Bearer token");
assertIncludes(authApi, "/api/external-auth/exchange-code", "前端通过 NewCar code 换 token");
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
