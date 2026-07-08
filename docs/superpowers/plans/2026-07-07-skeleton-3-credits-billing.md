# 骨架计划 3：积分计费核心 + 上线前置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给已通的聊天链路装上积分闸门（预检→扣费→月度重置），并补齐真实上线前置（SMTP 邮件、真实模式 skill 枚举），使系统能注册真实账号、按用量计费、跑通一次闭环。

**Architecture:** 新增 `credits` 模块（账户/流水/记账函数，余额由流水推导、行锁防并发双扣）。聊天端点在运行前做余额预检、运行后按 token 折算实扣，并加 15 分钟绝对超时与 per-user 限频。APScheduler 进程内跑月初零点重置。补 `admin` 模块做积分/套餐手动调整（写审计日志）。邮件按 `email_backend` 设置切 console/smtp。skill 目录像 tools 一样拷入每 thread 工作区，绕开沙箱越界拒绝。

**Tech Stack:** FastAPI、SQLAlchemy 2 async、Alembic、APScheduler（AsyncIOScheduler）、redis.asyncio（限频）、langchain_core UsageMetadataCallbackHandler（token 计量）、aiosmtplib（SMTP）。

## Global Constraints

- Python 3.12，包管理 `uv`，测试 `pytest`（testcontainers 真 Postgres，ryuk flake 时加 `TESTCONTAINERS_RYUK_DISABLED=true`）。
- 时区统一 **Asia/Shanghai**（北京时间），月度重置按北京时间零点。
- 一切积分变更**必须**走 `credits.service` 的记账函数（单事务 + `SELECT ... FOR UPDATE` 行锁）；严禁直接改 `credit_accounts.balance`。余额可由 `credit_transactions` 流水求和审计。
- 积分参数可配（`TOKENS_PER_CREDIT`、`FREE_MONTHLY_QUOTA=100`、`SUBSCRIBED_MONTHLY_QUOTA=2000`、`MIN_CHARGE=1`），从 `Settings` 读，不硬编码散落。
- 模型白名单不变：仅 `deepseek-v4-flash` / `deepseek-v4-pro`。
- 分支 `skeleton-3` 从 `main` 起；本地 commit 已授权，**不 push**（等用户 `c&p`）。
- 不写多余文档；README 只补计费相关一节。
- **skill 固定定价**依赖 `skills` 表（计划 4 才建）；本计划扣费只做 **token 折算基础扣费**，skill 定价挂钩留计划 4，代码中以显式 TODO + 单测边界标注，不留空壳。

---

### Task 0: 分支与骨架目录

**Files:**
- Create: `backend/app/credits/__init__.py`、`backend/app/admin/__init__.py`

- [ ] **Step 1: 建分支**

Run:
```bash
cd /Users/weixi1/Documents/mine/D-sight && git checkout main && git checkout -b skeleton-3
```
Expected: `Switched to a new branch 'skeleton-3'`

- [ ] **Step 2: 建空包**

```bash
cd backend && mkdir -p app/credits app/admin && touch app/credits/__init__.py app/admin/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/credits/__init__.py backend/app/admin/__init__.py
git commit -m "chore(credits): scaffold credits and admin packages"
```

---

### Task 1: 积分数据模型 + 迁移

**Files:**
- Create: `backend/app/credits/models.py`
- Create: migration（`backend/alembic/versions/*_credits.py`，autogenerate）
- Test: `backend/tests/test_credits_models.py`

**Interfaces:**
- Produces:
  - `CreditAccount(user_id: UUID PK/FK, balance: int, monthly_quota: int, plan: str, reset_at: datetime|None, updated_at)`
  - `CreditTransaction(id: UUID, user_id: UUID FK, kind: str, amount: int, balance_after: int, ref_type: str|None, ref_id: str|None, created_at)`
  - `AdminAuditLog(id: UUID, admin_id: UUID FK, action: str, target_type: str, target_id: str, detail: dict(JSON), created_at)`
  - `kind` 取值约定：`grant`（发放/月度重置补足）、`reset`（重置清零负向）、`chat`（对话扣费，负）、`adjust`（管理员手工，±）。

- [ ] **Step 1: 写模型**

`backend/app/credits/models.py`:
```python
import datetime as dt
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monthly_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="free", server_default="free")
    reset_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 有符号：正=入，负=扣
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 2: 让模型被 Alembic 发现**

确认 `backend/alembic/env.py` 通过 `app.core.db.Base.metadata` 采集，且导入了模型模块。检查 `backend/app/main.py` 或 alembic env 是否已 import 各 models；若 credits 模型未被导入，在 `backend/alembic/env.py` 顶部补 `import app.credits.models  # noqa: F401`（与现有 `app.auth.models` / `app.threads.models` 导入同处）。

Run（先确认现状）：
```bash
cd backend && grep -rn "import app\..*models" alembic/env.py
```

- [ ] **Step 3: 生成迁移**

Run:
```bash
cd backend && uv run alembic revision --autogenerate -m "credits"
```
Expected: 生成 `alembic/versions/xxxx_credits.py`，`upgrade()` 含 `create_table('credit_accounts')` / `credit_transactions` / `admin_audit_log`。人工 Read 该文件确认三表都在、外键正确、无误删其他表。

- [ ] **Step 4: 写模型往返测试**

`backend/tests/test_credits_models.py`:
```python
import uuid

import pytest

from app.auth.models import User
from app.credits.models import CreditAccount, CreditTransaction
from app.core.security import hash_password


@pytest.mark.asyncio
async def test_account_and_transaction_roundtrip(db_session):
    user = User(email=f"c-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(user)
    await db_session.flush()

    acct = CreditAccount(user_id=user.id, balance=100, monthly_quota=100, plan="free")
    db_session.add(acct)
    tx = CreditTransaction(
        user_id=user.id, kind="grant", amount=100, balance_after=100,
        ref_type="signup", ref_id=None,
    )
    db_session.add(tx)
    await db_session.commit()

    got = await db_session.get(CreditAccount, user.id)
    assert got.balance == 100 and got.plan == "free"
```
（注：`hash_password` 函数名以 `app/core/security.py` 实际导出为准；若名为 `get_password_hash`，改之。先 `grep -n "def .*password" app/core/security.py` 确认。）

