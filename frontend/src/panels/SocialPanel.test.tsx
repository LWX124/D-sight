import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const social = vi.hoisted(() => ({
  getFeed: vi.fn(),
  listUnifiedSubscriptions: vi.fn(),
  listBookmarks: vi.fn(),
  searchPublishers: vi.fn(),
  addUnifiedSubscription: vi.fn(),
  removeUnifiedSubscription: vi.fn(),
  refreshPublisher: vi.fn(),
  addBookmark: vi.fn(),
  removeBookmark: vi.fn(),
  getSocialItemDetail: vi.fn(),
  getWeiboCredential: vi.fn(),
  previewWeiboAccount: vi.fn(),
  subscribeWeibo: vi.fn(),
  listCredentials: vi.fn(),
  startLoginQrcode: vi.fn(),
  pollLoginStatus: vi.fn(),
  searchAccounts: vi.fn(),
  subscribe: vi.fn(),
}));

vi.mock("@/lib/social", () => social);

const subscription = {
  id: "sub-1",
  publisher_id: "publisher-1",
  platform: "wechat",
  external_id: "wx-1",
  name: "价值研究所",
  avatar: null,
  enabled: true,
};

const item = {
  id: "item-1",
  platform: "wechat",
  external_id: "article-1",
  content_type: "article",
  title: "利率变化与市场定价",
  digest: "这是一段摘要",
  cover_url: null,
  url: "https://example.com/article",
  published_at: "2026-08-11T02:00:00Z",
  publisher: { id: "publisher-1", name: "价值研究所", avatar: null, platform: "wechat" },
};

const olderItem = {
  ...item,
  id: "item-2",
  external_id: "article-2",
  title: "上一页的市场观察",
  published_at: "2026-08-10T02:00:00Z",
};

const bookmark = {
  id: "bookmark-1",
  item_id: item.id,
  platform: item.platform,
  title: item.title,
  digest: item.digest,
  cover_url: item.cover_url,
  url: item.url,
  published_at: item.published_at,
  publisher: item.publisher,
  notes: null,
  created_at: "2026-08-11T03:00:00Z",
  body_text: "收藏时保留的正文",
  transcript_text: null,
};

