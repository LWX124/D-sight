import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThreadListSidebar } from "./ThreadListSidebar";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(async () => new Response("[]", { status: 200 })),
}));

describe("ThreadListSidebar navigation", () => {
  it("places AIHot directly after 7x24h as an independent menu", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ThreadListSidebar
          activeThreadId={null}
          activePanel="aihot"
          onSelect={vi.fn()}
          onPanelChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    const navLabels = screen.getAllByTestId(/^nav-/).map((element) => element.textContent);
    expect(navLabels.slice(0, 4)).toEqual(["对话", "7x24h", "AIHot", "社媒信息"]);
    expect(screen.getByTestId("nav-aihot").textContent).toBe("AIHot");
  });
});
