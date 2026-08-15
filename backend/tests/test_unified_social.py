import datetime as dt
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.aihot.models import HotItemSource, HotSourceMembership
from app.auth.models import User
from app.core.security import create_access_token, hash_password
from app.social.unified import compute_content_hash, get_feed, record_metrics, upsert_item
from app.social.unified_models import (
    ContentBookmark,
    SocialItem,
    SocialItemMetricSnapshot,
    SocialPublisher,
    SocialPublisherIdentity,
    SocialSubscription,
)
from app.social.providers.base import ItemDTO, MetricsDTO


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


class _WechatDetailProvider:
    def __init__(self, body_text: str | None = None, error: Exception | None = None):
        self.body_text = body_text
        self.error = error
        self.calls: list[ItemDTO] = []

    def capabilities(self, platform: str) -> dict:
        return {"detail": platform == "wechat"}

    async def fetch_item_detail(self, item: ItemDTO) -> ItemDTO:
        self.calls.append(item)
        if self.error is not None:
            raise self.error
        return ItemDTO(
            platform=item.platform,
            external_id=item.external_id,
            content_type=item.content_type,
            body_text=self.body_text,
            url=item.url,
        )


@pytest.mark.asyncio
async def test_provider_identity_merge_preserves_bookmarks_and_dedupes_subscriptions(
    db_session,
):
    from app.social.identity import bind_publisher_identity, ensure_publisher_identity

    user = User(
        email=f"identity-merge-{uuid.uuid4().hex}@test.dev",
        password_hash=hash_password("x"),
    )
    canonical = SocialPublisher(
        platform="wechat",
        external_id=f"redfox-{uuid.uuid4().hex}",
        name="同一公众号",
        provider="redfox",
    )
    duplicate = SocialPublisher(
        platform="wechat",
        external_id=f"fakeid-{uuid.uuid4().hex}",
        name="同一公众号",
        provider="wechat_mp",
    )
    db_session.add_all([user, canonical, duplicate])
    await db_session.flush()
    await ensure_publisher_identity(
        db_session,
        canonical,
        provider="redfox",
        external_id=canonical.external_id,
    )
    wechat_identity = await ensure_publisher_identity(
        db_session,
        duplicate,
        provider="wechat_mp",
        external_id=duplicate.external_id,
    )
    item = SocialItem(
        publisher_id=duplicate.id,
        platform="wechat",
        external_id=f"merge-item-{uuid.uuid4().hex}",
        content_type="article",
        title="保留引用",
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add_all(
        [
            SocialSubscription(user_id=user.id, publisher_id=canonical.id),
            SocialSubscription(user_id=user.id, publisher_id=duplicate.id),
            item,
        ]
    )
    await db_session.flush()
    bookmark = ContentBookmark(user_id=user.id, item_id=item.id)
    db_session.add(bookmark)
    await db_session.commit()
    item_id = item.id
    bookmark_id = bookmark.id
    duplicate_id = duplicate.id

    merged, rebound = await bind_publisher_identity(
        db_session,
        canonical,
        provider="wechat_mp",
        external_id=wechat_identity.external_id,
    )
    await db_session.commit()

    assert merged.id == canonical.id
    assert rebound.publisher_id == canonical.id
    assert await db_session.get(SocialPublisher, duplicate_id) is None
    moved_item = await db_session.get(SocialItem, item_id)
    assert moved_item.publisher_id == canonical.id
    preserved = await db_session.get(ContentBookmark, bookmark_id)
    assert preserved.item_id == item_id
    subscriptions = (
        await db_session.execute(
            select(SocialSubscription).where(SocialSubscription.user_id == user.id)
        )
    ).scalars().all()
    assert [subscription.publisher_id for subscription in subscriptions] == [canonical.id]


@pytest.mark.asyncio
async def test_wechat_identity_requires_one_normalized_exact_match(db_session):
    from app.social.identity import ensure_publisher_identity, resolve_wechat_identity

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"redfox-{uuid.uuid4().hex}",
        name="Ｒｕｉｑｉｎ  袁锐钦",
        provider="redfox",
    )
    db_session.add(publisher)
    await db_session.flush()
    await ensure_publisher_identity(
        db_session,
        publisher,
        provider="redfox",
        external_id=publisher.external_id,
    )

    state, identity = await resolve_wechat_identity(
        db_session,
        publisher,
        [
            {"fakeid": "fake-a", "nickname": "Ruiqin 袁锐钦"},
            {"fakeid": "fake-b", "nickname": "Ruiqin 袁锐钦"},
        ],
    )
    assert state == "identity_ambiguous"
    assert identity is None

    state, identity = await resolve_wechat_identity(
        db_session,
        publisher,
        [{"fakeid": "fake-a", "nickname": "Ruiqin 袁锐钦"}],
    )
    assert state == "queued"
    assert identity.provider == "wechat_mp"
    assert identity.external_id == "fake-a"


