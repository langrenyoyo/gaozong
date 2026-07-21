import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

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

function assertOrder(content, first, second, label) {
  const firstIndex = content.indexOf(first);
  const secondIndex = content.indexOf(second);
  if (firstIndex < 0 || secondIndex < 0 || firstIndex >= secondIndex) {
    throw new Error(`${label}: expected ${first} before ${second}`);
  }
}

async function assertRejectedWithMessage(action, expected, label) {
  let error;
  try {
    await action();
  } catch (caught) {
    error = caught;
  }
  assert.ok(error instanceof Error, `${label}: expected rejection`);
  assert.equal(error.message, expected, `${label}: unexpected public error`);
}

function memoryStorage(initialValues = {}) {
  const values = new Map(Object.entries(initialValues));
  return {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key) {
      return values.get(key) ?? null;
    },
    key(index) {
      return [...values.keys()][index] ?? null;
    },
    removeItem(key) {
      values.delete(key);
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
  };
}

function setGlobal(name, value, snapshots) {
  snapshots.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
}

function restoreGlobals(snapshots) {
  for (const [name, descriptor] of snapshots) {
    if (descriptor) {
      Object.defineProperty(globalThis, name, descriptor);
    } else {
      delete globalThis[name];
    }
  }
}

async function runAuthBehaviorChecks() {
  const output = await build({
    entryPoints: [path.join(root, "src/api/auth.ts")],
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    write: false,
    define: {
      "import.meta.env.DEV": "false",
      "import.meta.env.VITE_API_BASE_URL": JSON.stringify("https://auto.example.test///"),
      "import.meta.env.VITE_AUTO_WECHAT_API_BASE_URL": "undefined",
      "import.meta.env.VITE_NEWCAR_AUTH_BASE_URL": JSON.stringify("https://newcar.example.test///"),
      "import.meta.env.VITE_NEWCAR_LOGIN_URL": JSON.stringify("https://newcar.example.test/login"),
    },
  });
  const tempFile = path.join(os.tmpdir(), `auto-wechat-auth-contract-${process.pid}-${Date.now()}.mjs`);
  const snapshots = new Map();
  const calls = [];

  try {
    fs.writeFileSync(tempFile, output.outputFiles[0].text, "utf8");
    setGlobal("sessionStorage", memoryStorage({ external_token: "switch-token" }), snapshots);
    setGlobal(
      "window",
      {
        addEventListener() {},
        dispatchEvent() { return true; },
        history: { replaceState() {} },
        location: {
          hash: "",
          href: "https://auto.example.test/leads",
          origin: "https://auto.example.test",
          pathname: "/leads",
          replace() {},
          search: "",
        },
        removeEventListener() {},
        setTimeout,
      },
      snapshots,
    );

    let fetchHandler;
    setGlobal(
      "fetch",
      async (url, options = {}) => {
        calls.push({ url: String(url), options });
        return await fetchHandler(url, options);
      },
      snapshots,
    );

    const authModule = await import(`${pathToFileURL(tempFile).href}?v=${Date.now()}`);
    const switchError = "切换到内部系统失败，请稍后重试。";
    const logoutError = "退出失败，请重试";
    const jsonResponse = (body, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

    fetchHandler = async () => jsonResponse({ redirect_url: "https://internal.example.test/home?source=auto_wechat" });
    calls.length = 0;
    assert.equal(
      await authModule.switchToInternalSystem(),
      "https://internal.example.test/home?source=auto_wechat",
      "switch returns validated redirect_url",
    );
    assert.equal(calls.length, 1, "switch makes one request");
    assert.equal(calls[0].url, "https://newcar.example.test/api/external-auth/switch-to-internal");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.headers.Authorization, "Bearer switch-token");
    assert.equal(calls[0].options.body, "{}");
    assert.ok(calls[0].options.signal instanceof AbortSignal, "switch request carries AbortSignal");

    fetchHandler = async () => jsonResponse({ detail: "RAW_401_SECRET" }, 401);
    await assertRejectedWithMessage(
      authModule.switchToInternalSystem,
      "登录已过期，无法切换到内部系统。",
      "switch 401",
    );
    fetchHandler = async () => jsonResponse({ detail: "RAW_403_SECRET" }, 403);
    await assertRejectedWithMessage(
      authModule.switchToInternalSystem,
      "当前账号暂无切换到内部系统的权限。",
      "switch 403",
    );
    fetchHandler = async () => new Response("RAW_INVALID_JSON_SECRET", { status: 200 });
    await assertRejectedWithMessage(authModule.switchToInternalSystem, switchError, "switch invalid json");
    fetchHandler = async () => jsonResponse({ detail: "RAW_MISSING_REDIRECT_SECRET" });
    await assertRejectedWithMessage(authModule.switchToInternalSystem, switchError, "switch missing redirect");
    fetchHandler = async () => jsonResponse({ redirect_url: "javascript:alert('RAW_URL_SECRET')" });
    await assertRejectedWithMessage(authModule.switchToInternalSystem, switchError, "switch unsafe redirect");
    fetchHandler = async () => { throw new Error("RAW_NETWORK_SECRET"); };
    await assertRejectedWithMessage(authModule.switchToInternalSystem, switchError, "switch network error");
    fetchHandler = async () => { throw new DOMException("RAW_ABORT_SECRET", "AbortError"); };
    await assertRejectedWithMessage(authModule.switchToInternalSystem, switchError, "switch abort");

    fetchHandler = async () => jsonResponse({ ok: true });
    calls.length = 0;
    await authModule.logoutAutoWechat("logout-token");
    assert.equal(calls.length, 1, "logout makes one request");
    assert.equal(calls[0].url, "https://auto.example.test/auth/logout");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.headers.Authorization, "Bearer logout-token");
    assert.equal(calls[0].options.body, "{}");
    assert.ok(calls[0].options.signal instanceof AbortSignal, "logout request carries AbortSignal");

    fetchHandler = async () => jsonResponse({ detail: "RAW_503_SECRET" }, 503);
    await assertRejectedWithMessage(() => authModule.logoutAutoWechat("logout-token"), logoutError, "logout 503");
    fetchHandler = async () => { throw new Error("RAW_LOGOUT_NETWORK_SECRET"); };
    await assertRejectedWithMessage(
      () => authModule.logoutAutoWechat("logout-token"),
      logoutError,
      "logout network error",
    );
    fetchHandler = async () => { throw new DOMException("RAW_LOGOUT_ABORT_SECRET", "AbortError"); };
    await assertRejectedWithMessage(() => authModule.logoutAutoWechat("logout-token"), logoutError, "logout abort");
  } finally {
    restoreGlobals(snapshots);
    fs.rmSync(tempFile, { force: true });
  }
}

