import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { Toaster, toast } from "sonner";
import Index from "./pages/Index";
import Login from "./pages/Login";
import ChangePasswordDialog from "./components/ChangePasswordDialog";
import {
  changeExternalPassword,
  exchangeExternalCode,
  fetchCurrentAuthUser,
  fetchCurrentAuthUserWithoutRedirect,
  logoutAutoWechat,
  logoutCurrentBrowserOnNewCar,
  switchToInternalSystem,
  type AuthContextData,
  type PermissionItem,
} from "./api/auth";
import { setNewCarAuthRedirectSuppressed } from "./api/client";
import { clearExternalToken, getExternalToken, setExternalToken } from "./authToken";
import {
  addNewCarRedirectNoticeListener,
  clearNewCarRedirectState,
  consumeSavedRedirectPathAfterLogin,
  redirectToNewCarLogin,
} from "./newcarRedirect";
import { capabilityRoutes, legacyRouteRedirects } from "./features/routes";
import {
  filterCapabilityNavCenters,
  hasAdminPermission,
  hasPermission,
  isMockAuthUser,
  isAdminLike,
  PERMISSIONS,
} from "./features/capabilities";
import { userFacingError } from "./lib/userFacingError";
import { clearAllAgentTokens } from "./features/ai-edit/localApi";

const queryClient = new QueryClient();
const adminRoutes = [
  { path: "/admin/autoreply-rollout", navId: "admin-autoreply-rollout", permission: PERMISSIONS.adminAutoreply },
  { path: "/admin/return-visits", navId: "admin-return-visits", permission: PERMISSIONS.adminReturnVisitPrompts },
  { path: "/admin/ai-reply-records", navId: "ai-reply-records", permission: PERMISSIONS.adminAiReplyRecords },
  { path: "/admin/forbidden-words", navId: "admin-forbidden-words", permission: PERMISSIONS.adminForbiddenWords },
  { path: "/admin/compute-config", navId: "admin-compute-config", permission: PERMISSIONS.adminComputeConfig },
  { path: "/admin/no-local-feature", navId: "admin-no-local-feature", message: "暂无可访问管理员功能" },
  { path: "/admin/newcar-owned", navId: "admin-newcar-owned", message: "该管理功能请在 NewCarProject 操作" },
];

export interface AppUser {
  account: string;
  role: "merchant" | "super_admin" | "operation_admin" | "finance_admin";
  roleLabel: string;
  permissions?: string[];
  permissionItems?: PermissionItem[];
  merchantId?: string | null;
  merchantIds?: string[];
  admin?: boolean;
  authMode?: string;
  sourceSystem?: string;
}

function userFromAuthData(data: AuthContextData): AppUser {
  const permissions = data.permission_codes || data.permissions || [];
  const adminLike = Boolean(data.super_admin) || permissions.some((code) => code.startsWith("auto_wechat:admin:"));
  const role = data.super_admin ? "super_admin" : adminLike ? "operation_admin" : "merchant";
  return {
    account: data.username || data.display_name || data.user_id || "external-user",
    role,
    roleLabel: data.super_admin ? "超级管理员" : adminLike ? "管理员账号" : "商户账号",
    permissions,
    permissionItems: data.permission_items || [],
    merchantId: data.merchant_id ?? null,
    merchantIds: data.merchant_ids || [],
    admin: hasAdminPermission({ role, permissions, authMode: data.auth_mode, sourceSystem: data.source_system }),
    authMode: data.auth_mode,
    sourceSystem: data.source_system,
  };
}

function isMockAuthData(data: AuthContextData | null): data is AuthContextData {
  return data?.auth_mode === "mock" || data?.source_system === "mock";
}

function assertCanEnterSystem(user: AppUser) {
  if (!hasPermission(user, PERMISSIONS.use) && !isAdminLike(user)) {
    throw new Error("当前账号暂无访问该功能权限，请联系管理员开通。");
  }
}

function getNewCarRedirectCode(url: URL): string | null {
  const code = url.searchParams.get("code");
  const source = url.searchParams.get("source");
  return code && source === "new_car_project" ? code : null;
}

function cleanCodeFromUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete("code");
  url.searchParams.delete("source");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function replaceCurrentPath(path: string) {
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (path !== currentPath) {
    window.history.replaceState({}, "", path);
  }
}

function defaultPathForUser(user: AppUser): string {
  if (isMockAuthUser(user)) {
    const first = filterCapabilityNavCenters(user)[0];
    return first?.path || "/";
  }
  if (isAdminLike(user)) {
    // 自动回复灰度入口已隐藏：是否自动发送只由 env 开关决定，不再跳转灰度控制台。
    if (hasPermission(user, PERMISSIONS.adminAiReplyRecords)) return "/admin/ai-reply-records";
    if (hasPermission(user, PERMISSIONS.adminReturnVisitPrompts)) return "/admin/return-visits";
    if (hasPermission(user, PERMISSIONS.adminForbiddenWords)) return "/admin/forbidden-words";
    if (hasPermission(user, PERMISSIONS.adminComputeConfig)) return "/admin/compute-config";
    if (hasAnyNewCarOwnedAdminPermission(user)) return "/admin/newcar-owned";
    return "/admin/no-local-feature";
  }
  const first = filterCapabilityNavCenters(user)[0];
  return first?.path || "/";
}

function pathNameOf(path: string): string | null {
  if (!path.trim() || !path.startsWith("/") || path.startsWith("//")) {
    return null;
  }
  try {
    return new URL(path, window.location.origin).pathname;
  } catch {
    return null;
  }
}

function canAccessPath(user: AppUser, path: string): boolean {
  const pathname = pathNameOf(path);
  if (!pathname) return false;

  if (pathname === "/admin/autoreply-rollout") {
    return isAdminLike(user) && hasPermission(user, PERMISSIONS.adminAutoreply);
  }
  if (pathname === "/admin/return-visits") {
    return isAdminLike(user) && hasPermission(user, PERMISSIONS.adminReturnVisitPrompts);
  }
  if (pathname === "/admin/ai-reply-records") {
    return isAdminLike(user) && hasPermission(user, PERMISSIONS.adminAiReplyRecords);
  }
  if (pathname === "/admin/forbidden-words") {
    return isAdminLike(user) && hasPermission(user, PERMISSIONS.adminForbiddenWords);
  }
  if (pathname === "/admin/compute-config") {
    return hasPermission(user, PERMISSIONS.adminComputeConfig);
  }
  if (pathname === "/admin/newcar-owned" || pathname === "/admin/no-local-feature") {
    return isAdminLike(user);
  }

  const legacyTarget = legacyRouteRedirects.find((route) => pathname === route.from)?.to;
  if (legacyTarget) {
    return canAccessPath(user, legacyTarget);
  }

  const allowedNavIds = new Set(filterCapabilityNavCenters(user).flatMap((center) => center.children.map((item) => item.id)));
  return capabilityRoutes.some((route) => route.path === pathname && allowedNavIds.has(route.navId));
}

function resolvePostLoginPath(user: AppUser, candidateRedirect: string | null): string {
  if (candidateRedirect && canAccessPath(user, candidateRedirect)) {
    return candidateRedirect;
  }
  return defaultPathForUser(user);
}

function hasAnyNewCarOwnedAdminPermission(user: AppUser): boolean {
  // adminForbiddenWords 是 9000 本地违禁词库功能，不是 NewCar 上游功能，已单独挂载本地路由。
  return [PERMISSIONS.adminAccounts].some((code) => hasPermission(user, code));
}

function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  const sourceQuery = location.search.startsWith("?") ? location.search.slice(1) : location.search;
  const separator = to.includes("?") ? "&" : "?";
  const destination = sourceQuery ? `${to}${separator}${sourceQuery}` : to;
  return <Navigate to={`${destination}${location.hash || ""}`} replace />;
}

type AuthErrorKind = "externalMerchantNotBound" | "permissionDenied" | "exchangeCodeFailed" | "tokenExpired" | "generic";

interface AuthErrorState {
  kind: AuthErrorKind;
  message: string;
}

