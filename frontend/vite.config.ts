import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } },
  },
  // @ts-expect-error vitest 扩展字段
  test: {
    environment: "jsdom",
    globals: true,
    // 只跑 src 下的单测；e2e/ 是 Playwright 用例，由 `npx playwright test` 单独跑。
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
