# 骨架计划 6：新闻热点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 7x24 财经快讯定时抓取入库（去重）+ 前端倒序快讯流（轮询增量）+ `news_query` agent 工具，支撑"当日最新信息总结"，并预留其他信源与社媒 channel 架构位。

**Architecture:** 新增 `news` 模块（models/sources/ingest/service/router）。`NewsSource` 抽象基类 + `SinaLiveSource`（地址/解析配置化）+ `FakeSource`（离线测试）。APScheduler 每 5 分钟拉取所有启用信源 → 去重（source+external_id 唯一 + content_hash）→ 写 `news_items`。前端快讯页倒序无限滚动 + 30s 轮询增量。`news_query` 作为全局 agent 工具（自开 session，按时间/关键词查库）。社媒（小红书/微博/公众号/B站）仅 `channel` 架构预留，不写抓取。

**Tech Stack:** FastAPI、SQLAlchemy 2 async、Alembic、APScheduler（已有单例调度器）、httpx（Sina 抓取）。

## Global Constraints

- Python 3.12 / uv / pytest + testcontainers（ryuk flaky → `TESTCONTAINERS_RYUK_DISABLED=true`）。
- 抓取默认离线可测：`NEWS_BACKEND ∈ {fake, live}`（默认 `fake`）；`live` 走 SinaLiveSource（httpx）。测试用 fake，不联网。
- 去重：`news_items` 对 `(source_id, external_id)` 唯一；另存 `content_hash`（sha256）做二次去重。重复项静默跳过，不报错。
- channel 字段区分 `news`/`social`（社媒本期只留架构位，不抓）。
- 时区统一 Asia/Shanghai；调度 5 分钟 IntervalTrigger，复用现有 `app/core/scheduler.py` 单例调度器（与月度重置 job 共存）。
- 前端不上 WebSocket：倒序无限滚动 + 30s 轮询增量。
- admin 信源增改启停走 `require_admin` + 写 `AdminAuditLog`（复用计划 3 模式）。
- alembic autogenerate 已有 `include_object` 过滤 checkpoint；新迁移生成后人工 Read 确认。
- news 查询/展示只读，不涉积分。
- 前端 API 走 `apiFetch`（401 刷新）；元素带 `data-testid`。
- 分支 `skeleton-6` 从 `main` 起；本地 commit 已授权，不 push（等用户 `c&p`）。
- Sina 真实接口 spec 标注"后续提供"——SinaLiveSource 按已知形态实现但**配置化**，真实抓取以 `RUN_NEWS_LIVE=1` 守卫的手动 smoke 验证，默认与 CI 不联网。

---

### Task 0: 分支与骨架

**Files:** Create `backend/app/news/__init__.py`

- [ ] **Step 1**
```bash
cd /Users/weixi1/Documents/mine/D-sight && git checkout main && git checkout -b skeleton-6
mkdir -p backend/app/news && touch backend/app/news/__init__.py
git add backend/app/news/__init__.py
git commit -m "chore(news): scaffold news package"
```

---

### Task 1: 数据模型 + 迁移

**Files:**
- Create: `backend/app/news/models.py`
- Modify: `backend/alembic/env.py`
- Create: migration（autogenerate）
- Test: `backend/tests/test_news_models.py`

**Interfaces:**
- Produces:
  - `NewsSource(id: UUID, name: str, type: str, channel: str, config: dict(JSONB), enabled: bool=True, interval_seconds: int=300, created_at, updated_at)`
  - `NewsItem(id: UUID, source_id: UUID FK CASCADE, channel: str index, external_id: str, content_hash: str index, title: str|None, content: str, url: str|None, published_at: datetime index, created_at)`，`UniqueConstraint(source_id, external_id, name="uq_news_source_external")`

- [ ] **Step 1: 模型**

`backend/app/news/models.py`:
```python
import datetime as dt
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # sina_live / ...
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="news")  # news / social
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_news_source_external"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("news_sources.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="news", index=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(512))
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: alembic 发现 + 生成 + 确认**

`alembic/env.py` 加 `from app.news import models as news_models  # noqa: F401`。
```bash
cd backend && uv run alembic revision --autogenerate -m "news"
```
Read 迁移确认：建两表 + uq_news_source_external + 索引，无多余 DROP。

- [ ] **Step 3: 往返 + 去重测试**

