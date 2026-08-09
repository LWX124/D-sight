import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { listArticles, previewWeiboAccount, refreshWeiboAccount, searchAccounts } from "./social";

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

  it("previewWeiboAccount sends profile_url as JSON", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ account_id: "a1", uid: "123456", name: "账号", avatar: null, description: null, profile_url: "https://weibo.com/u/123456" }), { status: 200 }),
    );
    await previewWeiboAccount("https://weibo.com/u/123456");
    expect(spy.mock.calls[0][0]).toBe("/api/social/weibo/accounts/preview");
    expect(JSON.parse(String((spy.mock.calls[0][1] as RequestInit).body)).profile_url).toContain("123456");
  });

  it("refreshWeiboAccount uses encoded account_id", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ added: 0 }), { status: 200 }),
    );
    await refreshWeiboAccount("account id");
    expect(spy.mock.calls[0][0]).toContain("account_id=account%20id");
  });
});
