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
const tokenStore = read("src/authToken.ts");
const newcarRedirect = read("src/newcarRedirect.ts");
const envExample = read(".env.example");

assertIncludes(authApi, "VITE_NEWCAR_AUTH_BASE_URL", "auth api reads NewCar base url");
assertIncludes(authApi, "/api/external-auth/exchange-code", "auth api calls upstream exchange-code");
assertIncludes(authApi, 'method: "POST"', "auth api posts exchange-code");
assertIncludes(authApi, 'platform: "auto_wechat"', "auth api sends platform");
assertIncludes(authApi, "navigator.userAgent.slice(0, 80)", "auth api sends bounded device_name");
assertNotIncludes(authApi, '"/auth/callback"', "auth api no longer calls 9000 callback");
assertIncludes(authApi, "EXTERNAL_MERCHANT_NOT_BOUND", "auth api maps unbound external account error");
assertIncludes(authApi, "账号未绑定商户，请联系管理员。", "auth api exposes unbound merchant message");

assertIncludes(app, 'source === "new_car_project"', "app only consumes NewCar redirect code");
assertIncludes(app, "assertCanEnterSystem", "app enforces auto_wechat:use");
assertIncludes(app, "await fetchCurrentAuthUser()", "app asks 9000 /auth/me after token is saved");
assertIncludes(app, "cleanCodeFromUrl()", "app clears one-time code from URL");
assertIncludes(app, "new URL(window.location.href)", "app reads NewCar code from the current browser URL");
assertIncludes(app, "`${url.pathname}${url.search}${url.hash}`", "app preserves current route when clearing one-time code");
assertIncludes(app, "externalMerchantNotBound", "app keeps unbound external account out of business routes");
assertIncludes(app, "redirectToNewCarLogin", "app redirects missing/expired external auth to NewCar login");
assertIncludes(app, "restoreSavedRedirectPathAfterLogin", "app restores saved path after code login");

assertIncludes(client, "getExternalToken()", "9000 api client reads token store");
assertIncludes(client, "Authorization = `Bearer ${token}`", "9000 api client injects bearer token");
assertIncludes(client, "redirectToNewCarLogin", "9000 api client redirects expired token to NewCar login");
assertIncludes(tokenStore, "sessionStorage", "token store uses sessionStorage");
assertIncludes(tokenStore, 'EXTERNAL_TOKEN_KEY = "external_token"', "token store uses the runtime sessionStorage key");
assertNotIncludes(tokenStore, "external_auth_token", "token store does not use the historical mistaken key");
assertIncludes(newcarRedirect, "NEWCAR_LOGIN_URL", "NewCar redirect helper uses configured login url");
assertIncludes(newcarRedirect, "NEWCAR_REDIRECT_PATH_KEY", "NewCar redirect helper stores current path");
assertIncludes(newcarRedirect, "NEWCAR_REDIRECTING_TTL_MS", "NewCar redirect helper expires stale redirect guard");
assertIncludes(newcarRedirect, "Date.now().toString()", "NewCar redirect helper stores redirect guard timestamp");
assertIncludes(newcarRedirect, "Number(redirectingAt)", "NewCar redirect helper parses previous redirect guard timestamp");
assertIncludes(newcarRedirect, "redirectingAgeMs < NEWCAR_REDIRECTING_TTL_MS", "NewCar redirect helper only blocks fresh duplicate redirects");
assertIncludes(newcarRedirect, "window.location.replace(loginUrl.toString())", "NewCar redirect helper uses replace to avoid history loop");
assertIncludes(newcarRedirect, "newcar_redirecting", "NewCar redirect helper prevents repeated redirects");
assertIncludes(newcarRedirect, "code", "NewCar redirect helper does not redirect while handling one-time code");
assertIncludes(newcarRedirect, "source", "NewCar redirect helper checks NewCar source before redirecting");
assertNotIncludes(newcarRedirect, 'sessionStorage.getItem(NEWCAR_REDIRECTING_KEY) === "1"', "NewCar redirect helper no longer treats old guard value as permanent");
assertIncludes(envExample, "VITE_NEWCAR_AUTH_BASE_URL=http://192.168.110.19:8790", "frontend env example documents NewCar base url");
assertIncludes(envExample, "VITE_NEWCAR_LOGIN_URL=http://192.168.110.19:5174/login", "frontend env example documents NewCar login url");

console.log("NewCar direct code exchange check passed.");