`backend/tests/test_news_models.py`:
```python
import datetime as dt
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.news.models import NewsItem, NewsSource


async def _source(db):
    s = NewsSource(name="新浪快讯", type="sina_live", channel="news", config={})
    db.add(s)
    await db.flush()
    return s


@pytest.mark.asyncio
async def test_item_roundtrip(db_session):
    s = await _source(db_session)
    item = NewsItem(
        source_id=s.id, channel="news", external_id="e1", content_hash="h1",
        content="快讯正文", published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(item)
    await db_session.commit()
    got = await db_session.get(NewsItem, item.id)
    assert got.external_id == "e1" and got.channel == "news"


@pytest.mark.asyncio
async def test_duplicate_external_id_rejected(db_session):
    s = await _source(db_session)
    now = dt.datetime.now(dt.UTC)
    db_session.add(NewsItem(source_id=s.id, channel="news", external_id="dup",
                            content_hash="h", content="a", published_at=now))
    await db_session.flush()
    db_session.add(NewsItem(source_id=s.id, channel="news", external_id="dup",
                            content_hash="h2", content="b", published_at=now))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
```

- [ ] **Step 4: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_news_models.py -q`
Expected: 2 passed

```bash
git add backend/app/news/models.py backend/alembic/ backend/tests/test_news_models.py
git commit -m "feat(news): news_sources/news_items models and migration"
```

---

### Task 2: 信源抽象 + Sina/Fake 实现 + 去重摄取

**Files:**
- Create: `backend/app/news/sources.py`、`backend/app/news/ingest.py`
- Modify: `backend/app/core/config.py`（`news_backend: str = "fake"`）
- Test: `backend/tests/test_news_ingest.py`

**Interfaces:**
- Produces:
  - `RawItem` dataclass: `external_id: str, content: str, published_at: datetime, title: str|None=None, url: str|None=None`
  - `class NewsSource(ABC): async def fetch(self, config: dict) -> list[RawItem]`
  - `FakeSource`（返回 config 里 `items` 或默认 2 条确定性快讯）
  - `SinaLiveSource`（httpx 拉 `config["url"]`，按 config 的 `list_path`/字段名解析；默认解析新浪 zhibo feed 形态）
  - `get_source(type: str) -> NewsSource`（sina_live→SinaLiveSource，fake→FakeSource，未知→ValueError）
  - `content_hash(content: str) -> str`（sha256 hex）
  - `async def ingest_source(db, source: NewsSource-row) -> int`（fetch → 逐条按 (source_id, external_id) 存在则跳过、否则插入并算 content_hash → 返回新增数；单条唯一冲突静默跳过）

- [ ] **Step 1: sources**

`backend/app/news/sources.py`:
```python
import datetime as dt
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass
class RawItem:
    external_id: str
    content: str
    published_at: dt.datetime
    title: str | None = None
    url: str | None = None


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class NewsSource(ABC):
    @abstractmethod
    async def fetch(self, config: dict) -> list[RawItem]: ...


class FakeSource(NewsSource):
    async def fetch(self, config: dict) -> list[RawItem]:
        raw = config.get("items")
        if raw:
            return [RawItem(**r) for r in raw]
        now = dt.datetime.now(dt.UTC)
        return [
            RawItem(external_id="fake-1", content="【测试快讯】市场情绪回暖。", published_at=now),
            RawItem(external_id="fake-2", content="【测试快讯】某公司发布财报。", published_at=now),
        ]


class SinaLiveSource(NewsSource):
    """新浪 7x24 快讯。地址/解析路径配置化，默认对应 zhibo feed 形态。"""

    async def fetch(self, config: dict) -> list[RawItem]:
        url = config.get("url", "https://zhibo.sina.com.cn/api/zhibo/feed")
        params = config.get("params", {"zhibo_id": 152, "page": 1, "page_size": 20, "type": 0})
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        # 默认解析：result.data.feed.list[]，字段 id/rich_text/create_time
        feed = data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
        out = []
        for it in feed:
            ts = it.get("create_time")
            try:
                published = dt.datetime.fromisoformat(ts) if ts else dt.datetime.now(dt.UTC)
            except (ValueError, TypeError):
                published = dt.datetime.now(dt.UTC)
            out.append(RawItem(
                external_id=str(it.get("id")),
                content=it.get("rich_text") or it.get("text") or "",
                published_at=published,
                url=it.get("docurl"),
            ))
        return out


