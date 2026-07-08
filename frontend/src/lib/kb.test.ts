import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { createKb, fetchKbs, fetchSubscribed, subscribeKb, uploadDoc } from "./kb";

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
});
