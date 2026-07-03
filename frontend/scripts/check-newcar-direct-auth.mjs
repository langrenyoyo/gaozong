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

const authApi = read("src/api/auth.ts");
const app = read("src/App.tsx");
const client = read("src/api/client.ts");
const wechatTasks = read("src/api/wechatTasks.ts");
const tokenStore = read("src/authToken.ts");
const newcarRedirect = read("src/newcarRedirect.ts");
const envExample = read(".env.example");
const wechatAgentPage = read("src/features/wechat-assistant/pages/WechatAgent.tsx");
const wechatTaskPanel = read("src/features/wechat-assistant/components/WechatTaskPanel.tsx");

assertIncludes(authApi, "VITE_NEWCAR_AUTH_BASE_URL", "auth api reads NewCar base url");
assertIncludes(authApi, "/api/external-auth/exchange-code", "auth api calls upstream exchange-code");
assertIncludes(authApi, 'method: "POST"', "auth api posts exchange-code");
assertIncludes(authApi, 'platform: "auto_wechat"', "auth api sends platform");
assertIncludes(authApi, "navigator.userAgent.slice(0, 80)", "auth api sends bounded device_name");
assertNotIncludes(authApi, '"/auth/callback"', "auth api no longer calls 9000 callback");
assertIncludes(authApi, "EXTERNAL_MERCHANT_NOT_BOUND", "auth api maps unbound external account error");
assertIncludes(authApi, "PERMISSION_DENIED", "auth api maps permission denied error");

assertIncludes(app, 'source === "new_car_project"', "app only consumes NewCar redirect code");
assertIncludes(app, "assertCanEnterSystem", "app enforces auto_wechat:use");
assertIncludes(app, "await fetchCurrentAuthUser()", "app asks 9000 /auth/me after token is saved");
assertIncludes(app, "cleanCodeFromUrl()", "app clears one-time code from URL");
assertIncludes(app, "new URL(window.location.href)", "app reads NewCar code from the current browser URL");
assertIncludes(app, "`${url.pathname}${url.search}${url.hash}`", "app preserves current route when clearing one-time code");
assertIncludes(app, "externalMerchantNotBound", "app keeps unbound external account out of business routes");
assertIncludes(app, "permissionDenied", "app keeps permission denied users out of relogin loops");
assertIncludes(app, "exchangeCodeFailed", "app handles invalid one-time code as a readable error");
assertIncludes(app, "redirectToNewCarLogin", "app redirects missing/expired external auth to NewCar login");
assertIncludes(app, "restoreSavedRedirectPathAfterLogin", "app restores saved path after code login");
assertIncludes(app, "AuthErrorScreen", "app renders user-facing auth error states");
assertIncludes(app, "handleRelogin", "app relogin action clears local auth state before NewCar redirect");
assertIncludes(app, "handleBackToWorkbench", "app permission action returns to the default workbench");
assertIncludes(app, "loginRedirectNotice", "app renders a user-facing NewCar redirect notice");

assertIncludes(client, "getExternalToken()", "9000 api client reads token store");
assertIncludes(client, "Authorization = `Bearer ${token}`", "9000 api client injects bearer token");
assertIncludes(client, "redirectToNewCarLogin", "9000 api client redirects expired token to NewCar login");
assertIncludes(client, "getApiErrorCode", "9000 api client classifies api error codes before redirecting");
assertIncludes(client, "isLocalAgentAuthErrorCode", "9000 api client recognizes Local Agent machine auth errors");
assertIncludes(client, 'code.startsWith("LOCAL_AGENT_")', "9000 api client treats all LOCAL_AGENT_* errors as machine auth errors");
assertIncludes(client, "LOCAL_AGENT_TOKEN_MISSING", "9000 api client explicitly covers missing Local Agent token");
assertIncludes(client, "LOCAL_AGENT_TOKEN_INVALID", "9000 api client explicitly covers invalid Local Agent token");
assertIncludes(client, "LOCAL_AGENT_TOKEN_REQUIRED", "9000 api client explicitly covers required Local Agent token");
assertIncludes(client, "LOCAL_AGENT_TOKEN_REVOKED", "9000 api client explicitly covers revoked Local Agent token");
assertIncludes(client, "PERMISSION_DENIED", "9000 api client does not redirect permission denied users to NewCar login");
assertIncludes(client, "EXTERNAL_MERCHANT_NOT_BOUND", "9000 api client does not redirect unbound merchants to NewCar login");
assertIncludes(client, "isNewCarLoginAuthErrorCode", "9000 api client explicitly recognizes NewCar login auth errors");
assertIncludes(client, "TOKEN_MISSING", "9000 api client keeps missing token redirect behavior");
assertIncludes(client, "TOKEN_EXPIRED", "9000 api client keeps expired token redirect behavior");
assertIncludes(client, "TOKEN_INVALID", "9000 api client keeps invalid token redirect behavior");
assertIncludes(client, "shouldRedirectToNewCarLogin", "9000 api client scopes 401 redirects to NewCar auth errors");
assertIncludes(client, "isNewCarLoginAuthErrorCode(code)", "9000 api client redirects known NewCar login auth errors");
assertIncludes(client, "!isLocalAgentAuthErrorCode(code)", "9000 api client excludes Local Agent auth errors from NewCar redirects");
assertIncludes(client, "!isNonLoginAuthErrorCode(code)", "9000 api client excludes permission and binding errors from NewCar redirects");

