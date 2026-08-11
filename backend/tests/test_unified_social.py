import datetime as dt
import uuid

import pytest
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.social.unified import compute_content_hash, get_feed, record_metrics, upsert_item
from app.social.unified_models import (
    ContentBookmark,
    SocialItem,
    SocialItemMetricSnapshot,
    SocialPublisher,
    SocialSubscription,
)
from app.social.providers.base import ItemDTO, MetricsDTO


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


@pytest.mark.asyncio
async def test_upsert_item_uses_full_stable_hash_and_preserves_body(db_session):
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"hash-{uuid.uuid4().hex}",
        name="Hash Publisher",
        provider="redfox",
    )
    db_session.add(publisher)
    await db_session.flush()
    published_at = dt.datetime.now(dt.UTC)
    item = await upsert_item(
        db_session,
        ItemDTO(
            platform="wechat",
            external_id=f"item-{uuid.uuid4().hex}",
            content_type="article",
            title="stable title",
            body_text="complete body",
            url="https://example.test/article",
            published_at=published_at,
        ),
        publisher.id,
    )
    expected = compute_content_hash("stable title", "complete body", "https://example.test/article")
    assert item.content_hash == expected
    assert len(item.content_hash) == 64

    same = await upsert_item(
        db_session,
        ItemDTO(
            platform="wechat",
            external_id=item.external_id,
            content_type="article",
            title="stable title",
            body_text=None,
            url="https://example.test/article",
            published_at=published_at,
        ),
        publisher.id,
    )
    assert same.id == item.id
    assert same.body_text == "complete body"
    assert same.content_hash == expected

    first_metrics = await record_metrics(
        db_session,
        item.id,
        MetricsDTO(view_count=100, like_count=10, raw={"source": "test"}),
    )
    repeated = await record_metrics(
        db_session,
        item.id,
        MetricsDTO(view_count=100, like_count=10, raw={"source": "test"}),
    )
    changed = await record_metrics(
        db_session,
        item.id,
        MetricsDTO(view_count=101, like_count=10, raw={"source": "test"}),
    )
    assert repeated.id == first_metrics.id
    assert changed.id != first_metrics.id
    assert await db_session.scalar(
        select(func.count(SocialItemMetricSnapshot.id)).where(
            SocialItemMetricSnapshot.item_id == item.id
        )
    ) == 2
    await db_session.rollback()


@pytest.mark.asyncio
async def test_feed_cursor_is_stable_and_strictly_subscription_scoped(db_session):
    user_one = User(
        email=f"feed-one-{uuid.uuid4().hex}@test.dev",
        password_hash=hash_password("x"),
    )
    user_two = User(
        email=f"feed-two-{uuid.uuid4().hex}@test.dev",
        password_hash=hash_password("x"),
    )
    own_publisher = SocialPublisher(
        platform="wechat", external_id=f"own-{uuid.uuid4().hex}", name="Own"
    )
    other_publisher = SocialPublisher(
        platform="weibo", external_id=f"other-{uuid.uuid4().hex}", name="Other"
    )
    db_session.add_all([user_one, user_two, own_publisher, other_publisher])
    await db_session.flush()
    db_session.add_all(
        [
            SocialSubscription(user_id=user_one.id, publisher_id=own_publisher.id),
            SocialSubscription(user_id=user_two.id, publisher_id=other_publisher.id),
        ]
    )
    timestamp = dt.datetime.now(dt.UTC).replace(microsecond=0)
    own_items = [
        SocialItem(
            publisher_id=own_publisher.id,
            platform="wechat",
            external_id=f"own-item-{uuid.uuid4().hex}",
            content_type="article",
            title=f"Own {index}",
            published_at=timestamp,
        )
        for index in range(3)
    ]
    hidden = SocialItem(
        publisher_id=other_publisher.id,
        platform="weibo",
        external_id=f"hidden-{uuid.uuid4().hex}",
        content_type="post",
        title="Hidden",
        published_at=timestamp + dt.timedelta(hours=1),
    )
    db_session.add_all([*own_items, hidden])
    await db_session.commit()

    first = await get_feed(db_session, user_one.id, limit=2)
    assert len(first["items"]) == 2
    assert first["next_before"]
    assert {item["title"] for item in first["items"]}.issubset({"Own 0", "Own 1", "Own 2"})

    from app.social.unified import decode_feed_cursor

    second = await get_feed(
        db_session,
        user_one.id,
        before=decode_feed_cursor(first["next_before"]),
        limit=2,
    )
    assert len(second["items"]) == 1
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})


@pytest.mark.asyncio
async def test_feed_and_bookmark_http_contracts(client, db_session, registered_user):
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"api-{uuid.uuid4().hex}",
        name="API Publisher",
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"api-item-{uuid.uuid4().hex}",
        content_type="article",
        title="API item",
        body_text="durable body",
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add_all(
        [item, SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id)]
    )
    await db_session.commit()
    headers = _auth(registered_user)

    response = await client.get("/api/social/feed?limit=1", headers=headers)
    assert response.status_code == 200
    assert set(response.json()) == {"items", "next_before"}
    assert response.json()["items"][0]["id"] == str(item.id)
    assert (await client.get("/api/social/api/social/feed", headers=headers)).status_code == 404

    bookmarked = await client.post(
        "/api/social/bookmarks",
        json={"item_id": str(item.id), "notes": "keep"},
        headers=headers,
    )
    assert bookmarked.status_code == 200
    stored = await db_session.scalar(
        select(ContentBookmark).where(
            ContentBookmark.user_id == registered_user.id,
            ContentBookmark.item_id == item.id,
        )
    )
    assert stored is not None
    await db_session.refresh(item)
    assert item.body_expires_at is None


