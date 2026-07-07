import { defineConfig } from "@playwright/test";

// E2E 冒烟：始终跑在 FAKE_LLM=1（确定性、免费）下。真实模型冒烟为一次性人工验证，不进此套件。
// 需要本机 dev postgres（localhost:5434）已起：docker compose -f ../docker-compose.dev.yml up -d
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  webServer: [
    {
      // 后端：先迁移再以 FAKE_LLM=1 起 uvicorn（env 覆盖 .env 里的 FAKE_LLM=0）。
      command:
        "uv run alembic upgrade head && FAKE_LLM=1 uv run uvicorn app.main:create_app --factory --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/healthz",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // 前端 dev server（vite 代理 /api → :8000）。
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