assertIncludes(tokenStore, "sessionStorage", "token store uses sessionStorage");
assertIncludes(tokenStore, 'EXTERNAL_TOKEN_KEY = "external_token"', "token store uses the runtime sessionStorage key");
assertNotIncludes(tokenStore, "external_auth_token", "token store does not use the historical mistaken key");

assertIncludes(newcarRedirect, "NEWCAR_LOGIN_URL", "NewCar redirect helper uses configured login url");
assertIncludes(newcarRedirect, "NEWCAR_REDIRECT_PATH_KEY", "NewCar redirect helper stores current path");
assertIncludes(newcarRedirect, 'DEFAULT_POST_LOGIN_PATH = "/douyin-cs/workbench"', "NewCar redirect helper has a stable default post-login path");
assertIncludes(newcarRedirect, 'NEWCAR_REDIRECT_PATH_SAVED_AT_KEY = "newcar_redirect_path_saved_at"', "NewCar redirect helper stores redirect path saved timestamp");
assertIncludes(newcarRedirect, "NEWCAR_REDIRECT_PATH_TTL_MS", "NewCar redirect path has a TTL");
assertIncludes(newcarRedirect, "ALLOWED_REDIRECT_PATH_PREFIXES", "NewCar redirect helper uses a path allowlist");
assertIncludes(newcarRedirect, "isAllowedRedirectPath", "NewCar redirect helper validates saved redirect path");
assertIncludes(newcarRedirect, "savedAgeMs > NEWCAR_REDIRECT_PATH_TTL_MS", "NewCar redirect helper rejects expired redirect paths");
assertIncludes(newcarRedirect, 'url.pathname === "/login"', "NewCar redirect helper rejects local login path");
assertIncludes(newcarRedirect, 'url.pathname === "/auth/callback"', "NewCar redirect helper rejects legacy callback path");
assertIncludes(newcarRedirect, 'url.pathname.startsWith(`${prefix}/`)', "NewCar redirect helper allows known business subpaths");
assertIncludes(newcarRedirect, '"/douyin-cs"', "NewCar redirect allowlist includes douyin cs");
assertIncludes(newcarRedirect, '"/leads"', "NewCar redirect allowlist includes leads");
assertIncludes(newcarRedirect, '"/compute"', "NewCar redirect allowlist includes compute");
assertIncludes(newcarRedirect, '"/agents"', "NewCar redirect allowlist includes agents");
assertIncludes(newcarRedirect, '"/wechat-assistant"', "NewCar redirect allowlist includes wechat assistant without changing its permission mapping");
assertIncludes(newcarRedirect, "restoreSavedRedirectPathAfterLogin", "NewCar redirect helper restores saved path after login");
assertIncludes(newcarRedirect, "return DEFAULT_POST_LOGIN_PATH", "NewCar redirect helper falls back to the default workbench");
assertIncludes(newcarRedirect, "NEWCAR_REDIRECTING_TTL_MS", "NewCar redirect helper expires stale redirect guard");
assertIncludes(newcarRedirect, "Date.now().toString()", "NewCar redirect helper stores redirect guard timestamp");
assertIncludes(newcarRedirect, "Number(redirectingAt)", "NewCar redirect helper parses previous redirect guard timestamp");
assertIncludes(newcarRedirect, "redirectingAgeMs < NEWCAR_REDIRECTING_TTL_MS", "NewCar redirect helper only blocks fresh duplicate redirects");
assertIncludes(newcarRedirect, "window.location.replace(loginUrl.toString())", "NewCar redirect helper uses replace to avoid history loop");
assertIncludes(newcarRedirect, "newcar_redirecting", "NewCar redirect helper prevents repeated redirects");
assertIncludes(newcarRedirect, "code", "NewCar redirect helper does not redirect while handling one-time code");
assertIncludes(newcarRedirect, "source", "NewCar redirect helper checks NewCar source before redirecting");
assertNotIncludes(newcarRedirect, 'sessionStorage.getItem(NEWCAR_REDIRECTING_KEY) === "1"', "NewCar redirect helper no longer treats old guard value as permanent");

assertIncludes(wechatTasks, "fetchBrowserPendingWechatTasks", "wechat task api exposes a browser pending list helper");
assertIncludes(wechatTasks, 'status: "pending"', "browser pending helper queries GET /wechat-tasks with status=pending");
assertIncludes(wechatTasks, 'apiClient.get("/wechat-tasks/pending"', "Local Agent pending poll endpoint remains available");
assertIncludes(wechatAgentPage, "fetchBrowserPendingWechatTasks({ limit: 20 })", "wechat assistant page uses browser pending task helper");
assertIncludes(wechatTaskPanel, "fetchBrowserPendingWechatTasks({ limit: 50 })", "wechat task panel uses browser pending task helper");
assertIncludes(wechatTaskPanel, 'fetchBrowserPendingWechatTasks({ task_type: "detect_reply", limit: 10 })', "detect reply list uses browser pending task helper");
assertNotIncludes(wechatAgentPage, "fetchPendingWechatTasks", "wechat assistant page no longer calls the Local Agent pending poll helper");
assertNotIncludes(wechatTaskPanel, "fetchPendingWechatTasks", "wechat task panel no longer calls the Local Agent pending poll helper");

assertIncludes(envExample, "VITE_NEWCAR_AUTH_BASE_URL=http://192.168.110.19:8790", "frontend env example documents NewCar base url");
assertIncludes(envExample, "VITE_NEWCAR_LOGIN_URL=http://192.168.110.19:5174/login", "frontend env example documents NewCar login url");

console.log("NewCar direct code exchange check passed.");
