import datetime as dt
import uuid

import pytest

from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.news.models import NewsItem, NewsSource


def _auth(user) -> dict:
    """签合法 access token；对注册夹具与直建 User 都用 user.id。"""
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


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
    # after 增量：取比 base+1min 更新的（用 params 让 httpx 正确编码 +00:00，
    # 否则 URL 里的 "+" 会被解析成空格导致 datetime 校验 422）
    after = (base + dt.timedelta(minutes=1)).isoformat()
    inc = (await client.get("/api/news", params={"after": after}, headers=h)).json()
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
