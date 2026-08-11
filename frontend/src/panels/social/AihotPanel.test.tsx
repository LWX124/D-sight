import React from "react";
import "@testing-library/jest-dom/vitest";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

const social = vi.hoisted(() => ({
  getAihot: vi.fn(),
  getAihotItemDetail: vi.fn(),
  refreshAihot: vi.fn(),
  addBookmark: vi.fn(),
  removeBookmark: vi.fn(),
  listAihotSources: vi.fn(),
  createAihotSource: vi.fn(),
  updateAihotSource: vi.fn(),
  deleteAihotSource: vi.fn(),
  getAihotProviderStats: vi.fn(),
  searchPublishers: vi.fn(),
}));

vi.mock("@/lib/social", () => social);

const hotItem = {
  id: "hot-1",
  rank: 1,
  previous_rank: 4,
  rank_delta: 3,
  trend: "up" as const,
  window: "24h" as const,
  category: "market" as const,
  assets: ["沪深300"],
  platform: "wechat",
  content_type: "article",
  title: "市场风险偏好回升",
  digest: "资金重新评估风险资产",
  cover_url: null,
  url: "https://example.com/hot",
  published_at: "2026-08-11T02:00:00Z",
  core_metric: { label: "阅读", value: 12000, formatted_value: "1.2万" },
  publisher: { id: "publisher-1", name: "市场观察", avatar: null, platform: "wechat" },
  bookmarked: false,
};

const source = {
  id: "source-1",
  publisher_id: null,
  platform: "xiaohongshu",
  external_id: null,
  name: "金融政策",
  avatar: null,
  category: "policy",
  source_key: "金融政策",
  enabled: true,
  notes: "重点观察",
};

