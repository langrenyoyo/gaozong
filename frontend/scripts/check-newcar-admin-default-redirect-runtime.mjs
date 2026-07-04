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
const newcarRedirect = read("src/newcarRedirect.ts");
const packageJson = read("package.json");

assertIncludes(packageJson, '"newcar-admin-redirect:check"', "package.json 注册管理员默认跳转检查脚本");
assertIncludes(app, "resolvePostLoginPath", "App 使用统一登录后跳转解析函数");
assertIncludes(app, "consumeSavedRedirectPathAfterLogin()", "code 登录成功后先消费 redirect 候选值");
assertIncludes(app, "replaceCurrentPath(postLoginPath)", "拿到当前用户权限后再替换浏览器路径");
assertIncludes(app, "canAccessPath", "redirect 候选路径必须校验当前用户权限");
assertIncludes(app, "!hasPermission(user, PERMISSIONS.use) && !isAdminLike(user)", "admin-only 账号不要求商户 use 权限");
assertIncludes(app, 'return "/admin/autoreply-rollout"', "admin:autoreply 默认进入自动回复灰度控制台");
assertIncludes(app, "PERMISSIONS.adminAutoreply", "admin:autoreply 使用专属权限");
assertIncludes(app, "PERMISSIONS.adminAiReplyRecords", "admin:ai_reply_records 不等同于 admin:autoreply");
assertIncludes(app, "PERMISSIONS.adminReturnVisitPrompts", "admin:return_visit_prompts 不等同于 admin:autoreply");
assertIncludes(app, "hasAnyNewCarOwnedAdminPermission", "NewCar 归属 admin 权限走本地提示页");
assertIncludes(app, '"/admin/newcar-owned"', "NewCar 归属 admin 权限不落到客服工作台");
assertIncludes(app, '"/admin/no-local-feature"', "无本地功能的 admin-only 账号有明确提示页");
assertIncludes(capabilities, 'path: "/douyin-cs/workbench"', "商户客服权限仍可进入客服工作台");

assertIncludes(newcarRedirect, "consumeSavedRedirectPathAfterLogin", "redirect helper 只返回候选路径并清理缓存");
assertIncludes(newcarRedirect, "clearSavedRedirectPath()", "redirect 被消费或拒绝后会清理缓存");
assertIncludes(newcarRedirect, 'DEFAULT_POST_LOGIN_PATH = "/"', "redirect helper 默认回到根路径，由 App 按权限计算首页");
assertNotIncludes(newcarRedirect, "restoreSavedRedirectPathAfterLogin", "redirect helper 不应在无用户权限时直接改浏览器路径");
assertNotIncludes(app, "restoreSavedRedirectPathAfterLogin()", "App 不应在构造用户权限前直接恢复 redirect");
assertNotIncludes(app, 'return "/douyin-cs/workbench";', "管理员默认跳转不能写死客服工作台");
assertNotIncludes(newcarRedirect, 'DEFAULT_POST_LOGIN_PATH = "/douyin-cs/workbench"', "redirect 默认 fallback 不能写死客服工作台");
assertNotMatches(app, /restoreSavedRedirectPathAfterLogin\(\);\s*const nextUser/s, "不能在 nextUser 构造前恢复 redirect");

for (const forbidden of ["force_send", "bypass", "ignore_gate", "set_final_auto_send"]) {
  assertNotIncludes(app, forbidden, `App 不包含危险字段 ${forbidden}`);
  assertNotIncludes(newcarRedirect, forbidden, `redirect helper 不包含危险字段 ${forbidden}`);
}

console.log("NewCar admin default redirect runtime check passed.");
