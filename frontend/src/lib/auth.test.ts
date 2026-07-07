import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api";
import { useAuthStore } from "./auth";

describe("apiFetch 401 刷新重试", () => {
  beforeEach(() => {
    useAuthStore.getState().setToken("old-token");
    vi.restoreAllMocks();
  });

  it("401 时刷新并用新 token 重试一次", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: any, init?: any) => {
        calls.push(`${url}|${init?.headers?.Authorization ?? ""}`);
        if (String(url).endsWith("/api/auth/refresh"))
          return new Response(JSON.stringify({ access_token: "new-token" }), { status: 200 });
        const auth = init?.headers?.Authorization;
        return new Response(auth === "Bearer new-token" ? "{}" : "unauthorized", {
          status: auth === "Bearer new-token" ? 200 : 401,
        });
      }),
    );
    const resp = await apiFetch("/api/threads/");
    expect(resp.status).toBe(200);
    expect(useAuthStore.getState().accessToken).toBe("new-token");
    expect(calls.some((c) => c.includes("/api/auth/refresh"))).toBe(true);
  });

  it("刷新失败则清空 token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: any) =>
        new Response("no", { status: 401 }),
      ),
    );
    const resp = await apiFetch("/api/threads/");
    expect(resp.status).toBe(401);
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});
