import { useAuthStore } from "./auth";

// 单飞刷新：并发的 401 只应触发一次 /api/auth/refresh。首个调用创建共享
// promise，后续并发调用 await 同一个；settle 后清空以便下次可再刷新。
let refreshInFlight: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  const r = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
  if (!r.ok) return null;
  const token = (await r.json()).access_token as string;
  useAuthStore.getState().setToken(token);
  return token;
}

export function tryRefresh(): Promise<string | null> {
  if (refreshInFlight === null) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
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