- [ ] **Step 5: 迁移 + 测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credits_models.py -q
```
Expected: PASS（conftest 的 `_database` fixture 会对 testcontainer 跑 `alembic upgrade head`，新迁移生效）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/credits/models.py backend/alembic/ backend/tests/test_credits_models.py
git commit -m "feat(credits): credit account/transaction/audit models and migration"
```

---

### Task 2: 记账服务 + 注册发放

**Files:**
- Create: `backend/app/credits/pricing.py`
- Create: `backend/app/credits/service.py`
- Modify: `backend/app/core/config.py`（加积分参数）
- Modify: `backend/app/auth/service.py`（注册成功后建账户 + 发放免费额度）
- Test: `backend/tests/test_credits_service.py`

**Interfaces:**
- Consumes: `CreditAccount`、`CreditTransaction`（Task 1）。
- Produces:
  - `pricing.tokens_to_credits(total_tokens: int) -> int`（`ceil(total_tokens / TOKENS_PER_CREDIT)`，下限 `MIN_CHARGE`）
  - `pricing.quota_for_plan(plan: str) -> int`
  - `class InsufficientCredits(Exception)`
  - `async def ensure_account(db, user_id: uuid.UUID) -> CreditAccount`（无则建 free 账户 + 发放 100 grant 流水；有则返回）
  - `async def get_balance(db, user_id) -> int`
  - `async def precheck(db, user_id, need: int = MIN_CHARGE) -> None`（余额 < need → `InsufficientCredits`）
  - `async def charge(db, user_id, amount: int, kind: str, ref_type=None, ref_id=None) -> CreditTransaction`（`amount>0` 扣费；行锁读账户→扣→写流水→单事务提交；余额允许扣至 0 下限即 `max(0, balance-amount)` 记账，但 `balance_after` 记真实扣后值）
  - `async def grant(db, user_id, amount: int, kind: str, ref_type=None, ref_id=None) -> CreditTransaction`（加余额）

- [ ] **Step 1: 配置项**

`backend/app/core/config.py` 的 `Settings` 内加：
```python
    tokens_per_credit: int = 1000
    free_monthly_quota: int = 100
    subscribed_monthly_quota: int = 2000
    min_charge: int = 1
```

- [ ] **Step 2: pricing**

`backend/app/credits/pricing.py`:
```python
import math

from app.core.config import get_settings


def tokens_to_credits(total_tokens: int) -> int:
    s = get_settings()
    credits = math.ceil(max(0, total_tokens) / s.tokens_per_credit)
    return max(credits, s.min_charge)


def quota_for_plan(plan: str) -> int:
    s = get_settings()
    return s.subscribed_monthly_quota if plan == "subscribed" else s.free_monthly_quota
```

- [ ] **Step 3: service**

`backend/app/credits/service.py`:
```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credits.models import CreditAccount, CreditTransaction
from app.credits.pricing import quota_for_plan


class InsufficientCredits(Exception):
    pass


async def ensure_account(db: AsyncSession, user_id: uuid.UUID) -> CreditAccount:
    acct = await db.get(CreditAccount, user_id)
    if acct is not None:
        return acct
    quota = quota_for_plan("free")
    acct = CreditAccount(user_id=user_id, balance=quota, monthly_quota=quota, plan="free")
    db.add(acct)
    db.add(CreditTransaction(
        user_id=user_id, kind="grant", amount=quota, balance_after=quota,
        ref_type="signup", ref_id=None,
    ))
    await db.flush()
    return acct


async def get_balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    acct = await db.get(CreditAccount, user_id)
    return acct.balance if acct else 0


async def precheck(db: AsyncSession, user_id: uuid.UUID, need: int) -> None:
    if await get_balance(db, user_id) < need:
        raise InsufficientCredits()


async def _apply(db, user_id, delta, kind, ref_type, ref_id) -> CreditTransaction:
    # 行锁读账户，防并发双扣（SELECT ... FOR UPDATE）
    acct = (
        await db.execute(
            select(CreditAccount).where(CreditAccount.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if acct is None:
        acct = await ensure_account(db, user_id)
        acct = (
            await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == user_id).with_for_update()
            )
        ).scalar_one()
    acct.balance = max(0, acct.balance + delta)
    tx = CreditTransaction(
        user_id=user_id, kind=kind, amount=delta, balance_after=acct.balance,
        ref_type=ref_type, ref_id=ref_id,
    )
    db.add(tx)
    await db.flush()
    return tx


async def charge(db, user_id, amount, kind, ref_type=None, ref_id=None) -> CreditTransaction:
    return await _apply(db, user_id, -abs(amount), kind, ref_type, ref_id)


async def grant(db, user_id, amount, kind, ref_type=None, ref_id=None) -> CreditTransaction:
    return await _apply(db, user_id, abs(amount), kind, ref_type, ref_id)
```

- [ ] **Step 4: 注册钩子**

`backend/app/auth/service.py`：注册成功创建 `User` 后（`await db.flush()` 拿到 `user.id` 之后、`commit` 之前）调用发放。先 `grep -n "def register\|db.add(user)\|flush\|commit" app/auth/service.py` 定位注册函数，在用户落库后插入：
```python
    from app.credits.service import ensure_account
    await ensure_account(db, user.id)
```
（放在 register 事务内，与用户创建同一 commit。）

- [ ] **Step 5: 服务单测**

`backend/tests/test_credits_service.py`:
```python
import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.credits import service
from app.credits.pricing import tokens_to_credits


def test_tokens_to_credits_floor_and_ceil():
    assert tokens_to_credits(0) == 1        # 下限 MIN_CHARGE
    assert tokens_to_credits(1) == 1
    assert tokens_to_credits(1000) == 1
    assert tokens_to_credits(1001) == 2


async def _mk_user(db):
    u = User(email=f"s-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db.add(u)
    await db.flush()
    return u


@pytest.mark.asyncio
async def test_ensure_account_grants_free_quota(db_session):
    u = await _mk_user(db_session)
    acct = await service.ensure_account(db_session, u.id)
    assert acct.balance == 100 and acct.plan == "free"
    # 幂等
    again = await service.ensure_account(db_session, u.id)
    assert again.balance == 100


@pytest.mark.asyncio
async def test_charge_and_precheck(db_session):
    u = await _mk_user(db_session)
    await service.ensure_account(db_session, u.id)
    await service.charge(db_session, u.id, 30, kind="chat", ref_type="thread", ref_id="t1")
    assert await service.get_balance(db_session, u.id) == 70
    await service.precheck(db_session, u.id, need=1)  # 不抛
    await service.charge(db_session, u.id, 100, kind="chat")  # 扣到 0 下限
    assert await service.get_balance(db_session, u.id) == 0
    with pytest.raises(service.InsufficientCredits):
        await service.precheck(db_session, u.id, need=1)
```