@pytest.mark.asyncio
async def test_wechat_fallback_capacity_waits_then_promotes(db_session):
    from types import SimpleNamespace

    from app.social.identity import ensure_publisher_identity
    from app.social.refresh import _claim_fallback_capacity

    user = User(
        email=f"capacity-{uuid.uuid4().hex}@test.dev",
        password_hash=hash_password("x"),
    )
    active = SocialPublisher(
        platform="wechat", external_id=f"active-{uuid.uuid4().hex}", name="Active"
    )
    waiting = SocialPublisher(
        platform="wechat", external_id=f"waiting-{uuid.uuid4().hex}", name="Waiting"
    )
    db_session.add_all([user, active, waiting])
    await db_session.flush()
    active_identity = await ensure_publisher_identity(
        db_session,
        active,
        provider="wechat_mp",
        external_id=active.external_id,
    )
    redfox_identity = await ensure_publisher_identity(
        db_session,
        waiting,
        provider="redfox",
        external_id=waiting.external_id,
        status="coverage_gap",
    )
    waiting_identity = await ensure_publisher_identity(
        db_session,
        waiting,
        provider="wechat_mp",
        external_id=f"waiting-fakeid-{uuid.uuid4().hex}",
    )
    active_subscription = SocialSubscription(
        user_id=user.id, publisher_id=active.id, enabled=True
    )
    db_session.add_all(
        [
            active_subscription,
            SocialSubscription(user_id=user.id, publisher_id=waiting.id, enabled=True),
        ]
    )
    await db_session.flush()

    other_active_count = await db_session.scalar(
        select(func.count(func.distinct(SocialPublisherIdentity.publisher_id)))
        .join(
            SocialSubscription,
            SocialSubscription.publisher_id == SocialPublisherIdentity.publisher_id,
        )
        .where(
            SocialPublisherIdentity.provider == "wechat_mp",
            SocialPublisherIdentity.status == "active",
            SocialPublisherIdentity.publisher_id != waiting.id,
            SocialSubscription.enabled.is_(True),
        )
    )
    settings = SimpleNamespace(
        social_wechat_fallback_capacity=int(other_active_count)
    )
    assert not await _claim_fallback_capacity(
        db_session,
        waiting,
        settings,
        redfox_identity,
        fallback_identity=waiting_identity,
    )
    assert waiting.sync_state == "waiting_capacity"
    assert waiting_identity.status == "waiting_capacity"
    assert waiting_identity.waiting_since_at is not None
    assert redfox_identity.status == "coverage_gap"

    active_subscription.enabled = False
    active_identity.status = "disabled"
    await db_session.flush()
    assert await _claim_fallback_capacity(
        db_session,
        waiting,
        settings,
        redfox_identity,
        fallback_identity=waiting_identity,
    )
    assert waiting_identity.status == "active"


