# 骨架 2a：后端基座与认证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭起生产后端基座（FastAPI + Postgres + Alembic + Docker Compose 开发环境）并交付完整的邮箱认证（验证码注册、登录、JWT access/refresh、吊销）与会话 CRUD。

**Architecture:** 模块化单体（spec §2）：`backend/app` 按领域分包（core/auth/threads），SQLAlchemy 2 async + Alembic 迁移，测试用 testcontainers 起真 Postgres。认证按 spec §7.1：bcrypt、access 15 分钟 + refresh 30 天（httpOnly cookie、jti 入库可吊销）、`user_identities` 解耦登录方式为微信 OAuth 预留。

**Tech Stack:** Python 3.12、uv、FastAPI、SQLAlchemy 2 (asyncpg)、Alembic、PyJWT、bcrypt、pydantic-settings、pytest + testcontainers、ruff

**对应 spec：** `docs/superpowers/specs/2026-07-06-d-sight-design.md` §2/§7.1/§7.3（role 字段）/§9（CI）/§10 步骤 2 前半。聊天链路（agent 移植、assistant-stream、前端）在计划 2b；PoC 的 7 条实战输入（`poc/eval/results-2026-07-06.md` 末节）全部由 2b 吸收，2a 无 agent 相关内容。

## Global Constraints

- Python 3.12，uv 管理依赖，`backend/uv.lock` 提交进 git
- 密钥只放 `backend/.env`（gitignore），提交 `backend/.env.example`
- JWT：access 15 分钟 + refresh 30 天，refresh 走 httpOnly cookie 且 jti 入库可吊销（spec §7.1 原文）
- `users` 表预留 `wechat_openid`/`wechat_unionid` 可空列 + `role`（user/admin）；登录方式解耦到 `user_identities`（spec §7.1/§7.3）
- Postgres 镜像用 `pgvector/pgvector:pg16`（为计划 4 向量检索预留；本计划不启用扩展）
- 所有新代码在 `backend/` 与仓库根的 compose/CI 文件内；`poc/` 不改动
- **commit 授权沿用既定模式**：在专属分支（如 `skeleton-2a`）上本地 commit，绝不 push；执行开始前向用户确认一次
- 错误响应统一 FastAPI HTTPException JSON（`{"detail": ...}`），中文 detail

---

### Task 1: 后端脚手架 + 开发环境

**Files:**
- Create: `backend/pyproject.toml`（uv 生成）、`backend/.env.example`、`backend/.gitignore`、`backend/app/__init__.py`、`backend/app/main.py`、`backend/app/core/__init__.py`、`backend/app/core/config.py`、`docker-compose.dev.yml`（仓库根）
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces:
  - `create_app() -> FastAPI`（`app.main`），`GET /healthz` → `{"status": "ok"}`
  - `get_settings() -> Settings`（`app.core.config`，lru_cache）：字段 `database_url`、`jwt_secret`、`jwt_refresh_secret`、`access_token_ttl_min=15`、`refresh_token_ttl_days=30`、`email_backend="console"`
  - 开发环境：`docker compose -f docker-compose.dev.yml up -d` 起 postgres(5432)/redis(6379)

- [ ] **Step 1: 初始化项目与依赖**

```bash
cd /Users/weixi1/Documents/mine/D-sight
uv init --bare backend --python 3.12
cd backend
uv add fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings pyjwt bcrypt "pydantic[email]"
uv add --dev pytest pytest-asyncio httpx "testcontainers[postgres]" ruff
mkdir -p app/core tests
touch app/__init__.py app/core/__init__.py
```

`backend/.gitignore`：

```
.env
__pycache__/
.venv/
.pytest_cache/
.ruff_cache/
```

`backend/.env.example`：

```bash
DATABASE_URL=postgresql+asyncpg://dsight:dsight@localhost:5434/dsight
JWT_SECRET=change-me
JWT_REFRESH_SECRET=change-me-too
EMAIL_BACKEND=console
```

在 `backend/pyproject.toml` 末尾追加：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: docker-compose.dev.yml（仓库根）**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: dsight
      POSTGRES_PASSWORD: dsight
      POSTGRES_DB: dsight
    ports:
      - "5434:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
  redis:
    image: redis:7-alpine
    ports:
      - "6381:6379"

