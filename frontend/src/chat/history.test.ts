import { beforeEach, describe, expect, it, vi } from "vitest";
import { ensureFreshToken, loadInitialState } from "./history";
import { useAuthStore } from "@/lib/auth";

describe("loadInitialState 历史加载", () => {
  beforeEach(() => {
    useAuthStore.getState().setToken("tok");
    vi.restoreAllMocks();
  });

  it("拉到两条历史 → initialState.messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            messages: [
              { type: "human", content: "茅台多少钱" },
              { type: "ai", content: "假回复" },
            ],
          }),
          { status: 200 },
        ),
      ),
    );
    const state = await loadInitialState("tid-1");
    expect(state.messages).toEqual([
      { type: "human", content: "茅台多少钱" },
      { type: "ai", content: "假回复" },
    ]);
  });

  it("请求失败 → 空历史（不抛）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("err", { status: 500 })));
    const state = await loadInitialState("tid-1");
    expect(state).toEqual({ messages: [] });
  });

  it("首次 401 走 apiFetch 单飞刷新后成功（不额外并发刷新）", async () => {
    let refreshCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: any, init?: any) => {
        if (String(url).endsWith("/api/auth/refresh")) {
          refreshCount += 1;
          return new Response(JSON.stringify({ access_token: "new-token" }), { status: 200 });
        }
        const auth = init?.headers?.Authorization;
        if (auth === "Bearer new-token")
          return new Response(JSON.stringify({ messages: [] }), { status: 200 });
        return new Response("unauthorized", { status: 401 });
      }),
    );
    const state = await loadInitialState("tid-1");
    expect(state).toEqual({ messages: [] });
    expect(refreshCount).toBe(1);
    expect(useAuthStore.getState().accessToken).toBe("new-token");
  });
});

describe("ensureFreshToken 会话内刷新", () => {
  beforeEach(() => {
    useAuthStore.getState().setToken("stale");
    vi.restoreAllMocks();
  });

  it("token 过期（me 返回 401）→ 刷新后返回新 token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: any, init?: any) => {
        if (String(url).endsWith("/api/auth/refresh"))
          return new Response(JSON.stringify({ access_token: "fresh" }), { status: 200 });
        const auth = init?.headers?.Authorization;
        return new Response(auth === "Bearer fresh" ? "{}" : "no", {
          status: auth === "Bearer fresh" ? 200 : 401,
        });
      }),
    );
    const token = await ensureFreshToken();
    expect(token).toBe("fresh");
    expect(useAuthStore.getState().accessToken).toBe("fresh");
  });

  it("token 有效（me 返回 200）→ 原 token 不变", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 200 })),
    );
    const token = await ensureFreshToken();
    expect(token).toBe("stale");
  });
});