- [ ] **Step 6: 跑测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credits_service.py -q
```
Expected: PASS（4 项）。

- [ ] **Step 7: 回归注册测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_auth_api.py -q
```
Expected: 全绿（注册钩子未破坏既有流程）。

- [ ] **Step 8: Commit**

```bash
git add backend/app/credits/pricing.py backend/app/credits/service.py backend/app/core/config.py backend/app/auth/service.py backend/tests/test_credits_service.py
git commit -m "feat(credits): accounting service with row lock, pricing, signup grant"
```

---

### Task 3: 聊天预检 + 实扣 + 15 分钟绝对超时

**Files:**
- Modify: `backend/app/chat/router.py`
- Test: `backend/tests/test_chat_credits.py`

**Interfaces:**
- Consumes: `service.precheck / charge / InsufficientCredits`（Task 2）、`pricing.tokens_to_credits`。
- Produces: 聊天端点行为——运行前 `precheck`（不足 → HTTP 402 `{"detail":"积分不足"}`）；运行后按本轮 token 折算 `charge(kind="chat", ref_type="thread", ref_id=thread_id)`；`astream` 包 15 分钟 `asyncio.timeout`，超时按已计量 token 实扣并结束。

- [ ] **Step 1: 写失败测试（预检拒绝）**

`backend/tests/test_chat_credits.py`（FAKE_LLM 模式；沿用 `test_chat_api.py` 的注册+建 thread+发消息夹具风格，先 Read 其辅助函数并复用）:
```python
import pytest

from app.credits import service


@pytest.mark.asyncio
async def test_chat_rejected_when_no_credits(client, db_session, registered_user, a_thread):
    # 把余额扣到 0
    await service.charge(db_session, registered_user.id, 1000, kind="adjust")
    await db_session.commit()
    resp = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_chat_charges_after_run(client, db_session, registered_user, a_thread):
    before = await service.get_balance(db_session, registered_user.id)
    resp = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert resp.status_code == 200
    await resp.aread()  # 消费完整流
    after = await service.get_balance(db_session, registered_user.id)
    assert after < before  # 至少扣了 MIN_CHARGE
```
（`registered_user`/`a_thread`/`_chat_body`/`_auth` 若 `test_chat_api.py` 已有等价物，抽到 `conftest.py` 复用；没有则在本文件内实现，与 `test_chat_api.py` 保持一致。FAKE_LLM 下 fake 模型无 usage_metadata → 折算得 0 → 由 `MIN_CHARGE` 兜底扣 1，`after < before` 成立。）

- [ ] **Step 2: 跑测试看失败**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_chat_credits.py -q
```
Expected: FAIL（尚无预检/扣费逻辑）。

- [ ] **Step 3: 改端点**

`backend/app/chat/router.py`：顶部加导入
```python
import asyncio
from langchain_core.callbacks import UsageMetadataCallbackHandler

from app.credits import service
from app.credits.pricing import tokens_to_credits
```
在 `chat()` 里 `thread = await _owned_thread(...)` 之后、`await db.commit()` 之前加预检：
```python
    try:
        await service.precheck(db, user.id, need=get_settings().min_charge)
    except service.InsufficientCredits:
        raise HTTPException(402, "积分不足")
```
（需 `from app.core.config import get_settings`。）

改 `run_callback`：装 usage 回调 + 超时 + 结束扣费。把 `config` 与 astream 段替换为：
```python
        usage_cb = UsageMetadataCallbackHandler()
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 200,
            "callbacks": [usage_cb],
        }
        try:
            async with asyncio.timeout(900):  # 15 分钟绝对超时
                async for namespace, event_type, chunk in agent.astream(
                    {"messages": input_messages},
                    config=config,
                    stream_mode=["messages", "updates"],
                    subgraphs=True,
                ):
                    append_langgraph_event(controller.state, namespace, event_type, chunk)
        except TimeoutError:
            append_langgraph_event(
                controller.state, (), "updates",
                {"error": {"messages": [{"type": "ai", "content": "（任务超时，已按实际消耗计费）"}]}},
            )
        finally:
            total = sum(v.get("total_tokens", 0) for v in usage_cb.usage_metadata.values())
            async with get_sessionmaker()() as s:
                await service.charge(
                    s, user.id, tokens_to_credits(total),
                    kind="chat", ref_type="thread", ref_id=thread_id,
                )
                t = await s.get(Thread, thread.id)
                if t is not None:
                    t.updated_at = datetime.now(UTC)
                await s.commit()
```
（把原先单独 touch `updated_at` 的 session 段并入这个 `finally`，一次事务同时扣费 + touch。`user.id` 在闭包内可见。超时事件的 `append_langgraph_event` 形参以 assistant_stream 实际签名为准，若不便直接注入错误事件，可只记日志并保证扣费；断言不依赖该事件文本。）

- [ ] **Step 4: 跑测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_chat_credits.py -q
```
Expected: PASS（2 项）。

- [ ] **Step 5: 回归**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_chat_api.py -q
```
Expected: 全绿（含既有 `updated_at` 前进断言——现在扣费事务里仍 touch）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/router.py backend/tests/test_chat_credits.py
git commit -m "feat(credits): chat precheck, token-based charge, 15min hard timeout"
```

---

### Task 4: Per-user 限频（redis 固定窗口）

**Files:**
- Create: `backend/app/core/ratelimit.py`
- Modify: `backend/app/core/config.py`（`redis_url`、`rate_limit_per_min`）
- Modify: `backend/app/chat/router.py`（接入限频）
- Modify: `backend/pyproject.toml`（加 `redis`）
- Test: `backend/tests/test_ratelimit.py`

