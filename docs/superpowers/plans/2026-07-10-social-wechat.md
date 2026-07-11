# 社媒板块（微信公众号）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 D-sight 新增微信公众号信源：用户扫码登录自己的公众号进入共享凭证池，搜索/订阅公众号，定时增量抓取文章元数据，正文懒抓为纯文本落库，agent 可查询。

**Architecture:** 后端新增 `app/social/` 模块（仿 `app/news/`）。凭证池：任一有效凭证可抓任意订阅号。抓取移植参考库 `wechat-article-exporter` 的 `getqrcode→ask→bizlogin` 登录与 `searchbiz`/`appmsgpublish` 接口。全局实体 `wechat_accounts`/`wechat_articles` + 用户 `wechat_subscriptions`。前端替换 `SocialPanel.tsx` 占位。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2 async / Alembic / httpx / APScheduler / redis.asyncio / cryptography(Fernet) / selectolax；React + Vite + vitest。

## Global Constraints

- 后端测试：`TESTCONTAINERS_RYUK_DISABLED=true uv run pytest`（testcontainers 起 pgvector/pgvector:pg16，自动 `alembic upgrade head`）。所有后端测试 async，用 `@pytest.mark.asyncio`。
- 鉴权：全部 `/api/social/*` 走 `Depends(get_current_user)`。测试签 token 用 `create_access_token(str(user.id))`。
- 微信返回码：`base_resp.ret == 0` 成功；`== 200003` → 会话失效（凭证标 expired）；其他非零 → 临时错误（退避/跳过，**不**标 expired）。
- 文章唯一键 `external_id = appmsgex.aid`。字段映射：`title←title`、`digest←digest`、`cover_url←cover`、`url←link`、`published_at←create_time`(unix 秒 → UTC)。
- `appmsgpublish` 响应双层 JSON 字符串：`publish_page`(str)→`publish_list[]`→每项 `publish_info`(str)→`appmsgex[]`。
- cookies/token 敏感 → Fernet 加密入库。
- 轮询默认间隔 30 分钟，单次 `count=20`。
- 敏感操作绝不向 agent 循环抛异常：工具内 try/except 返错误字符串（同 `news_query`）。
- 请求头固定：`Referer/Origin: https://mp.weixin.qq.com`，桌面 UA。
- 新 alembic 迁移 `down_revision = 'b1c2d3e4f5a6'`（当前 head）。

---

## File Structure

后端（`backend/`）：
- `app/social/__init__.py`
- `app/social/crypto.py` — Fernet 加解密（Task 1）
- `app/social/models.py` — 4 张表（Task 2）
- `app/social/schemas.py` — Pydantic Out（Task 10）
- `app/social/wechat/__init__.py`
- `app/social/wechat/errors.py` — 异常 + 返回码分类（Task 3）
- `app/social/wechat/parser.py` — appmsgpublish 解析 + HTML→纯文本（Task 3）
- `app/social/wechat/client.py` — httpx 接口封装（Task 4）
- `app/social/wechat/session_store.py` — 登录 session（Redis，Task 5）
- `app/social/wechat/login.py` — 扫码登录（Task 5）
- `app/social/credentials.py` — 凭证池 pick/expire（Task 6）
- `app/social/ingest.py` — account get-or-create + 抓取去重 + 懒抓（Task 7）
- `app/social/job.py` — 定时轮询（Task 8）
- `app/social/router.py` — API（Task 10）
- `app/agent/tools/social.py` — agent 工具（Task 9）
- 改：`app/core/config.py`、`alembic/env.py`、`alembic/versions/<new>_social.py`、`app/core/scheduler.py`、`app/agent/build.py`、`app/main.py`、`pyproject.toml`

前端（`frontend/`）：
- `src/lib/social.ts` + `src/lib/social.test.ts`（Task 11）
- 改：`src/panels/SocialPanel.tsx`（Task 11）

---

## Task 1: 依赖 + 配置 + Fernet 加解密

**Files:**
- Modify: `backend/pyproject.toml`（加 `cryptography`、`selectolax`）
- Modify: `backend/app/core/config.py`（加 3 项 settings）
- Create: `backend/app/social/__init__.py`（空文件）
- Create: `backend/app/social/crypto.py`
- Test: `backend/tests/test_social_crypto.py`

**Interfaces:**
- Produces: `app.social.crypto.encrypt(plaintext: str) -> str`、`decrypt(token: str) -> str`
- Produces: settings `social_encryption_key: str`、`social_poll_minutes: int`、`social_fetch_count: int`

- [ ] **Step 1: 加依赖**

`backend/pyproject.toml` 的 `dependencies` 列表加两行：

```toml
    "cryptography>=44.0.0",
    "selectolax>=0.3.21",
```

Run: `cd backend && uv sync`
Expected: 安装成功。

- [ ] **Step 2: 加配置项**

`backend/app/core/config.py` 的 `Settings` 类内、`news_backend` 后加：

```python
    news_backend: str = "fake"
    # Fernet 密钥（base64 urlsafe 32 字节）。留空则用 dev 默认（仅测试/本地）。
    social_encryption_key: str = "ZHNpZ2h0LXNvY2lhbC1kZXYtZmVybmV0LWtleS0zMmI="
    social_poll_minutes: int = 30
    social_fetch_count: int = 20
```

- [ ] **Step 3: 建空包**

Run: `mkdir -p backend/app/social/wechat && touch backend/app/social/__init__.py backend/app/social/wechat/__init__.py`

- [ ] **Step 4: 写失败测试**

`backend/tests/test_social_crypto.py`：

```python
import pytest


def test_encrypt_decrypt_roundtrip():
    from app.social.crypto import decrypt, encrypt

    secret = "token=abc123; cookie=xyz"
    enc = encrypt(secret)
    assert enc != secret
    assert decrypt(enc) == secret


def test_encrypt_nondeterministic_but_decryptable():
    from app.social.crypto import decrypt, encrypt

    a = encrypt("same")
    b = encrypt("same")
    assert a != b  # Fernet 带随机 IV
    assert decrypt(a) == decrypt(b) == "same"
```

- [ ] **Step 5: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_social_crypto.py -q`
Expected: FAIL（`ModuleNotFoundError: app.social.crypto`）

- [ ] **Step 6: 实现 crypto.py**

`backend/app/social/crypto.py`：

```python
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().social_encryption_key.encode()
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_social_crypto.py -q`
Expected: PASS（2 passed）

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/config.py backend/app/social/ backend/tests/test_social_crypto.py
git commit -m "feat(social): deps, config, Fernet crypto helper"
```

---

## Task 2: 数据模型 + Alembic 迁移

**Files:**
- Create: `backend/app/social/models.py`
- Modify: `backend/alembic/env.py`（注册 metadata import）
- Create: `backend/alembic/versions/c7d8e9f0a1b2_social.py`
- Test: `backend/tests/test_social_models.py`

**Interfaces:**
- Produces: ORM 类 `WechatCredential`、`WechatAccount`、`WechatArticle`、`WechatSubscription`（`app.social.models`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_social_models.py`：

```python
import datetime as dt

import pytest

from app.social.models import (
    WechatAccount,
    WechatArticle,
    WechatCredential,
    WechatSubscription,
)


