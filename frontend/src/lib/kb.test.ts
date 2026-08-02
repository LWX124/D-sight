import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import {
  addKbItems,
  addKbSource,
  createKb,
  deleteDoc,
  deleteKbSource,
  fetchDoc,
  fetchDocs,
  fetchKbSources,
  fetchKbThreadId,
  fetchKbs,
  fetchSubscribed,
  subscribeKb,
  uploadDoc,
} from "./kb";

describe("kb api", () => {
  it("parses list", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(
        JSON.stringify([{ id: "k1", name: "库", is_shared: false, doc_count: 2 }]),
        { status: 200 },
      ),
    );
    const items = await fetchKbs();
    expect(items[0].id).toBe("k1");
    expect(items[0].doc_count).toBe(2);
  });

  it("createKb posts json to /api/kb", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "k2", name: "n", is_shared: false, doc_count: 0 }), { status: 200 }),
    );
    const kb = await createKb("n");
    expect(kb.id).toBe("k2");
    expect(spy).toHaveBeenCalledWith("/api/kb", {
      method: "POST",
      body: JSON.stringify({ name: "n" }),
      headers: { "Content-Type": "application/json" },
    });
  });

  it("uploadDoc posts FormData without JSON content-type", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("{}", { status: 200 }));
    const file = new File(["hello"], "a.txt", { type: "text/plain" });
    await uploadDoc("k1", file);
    const [path, init] = spy.mock.calls[0];
    expect(path).toBe("/api/kb/k1/documents");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.headers as Record<string, string> | undefined)?.["Content-Type"]).toBeUndefined();
  });

  it("subscribeKb posts to subscribe slug", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ kb_id: "k9", name: "共享库" }), { status: 200 }),
    );
    const r = await subscribeKb("abc123");
    expect(r.kb_id).toBe("k9");
    expect(spy).toHaveBeenCalledWith("/api/kb/subscribe/abc123", { method: "POST" });
  });

  it("fetchSubscribed parses list", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([{ id: "s1", name: "订阅库" }]), { status: 200 }),
    );
    const items = await fetchSubscribed();
    expect(items[0].id).toBe("s1");
  });

  it("fetchDocs 带分页参数并解析新字段", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(
        JSON.stringify([{
          id: "d1", title: "某篇文章", filename: null, status: "ready", chunk_count: 3,
          error: null, source_type: "wechat_article",
          source_url: "https://mp.weixin.qq.com/s/x", published_at: "2026-07-01T00:00:00Z",
        }]),
        { status: 200 },
      ),
    );
    const docs = await fetchDocs("k1", { limit: 20, offset: 40 });
    expect(docs[0].title).toBe("某篇文章");
    expect(docs[0].filename).toBeNull();
    expect(docs[0].source_type).toBe("wechat_article");
    expect(spy.mock.calls[0][0]).toBe("/api/kb/k1/documents?limit=20&offset=40");
  });

  it("fetchDoc 返回入库文本快照", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({
        id: "d1", title: "t", filename: null, status: "ready", chunk_count: 1, error: null,
        source_type: "news_item", source_url: null, published_at: null, text: "正文快照",
      }), { status: 200 }),
    );
    const d = await fetchDoc("k1", "d1");
    expect(d.text).toBe("正文快照");
    expect(spy.mock.calls[0][0]).toBe("/api/kb/k1/documents/d1");
  });

  it("deleteDoc 发 DELETE", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await deleteDoc("k1", "d1");
    expect(spy).toHaveBeenCalledWith("/api/kb/k1/documents/d1", { method: "DELETE" });
  });

  it("addKbItems 提交数组并解析结果", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({
        added: 2, duplicate: 1, failed: [{ source_ref_id: "x", error: "快讯不存在" }],
      }), { status: 200 }),
    );
    const r = await addKbItems("k1", [
      { source_type: "news_item", source_ref_id: "a" },
      { source_type: "news_item", source_ref_id: "b" },
    ]);
    expect(r.added).toBe(2);
    expect(r.duplicate).toBe(1);
    expect(r.failed[0].error).toBe("快讯不存在");
    const [path, init] = spy.mock.calls[0];
    expect(path).toBe("/api/kb/k1/items");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string).items).toHaveLength(2);
  });

  it("addKbSource 提交订阅", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({
        id: "s1", source_type: "wechat_account", source_ref_id: "acc-1",
        display_name: "财经号", status: "pending", enabled: true, error: null,
        last_synced_at: null,
      }), { status: 200 }),
    );
    const s = await addKbSource("k1", {
      source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号",
    });
    expect(s.status).toBe("pending");
    expect(spy.mock.calls[0][0]).toBe("/api/kb/k1/sources");
  });

  it("deleteKbSource 默认不 purge，显式传 true 才带参数", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await deleteKbSource("k1", "s1");
    expect(spy).toHaveBeenCalledWith("/api/kb/k1/sources/s1?purge=false", { method: "DELETE" });
    await deleteKbSource("k1", "s1", true);
    expect(spy).toHaveBeenLastCalledWith("/api/kb/k1/sources/s1?purge=true", { method: "DELETE" });
  });

  it("fetchKbThreadId 取常驻会话 id", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ thread_id: "t-1" }), { status: 200 }),
    );
    expect(await fetchKbThreadId("k1")).toBe("t-1");
  });

  it("接口失败时抛错而不是静默返回空", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("nope", { status: 409 }));
    await expect(addKbItems("k1", [{ source_type: "news_item", source_ref_id: "a" }]))
      .rejects.toThrow();
  });

  it("剥掉 FastAPI 的 detail 信封，只把文案给用户", async () => {
    // 后端 HTTPException(409, "该知识库已达 2000 篇文档上限…") → {"detail":"…"}
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "该知识库已达 2000 篇文档上限，请先清理或新建知识库" }), {
        status: 409,
      }),
    );
    await expect(addKbItems("k1", [{ source_type: "news_item", source_ref_id: "a" }]))
      .rejects.toThrow("该知识库已达 2000 篇文档上限，请先清理或新建知识库");
  });

  it("非 JSON 错误响应原样透出，不吞掉", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response("502 Bad Gateway", { status: 502 }),
    );
    await expect(fetchDocs("k1")).rejects.toThrow("502 Bad Gateway");
  });

  it("空响应体时回落到状态码", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("", { status: 500 }));
    await expect(deleteDoc("k1", "d1")).rejects.toThrow("HTTP 500");
  });

  it("fetchKbSources 解析列表", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([{
        id: "s1", source_type: "wechat_account", source_ref_id: "a", display_name: "号",
        status: "ready", enabled: true, error: null, last_synced_at: "2026-08-01T00:00:00Z",
      }]), { status: 200 }),
    );
    const rows = await fetchKbSources("k1");
    expect(rows[0].display_name).toBe("号");
  });
});