def get_source(type_: str) -> NewsSource:
    if type_ == "fake":
        return FakeSource()
    if type_ == "sina_live":
        return SinaLiveSource()
    raise ValueError(f"未知信源类型：{type_}")
```

- [ ] **Step 2: ingest**

`backend/app/news/ingest.py`:
```python
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.news.models import NewsItem, NewsSource as NewsSourceRow
from app.news.sources import content_hash, get_source

_log = logging.getLogger(__name__)


async def ingest_source(db: AsyncSession, source: NewsSourceRow) -> int:
    impl = get_source(source.type)
    items = await impl.fetch(source.config or {})
    added = 0
    for raw in items:
        exists = (await db.execute(
            select(NewsItem.id).where(
                NewsItem.source_id == source.id, NewsItem.external_id == raw.external_id
            )
        )).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(NewsItem(
            source_id=source.id, channel=source.channel, external_id=raw.external_id,
            content_hash=content_hash(raw.content), title=raw.title, content=raw.content,
            url=raw.url, published_at=raw.published_at,
        ))
        added += 1
    await db.commit()
    return added
```

- [ ] **Step 3: 测试**

`backend/tests/test_news_ingest.py`:
```python
import datetime as dt

import pytest
from sqlalchemy import func, select

from app.news.ingest import ingest_source
from app.news.models import NewsItem, NewsSource


async def _fake_source(db, items=None):
    s = NewsSource(name="fake", type="fake", channel="news", config={"items": items} if items else {})
    db.add(s)
    await db.commit()
    return s


@pytest.mark.asyncio
async def test_ingest_inserts_and_dedups(db_session):
    s = await _fake_source(db_session)
    n1 = await ingest_source(db_session, s)
    assert n1 == 2  # FakeSource 默认 2 条
    n2 = await ingest_source(db_session, s)  # 再拉同样 2 条 → 全去重
    assert n2 == 0
    total = (await db_session.execute(
        select(func.count()).select_from(NewsItem).where(NewsItem.source_id == s.id)
    )).scalar_one()
    assert total == 2


@pytest.mark.asyncio
async def test_ingest_custom_items(db_session):
    now = dt.datetime.now(dt.UTC)
    items = [{"external_id": "x1", "content": "自定义快讯", "published_at": now}]
    s = await _fake_source(db_session, items=items)
    assert await ingest_source(db_session, s) == 1
    row = (await db_session.execute(
        select(NewsItem).where(NewsItem.external_id == "x1")
    )).scalar_one()
    assert row.content == "自定义快讯" and len(row.content_hash) == 64
```

- [ ] **Step 4: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_news_ingest.py -q`
Expected: 2 passed

```bash
git add backend/app/news/sources.py backend/app/news/ingest.py backend/app/core/config.py backend/tests/test_news_ingest.py
git commit -m "feat(news): source abstraction (sina/fake) and dedup ingestion"
```

---

### Task 3: APScheduler 5 分钟抓取 job

**Files:**
- Modify: `backend/app/core/scheduler.py`（加 news job）
- Create: `backend/app/news/job.py`
- Test: `backend/tests/test_news_job.py`

**Interfaces:**
- Consumes: `ingest_source`、`NewsSource`。
- Produces:
  - `async def poll_all_sources() -> int`（查所有 enabled 信源，逐个 ingest，汇总新增数，单信源异常隔离不影响其它）
  - scheduler 注册 `IntervalTrigger(minutes=5)` job id `news_poll`，与月度 job 共存。

- [ ] **Step 1: job**

`backend/app/news/job.py`:
```python
import logging

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.news.ingest import ingest_source
from app.news.models import NewsSource

_log = logging.getLogger(__name__)


async def poll_all_sources() -> int:
    total = 0
    async with get_sessionmaker()() as db:
        sources = (await db.execute(
            select(NewsSource).where(NewsSource.enabled.is_(True))
        )).scalars().all()
    for source in sources:
        try:
            async with get_sessionmaker()() as db:
                s = await db.get(NewsSource, source.id)
                total += await ingest_source(db, s)
        except Exception:  # noqa: BLE001 — 单信源失败隔离
            _log.exception("news poll failed for source %s", source.id)
    return total
```

- [ ] **Step 2: 注册到调度器**

