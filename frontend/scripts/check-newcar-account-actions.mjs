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
const sideNav = read("src/components/SideNav.tsx");
const changePasswordDialog = read("src/components/ChangePasswordDialog.tsx");

// ---------------------------------------------------------------------------
// 接口路径与凭据合同
// ---------------------------------------------------------------------------

// 改密只调用 9000 门面 /auth/password，不直连 NewCar，不接受用户 ID 入参。
assertIncludes(authApi, "`${baseUrl}/auth/password`", "改密调用 9000 /auth/password 门面");
// 改密请求体精确为两个密码字段（JSON.stringify 内只含 old_password/new_password，无 user_id/merchant_id）。
assertIncludes(authApi, "body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })", "改密请求体只含两个密码字段");
{
  const idx = authApi.indexOf("body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })");
  const bodyLine = authApi.slice(idx, idx + 80);
  assertNotIncludes(bodyLine, "user_id", "改密请求体不含 user_id");
  assertNotIncludes(bodyLine, "merchant_id", "改密请求体不含 merchant_id");
}

// R1：改密 API 返回结构化四态 outcome，不靠抛文案异常判定类别。
assertIncludes(authApi, "ChangeExternalPasswordOutcome", "改密导出结构化 outcome 类型");
assertIncludes(authApi, '{ status: "success"', "改密 outcome 含 success 态");
assertIncludes(authApi, '{ status: "business"', "改密 outcome 含 business 态（400/403，保留登录态）");
assertIncludes(authApi, '{ status: "relogin"', "改密 outcome 含 relogin 态（401）");
assertIncludes(authApi, '{ status: "unknown"', "改密 outcome 含 unknown 态（超时/网络/5xx/异常/非白名单）");
// R1-4：成功严格白名单 ok===true && relogin_required===true && revoked_session_scope==="all"。
assertIncludes(authApi, "data.ok === true && data.relogin_required === true", "改密成功严格匹配 ok+relogin_required");
assertIncludes(authApi, 'data.revoked_session_scope === "all"', "改密成功严格匹配 revoked_session_scope=all");

// 管理员当前浏览器退出直调 NewCar 且携带 credentials: include。
assertIncludes(authApi, "/api/external-auth/logout-current-browser", "管理员退出直调 NewCar logout-current-browser");
assertIncludes(authApi, 'credentials: "include"', "管理员退出携带 credentials include");
assertIncludes(authApi, "Authorization: `Bearer ${token}`", "管理员退出携带 Bearer token");

// 普通退出仍只调 9000 /auth/logout，不改为上游当前浏览器退出。
assertIncludes(authApi, "`${baseUrl}/auth/logout`", "普通退出仍调用 9000 /auth/logout");
{
  // 在 logoutAutoWechat 函数体内确认不直调 NewCar 当前浏览器退出。
  const fnStart = authApi.indexOf("export async function logoutAutoWechat");
  const fnEnd = authApi.indexOf("export async", fnStart + 10);
  const logoutFn = authApi.slice(fnStart, fnEnd > fnStart ? fnEnd : undefined);
  assertNotIncludes(logoutFn, "/api/external-auth/logout-current-browser", "普通退出不直调 NewCar 当前浏览器退出");
}

// 切换仍为 NewCar switch-to-internal。
assertIncludes(authApi, "/api/external-auth/switch-to-internal", "切换仍由浏览器直调 NewCar switch-to-internal");

// 所有外部 redirect 继续 HTTP(S) 校验与十秒超时。
assertIncludes(authApi, "AUTH_REQUEST_TIMEOUT_MS = 10_000", "外部请求使用十秒超时常量");
assertIncludes(authApi, "AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS)", "改密请求携带十秒中止信号");
assertIncludes(authApi, 'redirectUrl.protocol !== "http:" && redirectUrl.protocol !== "https:"', "管理员退出 redirect_url 只允许 HTTP(S)");

// ---------------------------------------------------------------------------
// 侧栏角色化动作
// ---------------------------------------------------------------------------