**Interfaces:**
- Produces:
  - `async def check_rate(user_id: str) -> bool`（True=放行；redis 不可用 → fail-open 返回 True 并日志）
  - 聊天端点：超限 → HTTP 429 `{"detail":"请求过于频繁"}`。

- [ ] **Step 1: 加依赖**

Run:
```bash
cd backend && uv add redis
```
Expected: `pyproject.toml` 出现 `redis`，`uv.lock` 更新。

- [ ] **Step 2: 配置**

`Settings` 加：
```python
    redis_url: str = "redis://localhost:6381/0"
    rate_limit_per_min: int = 20
```

- [ ] **Step 3: 限频实现**

`backend/app/core/ratelimit.py`:
```python
import logging

import redis.asyncio as aioredis

from app.core.config import get_settings

_log = logging.getLogger(__name__)
_client: aioredis.Redis | None = None


def _redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def check_rate(user_id: str) -> bool:
    """固定窗口：每分钟每用户至多 rate_limit_per_min 次。redis 挂则放行（fail-open）。"""
    s = get_settings()
    try:
        from datetime import UTC, datetime
        window = datetime.now(UTC).strftime("%Y%m%d%H%M")
        key = f"rl:{user_id}:{window}"
        r = _redis()
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 70)
        return n <= s.rate_limit_per_min
    except Exception as e:  # noqa: BLE001
        _log.warning("rate limit check failed, fail-open: %s", e)
        return True
```

- [ ] **Step 4: 接入端点**

`chat.py` 预检前加：
```python
    from app.core.ratelimit import check_rate
    if not await check_rate(str(user.id)):
        raise HTTPException(429, "请求过于频繁")
```

- [ ] **Step 5: 测试（打桩 redis，不依赖真实实例）**

`backend/tests/test_ratelimit.py`:
```python
import pytest

from app.core import ratelimit


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, ttl):
        return True


@pytest.mark.asyncio
async def test_allows_under_limit_then_blocks(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(ratelimit, "_redis", lambda: fake)
    monkeypatch.setattr(ratelimit.get_settings(), "rate_limit_per_min", 3, raising=False)
    # 前 3 次放行，第 4 次拦
    results = [await ratelimit.check_rate("u1") for _ in range(4)]
    assert results[:3] == [True, True, True]
    assert results[3] is False


@pytest.mark.asyncio
async def test_fail_open_on_redis_error(monkeypatch):
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(ratelimit, "_redis", boom)
    assert await ratelimit.check_rate("u1") is True
```
（`monkeypatch.setattr(get_settings(), ...)` 依赖 `get_settings()` 单例被缓存；若 `raising=False` 不适用，改为 monkeypatch `ratelimit.get_settings` 返回一个带 `rate_limit_per_min=3` 的 SimpleNamespace。）

- [ ] **Step 6: 跑测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_ratelimit.py -q
```
Expected: PASS（2 项）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/ratelimit.py backend/app/core/config.py backend/app/chat/router.py backend/pyproject.toml backend/uv.lock backend/tests/test_ratelimit.py
git commit -m "feat(credits): per-user fixed-window rate limit with fail-open"
```

---

### Task 5: 月度重置 + APScheduler

**Files:**
- Create: `backend/app/credits/reset.py`
- Create: `backend/app/core/scheduler.py`
- Modify: `backend/app/main.py`（lifespan 启停调度器）
- Modify: `backend/pyproject.toml`（加 `apscheduler`）
- Test: `backend/tests/test_credits_reset.py`

**Interfaces:**
- Consumes: `CreditAccount`、`grant`。
- Produces:
  - `async def reset_all_accounts(db) -> int`（把每账户 balance 重置为 `monthly_quota`（清零再发，非累加），写一条 `kind="reset"` 流水记录差额，返回处理账户数；`reset_at` 更新为当前时间）
  - `scheduler.start_scheduler()` / `stop_scheduler()`，注册 cron `day=1, hour=0, minute=0, timezone=Asia/Shanghai`。

- [ ] **Step 1: 加依赖**

Run:
```bash
cd backend && uv add apscheduler
```

- [ ] **Step 2: 重置逻辑**

`backend/app/credits/reset.py`:
```python
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credits.models import CreditAccount, CreditTransaction


async def reset_all_accounts(db: AsyncSession) -> int:
    accts = (await db.execute(select(CreditAccount).with_for_update())).scalars().all()
    now = dt.datetime.now(dt.UTC)
    for a in accts:
        delta = a.monthly_quota - a.balance  # 清零再发：直接置为配额，流水记差额
        a.balance = a.monthly_quota
        a.reset_at = now
        db.add(CreditTransaction(
            user_id=a.user_id, kind="reset", amount=delta, balance_after=a.balance,
            ref_type="monthly", ref_id=now.strftime("%Y-%m"),
        ))
    await db.commit()
    return len(accts)
```

- [ ] **Step 3: 调度器**

`backend/app/core/scheduler.py`:
```python
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.db import get_sessionmaker
from app.credits.reset import reset_all_accounts

_log = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def _monthly_job():
    async with get_sessionmaker()() as s:
        n = await reset_all_accounts(s)
    _log.info("monthly credit reset done: %d accounts", n)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        _monthly_job, CronTrigger(day=1, hour=0, minute=0, timezone="Asia/Shanghai"),
        id="monthly_credit_reset", replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
```

- [ ] **Step 4: 挂到 lifespan**

`backend/app/main.py` 的 `lifespan`：在 `app.state.checkpointer = checkpointer` 之后、`yield` 之前 `start_scheduler()`；`yield` 之后 `stop_scheduler()`。先 Read 现有 lifespan 结构，插入：
```python
    from app.core.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
```
（与现有 `async with cm as checkpointer:` 结构合并，保证 checkpointer 上下文与调度器都正确关闭。）

- [ ] **Step 5: 重置测试（直接调函数，不等定时）**

`backend/tests/test_credits_reset.py`:
```python
import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.credits import service
from app.credits.reset import reset_all_accounts


@pytest.mark.asyncio
async def test_reset_zeroes_then_refills_to_quota(db_session):
    u = User(email=f"r-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add(u)
    await db_session.flush()
    acct = await service.ensure_account(db_session, u.id)
    acct.monthly_quota = 2000  # 模拟订阅额度
    await service.charge(db_session, u.id, 90, kind="chat")  # 余额 10
    await db_session.commit()

    n = await reset_all_accounts(db_session)
    assert n >= 1
    assert await service.get_balance(db_session, u.id) == 2000  # 清零再发到配额，非累加
```

