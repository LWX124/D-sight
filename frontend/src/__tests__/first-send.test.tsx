import React from "react";
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatPage from "@/pages/ChatPage";

const apiFetch = vi.fn();
const runtimeSend = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));
vi.mock("@/lib/auth", () => ({ logout: vi.fn() }));
vi.mock("@/chat/ThreadListSidebar", () => ({
  threadsKey: ["threads"],
  ThreadListSidebar: () => <aside />,
}));
vi.mock("@/chat/RuntimeProvider", () => ({
  RuntimeProvider: ({ threadId, initialMessage, children }: { threadId: string; initialMessage?: string | null; children: React.ReactNode }) => {
    React.useEffect(() => {
      if (initialMessage) runtimeSend(threadId, initialMessage);
    }, [initialMessage, threadId]);
    return <div data-testid="runtime">{children}</div>;
  },
}));
vi.mock("@/chat/Thread", async () => {
  const actual = await vi.importActual<typeof import("@/chat/Thread")>("@/chat/Thread");
  return { ...actual, Thread: () => <div>会话内容</div> };
});
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

function renderDraft() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/chat/new"]}>
        <Location />
        <Routes>
          <Route path="/chat/:threadId?" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const thread = {
  id: "123e4567-e89b-12d3-a456-426614174000",
  title: "新对话",
  created_at: "2026-07-31T00:00:00Z",
  updated_at: "2026-07-31T00:00:00Z",
  last_message_at: null,
};

describe("First send", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    runtimeSend.mockReset();
    apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/api/threads/" && init?.method === "POST") {
        return new Response(JSON.stringify(thread), { status: 200 });
      }
      if (path === "/api/threads/") return new Response("[]", { status: 200 });
      return new Response("{}", { status: 200 });
    });
  });

  it("creates a thread, switches URL, and sends through the real thread", async () => {
    renderDraft();
    fireEvent.change(screen.getByLabelText("Message input"), { target: { value: "测试消息" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent(`/chat/${thread.id}`);
    });
    expect(apiFetch).toHaveBeenCalledWith("/api/threads/", expect.objectContaining({ method: "POST" }));
    expect(runtimeSend).toHaveBeenCalledWith(thread.id, "测试消息");
  });

  it("prevents duplicate creation on rapid sends", async () => {
    let resolveCreate!: (response: Response) => void;
    const createPending = new Promise<Response>((resolve) => { resolveCreate = resolve; });
    apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/api/threads/" && init?.method === "POST") return createPending;
      if (path === "/api/threads/") return new Response("[]", { status: 200 });
      return new Response("{}", { status: 200 });
    });

    renderDraft();
    fireEvent.change(screen.getByLabelText("Message input"), { target: { value: "测试" } });
    const send = screen.getByRole("button", { name: "Send message" });
    fireEvent.click(send);
    fireEvent.click(send);

    expect(apiFetch.mock.calls.filter(([path, init]) => path === "/api/threads/" && init?.method === "POST")).toHaveLength(1);
    resolveCreate(new Response(JSON.stringify(thread), { status: 200 }));
    await screen.findByTestId("runtime");
  });

  it("keeps the draft and permits retry when creation fails", async () => {
    apiFetch.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/api/threads/" && init?.method === "POST") return new Response("{}", { status: 500 });
      if (path === "/api/threads/") return new Response("[]", { status: 200 });
      return new Response("{}", { status: 200 });
    });

    renderDraft();
    const input = screen.getByLabelText("Message input");
    fireEvent.change(input, { target: { value: "保留消息" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("创建会话失败");
    expect(input).toHaveValue("保留消息");
    expect(screen.getByTestId("location")).toHaveTextContent("/chat/new");

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => {
      expect(apiFetch.mock.calls.filter(([path, init]) => path === "/api/threads/" && init?.method === "POST")).toHaveLength(2);
    });
  });
});
