import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    // /api 代理到后端；端口默认 8000，可用 BACKEND_PORT 覆盖（与 dev.sh 一致）。
    proxy: {
      "/api": {
        target: `http://localhost:${process.env.BACKEND_PORT ?? 8010}`,
        changeOrigin: false,
      },
    },
  },
  // @ts-expect-error vitest 扩展字段
  test: {
    environment: "jsdom",
    globals: true,
    // 只跑 src 下的单测；e2e/ 是 Playwright 用例，由 `npx playwright test` 单独跑。
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