- [ ] **Step 6: 跑测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credits_reset.py -q
```
Expected: PASS。

- [ ] **Step 7: 启动冒烟（调度器不崩）**

Run:
```bash
cd backend && FAKE_LLM=1 uv run python -c "from app.main import create_app; create_app(); print('app ok')"
```
Expected: 打印 `app ok`，无 import/调度器错误（此处仅构建 app，不进 lifespan；lifespan 由启动服务时触发）。

- [ ] **Step 8: Commit**

```bash
git add backend/app/credits/reset.py backend/app/core/scheduler.py backend/app/main.py backend/pyproject.toml backend/uv.lock backend/tests/test_credits_reset.py
git commit -m "feat(credits): monthly zero-and-refill reset via APScheduler"
```

---

### Task 6: 管理员积分/套餐调整 + 审计日志 + CLI

**Files:**
- Create: `backend/app/admin/deps.py`
- Create: `backend/app/admin/router.py`
- Create: `backend/app/admin/schemas.py`
- Create: `backend/scripts/admin.py`
- Modify: `backend/app/main.py`（挂 admin router）
- Test: `backend/tests/test_admin_api.py`

**Interfaces:**
- Consumes: `get_current_user`、`service.grant/charge`、`quota_for_plan`、`AdminAuditLog`。
- Produces:
  - `require_admin` 依赖（`user.role != "admin"` → 403）
  - `POST /api/admin/credits/adjust` `{user_id, delta, reason}` → grant/charge + 写 `AdminAuditLog(action="credit_adjust")`
  - `POST /api/admin/users/{user_id}/plan` `{plan}` → 设 `plan` + `monthly_quota=quota_for_plan(plan)` + 审计（不立即改 balance，下次重置生效；可选立即补差——本任务只改配额）
  - CLI `python -m scripts.admin set-admin <email>` / `grant <email> <amount>`

- [ ] **Step 1: require_admin**

`backend/app/admin/deps.py`:
```python
from fastapi import Depends, HTTPException

from app.auth.deps import get_current_user
from app.auth.models import User


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
```

- [ ] **Step 2: schemas**

`backend/app/admin/schemas.py`:
```python
from pydantic import BaseModel


class CreditAdjust(BaseModel):
    user_id: str
    delta: int
    reason: str = ""


class PlanChange(BaseModel):
    plan: str  # free / subscribed