@pytest.mark.asyncio
async def test_only_typed_redfox_coverage_gap_enters_fallback_routing(
    db_session, monkeypatch
):
    from types import SimpleNamespace

    from app.social import refresh as refresh_module
    from app.social.identity import ensure_publisher_identity
    from app.social.providers.base import ProviderCoverageGap

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"typed-gap-{uuid.uuid4().hex}",
        name="Typed Gap",
        provider="redfox",
    )
    db_session.add(publisher)
    await db_session.flush()
    await ensure_publisher_identity(
        db_session,
        publisher,
        provider="redfox",
        external_id=publisher.external_id,
    )

    async def coverage_gap(*args, **kwargs):
        raise ProviderCoverageGap("redfox", "wechat", "优质库暂未收录")

    monkeypatch.setattr(refresh_module, "_refresh_redfox", coverage_gap)
    count = await refresh_module.refresh_publisher(
        db_session,
        publisher,
        SimpleNamespace(social_wechat_fallback_enabled=False),
    )
    assert count == 0
    assert publisher.sync_state == "upstream_error"
    assert publisher.last_sync_error_code == "provider_coverage_gap"

    transient_publisher = SocialPublisher(
        platform="wechat",
        external_id=f"transient-{uuid.uuid4().hex}",
        name="Transient",
        provider="redfox",
    )
    db_session.add(transient_publisher)
    await db_session.flush()
    await ensure_publisher_identity(
        db_session,
        transient_publisher,
        provider="redfox",
        external_id=transient_publisher.external_id,
    )

    async def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("temporary")

    monkeypatch.setattr(refresh_module, "_refresh_redfox", timeout)
    with pytest.raises(httpx.ReadTimeout):
        await refresh_module.refresh_publisher(
            db_session,
            transient_publisher,
            SimpleNamespace(social_wechat_fallback_enabled=True),
        )
    wechat_identity = await db_session.scalar(
        select(SocialPublisherIdentity).where(
            SocialPublisherIdentity.publisher_id == transient_publisher.id,
            SocialPublisherIdentity.provider == "wechat_mp",
        )
    )
    assert wechat_identity is None

    # A transient RedFox reprobe must not *create* fallback, but it also must
    # not block a WeChat identity that was already bound by an earlier typed
    # coverage gap.
    user = User(
        email=f"established-fallback-{uuid.uuid4().hex}@test.dev",
        password_hash=hash_password("x"),
    )
    established = SocialPublisher(
        platform="wechat",
        external_id=f"established-{uuid.uuid4().hex}",
        name="Established",
        provider="redfox",
    )
    db_session.add_all([user, established])
    await db_session.flush()
    await ensure_publisher_identity(
        db_session,
        established,
        provider="redfox",
        external_id=established.external_id,
        status="coverage_gap",
    )
    await ensure_publisher_identity(
        db_session,
        established,
        provider="wechat_mp",
        external_id=f"established-fakeid-{uuid.uuid4().hex}",
    )
    db_session.add(
        SocialSubscription(user_id=user.id, publisher_id=established.id)
    )
    await db_session.flush()
    fallback_calls = []

    async def established_fallback(*args, **kwargs):
        fallback_calls.append(args[1].id)
        return 7

    monkeypatch.setattr(refresh_module, "_refresh_wechat_mp", established_fallback)
    assert await refresh_module.refresh_publisher(
        db_session,
        established,
        SimpleNamespace(
            social_wechat_fallback_enabled=True,
            social_wechat_fallback_capacity=100,
            redfox_api_key="test",
        ),
    ) == 7
    assert fallback_calls == [established.id]


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
    assert (
        await db_session.scalar(
            select(func.count(SocialItemMetricSnapshot.id)).where(
                SocialItemMetricSnapshot.item_id == item.id
            )
        )
        == 2
    )
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
async def test_wechat_detail_lazily_fetches_and_caches_body(
    client, db_session, registered_user, monkeypatch
):
    from app.social import feed_router

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"lazy-body-{uuid.uuid4().hex}",
        name="Lazy Body Publisher",
        provider="redfox",
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"lazy-body-item-{uuid.uuid4().hex}",
        content_type="article",
        title="需要懒抓的文章",
        digest="列表摘要",
        url="https://mp.weixin.qq.com/s/lazy-body",
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add_all(
        [item, SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id)]
    )
    await db_session.commit()

    provider = _WechatDetailProvider("第一段。\n第二段。")
    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: provider)
    response = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))
    assert response.status_code == 200
    assert response.json()["body_text"] == "第一段。\n第二段。"
    assert response.json()["digest"] == "列表摘要"
    assert response.json()["url"] == item.url

    await db_session.refresh(item)
    assert item.body_fetched_at is not None
    assert item.body_expires_at is not None
    assert item.body_expires_at - item.body_fetched_at == dt.timedelta(days=90)
    assert item.content_hash == compute_content_hash(item.title, item.body_text, item.url)

    cached = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))
    assert cached.status_code == 200
    assert cached.json()["body_text"] == "第一段。\n第二段。"
    assert [call.url for call in provider.calls] == [item.url]