// 管理员同时有切换和独立退出，普通商户有改密和退出；动作按身份分支。
assertIncludes(sideNav, "onSwitchToNewCar", "侧栏转发管理员切换动作");
assertIncludes(sideNav, "onAdminLogout", "侧栏转发管理员退出动作");
assertIncludes(sideNav, "onChangePassword", "侧栏转发商户改密动作");
assertIncludes(sideNav, "onLogout", "侧栏保留普通商户退出动作");
assertIncludes(sideNav, "切换到 NewCar", "管理员侧栏显示切换到 NewCar 文案");
assertIncludes(sideNav, "修改密码", "普通商户侧栏显示修改密码文案");
assertIncludes(sideNav, "KeyRoundIcon", "改密动作使用钥匙图标");

// 管理员/普通商户动作分支互斥：管理员分支含切换+退出，普通分支含改密+退出。
assertIncludes(sideNav, "isAdminUser ? (", "侧栏按管理员身份分支渲染底部动作");

// ---------------------------------------------------------------------------
// 账号操作区视觉结构对齐 NewCar
// ---------------------------------------------------------------------------

// 收起导航按钮使用 NewCar 深色填充样式（#22304b 填充 + 描边）。
assertIncludes(sideNav, "bg-[#22304b]", "收起导航按钮使用 NewCar 深色填充样式");

// 管理员橙色切换卡片：对齐 NewCar external-switch-card，含主标题与 NewCar 管理入口副标题。
assertIncludes(sideNav, "bg-[#fff7ed]", "管理员切换卡片使用 NewCar 橙色填充");
assertIncludes(sideNav, "border-[#f59e0b]", "管理员切换卡片使用 NewCar 橙色描边");
assertIncludes(sideNav, "切换到 NewCar", "管理员橙色卡片主标题为切换到 NewCar");
assertIncludes(sideNav, "NewCar 管理入口", "管理员橙色卡片含 NewCar 管理入口副标题");

// 账号卡片：复用 NewCar avatar.svg，展示头像 + 账号 + 角色。
assertIncludes(sideNav, 'from "../assets/avatar.svg"', "账号卡片复用 NewCar avatar.svg 资源");
assertIncludes(sideNav, "accountMenuOpen", "账号卡片使用 popover 状态控制下拉菜单");
assertIncludes(sideNav, "`${user.account} · ${user.roleLabel}`", "账号卡片 title 含账号与角色");

// 账号菜单按身份分支：管理员只显示退出登录，商户显示修改密码 + 退出登录。
{
  // 管理员分支在前、商户分支（含 onChangePassword）在后；切片到 onChangePassword 即覆盖整个管理员分支。
  const branchStart = sideNav.indexOf("isAdminUser ? (");
  const merchantStart = sideNav.indexOf("onChangePassword", branchStart);
  const adminBranch = sideNav.slice(branchStart, merchantStart > branchStart ? merchantStart : undefined);
  assertNotIncludes(adminBranch, "修改密码", "管理员账号菜单只显示退出登录，不含修改密码");
  assertIncludes(adminBranch, "onAdminLogout", "管理员账号菜单绑定管理员退出回调");
}
assertIncludes(sideNav, "onChangePassword", "商户账号菜单保留修改密码回调");
assertIncludes(sideNav, "KeyRoundIcon", "商户账号菜单修改密码使用钥匙图标");

// ---------------------------------------------------------------------------
// App 状态机：401 抑制与本地状态清理
// ---------------------------------------------------------------------------

// 改密开始抑制并发 401，业务失败恢复跳转。
assertIncludes(app, "setNewCarAuthRedirectSuppressed(true)", "改密/退出开始时抑制并发 401 跳转");
assertIncludes(app, "setNewCarAuthRedirectSuppressed(false)", "业务失败或重新登录恢复 401 跳转");

