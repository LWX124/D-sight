# D-sight backend

## 本地开发

1. 起依赖：`docker compose -f ../docker-compose.dev.yml up -d`
   - 本机端口已重映射：Postgres 走 `localhost:5434`、Redis 走 `localhost:6381`（见 `../docker-compose.dev.yml`）。
2. 配置：`cp .env.example .env`（本地默认值即可跑通，`DATABASE_URL` 已指向 5434 端口）
3. 迁移：`uv run alembic upgrade head`
4. 启动：`uv run uvicorn app.main:create_app --factory --reload --port 8000`
5. 测试：`uv run pytest`（需要 Docker，testcontainers 起独立 Postgres）
   - 本机若遇 testcontainers Ryuk 端口 flake，改用 `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest`。

## 结构

app/core（配置/DB/安全原语） · app/auth（注册登录 JWT） · app/threads（会话 CRUD）
聊天链路（agent/流式端点）见计划 2b。

## 聊天链路（2b）

**FAKE_LLM 开关**（`app/core/config.py`，默认 `0`）：置 `1` 时用脚本化假模型
（首轮调 `stock_quote`、次轮产出「假回复」），全程离线、确定、免费——用于测试与 E2E。
另附**测试后门**：`FAKE_LLM=1` 时 `POST /api/auth/request-code` 直接回传
`{"debug_code": "<6位验证码>"}`（正常模式恒为 204 无体，绝不泄漏验证码），
供无邮箱的 E2E 取码。

**前端启动**（`../frontend`）：`npm install` 后 `npm run dev`（默认 5173，vite 代理 `/api` → 后端 8000）。
后端仍按上文 `uv run uvicorn app.main:create_app --factory --reload --port 8000` 起。

**E2E 冒烟**（Playwright，只在本地跑，不进 CI）：

```bash
cd ../frontend
npx playwright install chromium   # 首次
npx playwright test               # 注册→发消息→断言「假回复」流式出现
```

`playwright.config.ts` 的 `webServer` 会自动以 `FAKE_LLM=1` 起后端 + 前端 dev server，
但**需本机 dev postgres（localhost:5434）在跑**：`docker compose -f ../docker-compose.dev.yml up -d`。

**真实模型所需 env**（`.env`）：`FAKE_LLM=0`、有效 `DEEPSEEK_API_KEY`
（模型 `DEEPSEEK_MODEL` 须在白名单 `deepseek-v4-flash|deepseek-v4-pro`）、
联网检索用 `BOCHA_API_KEY`。真实模型冒烟（会产生少量真实费用）默认跳过，
需显式开启：`RUN_REAL_SMOKE=1 uv run pytest tests/test_real_smoke.py -s`。