volumes:
  pgdata:
```

- [ ] **Step 3: 写失败测试**

`backend/tests/test_health.py`：

```python
from httpx import ASGITransport, AsyncClient


async def test_healthz():
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL（ModuleNotFoundError: app.main）

- [ ] **Step 4: 实现 config 与 app 工厂**

`backend/app/core/config.py`：

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://dsight:dsight@localhost:5434/dsight"
    jwt_secret: str = "dev-secret"
    jwt_refresh_secret: str = "dev-refresh-secret"
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 30
    email_backend: str = "console"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`backend/app/main.py`：

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="D-sight API")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: 测试通过 + lint**

Run: `uv run pytest tests/test_health.py -v && uv run ruff check .`
Expected: 1 passed；ruff 无告警

- [ ] **Step 6: Commit（需用户已授权）**

```bash
git add backend/ docker-compose.dev.yml
git commit -m "feat(backend): scaffold FastAPI app with dev compose"
```

---

### Task 2: 数据库基座 + Alembic + 测试夹具

**Files:**
- Create: `backend/app/core/db.py`、`backend/alembic.ini` + `backend/alembic/`（alembic 生成）、`backend/tests/conftest.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Produces:
  - `Base`（DeclarativeBase）、`get_engine()`（lru_cache）、`get_sessionmaker()`、FastAPI 依赖 `get_db()`（`app.core.db`）
  - 测试夹具：session 级 testcontainers Postgres（自动设 `DATABASE_URL` 环境变量并跑 `alembic upgrade head`）、`client` 夹具（ASGI AsyncClient）、`db_session` 夹具
  - 约定：后续所有 models 模块必须在 `alembic/env.py` 中 import，否则 autogenerate 看不到

- [ ] **Step 1: 实现 db.py**

`backend/app/core/db.py`：

```python
from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    return create_async_engine(get_settings().database_url)


def get_sessionmaker():
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db():
    async with get_sessionmaker()() as session:
        yield session
```

- [ ] **Step 2: 初始化 Alembic（async 模板）**

```bash
cd backend && uv run alembic init -t async alembic
```

修改 `backend/alembic/env.py`：在 `config = context.config` 之后加：

```python
import os

from app.core.db import Base

if os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
target_metadata = Base.metadata
```

（生成模板里原有的 `target_metadata = None` 删除；`alembic.ini` 的 `sqlalchemy.url` 留空占位，实际值来自环境变量或 .env。）

修改 `backend/alembic/env.py` 顶部再加 `from dotenv import load_dotenv` 不需要——统一约定：本地跑迁移前 `export DATABASE_URL=...` 或使用 compose 默认值。为免遗忘，在 `alembic.ini` 设：

```ini
sqlalchemy.url = postgresql+asyncpg://dsight:dsight@localhost:5434/dsight
```

（环境变量存在时覆盖它。）

- [ ] **Step 3: 写测试夹具与失败测试**

`backend/tests/conftest.py`：

```python
import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _database():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = url
        os.environ["JWT_SECRET"] = "test-secret"
        os.environ["JWT_REFRESH_SECRET"] = "test-refresh-secret"
        os.environ["EMAIL_BACKEND"] = "console"
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            check=True,
            env=os.environ.copy(),
        )
        yield


@pytest_asyncio.fixture
async def client():
    from app.main import create_app

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://t"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db_session():
    from app.core.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        yield session
```

注意：`get_settings`/`get_engine` 是 lru_cache，夹具在任何 app import 之前设好环境变量（session 级 autouse 保证顺序）。`test_health.py` 不依赖数据库但会被同一夹具覆盖，无害。

`backend/tests/test_db.py`：

```python
from sqlalchemy import text


async def test_db_roundtrip(db_session):
    assert (await db_session.execute(text("select 1"))).scalar() == 1
