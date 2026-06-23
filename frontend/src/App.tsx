import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Routes, Route, useLocation } from "react-router-dom";
import { useState } from "react";
import Index from "./pages/Index";
import Login from "./pages/Login";
import { capabilityRoutes, legacyRouteRedirects } from "./features/routes";

const queryClient = new QueryClient();

export interface AppUser {
  account: string;
  role: "merchant" | "super_admin" | "operation_admin" | "finance_admin";
  roleLabel: string;
}

function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  return <Navigate to={`${to}${location.search || ""}`} replace />;
}

const App = () => {
  const [user, setUser] = useState<AppUser | null>(null);
  const renderIndex = (initialActiveNav: string) =>
    user ? (
      <Index user={user} onLogout={() => setUser(null)} initialActiveNav={initialActiveNav} />
    ) : (
      <Login onLogin={setUser} />
    );

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              user ? (
                <Navigate to="/douyin-cs/workbench" replace />
              ) : (
                <Login onLogin={setUser} />
              )
            }
          />
          {capabilityRoutes.map((route) => (
            <Route key={route.path} path={route.path} element={renderIndex(route.navId)} />
          ))}
          {legacyRouteRedirects.map((route) => (
            <Route key={route.from} path={route.from} element={<LegacyRedirect to={route.to} />} />
          ))}
          <Route path="*" element={<Navigate to={user ? "/douyin-cs/workbench" : "/"} replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