@pytest.mark.asyncio
async def test_create_account_article_credential(db_session):
    acc = WechatAccount(fakeid="fake1", name="某公众号")
    db_session.add(acc)
    await db_session.flush()

    art = WechatArticle(
        account_id=acc.id, external_id="aid1", title="标题", url="https://mp/s/x",
        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
    )
    db_session.add(art)

    cred = WechatCredential(
        user_id=None, token="enc-t", cookies="enc-c", nickname="我的号",
        expires_at=dt.datetime(2026, 7, 14, tzinfo=dt.UTC), status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    assert art.content is None  # 懒抓，初始空
    assert cred.status == "active"
```

（注：`user_id=None` 仅为模型冒烟；真实凭证必绑 user，见 Task 5。若 FK NOT NULL 阻止，改为先建一个 User。此处 `user_id` 列允许为 test 简化——按 Step 3 定义为 nullable=False 时，本测试改为省略 cred 段，只测 account+article。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_models.py -q`
Expected: FAIL（`ModuleNotFoundError: app.social.models`）

- [ ] **Step 3: 实现 models.py**

`backend/app/social/models.py`：

```python
import datetime as dt
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WechatCredential(Base):
    __tablename__ = "wechat_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(Text, nullable=False)       # Fernet 加密
    cookies: Mapped[str] = mapped_column(Text, nullable=False)     # Fernet 加密
    nickname: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(512))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active/expired
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WechatAccount(Base):
    __tablename__ = "wechat_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fakeid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(512))
    signature: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WechatArticle(Base):
    __tablename__ = "wechat_articles"
    __table_args__ = (UniqueConstraint("account_id", "external_id", name="uq_wechat_account_external"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wechat_accounts.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)  # = aid
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    digest: Mapped[str | None] = mapped_column(String(1024))
    cover_url: Mapped[str | None] = mapped_column(String(1024))
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)  # 纯文本正文，懒抓填充
    content_fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WechatSubscription(Base):
    __tablename__ = "wechat_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_wechat_sub_user_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wechat_accounts.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: 注册到 alembic env**

`backend/alembic/env.py`，在 `from app.news import models as news_models  # noqa: F401` 后加：

```python
from app.social import models as social_models  # noqa: F401
```

- [ ] **Step 5: 写迁移**

`backend/alembic/versions/c7d8e9f0a1b2_social.py`：

```python
"""social wechat

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-07-10 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wechat_credentials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("cookies", sa.Text(), nullable=False),
        sa.Column("nickname", sa.String(length=128), nullable=False),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_wechat_credentials_user_id"), "wechat_credentials", ["user_id"])

    op.create_table(
        "wechat_accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("fakeid", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column("signature", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fakeid", name="uq_wechat_accounts_fakeid"),
    )

    op.create_table(
        "wechat_articles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("digest", sa.String(length=1024), nullable=True),
        sa.Column("cover_url", sa.String(length=1024), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "external_id", name="uq_wechat_account_external"),
    )
    op.create_index(op.f("ix_wechat_articles_account_id"), "wechat_articles", ["account_id"])
    op.create_index(op.f("ix_wechat_articles_published_at"), "wechat_articles", ["published_at"])

    op.create_table(
        "wechat_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "account_id", name="uq_wechat_sub_user_account"),
    )
    op.create_index(op.f("ix_wechat_subscriptions_user_id"), "wechat_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_table("wechat_subscriptions")
    op.drop_table("wechat_articles")
    op.drop_table("wechat_accounts")
    op.drop_table("wechat_credentials")
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_models.py -q`
Expected: PASS（迁移随容器启动执行；建表成功）

- [ ] **Step 7: Commit**

```bash
git add backend/app/social/models.py backend/alembic/env.py backend/alembic/versions/c7d8e9f0a1b2_social.py backend/tests/test_social_models.py
git commit -m "feat(social): 4 tables + alembic migration"
```

---

## Task 3: 返回码分类 + 响应/HTML 解析（纯函数）

**Files:**
- Create: `backend/app/social/wechat/errors.py`
- Create: `backend/app/social/wechat/parser.py`
- Test: `backend/tests/test_social_parser.py`

**Interfaces:**
- Produces: `errors.SessionExpiredError`、`errors.TransientMpError`、`errors.check_base_resp(data: dict) -> dict`
- Produces: `parser.RawArticle`(dataclass: `external_id, title, digest, cover_url, url, published_at`)
- Produces: `parser.parse_appmsgpublish(data: dict) -> list[RawArticle]`
- Produces: `parser.html_to_text(html: str) -> str`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_social_parser.py`：

```python
import datetime as dt
import json

import pytest

from app.social.wechat.errors import (
    SessionExpiredError,
    TransientMpError,
    check_base_resp,
)
from app.social.wechat.parser import RawArticle, html_to_text, parse_appmsgpublish


def test_check_base_resp_ok():
    assert check_base_resp({"base_resp": {"ret": 0}, "x": 1}) == {"base_resp": {"ret": 0}, "x": 1}


def test_check_base_resp_session_expired():
    with pytest.raises(SessionExpiredError):
        check_base_resp({"base_resp": {"ret": 200003, "err_msg": "invalid session"}})


def test_check_base_resp_transient():
    with pytest.raises(TransientMpError):
        check_base_resp({"base_resp": {"ret": 200013, "err_msg": "freq control"}})


def test_parse_appmsgpublish_double_json():
    appmsgex = [
        {"aid": "111_1", "title": "文章A", "digest": "摘要A", "cover": "http://c/a.jpg",
         "link": "https://mp.weixin.qq.com/s/AAA", "create_time": 1751000000},
        {"aid": "111_2", "title": "文章B", "digest": "", "cover": "",
         "link": "https://mp.weixin.qq.com/s/BBB", "create_time": 1751000100},
    ]
    publish_info = json.dumps({"appmsgex": appmsgex})
    publish_page = json.dumps({"publish_list": [{"publish_info": publish_info}], "total_count": 2})
    data = {"base_resp": {"ret": 0}, "publish_page": publish_page}

    arts = parse_appmsgpublish(data)
    assert [a.external_id for a in arts] == ["111_1", "111_2"]
    assert arts[0].title == "文章A"
    assert arts[0].url == "https://mp.weixin.qq.com/s/AAA"
    assert arts[0].published_at == dt.datetime.fromtimestamp(1751000000, tz=dt.UTC)
    assert arts[1].digest is None  # 空串归一为 None


def test_parse_appmsgpublish_empty_list():
    data = {"base_resp": {"ret": 0}, "publish_page": json.dumps({"publish_list": [], "total_count": 0})}
    assert parse_appmsgpublish(data) == []


def test_html_to_text_extracts_js_content():
    html = """
    <html><body>
      <div id="js_content"><p>第一段。</p><p>第二段。</p><img src="x"/></div>
      <script>ignore()</script>
    </body></html>
    """
    text = html_to_text(html)
    assert "第一段。" in text
    assert "第二段。" in text
    assert "ignore" not in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_social_parser.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 errors.py**

`backend/app/social/wechat/errors.py`：

```python
class MpError(Exception):
    """微信接口错误基类。"""


class SessionExpiredError(MpError):
    """会话失效（ret=200003）→ 凭证应标记 expired。"""


class TransientMpError(MpError):
    """临时错误（频控等非零码）→ 退避/跳过，不标 expired。"""


def check_base_resp(data: dict) -> dict:
    """校验微信响应；非 0 抛对应异常，成功原样返回 data。"""
    ret = data.get("base_resp", {}).get("ret", 0)
    if ret == 0:
        return data
    err = data.get("base_resp", {}).get("err_msg", "")
    if ret == 200003:
        raise SessionExpiredError(f"{ret}:{err}")
    raise TransientMpError(f"{ret}:{err}")
```

- [ ] **Step 4: 实现 parser.py**

`backend/app/social/wechat/parser.py`：

```python
import datetime as dt
import json
from dataclasses import dataclass

from selectolax.parser import HTMLParser

from app.social.wechat.errors import check_base_resp


@dataclass
class RawArticle:
    external_id: str
    title: str
    digest: str | None
    cover_url: str | None
    url: str
    published_at: dt.datetime


def _nz(s: str | None) -> str | None:
    """空串归一为 None。"""
    return s or None


def parse_appmsgpublish(data: dict) -> list[RawArticle]:
    check_base_resp(data)
    page = json.loads(data["publish_page"])
    out: list[RawArticle] = []
    for item in page.get("publish_list", []):
        info_raw = item.get("publish_info")
        if not info_raw:
            continue
        info = json.loads(info_raw)
        for a in info.get("appmsgex", []):
            out.append(RawArticle(
                external_id=str(a["aid"]),
                title=a.get("title", ""),
                digest=_nz(a.get("digest")),
                cover_url=_nz(a.get("cover")),
                url=a.get("link", ""),
                published_at=dt.datetime.fromtimestamp(int(a.get("create_time", 0)), tz=dt.UTC),
            ))
    return out


def html_to_text(html: str) -> str:
    """抠 #js_content 正文区，剥成纯文本（段落间换行）。找不到则退化为全文文本。"""
    tree = HTMLParser(html)
    node = tree.css_first("#js_content")
    target = node if node is not None else tree.body
    if target is None:
        return ""
    for bad in target.css("script, style"):
        bad.decompose()
    text = target.text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_social_parser.py -q`
Expected: PASS（6 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/social/wechat/errors.py backend/app/social/wechat/parser.py backend/tests/test_social_parser.py
git commit -m "feat(social): ret-code classification + appmsgpublish/html parsers"
```

---

## Task 4: 微信 httpx 客户端

**Files:**
- Create: `backend/app/social/wechat/client.py`
- Test: `backend/tests/test_social_client.py`

**Interfaces:**
- Produces: `client.ActiveCred`(dataclass: `id: uuid.UUID, token: str, cookies: str`)
- Produces: `client.new_mp_client() -> httpx.AsyncClient`
- Produces: `async client.search_biz(http, cred, keyword, begin=0, size=5) -> list[dict]`（每项 `{fakeid, nickname, avatar, signature}`）
- Produces: `async client.appmsg_publish(http, cred, fakeid, begin=0, count=20) -> list[RawArticle]`
- Produces: `async client.fetch_article_text(http, url) -> str`
- Consumes: `parser.RawArticle/parse_appmsgpublish/html_to_text`、`errors.check_base_resp`

- [ ] **Step 1: 写失败测试**（用 `httpx.MockTransport` 注入假响应）

`backend/tests/test_social_client.py`：

```python
import json
import uuid

import httpx
import pytest

from app.social.wechat.client import ActiveCred, appmsg_publish, search_biz


def _cred():
    return ActiveCred(id=uuid.uuid4(), token="tok", cookies="slave_sid=abc")


@pytest.mark.asyncio
async def test_search_biz_maps_fields_and_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["cookie"] = request.headers.get("cookie")
        body = {"base_resp": {"ret": 0}, "list": [
            {"fakeid": "F1", "nickname": "号A", "round_head_img": "http://a", "signature": "sig"},
        ]}
        return httpx.Response(200, json=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with http:
        rows = await search_biz(http, _cred(), "关键词")

    assert rows == [{"fakeid": "F1", "nickname": "号A", "avatar": "http://a", "signature": "sig"}]
    assert "token=tok" in captured["url"]
    assert "query=" in captured["url"]
    assert captured["cookie"] == "slave_sid=abc"


@pytest.mark.asyncio
async def test_appmsg_publish_parses_articles():
    appmsgex = [{"aid": "9_1", "title": "T", "digest": "d", "cover": "c",
                 "link": "https://mp/s/x", "create_time": 1751000000}]
    publish_info = json.dumps({"appmsgex": appmsgex})
    publish_page = json.dumps({"publish_list": [{"publish_info": publish_info}], "total_count": 1})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": publish_page})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with http:
        arts = await appmsg_publish(http, _cred(), "F1")

    assert len(arts) == 1
    assert arts[0].external_id == "9_1"


@pytest.mark.asyncio
async def test_session_expired_propagates():
    from app.social.wechat.errors import SessionExpiredError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"base_resp": {"ret": 200003, "err_msg": "x"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with http:
        with pytest.raises(SessionExpiredError):
            await appmsg_publish(http, _cred(), "F1")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_social_client.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 client.py**

`backend/app/social/wechat/client.py`：

```python
import uuid
from dataclasses import dataclass

import httpx

from app.social.wechat.parser import RawArticle, parse_appmsgpublish

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_BASE_HEADERS = {
    "Referer": "https://mp.weixin.qq.com/",
    "Origin": "https://mp.weixin.qq.com",
    "User-Agent": _UA,
    "Accept-Encoding": "identity",
}


@dataclass
class ActiveCred:
    id: uuid.UUID
    token: str
    cookies: str  # 已解密的 cookie 串


def new_mp_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=_BASE_HEADERS, timeout=30, follow_redirects=True)


async def _mp_get_json(http: httpx.AsyncClient, endpoint: str, params: dict, cred: ActiveCred) -> dict:
    from app.social.wechat.errors import check_base_resp

    p = {**params, "token": cred.token, "lang": "zh_CN", "f": "json", "ajax": "1"}
    r = await http.get(endpoint, params=p, headers={"Cookie": cred.cookies})
    r.raise_for_status()
    return check_base_resp(r.json())


async def search_biz(
    http: httpx.AsyncClient, cred: ActiveCred, keyword: str, begin: int = 0, size: int = 5
) -> list[dict]:
    data = await _mp_get_json(
        http, "https://mp.weixin.qq.com/cgi-bin/searchbiz",
        {"action": "search_biz", "begin": begin, "count": size, "query": keyword}, cred,
    )
    return [
        {
            "fakeid": it.get("fakeid"),
            "nickname": it.get("nickname"),
            "avatar": it.get("round_head_img"),
            "signature": it.get("signature"),
        }
        for it in data.get("list", [])
    ]


async def appmsg_publish(
    http: httpx.AsyncClient, cred: ActiveCred, fakeid: str, begin: int = 0, count: int = 20
) -> list[RawArticle]:
    data = await _mp_get_json(
        http, "https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
        {
            "sub": "list", "search_field": "null", "begin": begin, "count": count,
            "query": "", "fakeid": fakeid, "type": "101_1", "free_publish_type": 1,
            "sub_action": "list_ex",
        },
        cred,
    )
    return parse_appmsgpublish(data)


async def fetch_article_text(http: httpx.AsyncClient, url: str) -> str:
    from app.social.wechat.parser import html_to_text

    r = await http.get(url)
    r.raise_for_status()
    return html_to_text(r.text)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_social_client.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/social/wechat/client.py backend/tests/test_social_client.py
git commit -m "feat(social): wechat httpx client (searchbiz/appmsgpublish/article)"
```

---

## Task 5: 扫码登录（session store + login）

**Files:**
- Create: `backend/app/social/wechat/session_store.py`
- Create: `backend/app/social/wechat/login.py`
- Test: `backend/tests/test_social_login.py`

**Interfaces:**
- Produces: `session_store.save(session_id, cookies)`、`session_store.load(session_id) -> str | None`、`session_store.delete(session_id)`（async）
- Produces: `login.start_qrcode() -> tuple[str, bytes]`（session_id, qrcode png 字节）
- Produces: `async login.poll_status(db, session_id, user_id) -> dict`（`{"status": "waiting"|"scanned"|"confirmed", "nickname": str | None}`；confirmed 时落库凭证）
- Consumes: `client.new_mp_client`、`crypto.encrypt`、`models.WechatCredential`

- [ ] **Step 1: 写失败测试**（monkeypatch session_store 与 httpx）

`backend/tests/test_social_login.py`：

```python
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.social.models import WechatCredential


@pytest.mark.asyncio
async def test_poll_confirmed_stores_encrypted_credential(db_session, monkeypatch):
    from app.social import crypto
    from app.social.wechat import login, session_store

    # 假 session cookies
    async def fake_load(sid):
        return "uuid=UU"
    async def fake_delete(sid):
        return None
    monkeypatch.setattr(session_store, "load", fake_load)
    monkeypatch.setattr(session_store, "delete", fake_delete)

    # 假微信响应：ask=已确认(status=1)，bizlogin 返 redirect_url 带 token，info 返昵称
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "scanloginqrcode" in url and "action=ask" in url:
            return httpx.Response(200, json={"status": 1, "acct_size": 1, "base_resp": {"ret": 0}})
        if "bizlogin" in url:
            return httpx.Response(
                200,
                json={"base_resp": {"ret": 0}, "redirect_url": "/cgi-bin/home?token=TK123&lang=zh_CN"},
                headers={"set-cookie": "slave_sid=SS; Path=/"},
            )
        if "action=info" in url or "cgi-bin/info" in url:
            return httpx.Response(200, json={"base_resp": {"ret": 0}, "nick_name": "我的号", "head_img": "http://a"})
        return httpx.Response(200, json={"base_resp": {"ret": 0}})

    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    user_id = uuid.uuid4()
    # 需要一个真实 user 满足 FK；直接建
    from app.auth.models import User
    from app.core.security import hash_password
    u = User(id=user_id, email=f"login-{user_id.hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.commit()

    res = await login.poll_status(db_session, "sess-1", user_id)
    assert res["status"] == "confirmed"
    assert res["nickname"] == "我的号"

    cred = await db_session.scalar(select(WechatCredential).where(WechatCredential.user_id == user_id))
    assert cred is not None
    assert cred.status == "active"
    assert crypto.decrypt(cred.token) == "TK123"
    assert "slave_sid=SS" in crypto.decrypt(cred.cookies)


@pytest.mark.asyncio
async def test_poll_waiting_when_not_scanned(db_session, monkeypatch):
    from app.social.wechat import login, session_store

    async def fake_load(sid):
        return "uuid=UU"
    monkeypatch.setattr(session_store, "load", fake_load)

    def handler(request):
        return httpx.Response(200, json={"status": 0, "base_resp": {"ret": 0}})
    monkeypatch.setattr(login, "new_mp_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    res = await login.poll_status(db_session, "sess-2", uuid.uuid4())
    assert res["status"] == "waiting"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_login.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 session_store.py**（复用 `app.core.ratelimit._redis`）

`backend/app/social/wechat/session_store.py`：

```python
from app.core.ratelimit import _redis

_TTL = 300  # 5 分钟


def _key(session_id: str) -> str:
    return f"wxlogin:{session_id}"


async def save(session_id: str, cookies: str) -> None:
    await _redis().set(_key(session_id), cookies, ex=_TTL)


async def load(session_id: str) -> str | None:
    return await _redis().get(_key(session_id))


async def delete(session_id: str) -> None:
    await _redis().delete(_key(session_id))
```

- [ ] **Step 4: 实现 login.py**

`backend/app/social/wechat/login.py`：

```python
import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.social import crypto
from app.social.models import WechatCredential
from app.social.wechat.client import new_mp_client
from app.social.wechat.session_store import delete as session_delete
from app.social.wechat.session_store import load as session_load
from app.social.wechat.session_store import save as session_save

_QR = "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode"
_BIZLOGIN = "https://mp.weixin.qq.com/cgi-bin/bizlogin"
_INFO = "https://mp.weixin.qq.com/cgi-bin/info"


async def start_qrcode() -> tuple[str, bytes]:
    """取二维码 + 建 login session。返回 (session_id, png 字节)。"""
    session_id = uuid.uuid4().hex
    async with new_mp_client() as http:
        r = await http.get(_QR, params={"action": "getqrcode", "random": "1"})
        r.raise_for_status()
        set_cookie = r.headers.get("set-cookie", "")
        # 提取 uuid=... 片段作为 session cookies
        uuid_cookie = ""
        for part in set_cookie.split(","):
            if "uuid=" in part:
                uuid_cookie = part.split(";")[0].strip()
                break
        await session_save(session_id, uuid_cookie)
        return session_id, r.content


async def poll_status(db: AsyncSession, session_id: str, user_id: uuid.UUID) -> dict:
    """轮询扫码态；确认(status=1)则 bizlogin 换 token、落库凭证。"""
    cookies = await session_load(session_id)
    if cookies is None:
        return {"status": "expired", "nickname": None}

    async with new_mp_client() as http:
        ask = (await http.get(
            _QR, params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
            headers={"Cookie": cookies},
        )).json()
        status = ask.get("status", 0)
        if status != 1:
            # 0=等待，4/6=已扫未确认（微信语义），统一映射
            return {"status": "scanned" if status in (4, 6) else "waiting", "nickname": None}

        # 已确认 → bizlogin
        biz = await http.post(
            _BIZLOGIN, params={"action": "login"},
            data={"userlang": "zh_CN", "redirect_url": "", "login_type": 3, "token": "",
                  "lang": "zh_CN", "f": "json", "ajax": 1},
            headers={"Cookie": cookies},
        )
        biz_json = biz.json()
        redirect = biz_json.get("redirect_url", "")
        token = _extract_token(redirect)
        # 收集 bizlogin 返回的长期 cookies
        long_cookies = _merge_cookies(cookies, biz.headers.get_list("set-cookie"))

        # 取昵称
        info = (await http.get(
            _INFO, params={"action": "info", "token": token, "lang": "zh_CN", "f": "json", "ajax": 1},
            headers={"Cookie": long_cookies},
        )).json()
        nickname = info.get("nick_name") or info.get("user_info", {}).get("nick_name") or "公众号"
        avatar = info.get("head_img")

    cred = WechatCredential(
        user_id=user_id,
        token=crypto.encrypt(token),
        cookies=crypto.encrypt(long_cookies),
        nickname=nickname,
        avatar=avatar,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=4),
        status="active",
    )
    db.add(cred)
    await db.commit()
    await session_delete(session_id)
    return {"status": "confirmed", "nickname": nickname}


def _extract_token(redirect_url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(redirect_url).query)
    vals = q.get("token")
    return vals[0] if vals else ""


def _merge_cookies(base: str, set_cookies: list[str]) -> str:
    """把 bizlogin 的 set-cookie 合并进已有 cookie 串。"""
    jar: dict[str, str] = {}
    for pair in base.split(";"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            jar[k.strip()] = v.strip()
    for sc in set_cookies:
        first = sc.split(";")[0]
        if "=" in first:
            k, v = first.split("=", 1)
            jar[k.strip()] = v.strip()
    return "; ".join(f"{k}={v}" for k, v in jar.items())
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_login.py -q`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/social/wechat/session_store.py backend/app/social/wechat/login.py backend/tests/test_social_login.py
git commit -m "feat(social): qrcode login flow (getqrcode/ask/bizlogin) + redis session"
```

---

## Task 6: 凭证池

**Files:**
- Create: `backend/app/social/credentials.py`
- Test: `backend/tests/test_social_credentials.py`

**Interfaces:**
- Produces: `async credentials.pick_credential(db) -> ActiveCred | None`（返回已解密凭证；顺手把 expires_at 已过的标 expired）
- Produces: `async credentials.mark_expired(db, cred_id: uuid.UUID) -> None`
- Consumes: `client.ActiveCred`、`crypto.decrypt`、`models.WechatCredential`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_social_credentials.py`：

```python
import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.social import crypto
from app.social.models import WechatCredential


def _cred(status="active", days=1, tok="T"):
    return WechatCredential(
        user_id=None, token=crypto.encrypt(tok), cookies=crypto.encrypt("c"),
        nickname="n", expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=days), status=status,
    )


@pytest.mark.asyncio
async def test_pick_returns_active_decrypted(db_session):
    c = _cred(tok="TOKACT")
    db_session.add(c)
    await db_session.commit()
    from app.social.credentials import pick_credential

    got = await pick_credential(db_session)
    assert got is not None
    assert got.token == "TOKACT"


@pytest.mark.asyncio
async def test_pick_skips_and_marks_time_expired(db_session):
    stale = _cred(days=-1, tok="OLD")  # 已过期时间
    db_session.add(stale)
    await db_session.commit()
    from app.social.credentials import pick_credential

    got = await pick_credential(db_session)
    assert got is None
    row = await db_session.scalar(select(WechatCredential).where(WechatCredential.id == stale.id))
    assert row.status == "expired"


@pytest.mark.asyncio
async def test_mark_expired(db_session):
    c = _cred()
    db_session.add(c)
    await db_session.commit()
    from app.social.credentials import mark_expired

    await mark_expired(db_session, c.id)
    row = await db_session.scalar(select(WechatCredential).where(WechatCredential.id == c.id))
    assert row.status == "expired"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_credentials.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 credentials.py**

`backend/app/social/credentials.py`：

```python
import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.social import crypto
from app.social.models import WechatCredential
from app.social.wechat.client import ActiveCred


async def pick_credential(db: AsyncSession) -> ActiveCred | None:
    """挑一个 active 且未过期的凭证；顺手把时间已过的标 expired。池空返 None。"""
    now = dt.datetime.now(dt.UTC)
    rows = (await db.execute(
        select(WechatCredential)
        .where(WechatCredential.status == "active")
        .order_by(WechatCredential.updated_at.desc())
    )).scalars().all()
    for row in rows:
        if row.expires_at <= now:
            row.status = "expired"
            continue
        await db.commit()
        return ActiveCred(id=row.id, token=crypto.decrypt(row.token), cookies=crypto.decrypt(row.cookies))
    await db.commit()
    return None


async def mark_expired(db: AsyncSession, cred_id: uuid.UUID) -> None:
    await db.execute(
        update(WechatCredential).where(WechatCredential.id == cred_id).values(status="expired")
    )
    await db.commit()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_credentials.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/social/credentials.py backend/tests/test_social_credentials.py
git commit -m "feat(social): credential pool pick/expire"
```

---

## Task 7: Ingest（account get-or-create + 抓取去重 + 懒抓）

**Files:**
- Create: `backend/app/social/ingest.py`
- Test: `backend/tests/test_social_ingest.py`

**Interfaces:**
- Produces: `async ingest.get_or_create_account(db, fakeid, name, avatar=None, signature=None) -> WechatAccount`
- Produces: `async ingest.ingest_account(db, account, cred, http) -> int`（新增文章数）
- Produces: `async ingest.fetch_article_content(db, article, http) -> str`（懒抓填充 content，已抓则直接返回）
- Consumes: `client.appmsg_publish/fetch_article_text/ActiveCred`、`models.*`

- [ ] **Step 1: 写失败测试**（http 用 MockTransport 返 appmsgpublish/正文）

`backend/tests/test_social_ingest.py`：

```python
import datetime as dt
import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.social.models import WechatAccount, WechatArticle
from app.social.wechat.client import ActiveCred


def _cred():
    return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")


def _appmsg_handler(aids):
    appmsgex = [{"aid": a, "title": f"T{a}", "digest": "d", "cover": "",
                 "link": f"https://mp/s/{a}", "create_time": 1751000000} for a in aids]
    page = json.dumps({"publish_list": [{"publish_info": json.dumps({"appmsgex": appmsgex})}],
                       "total_count": len(aids)})

    def handler(request):
        if "appmsgpublish" in str(request.url):
            return httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": page})
        # 正文
        return httpx.Response(200, text='<div id="js_content"><p>正文内容。</p></div>')
    return handler


@pytest.mark.asyncio
async def test_get_or_create_account_idempotent(db_session):
    from app.social.ingest import get_or_create_account

    a1 = await get_or_create_account(db_session, "FID", "号名")
    a2 = await get_or_create_account(db_session, "FID", "号名改")
    assert a1.id == a2.id
    n = await db_session.scalar(select(func.count()).select_from(WechatAccount).where(WechatAccount.fakeid == "FID"))
    assert n == 1


@pytest.mark.asyncio
async def test_ingest_dedup(db_session):
    from app.social.ingest import get_or_create_account, ingest_account

    acc = await get_or_create_account(db_session, "FID2", "号2")
    http = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(["x1", "x2"])))
    async with http:
        added1 = await ingest_account(db_session, acc, _cred(), http)
        added2 = await ingest_account(db_session, acc, _cred(), http)  # 同样两篇
    assert added1 == 2
    assert added2 == 0
    total = await db_session.scalar(
        select(func.count()).select_from(WechatArticle).where(WechatArticle.account_id == acc.id)
    )
    assert total == 2


@pytest.mark.asyncio
async def test_lazy_fetch_content(db_session):
    from app.social.ingest import fetch_article_content, get_or_create_account, ingest_account

    acc = await get_or_create_account(db_session, "FID3", "号3")
    http = httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(["y1"])))
    async with http:
        await ingest_account(db_session, acc, _cred(), http)
        art = await db_session.scalar(select(WechatArticle).where(WechatArticle.account_id == acc.id))
        assert art.content is None
        text = await fetch_article_content(db_session, art, http)
    assert "正文内容。" in text
    assert art.content is not None
    assert art.content_fetched_at is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_ingest.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 ingest.py**

`backend/app/social/ingest.py`：

```python
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.social.models import WechatAccount, WechatArticle
from app.social.wechat.client import ActiveCred, appmsg_publish, fetch_article_text


async def get_or_create_account(
    db: AsyncSession, fakeid: str, name: str, avatar: str | None = None, signature: str | None = None
) -> WechatAccount:
    acc = await db.scalar(select(WechatAccount).where(WechatAccount.fakeid == fakeid))
    if acc is not None:
        return acc
    acc = WechatAccount(fakeid=fakeid, name=name, avatar=avatar, signature=signature)
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    return acc


async def ingest_account(db: AsyncSession, account: WechatAccount, cred: ActiveCred, http, count: int = 20) -> int:
    from app.core.config import get_settings

    raws = await appmsg_publish(http, cred, account.fakeid, begin=0, count=count or get_settings().social_fetch_count)
    added = 0
    for raw in raws:
        exists = await db.scalar(
            select(WechatArticle.id).where(
                WechatArticle.account_id == account.id, WechatArticle.external_id == raw.external_id
            )
        )
        if exists is not None:
            continue
        db.add(WechatArticle(
            account_id=account.id, external_id=raw.external_id, title=raw.title,
            digest=raw.digest, cover_url=raw.cover_url, url=raw.url, published_at=raw.published_at,
        ))
        added += 1
    await db.commit()
    return added


async def fetch_article_content(db: AsyncSession, article: WechatArticle, http) -> str:
    if article.content is not None:
        return article.content
    text = await fetch_article_text(http, article.url)
    article.content = text
    article.content_fetched_at = dt.datetime.now(dt.UTC)
    await db.commit()
    return text
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_ingest.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/social/ingest.py backend/tests/test_social_ingest.py
git commit -m "feat(social): ingest — account upsert, article dedup, lazy content"
```

---

## Task 8: 定时轮询 job

**Files:**
- Create: `backend/app/social/job.py`
- Modify: `backend/app/core/scheduler.py`
- Test: `backend/tests/test_social_job.py`

**Interfaces:**
- Produces: `async job.poll_all_subscriptions() -> int`（本轮新增文章总数）
- Consumes: `credentials.pick_credential/mark_expired`、`ingest.ingest_account`、`client.new_mp_client`、`models.WechatSubscription/WechatAccount`

- [ ] **Step 1: 写失败测试**（monkeypatch pick_credential + new_mp_client）

`backend/tests/test_social_job.py`：

```python
import json
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.social.models import WechatArticle


def _appmsg_handler(aids):
    appmsgex = [{"aid": a, "title": f"T{a}", "digest": "", "cover": "",
                 "link": f"https://mp/s/{a}", "create_time": 1751000000} for a in aids]
    page = json.dumps({"publish_list": [{"publish_info": json.dumps({"appmsgex": appmsgex})}], "total_count": len(aids)})
    return lambda request: httpx.Response(200, json={"base_resp": {"ret": 0}, "publish_page": page})


@pytest.mark.asyncio
async def test_poll_inserts_for_enabled_subs(db_session, monkeypatch):
    from app.auth.models import User
    from app.core.security import hash_password
    from app.social import job
    from app.social.ingest import get_or_create_account
    from app.social.models import WechatSubscription
    from app.social.wechat.client import ActiveCred

    u = User(email=f"job-{uuid.uuid4().hex[:6]}@t.dev", password_hash=hash_password("x"))
    db_session.add(u)
    await db_session.flush()
    acc = await get_or_create_account(db_session, f"F{uuid.uuid4().hex[:6]}", "号")
    db_session.add(WechatSubscription(user_id=u.id, account_id=acc.id, enabled=True, interval_seconds=1800))
    await db_session.commit()

    async def fake_pick(db):
        return ActiveCred(id=uuid.uuid4(), token="t", cookies="c")
    monkeypatch.setattr(job, "pick_credential", fake_pick)
    monkeypatch.setattr(job, "new_mp_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_appmsg_handler(["j1", "j2"]))))

    added = await job.poll_all_subscriptions()
    assert added >= 2
    n = await db_session.scalar(select(func.count()).select_from(WechatArticle).where(WechatArticle.account_id == acc.id))
    assert n == 2


@pytest.mark.asyncio
async def test_poll_skips_when_pool_empty(db_session, monkeypatch):
    from app.social import job

    async def fake_pick(db):
        return None
    monkeypatch.setattr(job, "pick_credential", fake_pick)
    added = await job.poll_all_subscriptions()
    assert added == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_job.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 job.py**

`backend/app/social/job.py`：

```python
import logging

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.social.credentials import mark_expired, pick_credential
from app.social.ingest import ingest_account
from app.social.models import WechatAccount, WechatSubscription
from app.social.wechat.client import new_mp_client
from app.social.wechat.errors import SessionExpiredError, TransientMpError

_log = logging.getLogger(__name__)


async def poll_all_subscriptions() -> int:
    """遍历 enabled 订阅去重后的号，用池凭证增量抓取。池空则整轮跳过。"""
    async with get_sessionmaker()() as db:
        account_ids = (await db.execute(
            select(WechatSubscription.account_id).where(WechatSubscription.enabled.is_(True)).distinct()
        )).scalars().all()
        if not account_ids:
            return 0
        cred = await pick_credential(db)
        if cred is None:
            _log.warning("social poll skipped: 凭证池为空")
            return 0
        accounts = (await db.execute(
            select(WechatAccount).where(WechatAccount.id.in_(account_ids))
        )).scalars().all()

    total = 0
    async with new_mp_client() as http:
        for account in accounts:
            try:
                async with get_sessionmaker()() as db:
                    acc = await db.get(WechatAccount, account.id)
                    total += await ingest_account(db, acc, cred, http)
            except SessionExpiredError:
                async with get_sessionmaker()() as db:
                    await mark_expired(db, cred.id)
                _log.warning("social poll: 凭证失效，本轮中止")
                break
            except TransientMpError:
                _log.warning("social poll: 临时错误，跳过 %s", account.id)
            except Exception:  # noqa: BLE001 — 单号失败隔离
                _log.exception("social poll failed for account %s", account.id)
    return total
```

- [ ] **Step 4: 注册 scheduler**

`backend/app/core/scheduler.py`，在 news job 注册块后、`_scheduler.start()` 前加：

```python
    from app.social.job import poll_all_subscriptions

    async def _social_job():
        n = await poll_all_subscriptions()
        _log.info("social poll done: %d new articles", n)

    _scheduler.add_job(
        _social_job, IntervalTrigger(minutes=get_settings().social_poll_minutes),
        id="social_poll", replace_existing=True,
    )
```

并在文件顶部 import：`from app.core.config import get_settings`（若尚无）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_job.py -q`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/social/job.py backend/app/core/scheduler.py backend/tests/test_social_job.py
git commit -m "feat(social): scheduled poll job + scheduler registration"
```

---

## Task 9: Agent 工具 wechat_query

**Files:**
- Create: `backend/app/agent/tools/social.py`
- Modify: `backend/app/agent/build.py`
- Test: `backend/tests/test_social_tool.py`

**Interfaces:**
- Produces: `make_wechat_query(session_factory) -> tool`（`wechat_query(account="", keyword="", days=30, limit=20) -> str`）
- Consumes: `models.WechatArticle/WechatAccount`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_social_tool.py`：

```python
import datetime as dt
import uuid

import pytest

from app.core.db import get_sessionmaker
from app.social.ingest import get_or_create_account
from app.social.models import WechatArticle


@pytest.mark.asyncio
async def test_wechat_query_returns_matches(db_session):
    acc = await get_or_create_account(db_session, f"TF{uuid.uuid4().hex[:6]}", "投研号")
    db_session.add(WechatArticle(
        account_id=acc.id, external_id="q1", title="茅台深度", digest="估值",
        url="https://mp/s/q1", content="茅台正文分析",
        published_at=dt.datetime.now(dt.UTC),
    ))
    await db_session.commit()

    from app.agent.tools.social import make_wechat_query
    tool = make_wechat_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "茅台", "days": 30})
    assert "茅台深度" in out


@pytest.mark.asyncio
async def test_wechat_query_empty_window():
    from app.agent.tools.social import make_wechat_query
    tool = make_wechat_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "不存在的关键词zzz", "days": 1})
    assert "无" in out or "（" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_tool.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 social.py**