```

Run: `uv run pytest tests/test_db.py -v`
Expected: 先见容器拉起（首次较慢），然后 PASS（若 FAIL，多为 Docker 未启动——报告并停）

- [ ] **Step 4: 全量测试 + Commit（需用户已授权）**

Run: `uv run pytest -q` → 2 passed

```bash
git add backend/
git commit -m "feat(backend): async SQLAlchemy base, alembic, testcontainers fixtures"
```

---

### Task 3: 安全原语（密码哈希 + JWT）

**Files:**
- Create: `backend/app/core/security.py`
- Test: `backend/tests/test_security.py`

**Interfaces:**
- Produces（`app.core.security`，后续任务按此签名调用）:
  - `hash_password(password: str) -> str` / `verify_password(password: str, password_hash: str) -> bool`
  - `create_access_token(user_id: str) -> str`（HS256，type=access，15 分钟）
  - `create_refresh_token(user_id: str) -> tuple[str, str, datetime]` 返回 `(token, jti, expires_at)`
  - `decode_token(token: str, *, refresh: bool = False) -> dict`，无效/过期/类型不符抛 `jwt.InvalidTokenError`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_security.py`：

```python
import datetime as dt

import jwt
import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h)
    assert not verify_password("wrong", h)


def test_access_token_roundtrip():
    token = create_access_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"


def test_refresh_token_has_jti_and_expiry():
    token, jti, expires = create_refresh_token("user-123")
    payload = decode_token(token, refresh=True)
    assert payload["jti"] == jti
    assert len(jti) == 32
    assert expires > dt.datetime.now(dt.UTC) + dt.timedelta(days=29)


def test_token_type_mismatch_rejected():
    access = create_access_token("u")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(access, refresh=True)


def test_forged_token_rejected():
    forged = jwt.encode({"sub": "u", "type": "access"}, "other-secret", algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(forged)
```

Run: `uv run pytest tests/test_security.py -v`
Expected: FAIL（ModuleNotFoundError: app.core.security）

- [ ] **Step 2: 实现**

`backend/app/core/security.py`：

```python
import datetime as dt
import uuid

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + dt.timedelta(minutes=s.access_token_ttl_min),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def create_refresh_token(user_id: str) -> tuple[str, str, dt.datetime]:
    """返回 (token, jti, expires_at)；jti 由调用方入库用于吊销。"""
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    jti = uuid.uuid4().hex
    expires = now + dt.timedelta(days=s.refresh_token_ttl_days)
    payload = {"sub": user_id, "type": "refresh", "jti": jti, "iat": now, "exp": expires}
    return jwt.encode(payload, s.jwt_refresh_secret, algorithm="HS256"), jti, expires


def decode_token(token: str, *, refresh: bool = False) -> dict:
    s = get_settings()
    secret = s.jwt_refresh_secret if refresh else s.jwt_secret
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    expected = "refresh" if refresh else "access"
    if payload.get("type") != expected:
        raise jwt.InvalidTokenError(f"token type 应为 {expected}")
    return payload
```

- [ ] **Step 3: 测试通过 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_security.py -v` → 5 passed

```bash
git add backend/app/core/security.py backend/tests/test_security.py
git commit -m "feat(backend): password hashing and JWT primitives"
```

---

### Task 4: 认证数据模型 + 迁移 + 验证码服务

**Files:**
- Create: `backend/app/auth/__init__.py`、`backend/app/auth/models.py`、`backend/app/auth/emailer.py`、`backend/app/auth/service.py`、`backend/alembic/versions/<自动生成>_auth_tables.py`
- Modify: `backend/alembic/env.py`（import models）
- Test: `backend/tests/test_auth_service.py`

**Interfaces:**
- Consumes: Task 2 `Base`/`get_sessionmaker`、Task 3 `hash_password`
- Produces:
  - models（`app.auth.models`）：`User(id: UUID, email, password_hash, role="user", wechat_openid?, wechat_unionid?, created_at)`、`UserIdentity(id, user_id, provider, provider_uid, created_at)`（provider+provider_uid 唯一）、`VerificationCode(id, email, code, purpose="register", expires_at, consumed_at?, created_at)`、`RefreshToken(jti: str pk, user_id, expires_at, revoked_at?, created_at)`
  - service（`app.auth.service`）：
    - `class AuthError(Exception)`，属性 `status: int`、`detail: str`
    - `request_code(db, email: str) -> None`（60 秒内重复请求抛 AuthError 429）
    - `register(db, email: str, code: str, password: str) -> User`（已注册 409；码错/过期/已用 400）
    - `login(db, email: str, password: str) -> User`（401）
  - emailer（`app.auth.emailer`）：`get_email_sender() -> EmailSender`（Protocol：`async send(to, subject, body)`），console 实现打印到 stdout

- [ ] **Step 1: 实现 models**

`backend/app/auth/models.py`：

```python
import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    wechat_openid: Mapped[str | None] = mapped_column(String(64))
    wechat_unionid: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_uid"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))  # email / wechat（预留）
    provider_uid: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(6))
    purpose: Mapped[str] = mapped_column(String(16), default="register", server_default="register")
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

