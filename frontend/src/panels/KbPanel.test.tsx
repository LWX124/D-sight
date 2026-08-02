import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/kb", () => ({
  fetchKbs: vi.fn(async () => [
    { id: "k1", name: "研报库", is_shared: false, doc_count: 2 },
    { id: "k2", name: "快讯库", is_shared: true, doc_count: 0 },
  ]),
  createKb: vi.fn(),
  deleteKb: vi.fn(),
  shareKb: vi.fn(async () => ({ share_slug: "abc123" })),
  subscribeKb: vi.fn(),
  uploadDoc: vi.fn(),
  fetchDocs: vi.fn(async () => []),
  fetchDoc: vi.fn(async () => ({})),
  deleteDoc: vi.fn(async () => undefined),
  fetchKbSources: vi.fn(async () => []),
  deleteKbSource: vi.fn(),
  fetchKbThreadId: vi.fn(async () => "t-kb-1"),
  clearKbThread: vi.fn(async () => "t-kb-2"),
  fetchSubscribed: vi.fn(async () => []),
}));

// 对话栏依赖 assistant-ui 运行时，单测里替换为占位，只验证挂载参数
vi.mock("@/panels/kb/KbAssistant", () => ({
  default: ({ kbId }: { kbId: string }) => <div data-testid="kb-assistant">{kbId}</div>,
}));

// 每个用例前重置 mock 实现：上一个用例的 mockResolvedValue 会污染下一个，
// 不重置则用例间相互干扰（vi.clearAllMocks 只清调用记录，不清实现）。
beforeEach(async () => {
  const kb = await import("@/lib/kb");
  vi.mocked(kb.fetchKbs).mockResolvedValue([
    { id: "k1", name: "研报库", is_shared: false, doc_count: 2 },
    { id: "k2", name: "快讯库", is_shared: true, doc_count: 0 },
  ]);
  vi.mocked(kb.fetchDocs).mockImplementation(async (kbId: string) =>
    kbId === "k1"
      ? [
          {
            id: "d1", title: "茅台年报解读", filename: null, status: "ready", chunk_count: 5,
            error: null, source_type: "wechat_article",
            source_url: "https://mp.weixin.qq.com/s/x", published_at: "2026-07-20T02:00:00Z",
          },
          {
            id: "d2", title: "手册.pdf", filename: "手册.pdf", status: "processing",
            chunk_count: 0, error: null, source_type: "upload", source_url: null,
            published_at: null,
          },
        ]
      : [],
  );
  vi.mocked(kb.fetchDoc).mockResolvedValue({
    id: "d1", title: "茅台年报解读", filename: null, status: "ready", chunk_count: 5,
    error: null, source_type: "wechat_article",
    source_url: "https://mp.weixin.qq.com/s/x", published_at: "2026-07-20T02:00:00Z",
    text: "这是入库时的文本快照内容。",
  });
  vi.mocked(kb.fetchKbSources).mockResolvedValue([]);
});

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return import("./KbPanel").then(({ default: KbPanel }) =>
    render(
      <QueryClientProvider client={qc}>
        <KbPanel />
      </QueryClientProvider>,
    ),
  );
}

describe("KbPanel 三栏", () => {
  afterEach(() => vi.clearAllMocks());

  it("列出知识库，默认选中第一个并加载其内容索引", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    expect(screen.getByText("快讯库")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
  });

  it("切换知识库会换掉内容索引", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
    fireEvent.click(screen.getByText("快讯库"));
    await waitFor(() => expect(screen.queryByText("茅台年报解读")).toBeNull());
    await waitFor(() => expect(screen.getByText("暂无内容")).toBeTruthy());
  });

  it("点内容项后详情区展示入库文本快照与原文链接", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
    fireEvent.click(screen.getByText("茅台年报解读"));
    await waitFor(() =>
      expect(screen.getByText("这是入库时的文本快照内容。")).toBeTruthy(),
    );
    const link = screen.getByRole("link", { name: /原文/ });
    expect(link.getAttribute("href")).toBe("https://mp.weixin.qq.com/s/x");
  });

  it("处理中的文档显示状态徽章", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("手册.pdf")).toBeTruthy());
    expect(screen.getByText("处理中")).toBeTruthy();
  });

  it("对话栏默认折叠，展开后把当前库 id 传给助手", async () => {
    await renderPanel();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    expect(screen.queryByTestId("kb-assistant")).toBeNull();
    fireEvent.click(screen.getByTestId("kb-chat-toggle"));
    await waitFor(() => {
      expect(screen.getByTestId("kb-assistant").textContent).toBe("k1");
    });
  });

  it("删除内容后从索引中消失", async () => {
    const kb = await import("@/lib/kb");
    await renderPanel();
    await waitFor(() => expect(screen.getByText("茅台年报解读")).toBeTruthy());
    vi.mocked(kb.fetchDocs).mockResolvedValue([]);
    fireEvent.click(screen.getByTestId("kb-doc-delete-d1"));
    await waitFor(() => expect(kb.deleteDoc).toHaveBeenCalledWith("k1", "d1"));
  });

  it("没有知识库时给出引导文案", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.fetchKbs).mockResolvedValue([]);
    await renderPanel();
    await waitFor(() =>
      expect(screen.getByText("还没有知识库，先建一个吧")).toBeTruthy(),
    );
  });

  it("订阅源触顶时在面板上给出可见提示", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.fetchKbSources).mockResolvedValue([
      {
        id: "s1", source_type: "wechat_account", source_ref_id: "acc-1",
        display_name: "财经号", status: "limited", enabled: true,
        error: "该知识库已达 2000 篇文档上限", last_synced_at: "2026-08-01T00:00:00Z",
      },
    ]);
    await renderPanel();
    await waitFor(() => expect(screen.getByText("订阅：财经号")).toBeTruthy());
    expect(screen.getByText("已达上限，停止入库")).toBeTruthy();
  });

  it("断开订阅时询问是否连带删除文档", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.fetchKbSources).mockResolvedValue([
      {
        id: "s1", source_type: "wechat_account", source_ref_id: "acc-1",
        display_name: "财经号", status: "ready", enabled: true, error: null,
        last_synced_at: null,
      },
    ]);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderPanel();
    await waitFor(() => expect(screen.getByText("订阅：财经号")).toBeTruthy());
    fireEvent.click(screen.getByTestId("kb-source-remove-s1"));
    await waitFor(() =>
      expect(kb.deleteKbSource).toHaveBeenCalledWith("k1", "s1", false),
    );
    confirmSpy.mockRestore();
  });
});