async function runClientRedirectSuppressionChecks() {
  const output = await build({
    entryPoints: [path.join(root, "src/api/client.ts")],
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    write: false,
    define: {
      "import.meta.env.DEV": "false",
      "import.meta.env.VITE_API_BASE_URL": JSON.stringify("https://auto.example.test"),
      "import.meta.env.VITE_AUTO_WECHAT_API_BASE_URL": "undefined",
      "import.meta.env.VITE_NEWCAR_LOGIN_URL": JSON.stringify("https://newcar.example.test/login"),
    },
  });
  const tempFile = path.join(os.tmpdir(), `auto-wechat-client-contract-${process.pid}-${Date.now()}.mjs`);
  const snapshots = new Map();
  const replaceCalls = [];
  let clientModule;

  try {
    fs.writeFileSync(tempFile, output.outputFiles[0].text, "utf8");
    setGlobal("sessionStorage", memoryStorage({ external_token: "race-token" }), snapshots);
    setGlobal(
      "CustomEvent",
      class ContractCustomEvent extends Event {
        constructor(type, init = {}) {
          super(type);
          this.detail = init.detail;
        }
      },
      snapshots,
    );
    setGlobal(
      "window",
      {
        dispatchEvent() { return true; },
        location: {
          hash: "#latest",
          href: "https://auto.example.test/leads?tab=all#latest",
          origin: "https://auto.example.test",
          pathname: "/leads",
          replace(url) { replaceCalls.push(String(url)); },
          search: "?tab=all",
        },
        setTimeout(callback) {
          callback();
          return 1;
        },
      },
      snapshots,
    );

    clientModule = await import(`${pathToFileURL(tempFile).href}?v=${Date.now()}`);
    clientModule.default.defaults.adapter = async () => {
      const error = new Error("RAW_LATE_401_SECRET");
      error.response = { status: 401, data: { detail: { code: "TOKEN_EXPIRED" } } };
      throw error;
    };
    const triggerLate401 = () => assert.rejects(clientModule.default.get("/late-request"));

    await triggerLate401();
    assert.deepEqual(replaceCalls, ["https://newcar.example.test/login"], "normal 401 still redirects to NewCar");
    assert.equal(sessionStorage.getItem("newcar_redirect_path"), "/leads?tab=all#latest");

    replaceCalls.length = 0;
    sessionStorage.clear();
    sessionStorage.setItem("external_token", "race-token");
    clientModule.setNewCarAuthRedirectSuppressed?.(true);
    await triggerLate401();
    assert.equal(replaceCalls.length, 0, "late 401 during logout must not replace the current URL");
    assert.equal(sessionStorage.getItem("newcar_redirect_path"), null, "suppressed 401 must not save a return path");
    assert.equal(sessionStorage.getItem("newcar_redirecting"), null, "suppressed 401 must not mark a redirect");
    assert.equal(sessionStorage.getItem("external_token"), "race-token", "suppressed 401 leaves logout cleanup to App");

    clientModule.setNewCarAuthRedirectSuppressed?.(false);
    await triggerLate401();
    assert.deepEqual(replaceCalls, ["https://newcar.example.test/login"], "re-enabled 401 redirects to NewCar");
  } finally {
    clientModule?.setNewCarAuthRedirectSuppressed?.(false);
    restoreGlobals(snapshots);
    fs.rmSync(tempFile, { force: true });
  }
}

