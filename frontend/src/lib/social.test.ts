import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import {
  addBookmark,
  addUnifiedSubscription,
  createAihotSource,
  deleteAihotSource,
  getAihot,
  getAihotProviderStats,
  getFeed,
  listArticles,
  listAihotSources,
  previewWeiboAccount,
  refreshPublisher,
  refreshWeiboAccount,
  searchAccounts,
  updateAihotSource,
} from "./social";

describe("social api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

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

  it("getFeed consumes the paginated unified feed contract", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_before: "cursor-1" }), { status: 200 }),
    );
    const response = await getFeed({ publisher_id: "publisher id", limit: 50 });
    expect(response.next_before).toBe("cursor-1");
    expect(spy.mock.calls[0][0]).toContain("publisher_id=publisher+id");
  });

  it("refreshPublisher uses the publisher-scoped endpoint", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await refreshPublisher("publisher/id");
    expect(spy.mock.calls[0][0]).toBe("/api/social/publishers/publisher%2Fid/refresh");
  });

  it("addBookmark sends item_id and notes in JSON body", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "bookmark-1" }), { status: 200 }),
    );
    await addBookmark("item-1", "重点");
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(spy.mock.calls[0][0]).toBe("/api/social/bookmarks");
    expect(JSON.parse(String(init.body))).toEqual({ item_id: "item-1", notes: "重点" });
  });

  it("addUnifiedSubscription omits publisher_id for a discovered publisher", async () => {
    const response = {
      id: "sub-1", publisher_id: "publisher-1", platform: "wechat", external_id: "wx-1",
      name: "账号", avatar: null, enabled: true,
    };
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify(response), { status: 200 }),
    );
    await addUnifiedSubscription({ platform: "wechat", external_id: "wx-1", name: "账号" });
    const body = JSON.parse(String((spy.mock.calls[0][1] as RequestInit).body));
    expect(body).toEqual({ platform: "wechat", external_id: "wx-1", name: "账号" });
  });

  it("getAihot serializes window, semantic category and search", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], run: null, status: "no_data" }), { status: 200 }),
    );
    await getAihot({ window: "7d", category: "company", q: "贵州茅台" });
    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("window=7d");
    expect(url).toContain("category=company");
    expect(url).toContain("q=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0");
  });

  it("AIHot 管理 API 使用 typed sources 与 provider stats 契约", async () => {
    const spy = vi.spyOn(api, "apiFetch")
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "source-1", ok: true }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        days: 30,
        total_estimated_cost: 12.5,
        budget: 100,
        budget_warning: false,
        groups: [],
      }), { status: 200 }));

    await listAihotSources();
    await createAihotSource({
      platform: "wechat",
      external_id: "wx-1",
      name: "金融公众号",
      description: "长期金融研究",
      category: "market",
    });
    await updateAihotSource("source/id", { enabled: false });
    await deleteAihotSource("source/id");
    const stats = await getAihotProviderStats(30);

    expect(spy.mock.calls[0][0]).toBe("/api/aihot/sources");
    expect(JSON.parse(String((spy.mock.calls[1][1] as RequestInit).body))).toEqual({
      platform: "wechat",
      external_id: "wx-1",
      name: "金融公众号",
      description: "长期金融研究",
      category: "market",
    });
    expect(spy.mock.calls[2][0]).toBe("/api/aihot/sources/source%2Fid");
    expect((spy.mock.calls[2][1] as RequestInit).method).toBe("PATCH");
    expect((spy.mock.calls[3][1] as RequestInit).method).toBe("DELETE");
    expect(spy.mock.calls[4][0]).toBe("/api/aihot/provider-stats?days=30");
    expect(stats.total_estimated_cost).toBe(12.5);
  });
});