`backend/app/agent/tools/social.py`：

```python
import datetime as dt

from langchain_core.tools import tool
from sqlalchemy import select

from app.social.models import WechatAccount, WechatArticle


def make_wechat_query(session_factory):
    @tool
    async def wechat_query(account: str = "", keyword: str = "", days: int = 30, limit: int = 20) -> str:
        """查询已订阅微信公众号的文章（标题+正文摘要），用于投研分析。
        account 限定公众号名（模糊），keyword 关键词，days 时间窗天数。"""
        # 同 news_query：绝不向 agent 循环抛异常。
        try:
            since = dt.datetime.now(dt.UTC) - dt.timedelta(days=max(1, days))
            q = (
                select(WechatArticle, WechatAccount.name)
                .join(WechatAccount, WechatArticle.account_id == WechatAccount.id)
                .where(WechatArticle.published_at >= since)
            )
            if account:
                q = q.where(WechatAccount.name.ilike(f"%{account}%"))
            if keyword:
                q = q.where(
                    WechatArticle.title.ilike(f"%{keyword}%")
                    | WechatArticle.content.ilike(f"%{keyword}%")
                    | WechatArticle.digest.ilike(f"%{keyword}%")
                )
            q = q.order_by(WechatArticle.published_at.desc()).limit(min(limit, 50))
            async with session_factory() as db:
                rows = (await db.execute(q)).all()
        except Exception as e:  # noqa: BLE001
            return f"（公众号查询失败：{e}）"
        if not rows:
            return "（时间窗内无相关公众号文章）"
        parts = []
        for art, name in rows:
            body = (art.content or art.digest or "")[:400]
            when = art.published_at.astimezone().strftime("%m-%d %H:%M")
            parts.append(f"[{when}] 《{art.title}》（{name}）\n{body}")
        return "\n\n".join(parts)

    return wechat_query
```