const authApi = read("src/api/auth.ts");
const app = read("src/App.tsx");
const capabilities = read("src/features/capabilities.ts");
const client = read("src/api/client.ts");
const sideNav = read("src/components/SideNav.tsx");
const indexPage = read("src/pages/Index.tsx");
const wechatTasks = read("src/api/wechatTasks.ts");
const tokenStore = read("src/authToken.ts");
const newcarRedirect = read("src/newcarRedirect.ts");
const envExample = read("../.env.lan.example");
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
assertIncludes(authApi, "fetchCurrentAuthUserWithoutRedirect", "auth api exposes a no-redirect backend auth probe for local mock mode");
assertIncludes(authApi, 'fetch(`${baseUrl}/auth/me`', "auth api no-redirect probe calls 9000 /auth/me");
assertIncludes(authApi, "switchToInternalSystem", "auth api exposes browser-side NewCar switch");
assertIncludes(authApi, "/api/external-auth/switch-to-internal", "auth api calls upstream switch-to-internal directly");
assertIncludes(authApi, "headers.Authorization = `Bearer ${token}`", "NewCar switch sends the external bearer token");
assertIncludes(authApi, "body: JSON.stringify({})", "NewCar switch and logout send an empty JSON object");
assertIncludes(authApi, 'redirectUrl.protocol !== "http:"', "NewCar switch rejects non-http redirect protocols");
assertIncludes(authApi, 'redirectUrl.protocol !== "https:"', "NewCar switch accepts only http or https redirects");
assertIncludes(authApi, "logoutAutoWechat", "auth api exposes direct 9000 logout without global interceptors");
assertIncludes(authApi, 'fetch(`${baseUrl}/auth/logout`', "auth api logout calls 9000 directly");
assertIncludes(authApi, "退出失败，请重试", "auth api logout exposes only a fixed readable error");
assertIncludes(authApi, "AUTH_REQUEST_TIMEOUT_MS = 10_000", "new auth requests use a ten second timeout");
assertIncludes(authApi, "AbortSignal.timeout(AUTH_REQUEST_TIMEOUT_MS)", "new auth requests carry an abort signal");
assertIncludes(authApi, 'replace(/\\/+$/, "")', "new auth request base urls remove trailing slashes");

