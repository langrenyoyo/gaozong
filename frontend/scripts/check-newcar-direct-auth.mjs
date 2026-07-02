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

assertIncludes(client, "getExternalToken()", "9000 api client reads token store");
assertIncludes(client, "Authorization = `Bearer ${token}`", "9000 api client injects bearer token");
assertIncludes(tokenStore, "sessionStorage", "token store uses sessionStorage");
assertIncludes(envExample, "VITE_NEWCAR_AUTH_BASE_URL=http://192.168.110.19:8790", "frontend env example documents NewCar base url");

console.log("NewCar direct code exchange check passed.");
