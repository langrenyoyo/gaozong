import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import Index from "./pages/Index";
import Login from "./pages/Login";
import apiClient from "./api/client";
import { exchangeExternalCode, fetchCurrentAuthUser, type AuthContextData, type PermissionItem } from "./api/auth";
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
  isAdminLike,
  PERMISSIONS,
} from "./features/capabilities";

const queryClient = new QueryClient();
const adminRoutes = [
  { path: "/admin/autoreply-rollout", navId: "admin-autoreply-rollout", permission: PERMISSIONS.adminAutoreply },
  { path: "/admin/ai-reply-records", navId: "ai-reply-records", permission: PERMISSIONS.adminAiReplyRecords },
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
    admin: hasAdminPermission({ role, permissions }),
  };
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
  if (isAdminLike(user)) {
    if (hasPermission(user, PERMISSIONS.adminAutoreply)) return "/admin/autoreply-rollout";
    if (hasPermission(user, PERMISSIONS.adminAiReplyRecords)) return "/admin/ai-reply-records";
    if (hasPermission(user, PERMISSIONS.adminReturnVisitPrompts)) return "/admin/no-local-feature";
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
  if (pathname === "/admin/ai-reply-records") {
    return isAdminLike(user) && hasPermission(user, PERMISSIONS.adminAiReplyRecords);
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
  return [
    PERMISSIONS.adminAccounts,
    PERMISSIONS.adminForbiddenWords,
  ].some((code) => hasPermission(user, code));
}

function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search || ""}`} replace />;
}

type AuthErrorKind = "externalMerchantNotBound" | "permissionDenied" | "exchangeCodeFailed" | "tokenExpired" | "generic";

interface AuthErrorState {
  kind: AuthErrorKind;
  message: string;
}

function classifyAuthError(error: unknown): AuthErrorState {
  const message = error instanceof Error ? error.message : "外部登录失败，请重新登录";
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

const App = () => {
  const [user, setUser] = useState<AppUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<AuthErrorState | null>(null);
  const [loginRedirectNotice, setLoginRedirectNotice] = useState<string | null>(null);
  const externalMerchantNotBound = authError?.kind === "externalMerchantNotBound";

  useEffect(() => {
    let active = true;
    const removeRedirectNoticeListener = addNewCarRedirectNoticeListener(setLoginRedirectNotice);

    async function restoreAuth() {
      const url = new URL(window.location.href);
      const code = getNewCarRedirectCode(url);
      try {
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

        if (getExternalToken()) {
          const data = await fetchCurrentAuthUser();
          const nextUser = userFromAuthData(data);
          assertCanEnterSystem(nextUser);
          if (active) setUser(nextUser);
        } else if (redirectToNewCarLogin({ message: "正在前往统一登录，请稍候…" })) {
          return;
        }
      } catch (error) {
        cleanCodeFromUrl();
        const nextAuthError = classifyAuthError(error);
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
    setUser(nextUser);
  };

  const handleLogout = () => {
    const token = getExternalToken();
    void (async () => {
      try {
        if (token) {
          await apiClient.post("/auth/logout", {}, { headers: { Authorization: `Bearer ${token}` } });
        } else {
          await apiClient.post("/auth/logout", {});
        }
      } catch {
        // 退出失败不阻塞本地清理，避免用户卡在旧登录态。
      } finally {
        clearExternalToken();
        clearNewCarRedirectState();
        setUser(null);
        setAuthError(null);
        void redirectToNewCarLogin({ message: "正在退出登录，请稍候…", delayMs: 0, saveCurrentPath: false });
      }
    })();
  };

  const handleRelogin = () => {
    clearExternalToken();
    clearNewCarRedirectState();
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
      <Index user={user} onLogout={handleLogout} initialActiveNav={initialActiveNav} />
    ) : (
      <Login onLogin={handleLogin} authError={authError?.message || null} />
    );

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