type LogoutViewState = "idle" | "pending" | "succeeded" | "failed";

// 改密结果状态页：
// - success：密码已修改，需重新登录（只有此态可展示“密码已修改”）。
// - relogin：登录已失效（401），需重新登录，不得声称密码已修改。
// - unknown：结果未知（超时/网络/5xx/异常 JSON/2xx 非白名单），需重新登录确认，不得声称成功或失败。
// - null：不展示状态页。
type PasswordResultView = "success" | "relogin" | "unknown";

function classifyAuthError(error: unknown): AuthErrorState {
  const message = userFacingError(error, "外部登录失败，请重新登录");
  if (message.includes("账号未绑定商户")) {
    return {
      kind: "externalMerchantNotBound",
      message: "账号已登录，但暂未绑定商户，请联系管理员开通服务。",
    };
  }
  if (message.includes("暂无访问该功能权限") || message.includes("缺少 auto_wechat:use 权限")) {
    return {
      kind: "permissionDenied",
      message: "当前账号暂无访问该功能权限，请联系管理员开通。",
    };
  }
  if (message.includes("登录凭证已失效") || message.includes("code")) {
    return {
      kind: "exchangeCodeFailed",
      message: "登录凭证已失效，请重新登录。",
    };
  }
  if (message.includes("登录已过期")) {
    return {
      kind: "tokenExpired",
      message: "登录已过期，请重新登录",
    };
  }
  return { kind: "generic", message };
}

function AuthErrorScreen({
  error,
  onRelogin,
  onBackToWorkbench,
}: {
  error: AuthErrorState;
  onRelogin: () => void;
  onBackToWorkbench: () => void;
}) {
  const canBackToWorkbench = error.kind === "permissionDenied";
  return (
    <div className="grid min-h-screen place-items-center bg-[#070d18] px-6 text-white">
      <div className="w-full max-w-md rounded-lg border border-white/10 bg-[#101729] p-6 shadow-[0_18px_50px_rgba(0,0,0,0.32)]">
        <div className="text-base font-semibold">{error.message}</div>
        <div className="mt-2 text-sm leading-6 text-slate-400">
          {error.kind === "externalMerchantNotBound"
            ? "当前登录态已保留，请联系管理员完成商户绑定后再进入系统。"
            : "如已完成开通，请重新登录后再试。"}
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          {canBackToWorkbench ? (
            <button
              type="button"
              onClick={onBackToWorkbench}
              className="rounded-md border border-white/15 px-4 py-2 text-sm font-semibold text-slate-200 transition hover:bg-white/8"
            >
              返回工作台
            </button>
          ) : null}
          <button
            type="button"
            onClick={onRelogin}
            className="rounded-md bg-[#2563eb] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#1d4ed8]"
          >
            重新登录
          </button>
        </div>
      </div>
    </div>
  );
}

function LogoutStatusScreen({ state, onRetry, onRelogin }: { state: Exclude<LogoutViewState, "idle">; onRetry: () => void; onRelogin: () => void }) {
  const failed = state === "failed";
  const succeeded = state === "succeeded";
  const title = state === "pending" ? "正在退出..." : failed ? "退出失败，请重试" : "已退出";
  const description =
    state === "pending"
      ? "正在注销当前系统登录态。"
      : failed
        ? "本地登录状态已清理，可在当前页面重试注销。"
        : "当前系统的本地登录状态已清理。";

  return (
    <div role="status" aria-live="polite" className="grid min-h-screen place-items-center bg-[#070d18] px-6 text-white">
      <div className="w-full max-w-sm text-center">
        <div className="text-base font-semibold">{title}</div>
        <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p>
        {succeeded ? (
          <button
            type="button"
            onClick={onRelogin}
            className="mt-5 h-10 rounded-md bg-[#2563eb] px-4 text-sm font-semibold text-white transition hover:bg-[#1d4ed8]"
          >
            重新登录
          </button>
        ) : failed ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-5 h-10 rounded-md bg-[#2563eb] px-4 text-sm font-semibold text-white transition hover:bg-[#1d4ed8]"
          >
            重试退出
          </button>
        ) : null}
      </div>
    </div>
  );
}

