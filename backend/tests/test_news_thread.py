import datetime as dt
import uuid

import pytest
from httpx import AsyncClient

from app.auth.models import User
from app.core.security import create_access_token, hash_password


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _make_user(db_session) -> User:
    u = User(
        email=f"news-thread-{uuid.uuid4().hex[:8]}@test.dev",
        password_hash=hash_password("pw-12345"),
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_news_thread_get_or_create_idempotent(client: AsyncClient, db_session):
    user = await _make_user(db_session)
    h = _auth(user)
    r1 = await client.get("/api/news/thread", headers=h)
    r2 = await client.get("/api/news/thread", headers=h)
    assert r1.status_code == 200
    assert r1.json()["thread_id"] == r2.json()["thread_id"]


@pytest.mark.asyncio
async def test_news_keyword_search(client: AsyncClient, db_session):
    from app.news.models import NewsItem, NewsSource
    import hashlib

    user = await _make_user(db_session)
    h = _auth(user)

    # Create a news source first
    source = NewsSource(name="Test Source", type="test", channel="news", config={})
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    # Create news item with required fields
    content = "苹果公司发布新款iPhone"
    item = NewsItem(
        source_id=source.id,
        channel="news",
        external_id="test-apple-1",
        content_hash=hashlib.md5(content.encode()).hexdigest(),
        title="苹果发布会",
        content=content,
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(item)
    await db_session.commit()

    r = await client.get("/api/news", params={"keyword": "苹果"}, headers=h)
    assert r.status_code == 200
    assert any("苹果" in i["content"] for i in r.json())

    r2 = await client.get("/api/news", params={"keyword": "腾讯xyz_unique_not_exist"}, headers=h)
    assert r2.json() == []
