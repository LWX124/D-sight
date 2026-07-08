import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { fetchSkills, installSkill } from "./skills";

describe("skills api", () => {
  it("parses list", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([{ slug: "dyp-ask", name: "n", description: "d",
        category: "research", price: 0, model_weight: "flash", is_default: true, installed: true }]),
        { status: 200 }),
    );
    const items = await fetchSkills();
    expect(items[0].slug).toBe("dyp-ask");
    expect(items[0].installed).toBe(true);
  });

  it("install posts to endpoint", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await installSkill("dyp-ask");
    expect(spy).toHaveBeenCalledWith("/api/skills/dyp-ask/install", { method: "POST" });
  });
});