assertIncludes(app, 'source === "new_car_project"', "app only consumes NewCar redirect code");
assertIncludes(app, "assertCanEnterSystem", "app enforces auto_wechat:use");
assertIncludes(app, "await fetchCurrentAuthUser()", "app asks 9000 /auth/me after token is saved");
assertIncludes(app, "await fetchCurrentAuthUserWithoutRedirect()", "app probes backend mock auth before consuming NewCar code");
assertOrder(
  app,
  "await fetchCurrentAuthUserWithoutRedirect()",
  "exchangeExternalCode(code)",
  "app must let backend mock auth win before direct NewCar code exchange",
);
assertIncludes(app, "cleanCodeFromUrl()", "app clears one-time code from URL");
assertIncludes(app, "new URL(window.location.href)", "app reads NewCar code from the current browser URL");
assertIncludes(app, "`${url.pathname}${url.search}${url.hash}`", "app preserves current route when clearing one-time code");
assertIncludes(app, "externalMerchantNotBound", "app keeps unbound external account out of business routes");
assertIncludes(app, "permissionDenied", "app keeps permission denied users out of relogin loops");
assertIncludes(app, "exchangeCodeFailed", "app handles invalid one-time code as a readable error");
assertIncludes(app, "redirectToNewCarLogin", "app redirects missing/expired external auth to NewCar login");
assertIncludes(app, "const data = await fetchCurrentAuthUser();", "app tries 9000 /auth/me before checking local token");
assertOrder(
  app,
  "const data = await fetchCurrentAuthUser();",
  "const token = getExternalToken();",
  "app restores backend mock auth before reading local external token",
);
assertNotIncludes(
  app,
  "} else if (redirectToNewCarLogin({ message: \"正在前往统一登录，请稍候…\" })) {",
  "app must not redirect to NewCar only because local token is missing",
);
assertIncludes(app, "consumeSavedRedirectPathAfterLogin", "app consumes saved path after code login");
assertIncludes(app, "resolvePostLoginPath", "app checks saved path against current user permissions");
assertIncludes(app, "canAccessPath", "app rejects saved paths the current user cannot access");
assertIncludes(app, "replaceCurrentPath", "app replaces browser path after permission-aware resolution");
assertIncludes(app, "AuthErrorScreen", "app renders user-facing auth error states");
assertIncludes(app, "handleRelogin", "app relogin action clears local auth state before NewCar redirect");
assertIncludes(app, "handleBackToWorkbench", "app permission action returns to the default workbench");
assertIncludes(app, "loginRedirectNotice", "app renders a user-facing NewCar redirect notice");
assertIncludes(app, "authMode?: string", "app user carries auth mode");
assertIncludes(app, "sourceSystem?: string", "app user carries source system");
assertIncludes(app, "authMode: data.auth_mode", "app maps backend auth_mode onto user");
assertIncludes(app, "sourceSystem: data.source_system", "app maps backend source_system onto user");
assertIncludes(app, "isMockAuthUser(user)", "app routes local mock users through full local workspace default");
assertIncludes(app, "window.location.assign(redirectUrl)", "app uses the validated upstream NewCar redirect url");
assertIncludes(app, 'import { Toaster, toast } from "sonner";', "app owns the global Sonner host and toast producer");
assertIncludes(app, '<Toaster position="top-right" richColors />', "app renders the global Sonner host");
assertIncludes(app, "logoutRetryTokenRef", "app keeps failed logout token only in page memory");
assertIncludes(app, "logoutAutoWechat(retryToken)", "app retries logout through the same 9000 endpoint");
assertIncludes(app, 'setLogoutViewState("pending")', "app unloads protected routes while logout is pending");
assertIncludes(app, 'const succeeded = state === "succeeded"', "logout status distinguishes a successful logout");
assertIncludes(app, "onRetry, onRelogin", "logout status accepts a relogin action");
assertIncludes(app, "onRelogin={handleRelogin}", "successful logout page uses the existing relogin handler");
assertIncludes(app, "重新登录", "successful logout page offers relogin");
assertIncludes(app, 'role="status" aria-live="polite"', "logout status is announced accessibly");
assertIncludes(app, 'setLogoutViewState("idle")', "relogin leaves the logout status screen");
assertIncludes(app, "logoutRetryTokenRef.current = null", "relogin clears the in-memory retry token");
assertOrder(
  app.slice(app.indexOf("const performLogout")),
  "setNewCarAuthRedirectSuppressed(true)",
  'setLogoutViewState("pending")',
  "logout suppresses stale 401 redirects before changing the view",
);
assertOrder(
  app.slice(app.indexOf("const handleRelogin")),
  "setNewCarAuthRedirectSuppressed(false)",
  "redirectToNewCarLogin({ message:",
  "explicit relogin re-enables redirects before going to NewCar",
);
// P4：logout、改密、管理员退出三类敏感操作都启用并发 401 抑制；relogin 与改密业务失败恢复抑制。
assert.equal((app.match(/setNewCarAuthRedirectSuppressed\(true\)/g) || []).length, 3, "logout/改密/管理员退出均启用 401 抑制");
assert.equal((app.match(/setNewCarAuthRedirectSuppressed\(false\)/g) || []).length, 2, "relogin 与改密业务失败恢复 401 跳转");
assertNotIncludes(
  app,
  'redirectToNewCarLogin({ message: "正在退出登录',
  "auto_wechat logout no longer redirects to NewCar",
);

