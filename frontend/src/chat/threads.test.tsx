import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// mock apiFetch：返回两条会话，不接真后端
const apiFetch = vi.fn(async (path: string) => {
  if (path === "/api/threads/" ) {
    return new Response(
      JSON.stringify([
        { id: "t1", title: "茅台现在多少钱", created_at: "", updated_at: "" },
        { id: "t2", title: "第二个会话", created_at: "", updated_at: "" },
      ]),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }
  return new Response("{}", { status: 200 });
});
vi.mock("@/lib/api", () => ({ apiFetch: (p: string, i?: RequestInit) => apiFetch(p, i) }));

async function renderSidebar(activeThreadId: string | null = "t1") {
  const { ThreadListSidebar } = await import("./ThreadListSidebar");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ThreadListSidebar activeThreadId={activeThreadId} onSelect={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ThreadListSidebar 列表渲染", () => {
  it("渲染两条会话标题与新建按钮", async () => {
    await renderSidebar();
    expect(screen.getByRole("button", { name: /新建会话/ })).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText("茅台现在多少钱")).toBeTruthy();
      expect(screen.getByText("第二个会话")).toBeTruthy();
    });
  });
});
