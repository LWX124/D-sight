import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";

vi.mock("@/lib/social", () => ({
  listCredentials: vi.fn(async () => []),
  listSubscriptions: vi.fn(async () => [{ id: "s1", account_id: "acc-1", fakeid: "F1", name: "测试公众号", avatar: null, enabled: true }]),
  searchAccounts: vi.fn(async () => []),
  subscribe: vi.fn(),
  listArticles: vi.fn(async () => []),
  getArticle: vi.fn(),
  refreshAccount: vi.fn(),
  startLoginQrcode: vi.fn(),
  pollLoginStatus: vi.fn(),
}));

describe("SocialPanel 渲染", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("顶部有信源 Tab 栏，微信公众号为当前激活 Tab", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);
    const tab = screen.getByRole("tab", { name: "微信公众号" });
    expect(tab).toBeTruthy();
    expect(tab.getAttribute("aria-selected")).toBe("true");
  });

  it("加载订阅列表并展示公众号名称", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);
    expect(screen.getByText("公众号登录")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText("测试公众号")).toBeTruthy();
    });
  });

  it("扫码后的每种登录状态都有可见反馈（scanned/no_account）", async () => {
    vi.useFakeTimers();
    const social = await import("@/lib/social");
    vi.mocked(social.startLoginQrcode).mockResolvedValue({
      login_session: "S1",
      qrcode: "data:image/jpg;base64,xx",
    });
    const poll = vi.mocked(social.pollLoginStatus);
    poll.mockResolvedValueOnce({ status: "scanned", nickname: null });
    poll.mockResolvedValueOnce({ status: "no_account", nickname: null });

    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);
    fireEvent.click(screen.getByText("扫码登录公众号"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByText(/已扫码/)).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByText(/没有可登录的公众号/)).toBeTruthy();
    vi.useRealTimers();
  });

  it("已有有效凭证时不显示扫码登录按钮，只显示登录状态", async () => {
    const social = await import("@/lib/social");
    vi.mocked(social.listCredentials).mockResolvedValueOnce([
      { id: "c1", nickname: "我的号", avatar: null, status: "active", expires_at: "2026-08-01" },
    ]);

    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    await waitFor(() => {
      expect(screen.getByText("我的号")).toBeTruthy();
    });
    expect(screen.queryByText("扫码登录公众号")).toBeNull();
  });

  it("接口失败时展示错误信息而不是静默失败", async () => {
    const social = await import("@/lib/social");
    vi.mocked(social.listArticles).mockRejectedValueOnce(new Error("HTTP 409"));

    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);

    await waitFor(() => {
      expect(screen.getByText("测试公众号")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("测试公众号"));

    await waitFor(() => {
      expect(screen.getByText(/HTTP 409/)).toBeTruthy();
    });
  });
});