const App = () => {
  const [user, setUser] = useState<AppUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<AuthErrorState | null>(null);
  const [loginRedirectNotice, setLoginRedirectNotice] = useState<string | null>(null);
  const [logoutViewState, setLogoutViewState] = useState<LogoutViewState>("idle");
  const [switchingToNewCar, setSwitchingToNewCar] = useState(false);
  const logoutRetryTokenRef = useRef<string | null>(null);

  // 商户改密：弹窗开关、提交中、错误文案。改密成功/失效/未知后进入对应结果状态页。
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [changePasswordError, setChangePasswordError] = useState<string | null>(null);
  const [passwordResultView, setPasswordResultView] = useState<PasswordResultView | null>(null);

  // 管理员当前浏览器退出：提交中、失败提示。token 只保留在页面内存 ref，不持久化。
  const [adminLoggingOut, setAdminLoggingOut] = useState(false);
  const [adminLogoutError, setAdminLogoutError] = useState<string | null>(null);
  const adminLogoutTokenRef = useRef<string | null>(null);
  const externalMerchantNotBound = authError?.kind === "externalMerchantNotBound";

  useEffect(() => {
    let active = true;
    const removeRedirectNoticeListener = addNewCarRedirectNoticeListener(setLoginRedirectNotice);

    async function restoreAuth() {
      const url = new URL(window.location.href);
      const code = getNewCarRedirectCode(url);
      try {
        const backendAuthData = await fetchCurrentAuthUserWithoutRedirect();
        if (isMockAuthData(backendAuthData)) {
          cleanCodeFromUrl();
          const nextUser = userFromAuthData(backendAuthData);
          assertCanEnterSystem(nextUser);
          clearNewCarRedirectState();
          if (active) setUser(nextUser);
          return;
        }

        if (code) {
          const data = await exchangeExternalCode(code);
          if (data.token) {
            setExternalToken(data.token);
          }
          const currentUserData = await fetchCurrentAuthUser();
          cleanCodeFromUrl();
          const nextUser = userFromAuthData(currentUserData);
          assertCanEnterSystem(nextUser);
          const postLoginPath = resolvePostLoginPath(nextUser, consumeSavedRedirectPathAfterLogin());
          replaceCurrentPath(postLoginPath);
          if (active) setUser(nextUser);
          return;
        }

        const data = await fetchCurrentAuthUser();
        const token = getExternalToken();
        const nextUser = userFromAuthData(data);
        assertCanEnterSystem(nextUser);
        if (active) setUser(nextUser);
        if (!token) {
          clearNewCarRedirectState();
        }
      } catch (error) {
        cleanCodeFromUrl();
        const nextAuthError = classifyAuthError(error);
        if (nextAuthError.kind === "tokenExpired" && redirectToNewCarLogin({ message: "正在前往统一登录，请稍候…" })) {
          return;
        }
        if (nextAuthError.kind !== "externalMerchantNotBound" && nextAuthError.kind !== "permissionDenied") {
          clearExternalToken();
        }
        if (active) {
          setUser(null);
          setAuthError(nextAuthError);
        }
      } finally {
        if (active) setAuthLoading(false);
      }
    }

    void restoreAuth();

    const onAuthExpired = () => {
      clearAllAgentTokens();  // FIX4-3：鉴权过期清理 Local Agent token，防残留
      if (redirectToNewCarLogin({ message: "登录已过期，正在重新登录…" })) {
        return;
      }
      setUser(null);
      setAuthError({ kind: "tokenExpired", message: "登录已过期，请重新登录" });
    };
    window.addEventListener("external-auth-expired", onAuthExpired);

    return () => {
      active = false;
      removeRedirectNoticeListener();
      window.removeEventListener("external-auth-expired", onAuthExpired);
    };
  }, []);

  const allowedRoutes = useMemo(() => {
    if (!user) return capabilityRoutes;
    const allowedNavIds = new Set(filterCapabilityNavCenters(user).flatMap((center) => center.children.map((item) => item.id)));
    return capabilityRoutes.filter((route) => allowedNavIds.has(route.navId));
  }, [user]);

  const deniedRoutes = useMemo(() => {
    if (!user) return [];
    const allowedPaths = new Set(allowedRoutes.map((route) => route.path));
    return capabilityRoutes.filter((route) => !allowedPaths.has(route.path));
  }, [allowedRoutes, user]);

  const handleLogin = (nextUser: AppUser) => {
    setAuthError(null);
    queryClient.clear();
    // FIX3-1：登录时清理可能残留的旧商户 Local Agent token（防 A 退出 B 登录复用）
    clearAllAgentTokens();
    setUser(nextUser);
  };

  const performLogout = async (retryToken: string | null) => {
    setNewCarAuthRedirectSuppressed(true);
    setLogoutViewState("pending");
    setUser(null);
    logoutRetryTokenRef.current = retryToken;
    try {
      await logoutAutoWechat(retryToken);
      logoutRetryTokenRef.current = null;
      setLogoutViewState("succeeded");
    } catch {
      setLogoutViewState("failed");
    } finally {
      queryClient.clear();
      clearExternalToken();
      clearNewCarRedirectState();
      clearAllAgentTokens();  // FIX3-1：退出清理 Local Agent token，防跨商户残留
      setUser(null);
      setAuthError(null);
    }
  };

  const handleLogout = () => {
    void performLogout(getExternalToken());
  };

  const handleSwitchToNewCar = async () => {
    if (switchingToNewCar) return;
    setSwitchingToNewCar(true);
    try {
      const redirectUrl = await switchToInternalSystem();
      window.location.assign(redirectUrl);
    } catch (error) {
      toast.error(userFacingError(error, "切换到 NewCar 失败，请稍后重试。"));
    } finally {
      setSwitchingToNewCar(false);
    }
  };

  const clearLocalPersistentAuthState = () => {
    queryClient.clear();
    clearExternalToken();
    clearNewCarRedirectState();
    clearAllAgentTokens();  // 退出/改密/重新登录统一清理 Local Agent token，防跨商户残留
  };

  const openChangePassword = () => {
    setChangePasswordError(null);
    setChangePasswordOpen(true);
  };

  const handleChangePassword = async (oldPassword: string, newPassword: string) => {
    // 改密期间抑制并发 401 跳转，避免晚到 401 覆盖改密结果。
    setNewCarAuthRedirectSuppressed(true);
    setChangingPassword(true);
    setChangePasswordError(null);
    try {
      const outcome = await changeExternalPassword(oldPassword, newPassword);
      if (outcome.status === "success") {
        // 成功：external token 已失效，清本地持久状态并进入“密码已修改”结果页。
        clearLocalPersistentAuthState();
        setUser(null);
        setAuthError(null);
        setChangePasswordOpen(false);
        setPasswordResultView("success");
        return;
      }
      if (outcome.status === "business") {
        // 400/403 业务失败：保留当前登录态，恢复 401 跳转，弹窗内提示错误供重试。
        setNewCarAuthRedirectSuppressed(false);
        setChangePasswordError(outcome.message);
        return;
      }
      if (outcome.status === "relogin") {
        // 401 登录已失效：清本地持久状态、卸载受保护页、进入“登录已失效”结果页，不得声称密码已修改。
        clearLocalPersistentAuthState();
        setUser(null);
        setAuthError(null);
        setChangePasswordOpen(false);
        setPasswordResultView("relogin");
        return;
      }
      // unknown（超时/网络/5xx/异常 JSON/2xx 非白名单）：
      // 清本地持久状态、卸载受保护页、进入“结果未知”结果页，不恢复旧会话、不恢复 401 跳转，不得声称成功或失败。
      clearLocalPersistentAuthState();
      setUser(null);
      setAuthError(null);
      setChangePasswordOpen(false);
      setPasswordResultView("unknown");
    } finally {
      setChangingPassword(false);
    }
  };

  // 管理员退出内部函数接收显式 token：首次调用读取存储，重试必须直接使用 adminLogoutTokenRef.current，
  // 不得再次读取存储或覆盖为空。
  const performAdminLogout = async (token: string | null) => {
    if (adminLoggingOut) return;
    // 管理员退出开始即抑制 401、卸载受保护页，token 只存页面内存 ref 供重试。
    setNewCarAuthRedirectSuppressed(true);
    setAdminLogoutError(null);
    adminLogoutTokenRef.current = token;
    setAdminLoggingOut(true);
    setUser(null);
    try {
      const redirectUrl = await logoutCurrentBrowserOnNewCar(token ?? "");
      // 成功：清本地持久状态，校验 redirect_url 后跳转 NewCar 登录页。
      clearLocalPersistentAuthState();
      adminLogoutTokenRef.current = null;
      window.location.replace(redirectUrl);
    } catch {
      // 失败：清本地持久状态并停留当前页显示重试，不跳错系统；内存 token 保留供重试。
      clearLocalPersistentAuthState();
      setAdminLogoutError("退出失败，请重试");
    } finally {
      setAdminLoggingOut(false);
    }
  };

  const handleAdminLogout = () => {
    void performAdminLogout(getExternalToken());
  };

  const retryAdminLogout = () => {
    // 重试必须直接使用原内存 token，不得再次读取存储或覆盖为空。
    if (!adminLogoutTokenRef.current) {
      // token 已不在内存，走重新登录。
      void handleRelogin();
      return;
    }
    void performAdminLogout(adminLogoutTokenRef.current);
  };

  const handleRelogin = () => {
    // 解除 401 跳转抑制，并清理全部 P3+P4 状态与内存 ref，不恢复旧会话。
    setNewCarAuthRedirectSuppressed(false);
    setLogoutViewState("idle");
    logoutRetryTokenRef.current = null;
    setChangePasswordOpen(false);
    setChangingPassword(false);
    setChangePasswordError(null);
    setPasswordResultView(null);
    setAdminLoggingOut(false);
    setAdminLogoutError(null);
    adminLogoutTokenRef.current = null;
    queryClient.clear();
    clearExternalToken();
    clearNewCarRedirectState();
    clearAllAgentTokens();  // FIX4-3：重新登录清理 Local Agent token，防跨商户残留
    setUser(null);
    setAuthError(null);
    void redirectToNewCarLogin({ message: "正在前往统一登录，请稍候…", delayMs: 0, saveCurrentPath: false });
  };

  const handleBackToWorkbench = () => {
    setAuthError(null);
    window.location.replace(defaultPathForUser(user || { account: "", role: "merchant", roleLabel: "商户账号" }));
  };

  const renderIndex = (initialActiveNav: string) =>
    user && !externalMerchantNotBound ? (
      <Index
        user={user}
        onLogout={handleLogout}
        onSwitchToNewCar={handleSwitchToNewCar}
        switchingToNewCar={switchingToNewCar}
        onChangePassword={openChangePassword}
        changingPassword={changingPassword}
        onAdminLogout={handleAdminLogout}
        adminLoggingOut={adminLoggingOut}
        initialActiveNav={initialActiveNav}
      />
    ) : (
      <Login onLogin={handleLogin} authError={authError?.message || null} />
    );

  if (logoutViewState !== "idle") {
    return (
      <LogoutStatusScreen
        state={logoutViewState}
        onRetry={() => void performLogout(logoutRetryTokenRef.current)}
        onRelogin={handleRelogin}
      />
    );
  }

  // 改密结果状态页：按 success/relogin/unknown 展示不同文案，均要求重新登录。
  // 只有 success 才能展示“密码已修改”；relogin 只说登录已失效；unknown 只说结果未知，不得声称成功或失败。
  if (passwordResultView) {
    const resultTitle =
      passwordResultView === "success"
        ? "密码已修改，请重新登录"
        : passwordResultView === "relogin"
          ? "登录已失效，请重新登录"
          : "密码修改结果未知，请重新登录确认";
    const resultDescription =
      passwordResultView === "success"
        ? "为保障账号安全，请使用新密码重新登录。"
        : passwordResultView === "relogin"
          ? "当前登录态已失效，请重新登录后继续操作。"
          : "由于网络或服务原因，改密结果无法确认，请重新登录后确认密码是否已更新。";
    return (
      <div role="status" aria-live="polite" className="grid min-h-screen place-items-center bg-[#070d18] px-6 text-white">
        <div className="w-full max-w-sm text-center">
          <div className="text-base font-semibold">{resultTitle}</div>
          <p className="mt-2 text-sm leading-6 text-slate-400">{resultDescription}</p>
          <button
            type="button"
            onClick={handleRelogin}
            className="mt-5 h-10 rounded-md bg-[#2563eb] px-4 text-sm font-semibold text-white transition hover:bg-[#1d4ed8]"
          >
            重新登录
          </button>
        </div>
      </div>
    );
  }

  // 管理员当前浏览器退出失败状态页：清本地持久状态后停留当前页，保留内存 token 供重试。
  if (adminLogoutError) {
    return (
      <div role="status" aria-live="polite" className="grid min-h-screen place-items-center bg-[#070d18] px-6 text-white">
        <div className="w-full max-w-sm text-center">
          <div className="text-base font-semibold">退出失败，请重试</div>
          <p className="mt-2 text-sm leading-6 text-slate-400">本地登录状态已清理，可在当前页面重试退出。</p>
          <button
            type="button"
            onClick={retryAdminLogout}
            className="mt-5 h-10 rounded-md bg-[#2563eb] px-4 text-sm font-semibold text-white transition hover:bg-[#1d4ed8]"
          >
            重试退出
          </button>
        </div>
      </div>
    );
  }

  if (loginRedirectNotice) {
    return (
      <div className="grid min-h-screen place-items-center bg-[#070d18] text-sm font-semibold text-white">
        {loginRedirectNotice}
      </div>
    );
  }

  if (authLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-[#070d18] text-sm font-semibold text-white">
        正在恢复登录态...
      </div>
    );
  }

  if (authError && authError.kind !== "tokenExpired") {
    return <AuthErrorScreen error={authError} onRelogin={handleRelogin} onBackToWorkbench={handleBackToWorkbench} />;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <Toaster position="top-right" richColors />
      {user && !isAdminLike(user) ? (
        <ChangePasswordDialog
          open={changePasswordOpen}
          submitting={changingPassword}
          errorMessage={changePasswordError}
          onOpenChange={(next) => {
            setChangePasswordOpen(next);
            if (!next) setChangePasswordError(null);
          }}
          onSubmit={handleChangePassword}
        />
      ) : null}
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              user && !externalMerchantNotBound ? (
                <Navigate to={defaultPathForUser(user)} replace />
              ) : (
                <Login onLogin={handleLogin} authError={authError?.message || null} />
              )
            }
          />
          {allowedRoutes.map((route) => (
            <Route key={route.path} path={route.path} element={renderIndex(route.navId)} />
          ))}
          {adminRoutes.map((route) => (
            <Route
              key={route.path}
              path={route.path}
              element={
                user && isAdminLike(user) && (!route.permission || hasPermission(user, route.permission)) ? (
                  renderIndex(route.navId)
                ) : (
                  <AuthErrorScreen
                    error={{
                      kind: "permissionDenied",
                      message: route.message || "当前账号暂无访问该功能权限，请联系管理员开通。",
                    }}
                    onRelogin={handleRelogin}
                    onBackToWorkbench={handleBackToWorkbench}
                  />
                )
              }
            />
          ))}
          {deniedRoutes.map((route) => (
            <Route
              key={route.path}
              path={route.path}
              element={
                <AuthErrorScreen
                  error={{ kind: "permissionDenied", message: "当前账号暂无访问该功能权限，请联系管理员开通。" }}
                  onRelogin={handleRelogin}
                  onBackToWorkbench={handleBackToWorkbench}
                />
              }
            />
          ))}
          {legacyRouteRedirects.map((route) => (
            <Route key={route.from} path={route.from} element={<LegacyRedirect to={route.to} />} />
          ))}
          <Route path="*" element={<Navigate to={user && !externalMerchantNotBound ? defaultPathForUser(user) : "/"} replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