```

- [ ] **Step 3: router**

`backend/app/admin/router.py`:
```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import require_admin
from app.admin.schemas import CreditAdjust, PlanChange
from app.auth.models import User
from app.credits import service
from app.credits.models import AdminAuditLog, CreditAccount
from app.credits.pricing import quota_for_plan
from app.core.db import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/credits/adjust")
async def adjust_credits(
    body: CreditAdjust, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    uid = uuid.UUID(body.user_id)
    await service.ensure_account(db, uid)
    if body.delta >= 0:
        await service.grant(db, uid, body.delta, kind="adjust", ref_type="admin", ref_id=str(admin.id))
    else:
        await service.charge(db, uid, -body.delta, kind="adjust", ref_type="admin", ref_id=str(admin.id))
    db.add(AdminAuditLog(
        admin_id=admin.id, action="credit_adjust", target_type="user", target_id=body.user_id,
        detail={"delta": body.delta, "reason": body.reason},
    ))
    await db.commit()
    return {"balance": await service.get_balance(db, uid)}


@router.post("/users/{user_id}/plan")
async def change_plan(
    user_id: str, body: PlanChange, admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.plan not in ("free", "subscribed"):
        raise HTTPException(400, "非法套餐")
    uid = uuid.UUID(user_id)
    acct = await service.ensure_account(db, uid)
    acct.plan = body.plan
    acct.monthly_quota = quota_for_plan(body.plan)
    db.add(AdminAuditLog(
        admin_id=admin.id, action="plan_change", target_type="user", target_id=user_id,
        detail={"plan": body.plan},
    ))
    await db.commit()
    return {"plan": acct.plan, "monthly_quota": acct.monthly_quota}
```
挂载：`app/main.py` `from app.admin.router import router as admin_router` + `app.include_router(admin_router)`。

- [ ] **Step 4: CLI**

`backend/scripts/admin.py`:
```python
"""管理 CLI：uv run python -m scripts.admin set-admin a@b.com / grant a@b.com 500"""
import asyncio
import sys

from sqlalchemy import select

from app.auth.models import User
from app.core.db import get_sessionmaker
from app.credits import service


async def _main(argv):
    cmd = argv[1]
    email = argv[2]
    async with get_sessionmaker()() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            print(f"no such user: {email}"); return
        if cmd == "set-admin":
            user.role = "admin"; await s.commit(); print(f"{email} is now admin")
        elif cmd == "grant":
            await service.ensure_account(s, user.id)
            await service.grant(s, user.id, int(argv[3]), kind="adjust", ref_type="cli")
            await s.commit(); print(f"granted {argv[3]} to {email}")
        else:
            print(f"unknown cmd: {cmd}")


if __name__ == "__main__":
    asyncio.run(_main(sys.argv))
```
（需 `backend/scripts/__init__.py` 空文件让 `-m scripts.admin` 可导入。）

- [ ] **Step 5: 测试**

`backend/tests/test_admin_api.py`（造一个 admin 用户 + 一个普通用户；复用注册夹具或直接建库对象并置 role）:
```python
import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.credits import service


@pytest.mark.asyncio
async def test_non_admin_forbidden(client, db_session, registered_user):
    resp = await client.post(
        "/api/admin/credits/adjust",
        json={"user_id": str(registered_user.id), "delta": 100, "reason": "x"},
        headers=_auth(registered_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_adjust_and_plan(client, db_session):
    admin = User(email=f"a-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role="admin")
    target = User(email=f"u-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"))
    db_session.add_all([admin, target]); await db_session.commit()
    await service.ensure_account(db_session, target.id); await db_session.commit()

    h = _auth(admin)
    r1 = await client.post("/api/admin/credits/adjust",
                           json={"user_id": str(target.id), "delta": 500, "reason": "vip"}, headers=h)
    assert r1.status_code == 200 and r1.json()["balance"] == 600
    r2 = await client.post(f"/api/admin/users/{target.id}/plan",
                           json={"plan": "subscribed"}, headers=h)
    assert r2.json()["monthly_quota"] == 2000
```
（`_auth(user)` 生成合法 access token 头——复用 conftest 里给已登录用户签 token 的辅助；若无，抽一个 `def _auth(user): return {"Authorization": f"Bearer {mint_access(user.id)}"}`，`mint_access` 用 `app/core/security.py` 的签发函数，函数名以实际为准。）

- [ ] **Step 6: 跑测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_admin_api.py -q
```
Expected: PASS（2 项）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/admin/ backend/scripts/ backend/app/main.py backend/tests/test_admin_api.py
git commit -m "feat(admin): credit/plan adjust API with audit log and CLI"
```

---

### Task 7: 积分查询 API + 前端余额展示 + 积分不足提示

**Files:**
- Create: `backend/app/credits/router.py`
- Modify: `backend/app/main.py`（挂 credits router）
- Create: `frontend/src/lib/credits.ts`
- Modify: 前端聊天页头部组件（显示余额徽章）、聊天发送错误处理（402 → 提示）
- Test: `backend/tests/test_credits_api.py`、`frontend/src/lib/credits.test.ts`

**Interfaces:**
- Produces:
  - `GET /api/credits` → `{"balance": int, "monthly_quota": int, "plan": str}`（当前用户，自动 `ensure_account`）
  - 前端 `fetchCredits(): Promise<{balance,monthly_quota,plan}>`（走 `apiFetch`）
  - 聊天 402 → 前端 toast/inline「积分不足，请联系管理员或等待月初重置」

- [ ] **Step 1: 后端 router**

`backend/app/credits/router.py`:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.credits import service
from app.core.db import get_db

router = APIRouter(prefix="/api/credits", tags=["credits"])


@router.get("")
async def get_credits(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    acct = await service.ensure_account(db, user.id)
    await db.commit()
    return {"balance": acct.balance, "monthly_quota": acct.monthly_quota, "plan": acct.plan}
```
挂载到 `main.py`。

- [ ] **Step 2: 后端测试**

`backend/tests/test_credits_api.py`:
```python
import pytest


@pytest.mark.asyncio
async def test_get_credits_returns_balance(client, registered_user):
    resp = await client.get("/api/credits", headers=_auth(registered_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["balance"] == 100 and body["monthly_quota"] == 100 and body["plan"] == "free"
```

- [ ] **Step 3: 跑后端测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credits_api.py -q
```
Expected: PASS。

- [ ] **Step 4: 前端 API 封装 + 测试**

`frontend/src/lib/credits.ts`:
```ts
import { apiFetch } from "./api";

export type Credits = { balance: number; monthly_quota: number; plan: string };

export async function fetchCredits(): Promise<Credits> {
  const res = await apiFetch("/api/credits");
  if (!res.ok) throw new Error("failed to load credits");
  return res.json();
}
```
`frontend/src/lib/credits.test.ts`（vitest，mock apiFetch）:
```ts
import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { fetchCredits } from "./credits";

describe("fetchCredits", () => {
  it("parses balance payload", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify({ balance: 100, monthly_quota: 100, plan: "free" }), { status: 200 }),
    );
    const c = await fetchCredits();
    expect(c.balance).toBe(100);
    expect(c.plan).toBe("free");
  });
});
```

- [ ] **Step 5: 前端余额徽章 + 402 处理**

在聊天页头部（先 Read `frontend/src/` 找到 sidebar/header 容器组件，如 `ThreadListSidebar` 顶栏或 App 布局）挂一个小徽章：进入时 `fetchCredits()`（TanStack Query `useQuery(['credits'], fetchCredits)`），显示 `余额 {balance}/{monthly_quota}`。发送消息失败时若响应 402，展示内联提示「积分不足，请联系管理员或等待月初重置」。RuntimeProvider 的 `onError`/请求失败回调里判状态码 402 → 触发提示（复用现有错误展示；无则用一个简单顶部 banner state）。发送成功后 `queryClient.invalidateQueries(['credits'])` 刷新余额。
给徽章根元素加 `data-testid="credit-badge"` 以便后续 e2e 断言。

- [ ] **Step 6: 前端测试 + 构建**

Run:
```bash
cd frontend && npx vitest run && npm run build
```
Expected: 全绿 + 构建成功。

- [ ] **Step 7: 手工冒烟**

Run（需本机 dev postgres 5434、redis 6381）：起后端 `FAKE_LLM=1 uv run uvicorn app.main:app --port 8000` + 前端 `npm run dev`，注册→登录→看到余额徽章 `100/100`→发一条消息→余额下降→刷新仍显示。贴结果。

- [ ] **Step 8: Commit**

```bash
git add backend/app/credits/router.py backend/app/main.py backend/tests/test_credits_api.py frontend/src/
git commit -m "feat(credits): balance API and frontend badge with insufficient-credit notice"
```

---

### Task 8: 邮件 SMTP（按设置切换，配置错即报错）

**Files:**
- Modify: `backend/app/auth/emailer.py`
- Modify: `backend/app/core/config.py`（SMTP 设置）
- Modify: `backend/pyproject.toml`（加 `aiosmtplib`）
- Test: `backend/tests/test_emailer.py`

**Interfaces:**
- Consumes: `Settings.email_backend`。
- Produces:
  - `class SmtpEmailSender`（aiosmtplib 发信）
  - `get_email_sender()` 依 `email_backend` 返回 console/smtp；未知值 → 抛 `RuntimeError`（fail-loud，杜绝"设置形同虚设"）；smtp 缺关键配置 → 抛 `RuntimeError`。

- [ ] **Step 1: 加依赖**

Run:
```bash
cd backend && uv add aiosmtplib
```

- [ ] **Step 2: 配置**

`Settings` 加：
```python
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
```

- [ ] **Step 3: emailer**

`backend/app/auth/emailer.py` 改为：
```python
from typing import Protocol

import aiosmtplib
from email.message import EmailMessage

from app.core.config import get_settings


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    async def send(self, to: str, subject: str, body: str) -> None:
        print(f"[email → {to}] {subject}: {body}")


class SmtpEmailSender:
    async def send(self, to: str, subject: str, body: str) -> None:
        s = get_settings()
        if not (s.smtp_host and s.smtp_user and s.smtp_from):
            raise RuntimeError("SMTP 未正确配置（smtp_host/smtp_user/smtp_from 必填）")
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg, hostname=s.smtp_host, port=s.smtp_port,
            username=s.smtp_user, password=s.smtp_password, use_tls=s.smtp_use_tls,
        )


