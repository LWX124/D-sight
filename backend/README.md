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

## 积分计费（计划 3）

**账户 / 流水模型**（`app/credits/models.py`）：
- `credit_accounts`：每用户一行，`balance`（当前余额）、`plan`（`free`/`subscribed`）、
  `monthly_quota`（月度配额）、`reset_at`。
- `credit_transactions`：不可变流水，`amount` 有符号（正入负扣）、`balance_after` 记扣后余额、
  `kind ∈ {grant, reset, chat, adjust}`、`ref_type/ref_id` 溯源。余额由账户行维护、流水可审计推导。
- `admin_audit_log`：管理操作审计（`action`、`target_id`、`detail` JSON）。

**记账函数与行锁**（`app/credits/service.py`）：`ensure_account / get_balance / precheck /
grant / charge`。`grant`/`charge` 在单事务内 `SELECT ... FOR UPDATE` 锁账户行，
原子更新余额并追加流水，余额不足抛 `InsufficientCredits`。

**扣费链路**（`app/chat` 端点）：执行前 `precheck`（余额 ≤ 0 → HTTP **402**）；
执行后按本轮 `total_tokens` 经 `tokens_to_credits`（`TOKENS_PER_CREDIT` 折算，最少 `MIN_CHARGE`）
`charge(kind="chat")`。整体 `asyncio.timeout(900)`（**15 分钟**）硬超时，
`finally` 按已消耗 token 实扣——超时不逃费。

**限频**（`app/core/ratelimit.py`）：每用户固定窗口 `RATE_LIMIT_PER_MIN` 次/分钟，
基于 Redis（`REDIS_URL`，本地默认 `redis://localhost:6381/0`）。
**Redis 不可用时 fail-open**（放行，不因限频组件挂掉阻断聊天）。

**月度重置**（`app/credits/reset.py` + APScheduler）：每月初（北京时间）`reset_all_accounts`
将各账户清零后按 `plan` 重发 `monthly_quota`（免费 100 / 订阅 2000），写 `kind="reset"` 流水。

**管理 CLI**（`uv run python -m scripts.admin`）：`set-admin <email>`（赋管理员角色）、
`grant <email> <amount>`（手动补积分）。管理 API：`POST /api/admin/credits/adjust`、
`POST /api/admin/users/{id}/plan`，均经 `require_admin` 保护并写审计。

**邮件（SMTP）**：`EMAIL_BACKEND=smtp` 时用 `SMTP_*` 发验证码；`console` 时打印到日志（默认，本地/CI）。

**真实模式 skill**：Agent 启动时把 skill 资产拷入受限工作区，真实模式枚举方可命中（计划 2b/T9）。

**新增 env**（见 `.env.example`，均有默认值）：
`REDIS_URL`、`RATE_LIMIT_PER_MIN`（默认 20）、`TOKENS_PER_CREDIT`（默认 1000）、
`FREE_MONTHLY_QUOTA`（100）、`SUBSCRIBED_MONTHLY_QUOTA`（2000）、`MIN_CHARGE`（1）、
`EMAIL_BACKEND`、`SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM/SMTP_USE_TLS`。

**端到端集成测试**：`tests/test_credits_flow.py` 串起预检→充值→通过闭环：
余额扣空 → 聊天 402 → 管理员 `adjust` 补分（并断言审计行落库）→ 再聊 200 且新增 `kind="chat"` 流水。

```bash
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credits_flow.py -q
```

**CI 说明**：后端测试**不需要真实 Redis**——限频测试打桩 `_redis`，其余走 testcontainers Postgres，
聊天链路命中 `check_rate` 时 Redis 不可用即 fail-open。故 `.github/workflows/ci.yml` **未加 redis service**。
本地若要真实验证限频，需起 dev redis（`localhost:6381`，`docker compose -f ../docker-compose.dev.yml up -d`）。