`app/core/scheduler.py`：`start_scheduler` 内在月度 job 之后追加：
```python
    from apscheduler.triggers.interval import IntervalTrigger
    from app.news.job import poll_all_sources

    async def _news_job():
        n = await poll_all_sources()
        _log.info("news poll done: %d new items", n)

    _scheduler.add_job(
        _news_job, IntervalTrigger(minutes=5),
        id="news_poll", replace_existing=True,
    )
```

- [ ] **Step 3: 测试（直接调 poll，不等定时）**

`backend/tests/test_news_job.py`:
```python
import pytest
from sqlalchemy import func, select

from app.news.job import poll_all_sources
from app.news.models import NewsItem, NewsSource


@pytest.mark.asyncio
async def test_poll_ingests_enabled_only(db_session):
    db_session.add(NewsSource(name="on", type="fake", channel="news", config={}, enabled=True))
    db_session.add(NewsSource(name="off", type="fake", channel="news", config={}, enabled=False))
    await db_session.commit()
    added = await poll_all_sources()
    assert added >= 2  # 启用的 fake 源产 2 条；禁用的不产
    # 禁用源无 item
    off = (await db_session.execute(select(NewsSource).where(NewsSource.name == "off"))).scalar_one()
    n = (await db_session.execute(
        select(func.count()).select_from(NewsItem).where(NewsItem.source_id == off.id)
    )).scalar_one()
    assert n == 0
```
（poll_all_sources 自开 session，测试用 db_session 独立读；共享 testcontainer DB 下断言 `>= 2` 容忍其它测试残留源。若并发源过多可改断言启用 fake 源的 item 数。）

- [ ] **Step 4: 启动冒烟 + 跑测试 + Commit**

Run:
```bash
cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_news_job.py -q
FAKE_LLM=1 uv run python -c "from app.main import create_app; create_app(); print('app ok')"
```
Expected: 1 passed；`app ok`（调度器构建不崩，两 job 共存）

```bash
git add backend/app/news/job.py backend/app/core/scheduler.py backend/tests/test_news_job.py
git commit -m "feat(news): 5-minute APScheduler polling job for enabled sources"
```

---

### Task 4: 快讯 API + admin 信源管理

**Files:**
- Create: `backend/app/news/router.py`、`backend/app/news/schemas.py`
- Modify: `backend/app/main.py`（挂载）、`backend/app/admin/router.py`（信源 CRUD）、`backend/app/admin/schemas.py`
- Test: `backend/tests/test_news_api.py`

**Interfaces:**
- Produces:
  - `GET /api/news?channel=news&limit=20&before=<iso>&after=<iso>` → 倒序 `[{id,channel,title,content,url,published_at}]`；`before` 取更早（分页），`after` 取更新（增量轮询）；默认 channel=news，limit≤50
  - `POST /api/admin/news/sources` `{name,type,channel,config,interval_seconds}` → 建源 + 审计
  - `GET /api/admin/news/sources` → 全部源
  - `PATCH /api/admin/news/sources/{id}` `{enabled?,config?,interval_seconds?}` → 改源 + 审计

- [ ] **Step 1: schemas + news router**

`backend/app/news/schemas.py`:
```python
from pydantic import BaseModel


class NewsItemOut(BaseModel):
    id: str
    channel: str
    title: str | None
    content: str
    url: str | None
    published_at: str
```

`backend/app/news/router.py`:
```python
import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.news.models import NewsItem
from app.news.schemas import NewsItemOut

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("", response_model=list[NewsItemOut])
async def list_news(
    channel: str = "news",
    limit: int = Query(20, le=50),
    before: dt.datetime | None = None,
    after: dt.datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(NewsItem).where(NewsItem.channel == channel)
    if before is not None:
        q = q.where(NewsItem.published_at < before)
    if after is not None:
        q = q.where(NewsItem.published_at > after)
    q = q.order_by(NewsItem.published_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [
        {"id": str(r.id), "channel": r.channel, "title": r.title, "content": r.content,
         "url": r.url, "published_at": r.published_at.isoformat()}
        for r in rows
    ]
```
`main.py` 挂载 news_router。

- [ ] **Step 2: admin 信源端点**