- [ ] **Step 4: 接入 build.py**

`backend/app/agent/build.py`，在 `from app.agent.tools.news import make_news_query` 后加 import，并把工具加入 `tools` 列表：

```python
    from app.agent.tools.news import make_news_query
    from app.agent.tools.social import make_wechat_query
    from app.core.db import get_sessionmaker

    tools = [
        web_search,
        fetch_page,
        stock_quote,
        stock_financials,
        make_run_python(ws),
        make_news_query(get_sessionmaker()),
        make_wechat_query(get_sessionmaker()),
    ]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_tool.py -q`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/tools/social.py backend/app/agent/build.py backend/tests/test_social_tool.py
git commit -m "feat(social): wechat_query agent tool + wire into agent"
```

---

## Task 10: API 路由 + schemas

**Files:**
- Create: `backend/app/social/schemas.py`
- Create: `backend/app/social/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_social_api.py`

**Interfaces:**
- Produces: 路由 prefix `/api/social`（见下 endpoints）
- Consumes: `login.start_qrcode/poll_status`、`credentials.pick_credential`、`client.search_biz`、`ingest.get_or_create_account/fetch_article_content`、`models.*`

- [ ] **Step 1: 写失败测试**（覆盖鉴权、订阅幂等、文章懒抓；search/login 用 monkeypatch）

`backend/tests/test_social_api.py`：

```python
import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.social.models import WechatAccount, WechatArticle, WechatSubscription


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.mark.asyncio
async def test_requires_auth(client):
    r = await client.get("/api/social/wechat/subscriptions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_subscribe_idempotent_and_list(client, db_session, registered_user):
    h = _auth(registered_user)
    body = {"fakeid": f"F{uuid.uuid4().hex[:6]}", "name": "投研号", "avatar": None}
    r1 = await client.post("/api/social/wechat/subscriptions", json=body, headers=h)
    assert r1.status_code == 200
    r2 = await client.post("/api/social/wechat/subscriptions", json=body, headers=h)
    assert r2.status_code == 200  # 幂等，不 500
    subs = (await client.get("/api/social/wechat/subscriptions", headers=h)).json()
    assert any(s["name"] == "投研号" for s in subs)
    # 只建了一个 account
    n = await db_session.scalar(
        select(func.count()).select_from(WechatAccount).where(WechatAccount.fakeid == body["fakeid"])
    )
    assert n == 1


@pytest.mark.asyncio
async def test_list_articles(client, db_session, registered_user):
    h = _auth(registered_user)
    acc = WechatAccount(fakeid=f"A{uuid.uuid4().hex[:6]}", name="号X")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(WechatArticle(
        account_id=acc.id, external_id="e1", title="标题X", url="https://mp/s/e1",
        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
    ))
    await db_session.commit()
    arts = (await client.get(f"/api/social/wechat/articles?account_id={acc.id}", headers=h)).json()
    assert arts[0]["title"] == "标题X"
    assert arts[0]["content"] is None


@pytest.mark.asyncio
async def test_article_lazy_fetch(client, db_session, registered_user, monkeypatch):
    h = _auth(registered_user)
    acc = WechatAccount(fakeid=f"B{uuid.uuid4().hex[:6]}", name="号Y")
    db_session.add(acc)
    await db_session.flush()
    art = WechatArticle(account_id=acc.id, external_id="e2", title="待抓", url="https://mp/s/e2",
                        published_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC))
    db_session.add(art)
    await db_session.commit()

    import app.social.router as router_mod

    async def fake_fetch(db, article, http):
        article.content = "抓到的正文"
        article.content_fetched_at = dt.datetime.now(dt.UTC)
        await db.commit()
        return "抓到的正文"
    monkeypatch.setattr(router_mod, "fetch_article_content", fake_fetch)

    got = (await client.get(f"/api/social/wechat/articles/{art.id}", headers=h)).json()
    assert got["content"] == "抓到的正文"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_api.py -q`
Expected: FAIL（路由未注册 / 404 或 import 错）

- [ ] **Step 3: 实现 schemas.py**

`backend/app/social/schemas.py`：

```python
from pydantic import BaseModel


