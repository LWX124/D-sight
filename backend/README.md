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