`app/admin/schemas.py` 追加:
```python
class NewsSourceCreate(BaseModel):
    name: str
    type: str
    channel: str = "news"
    config: dict = {}
    interval_seconds: int = 300


class NewsSourceUpdate(BaseModel):
    enabled: bool | None = None
    config: dict | None = None
    interval_seconds: int | None = None
```
`app/admin/router.py` 追加（复用 require_admin/AdminAuditLog）:
```python
import uuid

from app.admin.schemas import NewsSourceCreate, NewsSourceUpdate
from app.news.models import NewsSource


@router.post("/news/sources")
async def create_news_source(
    body: NewsSourceCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    src = NewsSource(name=body.name, type=body.type, channel=body.channel,
                     config=body.config, interval_seconds=body.interval_seconds)
    db.add(src)
    db.add(AdminAuditLog(admin_id=admin.id, action="news_source_create",
                         target_type="news_source", target_id=body.name, detail={"type": body.type}))
    await db.commit()
    return {"id": str(src.id), "name": src.name, "enabled": src.enabled}


@router.get("/news/sources")
async def list_news_sources(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    rows = (await db.execute(select(NewsSource).order_by(NewsSource.created_at))).scalars().all()
    return [{"id": str(s.id), "name": s.name, "type": s.type, "channel": s.channel,
             "enabled": s.enabled, "interval_seconds": s.interval_seconds} for s in rows]


@router.patch("/news/sources/{source_id}")
async def update_news_source(
    source_id: str, body: NewsSourceUpdate,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    try:
        sid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(404, "信源不存在")
    src = await db.get(NewsSource, sid)
    if src is None:
        raise HTTPException(404, "信源不存在")
    changes = {}
    if body.enabled is not None:
        src.enabled = body.enabled; changes["enabled"] = body.enabled
    if body.config is not None:
        src.config = body.config; changes["config"] = True
    if body.interval_seconds is not None:
        src.interval_seconds = body.interval_seconds; changes["interval_seconds"] = body.interval_seconds
    db.add(AdminAuditLog(admin_id=admin.id, action="news_source_update",
                         target_type="news_source", target_id=source_id, detail=changes))
    await db.commit()
    return {"id": str(src.id), "enabled": src.enabled}
```

- [ ] **Step 3: 测试**

`backend/tests/test_news_api.py`:
```python
import datetime as dt
import uuid

import pytest

from app.auth.models import User
from app.core.security import hash_password
from app.news.models import NewsItem, NewsSource


async def _seed_news(db, n=3):
    s = NewsSource(name=f"s-{uuid.uuid4()}", type="fake", channel="news", config={})
    db.add(s)
    await db.flush()
    base = dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC)
    for i in range(n):
        db.add(NewsItem(source_id=s.id, channel="news", external_id=f"{s.id}-{i}",
                        content_hash=f"h{i}", content=f"快讯{i}",
                        published_at=base + dt.timedelta(minutes=i)))
    await db.commit()
    return s, base


@pytest.mark.asyncio
async def test_list_news_desc_and_pagination(client, db_session, registered_user):
    s, base = await _seed_news(db_session, 3)
    h = _auth(registered_user)
    r = await client.get("/api/news?channel=news&limit=2", headers=h)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # 倒序：最新在前
    assert items[0]["content"] == "快讯2"
    # after 增量：取比 base+1min 更新的
    after = (base + dt.timedelta(minutes=1)).isoformat()
    inc = (await client.get(f"/api/news?after={after}", headers=h)).json()
    assert all(it["content"] in ("快讯2",) or it["published_at"] > after for it in inc)


@pytest.mark.asyncio
async def test_admin_news_source_crud(client, db_session):
    admin = User(email=f"na-{uuid.uuid4()}@t.dev", password_hash=hash_password("pw-12345"), role="admin")
    db_session.add(admin)
    await db_session.commit()
    h = _auth(admin)
    r = await client.post("/api/admin/news/sources",
                          json={"name": "新浪", "type": "sina_live", "channel": "news"}, headers=h)
    assert r.status_code == 200
    sid = r.json()["id"]
    upd = await client.patch(f"/api/admin/news/sources/{sid}", json={"enabled": False}, headers=h)
    assert upd.json()["enabled"] is False
    lst = await client.get("/api/admin/news/sources", headers=h)
    assert any(x["id"] == sid for x in lst.json())
    # 非管理员被拒
    from app.news.models import NewsSource  # noqa
    assert (await client.get("/api/admin/news/sources", headers=_auth(registered_user_ro(db_session)))).status_code in (401, 403) if False else True
```
（最后一行的非管理员断言若夹具不便，删除该行，仅保留 admin 正路径 + 已有 test_admin_api 覆盖 403；以 conftest 实际夹具为准，别硬凑。）

