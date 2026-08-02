import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/kb", () => ({
  fetchKbs: vi.fn(async () => [
    { id: "k1", name: "研报库", is_shared: false, doc_count: 1 },
    { id: "k2", name: "快讯库", is_shared: false, doc_count: 0 },
  ]),
  createKb: vi.fn(async (name: string) => ({
    id: "k9", name, is_shared: false, doc_count: 0,
  })),
  addKbItems: vi.fn(async () => ({ added: 1, duplicate: 0, failed: [] })),
  addKbSource: vi.fn(async () => ({
    id: "s1", source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号",
    status: "pending", enabled: true, error: null, last_synced_at: null,
  })),
}));

function renderDialog(props: Record<string, unknown> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return import("./AddToKbDialog").then(({ default: AddToKbDialog }) =>
    render(
      <QueryClientProvider client={qc}>
        <AddToKbDialog
          open
          onClose={() => {}}
          mode="items"
          items={[{ source_type: "news_item", source_ref_id: "n1" }]}
          {...props}
        />
      </QueryClientProvider>,
    ),
  );
}

describe("AddToKbDialog", () => {
  afterEach(() => vi.clearAllMocks());

  it("列出用户的知识库", async () => {
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    expect(screen.getByText("快讯库")).toBeTruthy();
  });

  it("选库后加入内容并提示结果", async () => {
    const kb = await import("@/lib/kb");
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() =>
      expect(kb.addKbItems).toHaveBeenCalledWith("k1", [
        { source_type: "news_item", source_ref_id: "n1" },
      ]),
    );
    await waitFor(() => expect(screen.getByText(/1 条已加入/)).toBeTruthy());
  });

  it("已在库中时给出明确提示而不是报错", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.addKbItems).mockResolvedValue({ added: 0, duplicate: 1, failed: [] });
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() => expect(screen.getByText(/1 条已在库中/)).toBeTruthy());
  });

  it("部分失败时同时报出成功与失败条数", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.addKbItems).mockResolvedValue({
      added: 2, duplicate: 1, failed: [{ source_ref_id: "x", error: "快讯不存在" }],
    });
    await renderDialog({
      items: [
        { source_type: "news_item", source_ref_id: "a" },
        { source_type: "news_item", source_ref_id: "b" },
        { source_type: "news_item", source_ref_id: "c" },
        { source_type: "news_item", source_ref_id: "x" },
      ],
    });
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() => expect(screen.getByText(/2 条已加入/)).toBeTruthy());
    expect(screen.getByText(/1 条已在库中/)).toBeTruthy();
    expect(screen.getByText(/1 条失败/)).toBeTruthy();
  });

  it("新建并加入：先建库再加入新库", async () => {
    const kb = await import("@/lib/kb");
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText("新建知识库并加入"), {
      target: { value: "新库" },
    });
    fireEvent.click(screen.getByTestId("add-to-kb-create"));
    await waitFor(() => expect(kb.createKb).toHaveBeenCalledWith("新库"));
    await waitFor(() => expect(kb.addKbItems).toHaveBeenCalledWith("k9", expect.anything()));
  });

  it("mode=source 时走整号订阅接口", async () => {
    const kb = await import("@/lib/kb");
    await renderDialog({
      mode: "source",
      items: undefined,
      source: { source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号" },
    });
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() =>
      expect(kb.addKbSource).toHaveBeenCalledWith("k1", {
        source_type: "wechat_account", source_ref_id: "acc-1", display_name: "财经号",
      }),
    );
    await waitFor(() => expect(screen.getByText(/已开始同步/)).toBeTruthy());
  });

  it("配额触顶等失败原样展示后端文案", async () => {
    const kb = await import("@/lib/kb");
    vi.mocked(kb.addKbItems).mockRejectedValue(new Error("该知识库已达 2000 篇文档上限"));
    await renderDialog();
    await waitFor(() => expect(screen.getByText("研报库")).toBeTruthy());
    fireEvent.click(screen.getByText("研报库"));
    await waitFor(() => expect(screen.getByText(/2000 篇文档上限/)).toBeTruthy());
  });

  it("open=false 时不渲染", async () => {
    await renderDialog({ open: false });
    expect(screen.queryByText("研报库")).toBeNull();
  });
});
