import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { listArticles, searchAccounts } from "./social";

describe("social api", () => {
  it("searchAccounts hits search endpoint with keyword", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([{ fakeid: "F1", nickname: "号A", avatar: null, signature: null }]), { status: 200 }),
    );
    const rows = await searchAccounts("茅台");
    expect(rows[0].fakeid).toBe("F1");
    expect(spy.mock.calls[0][0] as string).toContain("/api/social/wechat/search");
    expect(spy.mock.calls[0][0] as string).toContain("keyword=");
  });

  it("listArticles requests account_id", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await listArticles("acc-1");
    expect(spy.mock.calls[0][0] as string).toContain("account_id=acc-1");
  });
});
