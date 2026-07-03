import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import Index from "./pages/Index";
import Login from "./pages/Login";
import { exchangeExternalCode, fetchCurrentAuthUser, type AuthContextData, type PermissionItem } from "./api/auth";
import { clearExternalToken, getExternalToken, setExternalToken } from "./authToken";
import { addNewCarRedirectNoticeListener, redirectToNewCarLogin, restoreSavedRedirectPathAfterLogin } from "./newcarRedirect";
import { capabilityRoutes, legacyRouteRedirects } from "./features/routes";
import { filterCapabilityNavCenters, hasPermission, PERMISSIONS } from "./features/capabilities";

const queryClient = new QueryClient();

export interface AppUser {
  account: string;
  role: "merchant" | "super_admin" | "operation_admin" | "finance_admin";
  roleLabel: string;
  permissions?: string[];
  permissionItems?: PermissionItem[];
  merchantId?: string | null;
  merchantIds?: string[];
}

function userFromAuthData(data: AuthContextData): AppUser {
  const permissions = data.permission_codes || data.permissions || [];
  const role = data.super_admin ? "super_admin" : "merchant";
  return {
    account: data.username || data.display_name || data.user_id || "external-user",
    role,
    roleLabel: role === "super_admin" ? "超级管理员" : "商户账号",
    permissions,
    permissionItems: data.permission_items || [],
    merchantId: data.merchant_id ?? null,
    merchantIds: data.merchant_ids || [],
  };
}

function assertCanEnterSystem(user: AppUser) {
  if (!hasPermission(user, PERMISSIONS.use)) {
    throw new Error("账号缺少 auto_wechat:use 权限，无法进入系统");
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

function defaultPathForUser(user: AppUser): string {
  if (user.role !== "merchant") return "/agents";
  const first = filterCapabilityNavCenters(user)[0];
  return first?.path || "/";
}

function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search || ""}`} replace />;
}

const App = () => {
  const [user, setUser] = useState<AppUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [loginRedirectNotice, setLoginRedirectNotice] = useState<string | null>(null);
  const externalMerchantNotBound = authError === "账号未绑定商户，请联系管理员。";

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
          restoreSavedRedirectPathAfterLogin();
          const nextUser = userFromAuthData(currentUserData);
          assertCanEnterSystem(nextUser);
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
        clearExternalToken();
        cleanCodeFromUrl();
        if (active) {
          setUser(null);
          setAuthError(error instanceof Error ? error.message : "外部登录失败，请重新登录");
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
      setAuthError("登录已过期，请重新登录");
    };
    window.addEventListener("external-auth-expired", onAuthExpired);

    return () => {
      active = false;
      removeRedirectNoticeListener();
      window.removeEventListener("external-auth-expired", onAuthExpired);
    };
  }, []);

  const allowedRoutes = useMemo(() => {
    if (!user || user.role !== "merchant") return capabilityRoutes;
    const allowedNavIds = new Set(filterCapabilityNavCenters(user).flatMap((center) => center.children.map((item) => item.id)));
    return capabilityRoutes.filter((route) => allowedNavIds.has(route.navId));
  }, [user]);

  const handleLogin = (nextUser: AppUser) => {
    setAuthError(null);
    setUser(nextUser);
  };

  const handleLogout = () => {
    clearExternalToken();
    setUser(null);
    setAuthError(null);
  };

  const renderIndex = (initialActiveNav: string) =>
    user && !externalMerchantNotBound ? (
      <Index user={user} onLogout={handleLogout} initialActiveNav={initialActiveNav} />
    ) : (
      <Login onLogin={handleLogin} authError={authError} />
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
                <Login onLogin={handleLogin} authError={authError} />
              )
            }
          />
          {allowedRoutes.map((route) => (
            <Route key={route.path} path={route.path} element={renderIndex(route.navId)} />
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