在 `backend/alembic/env.py` 的 `target_metadata = Base.metadata` 之前加：

```python
from app.auth import models as auth_models  # noqa: F401
```

- [ ] **Step 2: 生成并检查迁移**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://dsight:dsight@localhost:5434/dsight uv run alembic revision --autogenerate -m "auth tables"
```

（需要 `docker compose -f ../docker-compose.dev.yml up -d postgres` 已运行。）
打开生成的 versions 文件确认包含 4 张表且无多余 drop；然后 `uv run alembic upgrade head` 验证可执行。

- [ ] **Step 3: 实现 emailer**

`backend/app/auth/emailer.py`：

```python
from typing import Protocol


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    """开发/测试用：验证码打到 stdout，不发真实邮件。SMTP 实现在部署阶段按 spec §7.1 接入。"""

    async def send(self, to: str, subject: str, body: str) -> None:
        print(f"[email → {to}] {subject}: {body}")


def get_email_sender() -> EmailSender:
    return ConsoleEmailSender()
```

- [ ] **Step 4: 写失败测试（服务层）**

`backend/tests/test_auth_service.py`：

```python
import pytest
from sqlalchemy import select

from app.auth import service
from app.auth.models import User, VerificationCode


async def _get_code(db, email: str) -> str:
    row = await db.scalar(
        select(VerificationCode)
        .where(VerificationCode.email == email)
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    )
    return row.code


async def test_register_full_flow(db_session):
    email = "svc-flow@test.dev"
    await service.request_code(db_session, email)
    code = await _get_code(db_session, email)
    user = await service.register(db_session, email, code, "pw-123456")
    assert isinstance(user, User) and user.email == email

    fetched = await service.login(db_session, email, "pw-123456")
    assert fetched.id == user.id


async def test_request_code_rate_limited(db_session):
    email = "svc-rate@test.dev"
    await service.request_code(db_session, email)
    with pytest.raises(service.AuthError) as exc:
        await service.request_code(db_session, email)
    assert exc.value.status == 429


async def test_register_wrong_code_rejected(db_session):
    email = "svc-wrong@test.dev"
    await service.request_code(db_session, email)
    with pytest.raises(service.AuthError) as exc:
        await service.register(db_session, email, "000000", "pw-123456")
    assert exc.value.status == 400


async def test_register_duplicate_email_rejected(db_session):
    email = "svc-dup@test.dev"
    await service.request_code(db_session, email)
    code = await _get_code(db_session, email)
    await service.register(db_session, email, code, "pw-123456")

    await service.request_code(db_session, email)
    code2 = await _get_code(db_session, email)
    with pytest.raises(service.AuthError) as exc:
        await service.register(db_session, email, code2, "pw-abcdef")
    assert exc.value.status == 409


async def test_login_wrong_password_rejected(db_session):
    email = "svc-badpw@test.dev"
    await service.request_code(db_session, email)
    code = await _get_code(db_session, email)
    await service.register(db_session, email, code, "pw-123456")
    with pytest.raises(service.AuthError) as exc:
        await service.login(db_session, email, "wrong")
    assert exc.value.status == 401
```

Run: `uv run pytest tests/test_auth_service.py -v`
Expected: FAIL（ModuleNotFoundError: app.auth.service）

注意：`test_request_code_rate_limited` 依赖同邮箱 60 秒窗口，每个测试用独立邮箱避免相互污染（共享一个 session 级数据库）。

- [ ] **Step 5: 实现 service**

`backend/app/auth/service.py`：

```python
import datetime as dt
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.emailer import get_email_sender
from app.auth.models import User, UserIdentity, VerificationCode
from app.core.security import hash_password, verify_password

CODE_TTL_MIN = 10
RESEND_INTERVAL_S = 60