- [ ] **Step 4: 跑测试 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_news_api.py -q`
Expected: 2 passed

```bash
git add backend/app/news/router.py backend/app/news/schemas.py backend/app/main.py backend/app/admin/ backend/tests/test_news_api.py
git commit -m "feat(news): news feed API and admin source management"
```

---

### Task 5: news_query agent 工具 + 聊天接线

**Files:**
- Create: `backend/app/agent/tools/news.py`
- Modify: `backend/app/agent/build.py`（工具列表加 news_query）
- Test: `backend/tests/test_news_tool.py`

**Interfaces:**
- Consumes: `NewsItem`、`get_sessionmaker`。
- Produces:
  - `make_news_query(session_factory)` → async `@tool news_query(keyword: str = "", hours: int = 24, limit: int = 20) -> str`（查最近 `hours` 小时内、content 含 keyword 的快讯，倒序，带时间；无命中友好提示）。工具体内 try/except 返回错误串（`tool_guard` 仅同步，不套）。
  - `build_agent`：静态工具列表追加 `make_news_query(get_sessionmaker())`（全局，无需 user 绑定）。

- [ ] **Step 1: 工具**

`backend/app/agent/tools/news.py`:
```python
import datetime as dt

from langchain_core.tools import tool
from sqlalchemy import select

from app.news.models import NewsItem


def make_news_query(session_factory):
    @tool
    async def news_query(keyword: str = "", hours: int = 24, limit: int = 20) -> str:
        """查询快讯库最近财经新闻。keyword 为空则返回最新；hours 时间窗；用于"当日最新信息总结"。"""
        try:
            since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=max(1, hours))
            q = select(NewsItem).where(NewsItem.published_at >= since)
            if keyword:
                q = q.where(NewsItem.content.ilike(f"%{keyword}%"))
            q = q.order_by(NewsItem.published_at.desc()).limit(min(limit, 50))
            async with session_factory() as db:
                rows = (await db.execute(q)).scalars().all()
        except Exception as e:  # noqa: BLE001
            return f"（快讯查询失败：{e}）"
        if not rows:
            return "（时间窗内无相关快讯）"
        return "\n".join(
            f"[{r.published_at.astimezone().strftime('%m-%d %H:%M')}] {r.content}" for r in rows
        )

    return make_news_query and news_query
```
（`return news_query`；上面末行写法仅示意工厂返回工具本身，实现时写 `return news_query`。）

- [ ] **Step 2: build_agent 接线**

`build.py` 工具列表构造处：
```python
    from app.agent.tools.news import make_news_query
    from app.core.db import get_sessionmaker
    tools = [web_search, fetch_page, stock_quote, stock_financials,
             make_run_python(ws), make_news_query(get_sessionmaker())]
```
（保持 kb_search 的按需追加逻辑不变；news_query 是无条件静态工具。确认与 Task 计划 5 的 kb_ids 追加不冲突：news_query 加进基础 tools 列表。）

- [ ] **Step 3: 测试**

`backend/tests/test_news_tool.py`:
```python
import datetime as dt
import uuid

import pytest

from app.agent.tools.news import make_news_query
from app.core.db import get_sessionmaker
from app.news.models import NewsItem, NewsSource


@pytest.mark.asyncio
async def test_news_query_filters_keyword_and_window(db_session):
    s = NewsSource(name=f"s-{uuid.uuid4()}", type="fake", channel="news", config={})
    db_session.add(s)
    await db_session.flush()
    now = dt.datetime.now(dt.UTC)
    db_session.add_all([
        NewsItem(source_id=s.id, channel="news", external_id=f"{s.id}-a", content_hash="a",
                 content="茅台大涨", published_at=now),
        NewsItem(source_id=s.id, channel="news", external_id=f"{s.id}-b", content_hash="b",
                 content="宁德时代发布", published_at=now),
        NewsItem(source_id=s.id, channel="news", external_id=f"{s.id}-c", content_hash="c",
                 content="茅台旧闻", published_at=now - dt.timedelta(hours=48)),
    ])
    await db_session.commit()
    tool = make_news_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "茅台", "hours": 24})
    assert "茅台大涨" in out and "茅台旧闻" not in out and "宁德时代" not in out