def get_email_sender() -> EmailSender:
    backend = get_settings().email_backend
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "smtp":
        return SmtpEmailSender()
    raise RuntimeError(f"未知 EMAIL_BACKEND: {backend!r}")
```

- [ ] **Step 4: 测试**

`backend/tests/test_emailer.py`:
```python
import pytest

from app.auth import emailer


def test_console_backend(monkeypatch):
    monkeypatch.setattr("app.auth.emailer.get_settings",
                        lambda: type("S", (), {"email_backend": "console"})())
    assert isinstance(emailer.get_email_sender(), emailer.ConsoleEmailSender)


def test_unknown_backend_fails_loud(monkeypatch):
    monkeypatch.setattr("app.auth.emailer.get_settings",
                        lambda: type("S", (), {"email_backend": "carrier-pigeon"})())
    with pytest.raises(RuntimeError):
        emailer.get_email_sender()


@pytest.mark.asyncio
async def test_smtp_missing_config_raises(monkeypatch):
    cfg = type("S", (), {
        "email_backend": "smtp", "smtp_host": "", "smtp_user": "", "smtp_from": "",
        "smtp_port": 465, "smtp_password": "", "smtp_use_tls": True,
    })()
    monkeypatch.setattr("app.auth.emailer.get_settings", lambda: cfg)
    with pytest.raises(RuntimeError):
        await emailer.SmtpEmailSender().send("a@b.com", "s", "b")
```

- [ ] **Step 5: 跑测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_emailer.py -q
```
Expected: PASS（3 项）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/auth/emailer.py backend/app/core/config.py backend/pyproject.toml backend/uv.lock backend/tests/test_emailer.py
git commit -m "feat(auth): settings-driven SMTP email sender with fail-loud config"
```

---

### Task 9: 真实模式 skill 枚举修复（skill 拷入工作区）

**Files:**
- Modify: `backend/app/agent/workspace.py`（首次建 workspace 时把 `skills_data/skills` 拷入 `{ws}/skills`）
- Modify: `backend/app/agent/build.py`（`skills=[str(ws / "skills")]`）
- Test: `backend/tests/test_workspace.py`（加 skill 拷贝断言）、`backend/tests/test_agent_build.py`（若存在，确认 skills 指向 ws 内）

**Interfaces:**
- 背景：现 `build.py` 用 `skills=[str(SKILLS_DATA / "skills")]`（在沙箱 root 外），`SandboxedFilesystemBackend._contained` 拒绝越界 → 真实模式 skill 枚举被拒。修法：像 `tools/` 一样把 skills 拷入每 thread 工作区，指向 `{ws}/skills`（沙箱 root 内）。
- Produces: `get_thread_workspace(thread_id)` 首次创建时 `{ws}/skills` 存在且内容 = `skills_data/skills`。

- [ ] **Step 1: 看现状**

Run:
```bash
cd backend && grep -n "copytree\|tools\|skills" app/agent/workspace.py && grep -n "skills=" app/agent/build.py
```
确认现有 tools 拷贝行（`shutil.copytree(SKILLS_DATA / "tools", ws / "tools")`）位置。

- [ ] **Step 2: 拷 skills**

`backend/app/agent/workspace.py` 在拷 tools 的相邻处补拷 skills（同样只在 workspace 首次创建、目标不存在时拷）：
```python
        shutil.copytree(SKILLS_DATA / "tools", ws / "tools")
        shutil.copytree(SKILLS_DATA / "skills", ws / "skills")
```
（放在同一 `if 首次创建` 分支内，保持幂等；若 tools 拷贝有 `dirs_exist_ok` 之类参数，skills 对齐同样处理。）

- [ ] **Step 3: build 指向 ws 内 skills**

`backend/app/agent/build.py`:
```python
    ws = get_thread_workspace(thread_id)
    ...
        skills=[str(ws / "skills")],
```
（原 `skills=[str(SKILLS_DATA / "skills")]` 改为 `str(ws / "skills")`；`SKILLS_DATA` import 若仅此处用可保留或清理。）

- [ ] **Step 4: 测试断言 skills 落入 ws**

`backend/tests/test_workspace.py` 加：
```python
def test_workspace_copies_skills(tmp_path, monkeypatch):
    import app.agent.workspace as ws_mod
    monkeypatch.setattr(ws_mod, "WORKSPACES_ROOT", tmp_path / "ws")
    ws = ws_mod.get_thread_workspace("thread-abc")
    assert (ws / "skills").is_dir()
    # skills_data/skills 下至少一个 SKILL.md 被拷入
    assert any((ws / "skills").rglob("SKILL.md"))
```
（`WORKSPACES_ROOT` monkeypatch 名称以 `test_workspace.py` 既有夹具为准，若已有 patch 方式复用之。）

- [ ] **Step 5: 跑测试**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_workspace.py tests/test_agent_build.py -q
```
Expected: PASS。

- [ ] **Step 6: 真实枚举冒烟（可选，需有效 key）**

Run:
```bash
cd backend && RUN_REAL_SMOKE=1 TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_real_smoke.py -q -s
```
Expected: 通过且**不再**打印 `路径越界被拒绝（escape denied）` 关于 skills 的告警（grep 输出确认）。若无有效 key 则跳过，注明。

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/workspace.py backend/app/agent/build.py backend/tests/test_workspace.py
git commit -m "fix(agent): copy skills into thread workspace so real-mode enumeration works"
```

---

### Task 10: 集成闭环 + README + CI

**Files:**
- Create: `backend/tests/test_credits_flow.py`（端到端集成：预检拒绝 → 充值 → 通过 → 流水存在）
- Modify: `backend/README.md`（补"积分计费（计划 3）"一节）
- Modify: `.github/workflows/ci.yml`（若 redis 为后端测试硬依赖则加 service；当前限频测试打桩 redis、其余走 testcontainers，理论上 CI 无需真 redis——确认后决定是否加）

**Interfaces:**
- 串起 Task 2/3/6：一个用户余额扣到 0 → 聊天 402 → 管理员 grant → 聊天 200 且新增 `kind="chat"` 流水。

- [ ] **Step 1: 集成测试**

`backend/tests/test_credits_flow.py`:
```python
import uuid

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.core.security import hash_password
from app.credits import service
from app.credits.models import CreditTransaction