@pytest.mark.asyncio
async def test_wechat_detail_honors_extended_explicit_cache_expiry(
    client, db_session, registered_user, monkeypatch
):
    """Unbookmarking extends expiry from now even when the original fetch is old."""
    from app.social import feed_router

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"extended-expiry-{uuid.uuid4().hex}",
        name="Extended Expiry Publisher",
    )
    db_session.add(publisher)
    await db_session.flush()
    now = dt.datetime.now(dt.UTC)
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"extended-expiry-item-{uuid.uuid4().hex}",
        content_type="article",
        title="取消收藏后仍有效的缓存",
        body_text="已有正文",
        url="https://mp.weixin.qq.com/s/extended-expiry",
        published_at=now,
        body_fetched_at=now - dt.timedelta(days=91),
        body_expires_at=now + dt.timedelta(days=90),
    )
    db_session.add_all(
        [item, SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id)]
    )
    await db_session.commit()

    provider = _WechatDetailProvider(
        error=AssertionError("valid explicit cache expiry must prevent an upstream request")
    )
    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: provider)
    response = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))
    assert response.status_code == 200
    assert response.json()["body_text"] == "已有正文"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_wechat_detail_normalizes_valid_cached_body_without_upstream_request(
    client, db_session, registered_user, monkeypatch
):
    from app.social import feed_router

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"cached-format-{uuid.uuid4().hex}",
        name="Cached Format Publisher",
    )
    db_session.add(publisher)
    await db_session.flush()
    now = dt.datetime.now(dt.UTC)
    malformed_body = "第一段。       第二段第一行。\n第二段第二行。"
    expected_body = "第一段。\n\n第二段第一行。\n第二段第二行。"
    fetched_at = now - dt.timedelta(days=1)
    expires_at = now + dt.timedelta(days=89)
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"cached-format-item-{uuid.uuid4().hex}",
        content_type="article",
        title="已缓存的格式错误正文",
        body_text=malformed_body,
        url="https://mp.weixin.qq.com/s/cached-format",
        published_at=now,
        body_fetched_at=fetched_at,
        body_expires_at=expires_at,
        content_hash=compute_content_hash(
            "已缓存的格式错误正文",
            malformed_body,
            "https://mp.weixin.qq.com/s/cached-format",
        ),
    )
    db_session.add_all(
        [item, SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id)]
    )
    await db_session.commit()

    provider = _WechatDetailProvider(
        error=AssertionError("valid cached body normalization must not request upstream")
    )
    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: provider)

    response = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))

    assert response.status_code == 200
    assert response.json()["body_text"] == expected_body
    assert provider.calls == []
    await db_session.refresh(item)
    assert item.body_text == expected_body
    assert item.body_fetched_at == fetched_at
    assert item.body_expires_at == expires_at
    assert item.content_hash == compute_content_hash(item.title, expected_body, item.url)


@pytest.mark.asyncio
async def test_expired_wechat_body_failure_degrades_both_detail_routes_without_deleting_stale_text(
    client, db_session, registered_user, monkeypatch
):
    from app.aihot import router as aihot_router
    from app.social import feed_router

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"expired-body-{uuid.uuid4().hex}",
        name="Expired Body Publisher",
    )
    db_session.add(publisher)
    await db_session.flush()
    now = dt.datetime.now(dt.UTC)
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"expired-body-item-{uuid.uuid4().hex}",
        content_type="article",
        title="刷新失败的过期正文",
        body_text="过期正文不应出现在响应中",
        digest="摘要仍然可见",
        url="https://mp.weixin.qq.com/s/expired-body",
        published_at=now,
        body_fetched_at=now - dt.timedelta(days=91),
        body_expires_at=now - dt.timedelta(days=1),
    )
    source = HotSourceMembership(
        publisher_id=publisher.id,
        provider="redfox",
        platform="wechat",
        category="market",
        added_by=registered_user.id,
    )
    db_session.add_all(
        [
            item,
            source,
            SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id),
        ]
    )
    await db_session.flush()
    db_session.add(HotItemSource(item_id=item.id, source_id=source.id))
    await db_session.commit()

    provider = _WechatDetailProvider(error=httpx.ConnectError("upstream unavailable"))
    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: provider)
    monkeypatch.setattr(aihot_router, "get_provider", lambda platform, settings: provider)
    headers = _auth(registered_user)
    social_response = await client.get(f"/api/social/items/{item.id}", headers=headers)
    hot_response = await client.get(f"/api/aihot/{item.id}", headers=headers)

    assert social_response.status_code == 200
    assert social_response.json()["body_text"] is None
    assert social_response.json()["digest"] == "摘要仍然可见"
    assert hot_response.status_code == 200
    assert hot_response.json()["body_text"] is None
    assert hot_response.json()["digest"] == "摘要仍然可见"
    assert [call.url for call in provider.calls] == [item.url, item.url]
    await db_session.refresh(item)
    assert item.body_text == "过期正文不应出现在响应中"
    assert item.body_fetched_at == now - dt.timedelta(days=91)
    assert item.body_expires_at == now - dt.timedelta(days=1)
    # The session-scoped PostgreSQL fixture intentionally persists across tests;
    # leave this regression row outside the global cleanup test's expired set.
    item.body_expires_at = now + dt.timedelta(days=90)
    await db_session.commit()