class AuthError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def request_code(db: AsyncSession, email: str) -> None:
    latest = await db.scalar(
        select(VerificationCode)
        .where(VerificationCode.email == email)
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    )
    if latest and (_now() - latest.created_at).total_seconds() < RESEND_INTERVAL_S:
        raise AuthError(429, "验证码请求过于频繁，请 60 秒后再试")
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        VerificationCode(email=email, code=code, expires_at=_now() + dt.timedelta(minutes=CODE_TTL_MIN))
    )
    await db.commit()
    await get_email_sender().send(email, "D-sight 注册验证码", f"验证码：{code}，{CODE_TTL_MIN} 分钟内有效")


async def register(db: AsyncSession, email: str, code: str, password: str) -> User:
    if await db.scalar(select(User).where(User.email == email)):
        raise AuthError(409, "该邮箱已注册")
    vc = await db.scalar(
        select(VerificationCode)
        .where(
            VerificationCode.email == email,
            VerificationCode.code == code,
            VerificationCode.consumed_at.is_(None),
        )
        .order_by(VerificationCode.created_at.desc())
        .limit(1)
    )
    if vc is None or vc.expires_at < _now():
        raise AuthError(400, "验证码错误或已过期")
    vc.consumed_at = _now()
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    await db.flush()
    db.add(UserIdentity(user_id=user.id, provider="email", provider_uid=email))
    await db.commit()
    await db.refresh(user)
    return user