@pytest.mark.asyncio
async def test_xiaohongshu_account_subscription_fails_explicitly(
    client, db_session, registered_user, monkeypatch
):
    from app.social import feed_router

    class Provider:
        def capabilities(self, platform):
            return {
                "account_item_list": False,
                "missing_reason": "RedFox does not expose a Xiaohongshu account item-list API",
            }

    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: Provider())
    response = await client.post(
        "/api/social/subscriptions",
        json={
            "platform": "xiaohongshu",
            "external_id": f"xhs-{uuid.uuid4().hex}",
            "name": "XHS",
        },
        headers=_auth(registered_user),
    )
    assert response.status_code == 422
    assert "item-list" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_is_real_and_publisher_global_across_users(
    client, db_session, registered_user, monkeypatch
):
    from app.social import feed_router

    second_user = User(
        email=f"refresh-two-{uuid.uuid4().hex}@test.dev",
        password_hash=hash_password("x"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"refresh-{uuid.uuid4().hex}",
        name="Refresh Publisher",
        provider="redfox",
    )
    db_session.add_all([second_user, publisher])
    await db_session.flush()
    db_session.add_all(
        [
            SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id),
            SocialSubscription(user_id=second_user.id, publisher_id=publisher.id),
        ]
    )
    await db_session.commit()

    class FakeRedis:
        values = {}

        async def set(self, key, value, ex, nx):
            assert ex == 900 and nx is True
            if key in self.values:
                return None
            self.values[key] = value
            return True

        async def ttl(self, key):
            return 899

        async def delete(self, key):
            self.values.pop(key, None)

        async def aclose(self):
            return None

    calls = []

    async def fake_refresh(db, refreshed_publisher, settings):
        calls.append(refreshed_publisher.id)
        return 3

    monkeypatch.setattr(feed_router.aioredis, "from_url", lambda *args, **kwargs: FakeRedis())
    monkeypatch.setattr(feed_router, "refresh_publisher", fake_refresh)
    first = await client.post(
        f"/api/social/publishers/{publisher.id}/refresh",
        headers=_auth(registered_user),
    )
    second = await client.post(
        f"/api/social/publishers/{publisher.id}/refresh",
        headers={"Authorization": f"Bearer {create_access_token(str(second_user.id))}"},
    )
    assert first.status_code == 200
    assert first.json()["fetched"] == 3
    assert second.status_code == 429
    assert calls == [publisher.id]

    from types import SimpleNamespace

    from app.social import refresh as refresh_module

    scheduled_calls = []

    async def fake_scheduled_refresh(db, refreshed_publisher, settings):
        scheduled_calls.append(refreshed_publisher.id)
        return 2

    monkeypatch.setattr(refresh_module, "refresh_publisher", fake_scheduled_refresh)
    stats = await refresh_module.refresh_subscribed_publishers(db_session, SimpleNamespace())
    assert scheduled_calls.count(publisher.id) == 1
    assert stats["items"] >= 2


@pytest.mark.asyncio
async def test_weibo_legacy_backfill_is_idempotent_and_preserves_fields(
    db_session, registered_user
):
    import importlib.util
    from pathlib import Path

    from app.social.models import WeiboAccount, WeiboPost, WeiboSubscription

    path = Path(__file__).resolve().parents[2] / "scripts" / "migrate_social_data.py"
    spec = importlib.util.spec_from_file_location("social_migration_script", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    account = WeiboAccount(
        uid=f"7{uuid.uuid4().int % 10**10:010d}",
        name="迁移微博",
        description="简介",
        profile_url="https://weibo.com/u/7",
        container_id="1076037",
    )
    db_session.add(account)
    await db_session.flush()
    post = WeiboPost(
        account_id=account.id,
        external_id=f"post-{uuid.uuid4().hex}",
        bid="BID",
        content="迁移正文",
        url="https://weibo.com/7/BID",
        media=[{"type": "image", "url": "https://img.test/1"}],
        published_at=dt.datetime.now(dt.UTC),
        captured_at=dt.datetime.now(dt.UTC),
    )
    db_session.add_all(
        [post, WeiboSubscription(user_id=registered_user.id, account_id=account.id)]
    )
    await db_session.commit()

    for _ in range(2):
        await migration._migrate_publishers(db_session)
        await migration._migrate_items(db_session)
        await migration._migrate_subscriptions(db_session)
        await db_session.commit()

    publisher = await db_session.scalar(
        select(SocialPublisher).where(
            SocialPublisher.platform == "weibo",
            SocialPublisher.external_id == account.uid,
        )
    )
    migrated = await db_session.scalar(
        select(SocialItem).where(
            SocialItem.platform == "weibo",
            SocialItem.external_id == post.external_id,
        )
    )
    assert publisher.name == account.name
    assert migrated.body_text == post.content
    assert migrated.url == post.url
    assert migrated.platform_metadata["bid"] == post.bid
    subscriptions = (
        await db_session.execute(
            select(SocialSubscription).where(
                SocialSubscription.user_id == registered_user.id,
                SocialSubscription.publisher_id == publisher.id,
            )
        )
    ).scalars().all()
    assert len(subscriptions) == 1