@pytest.mark.asyncio
async def test_bookmarked_wechat_body_is_cached_without_expiry(
    client, db_session, registered_user, monkeypatch
):
    from app.social import feed_router

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"bookmarked-body-{uuid.uuid4().hex}",
        name="Bookmarked Body Publisher",
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"bookmarked-body-item-{uuid.uuid4().hex}",
        content_type="article",
        title="已收藏文章",
        url="https://mp.weixin.qq.com/s/bookmarked-body",
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add_all(
        [
            SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id),
            ContentBookmark(user_id=registered_user.id, item_id=item.id),
        ]
    )
    await db_session.commit()

    provider = _WechatDetailProvider("长期保留正文")
    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: provider)
    response = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))
    assert response.status_code == 200
    assert response.json()["body_text"] == "长期保留正文"
    await db_session.refresh(item)
    assert item.body_fetched_at is not None
    assert item.body_expires_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        None,
        "http://mp.weixin.qq.com/s/not-https",
        "https://mp.weixin.qq.com.evil.test/s/wrong-host",
        "https://mp.weixin.qq.com@evil.test/s/user-info",
        "https://mp.weixin.qq.com:444/s/wrong-port",
        " https://mp.weixin.qq.com/s/leading-space",
        "https://mp.weixin.qq.com/s/control\ncharacter",
    ],
)
async def test_wechat_detail_rejects_untrusted_source_urls_without_request(
    client, db_session, registered_user, monkeypatch, url
):
    from app.social import feed_router

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"untrusted-body-{uuid.uuid4().hex}",
        name="Untrusted Body Publisher",
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"untrusted-body-item-{uuid.uuid4().hex}",
        content_type="article",
        title="不可信链接",
        digest="仍然可见",
        url=url,
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add_all(
        [item, SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id)]
    )
    await db_session.commit()

    provider = _WechatDetailProvider("不应使用")
    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: provider)
    response = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))
    assert response.status_code == 200
    assert response.json()["body_text"] is None
    assert response.json()["digest"] == "仍然可见"
    assert response.json()["url"] == url
    assert provider.calls == []
    await db_session.refresh(item)
    assert item.body_fetched_at is None
    assert item.body_expires_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["empty", "network_error"])
async def test_wechat_detail_fetch_failure_is_not_cached(
    client, db_session, registered_user, monkeypatch, outcome
):
    from app.social import feed_router

    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"failed-body-{uuid.uuid4().hex}",
        name="Failed Body Publisher",
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="wechat",
        external_id=f"failed-body-item-{uuid.uuid4().hex}",
        content_type="article",
        title="抓取失败文章",
        digest="失败时仍显示摘要",
        url="https://mp.weixin.qq.com/s/fetch-failure",
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add_all(
        [item, SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id)]
    )
    await db_session.commit()

    provider = _WechatDetailProvider(
        body_text="" if outcome == "empty" else None,
        error=httpx.ConnectError("upstream unavailable") if outcome == "network_error" else None,
    )
    monkeypatch.setattr(feed_router, "get_provider", lambda platform, settings: provider)
    for _ in range(2):
        response = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))
        assert response.status_code == 200
        assert response.json()["body_text"] is None
        assert response.json()["digest"] == "失败时仍显示摘要"
    assert [call.url for call in provider.calls] == [item.url, item.url]
    await db_session.refresh(item)
    assert item.body_text is None
    assert item.body_fetched_at is None
    assert item.body_expires_at is None


