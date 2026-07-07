import { create } from "zustand";

type AuthState = {
  accessToken: string | null;
  setToken: (t: string) => void;
  clearToken: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  setToken: (t) => set({ accessToken: t }),
  clearToken: () => set({ accessToken: null }),
}));

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
}

export async function requestCode(email: string) {
  const r = await post("/api/auth/request-code", { email });
  if (!r.ok) throw new Error((await r.json()).detail ?? "发送失败");
}

export async function register(email: string, code: string, password: string) {
  const r = await post("/api/auth/register", { email, code, password });
  if (!r.ok) throw new Error((await r.json()).detail ?? "注册失败");
  useAuthStore.getState().setToken((await r.json()).access_token);
}

export async function login(email: string, password: string) {
  const r = await post("/api/auth/login", { email, password });
  if (!r.ok) throw new Error((await r.json()).detail ?? "登录失败");
  useAuthStore.getState().setToken((await r.json()).access_token);
}

export async function logout() {
  await post("/api/auth/logout", {});
  useAuthStore.getState().clearToken();
}
