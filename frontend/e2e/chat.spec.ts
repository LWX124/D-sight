import { expect, test } from "@playwright/test";

// 注册（后端签发 token 即完成登录）→ 发消息 → 断言 FAKE_LLM 的"假回复"流式出现。
// 验证码经测试后门取得：FAKE_LLM=1 时 /api/auth/request-code 回传 debug_code。
test("注册登录并收到流式回复", async ({ page, request }) => {
  const email = `e2e-${Date.now()}@test.dev`;

  const codeResp = await request.post("http://localhost:8000/api/auth/request-code", {
    data: { email },
  });
  expect(codeResp.status()).toBe(200);
  const { debug_code } = await codeResp.json();
  expect(debug_code).toMatch(/^\d{6}$/);

  await page.goto("/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("验证码").fill(debug_code);
  await page.getByLabel("密码").fill("e2e-password-1");
  await page.getByRole("button", { name: /注册/ }).click();

  // 注册成功后落到聊天页，等 composer 就绪。
  const composer = page.getByPlaceholder("Send a message...");
  await expect(composer).toBeVisible({ timeout: 30_000 });

  // 登录后积分徽章应可见（Task 7 review gap：徽章拉取余额并渲染）。
  await expect(page.getByTestId("credit-badge")).toBeVisible({ timeout: 30_000 });

  await composer.fill("茅台现在多少钱");
  await page.keyboard.press("Enter");

  // fake 模型两轮后产出"假回复"。
  await expect(page.getByText("假回复")).toBeVisible({ timeout: 30_000 });
});
