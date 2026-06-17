import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import { useState } from "react";
import Index from "./pages/Index";
import Login from "./pages/Login";

const queryClient = new QueryClient();

export interface AppUser {
  account: string;
  role: "merchant" | "super_admin" | "operation_admin" | "finance_admin";
  roleLabel: string;
}

const App = () => {
  const [user, setUser] = useState<AppUser | null>(null);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              user ? (
                <Navigate to="/douyin-ai-cs" replace />
              ) : (
                <Login onLogin={setUser} />
              )
            }
          />
          <Route
            path="/douyin-ai-cs"
            element={
              user ? (
                <Index user={user} onLogout={() => setUser(null)} initialActiveNav="douyin-ai-cs" />
              ) : (
                <Login onLogin={setUser} />
              )
            }
          />
          <Route
            path="/douyin-ai-cs-test"
            element={
              user ? (
                <Index user={user} onLogout={() => setUser(null)} initialActiveNav="douyin-ai-cs-test" />
              ) : (
                <Login onLogin={setUser} />
              )
            }
          />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