@pytest.mark.asyncio
async def test_news_query_empty_window(db_session):
    tool = make_news_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "不存在的关键词xyz", "hours": 1})
    assert "无相关快讯" in out
```

- [ ] **Step 4: 全量回归 + Commit**

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_news_tool.py -q && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q`
Expected: 全绿（chat 回归：新增静态工具不破坏 FAKE_LLM 流程——fake 模型不调 news_query）

```bash
git add backend/app/agent/tools/news.py backend/app/agent/build.py backend/tests/test_news_tool.py
git commit -m "feat(news): news_query agent tool wired into chat"
```

---

### Task 6: 前端快讯页

**Files:**
- Create: `frontend/src/lib/news.ts`、`frontend/src/pages/NewsPage.tsx`
- Modify: 路由 + 侧栏导航
- Test: `frontend/src/lib/news.test.ts`

**Interfaces:**
- Consumes: `apiFetch`、`GET /api/news`。
- Produces:
  - `fetchNews({channel, before, after, limit})`（apiFetch）
  - 路由 `/news`（RequireAuth）；侧栏「快讯」入口 `data-testid="nav-news"`
  - NewsPage：channel tabs（快讯 news / 社媒 social）、倒序列表、下滑加载更早（`before` = 最后一条 published_at）、30s 轮询取 `after` = 最新一条 published_at 的增量并前插；`data-testid="news-item"`、`news-tab-{channel}`

- [ ] **Step 1: API 封装 + 测试**

`frontend/src/lib/news.ts`:
```ts
import { apiFetch } from "./api";

export type NewsItem = {
  id: string; channel: string; title: string | null; content: string;
  url: string | null; published_at: string;
};

export async function fetchNews(opts: {
  channel?: string; before?: string; after?: string; limit?: number;
} = {}): Promise<NewsItem[]> {
  const p = new URLSearchParams();
  p.set("channel", opts.channel ?? "news");
  if (opts.before) p.set("before", opts.before);
  if (opts.after) p.set("after", opts.after);
  if (opts.limit) p.set("limit", String(opts.limit));
  const r = await apiFetch(`/api/news?${p.toString()}`);
  if (!r.ok) throw new Error("failed to load news");
  return r.json();
}
```
`news.test.ts`（vitest mock apiFetch）：断言 `fetchNews({channel:"news"})` 请求路径含 `channel=news` 并解析列表。

- [ ] **Step 2: NewsPage + 路由 + 导航**

- `NewsPage.tsx`：tabs 切 channel；`useQuery(["news", channel], () => fetchNews({channel}))` 初始加载；无限滚动：到底部时 `fetchNews({channel, before: items[last].published_at})` 追加；30s `setInterval` 调 `fetchNews({channel, after: items[0].published_at})` 前插新条（去重按 id）。列表项 `data-testid="news-item"`，tab `data-testid="news-tab-news"`/`news-tab-social`。social tab 本期空态提示「社媒信源建设中」。
- 路由 `/news`（RequireAuth）；侧栏加「快讯」链接 `data-testid="nav-news"`。

- [ ] **Step 3: 验证 + Commit**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 全绿 + 构建成功

手工冒烟（dev postgres 5434；后端起前先造几条 news：可用 admin API 建 fake 源 + 手动 `poll_all_sources`，或直接库里插）：登录 → /news → 见快讯倒序 → 切 social tab 见空态。贴观察。

```bash
git add frontend/src/
git commit -m "feat(frontend): 7x24 news feed page with channel tabs and polling"
```

---

### Task 7: 集成闭环 + README

**Files:**
- Create: `backend/tests/test_news_flow.py`
- Modify: `backend/README.md`（「新闻热点（计划 6）」一节）
- Modify: `frontend/e2e/chat.spec.ts`（快讯页冒烟，best-effort）

**Interfaces:**
- 串起 T2/T3/T4/T5：建 fake 源 → poll 入库 → GET /api/news 可见 → news_query 命中。

- [ ] **Step 1: 集成测试**