describe("AihotPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    social.getAihot.mockResolvedValue({
      items: [hotItem],
      run: { id: "run-1", status: "success", finished_at: "2026-08-11T03:00:00Z", items_fetched: 50 },
      status: "ok",
    });
    social.getAihotItemDetail.mockResolvedValue({
      ...hotItem,
      body_text: "完整热榜正文",
      transcript_text: null,
      enrichment: {
        status: "done",
        summary: "AI 摘要",
        category: "market",
        assets: ["沪深300"],
        is_financial: true,
        relevance_confidence: 0.98,
        model: "test-model",
        version: "v1",
      },
      metrics: [],
      rank_history: [{
        window: "24h",
        rank: 1,
        previous_rank: 4,
        rank_delta: 3,
        platform_score: 90,
        freshness_score: 80,
        momentum_score: 70,
        computed_at: "2026-08-10T03:00:00Z",
        formula_version: "v1",
      }],
      media: [],
    });
    social.refreshAihot.mockResolvedValue({ status: "accepted" });
    social.addBookmark.mockResolvedValue({ id: "bookmark-1" });
    social.removeBookmark.mockResolvedValue(undefined);
    social.listAihotSources.mockResolvedValue([source]);
    social.createAihotSource.mockResolvedValue({ id: "source-2", ok: true });
    social.updateAihotSource.mockResolvedValue({ ok: true });
    social.deleteAihotSource.mockResolvedValue({ ok: true });
    social.getAihotProviderStats.mockResolvedValue({
      days: 30,
      total_estimated_cost: 25,
      budget: 100,
      budget_warning: false,
      groups: [{
        provider: "redfox",
        platform: "xiaohongshu",
        operation: "search_items",
        calls: 10,
        errors: 1,
        error_rate: 0.1,
        avg_elapsed_ms: 250,
        estimated_cost: 25,
      }],
    });
    social.searchPublishers.mockResolvedValue([]);
  });

  it("展示混合卡片墙、趋势和核心指标，但不展示总分", async () => {
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel />);

    expect(await screen.findByText("市场风险偏好回升")).toBeTruthy();
    expect(screen.getByText("#1")).toBeTruthy();
    expect(screen.getByText(/阅读 1\.2万/)).toBeTruthy();
    expect(screen.queryByText(/总分|AIHotScore|99\.9/)).toBeNull();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByRole("button", { name: "刷新" })).toBeNull();
    expect(screen.queryByRole("button", { name: "管理信源" })).toBeNull();
    expect(social.listAihotSources).not.toHaveBeenCalled();
  });

  it("时间窗、语义分类和搜索参数会发送到统一接口", async () => {
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel />);
    await screen.findByText("市场风险偏好回升");

    fireEvent.click(screen.getByRole("button", { name: "3天" }));
    await waitFor(() => expect(social.getAihot).toHaveBeenLastCalledWith(expect.objectContaining({ window: "3d" })));
    fireEvent.click(screen.getByRole("button", { name: "公司" }));
    await waitFor(() => expect(social.getAihot).toHaveBeenLastCalledWith(expect.objectContaining({ category: "company" })));
    fireEvent.change(screen.getByLabelText("搜索 AIHot"), { target: { value: "茅台" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => expect(social.getAihot).toHaveBeenLastCalledWith(expect.objectContaining({ q: "茅台" })));
  });

  it("详情抽屉支持收藏、原文和深度分析", async () => {
    const onDeepAnalysis = vi.fn().mockResolvedValue(undefined);
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel onDeepAnalysis={onDeepAnalysis} />);

    fireEvent.click(await screen.findByRole("button", { name: /市场风险偏好回升/ }));
    expect(await screen.findByText("完整热榜正文")).toBeTruthy();
    expect(screen.getByRole("link", { name: "原文" }).getAttribute("href")).toBe("https://example.com/hot");
    fireEvent.click(screen.getByRole("button", { name: "深度分析" }));
    await waitFor(() => expect(onDeepAnalysis).toHaveBeenCalledTimes(1));
    expect(onDeepAnalysis.mock.calls[0][0]).toContain("深度分析");
  });

  it("刷新失败不会被吞掉", async () => {
    social.refreshAihot.mockRejectedValueOnce(new Error("刷新权限不足"));
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel canRefresh />);
    fireEvent.click(await screen.findByRole("button", { name: "刷新" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("刷新权限不足");
  });

  it("异步刷新被受理后明确说明继续展示旧快照", async () => {
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel canRefresh />);
    fireEvent.click(await screen.findByRole("button", { name: "刷新" }));
    expect(await screen.findByText(/刷新任务已受理/)).toBeTruthy();
  });

  it("管理员按需打开管理面板并查看 Provider 健康、成本与预算", async () => {
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel canRefresh />);
    expect(social.listAihotSources).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "管理信源" }));

    expect(await screen.findByRole("heading", { name: "信源与 Provider 运行状况" })).toBeTruthy();
    expect(await screen.findByText("金融政策")).toBeTruthy();
    expect(screen.getByText("9 / 10")).toBeTruthy();
    expect(screen.getByText("10.0%")).toBeTruthy();
    expect(screen.getByText("250 ms")).toBeTruthy();
    expect(screen.getByText(/估算成本 25\.00/)).toBeTruthy();
    expect(screen.getByText(/预算 100\.00/)).toBeTruthy();
    expect(social.getAihotProviderStats).toHaveBeenCalledWith(30);
  });

  it("管理员可添加小红书关键词，并通过搜索添加公众号账号信源", async () => {
    social.searchPublishers.mockResolvedValueOnce([{
      platform: "wechat",
      external_id: "wx-account-1",
      name: "金融公众号",
      avatar: "https://example.com/avatar.png",
      description: "长期金融研究",
      provider: "redfox",
    }]);
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel canRefresh />);
    fireEvent.click(await screen.findByRole("button", { name: "管理信源" }));

    fireEvent.change(await screen.findByLabelText("小红书采集关键词"), { target: { value: "金融监管" } });
    fireEvent.change(screen.getByLabelText("信源分类"), { target: { value: "policy" } });
    fireEvent.click(screen.getByRole("button", { name: "添加关键词" }));
    await waitFor(() => expect(social.createAihotSource).toHaveBeenLastCalledWith({
      platform: "xiaohongshu",
      source_key: "金融监管",
      category: "policy",
    }));

    fireEvent.change(screen.getByLabelText("信源类型"), { target: { value: "account" } });
    fireEvent.change(await screen.findByLabelText("搜索账号信源"), { target: { value: "金融" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索账号" }));
    expect(await screen.findByText("金融公众号")).toBeTruthy();
    expect(social.searchPublishers).toHaveBeenCalledWith("wechat", "金融");
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => expect(social.createAihotSource).toHaveBeenLastCalledWith({
      platform: "wechat",
      external_id: "wx-account-1",
      name: "金融公众号",
      avatar: "https://example.com/avatar.png",
      description: "长期金融研究",
      category: "policy",
    }));
  });

  it("管理员可停用和移除信源", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel canRefresh />);
    fireEvent.click(await screen.findByRole("button", { name: "管理信源" }));

    fireEvent.click(await screen.findByRole("button", { name: "已启用" }));
    await waitFor(() => expect(social.updateAihotSource).toHaveBeenCalledWith("source-1", { enabled: false }));
    fireEvent.click(screen.getByRole("button", { name: "移除信源 金融政策" }));
    await waitFor(() => expect(social.deleteAihotSource).toHaveBeenCalledWith("source-1"));
    expect(screen.queryByText("金融政策")).toBeNull();
    confirm.mockRestore();
  });

  it("切换账号平台后忽略上一平台的迟到搜索结果", async () => {
    let resolveSearch: (value: unknown[]) => void = () => undefined;
    social.searchPublishers.mockReturnValueOnce(new Promise((resolve) => {
      resolveSearch = resolve;
    }));
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel canRefresh />);
    fireEvent.click(await screen.findByRole("button", { name: "管理信源" }));
    fireEvent.change(screen.getByLabelText("信源类型"), { target: { value: "account" } });
    fireEvent.change(await screen.findByLabelText("搜索账号信源"), { target: { value: "金融" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索账号" }));
    fireEvent.change(screen.getByLabelText("账号平台"), { target: { value: "bilibili" } });

    await act(async () => {
      resolveSearch([{
        platform: "wechat",
        external_id: "late-wechat",
        name: "迟到的公众号结果",
        avatar: null,
        description: null,
        provider: "redfox",
      }]);
    });

    await waitFor(() => expect(social.searchPublishers).toHaveBeenCalledWith("wechat", "金融"));
    expect(screen.queryByText("迟到的公众号结果")).toBeNull();
  });

  it("管理员权限失效或管理 API 失败时显式告警", async () => {
    social.listAihotSources.mockRejectedValueOnce(new Error("仅管理员可访问（HTTP 403）"));
    const { default: AihotPanel } = await import("./AihotPanel");
    render(<AihotPanel canRefresh />);
    fireEvent.click(await screen.findByRole("button", { name: "管理信源" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("仅管理员可访问（HTTP 403）");
  });

  it("角色降级后立即卸载管理面板且不再展示管理入口", async () => {
    const { default: AihotPanel } = await import("./AihotPanel");
    const { rerender } = render(<AihotPanel canRefresh />);
    fireEvent.click(await screen.findByRole("button", { name: "管理信源" }));
    expect(await screen.findByRole("heading", { name: "信源与 Provider 运行状况" })).toBeTruthy();

    rerender(<AihotPanel canRefresh={false} />);

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "信源与 Provider 运行状况" })).toBeNull();
    });
    expect(screen.queryByRole("button", { name: "管理信源" })).toBeNull();
  });
});
