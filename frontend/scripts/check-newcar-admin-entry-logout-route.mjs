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
const capabilities = read("src/features/capabilities.ts");
const sideNav = read("src/components/SideNav.tsx");
const newcarRedirect = read("src/newcarRedirect.ts");
const envExample = read(".env.example");
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
assertIncludes(app, "PERMISSIONS.adminAutoreply", "默认跳转优先识别自动回复灰度权限");
assertIncludes(app, '"/admin/autoreply-rollout"', "默认跳转支持自动回复灰度页面");
assertIncludes(app, "暂无可访问管理员功能", "管理员无本地可访问功能时显示明确提示");
assertIncludes(app, "该管理功能请在 NewCarProject 操作", "NewCar 管理功能显示归属提示");
assertIncludes(app, "redirectToNewCarLogin({ message: \"正在退出登录", "logout 跳 NewCar 登录页");
assertNotIncludes(app, 'return "/douyin-cs/workbench";', "登录后默认跳转不能固定到客服工作台");

assertIncludes(sideNav, "canViewAdminItem", "侧栏按具体权限过滤 admin 菜单");
assertIncludes(sideNav, "PERMISSIONS.adminAutoreply", "侧栏自动回复灰度使用专属权限");
assertIncludes(capabilities, "auto_wechat:admin:autoreply", "权限常量保留 NewCar 自动回复灰度权限码");
assertNotIncludes(sideNav, 'user.role === "super_admin")', "侧栏自动回复灰度不能只认 super_admin");
assertNotIncludes(sideNav, '"admin-accounts"', "不展示 auto_wechat 本地管理员账号管理入口");

assertIncludes(newcarRedirect, '"/admin/autoreply-rollout"', "redirect allowlist 包含自动回复灰度");
assertIncludes(newcarRedirect, "isAllowedRedirectPath", "redirect 使用安全 allowlist");
assertIncludes(newcarRedirect, 'url.origin !== window.location.origin', "redirect 拒绝外部 URL");
assertIncludes(newcarRedirect, 'url.pathname === "/login"', "redirect 拒绝本地 mock 登录页");
assertIncludes(newcarRedirect, "NEWCAR_LOGIN_URL", "logout 和重登录使用 NewCar 登录 URL");

assertIncludes(envExample, "VITE_NEWCAR_LOGIN_URL=http://192.168.110.19:5174/login", "env 示例记录 NewCar 登录页");
assertIncludes(adminCheck, "auto_wechat:admin:autoreply", "admin 静态检查覆盖自动回复灰度权限码");
assertIncludes(adminCheck, "hasAdminPermission", "admin 静态检查覆盖统一管理员权限工具");

for (const forbidden of ["force_send", "bypass", "ignore_gate", "set_final_auto_send"]) {
  assertNotIncludes(app, forbidden, `App 不包含危险字段 ${forbidden}`);
  assertNotIncludes(sideNav, forbidden, `SideNav 不包含危险字段 ${forbidden}`);
}

console.log("NewCar admin entry/logout route check passed.");
