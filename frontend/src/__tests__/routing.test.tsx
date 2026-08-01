import React from "react";
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatPage from "@/pages/ChatPage";

const apiFetch = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

vi.mock("@/lib/auth", () => ({
  logout: vi.fn(),
}));

vi.mock("@/chat/ThreadListSidebar", () => ({
  threadsKey: ["threads"],
  ThreadListSidebar: () => <aside data-testid="thread-sidebar" />,
}));

vi.mock("@/chat/RuntimeProvider", () => ({
  RuntimeProvider: ({ threadId, children }: { threadId: string; children: React.ReactNode }) => (
    <div data-testid="runtime" data-thread-id={threadId}>{children}</div>
  ),
}));

vi.mock("@/chat/Thread", () => ({ Thread: () => <div>会话内容</div> }));
vi.mock("@/chat/KbMountSelector", () => ({ KbMountSelector: () => null }));
vi.mock("@/lib/credits", () => ({ creditsKey: ["credits"], fetchCredits: vi.fn().mockResolvedValue(null) }));
vi.mock("@/panels/NewsPanel", () => ({ default: () => null }));
vi.mock("@/panels/SocialPanel", () => ({ default: () => null }));
vi.mock("@/panels/KbPanel", () => ({ default: () => null }));
vi.mock("@/panels/SkillsPanel", () => ({ default: () => null }));
vi.mock("@/panels/FundArbPanel", () => ({ default: () => null }));

function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderRoute(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Location />
        <Routes>
          <Route path="/chat/:threadId?" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Chat routing", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/threads/") return new Response("[]", { status: 200 });
      return new Response("{}", { status: 200 });
    });
  });

  it("renders draft state on /chat/new without loading thread details", async () => {
    renderRoute("/chat/new");

    expect(screen.getByText("新建会话后开始对话")).toBeInTheDocument();
    expect(screen.queryByText("正在准备会话…")).not.toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalledWith(expect.stringMatching(/^\/api\/threads\/[^/]+$/));
  });

  it("loads a valid thread from /chat/:threadId", async () => {
    const threadId = "123e4567-e89b-12d3-a456-426614174000";

    renderRoute(`/chat/${threadId}`);

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(`/api/threads/${threadId}`);
    });
    expect(await screen.findByTestId("runtime")).toHaveAttribute("data-thread-id", threadId);
  });

  it("redirects an invalid thread id to /chat/new without an API request", async () => {
    renderRoute("/chat/invalid-id-404");

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/chat/new");
    });
    expect(apiFetch).not.toHaveBeenCalledWith("/api/threads/invalid-id-404");
  });

  it("redirects a missing thread to /chat/new", async () => {
    const threadId = "123e4567-e89b-12d3-a456-426614174001";
    apiFetch.mockImplementation(async (path: string) => {
      if (path === `/api/threads/${threadId}`) return new Response("{}", { status: 404 });
      if (path === "/api/threads/") return new Response("[]", { status: 200 });
      return new Response("{}", { status: 200 });
    });

    renderRoute(`/chat/${threadId}`);

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/chat/new");
    });
  });
});