class SubscribeIn(BaseModel):
    fakeid: str
    name: str
    avatar: str | None = None


class AccountOut(BaseModel):
    id: str
    fakeid: str
    name: str
    avatar: str | None


class SubscriptionOut(BaseModel):
    id: str
    account_id: str
    fakeid: str
    name: str
    avatar: str | None
    enabled: bool


class ArticleOut(BaseModel):
    id: str
    account_id: str
    title: str
    digest: str | None
    cover_url: str | None
    url: str
    content: str | None
    published_at: str


class CredentialOut(BaseModel):
    id: str
    nickname: str
    avatar: str | None
    status: str
    expires_at: str
```

- [ ] **Step 4: 实现 router.py**

`backend/app/social/router.py`：

```python
import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.social.credentials import pick_credential
from app.social.ingest import fetch_article_content, get_or_create_account
from app.social.models import (
    WechatAccount,
    WechatArticle,
    WechatCredential,
    WechatSubscription,
)
from app.social.schemas import (
    AccountOut,
    ArticleOut,
    CredentialOut,
    SubscribeIn,
    SubscriptionOut,
)
from app.social.wechat.client import new_mp_client, search_biz
from app.social.wechat.login import poll_status, start_qrcode

router = APIRouter(prefix="/api/social", tags=["social"])