// R2：改密结果用四态枚举 success/relogin/unknown 代替布尔，按状态分流页面文案。
assertIncludes(app, "PasswordResultView = \"success\" | \"relogin\" | \"unknown\"", "改密结果状态用四态枚举类型");
assertIncludes(app, "passwordResultView", "改密结果状态变量");
assertIncludes(app, "setPasswordResultView(\"success\")", "改密成功进入 success 状态页");
assertIncludes(app, "setPasswordResultView(\"relogin\")", "改密 401 进入 relogin 状态页");
assertIncludes(app, "setPasswordResultView(\"unknown\")", "改密未知进入 unknown 状态页");
// 只有 success 才能展示“密码已修改”文案；relogin 只说登录已失效；unknown 只说结果未知。
assertIncludes(app, "密码已修改，请重新登录", "success 状态展示“密码已修改”文案");
assertIncludes(app, "登录已失效，请重新登录", "relogin 状态展示登录失效文案");
assertIncludes(app, "密码修改结果未知，请重新登录确认", "unknown 状态展示结果未知文案");
// relogin 状态页不得声称密码已修改；unknown 状态页不得声称成功或失败。
{
  const reloginStart = app.indexOf('passwordResultView === "relogin"');
  const reloginBlock = app.slice(reloginStart, app.indexOf('passwordResultView === "unknown"'));
  assertNotIncludes(reloginBlock, "密码已修改", "relogin 状态页不得声称密码已修改");
  const unknownStart = app.indexOf('passwordResultView === "unknown"');
  const unknownBlock = app.slice(unknownStart, unknownStart + 200);
  assertNotIncludes(unknownBlock, "密码已修改", "unknown 状态页不得声称密码已修改");
}
assertIncludes(app, "handleChangePassword", "App 持有改密提交处理器");

// 管理员退出：token 只存页面内存 ref，成功后 replace 到 redirect_url，不退化为普通商户退出门面或切换动作。
assertIncludes(app, "adminLogoutTokenRef", "管理员退出 token 只保留在页面内存 ref");
assertIncludes(app, "logoutCurrentBrowserOnNewCar", "App 调用管理员当前浏览器退出");
assertIncludes(app, "window.location.replace(redirectUrl)", "管理员退出成功后 replace 到 redirect_url");
assertIncludes(app, "onAdminLogout={handleAdminLogout}", "管理员退出动作绑定 handleAdminLogout");
assertNotIncludes(app, "logoutAutoWechat(adminLogoutTokenRef", "管理员退出不退化为普通商户 logout 门面");
// R1-1：管理员退出接收显式 token 的内部函数；首次读存储，重试用内存 ref，不重新读存储。
assertIncludes(app, "const performAdminLogout = async (token: string | null)", "管理员退出内部函数接收显式 token");
assertIncludes(app, "void performAdminLogout(getExternalToken())", "管理员退出首次从存储读取 token 传入");
assertIncludes(app, "performAdminLogout(adminLogoutTokenRef.current)", "管理员退出重试直接使用内存 ref token");
// R1-6：handleRelogin 清全部 P4 状态和内存 ref。
assertIncludes(app, "setChangePasswordOpen(false)", "重新登录清理改密弹窗状态");
assertIncludes(app, "setPasswordResultView(null)", "重新登录清理改密结果状态页");
assertIncludes(app, "setAdminLoggingOut(false)", "重新登录清理管理员退出 loading");
assertIncludes(app, "setAdminLogoutError(null)", "重新登录清理管理员退出错误");
assertIncludes(app, "adminLogoutTokenRef.current = null", "重新登录清理管理员退出内存 token");

// 普通退出沿用内存 token 重试与晚到 401 抑制。
assertIncludes(app, "logoutRetryTokenRef", "普通退出失败 token 只保留在页面内存");
assertIncludes(app, "logoutAutoWechat(retryToken)", "普通退出重试继续调用 9000 /auth/logout");

// ---------------------------------------------------------------------------
// ChangePasswordDialog：不把密码写入存储/日志/URL
// ---------------------------------------------------------------------------

assertIncludes(changePasswordDialog, "type=\"password\"", "改密弹窗密码字段使用 password 类型输入");
assertNotIncludes(changePasswordDialog, "localStorage", "改密弹窗不写入 localStorage");
assertNotIncludes(changePasswordDialog, "sessionStorage", "改密弹窗不写入 sessionStorage");
assertNotIncludes(changePasswordDialog, "console.log", "改密弹窗不输出日志");
assertIncludes(changePasswordDialog, "aria-live", "改密弹窗提供可访问的 aria-live 状态");

console.log("NewCar account actions contract check passed.");
