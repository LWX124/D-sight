import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { fetchNews } from "./news";

describe("news api", () => {
  it("parses list and requests channel=news", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            id: "n1",
            channel: "news",
            title: "标题",
            content: "内容",
            url: "https://example.com",
            published_at: "2026-07-07T12:00:00+00:00",
          },
        ]),
        { status: 200 },
      ),
    );
    const items = await fetchNews({ channel: "news" });
    expect(items[0].id).toBe("n1");
    expect(items[0].channel).toBe("news");
    const path = spy.mock.calls[0][0] as string;
    expect(path).toContain("channel=news");
  });

  it("defaults channel to news when omitted", async () => {
    const spy = vi
      .spyOn(api, "apiFetch")
      .mockResolvedValue(new Response("[]", { status: 200 }));
    await fetchNews();
    const path = spy.mock.calls[0][0] as string;
    expect(path).toContain("channel=news");
  });

  it("percent-encodes the + in ISO timestamps for before/after", async () => {
    const spy = vi
      .spyOn(api, "apiFetch")
      .mockResolvedValue(new Response("[]", { status: 200 }));
    await fetchNews({
      channel: "news",
      before: "2026-07-07T12:00:00+00:00",
      after: "2026-07-07T10:00:00+00:00",
      limit: 20,
    });
    const path = spy.mock.calls[0][0] as string;
    // URLSearchParams must encode the "+" as %2B, never leave a raw "+".
    expect(path).toContain("before=2026-07-07T12%3A00%3A00%2B00%3A00");
    expect(path).toContain("after=2026-07-07T10%3A00%3A00%2B00%3A00");
    expect(path).toContain("limit=20");
    expect(path).not.toMatch(/before=[^&]*\+/);
  });

  it("throws on non-ok response", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("nope", { status: 500 }));
    await expect(fetchNews()).rejects.toThrow("failed to load news");
  });
});