assertIncludes(capabilities, "isMockAuthUser", "capabilities expose local mock auth predicate");
assertIncludes(capabilities, 'user.authMode === "mock"', "capabilities detect mock auth mode");
assertIncludes(capabilities, 'user.sourceSystem === "mock"', "capabilities detect mock source system");
assertIncludes(capabilities, 'permissions.includes("*")', "capabilities treat wildcard mock permissions as full access");
assertOrder(capabilities, "isMockAuthUser(user)", "isSuperAdmin(user)", "permission checks must let mock auth win before normal roles");

assertIncludes(sideNav, "const isMockUser = isMockAuthUser(user)", "side nav detects local mock user");
assertIncludes(sideNav, "isAdminUser && !isMockUser", "side nav does not hide merchant centers for mock admins");
assertIncludes(sideNav, "visibleAdminItems.length > 0", "side nav can append admin entries for mock users");
assertIncludes(sideNav, "onSwitchToNewCar", "side nav receives the NewCar switch action");
assertIncludes(sideNav, "switchingToNewCar", "side nav exposes a stable switching state");
assertIncludes(sideNav, "切换到内部系统", "side nav labels the administrator switch action");
assertIncludes(sideNav, "isAdminUser ? (", "side nav renders administrator and merchant footer actions exclusively");
assertIncludes(sideNav, "ExternalLinkIcon", "side nav uses the standard external-link icon");
assertIncludes(sideNav, "LoaderCircleIcon", "side nav uses the standard loading icon");

assertIncludes(indexPage, "onSwitchToNewCar", "index forwards the NewCar switch action");
assertIncludes(indexPage, "switchingToNewCar", "index forwards the NewCar switching state");
assertNotIncludes(indexPage, 'import { Toaster } from "sonner";', "index does not own the global Sonner host");
assertNotIncludes(indexPage, "<Toaster", "index does not render a route-scoped Sonner host");
assert.equal(
  (app.match(/<Toaster\b/g) || []).length + (indexPage.match(/<Toaster\b/g) || []).length,
  1,
  "app and index render exactly one Sonner host",
);

