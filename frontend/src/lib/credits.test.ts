import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { fetchCredits } from "./credits";

describe("fetchCredits", () => {
  it("parses balance payload", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ balance: 100, monthly_quota: 100, plan: "free" }), { status: 200 }),
    );
    const c = await fetchCredits();
    expect(c.balance).toBe(100);
    expect(c.plan).toBe("free");
  });
});
