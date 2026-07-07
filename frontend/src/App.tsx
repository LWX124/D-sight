import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/lib/auth";
import { tryRefresh } from "@/lib/api";
import ChatPage from "@/pages/ChatPage";
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";

const qc = new QueryClient();

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.accessToken);
  // 页面刷新后内存中的 access token 会丢失；首次挂载且无 token 时，
  // 先用 refresh cookie 静默换取新 access，避免刷新即被登出。
  const [checking, setChecking] = useState(token === null);

  useEffect(() => {
    if (token !== null) {
      setChecking(false);
      return;
    }
    let active = true;
    void tryRefresh().finally(() => {
      if (active) setChecking(false);
    });
    return () => {
      active = false;
    };
    // 仅在首次挂载执行一次刷新尝试
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (checking) return null;
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <ChatPage />
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
