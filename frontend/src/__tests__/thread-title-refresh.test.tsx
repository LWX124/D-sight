import React from "react";
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatPage from "@/pages/ChatPage";

// 标题由后端用首条提问回填，而侧栏列表是在"建会话后、发消息前"拉的（那时是"新对话"）。
// 本文件锁住：一轮发送后侧栏会重拉列表拿到真标题，且发生在 onResponse（响应头到达）
// 而非 onFinish（整轮结束）——否则深度分析要等数分钟标题才更新。
const apiFetch = vi.fn();
let capturedOnSendResponse: ((status: number) => void) | null = null;
let capturedOnFinish: (() => void) | null = null;

vi.mock("@/lib/api", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }));
vi.mock("@/lib/auth", () => ({ logout: vi.fn() }));
vi.mock("@/chat/RuntimeProvider", () => ({
  RuntimeProvider: ({
    children,
    onSendResponse,
    onFinish,
  }: {
    children: React.ReactNode;
    onSendResponse?: (status: number) => void;
    onFinish?: () => void;
  }) => {
    capturedOnSendResponse = onSendResponse ?? null;
    capturedOnFinish = onFinish ?? null;
    return <div data-testid="runtime">{children}</div>;
  },
}));
vi.mock("@/chat/Thread", async () => {
  const actual = await vi.importActual<typeof import("@/chat/Thread")>("@/chat/Thread");
  return { ...actual, Thread: () => <div>会话内容</div> };
});
vi.mock("@/chat/KbMountSelector", () => ({ KbMountSelector: () => null }));
vi.mock("@/lib/credits", () => ({
  creditsKey: ["credits"],
  fetchCredits: vi.fn().mockResolvedValue(null),
}));
vi.mock("@/panels/NewsPanel", () => ({ default: () => null }));
vi.mock("@/panels/SocialPanel", () => ({ default: () => null }));
vi.mock("@/panels/KbPanel", () => ({ default: () => null }));
vi.mock("@/panels/SkillsPanel", () => ({ default: () => null }));
vi.mock("@/panels/FundArbPanel", () => ({ default: () => null }));

const TID = "123e4567-e89b-12d3-a456-426614174000";

function makeThread(title: string) {
  return {
    id: TID,
    title,
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
    last_message_at: "2026-07-31T00:00:00Z",
  };
}

function renderChat() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/chat/${TID}`]}>
        <Routes>
          <Route path="/chat/:threadId?" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("会话标题刷新", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    capturedOnSendResponse = null;
    capturedOnFinish = null;
    // 首次列表返回"新对话"（尚未发消息），之后返回后端回填的真标题
    let listCalls = 0;
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/threads/") {
        listCalls += 1;
        return new Response(
          JSON.stringify([makeThread(listCalls === 1 ? "新对话" : "分析贵州茅台的护城河")]),
          { status: 200 },
        );
      }
      if (path === `/api/threads/${TID}`) {
        return new Response(JSON.stringify(makeThread("新对话")), { status: 200 });
      }
      return new Response("{}", { status: 200 });
    });
  });

  it("响应头到达（onResponse）即重拉列表，侧栏显示真标题", async () => {
    renderChat();
    await screen.findByText("新对话");

    // 模拟后端返回 200 响应头：此时标题已在后端 commit
    capturedOnSendResponse?.(200);

    expect(await screen.findByText("分析贵州茅台的护城河")).toBeInTheDocument();
  });

  it("402（积分不足）不触发列表刷新，只显示提示", async () => {
    renderChat();
    await screen.findByText("新对话");
    const before = apiFetch.mock.calls.filter(([p]) => p === "/api/threads/").length;

    capturedOnSendResponse?.(402);

    expect(await screen.findByTestId("credit-notice")).toBeInTheDocument();
    await waitFor(() => {
      const after = apiFetch.mock.calls.filter(([p]) => p === "/api/threads/").length;
      expect(after).toBe(before);
    });
  });

  it("onFinish 只刷新积分，不承担标题刷新（避免等整轮结束）", async () => {
    renderChat();
    await screen.findByText("新对话");
    const before = apiFetch.mock.calls.filter(([p]) => p === "/api/threads/").length;

    capturedOnFinish?.();

    await waitFor(() => {
      const after = apiFetch.mock.calls.filter(([p]) => p === "/api/threads/").length;
      expect(after).toBe(before);
    });
  });
});