async def login(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError(401, "邮箱或密码错误")
    return user
```

- [ ] **Step 6: 测试通过 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_auth_service.py -v` → 5 passed；`uv run pytest -q` 全绿

```bash
git add backend/app/auth/ backend/alembic/ backend/tests/test_auth_service.py
git commit -m "feat(backend): auth models, migration, verification-code service"
```

---

### Task 5: 认证 API（注册/登录/refresh/登出/me）

**Files:**
- Create: `backend/app/auth/schemas.py`、`backend/app/auth/router.py`、`backend/app/auth/deps.py`
- Modify: `backend/app/main.py`（挂载 router + AuthError 异常处理器）
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: Task 3 全部安全原语、Task 4 service/models
- Produces:
  - 端点（前缀 `/api/auth`）：
    - `POST /request-code` `{email}` → 204
    - `POST /register` `{email, code, password}` → 201 `{access_token, token_type:"bearer"}` + httpOnly refresh cookie
    - `POST /login` `{email, password}` → 200 同上
    - `POST /refresh`（读 cookie）→ 200 新 access + 轮换 refresh cookie（旧 jti 吊销）
    - `POST /logout` → 204，吊销 refresh 并清 cookie
    - `GET /me` → 200 `{id, email, role}`（Bearer access）
  - `get_current_user` FastAPI 依赖（`app.auth.deps`）→ `User`，401 on 缺失/无效——**计划 2b 的聊天端点与 Task 6 的 threads 端点都消费它**
  - cookie 名 `dsight_refresh`，path=`/api/auth`
  - `create_app()` 注册 `AuthError` → JSONResponse(status, {"detail": ...})

- [ ] **Step 1: 写失败测试**

`backend/tests/test_auth_api.py`：

```python
from sqlalchemy import select

from app.auth.models import VerificationCode

REFRESH_COOKIE = "dsight_refresh"


async def _register(client, db_session, email: str, password: str = "pw-123456") -> str:
    """走完整注册流，返回 access_token。"""
    resp = await client.post("/api/auth/request-code", json={"email": email})
    assert resp.status_code == 204
    code = (
        await db_session.scalar(
            select(VerificationCode)
            .where(VerificationCode.email == email)
            .order_by(VerificationCode.created_at.desc())
            .limit(1)
        )
    ).code
    resp = await client.post(
        "/api/auth/register", json={"email": email, "code": code, "password": password}
    )
    assert resp.status_code == 201, resp.text
    assert REFRESH_COOKIE in resp.cookies
    return resp.json()["access_token"]


async def test_register_then_me(client, db_session):
    token = await _register(client, db_session, "api-reg@test.dev")
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "api-reg@test.dev" and body["role"] == "user"


async def test_me_requires_token(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer bogus"})
    assert resp.status_code == 401


async def test_login_and_refresh_rotation(client, db_session):
    await _register(client, db_session, "api-login@test.dev")
    resp = await client.post(
        "/api/auth/login", json={"email": "api-login@test.dev", "password": "pw-123456"}
    )
    assert resp.status_code == 200
    old_cookie = resp.cookies[REFRESH_COOKIE]

    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert resp.cookies[REFRESH_COOKIE] != old_cookie  # 轮换

    # 旧 refresh 已吊销：手动带旧 cookie 再刷新应 401
    client.cookies.set(REFRESH_COOKIE, old_cookie, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh(client, db_session):
    await _register(client, db_session, "api-logout@test.dev")
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 401
```

Run: `uv run pytest tests/test_auth_api.py -v`
Expected: FAIL（404，路由不存在）

- [ ] **Step 2: 实现 schemas / deps / router，并挂载**

`backend/app/auth/schemas.py`：

```python
from pydantic import BaseModel, EmailStr, Field


class RequestCodeIn(BaseModel):
    email: EmailStr


class RegisterIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    id: str
    email: EmailStr
    role: str
```

`backend/app/auth/deps.py`：

```python
import uuid

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.db import get_db
from app.core.security import decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(401, "未登录")
    try:
        payload = decode_token(cred.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "登录状态无效，请重新登录")
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(401, "用户不存在")
    return user
```

`backend/app/auth/router.py`：

```python
import datetime as dt

import jwt
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.deps import get_current_user
from app.auth.models import RefreshToken, User
from app.auth.schemas import LoginIn, MeOut, RegisterIn, RequestCodeIn, TokenOut
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "dsight_refresh"


async def _issue_tokens(db: AsyncSession, user: User, response: Response) -> TokenOut:
    token, jti, expires = create_refresh_token(str(user.id))
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires))
    await db.commit()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=get_settings().refresh_token_ttl_days * 86400,
        path="/api/auth",
    )
    return TokenOut(access_token=create_access_token(str(user.id)))


async def _valid_refresh_row(db: AsyncSession, request: Request) -> tuple[RefreshToken, str]:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise service.AuthError(401, "缺少 refresh token")
    try:
        payload = decode_token(token, refresh=True)
    except jwt.InvalidTokenError:
        raise service.AuthError(401, "refresh token 无效")
    row = await db.get(RefreshToken, payload["jti"])
    if row is None or row.revoked_at is not None or row.expires_at < dt.datetime.now(dt.UTC):
        raise service.AuthError(401, "refresh token 已失效，请重新登录")
    return row, payload["sub"]


@router.post("/request-code", status_code=204)
async def request_code(body: RequestCodeIn, db: AsyncSession = Depends(get_db)) -> None:
    await service.request_code(db, body.email)


@router.post("/register", status_code=201)
async def register(
    body: RegisterIn, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    user = await service.register(db, body.email, body.code, body.password)
    return await _issue_tokens(db, user, response)


@router.post("/login")
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = await service.login(db, body.email, body.password)
    return await _issue_tokens(db, user, response)


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    row, sub = await _valid_refresh_row(db, request)
    row.revoked_at = dt.datetime.now(dt.UTC)
    import uuid as _uuid

    user = await db.get(User, _uuid.UUID(sub))
    if user is None:
        raise service.AuthError(401, "用户不存在")
    return await _issue_tokens(db, user, response)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    try:
        row, _ = await _valid_refresh_row(db, request)
        row.revoked_at = dt.datetime.now(dt.UTC)
        await db.commit()
    except service.AuthError:
        pass  # 幂等：无有效 refresh 也允许登出
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> MeOut:
    return MeOut(id=str(user.id), email=user.email, role=user.role)
```

`backend/app/main.py` 改为：

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.auth.service import AuthError


def create_app() -> FastAPI:
    app = FastAPI(title="D-sight API")

    @app.exception_handler(AuthError)
    async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    app.include_router(auth_router)
    return app
```

- [ ] **Step 3: 测试通过**

Run: `uv run pytest tests/test_auth_api.py -v`
Expected: 4 passed（注意 httpx cookie 域/path 行为：AsyncClient 会自动携带 set-cookie 返回的 cookie；若 path 匹配问题导致 refresh 拿不到 cookie，把断言改为从 `resp.headers["set-cookie"]` 解析——先按现状跑，失败再查，不要盲改）

- [ ] **Step 4: 全量回归 + Commit（需用户已授权）**

Run: `uv run pytest -q` → 全绿；`uv run ruff check .`

```bash
git add backend/app/ backend/tests/test_auth_api.py
git commit -m "feat(backend): auth API with refresh rotation and revocation"
```

---

### Task 6: 会话（threads）模型与 CRUD API

**Files:**
- Create: `backend/app/threads/__init__.py`、`backend/app/threads/models.py`、`backend/app/threads/schemas.py`、`backend/app/threads/router.py`、`backend/alembic/versions/<自动生成>_threads.py`
- Modify: `backend/alembic/env.py`（import）、`backend/app/main.py`（挂载）
- Test: `backend/tests/test_threads_api.py`

**Interfaces:**
- Consumes: Task 5 `get_current_user`
- Produces:
  - model `Thread(id: UUID, user_id, title, created_at, updated_at, deleted_at?)`（spec §4.3：软删；标题默认取首条用户消息截断——落库逻辑在 2b 聊天端点，此处默认 `"新对话"`）
  - 端点（前缀 `/api/threads`，全部需登录）：
    - `POST /` `{title?}` → 201 `{id, title, created_at}`
    - `GET /` → 200 列表（不含已删，按 updated_at 倒序）
    - `PATCH /{thread_id}` `{title}` → 200
    - `DELETE /{thread_id}` → 204（软删）
  - 越权访问他人 thread → 404（不泄露存在性）
  - **计划 2b 消费**：`Thread` model 与"更新 `updated_at`"约定（聊天端点每次消息后 touch）

- [ ] **Step 1: 实现 model 并生成迁移**

`backend/app/threads/models.py`：

```python
import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
```

`backend/alembic/env.py` 加：

```python
from app.threads import models as thread_models  # noqa: F401
```

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://dsight:dsight@localhost:5434/dsight uv run alembic revision --autogenerate -m "threads"
uv run alembic upgrade head
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_threads_api.py`：

```python
from tests.test_auth_api import _register


async def _auth_headers(client, db_session, email: str) -> dict:
    token = await _register(client, db_session, email)
    return {"Authorization": f"Bearer {token}"}


async def test_thread_crud_flow(client, db_session):
    headers = await _auth_headers(client, db_session, "th-crud@test.dev")

    resp = await client.post("/api/threads/", json={}, headers=headers)
    assert resp.status_code == 201
    tid = resp.json()["id"]
    assert resp.json()["title"] == "新对话"

    resp = await client.patch(f"/api/threads/{tid}", json={"title": "茅台研究"}, headers=headers)
    assert resp.status_code == 200 and resp.json()["title"] == "茅台研究"

    resp = await client.get("/api/threads/", headers=headers)
    assert [t["id"] for t in resp.json()] == [tid]

    assert (await client.delete(f"/api/threads/{tid}", headers=headers)).status_code == 204
    resp = await client.get("/api/threads/", headers=headers)
    assert resp.json() == []


async def test_thread_isolation_between_users(client, db_session):
    headers_a = await _auth_headers(client, db_session, "th-a@test.dev")
    headers_b = await _auth_headers(client, db_session, "th-b@test.dev")

    tid = (await client.post("/api/threads/", json={}, headers=headers_a)).json()["id"]

    assert (await client.get("/api/threads/", headers=headers_b)).json() == []
    resp = await client.patch(f"/api/threads/{tid}", json={"title": "x"}, headers=headers_b)
    assert resp.status_code == 404
    assert (await client.delete(f"/api/threads/{tid}", headers=headers_b)).status_code == 404


async def test_threads_require_auth(client):
    assert (await client.get("/api/threads/")).status_code == 401
```

Run: `uv run pytest tests/test_threads_api.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现 schemas + router，挂载**

`backend/app/threads/schemas.py`：

```python
import datetime as dt

from pydantic import BaseModel, Field


class ThreadCreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ThreadPatchIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ThreadOut(BaseModel):
    id: str
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime
```

`backend/app/threads/router.py`：

```python
import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.threads.models import Thread
from app.threads.schemas import ThreadCreateIn, ThreadOut, ThreadPatchIn

router = APIRouter(prefix="/api/threads", tags=["threads"])


def _out(t: Thread) -> ThreadOut:
    return ThreadOut(id=str(t.id), title=t.title, created_at=t.created_at, updated_at=t.updated_at)


async def _owned_thread(db: AsyncSession, user: User, thread_id: str) -> Thread:
    try:
        tid = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(404, "会话不存在")
    t = await db.get(Thread, tid)
    if t is None or t.user_id != user.id or t.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    return t


@router.post("/", status_code=201)
async def create_thread(
    body: ThreadCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    t = Thread(user_id=user.id, title=body.title or "新对话")
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _out(t)


@router.get("/")
async def list_threads(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ThreadOut]:
    rows = await db.scalars(
        select(Thread)
        .where(Thread.user_id == user.id, Thread.deleted_at.is_(None))
        .order_by(Thread.updated_at.desc())
    )
    return [_out(t) for t in rows]


@router.patch("/{thread_id}")
async def rename_thread(
    thread_id: str,
    body: ThreadPatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    t = await _owned_thread(db, user, thread_id)
    t.title = body.title
    await db.commit()
    await db.refresh(t)
    return _out(t)


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    t = await _owned_thread(db, user, thread_id)
    t.deleted_at = dt.datetime.now(dt.UTC)
    await db.commit()
```

`backend/app/main.py` 挂载：在 `app.include_router(auth_router)` 后加：

```python
from app.threads.router import router as threads_router  # 移到文件顶部 import 区

app.include_router(threads_router)
```

- [ ] **Step 4: 测试通过 + 全量回归 + Commit（需用户已授权）**

Run: `uv run pytest tests/test_threads_api.py -v` → 3 passed；`uv run pytest -q` 全绿

```bash
git add backend/app/threads/ backend/alembic/ backend/app/main.py backend/tests/test_threads_api.py
git commit -m "feat(backend): thread CRUD with soft delete and ownership isolation"
```

---

### Task 7: CI 与开发文档

**Files:**
- Create: `.github/workflows/ci.yml`、`backend/README.md`

**Interfaces:**
- Produces: PR/push 到 main 自动跑 ruff + pytest（testcontainers 需要 Docker，GitHub ubuntu runner 自带）

- [ ] **Step 1: CI workflow**

`.github/workflows/ci.yml`：

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run pytest -q
```

- [ ] **Step 2: backend/README.md（防"空 workspace 静默"类问题，PoC 终审教训）**

```markdown
# D-sight backend

## 本地开发

1. 起依赖：`docker compose -f ../docker-compose.dev.yml up -d`
2. 配置：`cp .env.example .env`（本地默认值即可跑通）
3. 迁移：`uv run alembic upgrade head`
4. 启动：`uv run uvicorn app.main:create_app --factory --reload --port 8000`
5. 测试：`uv run pytest`（需要 Docker，testcontainers 起独立 Postgres）

## 结构

app/core（配置/DB/安全原语） · app/auth（注册登录 JWT） · app/threads（会话 CRUD）
聊天链路（agent/流式端点）见计划 2b。
```

- [ ] **Step 3: 本地全量验证 + Commit（需用户已授权）**

Run: `cd backend && uv run pytest -q && uv run ruff check .`
Expected: 全绿

```bash
git add .github/ backend/README.md
git commit -m "chore: CI workflow and backend dev docs"
```

---

## Self-Review 记录

- **Spec 覆盖**：§7.1 认证全项（验证码邮件→console 实现+接口预留 SMTP、bcrypt、JWT 15min/30d httpOnly 可吊销、`user_identities` 解耦、wechat 预留列）✅；§7.3 `users.role` ✅（admin API 在计划 3+）；§4.3 会话管理（列表/重命名/软删/默认标题，"标题取首条消息"归 2b 聊天端点）✅；§9 CI ✅；§2 架构形态 ✅。聊天链路、agent、积分、KB、新闻不在本计划（2b/3/4/5）。
- **占位符扫描**：无 TBD/TODO；Task 5 Step 3 的 cookie 行为备注是"先跑再查"的验证指引而非未完成项。SMTP 真实实现明确划归部署阶段（spec §7.1 一期用阿里云邮件推送——接口已抽象，配置类实现属计划 6 部署项）。✅
- **类型一致性**：`get_current_user -> User` 在 Task 5 定义、Task 6 消费一致；`AuthError(status, detail)` 全程一致；`_register` helper 被 test_threads_api 复用（同签名）；`REFRESH_COOKIE="dsight_refresh"` 两处测试与 router 一致。✅