assertIncludes(indexPage, "const isMockUser = isMockAuthUser(user)", "index detects local mock user");
assertIncludes(indexPage, "isAdminRouteNav", "index distinguishes admin nav from merchant nav");
assertIncludes(indexPage, "handleNavChange", "index routes mock nav clicks to merchant or admin state");
assertIncludes(indexPage, "isAdminRouteNav(initialActiveNav)", "index initializes mock admin routes correctly");

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
assertIncludes(client, "setNewCarAuthRedirectSuppressed", "9000 api client exposes the logout redirect guard");
assertIncludes(
  client,
  "!newCarAuthRedirectSuppressed && shouldRedirectToNewCarLogin(error)",
  "9000 api client checks the logout redirect guard before redirecting",
);

assertIncludes(tokenStore, "sessionStorage", "token store uses sessionStorage");
assertIncludes(tokenStore, 'EXTERNAL_TOKEN_KEY = "external_token"', "token store uses the runtime sessionStorage key");
assertNotIncludes(tokenStore, "external_auth_token", "token store does not use the historical mistaken key");

assertIncludes(newcarRedirect, "NEWCAR_LOGIN_URL", "NewCar redirect helper uses configured login url");
assertIncludes(newcarRedirect, "NEWCAR_REDIRECT_PATH_KEY", "NewCar redirect helper stores current path");
assertIncludes(newcarRedirect, 'DEFAULT_POST_LOGIN_PATH = "/"', "NewCar redirect helper falls back to permission-based app default");
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
assertIncludes(newcarRedirect, "consumeSavedRedirectPathAfterLogin", "NewCar redirect helper returns saved path candidate after login");
assertIncludes(newcarRedirect, "return null", "NewCar redirect helper lets App compute permission-based default");
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
assertNotIncludes(wechatTasks, 'apiClient.post("/wechat-tasks"', "browser must not call the disabled generic WeChat task creation endpoint");
assertNotIncludes(wechatTasks, "createWechatTask", "frontend must not expose the disabled generic WeChat task creation helper");
assertIncludes(wechatAgentPage, "fetchBrowserPendingWechatTasks({ limit: 20 })", "wechat assistant page uses browser pending task helper");
assertIncludes(wechatTaskPanel, "fetchBrowserPendingWechatTasks({ limit: 50 })", "wechat task panel uses browser pending task helper");
assertIncludes(wechatTaskPanel, 'fetchBrowserPendingWechatTasks({ task_type: "detect_reply", limit: 10 })', "detect reply list uses browser pending task helper");
assertIncludes(wechatAgentPage, "startLocalWechatTest", "wechat assistant paste test uses the Local Agent safety route");
assertIncludes(wechatTaskPanel, "startLocalWechatTest", "legacy task panel paste test uses the Local Agent safety route");
assertNotIncludes(wechatAgentPage, "createWechatTask", "wechat assistant page must not use the disabled generic task creation route");
assertNotIncludes(wechatTaskPanel, "createWechatTask", "legacy task panel must not use the disabled generic task creation route");
assertNotIncludes(wechatAgentPage, "fetchPendingWechatTasks", "wechat assistant page no longer calls the Local Agent pending poll helper");
assertNotIncludes(wechatTaskPanel, "fetchPendingWechatTasks", "wechat task panel no longer calls the Local Agent pending poll helper");

assertIncludes(envExample, "VITE_NEWCAR_AUTH_BASE_URL=http://192.168.110.19:8790", "frontend env example documents NewCar base url");
assertIncludes(envExample, "VITE_NEWCAR_LOGIN_URL=http://192.168.110.19:5174/login", "frontend env example documents NewCar login url");

await runAuthBehaviorChecks();
await runClientRedirectSuppressionChecks();

console.log("NewCar direct code exchange check passed.");