describe("SocialPanel 统一订阅动态", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    social.getFeed.mockResolvedValue({ items: [item], next_before: null });
    social.listUnifiedSubscriptions.mockResolvedValue([subscription]);
    social.listBookmarks.mockResolvedValue([]);
    social.searchPublishers.mockResolvedValue([]);
    social.addUnifiedSubscription.mockResolvedValue(subscription);
    social.removeUnifiedSubscription.mockResolvedValue(undefined);
    social.refreshPublisher.mockResolvedValue({ ok: true });
    social.addBookmark.mockResolvedValue({ id: "bookmark-1" });
    social.removeBookmark.mockResolvedValue(undefined);
    social.getSocialItemDetail.mockResolvedValue({
      ...item,
      body_text: "完整正文",
      transcript_text: null,
      media: [],
      bookmarked: false,
    });
    social.getWeiboCredential.mockResolvedValue({ configured: true, status: "active" });
    social.previewWeiboAccount.mockResolvedValue({
      account_id: "weibo-account-1",
      uid: "1234567890",
      name: "微博研究员",
      avatar: null,
      description: "宏观与公司研究",
      profile_url: "https://weibo.com/u/1234567890",
    });
    social.subscribeWeibo.mockResolvedValue({
      subscription: {},
      initial_sync_status: "success",
      added: 3,
    });
    social.listCredentials.mockResolvedValue([]);
    social.startLoginQrcode.mockResolvedValue({ login_session: "login-1", qrcode: "data:image/png;base64,abc" });
    social.pollLoginStatus.mockResolvedValue({ status: "expired", nickname: null });
    social.searchAccounts.mockResolvedValue([]);
    social.subscribe.mockResolvedValue({});
  });

  it("只展示统一订阅动态，不再出现内部 AIHot Tab", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByText("AIHot")).toBeNull();
    expect(await screen.findByText("利率变化与市场定价")).toBeTruthy();
    expect(screen.getAllByText("价值研究所").length).toBeGreaterThan(0);
  });

  it("再次点击已选发布者会取消筛选", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);
    const publisher = await screen.findByRole("button", { pressed: false, name: /价值研究所/ });

    fireEvent.click(publisher);
    await waitFor(() => {
      expect(social.getFeed).toHaveBeenLastCalledWith({ publisher_id: "publisher-1", limit: 50 });
    });
    fireEvent.click(publisher);
    await waitFor(() => {
      expect(social.getFeed).toHaveBeenLastCalledWith({ publisher_id: undefined, limit: 50 });
    });
  });

  it("使用服务端游标加载更多动态", async () => {
    social.getFeed
      .mockResolvedValueOnce({ items: [item], next_before: "cursor-1" })
      .mockResolvedValueOnce({ items: [olderItem], next_before: null });
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "加载更多" }));

    expect(await screen.findByText("上一页的市场观察")).toBeTruthy();
    expect(social.getFeed).toHaveBeenLastCalledWith({
      publisher_id: undefined,
      before: "cursor-1",
      limit: 50,
    });
    expect(screen.queryByRole("button", { name: "加载更多" })).toBeNull();
  });

  it("取消订阅后会立即从当前时间流移除内容", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);
    expect(await screen.findByText("利率变化与市场定价")).toBeTruthy();
    social.getFeed.mockResolvedValueOnce({ items: [], next_before: null });

    fireEvent.click(screen.getByRole("button", { name: "取消订阅 价值研究所" }));

    await waitFor(() => expect(social.removeUnifiedSubscription).toHaveBeenCalledWith("sub-1"));
    await waitFor(() => expect(screen.queryByText("利率变化与市场定价")).toBeNull());
    expect(social.getFeed).toHaveBeenLastCalledWith({ publisher_id: undefined, limit: 50 });
  });

  it("刷新与收藏失败会显示给用户", async () => {
    social.refreshPublisher.mockRejectedValueOnce(new Error("刷新冷却中"));
    social.addBookmark.mockRejectedValueOnce(new Error("收藏失败"));
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    fireEvent.click(await screen.findByRole("button", { pressed: false, name: /价值研究所/ }));
    fireEvent.click(await screen.findByRole("button", { name: "刷新账号" }));
    expect(await screen.findByText("刷新冷却中")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "收藏" }));
    expect(await screen.findByText("收藏失败")).toBeTruthy();
  });

  it("详情抽屉可发送到现有对话入口", async () => {
    const onSendToChat = vi.fn().mockResolvedValue(undefined);
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel onSendToChat={onSendToChat} />);

    fireEvent.click(await screen.findByRole("button", { name: /利率变化与市场定价/ }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
    await screen.findByText("完整正文");
    fireEvent.click(screen.getByRole("button", { name: "发送到对话" }));

    await waitFor(() => expect(onSendToChat).toHaveBeenCalledTimes(1));
    expect(onSendToChat.mock.calls[0][0]).toContain("完整正文");
  });

  it("收藏历史支持打开详情、深度分析和取消收藏", async () => {
    const onDeepAnalysis = vi.fn().mockResolvedValue(undefined);
    social.listBookmarks.mockResolvedValueOnce([bookmark]);
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel onDeepAnalysis={onDeepAnalysis} />);

    const history = await screen.findByRole("button", { name: /收藏历史 1/ });
    fireEvent.click(history);
    fireEvent.click(await screen.findByRole("button", { name: /利率变化与市场定价/ }));
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "深度分析" }));
    await waitFor(() => expect(onDeepAnalysis).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "收藏历史 1" }));
    fireEvent.click(await screen.findByRole("button", { name: "已收藏" }));
    await waitFor(() => expect(social.removeBookmark).toHaveBeenCalledWith(item.id));
    expect(screen.queryByText("利率变化与市场定价")).toBeNull();
  });

  it("微博主页预览通过 legacy 入口原子接入统一订阅", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    fireEvent.change(screen.getByLabelText("选择平台"), { target: { value: "weibo" } });
    fireEvent.change(await screen.findByLabelText("微博主页链接"), {
      target: { value: "https://weibo.com/u/1234567890" },
    });
    fireEvent.click(screen.getByRole("button", { name: "预览账号" }));
    expect(await screen.findByText("微博研究员")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认订阅" }));

    await waitFor(() => expect(social.subscribeWeibo).toHaveBeenCalledWith("weibo-account-1"));
    expect(social.addUnifiedSubscription).not.toHaveBeenCalled();
    expect(await screen.findByText(/微博订阅已接入/)).toBeTruthy();
  });

  it("微信 RedFox 不可用时可走扫码凭据备用搜索入口", async () => {
    social.searchAccounts.mockResolvedValueOnce([{
      fakeid: "legacy-wx-1",
      nickname: "备用公众号",
      avatar: null,
      signature: "长期研究",
    }]);
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    fireEvent.click(screen.getByRole("button", { name: /扫码备用/ }));
    fireEvent.change(await screen.findByLabelText("备用搜索公众号"), { target: { value: "研究" } });
    fireEvent.click(screen.getByRole("button", { name: "备用搜索" }));
    expect(await screen.findByText("备用公众号")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "接入" }));

    await waitFor(() => expect(social.subscribe).toHaveBeenCalledWith({
      fakeid: "legacy-wx-1",
      name: "备用公众号",
      avatar: null,
    }));
    expect(social.addUnifiedSubscription).not.toHaveBeenCalled();
    expect(await screen.findByText(/已通过扫码备用链路接入/)).toBeTruthy();
  });

  it("微信备用入口可生成二维码并显示终态", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    fireEvent.click(screen.getByRole("button", { name: /扫码备用/ }));
    fireEvent.click(await screen.findByRole("button", { name: "生成登录二维码" }));

    expect(await screen.findByRole("img", { name: "公众号登录二维码" })).toBeTruthy();
    expect(await screen.findByText("二维码已过期，请重新生成")).toBeTruthy();
    expect(social.startLoginQrcode).toHaveBeenCalledTimes(1);
    expect(social.pollLoginStatus).toHaveBeenCalledWith("login-1");
  });

  it("legacy 原子订阅失败会显式展示，且不会补发 unified 请求", async () => {
    social.searchAccounts.mockResolvedValueOnce([{
      fakeid: "legacy-wx-2",
      nickname: "失败公众号",
      avatar: null,
      signature: null,
    }]);
    social.subscribe.mockRejectedValueOnce(new Error("订阅事务失败"));
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    fireEvent.click(screen.getByRole("button", { name: /扫码备用/ }));
    fireEvent.change(await screen.findByLabelText("备用搜索公众号"), { target: { value: "失败" } });
    fireEvent.click(screen.getByRole("button", { name: "备用搜索" }));
    fireEvent.click(await screen.findByRole("button", { name: "接入" }));

    expect((await screen.findByRole("alert")).textContent).toContain("订阅事务失败");
    expect(social.addUnifiedSubscription).not.toHaveBeenCalled();
  });

  it("小红书账号订阅能力缺失时明确降级，不伪装成功", async () => {
    social.searchPublishers.mockResolvedValueOnce([{
      platform: "xiaohongshu",
      external_id: "xhs-1",
      name: "小红书财经号",
      avatar: null,
      description: null,
      provider: "redfox",
    }]);
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    fireEvent.change(screen.getByLabelText("选择平台"), { target: { value: "xiaohongshu" } });
    expect(screen.getByText(/仅支持关键词搜索发现/)).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("搜索并添加发布者…"), { target: { value: "财经" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    const degraded = await screen.findByRole("button", { name: "仅搜索发现" });
    expect(degraded.hasAttribute("disabled")).toBe(true);
    expect(social.addUnifiedSubscription).not.toHaveBeenCalled();
  });
});