@pytest.mark.asyncio
async def test_non_wechat_detail_preserves_list_complete_body_without_detail_provider(
    client, db_session, registered_user
):
    publisher = SocialPublisher(
        platform="weibo",
        external_id=f"list-complete-{uuid.uuid4().hex}",
        name="List Complete Publisher",
        provider="weibo",
    )
    db_session.add(publisher)
    await db_session.flush()
    item = SocialItem(
        publisher_id=publisher.id,
        platform="weibo",
        external_id=f"list-complete-item-{uuid.uuid4().hex}",
        content_type="post",
        title=None,
        body_text="列表已包含的微博正文",
        url="https://weibo.com/example/status",
        published_at=dt.datetime.now(dt.UTC),
    )
    db_session.add_all(
        [item, SocialSubscription(user_id=registered_user.id, publisher_id=publisher.id)]
    )
    await db_session.commit()

    response = await client.get(f"/api/social/items/{item.id}", headers=_auth(registered_user))

    assert response.status_code == 200
    assert response.json()["body_text"] == "列表已包含的微博正文"


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

    first = await client.post(
        f"/api/social/publishers/{publisher.id}/refresh",
        headers=_auth(registered_user),
    )
    queued_identity = await db_session.scalar(
        select(SocialPublisherIdentity).where(
            SocialPublisherIdentity.publisher_id == publisher.id
        )
    )
    first_requested_at = queued_identity.requested_at
    assert first_requested_at is not None
    second = await client.post(
        f"/api/social/publishers/{publisher.id}/refresh",
        headers={"Authorization": f"Bearer {create_access_token(str(second_user.id))}"},
    )
    assert first.status_code == 202
    assert first.json()["state"] == "queued"
    assert second.status_code == 202
    assert second.json()["state"] == "queued"
    await db_session.refresh(queued_identity)
    assert queued_identity.requested_at == first_requested_at
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
async def test_dispatcher_rechecks_due_state_after_advisory_lock(
    db_session, monkeypatch
):
    from types import SimpleNamespace

    from app.social import refresh as refresh_module

    future = dt.datetime.now(dt.UTC) + dt.timedelta(days=7)
    existing_publishers = (
        await db_session.execute(select(SocialPublisher))
    ).scalars().all()
    for existing in existing_publishers:
        existing.next_sync_at = future
    user = User(
        email=f"dispatcher-race-{uuid.uuid4().hex}@test.dev",
        password_hash=hash_password("x"),
    )
    publisher = SocialPublisher(
        platform="wechat",
        external_id=f"dispatcher-race-{uuid.uuid4().hex}",
        name="Dispatcher Race",
        provider="redfox",
        next_sync_at=None,
    )
    db_session.add_all([user, publisher])
    await db_session.flush()
    db_session.add(
        SocialSubscription(user_id=user.id, publisher_id=publisher.id)
    )
    await db_session.commit()

    original_refresh = db_session.refresh

    async def simulate_other_instance_commit(
        instance, attribute_names=None, **kwargs
    ):
        await original_refresh(
            instance, attribute_names=attribute_names, **kwargs
        )
        if instance.id == publisher.id:
            instance.next_sync_at = future

    upstream_calls = []

    async def unexpected_upstream(*args, **kwargs):
        upstream_calls.append(args[1].id)
        return 1

    monkeypatch.setattr(db_session, "refresh", simulate_other_instance_commit)
    monkeypatch.setattr(refresh_module, "refresh_publisher", unexpected_upstream)

    stats = await refresh_module.refresh_subscribed_publishers(
        db_session, SimpleNamespace()
    )

    assert upstream_calls == []
    assert stats["skipped_not_due"] == 1


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
    db_session.add_all([post, WeiboSubscription(user_id=registered_user.id, account_id=account.id)])
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
        (
            await db_session.execute(
                select(SocialSubscription).where(
                    SocialSubscription.user_id == registered_user.id,
                    SocialSubscription.publisher_id == publisher.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(subscriptions) == 1
