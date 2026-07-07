import { useAuthStore } from "./auth";

export async function tryRefresh(): Promise<string | null> {
  const r = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
  if (!r.ok) return null;
  const token = (await r.json()).access_token as string;
  useAuthStore.getState().setToken(token);
  return token;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const withAuth = (token: string | null): RequestInit => ({
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    credentials: "same-origin",
  });
  let resp = await fetch(path, withAuth(useAuthStore.getState().accessToken));
  if (resp.status === 401) {
    const fresh = await tryRefresh();
    if (fresh) {
      resp = await fetch(path, withAuth(fresh));
    } else {
      useAuthStore.getState().clearToken();
    }
  }
  return resp;
}