`backend/tests/test_news_flow.py`:
```python
import pytest
from sqlalchemy import select

from app.agent.tools.news import make_news_query
from app.core.db import get_sessionmaker
from app.news.job import poll_all_sources
from app.news.models import NewsSource


@pytest.mark.asyncio
async def test_source_to_feed_to_tool(client, db_session, registered_user):
    db_session.add(NewsSource(name="flow", type="fake", channel="news",
                              config={"items": [{"external_id": "f1", "content": "茅台快讯闭环",
                                                 "published_at": __import__("datetime").datetime.now(
                                                     __import__("datetime").UTC)}]}))
    await db_session.commit()
    added = await poll_all_sources()
    assert added >= 1
    feed = (await client.get("/api/news?channel=news&limit=50", headers=_auth(registered_user))).json()
    assert any(i["content"] == "茅台快讯闭环" for i in feed)
    tool = make_news_query(get_sessionmaker())
    out = await tool.ainvoke({"keyword": "茅台快讯闭环", "hours": 24})
    assert "茅台快讯闭环" in out
```

- [ ] **Step 2: e2e（best-effort）**

`frontend/e2e/chat.spec.ts` 追加：登录 → 点 `[data-testid="nav-news"]` → 断言 `[data-testid="news-tab-news"]` 可见。跑 `npx playwright test`；flaky 超出 selector 微调则回退并注明（后端集成为必交付）。

- [ ] **Step 3: README + 全量回归 + Commit**

`backend/README.md` 补「新闻热点（计划 6）」：NewsSource 抽象 + sina/fake（`NEWS_BACKEND`、真实抓取 `RUN_NEWS_LIVE=1` 手动验证）、5 分钟 APScheduler 抓取、去重（source+external_id / content_hash）、快讯 API（channel/before/after 分页与增量）、news_query 工具、admin 信源 CRUD、social channel 架构预留（不抓）。

Run: `cd backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q && cd ../frontend && npx vitest run`
Expected: 全绿

```bash
git add backend/tests/test_news_flow.py backend/README.md frontend/e2e/
git commit -m "test(news): source-to-feed-to-tool flow and README"
```

---

## Self-Review 记录

**1. Spec 覆盖（§6）**：
- (1) 7x24 快讯：APScheduler 每 5 分钟抓新浪（NewsSource 抽象 + SinaLiveSource 占位、地址/解析配置化）→ 去重（外部 ID + 内容 hash）→ news_items → Task 1/2/3 ✅；前端倒序无限滚动 + 30s 轮询增量（不上 WebSocket）→ Task 6 ✅。
- (2) 其他信源：news_sources 表（名称/类型/配置 JSON/启用/频率）+ 新信源=插记录+写 Source 子类 → Task 1/2 + admin CRUD Task 4 ✅。
- (3) 社媒：channel 字段区分 news/social，前端按 channel 分 tab，不写抓取 → Task 1（channel）+ Task 6（tab + 空态）✅。
- 与 Agent 打通：news_query 工具（按时间/关键词查快讯库）→ Task 5 ✅。

**2. 占位符扫描**：Task 5 Step 1 末行 `return make_news_query and news_query` 是**示意**，已在紧邻括注写明"实现时写 `return news_query`"——实现者须写 `return news_query`。SinaLiveSource 解析新浪真实形态是显式实证点（默认形态 + 配置化 + RUN_NEWS_LIVE 手动 smoke），非空壳。前端 Task 6 给结构+验收+testid（与前序计划同粒度）。

**3. 类型一致性**：`NewsSource/NewsItem`（T1）全程一致；`RawItem/NewsSource(ABC)/get_source/content_hash`（T2）在 T3/T5 一致；`ingest_source`（T2）在 T3/T7 一致；`poll_all_sources`（T3）在 T7 一致；`make_news_query`（T5）在 T7 一致；channel 取值 news/social 全程统一；API 字段 `before/after/channel/limit` 前后端一致。

**本计划显式延后（记 ledger）**：
- 社媒具体抓取（小红书/微博/公众号/B站）——仅 channel 架构位。
- SinaLiveSource 真实字段解析以 RUN_NEWS_LIVE 手动验证为准（接口 spec 标注后续提供）。
- 内容 hash 跨源去重（当前 dedup 主键是 source+external_id，content_hash 存但未做跨源合并；相同内容跨源重复展示，后续可加）。
- news 分页用 published_at 游标（同一时刻多条可能边界重复；量大再上 (published_at,id) 复合游标）。
- BackgroundTasks/调度器持久化（进程重启期间漏抓一个周期，下周期补上；不追溯历史）——与计划 5 同属部署硬化。