# ---- 登录 ----
@router.post("/wechat/login/qrcode")
async def login_qrcode(user: User = Depends(get_current_user)) -> dict:
    import base64

    session_id, png = await start_qrcode()
    return {"login_session": session_id, "qrcode": "data:image/png;base64," + base64.b64encode(png).decode()}


@router.get("/wechat/login/status")
async def login_status(
    s: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await poll_status(db, s, user.id)


@router.get("/wechat/credentials", response_model=list[CredentialOut])
async def my_credentials(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(WechatCredential).where(WechatCredential.user_id == user.id)
    )).scalars().all()
    return [
        CredentialOut(id=str(c.id), nickname=c.nickname, avatar=c.avatar, status=c.status,
                      expires_at=c.expires_at.isoformat())
        for c in rows
    ]


@router.delete("/wechat/credentials/{cred_id}")
async def delete_credential(
    cred_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    c = await db.get(WechatCredential, cred_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "凭证不存在")
    await db.delete(c)
    await db.commit()
    return {"ok": True}


# ---- 搜索 / 订阅 ----
@router.get("/wechat/search")
async def search(
    keyword: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    cred = await pick_credential(db)
    if cred is None:
        raise HTTPException(409, "凭证池为空，请先扫码登录一个公众号")
    async with new_mp_client() as http:
        return await search_biz(http, cred, keyword)


@router.post("/wechat/subscriptions", response_model=SubscriptionOut)
async def subscribe(
    body: SubscribeIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    acc = await get_or_create_account(db, body.fakeid, body.name, body.avatar)
    sub = await db.scalar(
        select(WechatSubscription).where(
            WechatSubscription.user_id == user.id, WechatSubscription.account_id == acc.id
        )
    )
    if sub is None:
        sub = WechatSubscription(user_id=user.id, account_id=acc.id, enabled=True)
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
    return SubscriptionOut(id=str(sub.id), account_id=str(acc.id), fakeid=acc.fakeid,
                           name=acc.name, avatar=acc.avatar, enabled=sub.enabled)


@router.get("/wechat/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(WechatSubscription, WechatAccount)
        .join(WechatAccount, WechatSubscription.account_id == WechatAccount.id)
        .where(WechatSubscription.user_id == user.id)
    )).all()
    return [
        SubscriptionOut(id=str(sub.id), account_id=str(acc.id), fakeid=acc.fakeid,
                        name=acc.name, avatar=acc.avatar, enabled=sub.enabled)
        for sub, acc in rows
    ]


@router.delete("/wechat/subscriptions/{sub_id}")
async def unsubscribe(
    sub_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    sub = await db.get(WechatSubscription, sub_id)
    if sub is None or sub.user_id != user.id:
        raise HTTPException(404, "订阅不存在")
    await db.delete(sub)
    await db.commit()
    return {"ok": True}


# ---- 文章 ----
@router.get("/wechat/articles", response_model=list[ArticleOut])
async def list_articles(
    account_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    before: dt.datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(WechatArticle).where(WechatArticle.account_id == account_id)
    if before is not None:
        q = q.where(WechatArticle.published_at < before)
    q = q.order_by(WechatArticle.published_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [_article_out(r) for r in rows]


@router.get("/wechat/articles/{article_id}", response_model=ArticleOut)
async def get_article(
    article_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    art = await db.get(WechatArticle, article_id)
    if art is None:
        raise HTTPException(404, "文章不存在")
    if art.content is None:
        async with new_mp_client() as http:
            await fetch_article_content(db, art, http)
    return _article_out(art)


@router.post("/wechat/refresh")
async def refresh(
    account_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    from app.social.ingest import ingest_account

    cred = await pick_credential(db)
    if cred is None:
        raise HTTPException(409, "凭证池为空，请先扫码登录一个公众号")
    acc = await db.get(WechatAccount, account_id)
    if acc is None:
        raise HTTPException(404, "公众号不存在")
    async with new_mp_client() as http:
        added = await ingest_account(db, acc, cred, http)
    return {"added": added}


def _article_out(r: WechatArticle) -> ArticleOut:
    return ArticleOut(
        id=str(r.id), account_id=str(r.account_id), title=r.title, digest=r.digest,
        cover_url=r.cover_url, url=r.url, content=r.content, published_at=r.published_at.isoformat(),
    )
```

- [ ] **Step 5: 注册路由**

`backend/app/main.py`，在 `app.include_router(news_router)` 后加：

```python
    from app.social.router import router as social_router
    app.include_router(social_router)
```

（import 风格对齐文件顶部现有 router import；若集中在顶部，则在顶部加 `from app.social.router import router as social_router` 并在 include 区加 `app.include_router(social_router)`。）

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_social_api.py -q`
Expected: PASS（4 passed）

- [ ] **Step 7: 全量后端回归**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q`
Expected: 全绿（含既有 news/kb/chat 等测试不回归）

- [ ] **Step 8: Commit**

```bash
git add backend/app/social/schemas.py backend/app/social/router.py backend/app/main.py backend/tests/test_social_api.py
git commit -m "feat(social): REST API (login/search/subscribe/articles) + register router"
```

---

## Task 11: 前端 lib + SocialPanel

**Files:**
- Create: `frontend/src/lib/social.ts`
- Create: `frontend/src/lib/social.test.ts`
- Modify: `frontend/src/panels/SocialPanel.tsx`

**Interfaces:**
- Produces: `social.ts`：`searchAccounts(keyword)`、`subscribe(a)`、`listSubscriptions()`、`listArticles(accountId)`、`getArticle(id)`、`startLoginQrcode()`、`pollLoginStatus(session)`、`listCredentials()`、类型 `WechatAccount/Subscription/Article/Credential`
- Consumes: `lib/api.apiFetch`

- [ ] **Step 1: 写失败测试**

`frontend/src/lib/social.test.ts`：

```ts
import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { listArticles, searchAccounts } from "./social";

describe("social api", () => {
  it("searchAccounts hits search endpoint with keyword", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([{ fakeid: "F1", nickname: "号A", avatar: null, signature: null }]), { status: 200 }),
    );
    const rows = await searchAccounts("茅台");
    expect(rows[0].fakeid).toBe("F1");
    expect(spy.mock.calls[0][0] as string).toContain("/api/social/wechat/search");
    expect(spy.mock.calls[0][0] as string).toContain("keyword=");
  });

  it("listArticles requests account_id", async () => {
    const spy = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await listArticles("acc-1");
    expect(spy.mock.calls[0][0] as string).toContain("account_id=acc-1");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/lib/social.test.ts`
Expected: FAIL（`./social` 不存在）

- [ ] **Step 3: 实现 social.ts**

`frontend/src/lib/social.ts`：

```ts
import { apiFetch } from "./api";

export type WechatAccount = { fakeid: string; nickname: string; avatar: string | null; signature: string | null };
export type Subscription = { id: string; account_id: string; fakeid: string; name: string; avatar: string | null; enabled: boolean };
export type Article = {
  id: string; account_id: string; title: string; digest: string | null;
  cover_url: string | null; url: string; content: string | null; published_at: string;
};
export type Credential = { id: string; nickname: string; avatar: string | null; status: string; expires_at: string };

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

export async function searchAccounts(keyword: string): Promise<WechatAccount[]> {
  return json(await apiFetch(`/api/social/wechat/search?keyword=${encodeURIComponent(keyword)}`));
}

export async function subscribe(a: { fakeid: string; name: string; avatar: string | null }): Promise<Subscription> {
  return json(await apiFetch(`/api/social/wechat/subscriptions`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(a),
  }));
}

export async function listSubscriptions(): Promise<Subscription[]> {
  return json(await apiFetch(`/api/social/wechat/subscriptions`));
}

export async function unsubscribe(id: string): Promise<void> {
  await apiFetch(`/api/social/wechat/subscriptions/${id}`, { method: "DELETE" });
}

export async function listArticles(accountId: string, limit = 20): Promise<Article[]> {
  return json(await apiFetch(`/api/social/wechat/articles?account_id=${accountId}&limit=${limit}`));
}

export async function getArticle(id: string): Promise<Article> {
  return json(await apiFetch(`/api/social/wechat/articles/${id}`));
}

export async function refreshAccount(accountId: string): Promise<{ added: number }> {
  return json(await apiFetch(`/api/social/wechat/refresh?account_id=${accountId}`, { method: "POST" }));
}

export async function startLoginQrcode(): Promise<{ login_session: string; qrcode: string }> {
  return json(await apiFetch(`/api/social/wechat/login/qrcode`, { method: "POST" }));
}

export async function pollLoginStatus(session: string): Promise<{ status: string; nickname: string | null }> {
  return json(await apiFetch(`/api/social/wechat/login/status?s=${encodeURIComponent(session)}`));
}

export async function listCredentials(): Promise<Credential[]> {
  return json(await apiFetch(`/api/social/wechat/credentials`));
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/lib/social.test.ts`
Expected: PASS（2 passed）

- [ ] **Step 5: 实现 SocialPanel.tsx**

替换 `frontend/src/panels/SocialPanel.tsx` 全文：

```tsx
import { useEffect, useState } from "react";
import {
  type Article,
  type Credential,
  type Subscription,
  type WechatAccount,
  getArticle,
  listArticles,
  listCredentials,
  listSubscriptions,
  pollLoginStatus,
  refreshAccount,
  searchAccounts,
  startLoginQrcode,
  subscribe,
} from "@/lib/social";

export default function SocialPanel() {
  const [creds, setCreds] = useState<Credential[]>([]);
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState<WechatAccount[]>([]);
  const [activeAcc, setActiveAcc] = useState<string | null>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [reading, setReading] = useState<Article | null>(null);
  const [qr, setQr] = useState<{ img: string; session: string } | null>(null);
  const [loginMsg, setLoginMsg] = useState("");
  const [err, setErr] = useState("");

  const hasActiveCred = creds.some((c) => c.status === "active");

  async function reloadCredsAndSubs() {
    setCreds(await listCredentials());
    setSubs(await listSubscriptions());
  }
  useEffect(() => {
    reloadCredsAndSubs().catch((e) => setErr(String(e)));
  }, []);

  async function onSearch() {
    setErr("");
    try {
      setResults(await searchAccounts(keyword));
    } catch (e) {
      setErr(String(e));
    }
  }

  async function onSubscribe(a: WechatAccount) {
    await subscribe({ fakeid: a.fakeid, name: a.nickname, avatar: a.avatar });
    setSubs(await listSubscriptions());
  }

  async function openAccount(accountId: string) {
    setActiveAcc(accountId);
    setReading(null);
    setArticles(await listArticles(accountId));
  }

  async function openArticle(id: string) {
    setReading(await getArticle(id)); // 懒抓正文
  }

  async function onRefresh() {
    if (activeAcc) {
      await refreshAccount(activeAcc);
      setArticles(await listArticles(activeAcc));
    }
  }

  async function onLogin() {
    setLoginMsg("请用微信扫码并在手机上确认");
    const { qrcode, login_session } = await startLoginQrcode();
    setQr({ img: qrcode, session: login_session });
    const timer = setInterval(async () => {
      const r = await pollLoginStatus(login_session);
      if (r.status === "confirmed") {
        clearInterval(timer);
        setQr(null);
        setLoginMsg(`已登录：${r.nickname}`);
        await reloadCredsAndSubs();
      } else if (r.status === "expired") {
        clearInterval(timer);
        setQr(null);
        setLoginMsg("二维码已过期，请重试");
      }
    }, 2000);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-4 p-5">
          {/* 登录区 */}
          <section className="rounded-lg border p-4">
            <div className="mb-2 text-sm font-medium">公众号登录</div>
            {!hasActiveCred && (
              <p className="mb-2 text-xs text-muted-foreground">
                需登录你自己的微信公众号才能使用。你的登录将进入平台共享抓取池，
                可能被用于抓取其他用户订阅的公众号——请知情后再登录。
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={onLogin} className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground">
                扫码登录公众号
              </button>
              {creds.map((c) => (
                <span key={c.id} className={`text-xs ${c.status === "active" ? "text-green-600" : "text-red-500"}`}>
                  {c.nickname}（{c.status === "active" ? "有效" : "已过期，请重登"}）
                </span>
              ))}
            </div>
            {loginMsg && <p className="mt-2 text-xs text-muted-foreground">{loginMsg}</p>}
            {qr && <img src={qr.img} alt="登录二维码" className="mt-2 h-40 w-40" />}
          </section>

          {/* 搜索订阅 */}
          <section className="rounded-lg border p-4">
            <div className="mb-2 text-sm font-medium">搜索公众号</div>
            <div className="flex gap-2">
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="输入公众号名"
                className="flex-1 rounded border px-2 py-1 text-sm"
              />
              <button type="button" onClick={onSearch} className="rounded border px-3 py-1 text-sm">搜索</button>
            </div>
            <ul className="mt-2 space-y-1">
              {results.map((a) => (
                <li key={a.fakeid} className="flex items-center justify-between text-sm">
                  <span>{a.nickname}</span>
                  <button type="button" onClick={() => onSubscribe(a)} className="text-xs text-primary">订阅</button>
                </li>
              ))}
            </ul>
          </section>

          {/* 订阅 + 文章 */}
          <section className="rounded-lg border p-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-medium">我的订阅</div>
              {activeAcc && <button type="button" onClick={onRefresh} className="text-xs text-primary">刷新</button>}
            </div>
            <div className="flex flex-wrap gap-2">
              {subs.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => openAccount(s.account_id)}
                  className={`rounded border px-2 py-1 text-xs ${activeAcc === s.account_id ? "bg-accent" : ""}`}
                >
                  {s.name}
                </button>
              ))}
            </div>
            <ul className="mt-3 space-y-2">
              {articles.map((art) => (
                <li key={art.id}>
                  <button type="button" onClick={() => openArticle(art.id)} className="text-left text-sm hover:underline">
                    {art.title}
                  </button>
                  <div className="text-xs text-muted-foreground">{new Date(art.published_at).toLocaleString()}</div>
                </li>
              ))}
            </ul>
          </section>

          {/* 阅读 */}
          {reading && (
            <section className="rounded-lg border p-4">
              <div className="mb-2 text-sm font-medium">{reading.title}</div>
              <pre className="whitespace-pre-wrap text-sm">{reading.content ?? "加载中…"}</pre>
              <a href={reading.url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-primary">
                原文链接
              </a>
            </section>
          )}

          {err && <p className="text-xs text-red-500">{err}</p>}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: 前端构建自检**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/lib/social.test.ts`
Expected: 类型通过 + 测试 PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/social.ts frontend/src/lib/social.test.ts frontend/src/panels/SocialPanel.tsx
git commit -m "feat(social): frontend lib + SocialPanel (login/search/subscribe/read)"
```

---

## Self-Review 结果

**Spec 覆盖核对：**
- §1 范围（登录/搜索/订阅/定时抓/懒抓纯文本/落库/agent）→ Tasks 5,10 / 10 / 10 / 8 / 7 / 2 / 9 ✓
- §2 抓取原理（三步登录、searchbiz、appmsgpublish 双层解析、返回码分类）→ Tasks 5,4,3 ✓
- §3 凭证池 + 过期处理 + 加密 → Tasks 6,1；池空暂停 → Task 8 ✓
- §4 四表 → Task 2 ✓
- §5 适配层（login/client/parser）→ Tasks 3,4,5 ✓
- §6 ingest（upsert/dedup/懒抓）→ Task 7 ✓
- §7 job（串行/隔离/间隔/池空跳过）→ Task 8 ✓
- §8 API 全 endpoints → Task 10 ✓
- §9 agent 工具 → Task 9 ✓
- §10 前端 lib+panel（登录/搜索/订阅/阅读/知情同意提示）→ Task 11 ✓
- §11 测试 → 各 Task 内置 ✓
- §12 合规知情同意 → Task 11 panel 文案 ✓
- §13 扩展位（SocialPlatform ABC）→ **本期未做**：YAGNI，一期只有 wechat，抽象 ABC 无第二实现验证。留待第二平台（微博）时再抽。前端平台 tab 亦暂缓，待第二平台加。

**占位扫描：** 无 TBD/TODO；每步含完整代码与命令。

**类型一致性核对：** `ActiveCred`(client 定义，credentials/ingest/job/login 消费一致)；`RawArticle`(parser 定义，client/ingest 消费)；`fetch_article_content(db, article, http)` 签名 Task 7 定义、Task 10 router 调用与 monkeypatch 一致；`pick_credential(db)`/`new_mp_client()` 在 job 中作模块属性被 monkeypatch（`job.pick_credential`/`job.new_mp_client`），故 job.py 用 `from ... import` 顶层引入 ✓。

**已知取舍（非阻塞）：**
- 登录 `ask` 的 `status` 语义（0 等待 / 4,6 已扫 / 1 确认）依参考库经验值；实测若不符，只调 `login.poll_status` 的映射，不影响其余任务。
- `info` 昵称接口字段（`nick_name` vs `user_info.nick_name`）做了双路兜底。
- 迁移 revision id `c7d8e9f0a1b2` 为占位常量；若与既有冲突，改一个新 hex 并同步 `down_revision` 链。
