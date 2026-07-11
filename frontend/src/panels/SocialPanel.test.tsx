import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

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
  it("加载订阅列表并展示公众号名称", async () => {
    const { default: SocialPanel } = await import("./SocialPanel");
    render(<SocialPanel />);
    expect(screen.getByText("公众号登录")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText("测试公众号")).toBeTruthy();
    });
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
