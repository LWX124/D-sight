import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as social from "@/lib/social";

vi.mock("@/lib/social", () => ({
  getWeiboCredential: vi.fn(async () => ({
    configured: true,
    status: "blocked",
    weibo_uid: "1",
    nickname: "专用账号",
    avatar: null,
    last_verified_at: "2026-08-06T00:00:00Z",
    blocked_until: "2026-08-07T00:00:00Z",
    last_error: "HTTP 432",
    can_manage: true,
  })),
  listWeiboSubscriptions: vi.fn(async () => []),
  previewWeiboAccount: vi.fn(async () => ({
    account_id: "a1", uid: "123456", name: "测试微博账号", avatar: null,
    description: "账号简介", profile_url: "https://weibo.com/u/123456",
  })),
  subscribeWeibo: vi.fn(async () => ({
    subscription: { account_id: "a1" }, initial_sync_status: "ok", added: 3,
  })),
  listWeiboPosts: vi.fn(async () => []),
  refreshWeiboAccount: vi.fn(async () => ({ added: 0 })),
  unsubscribeWeibo: vi.fn(),
  saveWeiboCredential: vi.fn(),
  deleteWeiboCredential: vi.fn(),
}));

describe("WeiboTab", () => {
  afterEach(() => vi.clearAllMocks());

  it("展示风控状态、管理员凭证入口和空状态", async () => {
    const { default: WeiboTab } = await import("./WeiboTab");
    render(<WeiboTab />);
    await waitFor(() => expect(screen.getByText(/微博触发风控/)).toBeTruthy());
    expect(screen.getByLabelText("微博 Cookie")).toBeTruthy();
    expect(screen.getByText("还没有订阅微博账号")).toBeTruthy();
    expect(screen.getByText("HTTP 432")).toBeTruthy();
  });

  it("粘贴主页链接后预览昵称与 UID，再确认订阅", async () => {
    const { default: WeiboTab } = await import("./WeiboTab");
    render(<WeiboTab />);
    fireEvent.change(screen.getByPlaceholderText("粘贴微博主页链接"), {
      target: { value: "https://weibo.com/u/123456" },
    });
    fireEvent.click(screen.getByText("预览账号"));
    await waitFor(() => expect(screen.getByText("测试微博账号")).toBeTruthy());
    expect(screen.getByText("UID 123456")).toBeTruthy();
    fireEvent.click(screen.getByText("确认订阅"));
    await waitFor(() => expect(screen.getByText(/首次获取 3 条/)).toBeTruthy());
  });

  it("展示所选账号的同步错误而不是吞成空状态", async () => {
    vi.mocked(social.listWeiboSubscriptions).mockResolvedValueOnce([{
      id: "s1",
      account_id: "a1",
      uid: "123456",
      name: "异常账号",
      avatar: null,
      description: null,
      profile_url: "https://weibo.com/u/123456",
      enabled: true,
      last_synced_at: null,
      last_sync_status: "error",
      last_sync_error: "微博内容暂时获取失败",
    }]);
    const { default: WeiboTab } = await import("./WeiboTab");
    render(<WeiboTab />);
    await waitFor(() => expect(screen.getByText("异常账号")).toBeTruthy());
    fireEvent.click(screen.getByText("异常账号"));
    await waitFor(() => expect(screen.getByText(/最近同步失败：微博内容暂时获取失败/)).toBeTruthy());
  });
});