@pytest.mark.asyncio
async def test_precheck_block_then_grant_then_charge(client, db_session, registered_user, a_thread):
    # 扣空
    await service.charge(db_session, registered_user.id, 1000, kind="adjust")
    await db_session.commit()
    r1 = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r1.status_code == 402

    # 管理员补
    admin = User(email=f"adm-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role="admin")
    db_session.add(admin); await db_session.commit()
    r2 = await client.post("/api/admin/credits/adjust",
                           json={"user_id": str(registered_user.id), "delta": 50, "reason": "test"},
                           headers=_auth(admin))
    assert r2.status_code == 200

    # 再聊成功且有 chat 流水
    r3 = await client.post("/api/chat", json=_chat_body(a_thread), headers=_auth(registered_user))
    assert r3.status_code == 200
    await r3.aread()
    txs = (await db_session.execute(
        select(CreditTransaction).where(
            CreditTransaction.user_id == registered_user.id, CreditTransaction.kind == "chat"
        )
    )).scalars().all()
    assert len(txs) >= 1
```
（复用 conftest 的 `registered_user/a_thread/_chat_body/_auth`。db_session 与 client 需共享同一 testcontainer DB——沿用现有 conftest 保证。）

- [ ] **Step 2: 跑集成**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credits_flow.py -q
```
Expected: PASS。

- [ ] **Step 3: 全量回归**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q
cd ../frontend && npx vitest run
```
Expected: 后端全绿（含新增），前端全绿。

- [ ] **Step 4: README**

`backend/README.md` 补"积分计费（计划 3）"：账户/流水模型、记账函数与行锁、预检+token 折算扣费、15 分钟超时、限频（redis 6381）、月度重置（APScheduler 北京时间月初）、管理 CLI（set-admin/grant）、SMTP 设置项、真实模式 skill 已拷入工作区。列出新增 env：`REDIS_URL`、`RATE_LIMIT_PER_MIN`、`TOKENS_PER_CREDIT`、`SMTP_*`、`EMAIL_BACKEND`。

- [ ] **Step 5: CI 决策**

Read `.github/workflows/ci.yml`。若后端测试不依赖真实 redis（限频已打桩），无需加 redis service，仅在 README 注明本地限频需 redis。若发现某测试连真 redis，则给 backend job 加：
```yaml
    services:
      redis:
        image: redis:7
        ports: ["6379:6379"]
```
并设 `REDIS_URL=redis://localhost:6379/0`。记录决策于 commit message。

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_credits_flow.py backend/README.md .github/workflows/ci.yml
git commit -m "test(credits): end-to-end billing flow, README and CI notes"
```

---

## Self-Review 记录

**1. Spec 覆盖**（对 §7.2 积分 / §7.3 管理 / §4.3 执行流程 / §4.5 失败处理 / §11 风险）：
- §7.2 `credit_accounts`+`credit_transactions`、余额流水推导、记账函数单事务+行锁 → Task 1/2 ✅；免费 100/订阅 2000、清零再发月初重置北京时间 APScheduler → Task 5 ✅；执行前预检/执行后实扣/失败按实际消耗 → Task 3 ✅；token 折算参数可配 → Task 2 pricing + config ✅。
- §7.3 `users.role`+admin 保护 API + CLI + `admin_audit_log` → Task 6 ✅（**兑换码生成 + subscriptions 表 + PaymentProvider 显式延后**，见下）。
- §4.3 步骤 1「积分余额预检」+ 步骤 5「结束后记账写 credit_transactions」 → Task 3 ✅（**已安装 skill 查询 + skill 固定价**依赖 skills 表，归计划 4）。
- §4.5「整体超时 15 分钟强制终止，按已消耗记账」 → Task 3 `asyncio.timeout(900)` + finally 扣费 ✅。
- §11「长任务成本失控 → 积分预检 + 15 分钟超时 + 按 skill 定价」 → 预检/超时 Task 3 ✅，按 skill 定价归计划 4。
- 上线前置：SMTP（§7.1）→ Task 8 ✅；真实模式 skill 枚举修复（延后清单 P0）→ Task 9 ✅。

**2. 占位符扫描**：无 TBD/TODO 空壳。唯一"未来挂钩"是 skill 固定定价（明确 gated on 计划 4 skills 表），已在 Global Constraints 与 Task 3 说明，非本计划占位。各步均有真实代码/命令/期望输出。

**3. 类型一致性**：`ensure_account/get_balance/precheck/charge/grant/InsufficientCredits`（Task 2 定义）在 Task 3/5/6/7/10 一致消费；`tokens_to_credits/quota_for_plan`（Task 2）在 Task 3/5/6 一致；`CreditAccount/CreditTransaction/AdminAuditLog`（Task 1）字段在各 Task 引用一致；`require_admin`（Task 6）；`check_rate`（Task 4）；`reset_all_accounts`（Task 5）在 scheduler 一致；`get_email_sender/SmtpEmailSender`（Task 8）。`kind` 取值全程用 `grant/reset/chat/adjust` 统一。

**本计划显式延后（记入 .superpowers/sdd/progress.md 延后清单）**：
- 兑换码系统（生成/兑换）+ `subscriptions` 表 + `PaymentProvider` 抽象 → 独立"订阅/支付"计划（一期靠 admin 手动调 plan 已够验证与运营兜底）。
- skill 固定定价扣费挂钩 → 计划 4（skill 市场，建 `skills` 表后）。
- 前端管理 UI（无，spec 明确不做）；本计划管理走 API+CLI。
- 限频用固定窗口（非滑动/令牌桶），够一期；精细化留后。
- 扣费按 total_tokens 折算，未区分 flash/pro 单价——spec 允许"参数可配"，差异化单价留计划 4 与 skill 定价一起做。
